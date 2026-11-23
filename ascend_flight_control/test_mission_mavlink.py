#!/usr/bin/env python3
"""Tests for mission conversion and the MAVLink mission transfer, using a fake FC."""

from __future__ import annotations

import queue
import unittest

import os

os.environ.setdefault("MAVLINK20", "1")  # mission_type and other v2 fields
from pymavlink import mavutil  # noqa: E402

from mission_mavlink import (
    MissionTransferError,
    compare_items,
    download_mission,
    items_to_mission,
    mission_to_items,
    upload_mission,
)
from mission_schema import HomePoint, LoiterSettings, Mission, Waypoint, WaypointEvent, mission_from_dict, mission_to_dict

mavlink = mavutil.mavlink
GCS = 255


def sample_mission() -> Mission:
    m = Mission(name="Test", home=HomePoint(45.64, -111.19, 1490))
    m.waypoints = [
        Waypoint(1, 45.641, -111.189, altitude_m=60, action="takeoff"),
        Waypoint(2, 45.645, -111.185, altitude_m=100, speed_mps=18),
        Waypoint(3, 45.646, -111.180, altitude_m=100, speed_mps=18, action="set_servo",
                 event=WaypointEvent(servo_channel=9, servo_pwm=1900)),
        Waypoint(4, 45.644, -111.178, altitude_m=80, speed_mps=18, action="loiter",
                 event=WaypointEvent(type="camera"), loiter=LoiterSettings(mode="time", seconds=30)),
        Waypoint(5, 45.640, -111.188, altitude_m=0, action="return_home"),
    ]
    return m


class FakeFc:
    """Speaks the vehicle side of the MAVLink mission protocol."""

    def __init__(self, drop_first_request_for=None, reject=None):
        self.stored: list = []
        self.target_system = 1
        self.target_component = 1
        self._q: queue.Queue = queue.Queue()
        self._incoming_count = None
        self._incoming: dict = {}
        self._drop = set(drop_first_request_for or [])
        self.reject = reject

    # FcLink interface used by mission_mavlink
    def drain_mission_messages(self):
        while not self._q.empty():
            self._q.get_nowait()

    def wait_mission_message(self, types, timeout):
        while True:
            try:
                msg = self._q.get_nowait()
            except queue.Empty:
                return None  # simulated timeout
            if msg.get_type() in types:
                return msg

    def send(self, fn):
        fn(self)

    # mav.*_send methods the GCS calls
    def _request(self, seq):
        if seq in self._drop:
            self._drop.discard(seq)  # lost on the radio link
            return
        self._q.put(mavlink.MAVLink_mission_request_int_message(GCS, 0, seq, 0))

    def mission_count_send(self, _ts, _tc, count, _mt):
        if self.reject is not None:
            self._q.put(mavlink.MAVLink_mission_ack_message(GCS, 0, self.reject, 0))
            return
        self._incoming_count = count
        self._incoming = {}
        self._request(0)

    def mission_item_int_send(self, _ts, _tc, seq, frame, command, _cur, _auto, p1, p2, p3, p4, x, y, z, _mt):
        self._incoming[seq] = mavlink.MAVLink_mission_item_int_message(
            GCS, 0, seq, frame, command, 0, 1, p1, p2, p3, p4, x, y, z, 0)
        if len(self._incoming) == self._incoming_count:
            self.stored = [self._incoming[i] for i in range(self._incoming_count)]
            self._q.put(mavlink.MAVLink_mission_ack_message(GCS, 0, mavlink.MAV_MISSION_ACCEPTED, 0))
        else:
            self._request(seq + 1)

    def mission_request_list_send(self, _ts, _tc, _mt):
        self._q.put(mavlink.MAVLink_mission_count_message(GCS, 0, len(self.stored), 0))

    def mission_request_int_send(self, _ts, _tc, seq, _mt):
        self._q.put(self.stored[seq])

    def mission_ack_send(self, *_args):
        pass


def wait_retry(fc: FakeFc):
    """When the fake drops a packet, the GCS times out; emulate the FC re-requesting."""
    original = fc.wait_mission_message

    def wrapped(types, timeout):
        msg = original(types, timeout)
        if msg is None and fc._incoming_count and len(fc._incoming) < fc._incoming_count:
            fc._request(len(fc._incoming))
            msg = original(types, timeout)
        return msg

    fc.wait_mission_message = wrapped


class ConversionTests(unittest.TestCase):
    def test_item_layout(self):
        result = mission_to_items(sample_mission())
        self.assertEqual(result.errors, [])
        names = [i.describe() for i in result.items]
        self.assertEqual(names, [
            "NAV_WAYPOINT",          # home
            "NAV_TAKEOFF",
            "DO_CHANGE_SPEED",       # 15 -> 18 before WP2
            "NAV_WAYPOINT",
            "NAV_WAYPOINT", "DO_SET_SERVO",
            "NAV_LOITER_TIME", "DO_DIGICAM_CONTROL",
            "NAV_RETURN_TO_LAUNCH",
        ])
        self.assertEqual(result.items[0].frame, mavlink.MAV_FRAME_GLOBAL_INT)
        self.assertEqual(result.items[1].frame, mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT_INT)
        self.assertEqual(result.items[5].params[:2], (9.0, 1900.0))
        self.assertEqual(result.items[6].params[:3], (30.0, 0, 1))
        self.assertEqual(result.items[7].x, 1)  # shutter trigger in param5

    def test_bad_servo_is_error(self):
        m = sample_mission()
        m.waypoints[2].event.servo_pwm = None
        self.assertTrue(any("servo" in e for e in mission_to_items(m).errors))

    def test_warns_without_takeoff(self):
        m = sample_mission()
        m.waypoints[0].action = "waypoint"
        self.assertTrue(any("takeoff" in w for w in mission_to_items(m).warnings))

    def test_round_trip_to_editor(self):
        original = sample_mission()
        items = mission_to_items(original).items
        rebuilt, notes = items_to_mission(items)
        self.assertEqual(notes, [])
        self.assertEqual([w.action for w in rebuilt.waypoints], [w.action for w in original.waypoints])
        self.assertEqual(rebuilt.waypoints[2].event.servo_channel, 9)
        self.assertEqual(rebuilt.waypoints[3].event.type, "camera")
        self.assertEqual(rebuilt.waypoints[3].loiter.mode, "time")
        self.assertEqual(rebuilt.waypoints[3].loiter.seconds, 30)
        self.assertEqual(rebuilt.waypoints[1].speed_mps, 18)
        # Converting the rebuilt mission again must give identical FC items.
        self.assertEqual(compare_items(items, mission_to_items(rebuilt).items), [])


def loiter_mission(loiter: LoiterSettings) -> Mission:
    m = Mission(home=HomePoint(45.64, -111.19, 1490))
    m.waypoints = [Waypoint(1, 45.641, -111.189, altitude_m=60, action="takeoff"),
                   Waypoint(2, 45.645, -111.185, altitude_m=90, action="loiter", loiter=loiter)]
    return m


class LoiterTests(unittest.TestCase):
    def convert(self, loiter):
        result = mission_to_items(loiter_mission(loiter))
        return result, (result.items[-1] if result.items else None)

    def test_time_ignores_radius_and_sets_direction(self):
        result, item = self.convert(LoiterSettings(mode="time", seconds=45, radius_m=120, clockwise=False))
        self.assertEqual(item.command, mavlink.MAV_CMD_NAV_LOITER_TIME)
        self.assertEqual(item.params, (45.0, 0, -1.0, 0))
        self.assertTrue(any("default loiter radius" in w for w in result.warnings))

    def test_laps_with_radius_and_direction(self):
        result, item = self.convert(LoiterSettings(mode="turns", turns=4, radius_m=80, clockwise=False))
        self.assertEqual(result.errors, [])
        self.assertEqual(item.command, mavlink.MAV_CMD_NAV_LOITER_TURNS)
        self.assertEqual(item.params, (4.0, 0, -80.0, 0))

    def test_laps_large_radius_rounded_to_10m(self):
        result, item = self.convert(LoiterSettings(mode="turns", turns=2, radius_m=304))
        self.assertEqual(item.params[2], 300.0)
        self.assertTrue(any("10 m steps" in w for w in result.warnings))

    def test_forever_with_radius(self):
        result, item = self.convert(LoiterSettings(mode="forever", radius_m=150))
        self.assertEqual(item.command, mavlink.MAV_CMD_NAV_LOITER_UNLIM)
        self.assertEqual(item.params[2], 150.0)

    def test_counter_clockwise_needs_radius(self):
        for mode in ("turns", "forever"):
            result, _ = self.convert(LoiterSettings(mode=mode, radius_m=0, clockwise=False))
            self.assertTrue(any("needs a loiter radius" in e for e in result.errors), mode)

    def test_limits(self):
        self.assertTrue(self.convert(LoiterSettings(mode="turns", turns=0))[0].errors)
        self.assertTrue(self.convert(LoiterSettings(mode="turns", turns=256))[0].errors)
        self.assertTrue(self.convert(LoiterSettings(mode="time", seconds=0))[0].errors)
        self.assertTrue(self.convert(LoiterSettings(mode="forever", radius_m=3000))[0].errors)

    def test_round_trip_every_mode(self):
        for lo in (LoiterSettings(mode="time", seconds=90, clockwise=False),
                   LoiterSettings(mode="turns", turns=5, radius_m=75),
                   LoiterSettings(mode="turns", turns=2, radius_m=400, clockwise=False),
                   LoiterSettings(mode="forever", radius_m=0),
                   LoiterSettings(mode="forever", radius_m=200, clockwise=False)):
            items = mission_to_items(loiter_mission(lo)).items
            fc = FakeFc()
            upload_mission(fc, items)
            readback = download_mission(fc)
            self.assertEqual(compare_items(items, readback), [], lo)
            rebuilt, notes = items_to_mission(readback)
            self.assertEqual(notes, [])
            self.assertEqual(rebuilt.waypoints[1].loiter, lo)

    def test_json_round_trip_and_old_files(self):
        m = loiter_mission(LoiterSettings(mode="turns", turns=3, radius_m=90, clockwise=False))
        self.assertEqual(mission_from_dict(mission_to_dict(m)).waypoints[1].loiter, m.waypoints[1].loiter)
        old = mission_to_dict(loiter_mission(LoiterSettings()))
        for wp in old["waypoints"]:
            wp.pop("loiter")
        old["waypoints"][1]["event"]["hold_seconds"] = 40
        self.assertEqual(mission_from_dict(old).waypoints[1].loiter, LoiterSettings(mode="time", seconds=40))
        old["waypoints"][1]["event"]["hold_seconds"] = 0
        self.assertEqual(mission_from_dict(old).waypoints[1].loiter.mode, "forever")


def photo_mission(start_m=23.7, stop=True) -> Mission:
    m = Mission(home=HomePoint(45.64, -111.19, 1490))
    m.waypoints = [Waypoint(1, 45.641, -111.189, altitude_m=60, action="takeoff"),
                   Waypoint(2, 45.645, -111.185, event=WaypointEvent(type="camera_distance", camera_distance_m=start_m)),
                   Waypoint(3, 45.646, -111.180,
                            event=WaypointEvent(type="camera_distance", camera_distance_m=0) if stop else WaypointEvent())]
    return m


class CameraDistanceTests(unittest.TestCase):
    def test_start_and_stop_items(self):
        result = mission_to_items(photo_mission())
        self.assertEqual(result.errors, [])
        self.assertEqual([i.describe() for i in result.items[1:]],
                         ["NAV_TAKEOFF", "NAV_WAYPOINT", "DO_SET_CAM_TRIGG_DIST", "NAV_WAYPOINT", "DO_SET_CAM_TRIGG_DIST"])
        start, stop = result.items[3], result.items[5]
        self.assertEqual(start.params, (23.7, 0, 1.0, 0))  # first photo right away
        self.assertEqual(stop.params, (0.0, 0, 0.0, 0))
        self.assertFalse(any("keeps firing" in w for w in result.warnings))

    def test_warns_when_never_stopped(self):
        self.assertTrue(any("keeps firing" in w for w in mission_to_items(photo_mission(stop=False)).warnings))

    def test_out_of_range_is_error(self):
        self.assertTrue(any("photo distance" in e for e in mission_to_items(photo_mission(start_m=1500)).errors))
        from mission_schema import validate_mission
        self.assertTrue(any("photo distance" in e for e in validate_mission(photo_mission(start_m=-1))))

    def test_round_trip_and_json(self):
        original = photo_mission()
        items = mission_to_items(original).items
        rebuilt, notes = items_to_mission(items)
        self.assertEqual(notes, [])
        self.assertEqual([(w.event.type, w.event.camera_distance_m) for w in rebuilt.waypoints[1:]],
                         [("camera_distance", 23.7), ("camera_distance", 0.0)])
        self.assertEqual(compare_items(items, mission_to_items(rebuilt).items), [])
        self.assertEqual(mission_from_dict(mission_to_dict(original)).waypoints[1].event.camera_distance_m, 23.7)

    def test_float32_readback_matches(self):
        """The FC stores the distance as a 32-bit float; the read-back check must accept that."""
        import struct
        items = mission_to_items(photo_mission(start_m=23.7)).items
        upload_mission(FakeFc(), items)  # protocol path accepts the item
        stored = list(items)
        a = stored[3]
        f32 = struct.unpack("<f", struct.pack("<f", a.params[0]))[0]
        b = type(a)(a.command, a.frame, (f32, a.params[1], a.params[2], a.params[3]), source_wp=a.source_wp)
        stored[3] = b
        self.assertEqual(compare_items(items, stored), [])


class TransferTests(unittest.TestCase):
    def test_upload_then_download_verifies(self):
        fc = FakeFc()
        items = mission_to_items(sample_mission()).items
        upload_mission(fc, items)
        self.assertEqual(len(fc.stored), len(items))
        self.assertEqual(compare_items(items, download_mission(fc)), [])

    def test_upload_survives_dropped_requests(self):
        fc = FakeFc(drop_first_request_for=[0, 3])
        wait_retry(fc)
        items = mission_to_items(sample_mission()).items
        # Item 0 is dropped before anything was sent, so the GCS resends MISSION_COUNT.
        upload_mission(fc, items)
        self.assertEqual(len(fc.stored), len(items))

    def test_rejection_is_reported(self):
        fc = FakeFc(reject=mavlink.MAV_MISSION_NO_SPACE)
        with self.assertRaisesRegex(MissionTransferError, "NO_SPACE"):
            upload_mission(fc, mission_to_items(sample_mission()).items)

    def test_silent_fc_times_out(self):
        fc = FakeFc()
        fc.mission_count_send = lambda *a: None
        with self.assertRaisesRegex(MissionTransferError, "stopped responding"):
            upload_mission(fc, mission_to_items(sample_mission()).items, retries=2)

    def test_compare_accepts_float_frames(self):
        # ArduPilot reads GLOBAL_RELATIVE_ALT_INT (6) back as GLOBAL_RELATIVE_ALT (3).
        items = mission_to_items(sample_mission()).items
        fc = FakeFc()
        upload_mission(fc, items)
        readback = download_mission(fc)
        for item in readback:
            if item.frame == mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT_INT:
                item.frame = mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT
        self.assertEqual(compare_items(items, readback), [])

    def test_compare_detects_altitude_change(self):
        items = mission_to_items(sample_mission()).items
        fc = FakeFc()
        upload_mission(fc, items)
        readback = download_mission(fc)
        readback[3].alt = 50
        self.assertTrue(any("altitude" in p for p in compare_items(items, readback)))


if __name__ == "__main__":
    unittest.main()
