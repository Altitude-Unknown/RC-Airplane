import unittest
from pathlib import Path


SOURCE = Path(__file__).with_name("rx_firmware") / "rx_firmware.ino"


class ReceiverBindPlugSafetyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = SOURCE.read_text()

    def test_rudder_output_is_guarded_for_bind_plug_boot(self):
        self.assertIn("if (!bindPlugBoot) pinMode(PIN_SERVO_RUDDER, OUTPUT);", self.source)
        self.assertIn("if (!bindPlugBoot) {\n    writePulse(PIN_SERVO_RUDDER, cur_r);", self.source)

    def test_bind_plug_requires_restart_before_accepting_controls(self):
        self.assertIn("bindRestartRequired = bindPlugBoot;", self.source)
        self.assertIn("const bool accept = !bindMode && !bindRestartRequired", self.source)
        self.assertIn("if (bindRestartRequired) {", self.source)

    def test_bind_plug_detection_precedes_rudder_output_configuration(self):
        detection = self.source.index("bindPlugBoot = detectRudderBindPlug();")
        output = self.source.index("if (!bindPlugBoot) pinMode(PIN_SERVO_RUDDER, OUTPUT);")
        self.assertLess(detection, output)


if __name__ == "__main__":
    unittest.main()
