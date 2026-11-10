import unittest
from pathlib import Path


SOURCE = Path(__file__).with_name("rx_firmware") / "rx_firmware.ino"


class ReceiverBindPlugSafetyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = SOURCE.read_text()

    def test_bind_plug_uses_d20_sda_and_not_a_servo_output(self):
        self.assertIn("const int PIN_BIND_PLUG = 20;", self.source)
        self.assertIn("pinMode(PIN_BIND_PLUG, INPUT_PULLUP);", self.source)
        self.assertIn("digitalRead(PIN_BIND_PLUG)", self.source)
        self.assertNotIn("pinMode(PIN_SERVO_RUDDER, INPUT_PULLUP);", self.source)
        self.assertIn("pinMode(PIN_SERVO_RUDDER, OUTPUT);", self.source)
        self.assertIn("writePulse(PIN_SERVO_RUDDER, cur_r);", self.source)

    def test_bind_plug_requires_restart_before_accepting_controls(self):
        self.assertIn("bindRestartRequired = bindPlugBoot;", self.source)
        self.assertIn("const bool accept = !bindMode && !bindRestartRequired", self.source)
        self.assertIn("if (bindRestartRequired) {", self.source)

    def test_bind_plug_detection_is_latched_at_boot(self):
        self.assertIn("bindPlugBoot = detectBindPlug();", self.source)


if __name__ == "__main__":
    unittest.main()
