import hashlib
import json
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
    def test_fetch_latest_firmware_validates_manifest(self):
        images = {"samd21": b"samd", "esp32c3": b"esp"}
        assets = [{"name": updater.MANIFEST_ASSET_NAME, "browser_download_url": "manifest"}]
        boards = {}
        for target, content in images.items():
            asset = target + (".uf2" if target == "samd21" else ".bin")
            assets.append({"name": asset, "browser_download_url": "url-" + target})
            boards[target] = {"asset": asset, "sha256": hashlib.sha256(content).hexdigest()}
        release = {"tag_name": "v1", "assets": assets}
        manifest = {"schema": 1, "boards": boards}
        with mock.patch.object(
                updater, "_request_json",
                side_effect=lambda url, timeout: release if "latest" in url else manifest):
            result = updater.fetch_latest_firmware()
        self.assertEqual(result["tag"], "v1")
        self.assertEqual(result["manifest"]["boards"]["esp32c3"]["download_url"], "url-esp32c3")

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
            self.assertEqual((mount / "WALACH_TX.UF2").read_bytes(), b"UF2")


if __name__ == "__main__":
    unittest.main()
