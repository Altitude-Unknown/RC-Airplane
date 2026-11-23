#!/usr/bin/env python3
"""
MAVLink connection to an ArduPilot flight controller for ASCEND Flight Control.

One background thread owns all reads. It keeps a live vehicle status snapshot
and routes mission-protocol messages into a queue that mission transfers read
from. Sends from any thread go through a lock.
"""

from __future__ import annotations

import math
import queue
import threading
import time
from dataclasses import dataclass, field
from typing import Callable

import os

os.environ.setdefault("MAVLINK20", "1")  # mission_type and other v2 fields
from pymavlink import mavutil  # noqa: E402

mavlink = mavutil.mavlink

GCS_SYSTEM_ID = 255
GCS_COMPONENT_ID = mavlink.MAV_COMP_ID_MISSIONPLANNER
HEARTBEAT_LOST_S = 3.0
MISSION_TYPES = {"MISSION_REQUEST_INT", "MISSION_REQUEST", "MISSION_ACK", "MISSION_COUNT", "MISSION_ITEM_INT"}


@dataclass
class VehicleStatus:
    connected: bool = False
    last_heartbeat: float = 0.0
    system_id: int = 0
    armed: bool = False
    mode: str = "?"
    gps_fix: int = 0
    satellites: int = 0
    battery_v: float | None = None
    lat: float | None = None
    lon: float | None = None
    heading: float | None = None
    messages: list[str] = field(default_factory=list)  # recent STATUSTEXT
    # Flight data for the Flight tab (SI units, degrees for angles)
    roll: float | None = None
    pitch: float | None = None
    yaw: float | None = None
    attitude_time: float = 0.0  # monotonic time of the last ATTITUDE
    airspeed: float | None = None
    groundspeed: float | None = None
    climb: float | None = None
    throttle: int | None = None
    alt_rel: float | None = None  # metres above home
    alt_msl: float | None = None
    wp_seq: int | None = None
    wp_dist: float | None = None
    home_lat: float | None = None
    home_lon: float | None = None
    armed_since: float | None = None  # monotonic time the vehicle armed
    log: list[tuple[float, int, str]] = field(default_factory=list)  # (wall time, severity, text)

    def summary(self) -> str:
        if not self.connected:
            return "No heartbeat"
        fix = {0: "no GPS", 1: "no fix", 2: "2D", 3: "3D", 4: "DGPS", 5: "RTK float", 6: "RTK"}.get(self.gps_fix, str(self.gps_fix))
        batt = f"  {self.battery_v:.1f} V" if self.battery_v is not None else ""
        return f"{'ARMED' if self.armed else 'Disarmed'}  {self.mode}  GPS {fix} ({self.satellites} sats){batt}"


def list_connection_choices() -> list[str]:
    """Serial ports plus the usual SITL/telemetry network endpoints."""
    ports = []
    try:
        from serial.tools import list_ports
        for port in list_ports.comports():
            if "Bluetooth" in port.device:
                continue
            ports.append(port.device)
    except Exception:
        pass
    return ports + ["tcp:127.0.0.1:5760", "udp:127.0.0.1:14550"]


class FcLink:
    def __init__(self, device: str, baud: int = 115200,
                 on_status: Callable[[VehicleStatus], None] | None = None):
        self.device = device
        self.baud = baud
        self.on_status = on_status
        self.status = VehicleStatus()
        self.target_system = 1
        self.target_component = 1
        self._conn = None
        self._send_lock = threading.Lock()
        self._mission_queue: queue.Queue = queue.Queue()
        self._param_queue: queue.Queue = queue.Queue()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # -- lifecycle ---------------------------------------------------------

    def open(self, wait_heartbeat_s: float = 10.0) -> None:
        self._conn = mavutil.mavlink_connection(
            self.device, baud=self.baud, source_system=GCS_SYSTEM_ID,
            source_component=GCS_COMPONENT_ID, autoreconnect=True,
        )
        hb = self._conn.wait_heartbeat(timeout=wait_heartbeat_s)
        if hb is None:
            self._conn.close()
            self._conn = None
            raise ConnectionError(f"No heartbeat from {self.device} within {wait_heartbeat_s:.0f} s.")
        self.target_system = self._conn.target_system
        self.target_component = self._conn.target_component or 1
        self._handle(hb)
        self._request_streams()
        self._thread = threading.Thread(target=self._run, name="fc-link", daemon=True)
        self._thread.start()

    def close(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
        if self._conn:
            self._conn.close()
        self._conn = None
        self.status.connected = False

    # -- sending -----------------------------------------------------------

    def send(self, fn: Callable) -> None:
        """Call fn(mav) under the send lock, e.g. link.send(lambda mav: mav.ping_send(...))."""
        if not self._conn:
            raise ConnectionError("Not connected.")
        with self._send_lock:
            fn(self._conn.mav)

    def _request_streams(self) -> None:
        # Ask for status/position streams at modest rates on this link.
        for msg_id, hz in (
            (mavlink.MAVLINK_MSG_ID_SYS_STATUS, 1),
            (mavlink.MAVLINK_MSG_ID_GPS_RAW_INT, 2),
            (mavlink.MAVLINK_MSG_ID_GLOBAL_POSITION_INT, 5),
            (mavlink.MAVLINK_MSG_ID_ATTITUDE, 10),  # smooth attitude indicator; ~400 B/s
            (mavlink.MAVLINK_MSG_ID_VFR_HUD, 5),
            (mavlink.MAVLINK_MSG_ID_NAV_CONTROLLER_OUTPUT, 2),
            (mavlink.MAVLINK_MSG_ID_MISSION_CURRENT, 1),
            (mavlink.MAVLINK_MSG_ID_HOME_POSITION, 0.5),
        ):
            self.send(lambda mav, m=msg_id, h=hz: mav.command_long_send(
                self.target_system, self.target_component, mavlink.MAV_CMD_SET_MESSAGE_INTERVAL,
                0, m, 1e6 / h, 0, 0, 0, 0, 0))

    # -- mission message routing ---------------------------------------------

    def drain_mission_messages(self) -> None:
        while True:
            try:
                self._mission_queue.get_nowait()
            except queue.Empty:
                return

    def wait_mission_message(self, types: list[str], timeout: float):
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            try:
                msg = self._mission_queue.get(timeout=remaining)
            except queue.Empty:
                return None
            if msg.get_type() in types:
                return msg

    # -- parameter message routing -------------------------------------------

    def drain_param_messages(self) -> None:
        while True:
            try:
                self._param_queue.get_nowait()
            except queue.Empty:
                return

    def wait_param_message(self, timeout: float):
        try:
            return self._param_queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def reboot(self) -> None:
        """Reboot the autopilot. Caller must make sure the vehicle is disarmed."""
        self.send(lambda mav: mav.command_long_send(
            self.target_system, self.target_component, mavlink.MAV_CMD_PREFLIGHT_REBOOT_SHUTDOWN,
            0, 1, 0, 0, 0, 0, 0, 0))

    # -- reader thread -----------------------------------------------------

    def _run(self) -> None:
        last_hb_sent = 0.0
        while not self._stop.is_set():
            now = time.monotonic()
            if now - last_hb_sent >= 1.0:
                try:
                    self.send(lambda mav: mav.heartbeat_send(
                        mavlink.MAV_TYPE_GCS, mavlink.MAV_AUTOPILOT_INVALID, 0, 0, 0))
                except Exception:
                    pass
                last_hb_sent = now
            try:
                msg = self._conn.recv_match(blocking=True, timeout=0.2)
            except Exception:
                msg = None
            if msg is not None:
                self._handle(msg)
            if self.status.connected and time.monotonic() - self.status.last_heartbeat > HEARTBEAT_LOST_S:
                self.status.connected = False
                self._notify()

    def _handle(self, msg) -> None:
        kind = msg.get_type()
        if kind == "BAD_DATA":
            return
        if msg.get_srcSystem() != self.target_system:
            return
        if kind == "PARAM_VALUE":
            self._param_queue.put(msg)
            return
        if kind in MISSION_TYPES:
            if getattr(msg, "target_system", GCS_SYSTEM_ID) == GCS_SYSTEM_ID:
                self._mission_queue.put(msg)
            return
        s = self.status
        changed = False
        if kind == "HEARTBEAT" and msg.get_srcComponent() == self.target_component:
            s.connected = True
            s.last_heartbeat = time.monotonic()
            s.system_id = msg.get_srcSystem()
            armed = bool(msg.base_mode & mavlink.MAV_MODE_FLAG_SAFETY_ARMED)
            if armed and not s.armed:
                s.armed_since = time.monotonic()
            elif not armed:
                s.armed_since = None
            s.armed = armed
            s.mode = mavutil.mode_string_v10(msg)
            changed = True
        elif kind == "GPS_RAW_INT":
            s.gps_fix, s.satellites = msg.fix_type, msg.satellites_visible
            changed = True
        elif kind == "GLOBAL_POSITION_INT":
            s.alt_rel = msg.relative_alt / 1000.0
            s.alt_msl = msg.alt / 1000.0
            if s.gps_fix >= 2 and (msg.lat or msg.lon):
                s.lat, s.lon = msg.lat / 1e7, msg.lon / 1e7
                s.heading = None if msg.hdg == 65535 else (msg.hdg / 100.0) % 360.0
            else:
                s.lat = s.lon = s.heading = None
            changed = True
        elif kind == "SYS_STATUS":
            s.battery_v = msg.voltage_battery / 1000.0 if msg.voltage_battery not in (0, 0xFFFF) else None
            changed = True
        elif kind == "STATUSTEXT":
            s.messages = (s.messages + [msg.text])[-20:]
            s.log = (s.log + [(time.time(), msg.severity, msg.text)])[-200:]
            changed = True
        elif kind == "ATTITUDE":
            s.roll, s.pitch, s.yaw = (math.degrees(msg.roll), math.degrees(msg.pitch),
                                      math.degrees(msg.yaw) % 360.0)
            s.attitude_time = time.monotonic()
            changed = True
        elif kind == "VFR_HUD":
            s.airspeed, s.groundspeed, s.climb, s.throttle = msg.airspeed, msg.groundspeed, msg.climb, msg.throttle
            changed = True
        elif kind == "NAV_CONTROLLER_OUTPUT":
            s.wp_dist = float(msg.wp_dist)
            changed = True
        elif kind == "MISSION_CURRENT":
            s.wp_seq = msg.seq
            changed = True
        elif kind == "HOME_POSITION":
            s.home_lat, s.home_lon = msg.latitude / 1e7, msg.longitude / 1e7
            changed = True
        if changed:
            self._notify()

    def _notify(self) -> None:
        if self.on_status:
            try:
                self.on_status(self.status)
            except Exception:
                pass
