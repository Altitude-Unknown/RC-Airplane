#!/usr/bin/env python3
"""
Flight tab for ASCEND Flight Control: monitor a flight in progress.

- PrimaryFlightDisplay: glass-cockpit display drawn on a Tk canvas: attitude
  indicator (pitch ladder, roll scale), airspeed tape, altitude tape with a
  vertical speed bar, heading tape, mode and armed state.
- Readout tiles: speeds, altitudes, climb, throttle, distance home, target
  waypoint, flight time, GPS.
- Flight controller messages.
- A live map with the mission, the aircraft and its trail.

All telemetry arrives in SI units; the Units preference converts for display.
"""

from __future__ import annotations

import math
import time
import tkinter as tk
from tkinter import ttk

from map_view import MissionMap
from units import Units

# Glass-cockpit palette
PFD_BG = "#0b1220"
SKY = "#2f6db5"
GROUND = "#7a4a22"
HORIZON = "#ffffff"
TAPE_BG = "#111827"
TAPE_TEXT = "#e5e7eb"
TAPE_TICK = "#9ca3af"
VALUE_BOX = "#000000"
CYAN = "#22d3ee"
MAGENTA = "#e879f9"
AMBER = "#fbbf24"
GREEN = "#4ade80"
RED = "#f87171"
SYMBOL = "#facc15"

PANEL_BG = "#0f172a"
CARD_BG = "#16213a"
CARD_LABEL = "#94a3b8"
CARD_VALUE = "#f8fafc"

STALE_S = 2.0  # attitude older than this is shown as lost
FONT = "TkDefaultFont"


def _rot(px, py, cx, cy, cos_r, sin_r):
    dx, dy = px - cx, py - cy
    return cx + dx * cos_r - dy * sin_r, cy + dx * sin_r + dy * cos_r


class PrimaryFlightDisplay(tk.Canvas):
    def __init__(self, parent, units: Units, **kwargs):
        super().__init__(parent, bg=PFD_BG, highlightthickness=0, **kwargs)
        self.units = units
        self.airspeed_estimated = True

    # -- drawing ---------------------------------------------------------------

    def draw(self, st) -> None:
        self.delete("all")
        w, h = max(self.winfo_width(), 320), max(self.winfo_height(), 260)
        heading_h = 34
        speed_w, alt_w, vsi_w = 72, 78, 22
        ax0, ax1 = speed_w, w - alt_w - vsi_w
        ay0, ay1 = 0, h - heading_h
        cx, cy = (ax0 + ax1) / 2, (ay0 + ay1) / 2 + 6

        attitude_ok = st is not None and st.roll is not None and time.monotonic() - st.attitude_time < STALE_S
        roll = st.roll if attitude_ok else 0.0
        pitch = st.pitch if attitude_ok else 0.0
        self._attitude(ax0, ay0, ax1, ay1, cx, cy, roll, pitch)
        self._roll_scale(cx, cy, min(ax1 - ax0, ay1 - ay0) * 0.42, roll)
        self._aircraft_symbol(cx, cy)
        self._speed_tape(0, 0, speed_w, ay1, st)
        self._alt_tape(w - alt_w - vsi_w, 0, alt_w, ay1, st)
        self._vsi(w - vsi_w, 0, vsi_w, ay1, st)
        self._heading_tape(0, ay1, w, heading_h, st)
        self._annunciators(ax0, ax1, st)
        if not attitude_ok:
            self._no_data(cx, cy, st)

    def _attitude(self, x0, y0, x1, y1, cx, cy, roll, pitch):
        self.create_rectangle(x0, y0, x1, y1, fill=SKY, outline="")
        ppd = (y1 - y0) / 44.0  # pixels per degree of pitch (about ±22° visible)
        r = math.radians(roll)
        d = (math.cos(r), -math.sin(r))  # along the horizon, to the right
        n = (math.sin(r), math.cos(r))   # perpendicular, toward the ground
        hx, hy = cx + n[0] * pitch * ppd, cy + n[1] * pitch * ppd
        big = 3000
        ground = [hx - d[0] * big, hy - d[1] * big, hx + d[0] * big, hy + d[1] * big,
                  hx + d[0] * big + n[0] * big, hy + d[1] * big + n[1] * big,
                  hx - d[0] * big + n[0] * big, hy - d[1] * big + n[1] * big]
        self.create_polygon(ground, fill=GROUND, outline="")
        self.create_line(hx - d[0] * big, hy - d[1] * big, hx + d[0] * big, hy + d[1] * big,
                         fill=HORIZON, width=2)
        # Pitch ladder: every 5°, labels every 10°, within ±20° of the current pitch
        first = int(math.floor((pitch - 20) / 5.0)) * 5
        for a in range(first, first + 45, 5):
            if a == 0 or a < -90 or a > 90:
                continue
            half = 46 if a % 10 == 0 else 22
            px, py = cx + n[0] * (pitch - a) * ppd, cy + n[1] * (pitch - a) * ppd
            if not (y0 + 10 < py < y1 - 10) and abs(roll) < 60:
                continue
            self.create_line(px - d[0] * half, py - d[1] * half, px + d[0] * half, py + d[1] * half,
                             fill="#ffffff", width=2 if a % 10 == 0 else 1, dash=() if a > 0 else (5, 3))
            if a % 10 == 0:
                for side in (-1, 1):
                    tx, ty = px + d[0] * side * (half + 14), py + d[1] * side * (half + 14)
                    self.create_text(tx, ty, text=str(abs(a)), fill="#ffffff", font=(FONT, 10, "bold"),
                                     angle=-roll)
        # Keep the attitude drawing inside its area: cover spill-over above and below.
        self.create_rectangle(x0, y1, x1, y1 + 2000, fill=PFD_BG, outline="")

    def _roll_scale(self, cx, cy, radius, roll):
        top = cy - radius
        self.create_arc(cx - radius, cy - radius, cx + radius, cy + radius, start=30, extent=120,
                        style="arc", outline="#ffffff", width=2)
        for a in (-60, -45, -30, -20, -10, 0, 10, 20, 30, 45, 60):
            rad = math.radians(a)
            length = 12 if a in (-60, -30, 0, 30, 60) else 7
            x1, y1 = cx + radius * math.sin(rad), cy - radius * math.cos(rad)
            x2, y2 = cx + (radius + length) * math.sin(rad), cy - (radius + length) * math.cos(rad)
            self.create_line(x1, y1, x2, y2, fill="#ffffff", width=2)
        # Fixed index at the top, moving sky pointer that follows the horizon
        self.create_polygon(cx, top - 1, cx - 7, top - 13, cx + 7, top - 13, fill="#ffffff", outline="")
        rad = math.radians(-roll)
        px, py = cx + (radius - 2) * math.sin(rad), cy - (radius - 2) * math.cos(rad)
        c, s = math.cos(rad), math.sin(rad)
        pts = [_rot(px, py, px, py, c, s), _rot(px - 8, py + 13, px, py, c, s), _rot(px + 8, py + 13, px, py, c, s)]
        self.create_polygon([v for p in pts for v in p], fill=SYMBOL, outline="#000000")

    def _aircraft_symbol(self, cx, cy):
        for side in (-1, 1):
            x_in, x_out = cx + side * 24, cx + side * 70
            self.create_rectangle(min(x_in, x_out), cy - 3, max(x_in, x_out), cy + 3, fill=SYMBOL, outline="#000000")
        self.create_polygon(cx - 22, cy + 14, cx, cy, cx + 22, cy + 14, cx + 22, cy + 18, cx, cy + 6,
                            cx - 22, cy + 18, fill=SYMBOL, outline="#000000")
        self.create_rectangle(cx - 3, cy - 3, cx + 3, cy + 3, fill="#000000", outline=SYMBOL)

    def _tape(self, x, y, w, h, value, span, major, minor, label, fmt, align_right=False):
        """Vertical moving tape centered on `value` (display units)."""
        self.create_rectangle(x, y, x + w, y + h, fill=TAPE_BG, outline="#1f2937")
        mid = y + h / 2
        ppu = h / span
        start = math.floor((value - span / 2) / minor) * minor
        v = start
        while v <= value + span / 2 + minor:
            py = mid - (v - value) * ppu
            if y + 4 < py < y + h - 4:
                is_major = abs(v / major - round(v / major)) < 1e-6
                tick = 12 if is_major else 6
                if align_right:
                    self.create_line(x, py, x + tick, py, fill=TAPE_TICK, width=1)
                    if is_major:
                        self.create_text(x + tick + 4, py, text=fmt(v), anchor="w", fill=TAPE_TEXT, font=(FONT, 11))
                else:
                    self.create_line(x + w - tick, py, x + w, py, fill=TAPE_TICK, width=1)
                    if is_major:
                        self.create_text(x + w - tick - 4, py, text=fmt(v), anchor="e", fill=TAPE_TEXT, font=(FONT, 11))
            v += minor
        # Current value box
        bh = 30
        self.create_rectangle(x + 2, mid - bh / 2, x + w - 2, mid + bh / 2, fill=VALUE_BOX, outline="#ffffff", width=1)
        self.create_text(x + w / 2, mid, text=fmt(value), fill="#ffffff", font=(FONT, 16, "bold"))
        self.create_text(x + w / 2, y + 12, text=label, fill=CYAN, font=(FONT, 10, "bold"))

    def _speed_tape(self, x, y, w, h, st):
        u = self.units
        speed = st.airspeed if st is not None and st.airspeed is not None else None
        value = u.speed(speed) if speed is not None else 0.0
        span, major, minor = {"m/s": (20, 5, 1), "km/h": (80, 20, 5), "mph": (50, 10, 2), "kn": (40, 10, 2)}[u.speed_label]
        label = f"IAS {u.speed_label}" + ("*" if self.airspeed_estimated else "")
        self._tape(x, y, w, h, value, span, major, minor, label, lambda v: f"{v:.0f}")
        if speed is None:
            self.create_text(x + w / 2, y + h / 2, text="—", fill=AMBER, font=(FONT, 16, "bold"))
        gs = st.groundspeed if st is not None else None
        self.create_text(x + w / 2, y + h - 12, text=f"GS {u.fmt_speed(gs, unit=False)}", fill=GREEN, font=(FONT, 11, "bold"))

    def _alt_tape(self, x, y, w, h, st):
        u = self.units
        alt = st.alt_rel if st is not None else None
        value = u.alt(alt) if alt is not None else 0.0
        span, major, minor = (400, 100, 20) if u.alt_label == "ft" else (120, 20, 5)
        self._tape(x, y, w, h, value, span, major, minor, f"ALT {u.alt_label}", lambda v: f"{v:.0f}", align_right=True)
        if alt is None:
            self.create_text(x + w / 2, y + h / 2, text="—", fill=AMBER, font=(FONT, 16, "bold"))
        self.create_text(x + w / 2, y + h - 12, text="above home", fill=TAPE_TICK, font=(FONT, 9))

    def _vsi(self, x, y, w, h, st):
        u = self.units
        self.create_rectangle(x, y, x + w, y + h, fill="#0f172a", outline="#1f2937")
        mid = y + h / 2
        self.create_line(x, mid, x + w, mid, fill=TAPE_TICK)
        climb = st.climb if st is not None else None
        if climb is None:
            return
        full = 10.0 if u.vspeed_label == "m/s" else 2000.0
        frac = max(-1.0, min(1.0, u.vspeed(climb) / full))
        top = mid - frac * (h / 2 - 20)
        color = GREEN if climb >= 0 else AMBER
        self.create_rectangle(x + 5, min(mid, top), x + w - 5, max(mid, top), fill=color, outline="")
        self.create_text(x + w / 2, y + 12, text="VS", fill=CYAN, font=(FONT, 9, "bold"))

    def _heading_tape(self, x, y, w, h, st):
        self.create_rectangle(x, y, x + w, y + h, fill=TAPE_BG, outline="#1f2937")
        heading = st.yaw if st is not None and st.yaw is not None else None
        value = heading if heading is not None else 0.0
        mid = x + w / 2
        ppd = w / 80.0
        names = {0: "N", 90: "E", 180: "S", 270: "W"}
        start = int(math.floor((value - 40) / 5.0)) * 5
        for a in range(start, start + 90, 5):
            px = mid + (a - value) * ppd
            if not x + 4 < px < x + w - 4:
                continue
            deg = a % 360
            major = deg % 10 == 0
            self.create_line(px, y, px, y + (10 if major else 5), fill=TAPE_TICK)
            if deg % 30 == 0:
                self.create_text(px, y + 20, text=names.get(deg, str(deg // 10)), fill=TAPE_TEXT,
                                 font=(FONT, 11, "bold" if deg in names else "normal"))
        self.create_rectangle(mid - 30, y + 2, mid + 30, y + h - 2, fill=VALUE_BOX, outline="#ffffff")
        self.create_text(mid, y + h / 2, text="—" if heading is None else f"{value:03.0f}°", fill="#ffffff",
                         font=(FONT, 14, "bold"))

    def _annunciators(self, x0, x1, st):
        if st is None or not st.connected:
            self.create_text(x0 + 8, 10, text="NOT CONNECTED", anchor="nw", fill=AMBER, font=(FONT, 12, "bold"))
            return
        self.create_text(x0 + 8, 8, text=st.mode, anchor="nw", fill=GREEN, font=(FONT, 15, "bold"))
        armed = "ARMED" if st.armed else "DISARMED"
        self.create_text(x1 - 8, 8, text=armed, anchor="ne", fill=RED if st.armed else TAPE_TEXT,
                         font=(FONT, 13, "bold"))

    def _no_data(self, cx, cy, st):
        text = "NO ATTITUDE DATA" if st is not None and st.connected else "CONNECT TO SEE FLIGHT DATA"
        self.create_rectangle(cx - 120, cy - 52, cx + 120, cy - 22, fill="#000000", outline=AMBER)
        self.create_text(cx, cy - 37, text=text, fill=AMBER, font=(FONT, 12, "bold"))


class FlightTab(tk.Frame):
    def __init__(self, parent, units: Units):
        super().__init__(parent, bg=PANEL_BG)
        self.units = units
        self._last_log_len = 0
        self._last_log_time = None

        panes = ttk.Panedwindow(self, orient="horizontal")
        panes.pack(fill="both", expand=True)

        map_side = tk.Frame(panes, bg="#f3f6f8", padx=10, pady=10)
        self.map = MissionMap(map_side, on_add=None, on_select=None, live_view=True)
        self.map.pack(fill="both", expand=True)

        side = tk.Frame(panes, bg=PANEL_BG, padx=12, pady=12)
        panes.add(map_side, weight=3)
        panes.add(side, weight=2)

        self.pfd = PrimaryFlightDisplay(side, units, height=360)
        self.pfd.pack(fill="x")
        self.estimate_note = tk.Label(side, text="* Estimated airspeed: no airspeed sensor fitted",
                                      bg=PANEL_BG, fg=CARD_LABEL, font=(FONT, 10))
        self.estimate_note.pack(anchor="w", pady=(4, 8))

        grid = tk.Frame(side, bg=PANEL_BG)
        grid.pack(fill="x")
        self.tiles: dict[str, tk.Label] = {}
        names = [("groundspeed", "Ground speed"), ("airspeed", "Airspeed"), ("climb", "Climb rate"),
                 ("alt_rel", "Altitude (above home)"), ("alt_msl", "Altitude (sea level)"), ("throttle", "Throttle"),
                 ("home", "Distance to home"), ("target", "Target"), ("flight_time", "Flight time"),
                 ("gps", "GPS"), ("heading", "Heading"), ("battery", "Battery")]
        for i, (key, label) in enumerate(names):
            card = tk.Frame(grid, bg=CARD_BG, padx=10, pady=6)
            card.grid(row=i // 3, column=i % 3, sticky="nsew", padx=3, pady=3)
            tk.Label(card, text=label, bg=CARD_BG, fg=CARD_LABEL, font=(FONT, 10)).pack(anchor="w")
            value = tk.Label(card, text="—", bg=CARD_BG, fg=CARD_VALUE, font=(FONT, 16, "bold"))
            value.pack(anchor="w")
            self.tiles[key] = value
        for c in range(3):
            grid.columnconfigure(c, weight=1, uniform="tiles")

        tk.Label(side, text="Flight controller messages", bg=PANEL_BG, fg=CARD_LABEL,
                 font=(FONT, 10)).pack(anchor="w", pady=(10, 2))
        self.messages = tk.Text(side, height=6, bg="#0b1220", fg="#e2e8f0", relief="flat", wrap="word",
                                font="TkFixedFont", highlightthickness=0)
        self.messages.pack(fill="both", expand=True)
        for tag, color in (("emergency", RED), ("warning", AMBER), ("info", "#e2e8f0"), ("time", "#64748b")):
            self.messages.tag_configure(tag, foreground=color)
        self.messages.configure(state="disabled")

    # -- updates -----------------------------------------------------------------

    def update_view(self, st, target_text: str, home: tuple[float | None, float | None]):
        self.pfd.draw(st)
        u = self.units
        t = self.tiles
        if st is None or not st.connected:
            for label in t.values():
                label.configure(text="—", fg=CARD_VALUE)
            return
        t["groundspeed"].configure(text=u.fmt_speed(st.groundspeed))
        t["airspeed"].configure(text=u.fmt_speed(st.airspeed) + ("*" if self.pfd.airspeed_estimated else ""))
        t["climb"].configure(text=u.fmt_vspeed(st.climb),
                             fg=GREEN if (st.climb or 0) > 0.3 else AMBER if (st.climb or 0) < -0.3 else CARD_VALUE)
        t["alt_rel"].configure(text=u.fmt_alt(st.alt_rel))
        t["alt_msl"].configure(text=u.fmt_alt(st.alt_msl))
        t["throttle"].configure(text="—" if st.throttle is None else f"{st.throttle}%")
        t["heading"].configure(text="—" if st.yaw is None else f"{st.yaw:03.0f}°")
        t["home"].configure(text=u.fmt_distance(distance_m(st.lat, st.lon, *home)))
        t["target"].configure(text=target_text)
        if st.armed_since is not None:
            secs = int(time.monotonic() - st.armed_since)
            t["flight_time"].configure(text=f"{secs // 60}:{secs % 60:02d}")
        else:
            t["flight_time"].configure(text="not armed")
        fix = {0: "no GPS", 1: "no fix", 2: "2D", 3: "3D", 4: "DGPS", 5: "RTK float", 6: "RTK"}.get(st.gps_fix, "?")
        t["gps"].configure(text=f"{fix} · {st.satellites}", fg=GREEN if st.gps_fix >= 3 else AMBER)
        t["battery"].configure(text="—" if st.battery_v is None else f"{st.battery_v:.1f} V")
        self._update_messages(st)

    def _update_messages(self, st):
        log = st.log
        if not log or (len(log) == self._last_log_len and log[-1][0] == self._last_log_time):
            return
        new = [entry for entry in log if self._last_log_time is None or entry[0] > self._last_log_time]
        self._last_log_len, self._last_log_time = len(log), log[-1][0]
        self.messages.configure(state="normal")
        for wall, severity, text in new:
            tag = "emergency" if severity <= 3 else "warning" if severity == 4 else "info"
            self.messages.insert("end", time.strftime("%H:%M:%S ", time.localtime(wall)), "time")
            self.messages.insert("end", text + "\n", tag)
        lines = int(self.messages.index("end-1c").split(".")[0])
        if lines > 300:
            self.messages.delete("1.0", f"{lines - 300}.0")
        self.messages.see("end")
        self.messages.configure(state="disabled")


def distance_m(lat1, lon1, lat2, lon2) -> float | None:
    if None in (lat1, lon1, lat2, lon2):
        return None
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))
