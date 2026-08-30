"""Download and flash signed-off transmitter firmware release assets.

The updater deliberately keeps hardware operations separate from Tkinter so
the release parser, checksum checks, and drive detection can be unit tested.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import ssl
import string
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

import certifi


GITHUB_REPOSITORY = "Altitude-Unknown/RC-Airplane"
LATEST_RELEASE_URL = f"https://api.github.com/repos/{GITHUB_REPOSITORY}/releases/latest"
MANIFEST_ASSET_NAME = "transmitter-firmware-manifest.json"
USER_AGENT = "Walach-Transmitter-Configurator/firmware-updater"
TARGETS = ("samd21", "esp32c3")
TLS_CONTEXT = ssl.create_default_context(cafile=certifi.where())


class FirmwareUpdateError(RuntimeError):
    pass


def _request_json(url, timeout=20):
    request = urllib.request.Request(
        url, headers={"Accept": "application/vnd.github+json", "User-Agent": USER_AGENT}
    )
    with urllib.request.urlopen(request, timeout=timeout, context=TLS_CONTEXT) as response:
        return json.load(response)


def _asset_map(release):
    return {
        asset.get("name"): asset.get("browser_download_url")
        for asset in release.get("assets", [])
        if asset.get("name") and asset.get("browser_download_url")
    }


def fetch_latest_firmware(timeout=20):
    """Return validated release metadata and firmware manifest."""
    try:
        release = _request_json(LATEST_RELEASE_URL, timeout)
        assets = _asset_map(release)
        manifest_url = assets.get(MANIFEST_ASSET_NAME)
        if not manifest_url:
            raise FirmwareUpdateError(
                "The latest release does not contain transmitter firmware. "
                "Install a newer configurator release or try again later."
            )
        manifest = _request_json(manifest_url, timeout)
    except FirmwareUpdateError:
        raise
    except Exception as exc:
        raise FirmwareUpdateError(f"Could not check GitHub for firmware: {exc}") from exc

    if manifest.get("schema") != 1:
        raise FirmwareUpdateError("The release uses an unsupported firmware manifest format.")
    boards = manifest.get("boards")
    if not isinstance(boards, dict):
        raise FirmwareUpdateError("The firmware manifest has no board definitions.")
    for target in TARGETS:
        board = boards.get(target)
        if not isinstance(board, dict):
            raise FirmwareUpdateError(f"The release is missing {target} firmware.")
        name = board.get("asset")
        checksum = str(board.get("sha256", "")).lower()
        if name not in assets or len(checksum) != 64 or any(c not in string.hexdigits for c in checksum):
            raise FirmwareUpdateError(f"The {target} firmware entry is incomplete or invalid.")
        board["download_url"] = assets[name]
    return {
        "tag": release.get("tag_name", "unknown"),
        "name": release.get("name") or release.get("tag_name", "Latest release"),
        "published_at": release.get("published_at", ""),
        "html_url": release.get("html_url", ""),
        "manifest": manifest,
    }


def download_firmware(release_info, target, destination=None, timeout=60):
    """Download one image and reject it unless its SHA-256 matches."""
    if target not in TARGETS:
        raise FirmwareUpdateError(f"Unknown firmware target: {target}")
    board = release_info["manifest"]["boards"][target]
    suffix = Path(board["asset"]).suffix
    if destination is None:
        fd, destination = tempfile.mkstemp(prefix=f"walach-{target}-", suffix=suffix)
        os.close(fd)
    destination = Path(destination)
    request = urllib.request.Request(board["download_url"], headers={"User-Agent": USER_AGENT})
    try:
        digest = hashlib.sha256()
        with urllib.request.urlopen(request, timeout=timeout, context=TLS_CONTEXT) as response, destination.open("wb") as output:
            while True:
                chunk = response.read(128 * 1024)
                if not chunk:
                    break
                output.write(chunk)
                digest.update(chunk)
    except Exception as exc:
        destination.unlink(missing_ok=True)
        raise FirmwareUpdateError(f"Firmware download failed: {exc}") from exc
    if digest.hexdigest().lower() != board["sha256"].lower():
        destination.unlink(missing_ok=True)
        raise FirmwareUpdateError("Firmware checksum did not match. Nothing was flashed.")
    return destination


def uf2_mounts():
    """Find mounted UF2 bootloader volumes on macOS, Windows, and Linux."""
    candidates = []
    if sys.platform == "darwin":
        candidates.extend(Path("/Volumes").glob("*"))
    elif os.name == "nt":
        candidates.extend(Path(f"{letter}:/") for letter in string.ascii_uppercase)
    else:
        user = os.environ.get("USER", "")
        candidates.extend(Path("/media").glob("*/*"))
        candidates.extend(Path("/run/media").glob("*/*"))
        if user:
            candidates.extend((Path("/media") / user).glob("*"))
            candidates.extend((Path("/run/media") / user).glob("*"))
    found = []
    for path in candidates:
        try:
            if path.is_dir() and (path / "INFO_UF2.TXT").is_file():
                found.append(path)
        except OSError:
            pass
    return found


def wait_for_new_uf2_mount(previous=(), timeout=90, poll_interval=0.5):
    previous = {str(Path(item)) for item in previous}
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        mounts = uf2_mounts()
        new_mounts = [mount for mount in mounts if str(mount) not in previous]
        if new_mounts:
            return new_mounts[0]
        if mounts and not previous:
            return mounts[0]
        time.sleep(poll_interval)
    raise FirmwareUpdateError(
        "The SAMD21 UF2 drive did not appear. Check the M0 USB cable and double-tap RESET again."
    )


def flash_samd_uf2(image, mount):
    image = Path(image)
    mount = Path(mount)
    if image.suffix.lower() != ".uf2" or not (mount / "INFO_UF2.TXT").is_file():
        raise FirmwareUpdateError("The selected file or drive is not a valid UF2 update target.")
    try:
        shutil.copyfile(image, mount / "WALACH_TX.UF2")
    except Exception as exc:
        raise FirmwareUpdateError(f"Could not copy firmware to the SAMD21: {exc}") from exc


def flash_esp32(image, port, offset="0x0", progress=None):
    """Flash a merged ESP32-C3 image through esptool's supported CLI entry point."""
    if not port:
        raise FirmwareUpdateError("Select the ESP32-C3 USB port first.")
    try:
        import esptool
    except ImportError as exc:
        raise FirmwareUpdateError(
            "ESP32 flashing support is missing. Reinstall the configurator or run 'pip install esptool'."
        ) from exc
    args = [
        "--chip", "esp32c3", "--port", port, "--baud", "460800",
        "--before", "default-reset", "--after", "hard-reset",
        "write-flash", "--flash-mode", "dio", offset, str(image),
    ]
    if progress:
        progress("Connecting to the ESP32-C3 bootloader…")
    try:
        esptool.main(args)
    except SystemExit as exc:
        if exc.code not in (None, 0):
            raise FirmwareUpdateError(f"ESP32 flashing failed (esptool exit {exc.code}).") from exc
    except Exception as exc:
        raise FirmwareUpdateError(f"ESP32 flashing failed: {exc}") from exc
