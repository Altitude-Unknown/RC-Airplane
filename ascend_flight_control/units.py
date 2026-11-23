#!/usr/bin/env python3
"""
Display units for ASCEND Flight Control.

Everything inside the app (missions, MAVLink, parameters) stays in SI units:
metres and metres per second. These helpers convert only for display and
input, using the person's saved preference.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

SPEED_UNITS = {"m/s": 1.0, "km/h": 3.6, "mph": 2.2369363, "kn": 1.9438445}
ALT_UNITS = {"m": 1.0, "ft": 3.2808399}
VSPEED_UNITS = {"m/s": 1.0, "ft/min": 196.850394}

SPEED_NAMES = {"m/s": "Metres per second (m/s)", "km/h": "Kilometres per hour (km/h)",
               "mph": "Miles per hour (mph)", "kn": "Knots (kn)"}
ALT_NAMES = {"m": "Metres (m)", "ft": "Feet (ft)"}
VSPEED_NAMES = {"m/s": "Metres per second (m/s)", "ft/min": "Feet per minute (ft/min)"}

PRESETS = {
    "Metric": ("m/s", "m", "m/s"),
    "US (mph / ft)": ("mph", "ft", "ft/min"),
    "Aviation (knots / ft)": ("kn", "ft", "ft/min"),
}


def config_dir() -> Path:
    """Per-user settings folder (not inside the project, so it survives updates)."""
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "ASCEND Flight Control"
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(base) / "ASCEND Flight Control"
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "ascend-flight-control"


@dataclass
class UnitChoice:
    speed: str = "m/s"
    alt: str = "m"
    vspeed: str = "m/s"


class Units:
    def __init__(self, choice: UnitChoice | None = None, path: Path | None = None):
        self.path = path or (config_dir() / "settings.json")
        self.choice = choice or UnitChoice()
        self._listeners: list[Callable[[], None]] = []

    # -- persistence -------------------------------------------------------------

    @classmethod
    def load(cls, path: Path | None = None) -> "Units":
        units = cls(path=path)
        try:
            data = json.loads(units.path.read_text(encoding="utf-8")).get("units", {})
            units.choice = UnitChoice(
                speed=data.get("speed") if data.get("speed") in SPEED_UNITS else "m/s",
                alt=data.get("alt") if data.get("alt") in ALT_UNITS else "m",
                vspeed=data.get("vspeed") if data.get("vspeed") in VSPEED_UNITS else "m/s",
            )
        except (OSError, ValueError, AttributeError):
            pass  # first run or unreadable file: metric
        return units

    def save(self) -> None:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        data["units"] = asdict(self.choice)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def set(self, speed: str, alt: str, vspeed: str) -> None:
        self.choice = UnitChoice(speed, alt, vspeed)
        try:
            self.save()
        except OSError:
            pass  # still applies for this session
        for fn in self._listeners:
            fn()

    def subscribe(self, fn: Callable[[], None]) -> None:
        self._listeners.append(fn)

    # -- labels ------------------------------------------------------------------

    @property
    def speed_label(self) -> str:
        return self.choice.speed

    @property
    def alt_label(self) -> str:
        return self.choice.alt

    @property
    def vspeed_label(self) -> str:
        return self.choice.vspeed

    # -- conversions (SI in, display out; display in, SI out) ---------------------

    def speed(self, mps: float) -> float:
        return mps * SPEED_UNITS[self.choice.speed]

    def speed_si(self, value: float) -> float:
        return value / SPEED_UNITS[self.choice.speed]

    def alt(self, m: float) -> float:
        return m * ALT_UNITS[self.choice.alt]

    def alt_si(self, value: float) -> float:
        return value / ALT_UNITS[self.choice.alt]

    def vspeed(self, mps: float) -> float:
        return mps * VSPEED_UNITS[self.choice.vspeed]

    # -- formatting ----------------------------------------------------------------

    def fmt_speed(self, mps: float | None, unit: bool = True) -> str:
        if mps is None:
            return "—"
        text = f"{self.speed(mps):.0f}" if self.choice.speed != "m/s" else f"{mps:.1f}"
        return f"{text} {self.speed_label}" if unit else text

    def fmt_alt(self, m: float | None, unit: bool = True) -> str:
        if m is None:
            return "—"
        text = f"{self.alt(m):.0f}"
        return f"{text} {self.alt_label}" if unit else text

    def fmt_vspeed(self, mps: float | None, unit: bool = True) -> str:
        if mps is None:
            return "—"
        value = self.vspeed(mps)
        text = f"{value:+.0f}" if self.choice.vspeed == "ft/min" else f"{value:+.1f}"
        return f"{text} {self.vspeed_label}" if unit else text

    def fmt_distance(self, m: float | None) -> str:
        """Longer distances: m/km for metric; ft/mi (or ft/nm with knots) for feet."""
        if m is None:
            return "—"
        if self.choice.alt == "m":
            return f"{m:.0f} m" if m < 1000 else f"{m / 1000:.2f} km"
        ft = m * ALT_UNITS["ft"]
        if ft < 2000:
            return f"{ft:.0f} ft"
        if self.choice.speed == "kn":
            return f"{m / 1852:.2f} nm"
        return f"{m / 1609.344:.2f} mi"
