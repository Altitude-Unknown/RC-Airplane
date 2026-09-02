import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent
PRODUCTION_SOURCES = (
    ROOT / "PCB/TxV3/TxV3_Full_M0/flight_core.h",
    ROOT / "tx_firmware/tx_firmware.ino",
)
PRODUCTION_RECEIVER = ROOT / "rx_firmware/rx_firmware.ino"


class TransmitterTrimSourceTests(unittest.TestCase):
    def test_all_physical_trim_channels_step_on_release(self):
        for source in PRODUCTION_SOURCES:
            text = source.read_text(encoding="utf-8")
            self.assertIn("if (b.wasPressed) {\n      stepTrim(b.ch, b.dir);", text)
            self.assertNotIn("if (b.ch != 0)", text)

    def test_production_rudder_buttons_do_not_emit_autolevel_commands(self):
        for source in PRODUCTION_SOURCES:
            text = source.read_text(encoding="utf-8")
            self.assertNotIn("AUX_AUTOLEVEL_ON", text)
            self.assertNotIn("AUX_AUTOLEVEL_OFF", text)

    def test_production_receiver_keeps_reserved_packet_byte_without_autolevel(self):
        text = PRODUCTION_RECEIVER.read_text(encoding="utf-8")
        packet = text.split("struct __attribute__((packed)) ControlPacket {", 1)[1].split("};", 1)[0]
        self.assertIn("uint16_t flags;", packet)
        self.assertIn("uint8_t aux_flags;", packet)
        self.assertIn("uint16_t seq;", packet)
        self.assertNotIn("AUX_AUTOLEVEL_ON", text)
        self.assertNotIn("handleAutolevel", text)


if __name__ == "__main__":
    unittest.main()
