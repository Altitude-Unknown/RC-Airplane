"""Download (or load from disk) and flash transmitter, receiver and flight controller firmware.

The updater deliberately keeps hardware operations separate from Tkinter so
the release parser, checksum checks, and drive detection can be unit tested.
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import re
import shutil
import ssl
import string
import struct
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
    # Flight controller firmware is optional so older releases still validate.
    flight_controllers = manifest.get("flight_controllers", [])
    if not isinstance(flight_controllers, list):
        raise FirmwareUpdateError("The flight controller firmware list is invalid.")
    for entry in flight_controllers:
        name = entry.get("asset") if isinstance(entry, dict) else None
        checksum = str(entry.get("sha256", "")).lower() if isinstance(entry, dict) else ""
        if not name or name not in assets or not isinstance(entry.get("board_id"), int) or \
                not entry.get("board") or len(checksum) != 64 or \
                any(c not in string.hexdigits for c in checksum):
            raise FirmwareUpdateError("A flight controller firmware entry is incomplete or invalid.")
        entry["download_url"] = assets[name]
    manifest["flight_controllers"] = flight_controllers
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
    return _download_verified(board[url_key], board[checksum_key], target,
                              Path(board[asset_key]).suffix, destination, timeout)


def download_flight_controller_firmware(release_info, timeout=60):
    """Download every released flight controller image; return {board_id: path}."""
    entries = release_info["manifest"].get("flight_controllers", [])
    if not entries:
        raise FirmwareUpdateError("This release has no flight controller firmware.")
    images = {}
    try:
        for entry in entries:
            images[entry["board_id"]] = _download_verified(
                entry["download_url"], entry["sha256"], "fc-" + entry["board"], ".apj", None, timeout)
    except Exception:
        for path in images.values():
            path.unlink(missing_ok=True)
        raise
    return images


def _download_verified(url, checksum, label, suffix, destination, timeout):
    if destination is None:
        fd, destination = tempfile.mkstemp(prefix=f"altitude-unknown-{label}-", suffix=suffix)
        os.close(fd)
    destination = Path(destination)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
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
    if digest.hexdigest().lower() != checksum.lower():
        destination.unlink(missing_ok=True)
        raise FirmwareUpdateError("Firmware checksum did not match. Nothing was flashed.")
    return destination


LOCAL_TARGETS = ("samd21", "esp32c3", "receiver_samd21", "flight_controller")
UF2_MAGIC_START0 = 0x0A324655
UF2_MAGIC_START1 = 0x9E5D5157
UF2_MAGIC_END = 0x0AB16F30
UF2_FLAG_NOT_MAIN_FLASH = 0x00000001
UF2_FLAG_FAMILY_ID = 0x00002000
SAMD21_FAMILY_ID = 0x68ED2B88
SAMD21_APP_START = 0x2000          # the UF2/SAM-BA bootloader occupies 0x0000-0x1FFF
SAMD21_FLASH_END = 0x40000         # 256 KiB SAMD21G18
SAMD21_SRAM = (0x20000000, 0x20008000)
ESP32C3_CHIP_ID = 5
ESP_PARTITION_TABLE_OFFSET = 0x8000


def _sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(128 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _check_samd21_uf2(data):
    if not data or len(data) % 512:
        raise FirmwareUpdateError("This is not a valid UF2 file (its size is not a whole number of blocks).")
    lowest = None
    for offset in range(0, len(data), 512):
        block = data[offset:offset + 512]
        start0, start1, flags, address, size, _, _, family = struct.unpack_from("<8I", block)
        (end,) = struct.unpack_from("<I", block, 508)
        if start0 != UF2_MAGIC_START0 or start1 != UF2_MAGIC_START1 or end != UF2_MAGIC_END:
            raise FirmwareUpdateError("This is not a valid UF2 file (bad block header).")
        if flags & UF2_FLAG_NOT_MAIN_FLASH:
            continue
        if flags & UF2_FLAG_FAMILY_ID and family != SAMD21_FAMILY_ID:
            raise FirmwareUpdateError("This UF2 file is built for a different chip family, not the SAMD21.")
        if address < SAMD21_APP_START or address + size > SAMD21_FLASH_END:
            raise FirmwareUpdateError(
                f"This UF2 file writes to 0x{address:X}, outside the SAMD21 application area "
                "(0x2000 onward). It could overwrite the bootloader, so it was rejected.")
        lowest = address if lowest is None else min(lowest, address)
    if lowest is None:
        raise FirmwareUpdateError("This UF2 file contains no flash data.")
    return f"UF2, {len(data) // 512} blocks from 0x{lowest:X}"


def _check_samd21_bin(data):
    """A raw SAM-BA image must be an ARM vector table linked at 0x2000."""
    if len(data) < 8 or len(data) > SAMD21_FLASH_END - SAMD21_APP_START:
        raise FirmwareUpdateError("This .bin file is the wrong size for a SAMD21 application.")
    stack = int.from_bytes(data[0:4], "little")
    reset = int.from_bytes(data[4:8], "little")
    if not (SAMD21_SRAM[0] < stack <= SAMD21_SRAM[1]) or not reset & 1 or \
            not (SAMD21_APP_START <= reset & ~1 < SAMD21_FLASH_END):
        raise FirmwareUpdateError(
            "This .bin file is not a SAMD21 application built to start at 0x2000. "
            "Use the receiver's compiled .bin (not a bootloader or merged image).")
    return f"SAM-BA binary, {len(data):,} bytes"


def _check_esp32c3_merged(data):
    if len(data) < ESP_PARTITION_TABLE_OFFSET + 2 or data[0] != 0xE9:
        raise FirmwareUpdateError(
            "This is not a merged ESP32-C3 image. Use the merged .bin that starts with the bootloader.")
    chip_id = int.from_bytes(data[12:14], "little")
    if chip_id != ESP32C3_CHIP_ID:
        raise FirmwareUpdateError(f"This ESP image is built for another chip (chip ID {chip_id}), not the ESP32-C3.")
    if data[ESP_PARTITION_TABLE_OFFSET:ESP_PARTITION_TABLE_OFFSET + 2] != b"\xAA\x50":
        raise FirmwareUpdateError(
            "This ESP32-C3 image has no partition table at 0x8000. It looks like an application-only "
            ".bin; flashing it at 0x0 would leave the transmitter unable to boot. Use the merged image.")
    return f"merged ESP32-C3 image, {len(data):,} bytes"


def validate_local_firmware(path, target):
    """Check a firmware file chosen from disk before anything is written.

    Returns a description including the file's SHA-256. Local files are never
    deleted by the updater.
    """
    if target not in LOCAL_TARGETS:
        raise FirmwareUpdateError(f"Unknown firmware target: {target}")
    path = Path(path)
    if not path.is_file():
        raise FirmwareUpdateError(f"Firmware file not found: {path}")
    suffix = path.suffix.lower()
    info = {"path": path, "name": path.name, "size": path.stat().st_size, "sha256": _sha256_file(path)}
    if target == "flight_controller":
        if suffix != ".apj":
            raise FirmwareUpdateError("Flight controller firmware must be an ArduPilot .apj file.")
        import ardupilot_uploader
        try:
            fw = ardupilot_uploader.firmware(str(path))
        except Exception as exc:
            raise FirmwareUpdateError(f"This .apj file could not be read: {exc}") from exc
        board_id = fw.property("board_id")
        if not isinstance(board_id, int):
            raise FirmwareUpdateError("This .apj file does not state which board it is built for.")
        board = fw.property("summary") or f"board {board_id}"
        info.update(format="apj", board_id=board_id, board=board,
                    summary=f"ArduPilot .apj for {board} (board ID {board_id})"
                    + (f", git {fw.property('git_identity')}" if fw.property("git_identity") else ""))
        return info
    data = path.read_bytes()
    if target == "esp32c3":
        if suffix != ".bin":
            raise FirmwareUpdateError("ESP32-C3 firmware must be a merged .bin image.")
        info.update(format="merged-bin", summary=_check_esp32c3_merged(data))
    elif suffix == ".uf2":
        info.update(format="uf2", summary=_check_samd21_uf2(data))
    elif suffix == ".bin" and target == "receiver_samd21":
        info.update(format="sam-ba-bin", summary=_check_samd21_bin(data))
    else:
        raise FirmwareUpdateError(
            "Transmitter M0 firmware must be a .uf2 file." if target == "samd21" else
            "Receiver firmware must be a .uf2 file (UF2 bootloader) or a .bin file (older SAM-BA bootloader).")
    return info


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


def _uf2_mounts_identifying_as(*keywords):
    """Return mounted UF2 volumes whose INFO_UF2.TXT contains any keyword."""
    matches = []
    for mount in uf2_mounts():
        try:
            info = (Path(mount) / "INFO_UF2.TXT").read_text(errors="replace").lower()
        except OSError:
            continue
        if any(keyword in info for keyword in keywords):
            matches.append(Path(mount))
    return matches


def receiver_uf2_mounts():
    """Return mounted UF2 volumes that identify as an Altitude receiver."""
    return _uf2_mounts_identifying_as("rx m0", "receiver", "altitude-rc-rx")


def transmitter_uf2_mounts():
    """Return mounted UF2 volumes that identify as an Altitude transmitter M0."""
    return _uf2_mounts_identifying_as("tx m0", "altitude-rc-tx")


def enter_transmitter_uf2(port, timeout=20):
    """Enter the transmitter M0's UF2 bootloader, or reuse it if already mounted.

    A board that has only just had its bootloader installed has no application
    to run, so it stays in the bootloader with RCTXBOOT already mounted. A
    1200-baud touch then produces no new drive, so reuse the one present.
    """
    mounted = transmitter_uf2_mounts()
    if len(mounted) == 1:
        return mounted[0]
    return enter_samd_uf2(port, timeout=timeout)


def wait_for_transmitter_uf2(previous=(), timeout=90, poll_interval=0.5):
    """Wait after a manual RESET double-tap for the transmitter's UF2 drive.

    The drive often remounts at the same path, which wait_for_new_uf2_mount
    would not count as new, so accept a single transmitter drive directly.
    """
    previous = {str(Path(item)) for item in previous}
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        mounted = transmitter_uf2_mounts()
        if len(mounted) == 1:
            return mounted[0]
        new_mounts = [mount for mount in uf2_mounts() if str(mount) not in previous]
        if new_mounts:
            return new_mounts[0]
        time.sleep(poll_interval)
    raise FirmwareUpdateError(
        "The transmitter's UF2 drive did not appear. Double-tap RESET and try again."
    )


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
    # Only the selected port, or a port that appears after the reset, may be
    # the receiver's bootloader. Never probe other devices (a flight
    # controller, the transmitter) with BOSSA.
    ports_before = _serial_port_devices()
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
        candidates = [port] + [device for device in _serial_port_devices(exclude_flight_controllers=True)
                               if device not in ports_before and device != port]
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


# ArduPilot's pid.codes USB IDs: 0x5741 for single-USB boards, 0x5740 for
# dual-USB boards. The application and its bootloader both use them.
ARDUPILOT_USB_IDS = {(0x1209, 0x5740), (0x1209, 0x5741)}


def _is_flight_controller(port_info):
    return (port_info.vid, port_info.pid) in ARDUPILOT_USB_IDS


def _serial_port_devices(exclude_flight_controllers=False):
    try:
        from serial.tools import list_ports
        return [item.device for item in list_ports.comports()
                if not (exclude_flight_controllers and _is_flight_controller(item))]
    except Exception:
        return []


def flight_controller_ports():
    """Return connected ArduPilot flight controllers (application or bootloader)."""
    from serial.tools import list_ports
    return [item for item in list_ports.comports() if _is_flight_controller(item)]


class _UploaderOutput(io.TextIOBase):
    """Collect the ArduPilot uploader's console output and report its progress bars."""

    PROGRESS = re.compile(r"(Erase|Program|Verify)\s*:\s*\[[= ]*\]\s*([\d.]+)%")

    def __init__(self, progress):
        self.progress = progress
        self.last = None
        self.text = []

    def write(self, text):
        self.text.append(text)
        for match in self.PROGRESS.finditer(text):
            step = (match.group(1), int(float(match.group(2))) // 5 * 5)
            if self.progress and step != self.last:
                self.last = step
                self.progress(f"Flight controller: {step[0].lower()} {step[1]}%")
        return len(text)


def _identify_or_request_bootloader(up):
    """Identify an ArduPilot bootloader on the open port, or ask the running
    application to reboot into it (MAVLink reboot request) and return False."""
    up.open()
    try:
        up.identify()
        return True
    except Exception:
        pass
    up.send_reboot()
    time.sleep(0.25)
    return False


def flash_flight_controller(images, port, progress=None, timeout=45):
    """Flash an ArduPilot flight controller with the image for its board ID.

    images maps board_id -> .apj path. The board ID comes from the board's own
    bootloader, so firmware for another board (for example BOREALIS V2 output
    order on an ASCEND FC) is never written. Only ArduPilot USB devices are
    opened. Parameters and calibration are kept by ArduPilot across updates.
    """
    import ardupilot_uploader
    firmwares = {}
    for board_id, path in images.items():
        fw = ardupilot_uploader.firmware(str(path))
        if fw.property("board_id") != board_id:
            raise FirmwareUpdateError(f"{Path(path).name} is not built for board ID {board_id}.")
        firmwares[board_id] = fw
    if port not in [item.device for item in flight_controller_ports()]:
        raise FirmwareUpdateError("Select a connected ArduPilot flight controller USB port.")

    output = _UploaderOutput(progress)
    deadline = time.monotonic() + timeout
    with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
        while time.monotonic() < deadline:
            # After the reboot request the bootloader may come back under a
            # new port name; it keeps ArduPilot's USB IDs.
            candidates = [port] + [item.device for item in flight_controller_ports()
                                   if item.device != port]
            for candidate in candidates:
                try:
                    up = ardupilot_uploader.uploader(candidate, 115200, [57600])
                except Exception:
                    continue
                try:
                    if not _identify_or_request_bootloader(up):
                        continue
                    fw = firmwares.get(up.board_type)
                    if fw is None:
                        up._uploader__reboot()  # return to the existing application
                        raise FirmwareUpdateError(
                            f"The selected firmware is not built for the connected flight controller "
                            f"(board ID {up.board_type}). Nothing was flashed.")
                    board = fw.property("summary") or f"board {up.board_type}"
                    if progress:
                        progress(f"Flashing {board}…")
                    try:
                        up.upload(fw)
                    except RuntimeError as exc:
                        raise FirmwareUpdateError(
                            f"Flight controller flashing failed: {exc}. The board stays in its "
                            "bootloader; try the update again.") from exc
                    return {"board_id": up.board_type, "board": board}
                except (IOError, OSError):
                    continue  # the port vanished during a reboot; look again
                finally:
                    up.close()
            time.sleep(0.2)
    raise FirmwareUpdateError(
        "The flight controller bootloader did not respond. Unplug the flight controller's USB, "
        "reconnect it, and try again.")


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
