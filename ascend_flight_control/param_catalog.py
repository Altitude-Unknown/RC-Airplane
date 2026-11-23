#!/usr/bin/env python3
"""
The curated Aircraft Settings shown to students, grouped in plain English.

Names, ranges and option values must exist in param_metadata/ArduPlane.json
(test_params.py checks this), so the editor always matches the firmware.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Setting:
    name: str
    label: str
    help: str
    options: dict[int, str] | None = None  # shown choices (value -> label); None = from metadata or number
    min: float | None = None  # overrides the metadata range for the curated view
    max: float | None = None
    scale: float = 1.0  # shown value = raw value * scale
    unit: str | None = None  # overrides the metadata unit
    caution: str = ""  # shown when the chosen value is one of caution_values
    caution_values: tuple = ()


@dataclass
class Group:
    title: str
    intro: str
    settings: list[Setting] = field(default_factory=list)


PLANE_MODES = {
    0: "Manual - no stabilization",
    5: "FBWA - self-leveling (recommended for learning)",
    6: "FBWB - self-leveling with altitude hold",
    7: "Cruise - holds heading and altitude",
    2: "Stabilize - levels when sticks are centered",
    3: "Training - limits bank and pitch",
    4: "Acro - rate control for aerobatics",
    8: "Autotune - tunes the gains while you fly",
    10: "Auto - flies the uploaded mission",
    11: "RTL - returns home and circles",
    12: "Loiter - circles where it is",
    1: "Circle - gentle circles",
    13: "Takeoff - climbs out automatically",
}

ON_OFF = {0: "Off", 1: "On"}

CATALOG: list[Group] = [
    Group(
        "Flight Modes",
        "What the mode switches on your transmitter do. CH5 picks between two modes; CH6 is an extra switch.",
        [
            Setting("FLTMODE1", "Mode switch down (CH5 low)",
                    "Flight mode when the CH5 switch is in the low position.", options=PLANE_MODES),
            Setting("FLTMODE6", "Mode switch up (CH5 high)",
                    "Flight mode when the CH5 switch is in the high position.", options=PLANE_MODES),
            Setting("RC6_OPTION", "CH6 switch",
                    "What the CH6 switch does when it is turned on. Off returns to the CH5 mode.",
                    options={0: "Nothing", 16: "Auto - fly the mission", 4: "RTL - return home",
                             107: "Autotune", 11: "Turn geofence on", 9: "Trigger camera",
                             28: "Relay 1 on/off", 208: "Flaps"}),
        ],
    ),
    Group(
        "Return Home",
        "How the plane comes back when it switches to RTL, either from a switch or a failsafe.",
        [
            Setting("RTL_ALTITUDE", "Return altitude",
                    "Height above home the plane climbs or descends to on its way back. -1 keeps the current height.",
                    min=-1, max=400),
            Setting("RTL_RADIUS", "Circle size at home",
                    "Radius of the circle flown over home. 0 uses the loiter radius below. Negative circles counter-clockwise.",
                    min=-500, max=500),
            Setting("WP_LOITER_RAD", "Loiter radius",
                    "Radius for loiter and circle. Negative circles counter-clockwise.", min=-500, max=500),
            Setting("WP_RADIUS", "Waypoint reached distance",
                    "How close the plane must get before a waypoint counts as reached.", min=5, max=200),
        ],
    ),
    Group(
        "Speed & Throttle",
        "The standard airplane has no airspeed sensor, so cruise throttle sets how fast it flies in automatic modes.",
        [
            Setting("TRIM_THROTTLE", "Cruise throttle",
                    "Throttle used for level flight in FBWB, Cruise, Auto and RTL. Raise it if the plane is slow or sinks."),
            Setting("THR_MAX", "Maximum throttle", "Highest throttle the autopilot will use."),
            Setting("THR_MIN", "Minimum throttle",
                    "Lowest throttle in automatic modes. Keep 0 unless the motor must keep spinning.", min=0, max=50),
            Setting("AIRSPEED_CRUISE", "Cruise airspeed",
                    "Target speed in automatic modes. Without an airspeed sensor it is only an estimate.", min=5, max=40),
            Setting("AIRSPEED_MIN", "Minimum airspeed",
                    "Slowest speed the autopilot will fly in automatic modes. Keep it safely above stall."),
            Setting("AIRSPEED_MAX", "Maximum airspeed", "Fastest speed the autopilot will fly in automatic modes."),
        ],
    ),
    Group(
        "Flight Limits",
        "How far the autopilot lets the plane bank and pitch in stabilized and automatic modes.",
        [
            Setting("ROLL_LIMIT_DEG", "Maximum bank angle", "Steepest bank allowed. Lower is gentler.", min=20, max=70),
            Setting("PTCH_LIM_MAX_DEG", "Maximum nose-up pitch", "Steepest climb allowed.", min=10, max=45),
            Setting("PTCH_LIM_MIN_DEG", "Maximum nose-down pitch", "Steepest dive allowed (a negative number).",
                    min=-45, max=-5),
        ],
    ),
    Group(
        "Takeoff & Landing",
        "Automatic takeoff (Takeoff mode or a takeoff waypoint) and landing behavior.",
        [
            Setting("TKOFF_THR_MINACC", "Launch detection",
                    "How hard a throw must be (forward acceleration) before the motor starts on a hand launch. 0 starts it right away.",
                    min=0, max=30),
            Setting("TKOFF_THR_DELAY", "Motor start delay",
                    "Wait after the launch is detected before the motor starts, so the propeller clears your hand.",
                    scale=0.1, unit="s", min=0, max=12.7),
            Setting("TKOFF_THR_MAX", "Takeoff throttle",
                    "Throttle used while climbing out. 0 uses maximum throttle."),
            Setting("TKOFF_ALT", "Takeoff mode altitude", "Height Takeoff mode climbs to before it circles."),
            Setting("LAND_FLARE_ALT", "Flare height",
                    "Height above ground where an automatic landing raises the nose to flare."),
        ],
    ),
    Group(
        "Failsafes",
        "What the plane does if it loses the radio link. Test these on the ground before flying.",
        [
            Setting("THR_FAILSAFE", "Radio-loss failsafe",
                    "Turns the radio-loss failsafe on. Leave this on.",
                    options={0: "Off", 1: "On", 2: "On, but only report it"},
                    caution="The plane will not react to losing the radio link.", caution_values=(0, 2)),
            Setting("FS_SHORT_ACTN", "After 1.5 seconds without radio",
                    "First reaction to a radio loss. Auto, Guided and Loiter keep going unless you pick otherwise.",
                    options={0: "Circle (keep going if in Auto)", 1: "Circle", 2: "Glide with motor off",
                             4: "FBWB", 3: "Do nothing"}),
            Setting("FS_LONG_ACTN", "After a long radio loss",
                    "What happens once the radio has been lost for the time below.",
                    options={1: "Return home", 0: "Keep going (RTL if in a manual mode)", 2: "Glide with motor off",
                             4: "Auto - fly the mission"}),
            Setting("FS_LONG_TIMEOUT", "Long radio-loss time", "Seconds without radio before the long action.",
                    min=1, max=120),
            Setting("FS_GCS_ENABL", "Telemetry-loss failsafe",
                    "Treats losing the ground station link as a failsafe. Only for flights that always use telemetry.",
                    options={0: "Off", 1: "On", 3: "Only in Auto"},
                    caution="The plane reacts whenever telemetry drops out, even with a good radio link.",
                    caution_values=(1, 3)),
        ],
    ),
    Group(
        "Geofence",
        "An invisible boundary. If the plane crosses it, the autopilot takes over.",
        [
            Setting("FENCE_ENABLE", "Geofence", "Turns the boundary on. Set the radius and ceiling first.",
                    options=ON_OFF),
            Setting("FENCE_ACTION", "When the fence is crossed", "What the autopilot does on a breach.",
                    options={1: "Return home", 0: "Warn only", 8: "Land if a landing is set up, else return home"}),
            Setting("FENCE_RADIUS", "Fence radius", "Distance from home the plane may fly.", min=30, max=2000),
            Setting("FENCE_ALT_MAX", "Fence ceiling",
                    "Highest altitude above home allowed. In the US, Part 107 limits flights to 400 ft (122 m).",
                    min=10, max=400),
            Setting("FENCE_TYPE", "Fence shape", "Which limits are active (shown as a sum of the selected boxes)."),
        ],
    ),
    Group(
        "Arming",
        "How the motor is armed. The plane will not arm until its safety checks pass.",
        [
            Setting("ARMING_RUDDER", "Arm with rudder stick",
                    "Arm by holding full right rudder with throttle down.",
                    options={0: "Off", 1: "Arm only", 2: "Arm and disarm"}),
        ],
    ),
]

# Parameters that project rules reserve. The full list asks before changing them.
PROTECTED = {
    "RC7_OPTION": "CH7 is the Bind-button trim-save on every ASCEND transmitter (RC7_OPTION 155). "
                  "Do not give CH7 another function.",
    "ARMING_SKIPCHK": "Skipping arming checks can let the plane arm without GPS, calibration or radio. "
                      "Leave this at 0 on the standard setup.",
    "FLTMODE_CH": "CH5 is the mode channel on every ASCEND transmitter.",
}


def curated_names() -> list[str]:
    return [s.name for g in CATALOG for s in g.settings]
