#!/usr/bin/env python3
"""
Calibration logic for ASCEND Flight Control (no UI here; see calibration_view.py).

ArduPlane's own calibration routines do the work; these classes drive them over
MAVLink and turn the replies into simple events:

- Accelerometer (6 positions): MAV_CMD_PREFLIGHT_CALIBRATION param5=1. The FC
  asks for each pose with a COMMAND_LONG MAV_CMD_ACCELCAL_VEHICLE_POS; the GCS
  confirms the pose by sending the same command back (as Mission Planner does).
- Gyroscope: PREFLIGHT_CALIBRATION param1=1 (ArduPlane also does this at boot).
- Level: PREFLIGHT_CALIBRATION param5=2 (sets AHRS_TRIM_X/Y).
- Compass: MAV_CMD_DO_START_MAG_CAL with autosave; progress and results arrive
  as MAG_CAL_PROGRESS / MAG_CAL_REPORT.
- Radio: the GCS records RC_CHANNELS while the sticks and switches are moved
  through their range, then writes RCn_MIN / RCn_MAX (and the throttle low
  point). PREFLIGHT_CALIBRATION param4=1/0 tells the FC a radio calibration is
  in progress.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field

os.environ.setdefault("MAVLINK20", "1")
from pymavlink import mavutil  # noqa: E402

mavlink = mavutil.mavlink
CMD_CAL = mavlink.MAV_CMD_PREFLIGHT_CALIBRATION
CMD_ACCEL_POS = mavlink.MAV_CMD_ACCELCAL_VEHICLE_POS

POSE_LEVEL, POSE_LEFT, POSE_RIGHT, POSE_NOSEDOWN, POSE_NOSEUP, POSE_BACK = 1, 2, 3, 4, 5, 6
POSE_SUCCESS = mavlink.ACCELCAL_VEHICLE_POS_SUCCESS
POSE_FAILED = mavlink.ACCELCAL_VEHICLE_POS_FAILED
POSE_TEXT = {
    POSE_LEVEL: ("Level", "Set the plane level, wheels down, as if sitting on the runway."),
    POSE_LEFT: ("Left side", "Roll the plane onto its LEFT wingtip, left wing pointing at the ground."),
    POSE_RIGHT: ("Right side", "Roll the plane onto its RIGHT wingtip, right wing pointing at the ground."),
    POSE_NOSEDOWN: ("Nose down", "Point the nose straight DOWN at the ground."),
    POSE_NOSEUP: ("Nose up", "Point the nose straight UP at the sky."),
    POSE_BACK: ("Upside down", "Turn the plane UPSIDE DOWN, resting on its back."),
}

MAG_STATUS_TEXT = {
    mavlink.MAG_CAL_NOT_STARTED: "not started",
    mavlink.MAG_CAL_WAITING_TO_START: "waiting to start",
    mavlink.MAG_CAL_RUNNING_STEP_ONE: "collecting (step 1 of 2)",
    mavlink.MAG_CAL_RUNNING_STEP_TWO: "collecting (step 2 of 2)",
    mavlink.MAG_CAL_SUCCESS: "success",
    mavlink.MAG_CAL_FAILED: "failed",
    mavlink.MAG_CAL_FAILED_ORIENTATION: "failed: the compass orientation could not be worked out",
    mavlink.MAG_CAL_FAILED_RADIUS: "failed: field strength out of range (metal or magnets nearby?)",
    mavlink.MAG_CAL_FAILED_OFFSETS: "failed: offsets too large (magnetic interference near the compass?)",
    mavlink.MAG_CAL_FAILED_DIAG_SCALING: "failed: scaling out of range",
    mavlink.MAG_CAL_FAILED_RESIDUALS_HIGH: "failed: readings too noisy; rotate more slowly, away from metal",
}
MAG_DONE = {mavlink.MAG_CAL_SUCCESS, mavlink.MAG_CAL_FAILED, mavlink.MAG_CAL_FAILED_ORIENTATION,
            mavlink.MAG_CAL_FAILED_RADIUS, mavlink.MAG_CAL_FAILED_OFFSETS,
            mavlink.MAG_CAL_FAILED_DIAG_SCALING, mavlink.MAG_CAL_FAILED_RESIDUALS_HIGH}

RESULT_TEXT = {
    mavlink.MAV_RESULT_ACCEPTED: "accepted",
    mavlink.MAV_RESULT_TEMPORARILY_REJECTED: "busy: it may still be starting up or finishing another "
                                             "calibration. Wait a few seconds, keep the plane still, and try again",
    mavlink.MAV_RESULT_DENIED: "denied",
    mavlink.MAV_RESULT_UNSUPPORTED: "not supported by this firmware",
    mavlink.MAV_RESULT_FAILED: "failed",
    mavlink.MAV_RESULT_IN_PROGRESS: "in progress",
}


def result_text(result: int) -> str:
    return RESULT_TEXT.get(result, f"result {result}")


# --------------------------------------------------------------------------
# Accelerometer
# --------------------------------------------------------------------------

class AccelCal:
    """Feed every vehicle message to on_message(); it returns a list of events:
    ("pose", n)        the FC wants pose n (see POSE_TEXT)
    ("done", ok)       the FC finished; ok is True on success
    ("rejected", text) the FC refused to start
    """

    def __init__(self, link):
        self.link = link
        self.pose: int | None = None
        self.confirmed: set[int] = set()
        self.finished = False

    def start(self) -> None:
        self.link.command(CMD_CAL, 0, 0, 0, 0, 1)

    def confirm_pose(self) -> None:
        if self.pose is not None:
            self.confirmed.add(self.pose)
            self.link.command(CMD_ACCEL_POS, self.pose)

    def on_message(self, msg) -> list:
        events = []
        kind = msg.get_type()
        if kind == "COMMAND_LONG" and msg.command == CMD_ACCEL_POS:
            position = int(round(msg.param1))
            if position == POSE_SUCCESS:
                self.finished = True
                events.append(("done", True))
            elif position == POSE_FAILED:
                self.finished = True
                events.append(("done", False))
            elif position in POSE_TEXT and position != self.pose:
                self.pose = position
                events.append(("pose", position))
        elif kind == "COMMAND_ACK" and msg.command == CMD_CAL:
            if msg.result not in (mavlink.MAV_RESULT_ACCEPTED, mavlink.MAV_RESULT_IN_PROGRESS):
                self.finished = True
                events.append(("rejected", result_text(msg.result)))
        return events


# --------------------------------------------------------------------------
# Compass
# --------------------------------------------------------------------------

@dataclass
class CompassResult:
    compass_id: int
    status: int
    fitness: float
    offsets: tuple[float, float, float]
    autosaved: bool
    old_orientation: int
    new_orientation: int

    @property
    def ok(self) -> bool:
        return self.status == mavlink.MAG_CAL_SUCCESS

    @property
    def text(self) -> str:
        return MAG_STATUS_TEXT.get(self.status, f"status {self.status}")


class CompassCal:
    """Events from on_message():
    ("progress", {compass_id: percent})
    ("result", CompassResult)   one per compass when it finishes
    ("rejected", text)
    """

    def __init__(self, link):
        self.link = link
        self.progress: dict[int, int] = {}
        self.results: dict[int, CompassResult] = {}
        self.started = False

    def start(self) -> None:
        self.link.set_message_rate(mavlink.MAVLINK_MSG_ID_MAG_CAL_PROGRESS, 4)
        self.link.set_message_rate(mavlink.MAVLINK_MSG_ID_MAG_CAL_REPORT, 2)
        # mask 0 = all compasses, no retry, autosave, no delay, no auto-reboot
        self.link.command(mavlink.MAV_CMD_DO_START_MAG_CAL, 0, 0, 1, 0, 0)
        self.started = True

    def cancel(self) -> None:
        self.link.command(mavlink.MAV_CMD_DO_CANCEL_MAG_CAL, 0)
        self.started = False

    @property
    def finished(self) -> bool:
        return bool(self.progress) and set(self.results) >= set(self.progress)

    def on_message(self, msg) -> list:
        kind = msg.get_type()
        if kind == "MAG_CAL_PROGRESS" and msg.compass_id not in self.results:
            self.progress[msg.compass_id] = int(msg.completion_pct)
            return [("progress", dict(self.progress))]
        if kind == "MAG_CAL_REPORT" and msg.cal_status in MAG_DONE and msg.compass_id not in self.results:
            result = CompassResult(msg.compass_id, msg.cal_status, msg.fitness, (msg.ofs_x, msg.ofs_y, msg.ofs_z),
                                   bool(msg.autosaved), msg.old_orientation, msg.new_orientation)
            self.results[msg.compass_id] = result
            self.progress.setdefault(msg.compass_id, 100 if result.ok else self.progress.get(msg.compass_id, 0))
            return [("result", result)]
        if kind == "COMMAND_ACK" and msg.command == mavlink.MAV_CMD_DO_START_MAG_CAL:
            if msg.result not in (mavlink.MAV_RESULT_ACCEPTED, mavlink.MAV_RESULT_IN_PROGRESS):
                self.started = False
                return [("rejected", result_text(msg.result))]
        return []


# --------------------------------------------------------------------------
# Radio
# --------------------------------------------------------------------------

RADIO_CHANNELS = 6  # CH1-CH6. CH7 is the Bind-button trim-save pulse and is left alone.
MIN_TRAVEL_US = 300  # less than this and the channel probably was not moved
PWM_LIMITS = (800, 2200)


@dataclass
class ChannelRange:
    lo: int = 10000
    hi: int = 0
    now: int = 0

    def add(self, pwm: int) -> None:
        if not PWM_LIMITS[0] - 100 <= pwm <= PWM_LIMITS[1] + 100:
            return  # 0 / 65535 = no signal on this channel
        self.now = pwm
        self.lo = min(self.lo, pwm)
        self.hi = max(self.hi, pwm)

    @property
    def seen(self) -> bool:
        return self.hi >= self.lo

    @property
    def travel(self) -> int:
        return self.hi - self.lo if self.seen else 0


@dataclass
class RadioPlan:
    changes: dict[str, float] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    rows: list[tuple[int, str, str, str]] = field(default_factory=list)  # (ch, role, old, new)


class RadioCal:
    def __init__(self, link=None, channels: int = RADIO_CHANNELS):
        self.link = link
        self.ranges = {ch: ChannelRange() for ch in range(1, channels + 1)}
        self.last_rc_time = 0.0

    def start(self) -> None:
        self.link.command(CMD_CAL, 0, 0, 0, 1)  # param4=1: radio calibration in progress
        self.link.set_message_rate(mavlink.MAVLINK_MSG_ID_RC_CHANNELS, 10)

    def stop(self) -> None:
        if self.link is not None:
            self.link.command(CMD_CAL, 0, 0, 0, 0)
            self.link.set_message_rate(mavlink.MAVLINK_MSG_ID_RC_CHANNELS, 0)

    def on_message(self, msg) -> bool:
        if msg.get_type() != "RC_CHANNELS":
            return False
        self.last_rc_time = time.monotonic()
        for ch, rng in self.ranges.items():
            rng.add(getattr(msg, f"chan{ch}_raw"))
        return True

    def plan(self, params: dict, roles: dict[int, str], throttle_ch: int) -> RadioPlan:
        """Work out RCn_MIN/MAX (and the throttle low point) from what was recorded.

        Stick centers (RCn_TRIM for roll, pitch and yaw) are not changed: on the ASCEND
        setup they are set by the Bind-button trim-save in MANUAL, which updates the
        servo trims at the same time. Changing them here alone would move the surfaces.
        """
        plan = RadioPlan()
        for ch, rng in self.ranges.items():
            role = roles.get(ch, f"Channel {ch}")
            old_min = params.get(f"RC{ch}_MIN")
            old_max = params.get(f"RC{ch}_MAX")
            old = f"{old_min:.0f}–{old_max:.0f}" if old_min is not None and old_max is not None else "?"
            if not rng.seen:
                plan.warnings.append(f"CH{ch} ({role}): no signal; left unchanged.")
                plan.rows.append((ch, role, old, "no signal"))
                continue
            if rng.travel < MIN_TRAVEL_US:
                plan.warnings.append(f"CH{ch} ({role}): moved only {rng.travel} µs; left unchanged. "
                                     "Move it to both ends and try again if it is used.")
                plan.rows.append((ch, role, old, "not moved"))
                continue
            plan.changes[f"RC{ch}_MIN"] = float(rng.lo)
            plan.changes[f"RC{ch}_MAX"] = float(rng.hi)
            new = f"{rng.lo}–{rng.hi}"
            if ch == throttle_ch:
                plan.changes[f"RC{ch}_TRIM"] = float(rng.lo)
                new += f" (low {rng.lo})"
            else:
                trim = params.get(f"RC{ch}_TRIM")
                if trim is not None and not rng.lo <= trim <= rng.hi:
                    plan.warnings.append(f"CH{ch} ({role}): its center ({trim:.0f}) is outside the new range. "
                                         "Save trims with the Bind button in MANUAL after writing.")
            plan.rows.append((ch, role, old, new))
        # Only keep values that actually change.
        plan.changes = {k: v for k, v in plan.changes.items() if params.get(k) != v}
        return plan
