#!/usr/bin/env python3
"""
Convert ASCEND Flight Control missions to ArduPlane MAVLink mission items and
move them to/from the flight controller.

ArduPilot mission conventions used here:
- Item 0 is always the home position (ArduPilot replaces it with its own home).
- Waypoint altitudes are meters above home (MAV_FRAME_GLOBAL_RELATIVE_ALT_INT).
- Speed changes become MAV_CMD_DO_CHANGE_SPEED items placed before the
  waypoint that needs the new speed.
- Waypoint events become DO_* items placed after the waypoint, so they fire
  once the aircraft reaches it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import os

os.environ.setdefault("MAVLINK20", "1")  # mission_type and other v2 fields
from pymavlink import mavutil  # noqa: E402

from mission_schema import HomePoint, LoiterSettings, Mission, Waypoint, WaypointEvent, validate_loiter

mavlink = mavutil.mavlink

FRAME_ABS = mavlink.MAV_FRAME_GLOBAL_INT
FRAME_REL = mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT_INT
FRAME_MISSION = mavlink.MAV_FRAME_MISSION

TAKEOFF_PITCH_DEG = 15.0
# ArduPilot reports the float-frame equivalents of the *_INT frames we send.
FRAME_EQUIVALENT = {
    mavlink.MAV_FRAME_GLOBAL_INT: mavlink.MAV_FRAME_GLOBAL,
    mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT_INT: mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT,
    mavlink.MAV_FRAME_GLOBAL_TERRAIN_ALT_INT: mavlink.MAV_FRAME_GLOBAL_TERRAIN_ALT,
}
RELATIVE_FRAMES = {mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT, mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT_INT}
NAV_COMMANDS = {
    mavlink.MAV_CMD_NAV_WAYPOINT,
    mavlink.MAV_CMD_NAV_TAKEOFF,
    mavlink.MAV_CMD_NAV_LOITER_UNLIM,
    mavlink.MAV_CMD_NAV_LOITER_TURNS,
    mavlink.MAV_CMD_NAV_LOITER_TIME,
    mavlink.MAV_CMD_NAV_RETURN_TO_LAUNCH,
    mavlink.MAV_CMD_NAV_LAND,
}


@dataclass
class MissionItem:
    command: int
    frame: int = FRAME_REL
    params: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
    lat: float = 0.0
    lon: float = 0.0
    alt: float = 0.0
    source_wp: int | None = None  # waypoint id this item came from (for messages)
    raw_x: int | None = None  # param5 sent as-is (non-position commands)

    @property
    def x(self) -> int:
        if self.raw_x is not None:
            return self.raw_x
        return int(round(self.lat * 1e7))

    @property
    def y(self) -> int:
        return int(round(self.lon * 1e7))

    def describe(self) -> str:
        try:
            name = mavlink.enums["MAV_CMD"][self.command].name.replace("MAV_CMD_", "")
        except KeyError:
            name = f"CMD {self.command}"
        return name


@dataclass
class ConversionResult:
    items: list[MissionItem] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def mission_to_items(mission: Mission) -> ConversionResult:
    """Build the full ArduPlane item list, including home at index 0."""
    result = ConversionResult()
    home = mission.home
    if home.lat is None or home.lon is None:
        if mission.waypoints:
            home_lat, home_lon = mission.waypoints[0].lat, mission.waypoints[0].lon
            result.warnings.append("Home is not set; using the first waypoint as a placeholder home.")
        else:
            home_lat = home_lon = 0.0
    else:
        home_lat, home_lon = home.lat, home.lon
    result.items.append(
        MissionItem(mavlink.MAV_CMD_NAV_WAYPOINT, FRAME_ABS, lat=home_lat, lon=home_lon, alt=float(home.altitude_m))
    )

    if not mission.waypoints:
        result.errors.append("Mission has no waypoints.")
        return result

    if mission.waypoints[0].action != "takeoff":
        result.warnings.append(
            "First waypoint is not a takeoff. In AUTO the plane will only fly this mission if it is already airborne."
        )

    current_speed = mission.defaults.speed_mps
    for index, wp in enumerate(mission.waypoints, start=1):
        label = f"Waypoint {index}"

        if wp.speed_mps and wp.speed_mps != current_speed and wp.action not in ("return_home",):
            # param1 0 = airspeed, param3 -1 = leave throttle unchanged
            result.items.append(
                MissionItem(mavlink.MAV_CMD_DO_CHANGE_SPEED, FRAME_MISSION, (0, float(wp.speed_mps), -1, 0), source_wp=wp.id)
            )
            current_speed = wp.speed_mps

        nav = _nav_item(wp, label, result)
        if nav:
            result.items.append(nav)

        if wp.action == "set_servo":
            _append_servo(wp.event.servo_channel, wp.event.servo_pwm, wp, label, result)
        elif wp.action == "camera_trigger":
            result.items.append(_camera_item(wp))

        _append_event(wp, label, result)

        if wp.event.hold_seconds and wp.action != "loiter":
            result.warnings.append(
                f"{label}: hold time is ignored by planes except on loiter waypoints."
            )

    return result


def _nav_item(wp, label, result: ConversionResult) -> MissionItem | None:
    alt = float(wp.altitude_m)
    action = wp.action
    if action in ("waypoint", "set_servo", "camera_trigger"):
        return MissionItem(mavlink.MAV_CMD_NAV_WAYPOINT, lat=wp.lat, lon=wp.lon, alt=alt, source_wp=wp.id)
    if action == "takeoff":
        if alt <= 0:
            result.errors.append(f"{label}: takeoff altitude must be above zero.")
        return MissionItem(
            mavlink.MAV_CMD_NAV_TAKEOFF, params=(TAKEOFF_PITCH_DEG, 0, 0, 0), lat=wp.lat, lon=wp.lon, alt=alt, source_wp=wp.id
        )
    if action == "loiter":
        return _loiter_item(wp, label, alt, result)
    if action == "return_home":
        return MissionItem(mavlink.MAV_CMD_NAV_RETURN_TO_LAUNCH, source_wp=wp.id)
    if action == "land":
        return MissionItem(mavlink.MAV_CMD_NAV_LAND, lat=wp.lat, lon=wp.lon, alt=0.0, source_wp=wp.id)
    result.errors.append(f"{label}: unknown action '{action}'.")
    return None


def _loiter_item(wp, label, alt, result: ConversionResult) -> MissionItem | None:
    """ArduPlane loiter commands. Direction is the sign of param3 (negative = counter-clockwise).

    - forever: NAV_LOITER_UNLIM, param3 = radius (0 = WP_LOITER_RAD)
    - turns:   NAV_LOITER_TURNS, param1 = laps (whole, 1-255), param3 = radius.
               Radii above 255 m are stored in 10 m steps.
    - time:    NAV_LOITER_TIME, param1 = seconds. ArduPlane has no radius for this
               command and always circles at WP_LOITER_RAD; param3 = +/-1 sets direction.
    """
    lo: LoiterSettings = wp.loiter
    problems = validate_loiter(lo, label)
    if problems:
        result.errors.extend(problems)
        return None
    sign = 1.0 if lo.clockwise else -1.0
    where = dict(lat=wp.lat, lon=wp.lon, alt=alt, source_wp=wp.id)
    if lo.mode == "time":
        if lo.radius_m:
            result.warnings.append(f"{label}: timed loiters always use the default loiter radius "
                                   f"(WP_LOITER_RAD); the {lo.radius_m} m radius is not used.")
        return MissionItem(mavlink.MAV_CMD_NAV_LOITER_TIME, params=(float(lo.seconds), 0, sign, 0), **where)
    radius = lo.radius_m
    if lo.mode == "turns":
        if radius > 255 and radius % 10:
            rounded = int(round(radius / 10.0)) * 10
            result.warnings.append(f"{label}: ArduPlane stores lap radii above 255 m in 10 m steps; "
                                   f"{radius} m becomes {rounded} m.")
            radius = rounded
        return MissionItem(mavlink.MAV_CMD_NAV_LOITER_TURNS, params=(float(lo.turns), 0, sign * radius, 0), **where)
    result.warnings.append(f"{label}: loiters forever, until the flight mode is changed.")
    return MissionItem(mavlink.MAV_CMD_NAV_LOITER_UNLIM, params=(0, 0, sign * radius, 0), **where)


def _append_servo(channel, pwm, wp, label, result: ConversionResult):
    if channel is None or pwm is None:
        result.errors.append(f"{label}: servo actions need both a servo channel and a PWM value.")
        return
    if not 1 <= channel <= 16:
        result.errors.append(f"{label}: servo channel must be 1-16.")
        return
    if not 800 <= pwm <= 2200:
        result.errors.append(f"{label}: servo PWM must be 800-2200.")
        return
    result.items.append(
        MissionItem(mavlink.MAV_CMD_DO_SET_SERVO, FRAME_MISSION, (float(channel), float(pwm), 0, 0), source_wp=wp.id)
    )


def _camera_item(wp) -> MissionItem:
    # param5 (x) = 1 triggers the shutter once
    return MissionItem(mavlink.MAV_CMD_DO_DIGICAM_CONTROL, FRAME_MISSION, raw_x=1, source_wp=wp.id)


def _append_event(wp, label, result: ConversionResult):
    event = wp.event
    if event.type in ("none", ""):
        return
    if event.type in ("servo", "payload"):
        _append_servo(event.servo_channel, event.servo_pwm, wp, label, result)
    elif event.type == "camera":
        if wp.action != "camera_trigger":
            result.items.append(_camera_item(wp))
    elif event.type == "relay":
        if event.servo_channel is None:
            result.errors.append(f"{label}: relay events use the Servo Ch field as the relay number (1 = RELAY1).")
            return
        state = 0.0 if event.servo_pwm == 0 else 1.0
        result.items.append(
            MissionItem(mavlink.MAV_CMD_DO_SET_RELAY, FRAME_MISSION, (float(event.servo_channel - 1), state, 0, 0), source_wp=wp.id)
        )
    else:
        result.errors.append(f"{label}: unknown event '{event.type}'.")


def items_to_mission(items: list[MissionItem], name: str = "Downloaded Mission") -> tuple[Mission, list[str]]:
    """Rebuild an editable mission from FC items. Returns (mission, notes about skipped items)."""
    notes: list[str] = []
    mission = Mission(name=name)
    if items:
        home = items[0]
        mission.home = HomePoint(lat=home.lat, lon=home.lon, altitude_m=int(round(home.alt)))
    speed = mission.defaults.speed_mps
    last: Waypoint | None = None
    cmd = mavlink

    for seq, item in enumerate(items[1:], start=1):
        c = item.command
        if c == cmd.MAV_CMD_DO_CHANGE_SPEED:
            speed = round(item.params[1], 2)
            continue
        if c in NAV_COMMANDS:
            action = {
                cmd.MAV_CMD_NAV_WAYPOINT: "waypoint",
                cmd.MAV_CMD_NAV_TAKEOFF: "takeoff",
                cmd.MAV_CMD_NAV_LOITER_UNLIM: "loiter",
                cmd.MAV_CMD_NAV_LOITER_TURNS: "loiter",
                cmd.MAV_CMD_NAV_LOITER_TIME: "loiter",
                cmd.MAV_CMD_NAV_RETURN_TO_LAUNCH: "return_home",
                cmd.MAV_CMD_NAV_LAND: "land",
            }[c]
            lat, lon = item.lat, item.lon
            if c != cmd.MAV_CMD_NAV_RETURN_TO_LAUNCH and item.frame not in RELATIVE_FRAMES:
                notes.append(f"Item {seq} ({item.describe()}) uses frame {item.frame}, not altitude above home; "
                             "its altitude was loaded as-is and should be checked.")
            if c == cmd.MAV_CMD_NAV_RETURN_TO_LAUNCH:
                lat = mission.home.lat or 0.0
                lon = mission.home.lon or 0.0
            last = Waypoint(id=mission.next_waypoint_id(), lat=lat, lon=lon,
                            altitude_m=round(item.alt, 2), speed_mps=speed, action=action)
            p1, p3 = item.params[0], item.params[2]
            if c == cmd.MAV_CMD_NAV_LOITER_TIME:
                last.loiter = LoiterSettings(mode="time", seconds=int(round(p1)), clockwise=p3 >= 0)
            elif c == cmd.MAV_CMD_NAV_LOITER_TURNS:
                if 0 < p1 < 1:
                    notes.append(f"Item {seq}: {p1:g} laps rounded up to 1.")
                last.loiter = LoiterSettings(mode="turns", turns=max(1, int(round(p1))),
                                             radius_m=int(round(abs(p3))), clockwise=p3 >= 0)
            elif c == cmd.MAV_CMD_NAV_LOITER_UNLIM:
                last.loiter = LoiterSettings(mode="forever", radius_m=int(round(abs(p3))), clockwise=p3 >= 0)
            mission.waypoints.append(last)
            continue
        if last is None:
            notes.append(f"Item {seq} ({item.describe()}) comes before any waypoint and was skipped.")
            continue
        if c == cmd.MAV_CMD_DO_SET_SERVO:
            ch, pwm = int(item.params[0]), int(item.params[1])
            if last.action == "waypoint" and last.event.type == "none":
                last.action = "set_servo"
                last.event = WaypointEvent(servo_channel=ch, servo_pwm=pwm)
            elif last.event.type == "none":
                last.event = WaypointEvent(type="servo", servo_channel=ch, servo_pwm=pwm,
                                           hold_seconds=last.event.hold_seconds)
            else:
                notes.append(f"Item {seq} (extra servo command on one waypoint) was skipped.")
        elif c == cmd.MAV_CMD_DO_DIGICAM_CONTROL:
            if last.action == "waypoint":
                last.action = "camera_trigger"
            elif last.event.type == "none":
                last.event.type = "camera"
        elif c == cmd.MAV_CMD_DO_SET_RELAY and last.event.type == "none":
            last.event = WaypointEvent(type="relay", servo_channel=int(item.params[0]) + 1,
                                       servo_pwm=0 if item.params[1] == 0 else 1,
                                       hold_seconds=last.event.hold_seconds)
        else:
            notes.append(f"Item {seq} ({item.describe()}) is not supported by the editor and was skipped.")
    return mission, notes


# --------------------------------------------------------------------------
# Transfer protocol
# --------------------------------------------------------------------------

class MissionTransferError(Exception):
    pass


Progress = Callable[[str], None]
MISSION_MSGS = ["MISSION_REQUEST_INT", "MISSION_REQUEST", "MISSION_ACK", "MISSION_COUNT", "MISSION_ITEM_INT"]


def upload_mission(link, items: list[MissionItem], progress: Progress = lambda _m: None,
                   timeout: float = 2.0, retries: int = 5) -> None:
    """Send items with the MAVLink mission protocol. `link` is an FcLink."""
    count = len(items)
    link.drain_mission_messages()
    progress(f"Starting upload of {count} items")
    link.send(lambda mav: mav.mission_count_send(link.target_system, link.target_component, count,
                                                  mavlink.MAV_MISSION_TYPE_MISSION))
    sent_any = False
    tries = 0
    while True:
        msg = link.wait_mission_message(MISSION_MSGS, timeout)
        if msg is None:
            tries += 1
            if tries > retries:
                raise MissionTransferError("Flight controller stopped responding during upload.")
            if not sent_any:
                link.send(lambda mav: mav.mission_count_send(link.target_system, link.target_component, count,
                                                              mavlink.MAV_MISSION_TYPE_MISSION))
            # Otherwise wait; the FC re-requests the item it is missing.
            continue
        tries = 0
        kind = msg.get_type()
        if kind in ("MISSION_REQUEST_INT", "MISSION_REQUEST"):
            seq = msg.seq
            if not 0 <= seq < count:
                raise MissionTransferError(f"Flight controller requested invalid item {seq}.")
            sent_any = True
            item = items[seq]
            link.send(lambda mav, s=seq, it=item: mav.mission_item_int_send(
                link.target_system, link.target_component, s, it.frame, it.command,
                0, 1, *it.params, it.x, it.y, it.alt, mavlink.MAV_MISSION_TYPE_MISSION))
            progress(f"Sent item {seq + 1}/{count}")
        elif kind == "MISSION_ACK":
            if msg.type == mavlink.MAV_MISSION_ACCEPTED:
                if count > 1 and not sent_any:
                    raise MissionTransferError("Flight controller accepted the mission without requesting any items.")
                progress("Upload accepted")
                return
            reason = mavlink.enums["MAV_MISSION_RESULT"].get(msg.type)
            text = reason.name if reason else str(msg.type)
            if msg.type == mavlink.MAV_MISSION_NO_SPACE:
                text += " (if the flight controller just powered up, wait for it to finish initializing and try again)"
            raise MissionTransferError(f"Flight controller rejected the mission: {text}")


def download_mission(link, progress: Progress = lambda _m: None,
                     timeout: float = 2.0, retries: int = 5) -> list[MissionItem]:
    link.drain_mission_messages()
    progress("Requesting mission from flight controller")
    request_list = lambda mav: mav.mission_request_list_send(link.target_system, link.target_component,
                                                           mavlink.MAV_MISSION_TYPE_MISSION)
    link.send(request_list)
    count = None
    for _ in range(retries + 1):
        msg = link.wait_mission_message(["MISSION_COUNT"], timeout)
        if msg is not None:
            count = msg.count
            break
        link.send(request_list)
    if count is None:
        raise MissionTransferError("Flight controller did not report a mission count.")

    items: list[MissionItem] = []
    for seq in range(count):
        request = lambda mav, s=seq: mav.mission_request_int_send(link.target_system, link.target_component, s,
                                                                  mavlink.MAV_MISSION_TYPE_MISSION)
        for attempt in range(retries + 1):
            link.send(request)
            msg = link.wait_mission_message(["MISSION_ITEM_INT"], timeout)
            if msg is not None and msg.seq == seq:
                items.append(MissionItem(
                    command=msg.command, frame=msg.frame,
                    params=(msg.param1, msg.param2, msg.param3, msg.param4),
                    lat=msg.x / 1e7, lon=msg.y / 1e7, alt=msg.z, raw_x=msg.x,
                ))
                progress(f"Received item {seq + 1}/{count}")
                break
        else:
            raise MissionTransferError(f"Flight controller did not send item {seq}.")

    link.send(lambda mav: mav.mission_ack_send(link.target_system, link.target_component,
                                               mavlink.MAV_MISSION_ACCEPTED, mavlink.MAV_MISSION_TYPE_MISSION))
    progress(f"Downloaded {count} items")
    return items


def compare_items(sent: list[MissionItem], received: list[MissionItem]) -> list[str]:
    """Return differences. Home (item 0) is skipped: ArduPilot keeps its own home."""
    problems = []
    if len(sent) != len(received):
        return [f"Flight controller holds {len(received)} items, expected {len(sent)}."]
    for seq in range(1, len(sent)):
        a, b = sent[seq], received[seq]
        where = f"Item {seq} ({a.describe()})"
        if a.command != b.command:
            problems.append(f"{where}: command became {b.describe()}.")
            continue
        if (a.frame != FRAME_MISSION and a.command != mavlink.MAV_CMD_NAV_RETURN_TO_LAUNCH
                and FRAME_EQUIVALENT.get(a.frame, a.frame) != FRAME_EQUIVALENT.get(b.frame, b.frame)):
            problems.append(f"{where}: frame {a.frame} became {b.frame}.")
        if a.command in NAV_COMMANDS and a.command != mavlink.MAV_CMD_NAV_RETURN_TO_LAUNCH:
            if abs(a.x - b.x) > 1 or abs(a.y - b.y) > 1:
                problems.append(f"{where}: position changed.")
            if abs(a.alt - b.alt) > 0.1:
                problems.append(f"{where}: altitude {a.alt} became {b.alt}.")
        if a.raw_x is not None and a.raw_x != b.x:
            problems.append(f"{where}: param5 {a.raw_x} became {b.x}.")
        for i, (pa, pb) in enumerate(zip(a.params, b.params), start=1):
            if abs(pa - pb) > 1e-3:
                problems.append(f"{where}: param{i} {pa} became {pb}.")
    return problems
