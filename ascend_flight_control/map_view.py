#!/usr/bin/env python3
"""
Mission map for ASCEND Flight Control, drawn inside the app with tkintermapview
(OpenStreetMap tiles on a Tk canvas; no browser needed).

- Click the map to add a waypoint; click a waypoint to select it.
- Numbered waypoint markers, the route line and the home point.
- The aircraft's live position and heading while connected.
"""

from __future__ import annotations

import math
import tkinter as tk
from tkinter import ttk
from typing import Callable

from PIL import Image, ImageDraw, ImageFont, ImageTk

from mac_gestures import install_pinch_zoom

try:
    import tkintermapview
except ImportError:  # shown as a message in the map area
    tkintermapview = None

TEAL = "#0f7f8f"
ORANGE = "#c2410c"
HOME = "#1f2937"
AIRCRAFT = "#2563eb"
DEFAULT_CENTER = (39.7392, -104.9903)
USER_AGENT = "ASCEND-Flight-Control/1.0"
SS = 3  # supersampling for smooth icon edges


def _font(size: int):
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # Pillow < 10.1
        return ImageFont.load_default()


def circle_icon(text: str, fill: str, diameter: int = 26) -> ImageTk.PhotoImage:
    d = diameter * SS
    img = Image.new("RGBA", (d, d), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse((SS, SS, d - SS, d - SS), fill="#ffffff")
    draw.ellipse((3 * SS, 3 * SS, d - 3 * SS, d - 3 * SS), fill=fill)
    font = _font(int(12 * SS) if len(text) < 3 else int(10 * SS))
    draw.text((d / 2, d / 2), text, fill="#ffffff", font=font, anchor="mm")
    return ImageTk.PhotoImage(img.resize((diameter, diameter), Image.LANCZOS))


def aircraft_icon(heading_deg: float, size: int = 34) -> ImageTk.PhotoImage:
    d = size * SS
    img = Image.new("RGBA", (d, d), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    c = d / 2
    # Arrow pointing up (north), then rotated to the heading.
    pts = [(c, 2 * SS), (d - 6 * SS, d - 4 * SS), (c, d - 11 * SS), (6 * SS, d - 4 * SS)]
    draw.polygon(pts, fill=AIRCRAFT, outline="#ffffff", width=2 * SS)
    img = img.rotate(-heading_deg, resample=Image.BICUBIC)
    return ImageTk.PhotoImage(img.resize((size, size), Image.LANCZOS))


class MissionMap(tk.Frame):
    def __init__(self, parent, on_add: Callable[[float, float], None] | None,
                 on_select: Callable[[int], None] | None, live_view: bool = False):
        """live_view=True: the Flight tab's map (no editing, follows the aircraft, shows a trail)."""
        super().__init__(parent, bg="#f3f6f8")
        self.live_view = live_view
        self._trail = None
        self._trail_points: list[tuple[float, float]] = []
        self.on_add = on_add
        self.on_select = on_select
        self._icons: dict = {}
        self._markers: list = []
        self._path = None
        self._circles: list = []
        self._home_marker = None
        self._aircraft_marker = None
        self._aircraft_heading_drawn: float | None = None
        self._aircraft_pos: tuple[float, float] | None = None
        self._signature = None
        self._suppress_click = False
        self._fitted = True  # only fit after reset_fit() (Open / Download), not on clicks
        self._rendering = False
        self._pending_render = None
        self._waypoints: list = []

        bar = tk.Frame(self, bg="#f3f6f8")
        bar.pack(fill="x", pady=(0, 6))
        hint = ("Live view · drag to move · scroll or +/− to zoom" if live_view else
                "Click the map to add a waypoint · drag to move · scroll or +/− to zoom")
        self.hint = tk.Label(bar, text=hint,
                             bg="#f3f6f8", fg="#60707d", font=("TkDefaultFont", 12))
        self.hint.pack(side="left")
        self.aircraft_button = ttk.Button(bar, text="Go to Aircraft", command=self.go_to_aircraft, state="disabled")
        self.aircraft_button.pack(side="right")
        ttk.Button(bar, text="Fit Mission", command=self.fit_mission).pack(side="right", padx=(0, 6))
        self.follow_var = tk.BooleanVar(value=live_view)
        ttk.Checkbutton(bar, text="Follow aircraft", variable=self.follow_var).pack(side="right", padx=(0, 12))
        if live_view:
            ttk.Button(bar, text="Clear Trail", command=self.clear_trail).pack(side="right", padx=(0, 12))

        if tkintermapview is None:
            self.map = None
            tk.Label(self, text="The in-app map needs the tkintermapview package.\n\n"
                                "Install it with:  pip install -r requirements.txt",
                     bg="#ffffff", fg="#17212b", font=("TkDefaultFont", 13), justify="center"
                     ).pack(fill="both", expand=True)
            return

        holder = tk.Frame(self, bg="#dde3e8", padx=1, pady=1)
        holder.pack(fill="both", expand=True)
        self.map = tkintermapview.TkinterMapView(holder, corner_radius=0, user_agent=USER_AGENT)
        self.map.pack(fill="both", expand=True)
        self.map.set_position(*DEFAULT_CENTER)
        self.map.set_zoom(13)
        self.map.add_left_click_map_command(self._map_clicked)
        # Runs before the map's own release handler; remembers if the press hit a map control.
        self.map.canvas.bind("<Button-1>", self._on_press, add="+")
        self._install_zoom_controls()
        tk.Label(holder, text="© OpenStreetMap contributors", bg="#ffffff", fg="#60707d",
                 font=("TkDefaultFont", 10)).place(relx=1.0, rely=1.0, anchor="se")

    # -- events --------------------------------------------------------------

    # -- zoom and pan -----------------------------------------------------------

    def _install_zoom_controls(self):
        """Keyboard zoom/pan everywhere, plus trackpad pinch on macOS when pyobjc is installed.

        Already provided by tkintermapview: scroll wheel / two-finger scroll (all platforms),
        Ctrl+wheel (Windows precision-touchpad pinch arrives this way), Button-4/5 (Linux/Pi).
        """
        canvas = self.map.canvas
        canvas.configure(takefocus=1)
        canvas.bind("<Button-1>", lambda _e: canvas.focus_set(), add="+")
        for key in ("<plus>", "<equal>", "<KP_Add>"):
            canvas.bind(key, lambda _e: self.zoom_by(1))
        for key in ("<minus>", "<underscore>", "<KP_Subtract>"):
            canvas.bind(key, lambda _e: self.zoom_by(-1))
        for key, dx, dy in (("<Left>", -1, 0), ("<Right>", 1, 0), ("<Up>", 0, -1), ("<Down>", 0, 1)):
            canvas.bind(key, lambda _e, x=dx, y=dy: self.pan_by(x, y))
        self.pinch_enabled = install_pinch_zoom(canvas, self._on_pinch)
        if self.pinch_enabled:
            self.hint.configure(text=self.hint.cget("text").replace("scroll or +/− to zoom", "pinch or scroll to zoom"))

    def zoom_by(self, steps: float, rel_x: float = 0.5, rel_y: float = 0.5):
        self.map.set_zoom(self.map.zoom + steps, relative_pointer_x=rel_x, relative_pointer_y=rel_y)

    def _on_pinch(self, magnification: float, x: int, y: int):
        width, height = max(1, self.map.width), max(1, self.map.height)
        # A full pinch-out is roughly magnification 1.0; make that about 3 zoom levels.
        self.zoom_by(magnification * 3.0, min(max(x / width, 0.0), 1.0), min(max(y / height, 0.0), 1.0))

    def pan_by(self, dx: int, dy: int):
        """Move the view a quarter of its width/height per key press."""
        w, h = self.map.width, self.map.height
        lat, lon = self.map.convert_canvas_coords_to_decimal_coords(w / 2 + dx * w / 4, h / 2 + dy * h / 4)
        self.map.set_position(lat, lon)

    def _control_items(self) -> set:
        """Canvas item ids of the +/- zoom buttons (looked up each time; redraws make new ids)."""
        ids = set()
        for name in ("button_zoom_in", "button_zoom_out"):
            button = getattr(self.map, name, None)
            for attr in ("canvas_rect", "canvas_text"):
                item = getattr(button, attr, None)
                if item is not None:
                    ids.add(item)
        return ids

    def _on_press(self, event):
        hit = set(self.map.canvas.find_overlapping(event.x - 1, event.y - 1, event.x + 1, event.y + 1))
        if hit & self._control_items():
            self._suppress_click = True
            self.after(400, lambda: setattr(self, "_suppress_click", False))

    def _map_clicked(self, coords):
        if self._suppress_click:  # the click landed on a marker or a zoom button
            self._suppress_click = False
            return
        if self.on_add is not None:
            self.on_add(coords[0], coords[1])

    def _marker_clicked(self, marker):
        self._suppress_click = True
        # If the press turns into a drag there is no click to swallow; clear the guard.
        self.after(400, lambda: setattr(self, "_suppress_click", False))
        if marker.data is not None and self.on_select is not None:
            self.on_select(marker.data)

    # -- mission -------------------------------------------------------------

    def icon(self, key, factory):
        if key not in self._icons:
            self._icons[key] = factory()
        return self._icons[key]

    def render(self, mission, selected_id, default_loiter_radius: int = 60):
        if self.map is None:
            return
        if self._rendering:
            # tkintermapview's marker.delete() runs the Tk event loop, so another redraw
            # can arrive mid-render. Defer it instead of racing over the same markers.
            self._pending_render = (mission, selected_id, default_loiter_radius)
            return
        self._rendering = True
        try:
            self._render(mission, selected_id, default_loiter_radius)
        finally:
            self._rendering = False
        if self._pending_render is not None:
            args, self._pending_render = self._pending_render, None
            self.after_idle(lambda: self.render(*args))

    def _render(self, mission, selected_id, default_loiter_radius):
        waypoints = [(wp.id, wp.lat, wp.lon, wp.action) for wp in mission.waypoints]
        circles = [(wp.lat, wp.lon, loiter_radius(wp, default_loiter_radius))
                   for wp in mission.waypoints if wp.action == "loiter"]
        home = (mission.home.lat, mission.home.lon)
        signature = (tuple(waypoints), tuple(circles), home, selected_id)
        if signature == self._signature:
            return
        self._signature = signature
        self._waypoints = waypoints

        # Detach everything first, then delete, so nothing can be orphaned.
        old = self._markers + [m for m in (self._home_marker,) if m is not None]
        old_shapes = self._circles + [p for p in (self._path,) if p is not None]
        self._markers, self._home_marker, self._path, self._circles = [], None, None, []
        for shape in old_shapes:
            shape.delete()
        for marker in old:
            marker.delete()

        for lat, lon, radius in circles:
            circle = self.map.set_polygon(circle_points(lat, lon, radius), outline_color=TEAL,
                                          fill_color=None, border_width=2)
            if circle.canvas_polygon is not None:
                self.map.canvas.itemconfigure(circle.canvas_polygon, dash=(6, 4))
            self._circles.append(circle)

        if home[0] is not None and home[1] is not None:
            self._home_marker = self.map.set_marker(
                home[0], home[1], icon=self.icon("home", lambda: circle_icon("H", HOME, 24)))

        positions = []
        for number, (wp_id, lat, lon, _action) in enumerate(waypoints, start=1):
            selected = wp_id == selected_id
            color = ORANGE if selected else TEAL
            icon = self.icon((number, selected), lambda n=number, c=color: circle_icon(str(n), c))
            self._markers.append(self.map.set_marker(lat, lon, icon=icon, data=wp_id, command=self._marker_clicked))
            positions.append((lat, lon))

        if len(positions) >= 2:
            self._path = self.map.set_path(positions, color=TEAL, width=3)

        if not self._fitted and positions:
            self._fitted = True
            self.after(50, self.fit_mission)
        self._raise_aircraft()

    def fit_mission(self):
        if self.map is None:
            return
        points = [(lat, lon) for _id, lat, lon, _a in self._waypoints]
        if not points:
            if self._aircraft_pos:
                self.go_to_aircraft()
            return
        if len(points) == 1:
            self.map.set_position(*points[0])
            self.map.set_zoom(16)
            return
        lats = [p[0] for p in points]
        lons = [p[1] for p in points]
        pad_lat = max(0.0008, (max(lats) - min(lats)) * 0.15)
        pad_lon = max(0.0008, (max(lons) - min(lons)) * 0.15)
        self.map.fit_bounding_box((max(lats) + pad_lat, min(lons) - pad_lon),
                                  (min(lats) - pad_lat, max(lons) + pad_lon))

    def reset_fit(self):
        """Fit to the next mission that is drawn (after Open / Download)."""
        self._fitted = False
        self._signature = None

    # -- aircraft --------------------------------------------------------------

    def set_aircraft(self, lat: float | None, lon: float | None, heading: float | None):
        if self.map is None:
            return
        if lat is None or lon is None:
            self.clear_aircraft()
            return
        first = self._aircraft_pos is None
        self._aircraft_pos = (lat, lon)
        self.aircraft_button.configure(state="normal")
        heading = heading or 0.0
        rounded = round(heading / 5) * 5 % 360  # redraw the arrow in 5° steps
        icon = self.icon(("aircraft", rounded), lambda h=rounded: aircraft_icon(h))
        marker = self._aircraft_marker
        if marker is None:
            self._aircraft_marker = marker = self.map.set_marker(lat, lon, icon=icon)
        else:
            # One marker for the life of the connection: swap its image, never delete/re-add.
            if self._aircraft_heading_drawn != rounded:
                marker.icon = icon
                if marker.canvas_icon is not None:
                    self.map.canvas.itemconfigure(marker.canvas_icon, image=icon)
            marker.set_position(lat, lon)
        self._aircraft_heading_drawn = rounded
        self._raise_aircraft()
        if self.follow_var.get() or (first and not self._waypoints):
            self.map.set_position(lat, lon)
            if first:
                self.map.set_zoom(16)

    def clear_aircraft(self):
        if self._aircraft_marker is not None:
            self._aircraft_marker.delete()
        self._aircraft_marker = None
        self._aircraft_heading_drawn = None
        self._aircraft_pos = None
        self.aircraft_button.configure(state="disabled")

    def _raise_aircraft(self):
        """Keep the aircraft drawn above the waypoints."""
        marker = self._aircraft_marker
        if marker is not None and marker.canvas_icon is not None:
            self.map.canvas.tag_raise(marker.canvas_icon)

    # -- trail (Flight tab) ---------------------------------------------------------

    def add_trail_point(self, lat: float, lon: float, min_step_m: float = 3.0, max_points: int = 3000):
        if self.map is None:
            return
        if self._trail_points:
            plat, plon = self._trail_points[-1]
            dy = (lat - plat) * 111_320.0
            dx = (lon - plon) * 111_320.0 * math.cos(math.radians(lat))
            if dx * dx + dy * dy < min_step_m * min_step_m:
                return
        self._trail_points.append((lat, lon))
        if len(self._trail_points) > max_points:
            del self._trail_points[: len(self._trail_points) - max_points]
        if len(self._trail_points) < 2:
            return
        if self._trail is None:
            self._trail = self.map.set_path(list(self._trail_points), color="#7c3aed", width=3)
        else:
            self._trail.set_position_list(list(self._trail_points))
        self._raise_aircraft()

    def clear_trail(self):
        self._trail_points = []
        if self._trail is not None:
            self._trail.delete()
            self._trail = None

    def go_to_aircraft(self):
        if self.map is not None and self._aircraft_pos:
            self.map.set_position(*self._aircraft_pos)

    def destroy(self):
        if self.map is not None:
            self.map.running = False
        super().destroy()


def loiter_radius(wp, default_radius: int) -> int:
    """Radius the plane will actually fly: timed loiters always use the default."""
    lo = wp.loiter
    if lo.mode == "time" or not lo.radius_m:
        return max(1, int(default_radius))
    return lo.radius_m


def circle_points(lat: float, lon: float, radius_m: float, steps: int = 48) -> list[tuple[float, float]]:
    dlat = radius_m / 111_320.0
    dlon = radius_m / (111_320.0 * max(0.01, math.cos(math.radians(lat))))
    return [(lat + dlat * math.sin(2 * math.pi * i / steps), lon + dlon * math.cos(2 * math.pi * i / steps))
            for i in range(steps)]
