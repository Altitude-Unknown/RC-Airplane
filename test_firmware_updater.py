import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import firmware_updater as updater


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload
        self.offset = 0

    def __enter__(self): return self
    def __exit__(self, *args): return False
    def read(self, size=-1):
        if isinstance(self.payload, bytes):
            if size < 0:
                result, self.payload = self.payload, b""
                return result
            result, self.payload = self.payload[:size], self.payload[size:]
            return result
        return json.dumps(self.payload).encode()


class FirmwareUpdaterTests(unittest.TestCase):
    def test_release_packager_includes_receiver_uf2(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            samd = root / "tx.bin"
            esp = root / "esp.bin"
            receiver = root / "rx.bin"
            output = root / "out"
            samd.write_bytes(b"tx")
            esp.write_bytes(b"esp")
            receiver.write_bytes(b"rx")
            subprocess.run([
                sys.executable, "tools/package_transmitter_firmware.py",
                "--samd-bin", str(samd),
                "--esp-merged-bin", str(esp),
                "--receiver-bin", str(receiver),
                "--version", "test",
                "--output", str(output),
            ], check=True)
            manifest = json.loads(
                (output / "transmitter-firmware-manifest.json").read_text()
            )
            receiver_info = manifest["boards"]["receiver_samd21"]
            self.assertEqual(receiver_info["asset"], "altitude-unknown-rx-v4-samd21.uf2")
            self.assertTrue((output / receiver_info["asset"]).is_file())
            self.assertEqual(receiver_info["serial_asset"], "altitude-unknown-rx-v4-samd21.bin")
            self.assertTrue((output / receiver_info["serial_asset"]).is_file())

    def test_fetch_latest_firmware_validates_manifest(self):
        images = {"samd21": b"samd", "esp32c3": b"esp", "receiver_samd21": b"rx"}
        assets = [{"name": updater.MANIFEST_ASSET_NAME, "browser_download_url": "manifest"}]
        boards = {}
        for target, content in images.items():
            asset = target + (".bin" if target == "esp32c3" else ".uf2")
            assets.append({"name": asset, "browser_download_url": "url-" + target})
            boards[target] = {"asset": asset, "sha256": hashlib.sha256(content).hexdigest()}
            if target == "receiver_samd21":
                assets.append({"name": "rx.bin", "browser_download_url": "url-rx-bin"})
                boards[target].update(serial_asset="rx.bin", serial_sha256=hashlib.sha256(b"rxbin").hexdigest())
        release = {"tag_name": "v1", "assets": assets}
        manifest = {"schema": 1, "boards": boards}
        with mock.patch.object(
                updater, "_request_json",
                side_effect=lambda url, timeout: release if "latest" in url else manifest):
            result = updater.fetch_latest_firmware()
        self.assertEqual(result["tag"], "v1")
        self.assertEqual(result["manifest"]["boards"]["esp32c3"]["download_url"], "url-esp32c3")
        self.assertEqual(result["manifest"]["boards"]["receiver_samd21"]["serial_download_url"], "url-rx-bin")

    def test_download_rejects_bad_checksum(self):
        info = {"manifest": {"boards": {"samd21": {
            "asset": "samd.uf2", "download_url": "https://example.invalid/image", "sha256": "0" * 64
        }}}}
        with tempfile.TemporaryDirectory() as folder:
            destination = Path(folder) / "samd.uf2"
            with mock.patch.object(updater.urllib.request, "urlopen", return_value=FakeResponse(b"bad")):
                with self.assertRaisesRegex(updater.FirmwareUpdateError, "checksum"):
                    updater.download_firmware(info, "samd21", destination)
            self.assertFalse(destination.exists())

    def test_flash_samd_copies_only_to_uf2_drive(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            image = root / "firmware.uf2"
            image.write_bytes(b"UF2")
            mount = root / "mount"
            mount.mkdir()
            (mount / "INFO_UF2.TXT").write_text("UF2 Bootloader")
            updater.flash_samd_uf2(image, mount)
            self.assertEqual((mount / "ALTITUDE.UF2").read_bytes(), b"UF2")

    def test_enter_samd_uf2_uses_1200_baud_touch_then_waits(self):
        with mock.patch.object(updater, "request_samd_bootloader") as request, \
             mock.patch.object(updater, "uf2_mounts", return_value=[Path("/old")]), \
             mock.patch.object(updater, "wait_for_new_uf2_mount", return_value=Path("/new")) as wait:
            result = updater.enter_samd_uf2("/dev/receiver", timeout=7)
        request.assert_called_once_with("/dev/receiver")
        wait.assert_called_once_with([Path("/old")], timeout=7, poll_interval=0.25)
        self.assertEqual(result, Path("/new"))

    def test_receiver_samba_uses_automatic_touch_and_verified_binary(self):
        with tempfile.TemporaryDirectory() as folder:
            image = Path(folder) / "receiver.bin"
            image.write_bytes(b"firmware")
            waiting = mock.Mock(returncode=1, stdout="No device found", stderr="")
            completed = mock.Mock(returncode=0, stdout="Verify successful", stderr="")
            with mock.patch.object(updater, "request_samd_bootloader") as request, \
                 mock.patch.dict(sys.modules, {"serial": mock.Mock(Serial=mock.Mock(side_effect=Exception("legacy")))}), \
                 mock.patch.object(updater, "_bossac_path", return_value=Path("/tools/bossac")), \
                 mock.patch.object(updater.time, "sleep"), \
                 mock.patch.object(updater.subprocess, "run", side_effect=[waiting, completed]) as run:
                updater.flash_receiver_samba(image, "/dev/cu.usbmodem1101")
            request.assert_called_once_with("/dev/cu.usbmodem1101")
            command = run.call_args.args[0]
            self.assertIn("--port=cu.usbmodem1101", command)
            self.assertIn("--offset=0x2000", command)
            self.assertIn("-e", command)
            self.assertEqual(run.call_count, 2)


if __name__ == "__main__":
    unittest.main()
