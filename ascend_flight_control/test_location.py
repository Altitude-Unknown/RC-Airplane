#!/usr/bin/env python3
"""Tests for location answers and the saved map home."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import app_settings
import units
from location import parse


class ParseTests(unittest.TestCase):
    def test_ok(self):
        r = parse("ok 45.6418354 -111.1893332 65")
        self.assertTrue(r.ok)
        self.assertEqual((r.lat, r.lon, r.accuracy_m), (45.6418354, -111.1893332, 65.0))

    def test_ok_without_accuracy_and_windows_line_endings(self):
        r = parse("ok 39.7392 -104.9903\r\n")
        self.assertTrue(r.ok)
        self.assertIsNone(r.accuracy_m)

    def test_refusals_explain_themselves(self):
        for word, phrase in (("denied", "privacy settings"), ("off", "turned off"), ("unknown", "could not work out")):
            r = parse(word)
            self.assertFalse(r.ok)
            self.assertIn(phrase, r.message)

    def test_garbage_and_out_of_range(self):
        self.assertFalse(parse("").ok)
        self.assertFalse(parse("error COMException").ok)
        self.assertFalse(parse("ok 45,64 -111,19 10").ok)  # a comma-decimal locale must not slip through
        self.assertFalse(parse("ok 123 45 10").ok)


class MapHomeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self._orig = units.config_dir
        app_settings.config_dir = lambda: self.tmp

    def tearDown(self):
        app_settings.config_dir = self._orig

    def test_save_load_clear_keeps_other_settings(self):
        (self.tmp / "settings.json").write_text('{"units": {"speed": "mph", "alt": "ft", "vspeed": "ft/min"}}')
        home = {"lat": 45.64, "lon": -111.19, "zoom": 14}
        self.assertTrue(app_settings.save_setting("map_home", home))
        self.assertEqual(app_settings.load_setting("map_home"), home)
        self.assertEqual(app_settings.load_setting("units")["speed"], "mph")
        app_settings.save_setting("map_home", None)
        self.assertIsNone(app_settings.load_setting("map_home"))
        self.assertEqual(app_settings.load_setting("units")["alt"], "ft")

    def test_unreadable_file_gives_default(self):
        (self.tmp / "settings.json").write_text("{not json")
        self.assertEqual(app_settings.load_setting("map_home", "none"), "none")

    def test_valid_map_home(self):
        from ascend_flight_control import valid_map_home
        self.assertEqual(valid_map_home({"lat": "45.6", "lon": -111.2, "zoom": 40}), {"lat": 45.6, "lon": -111.2, "zoom": 19})
        self.assertIsNone(valid_map_home({"lat": 95, "lon": 0}))
        self.assertIsNone(valid_map_home({"lat": 1}))
        self.assertIsNone(valid_map_home(None))


if __name__ == "__main__":
    unittest.main()
