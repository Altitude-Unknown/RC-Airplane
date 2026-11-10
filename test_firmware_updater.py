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

    def test_enter_receiver_uf2_reuses_matching_mounted_bootloader(self):
        with mock.patch.object(updater, "receiver_uf2_mounts",
                               return_value=[Path("/Volumes/RCRXBOOT")]), \
             mock.patch.object(updater, "enter_samd_uf2") as enter:
            result = updater.enter_receiver_uf2("/dev/receiver")
        enter.assert_not_called()
        self.assertEqual(result, Path("/Volumes/RCRXBOOT"))

    def test_enter_receiver_uf2_requests_bootloader_when_not_mounted(self):
        with mock.patch.object(updater, "receiver_uf2_mounts", return_value=[]), \
             mock.patch.object(updater, "enter_samd_uf2",
                               return_value=Path("/Volumes/RCRXBOOT")) as enter:
            result = updater.enter_receiver_uf2("/dev/receiver", timeout=6)
        enter.assert_called_once_with("/dev/receiver", timeout=6)
        self.assertEqual(result, Path("/Volumes/RCRXBOOT"))

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

    def test_receiver_samba_never_probes_a_flight_controller(self):
        ports = [mock.Mock(device="/dev/cu.usbmodem1101", vid=0x239A, pid=0x800B),
                 mock.Mock(device="/dev/cu.usbmodem101", vid=0x1209, pid=0x5741)]
        with tempfile.TemporaryDirectory() as folder:
            image = Path(folder) / "receiver.bin"
            image.write_bytes(b"firmware")
            waiting = mock.Mock(returncode=1, stdout="No device found", stderr="")
            with mock.patch("serial.tools.list_ports.comports", return_value=ports), \
                 mock.patch.object(updater, "request_samd_bootloader"), \
                 mock.patch("serial.Serial", side_effect=Exception("legacy")), \
                 mock.patch.object(updater, "_bossac_path", return_value=Path("/tools/bossac")), \
                 mock.patch.object(updater.time, "sleep"), \
                 mock.patch.object(updater.time, "monotonic", side_effect=[0, 1, 2, 99]), \
                 mock.patch.object(updater.subprocess, "run", return_value=waiting) as run:
                with self.assertRaises(updater.FirmwareUpdateError):
                    updater.flash_receiver_samba(image, "/dev/cu.usbmodem1101")
            probed = {arg for call in run.call_args_list for arg in call.args[0] if arg.startswith("--port=")}
            self.assertEqual(probed, {"--port=cu.usbmodem1101"})

    def test_release_packager_reads_flight_controller_board_from_apj(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name, content in (("tx.bin", b"tx"), ("esp.bin", b"esp")):
                (root / name).write_bytes(content)
            apj = root / "arduplane.apj"
            apj.write_text(json.dumps({"magic": "APJFWv1", "board_id": 65093,
                                       "summary": "ASCENDFCRev2", "git_identity": "25c94416"}))
            subprocess.run([
                sys.executable, "tools/package_transmitter_firmware.py",
                "--samd-bin", str(root / "tx.bin"), "--esp-merged-bin", str(root / "esp.bin"),
                "--flight-controller-apj", str(apj), "--version", "test", "--output", str(root / "out"),
            ], check=True)
            manifest = json.loads((root / "out" / "transmitter-firmware-manifest.json").read_text())
            entry, = manifest["flight_controllers"]
            self.assertEqual((entry["board"], entry["board_id"]), ("ASCENDFCRev2", 65093))
            self.assertEqual(entry["asset"], "altitude-unknown-fc-ascendfcrev2-arduplane.apj")
            asset = root / "out" / entry["asset"]
            self.assertEqual(entry["sha256"], hashlib.sha256(asset.read_bytes()).hexdigest())

    def _release_with_flight_controllers(self, flight_controllers, fc_assets):
        images = {"samd21": b"samd", "esp32c3": b"esp", "receiver_samd21": b"rx"}
        assets = [{"name": updater.MANIFEST_ASSET_NAME, "browser_download_url": "manifest"}]
        boards = {}
        for target, content in images.items():
            assets.append({"name": target, "browser_download_url": "url-" + target})
            boards[target] = {"asset": target, "sha256": hashlib.sha256(content).hexdigest()}
        assets += [{"name": name, "browser_download_url": "url-" + name} for name in fc_assets]
        release = {"tag_name": "v1", "assets": assets}
        manifest = {"schema": 1, "boards": boards, "flight_controllers": flight_controllers}
        with mock.patch.object(updater, "_request_json",
                               side_effect=lambda url, timeout: release if "latest" in url else manifest):
            return updater.fetch_latest_firmware()

    def test_fetch_accepts_flight_controller_firmware(self):
        entry = {"board": "ASCENDFCRev2", "board_id": 65093, "asset": "fc.apj", "sha256": "a" * 64}
        result = self._release_with_flight_controllers([entry], ["fc.apj"])
        self.assertEqual(result["manifest"]["flight_controllers"][0]["download_url"], "url-fc.apj")

    def test_fetch_rejects_flight_controller_entry_without_board_id(self):
        entry = {"board": "ASCENDFCRev2", "asset": "fc.apj", "sha256": "a" * 64}
        with self.assertRaisesRegex(updater.FirmwareUpdateError, "flight controller"):
            self._release_with_flight_controllers([entry], ["fc.apj"])

    def test_flight_controller_ports_are_ardupilot_only(self):
        ports = [mock.Mock(device="/dev/rx", vid=0x239A, pid=0x800B),
                 mock.Mock(device="/dev/fc", vid=0x1209, pid=0x5741),
                 mock.Mock(device="/dev/other-pidcodes", vid=0x1209, pid=0x0001)]
        with mock.patch("serial.tools.list_ports.comports", return_value=ports):
            self.assertEqual([p.device for p in updater.flight_controller_ports()], ["/dev/fc"])

    def _fake_uploader(self, board_type, uploads):
        class FakeUploader:
            def __init__(self, port, *args):
                self.port_name, self.board_type = port, board_type
            def open(self): pass
            def identify(self): pass
            def send_reboot(self): return True
            def close(self): pass
            def upload(self, fw): uploads.append((self.port_name, fw.property("board_id")))
            def _uploader__reboot(self): uploads.append(("rebooted", None))
        return FakeUploader

    def _fake_apj(self, folder, board_id):
        path = Path(folder) / f"{board_id}.apj"
        path.write_text("{}")
        return path

    def test_flash_flight_controller_writes_image_matching_bootloader_board_id(self):
        uploads = []
        fake = mock.Mock(uploader=self._fake_uploader(65093, uploads),
                         firmware=lambda path: mock.Mock(property=lambda key, default=None: {
                             "board_id": int(Path(path).stem), "summary": "ASCENDFCRev2"}.get(key, default)))
        fc = mock.Mock(device="/dev/fc", vid=0x1209, pid=0x5741)
        with tempfile.TemporaryDirectory() as folder, \
             mock.patch.dict(sys.modules, {"ardupilot_uploader": fake}), \
             mock.patch.object(updater, "flight_controller_ports", return_value=[fc]):
            images = {board_id: self._fake_apj(folder, board_id) for board_id in (65092, 65093)}
            result = updater.flash_flight_controller(images, "/dev/fc")
        self.assertEqual(uploads, [("/dev/fc", 65093)])
        self.assertEqual(result, {"board_id": 65093, "board": "ASCENDFCRev2"})

    def test_flash_flight_controller_refuses_unknown_board(self):
        uploads = []
        fake = mock.Mock(uploader=self._fake_uploader(140, uploads),
                         firmware=lambda path: mock.Mock(property=lambda key, default=None: {
                             "board_id": int(Path(path).stem)}.get(key, default)))
        fc = mock.Mock(device="/dev/fc", vid=0x1209, pid=0x5741)
        with tempfile.TemporaryDirectory() as folder, \
             mock.patch.dict(sys.modules, {"ardupilot_uploader": fake}), \
             mock.patch.object(updater, "flight_controller_ports", return_value=[fc]):
            images = {65093: self._fake_apj(folder, 65093)}
            with self.assertRaisesRegex(updater.FirmwareUpdateError, "board ID 140"):
                updater.flash_flight_controller(images, "/dev/fc")
        self.assertEqual(uploads, [("rebooted", None)])

    def test_flash_flight_controller_rejects_non_ardupilot_port(self):
        with tempfile.TemporaryDirectory() as folder, \
             mock.patch.dict(sys.modules, {"ardupilot_uploader": mock.Mock(
                 firmware=lambda path: mock.Mock(property=lambda key, default=None: 65093))}), \
             mock.patch.object(updater, "flight_controller_ports", return_value=[]):
            with self.assertRaisesRegex(updater.FirmwareUpdateError, "ArduPilot"):
                updater.flash_flight_controller({65093: self._fake_apj(folder, 65093)}, "/dev/rx")


if __name__ == "__main__":
    unittest.main()
