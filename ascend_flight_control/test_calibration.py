#!/usr/bin/env python3
"""Tests for calibration.py using fake flight controller messages."""

from __future__ import annotations

import unittest

from calibration import (
    CMD_ACCEL_POS,
    CMD_CAL,
    POSE_FAILED,
    POSE_LEFT,
    POSE_LEVEL,
    POSE_SUCCESS,
    AccelCal,
    CompassCal,
    RadioCal,
    mavlink,
)


class FakeLink:
    def __init__(self):
        self.commands = []
        self.rates = []

    def command(self, cmd, *params):
        self.commands.append((cmd, params))

    def set_message_rate(self, msg_id, hz):
        self.rates.append((msg_id, hz))


def pose_msg(position):
    return mavlink.MAVLink_command_long_message(255, 0, CMD_ACCEL_POS, 0, float(position), 0, 0, 0, 0, 0, 0)


def ack(command, result):
    return mavlink.MAVLink_command_ack_message(command, result, 0, 0, 255, 0)


def rc_msg(values):
    chans = list(values) + [0] * (18 - len(values))
    return mavlink.MAVLink_rc_channels_message(0, len(values), *chans, 255)


class AccelTests(unittest.TestCase):
    def test_pose_sequence_and_success(self):
        link = FakeLink()
        cal = AccelCal(link)
        cal.start()
        self.assertEqual(link.commands[0], (CMD_CAL, (0, 0, 0, 0, 1)))
        self.assertEqual(cal.on_message(ack(CMD_CAL, mavlink.MAV_RESULT_ACCEPTED)), [])
        self.assertEqual(cal.on_message(pose_msg(POSE_LEVEL)), [("pose", POSE_LEVEL)])
        self.assertEqual(cal.on_message(pose_msg(POSE_LEVEL)), [])  # repeats are ignored
        cal.confirm_pose()
        self.assertEqual(link.commands[-1], (CMD_ACCEL_POS, (POSE_LEVEL,)))
        self.assertEqual(cal.on_message(pose_msg(POSE_LEFT)), [("pose", POSE_LEFT)])
        self.assertEqual(cal.on_message(pose_msg(POSE_SUCCESS)), [("done", True)])
        self.assertTrue(cal.finished)

    def test_failure_and_rejection(self):
        cal = AccelCal(FakeLink())
        self.assertEqual(cal.on_message(pose_msg(POSE_FAILED)), [("done", False)])
        cal = AccelCal(FakeLink())
        events = cal.on_message(ack(CMD_CAL, mavlink.MAV_RESULT_TEMPORARILY_REJECTED))
        self.assertEqual(events[0][0], "rejected")


class CompassTests(unittest.TestCase):
    def progress(self, cid, pct, status=mavlink.MAG_CAL_RUNNING_STEP_ONE):
        return mavlink.MAVLink_mag_cal_progress_message(cid, 1, status, 1, pct, [0] * 10, 0, 0, 0)

    def report(self, cid, status, fitness=5.0, old=0, new=0):
        return mavlink.MAVLink_mag_cal_report_message(cid, 1, status, 1, fitness, 10, -20, 30, 1, 1, 1, 0, 0, 0,
                                                      30.0, old, new, 1.0)

    def test_progress_then_success(self):
        link = FakeLink()
        cal = CompassCal(link)
        cal.start()
        self.assertEqual(link.commands[-1][0], mavlink.MAV_CMD_DO_START_MAG_CAL)
        self.assertEqual(link.commands[-1][1][2], 1, "autosave must be on")
        self.assertIn((mavlink.MAVLINK_MSG_ID_MAG_CAL_PROGRESS, 4), link.rates)
        self.assertEqual(cal.on_message(self.progress(0, 40)), [("progress", {0: 40})])
        events = cal.on_message(self.report(0, mavlink.MAG_CAL_SUCCESS, old=0, new=14))
        result = events[0][1]
        self.assertTrue(result.ok)
        self.assertEqual((result.old_orientation, result.new_orientation), (0, 14))
        self.assertTrue(cal.finished)

    def test_two_compasses_wait_for_both(self):
        cal = CompassCal(FakeLink())
        cal.on_message(self.progress(0, 50))
        cal.on_message(self.progress(1, 50))
        cal.on_message(self.report(0, mavlink.MAG_CAL_SUCCESS))
        self.assertFalse(cal.finished)
        events = cal.on_message(self.report(1, mavlink.MAG_CAL_FAILED_RESIDUALS_HIGH))
        self.assertFalse(events[0][1].ok)
        self.assertIn("noisy", events[0][1].text)
        self.assertTrue(cal.finished)

    def test_running_reports_are_not_results(self):
        cal = CompassCal(FakeLink())
        self.assertEqual(cal.on_message(self.report(0, mavlink.MAG_CAL_RUNNING_STEP_TWO)), [])


class RadioTests(unittest.TestCase):
    ROLES = {1: "Aileron (roll)", 2: "Elevator (pitch)", 3: "Throttle", 4: "Rudder (yaw)", 5: "Mode switch",
             6: "CH6 switch"}
    PARAMS = {**{f"RC{ch}_MIN": 1100.0 for ch in range(1, 9)}, **{f"RC{ch}_MAX": 1900.0 for ch in range(1, 9)},
              **{f"RC{ch}_TRIM": 1500.0 for ch in range(1, 9)}, "RC3_TRIM": 1100.0}

    def sweep(self, cal, lows, highs, rest):
        for values in (lows, highs, rest):
            cal.on_message(rc_msg(values))

    def test_plan_sets_ranges_and_throttle_low_only(self):
        cal = RadioCal(FakeLink())
        self.sweep(cal, [988, 990, 985, 992, 1000, 1000, 1500], [2012, 2010, 2015, 2008, 2000, 2000, 2000],
                   [1510, 1495, 985, 1502, 1000, 1000, 1500])
        plan = cal.plan(self.PARAMS, self.ROLES, throttle_ch=3)
        self.assertEqual(plan.changes["RC1_MIN"], 988)
        self.assertEqual(plan.changes["RC1_MAX"], 2012)
        self.assertEqual(plan.changes["RC3_TRIM"], 985)  # throttle low point
        for ch in (1, 2, 4, 5, 6):
            self.assertNotIn(f"RC{ch}_TRIM", plan.changes, "stick centers belong to Bind trim-save")
        self.assertFalse(any(k.startswith("RC7_") for k in plan.changes), "CH7 is never calibrated")
        self.assertEqual(plan.warnings, [])

    def test_unmoved_and_missing_channels_are_left_alone(self):
        cal = RadioCal(FakeLink())
        self.sweep(cal, [1000, 1500, 1000, 1000, 1500, 0], [2000, 1560, 2000, 2000, 1500, 0],
                   [1500, 1530, 1000, 1500, 1500, 0])
        plan = cal.plan(self.PARAMS, self.ROLES, throttle_ch=3)
        self.assertNotIn("RC2_MIN", plan.changes)
        self.assertNotIn("RC6_MIN", plan.changes)
        self.assertTrue(any("CH2" in w and "moved only" in w for w in plan.warnings))
        self.assertTrue(any("CH6" in w and "no signal" in w for w in plan.warnings))

    def test_warns_when_center_outside_new_range(self):
        cal = RadioCal(FakeLink())
        params = dict(self.PARAMS, RC1_TRIM=1950.0)
        self.sweep(cal, [1000] * 6, [1900] * 6, [1450] * 6)
        plan = cal.plan(params, self.ROLES, throttle_ch=3)
        self.assertTrue(any("CH1" in w and "center" in w for w in plan.warnings))

    def test_unchanged_values_are_not_rewritten(self):
        cal = RadioCal(FakeLink())
        self.sweep(cal, [1100] * 6, [1900] * 6, [1500, 1500, 1100, 1500, 1100, 1100])
        plan = cal.plan(self.PARAMS, self.ROLES, throttle_ch=3)
        self.assertEqual(plan.changes, {})

    def test_start_and_stop_tell_the_fc(self):
        link = FakeLink()
        cal = RadioCal(link)
        cal.start()
        self.assertEqual(link.commands[0], (CMD_CAL, (0, 0, 0, 1)))
        self.assertIn((mavlink.MAVLINK_MSG_ID_RC_CHANNELS, 10), link.rates)
        cal.stop()
        self.assertEqual(link.commands[-1], (CMD_CAL, (0, 0, 0, 0)))


if __name__ == "__main__":
    unittest.main()
