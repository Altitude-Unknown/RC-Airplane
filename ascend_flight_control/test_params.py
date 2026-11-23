#!/usr/bin/env python3
"""Tests for the parameter catalog, protocol, backup files and change store."""

from __future__ import annotations

import os
import queue
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("MAVLINK20", "1")
from pymavlink import mavutil  # noqa: E402

from param_catalog import CATALOG, PROTECTED  # noqa: E402
from param_protocol import (  # noqa: E402
    Param,
    ParamError,
    download_all,
    load_param_file,
    plan_file_restore,
    save_param_file,
    write_changes,
)
from params_view import ParamStore, load_metadata, metadata_range  # noqa: E402

mavlink = mavutil.mavlink
FLOAT = mavlink.MAV_PARAM_TYPE_REAL32
INT8 = mavlink.MAV_PARAM_TYPE_INT8
INT16 = mavlink.MAV_PARAM_TYPE_INT16

METADATA, METADATA_SOURCE = load_metadata()


class CatalogTests(unittest.TestCase):
    def test_metadata_present(self):
        self.assertGreater(len(METADATA), 1000, f"metadata missing ({METADATA_SOURCE})")

    def test_every_setting_matches_firmware(self):
        seen = set()
        for group in CATALOG:
            for s in group.settings:
                with self.subTest(param=s.name):
                    self.assertNotIn(s.name, seen, "listed twice")
                    seen.add(s.name)
                    info = METADATA.get(s.name)
                    self.assertIsNotNone(info, "not a parameter on this firmware")
                    if s.options is not None and info.get("Values"):
                        for value in s.options:
                            self.assertIn(str(value), info["Values"], f"option {value} not valid")
                    lo, hi = metadata_range(info)
                    if lo is not None and s.min is not None:
                        self.assertGreaterEqual(s.min, lo * s.scale - 1e-9)
                    if hi is not None and s.max is not None:
                        self.assertLessEqual(s.max, hi * s.scale + 1e-9)
                    for value in s.caution_values:
                        self.assertIn(value, s.options or {}, "caution value is not an option")

    def test_project_rules_respected(self):
        names = {s.name for g in CATALOG for s in g.settings}
        self.assertNotIn("RC7_OPTION", names, "CH7 is reserved for Bind-button trim-save")
        self.assertIn("RC7_OPTION", PROTECTED)


class FakeFc:
    """Vehicle side of the MAVLink parameter protocol."""

    def __init__(self, params, drop_indexes=(), clamp=None, ignore_sets=False):
        self.params = params  # list of (name, value, type)
        self.target_system = 1
        self.target_component = 1
        self._q: queue.Queue = queue.Queue()
        self._drop = set(drop_indexes)
        self.clamp = clamp or {}
        self.ignore_sets = ignore_sets

    def drain_param_messages(self):
        while not self._q.empty():
            self._q.get_nowait()

    def wait_param_message(self, timeout):
        try:
            return self._q.get_nowait()
        except queue.Empty:
            return None

    def send(self, fn):
        fn(self)

    def _value_msg(self, index, use_index=True):
        name, value, ptype = self.params[index]
        return mavlink.MAVLink_param_value_message(
            name.encode(), value, ptype, len(self.params), index if use_index else 65535)

    def param_request_list_send(self, _ts, _tc):
        for i in range(len(self.params)):
            if i in self._drop:
                self._drop.discard(i)
                continue
            self._q.put(self._value_msg(i))

    def param_request_read_send(self, _ts, _tc, _name, index):
        self._q.put(self._value_msg(index))

    def param_set_send(self, _ts, _tc, name, value, ptype):
        if self.ignore_sets:
            return
        name = name.decode() if isinstance(name, bytes) else name
        for i, (n, _v, t) in enumerate(self.params):
            if n == name:
                lo, hi = self.clamp.get(n, (-1e9, 1e9))
                self.params[i] = (n, min(max(value, lo), hi), t)
                self._q.put(self._value_msg(i, use_index=False))


def sample_params():
    return [("TRIM_THROTTLE", 45.0, INT8), ("ROLL_LIMIT_DEG", 55.0, FLOAT),
            ("THR_FAILSAFE", 1.0, INT8), ("RTL_ALTITUDE", 100.0, FLOAT),
            ("AHRS_TRIM_X", 0.01, FLOAT), ("STAT_FLTTIME", 1234.0, INT16)]


class ProtocolTests(unittest.TestCase):
    def test_download_all(self):
        params = download_all(FakeFc(sample_params()))
        self.assertEqual(len(params), 6)
        self.assertTrue(params["TRIM_THROTTLE"].is_int)
        self.assertFalse(params["ROLL_LIMIT_DEG"].is_int)

    def test_download_fills_gaps(self):
        params = download_all(FakeFc(sample_params(), drop_indexes={1, 4}), stall_timeout=0)
        self.assertEqual(set(params), {p[0] for p in sample_params()})

    def test_silent_fc_raises(self):
        fc = FakeFc(sample_params())
        fc.param_request_list_send = lambda *_a: None
        with self.assertRaisesRegex(ParamError, "did not send"):
            download_all(fc, stall_timeout=0, rounds=2)

    def test_write_verifies(self):
        fc = FakeFc(sample_params())
        params = download_all(fc)
        results = write_changes(fc, params, {"TRIM_THROTTLE": 50, "ROLL_LIMIT_DEG": 45.5})
        self.assertTrue(all(r.ok for r in results))
        self.assertEqual(params["TRIM_THROTTLE"].value, 50)

    def test_write_detects_clamp(self):
        fc = FakeFc(sample_params(), clamp={"ROLL_LIMIT_DEG": (0, 60)})
        params = download_all(fc)
        (result,) = write_changes(fc, params, {"ROLL_LIMIT_DEG": 80})
        self.assertFalse(result.ok)
        self.assertIn("kept 60", result.message)

    def test_write_reports_no_reply(self):
        fc = FakeFc(sample_params())
        params = download_all(fc)
        fc.ignore_sets = True
        (result,) = write_changes(fc, params, {"TRIM_THROTTLE": 50})
        self.assertFalse(result.ok)
        self.assertIn("No reply", result.message)


class FileTests(unittest.TestCase):
    def test_round_trip_and_restore_plan(self):
        fc = FakeFc(sample_params())
        params = download_all(fc)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "backup.param"
            save_param_file(path, params, "test backup")
            values = load_param_file(path)
            self.assertEqual(values["TRIM_THROTTLE"], 45)
            self.assertAlmostEqual(values["ROLL_LIMIT_DEG"], 55)

            path.write_text("# other board\nTRIM_THROTTLE,60\nROLL_LIMIT_DEG 40\nAHRS_TRIM_X,0.05\n"
                            "STAT_FLTTIME,99\nNOT_A_PARAM,1\nTHR_FAILSAFE,1\n")
            plan = plan_file_restore(load_param_file(path), params)
        self.assertEqual(plan.changes, {"TRIM_THROTTLE": 60, "ROLL_LIMIT_DEG": 40})
        self.assertEqual(plan.calibration_changes, {"AHRS_TRIM_X": 0.05})
        self.assertEqual(plan.unknown, ["NOT_A_PARAM"])
        self.assertEqual(plan.skipped, ["STAT_FLTTIME"])

    def test_bad_line_reports_line_number(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.param"
            path.write_text("TRIM_THROTTLE,50\nROLL_LIMIT_DEG,abc\n")
            with self.assertRaisesRegex(ParamError, "Line 2"):
                load_param_file(path)


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.store = ParamStore(METADATA)
        self.store.set_params({
            "TRIM_THROTTLE": Param("TRIM_THROTTLE", 45, INT8),
            "ROLL_LIMIT_DEG": Param("ROLL_LIMIT_DEG", 55, FLOAT),
        }, "now")
        self.calls = 0
        self.store.subscribe(self._count)

    def _count(self):
        self.calls += 1

    def test_stage_and_revert(self):
        self.store.stage("TRIM_THROTTLE", 50.4)
        self.assertEqual(self.store.pending, {"TRIM_THROTTLE": 50.0})  # ints are rounded
        self.store.stage("TRIM_THROTTLE", 45)  # back to the FC value = no change
        self.assertEqual(self.store.pending, {})

    def test_no_notify_without_change(self):
        self.store.stage("ROLL_LIMIT_DEG", 55)
        self.assertEqual(self.calls, 0)
        self.store.stage("ROLL_LIMIT_DEG", 50)
        self.store.stage("ROLL_LIMIT_DEG", 50)
        self.assertEqual(self.calls, 1)

    def test_describe_uses_option_names(self):
        self.store.params["FLTMODE1"] = Param("FLTMODE1", 5, INT8)
        self.assertEqual(self.store.describe("FLTMODE1", 5), "FBWA")
        self.assertEqual(self.store.describe("ROLL_LIMIT_DEG", 55), "55 deg")


if __name__ == "__main__":
    unittest.main()
