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
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

import certifi


GITHUB_REPOSITORY = "Altitude-Unknown/RC-Airplane"
LATEST_RELEASE_URL = f"https://api.github.com/repos/{GITHUB_REPOSITORY}/releases/latest"
MANIFEST_ASSET_NAME = "transmitter-firmware-manifest.json"
USER_AGENT = "Altitude-Unknown-RC-Configurator/firmware-updater"
TARGETS = ("samd21", "esp32c3", "receiver_samd21")
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
        if target == "receiver_samd21" and board.get("serial_asset"):
            serial_name = board["serial_asset"]
            serial_checksum = str(board.get("serial_sha256", "")).lower()
            if serial_name not in assets or len(serial_checksum) != 64 or \
                    any(c not in string.hexdigits for c in serial_checksum):
                raise FirmwareUpdateError("The receiver serial firmware entry is incomplete or invalid.")
            board["serial_download_url"] = assets[serial_name]
    return {
        "tag": release.get("tag_name", "unknown"),
        "name": release.get("name") or release.get("tag_name", "Latest release"),
        "published_at": release.get("published_at", ""),
        "html_url": release.get("html_url", ""),
        "manifest": manifest,
    }


def download_firmware(release_info, target, destination=None, timeout=60, serial_image=False):
    """Download one image and reject it unless its SHA-256 matches."""
    if target not in TARGETS:
        raise FirmwareUpdateError(f"Unknown firmware target: {target}")
    board = release_info["manifest"]["boards"][target]
    asset_key = "serial_asset" if serial_image else "asset"
    url_key = "serial_download_url" if serial_image else "download_url"
    checksum_key = "serial_sha256" if serial_image else "sha256"
    if asset_key not in board or url_key not in board:
        raise FirmwareUpdateError(f"The release has no {'serial' if serial_image else target} image.")
    suffix = Path(board[asset_key]).suffix
    if destination is None:
        fd, destination = tempfile.mkstemp(prefix=f"altitude-unknown-{target}-", suffix=suffix)
        os.close(fd)
    destination = Path(destination)
    request = urllib.request.Request(board[url_key], headers={"User-Agent": USER_AGENT})
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
    if digest.hexdigest().lower() != board[checksum_key].lower():
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
        "The SAMD21 UF2 drive did not appear automatically. Double-tap RESET and try again."
    )


def request_samd_bootloader(port):
    """Ask a running SAMD21 application to reboot into UF2 via 1200-baud touch."""
    if not port:
        raise FirmwareUpdateError("Select the transmitter M0 or receiver USB port first.")
    try:
        import serial
        connection = serial.Serial(port=port, baudrate=1200, timeout=0.25)
        # Match Arduino CLI's touch1200 operation: open at 1200 baud and close.
        # Closing drops the control lines through the OS serial driver. Some
        # older SAM-BA receivers do not react correctly if DTR is forced low
        # explicitly before the close.
        connection.close()
    except Exception as exc:
        raise FirmwareUpdateError(
            f"Could not request automatic SAMD21 bootloader entry on {port}: {exc}"
        ) from exc


def enter_samd_uf2(port, timeout=20, poll_interval=0.25):
    """Perform a 1200-baud touch and return the newly mounted UF2 volume."""
    before = uf2_mounts()
    request_samd_bootloader(port)
    return wait_for_new_uf2_mount(before, timeout=timeout, poll_interval=poll_interval)


def receiver_uf2_mounts():
    """Return mounted UF2 volumes that identify as an Altitude receiver."""
    matches = []
    for mount in uf2_mounts():
        try:
            info = (Path(mount) / "INFO_UF2.TXT").read_text(errors="replace").lower()
        except OSError:
            continue
        if "rx m0" in info or "receiver" in info or "altitude-rc-rx" in info:
            matches.append(Path(mount))
    return matches


def enter_receiver_uf2(port, timeout=8):
    """Enter a newer receiver's UF2 bootloader, or reuse it if already mounted."""
    mounted = receiver_uf2_mounts()
    if len(mounted) == 1:
        return mounted[0]
    return enter_samd_uf2(port, timeout=timeout)


def flash_samd_uf2(image, mount, destination_name="ALTITUDE.UF2"):
    image = Path(image)
    mount = Path(mount)
    if image.suffix.lower() != ".uf2" or not (mount / "INFO_UF2.TXT").is_file():
        raise FirmwareUpdateError("The selected file or drive is not a valid UF2 update target.")
    try:
        shutil.copyfile(image, mount / destination_name)
    except Exception as exc:
        raise FirmwareUpdateError(f"Could not copy firmware to the SAMD21: {exc}") from exc


def _bossac_path():
    name = "bossac.exe" if os.name == "nt" else "bossac"
    bundled = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)) / "tools" / name
    if bundled.is_file():
        return bundled
    found = shutil.which(name)
    if found:
        return Path(found)
    roots = ([Path.home() / "Library/Arduino15"] if sys.platform == "darwin" else
             [Path.home() / ".arduino15", Path(os.environ.get("LOCALAPPDATA", "")) / "Arduino15"])
    for root in roots:
        matches = list(root.glob(f"packages/adafruit/tools/bossac/*/{name}"))
        if matches:
            return matches[-1]
    raise FirmwareUpdateError("Receiver serial flashing support (BOSSA) is missing from this installation.")


def flash_receiver_samba(image, port):
    """Flash an older Receiver V4 SAM-BA bootloader without a physical reset."""
    image = Path(image)
    if image.suffix.lower() != ".bin":
        raise FirmwareUpdateError("Receiver SAM-BA flashing requires the verified .bin image.")
    # PySerial's 1200-baud control-line behavior is inconsistent with this
    # original 2016 SAM-BA board on macOS. Current receiver firmware therefore
    # exposes a guarded command and performs the SAMD core's normal reset while
    # this connection remains open. Older firmware retains touch1200 fallback.
    commanded = False
    try:
        import serial
        connection = serial.Serial(port=port, baudrate=115200, timeout=1.0)
        try:
            time.sleep(0.5)
            connection.reset_input_buffer()
            connection.write(b"BOOTLOADER\n")
            connection.flush()
            commanded = b"OK BOOTLOADER" in connection.readline()
            if commanded:
                time.sleep(0.75)
        finally:
            connection.close()
    except Exception:
        commanded = False
    if not commanded:
        request_samd_bootloader(port)
    def bossac_port_name(candidate):
        # BOSSA expects macOS's actual basename (for example
        # ``cu.usbmodem1101``), including the ``cu.`` prefix.
        return Path(candidate).name

    deadline = time.monotonic() + 15
    result = None
    first_attempt = True
    while time.monotonic() < deadline:
        if not first_attempt:
            time.sleep(0.1)
        first_attempt = False
        candidates = [port]
        try:
            import serial.tools.list_ports
            candidates += [item.device for item in serial.tools.list_ports.comports()
                           if "usbmodem" in item.device.lower() and item.device not in candidates]
        except Exception:
            pass
        for candidate in candidates:
            command = [str(_bossac_path()), "-i", "-d",
                       f"--port={bossac_port_name(candidate)}", "-U", "-i",
                       "--offset=0x2000", "-e", "-w", "-v", str(image), "-R"]
            try:
                result = subprocess.run(command, capture_output=True, text=True, timeout=120)
            except Exception as exc:
                raise FirmwareUpdateError(f"Receiver serial flashing could not start: {exc}") from exc
            if result.returncode == 0:
                return
            detail = (result.stderr or result.stdout).strip().lower()
            if "no device found" not in detail and "failed to connect" not in detail:
                break
    detail = ((result.stderr or result.stdout).strip() if result else "bootloader did not respond")
    raise FirmwareUpdateError(f"Receiver serial flashing failed: {detail}")


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
