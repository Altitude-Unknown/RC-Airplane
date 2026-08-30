#!/usr/bin/env python3
"""Create updater-ready firmware assets and their checksum manifest."""

import argparse
import hashlib
import json
import struct
from pathlib import Path


UF2_MAGIC_START0 = 0x0A324655
UF2_MAGIC_START1 = 0x9E5D5157
UF2_MAGIC_END = 0x0AB16F30
UF2_FLAG_FAMILY_ID = 0x00002000
SAMD21_FAMILY_ID = 0x68ED2B88


def bin_to_uf2(data, base_address=0x2000, payload_size=256):
    blocks = []
    block_count = (len(data) + payload_size - 1) // payload_size
    for block_number in range(block_count):
        payload = data[block_number * payload_size:(block_number + 1) * payload_size]
        payload = payload.ljust(payload_size, b"\0")
        header = struct.pack(
            "<IIIIIIII", UF2_MAGIC_START0, UF2_MAGIC_START1, UF2_FLAG_FAMILY_ID,
            base_address + block_number * payload_size, payload_size,
            block_number, block_count, SAMD21_FAMILY_ID,
        )
        blocks.append(header + payload + bytes(476 - payload_size) + struct.pack("<I", UF2_MAGIC_END))
    return b"".join(blocks)


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(128 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--samd-bin", required=True, type=Path)
    parser.add_argument("--esp-merged-bin", required=True, type=Path)
    parser.add_argument("--version", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    samd_asset = args.output / "walach-tx-v3-samd21.uf2"
    esp_asset = args.output / "walach-tx-v3-esp32c3.bin"
    samd_asset.write_bytes(bin_to_uf2(args.samd_bin.read_bytes()))
    esp_asset.write_bytes(args.esp_merged_bin.read_bytes())
    manifest = {
        "schema": 1,
        "version": args.version,
        "boards": {
            "samd21": {"asset": samd_asset.name, "format": "uf2", "sha256": sha256(samd_asset)},
            "esp32c3": {"asset": esp_asset.name, "format": "merged-bin", "offset": "0x0", "sha256": sha256(esp_asset)},
        },
    }
    (args.output / "transmitter-firmware-manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
