#!/usr/bin/env python3
"""Hardware-free regression tests for transmitter GUI model/protocol codecs."""

import struct
import unittest

from fram_gui_models import (
    EspRoleWorker,
    MODEL_BIN_SIZE,
    MODEL_FMT,
    ModelsStore,
    validate_model_controls,
)


class MemoryWorker:
    def __init__(self):
        self.data = bytearray(4096)

    def cmd_write(self, address, data):
        self.data[address:address + len(data)] = data

    def cmd_read(self, address, length):
        return bytes(self.data[address:address + length])


class ModelCodecTests(unittest.TestCase):
    def test_collapsed_zero_endpoints_are_rejected(self):
        model = {
            "rates": [50, 50, 50, 0],
            "expo": [40, 40, 40, 0],
            "subtrim": [0, 0, 0, 0],
            "endpoints": [[0, 0] for _ in range(4)],
        }

        with self.assertRaisesRegex(ValueError, "Rudder endpoints"):
            validate_model_controls(model)

    def test_endpoints_are_limited_to_receiver_range(self):
        model = {
            "rates": [100] * 4,
            "expo": [0] * 4,
            "subtrim": [0] * 4,
            "endpoints": [[700, 2300] for _ in range(4)],
        }

        validate_model_controls(model)
        self.assertEqual(model["endpoints"], [[800, 2200] for _ in range(4)])

    def test_mix_and_reverse_round_trip_with_valid_crc(self):
        worker = MemoryWorker()
        store = ModelsStore(worker)
        model = {
            "name": "Mix Test",
            "bind_code": 1234,
            "rates": [100, 90, 80, 70],
            "expo": [0, 10, -10, 0],
            "dr_switch": 0,
            "active_rates": False,
            "subtrim": [0, 1, -2, 0],
            "endpoints": [[1000, 2000] for _ in range(4)],
            "reverse": [False, True, False, False],
            "ail_to_rud_mix_enabled": True,
            "ail_to_rud_mix_percent": -35,
        }

        store.write_model(0, model)
        decoded = store.read_model(0)

        self.assertTrue(decoded["crc_ok"])
        self.assertEqual(decoded["reverse"], model["reverse"])
        self.assertTrue(decoded["ail_to_rud_mix_enabled"])
        self.assertEqual(decoded["ail_to_rud_mix_percent"], -35)

        raw = worker.cmd_read(store.slot_addr(0), MODEL_BIN_SIZE)
        reserved = struct.unpack(MODEL_FMT, raw)[24]
        self.assertEqual(reserved, bytes([0x02, 0x01, 0xDD, 0, 0, 0]))

    def test_legacy_zero_reserved_bytes_disable_mix(self):
        worker = MemoryWorker()
        store = ModelsStore(worker)
        model = {
            "name": "Legacy",
            "bind_code": 1,
            "rates": [100] * 4,
            "expo": [0] * 4,
            "dr_switch": 0,
            "active_rates": False,
            "subtrim": [0] * 4,
            "endpoints": [[1000, 2000] for _ in range(4)],
            "reverse": [False] * 4,
        }

        store.write_model(0, model)
        decoded = store.read_model(0)

        self.assertFalse(decoded["ail_to_rud_mix_enabled"])
        self.assertEqual(decoded["ail_to_rud_mix_percent"], 0)


class EspStatusTests(unittest.TestCase):
    def test_status_includes_role_mode_and_mac(self):
        status = EspRoleWorker.parse_status(
            "STATUS role=MASTER authority=INSTRUCTOR mode=CONFIG "
            "mode_age_ms=125 mac=80:F1:B2:F0:1A:E8 samd_lines=20"
        )
        self.assertEqual(status["role"], "MASTER")
        self.assertEqual(status["mode"], "CONFIG")
        self.assertEqual(status["mac"], "80:F1:B2:F0:1A:E8")


if __name__ == "__main__":
    unittest.main()
