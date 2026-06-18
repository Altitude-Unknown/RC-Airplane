#!/usr/bin/env python3
"""
Mission data model for the Walach Aviation Mission Planner.

This file intentionally keeps the mission format plain JSON-friendly data.
The future flight controller upload protocol can pack this into binary later,
but the editor should stay readable and easy to validate while the design is
still evolving.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


MISSION_VERSION = 1
DEFAULT_ALTITUDE_M = 100
DEFAULT_SPEED_MPS = 15

ACTION_TYPES = [
    "waypoint",
    "takeoff",
    "loiter",
    "set_servo",
    "camera_trigger",
    "return_home",
    "land",
]

EVENT_TYPES = [
    "none",
    "servo",
    "camera",
    "payload",
    "relay",
]


@dataclass
class WaypointEvent:
    type: str = "none"
    servo_channel: int | None = None
    servo_pwm: int | None = None
    hold_seconds: int = 0
    notes: str = ""


@dataclass
class Waypoint:
    id: int
    lat: float
    lon: float
    altitude_m: int = DEFAULT_ALTITUDE_M
    speed_mps: int = DEFAULT_SPEED_MPS
    action: str = "waypoint"
    event: WaypointEvent = field(default_factory=WaypointEvent)
    notes: str = ""


@dataclass
class MissionDefaults:
    altitude_m: int = DEFAULT_ALTITUDE_M
    speed_mps: int = DEFAULT_SPEED_MPS
    failsafe_action: str = "return_home"


@dataclass
class HomePoint:
    lat: float | None = None
    lon: float | None = None
    altitude_m: int = 0


@dataclass
class Mission:
    mission_version: int = MISSION_VERSION
    name: str = "Untitled Mission"
    vehicle: str = "Walach RC Aircraft"
    home: HomePoint = field(default_factory=HomePoint)
    defaults: MissionDefaults = field(default_factory=MissionDefaults)
    waypoints: list[Waypoint] = field(default_factory=list)

    def next_waypoint_id(self) -> int:
        used = {wp.id for wp in self.waypoints}
        candidate = 1
        while candidate in used:
            candidate += 1
        return candidate


def mission_to_dict(mission: Mission) -> dict[str, Any]:
    return asdict(mission)


def mission_from_dict(data: dict[str, Any]) -> Mission:
    defaults_data = data.get("defaults") or {}
    home_data = data.get("home") or {}
    waypoints = []

    for raw in data.get("waypoints") or []:
        event_data = raw.get("event") or {}
        waypoints.append(
            Waypoint(
                id=int(raw.get("id", len(waypoints) + 1)),
                lat=float(raw.get("lat", 0.0)),
                lon=float(raw.get("lon", 0.0)),
                altitude_m=int(raw.get("altitude_m", DEFAULT_ALTITUDE_M)),
                speed_mps=int(raw.get("speed_mps", DEFAULT_SPEED_MPS)),
                action=str(raw.get("action", "waypoint")),
                event=WaypointEvent(
                    type=str(event_data.get("type", "none")),
                    servo_channel=_optional_int(event_data.get("servo_channel")),
                    servo_pwm=_optional_int(event_data.get("servo_pwm")),
                    hold_seconds=int(event_data.get("hold_seconds", 0) or 0),
                    notes=str(event_data.get("notes", "")),
                ),
                notes=str(raw.get("notes", "")),
            )
        )

    return Mission(
        mission_version=int(data.get("mission_version", MISSION_VERSION)),
        name=str(data.get("name", "Untitled Mission")),
        vehicle=str(data.get("vehicle", "Walach RC Aircraft")),
        home=HomePoint(
            lat=_optional_float(home_data.get("lat")),
            lon=_optional_float(home_data.get("lon")),
            altitude_m=int(home_data.get("altitude_m", 0) or 0),
        ),
        defaults=MissionDefaults(
            altitude_m=int(defaults_data.get("altitude_m", DEFAULT_ALTITUDE_M)),
            speed_mps=int(defaults_data.get("speed_mps", DEFAULT_SPEED_MPS)),
            failsafe_action=str(defaults_data.get("failsafe_action", "return_home")),
        ),
        waypoints=waypoints,
    )


def validate_mission(mission: Mission) -> list[str]:
    issues = []
    if not mission.waypoints:
        issues.append("Mission has no waypoints.")

    ids = set()
    for index, waypoint in enumerate(mission.waypoints, start=1):
        label = f"Waypoint {index}"
        if waypoint.id in ids:
            issues.append(f"{label} has a duplicate ID.")
        ids.add(waypoint.id)

        if not -90 <= waypoint.lat <= 90:
            issues.append(f"{label} latitude is outside the valid range.")
        if not -180 <= waypoint.lon <= 180:
            issues.append(f"{label} longitude is outside the valid range.")
        if waypoint.altitude_m < 0:
            issues.append(f"{label} altitude must be zero or higher.")
        if waypoint.speed_mps < 0:
            issues.append(f"{label} speed must be zero or higher.")
        if waypoint.action not in ACTION_TYPES:
            issues.append(f"{label} uses an unknown action: {waypoint.action}.")
        if waypoint.event.type not in EVENT_TYPES:
            issues.append(f"{label} uses an unknown event: {waypoint.event.type}.")

    if mission.home.lat is not None and not -90 <= mission.home.lat <= 90:
        issues.append("Home latitude is outside the valid range.")
    if mission.home.lon is not None and not -180 <= mission.home.lon <= 180:
        issues.append("Home longitude is outside the valid range.")

    return issues


def _optional_int(value: Any) -> int | None:
    if value in ("", None):
        return None
    return int(value)


def _optional_float(value: Any) -> float | None:
    if value in ("", None):
        return None
    return float(value)
