#!/usr/bin/env python3
"""
Survey Grid window for ASCEND Flight Control.

While it is open, the Mission map is in area mode: clicks place the survey
area's corners (a box from two opposite corners, or a polygon corner by corner)
and corners can be dragged. The planned passes are drawn on the map as the
settings change, and "Add Grid to Mission" turns them into waypoints. With
"Take photos" on, the waypoints also carry photo-every-N-meters events
(DO_SET_CAM_TRIGG_DIST), on for each pass and off in the turns.
"""

from __future__ import annotations

import math
import tkinter as tk
from tkinter import messagebox, ttk

import grid_survey as gs
from app_settings import load_setting, save_setting
from params_view import ScrollFrame

SETTINGS_KEY = "survey_grid"
PANEL = "#ffffff"
TEXT = "#17212b"
MUTED = "#60707d"
ERROR = "#b91c1c"
WARN = "#b45309"


class SurveyGridWindow(tk.Toplevel):
    def __init__(self, app, mission_map, on_finish):
        """on_finish(points, altitude_m, speed_mps, replace, photos) adds the grid's waypoints to the mission.
        photos is a list (one per point) of meters between photos, 0.0 to stop, or None for no event."""
        super().__init__(app)
        self.app = app
        self.units = app.units
        self.map = mission_map
        self.on_finish = on_finish
        self.title("Survey Grid")
        self.transient(app)
        self.configure(bg=PANEL)
        self.resizable(False, True)
        self.protocol("WM_DELETE_WINDOW", self.cancel)

        self.corners: list[tuple[float, float]] = []
        self.box_anchor: tuple[float, float] | None = None  # first click of a box
        self.result: gs.GridResult | None = None
        self._pending = None

        saved = load_setting(SETTINGS_KEY) or {}
        defaults = app.mission.defaults
        u = self.units
        self.shape_var = tk.StringVar(value=saved.get("shape", "box"))
        self.alt_var = tk.StringVar(value=f"{u.alt(defaults.altitude_m):.0f}")
        self.speed_var = tk.StringVar(value=app.fmt_speed_input(defaults.speed_mps))
        self.spacing_mode_var = tk.StringVar(value=saved.get("spacing_mode", "camera"))
        self.hfov_var = tk.StringVar(value=str(saved.get("hfov", 60)))
        self.vfov_var = tk.StringVar(value=str(saved.get("vfov", 45)))
        self.side_var = tk.StringVar(value=str(saved.get("side_overlap", 60)))
        self.front_var = tk.StringVar(value=str(saved.get("front_overlap", 70)))
        self.spacing_var = tk.StringVar(value=f"{u.alt(saved.get('spacing_m', 50)):.0f}")
        self.auto_angle_var = tk.BooleanVar(value=saved.get("auto_angle", True))
        self.angle_var = tk.StringVar(value=str(saved.get("angle", 0)))
        self.runout_var = tk.StringVar(value=f"{u.alt(saved.get('runout_m', 40)):.0f}")
        self.corner_var = tk.StringVar(value=gs.START_CORNERS[0].capitalize())
        self.replace_var = tk.BooleanVar(value=not app.mission.waypoints)
        self.photos_var = tk.BooleanVar(value=saved.get("photos", True))
        self.per_pass_var = tk.BooleanVar(value=saved.get("photos_per_pass", True))
        self.photo_dist_var = tk.StringVar(value=f"{u.alt(saved.get('photo_m', 25)):.0f}")

        self._build()
        for var in (self.alt_var, self.speed_var, self.spacing_mode_var, self.hfov_var, self.vfov_var,
                    self.side_var, self.front_var, self.spacing_var, self.auto_angle_var, self.angle_var,
                    self.runout_var, self.corner_var, self.photos_var, self.per_pass_var, self.photo_dist_var):
            var.trace_add("write", lambda *_a: self.schedule_update())
        self.map.set_area_editor(self)
        self.update_controls()
        self.schedule_update()
        self.place_beside_map()

    # -- layout ----------------------------------------------------------------------

    def _build(self):
        # Stats and buttons are pinned to the bottom so they never fall off a small screen;
        # the settings above them scroll.
        footer = tk.Frame(self, bg=PANEL, padx=16, pady=10, highlightbackground="#dde3e8", highlightthickness=1)
        footer.pack(side="bottom", fill="x")
        self.scroller = ScrollFrame(self, bg=PANEL)
        self.scroller.pack(side="top", fill="both", expand=True)
        body = tk.Frame(self.scroller.body, bg=PANEL, padx=16, pady=12)
        body.pack(fill="both", expand=True)
        self._body = body
        tk.Label(body, text="Survey Grid", bg=PANEL, fg=TEXT, font=("TkDefaultFont", 15, "bold")).pack(anchor="w")
        tk.Label(body, text="Back-and-forth passes that cover an area, for mapping photos or sensor surveys.",
                 bg=PANEL, fg=MUTED, wraplength=360, justify="left").pack(anchor="w", pady=(2, 10))

        area = ttk.LabelFrame(body, text="Area", padding=10)
        area.pack(fill="x")
        row = ttk.Frame(area)
        row.pack(fill="x")
        ttk.Radiobutton(row, text="Box", value="box", variable=self.shape_var,
                        command=self.shape_changed).pack(side="left")
        ttk.Radiobutton(row, text="Polygon", value="polygon", variable=self.shape_var,
                        command=self.shape_changed).pack(side="left", padx=(12, 0))
        self.area_hint = tk.Label(area, bg=PANEL, fg=MUTED, wraplength=340, justify="left")
        self.area_hint.pack(anchor="w", pady=(6, 6))
        row = ttk.Frame(area)
        row.pack(fill="x")
        ttk.Button(row, text="Box Around Map View", command=self.box_from_view).pack(side="left")
        self.undo_button = ttk.Button(row, text="Undo Corner", command=self.undo_corner)
        self.undo_button.pack(side="left", padx=(6, 0))
        ttk.Button(row, text="Clear", command=self.clear_area).pack(side="left", padx=(6, 0))

        flight = ttk.LabelFrame(body, text="Flight", padding=10)
        flight.pack(fill="x", pady=(10, 0))
        self._field(flight, f"Altitude ({self.units.alt_label})", self.alt_var)
        self._field(flight, f"Speed ({self.units.speed_label})", self.speed_var)

        spacing = ttk.LabelFrame(body, text="Pass Spacing and Overlap", padding=10)
        spacing.pack(fill="x", pady=(10, 0))
        row = ttk.Frame(spacing)
        row.pack(fill="x")
        ttk.Radiobutton(row, text="From camera and overlap", value="camera", variable=self.spacing_mode_var,
                        command=self.update_controls).pack(side="left")
        ttk.Radiobutton(row, text="Fixed spacing", value="fixed", variable=self.spacing_mode_var,
                        command=self.update_controls).pack(side="left", padx=(12, 0))
        self.camera_rows = [
            self._field(spacing, "Side overlap (%)", self.side_var,
                        "How much each pass overlaps the one beside it."),
            self._field(spacing, "Front overlap (%)", self.front_var,
                        "How much each photo overlaps the next one along a pass."),
            self._field(spacing, "Camera view across (°)", self.hfov_var,
                        "Field of view across the passes (the wide side of the photo)."),
            self._field(spacing, "Camera view along (°)", self.vfov_var,
                        "Field of view along the passes."),
        ]
        self.fixed_rows = [self._field(spacing, f"Spacing ({self.units.alt_label})", self.spacing_var,
                                       "Distance between neighboring passes.")]

        pattern = ttk.LabelFrame(body, text="Pattern", padding=10)
        pattern.pack(fill="x", pady=(10, 0))
        ttk.Checkbutton(pattern, text="Fly along the area's longest edge (fewest turns)",
                        variable=self.auto_angle_var, command=self.update_controls).pack(anchor="w")
        self.angle_row = self._field(pattern, "Pass heading (°)", self.angle_var,
                                     "Direction of the passes, degrees from north.")
        self._field(pattern, f"Run-out ({self.units.alt_label})", self.runout_var,
                    "How far each pass continues past the area's edge, so the plane has "
                    "finished turning and is flying straight before it is over the area.")
        row = ttk.Frame(pattern)
        row.pack(fill="x", pady=3)
        ttk.Label(row, text="Start at", width=20).pack(side="left")
        ttk.Combobox(row, textvariable=self.corner_var, state="readonly", width=20,
                     values=[c.capitalize() for c in gs.START_CORNERS]).pack(side="left", fill="x", expand=True)

        photos = ttk.LabelFrame(body, text="Photos", padding=10)
        photos.pack(fill="x", pady=(10, 0))
        ttk.Checkbutton(photos, text="Take photos by distance", variable=self.photos_var,
                        command=self.update_controls).pack(anchor="w")
        self.per_pass_check = ttk.Checkbutton(photos, text="Only on the passes (camera off in the turns)",
                                              variable=self.per_pass_var)
        self.per_pass_check.pack(anchor="w", pady=(2, 0))
        self.photo_dist_row = self._field(photos, f"Photo every ({self.units.alt_label})", self.photo_dist_var,
                                          "Distance between photos. With camera spacing it comes from "
                                          "the front overlap instead.")
        self.photo_note = tk.Label(photos, bg=PANEL, fg=MUTED, wraplength=340, justify="left")
        self.photo_note.pack(anchor="w", pady=(4, 0))

        add = ttk.LabelFrame(body, text="Add to Mission", padding=10)
        add.pack(fill="x", pady=(10, 0))
        ttk.Radiobutton(add, text="After the current waypoints", value=False,
                        variable=self.replace_var).pack(anchor="w")
        ttk.Radiobutton(add, text="Replace all waypoints", value=True,
                        variable=self.replace_var).pack(anchor="w")

        self.stats = tk.Label(footer, bg=PANEL, fg=TEXT, justify="left", wraplength=380, anchor="w")
        self.stats.pack(fill="x")
        self.message = tk.Label(footer, bg=PANEL, fg=ERROR, justify="left", wraplength=380, anchor="w")
        self.message.pack(fill="x", pady=(4, 0))

        buttons = tk.Frame(footer, bg=PANEL)
        buttons.pack(fill="x", pady=(8, 0))
        self.add_button = ttk.Button(buttons, text="Add Grid to Mission", style="Accent.TButton", command=self.finish)
        self.add_button.pack(side="right")
        ttk.Button(buttons, text="Cancel", command=self.cancel).pack(side="right", padx=(0, 6))
        ttk.Button(buttons, text="Show Area", command=self.fit_area).pack(side="left")

    def place_beside_map(self):
        """Fit the window on screen and put it over the right side of the app (the Waypoint
        Editor), leaving the map free to draw on."""
        self.update_idletasks()
        self.scroller.canvas.configure(width=self._body.winfo_reqwidth(), height=self._body.winfo_reqheight())
        self.update_idletasks()
        app = self.app
        screen_h = self.winfo_screenheight()
        width = self.winfo_reqwidth()
        height = min(self.winfo_reqheight(), screen_h - 140)  # room for the menu bar, title bar and dock
        x = app.winfo_rootx() + app.winfo_width() - width - 16
        x = max(0, min(x, self.winfo_screenwidth() - width))
        y = max(30, min(app.winfo_rooty() + 40, screen_h - height - 90))
        self.geometry(f"{width}x{height}+{x}+{y}")
        self.minsize(width, 320)
    def _field(self, parent, label, variable, tip=None):
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=3)
        ttk.Label(row, text=label, width=20).pack(side="left")
        ttk.Entry(row, textvariable=variable, width=10).pack(side="left")
        if tip:
            tk.Label(row, text="ⓘ", bg=PANEL, fg=MUTED).pack(side="left", padx=(6, 0))
            row.winfo_children()[-1].bind("<Enter>", lambda _e: self.message.configure(text=tip, fg=MUTED))
            row.winfo_children()[-1].bind("<Leave>", lambda _e: self.schedule_update())
        return row

    def update_controls(self):
        camera = self.spacing_mode_var.get() == "camera"
        for row in self.camera_rows:
            row.pack_forget()
        for row in self.fixed_rows:
            row.pack_forget()
        for row in (self.camera_rows if camera else self.fixed_rows):
            row.pack(fill="x", pady=3)
        for child in self.angle_row.winfo_children():
            if isinstance(child, ttk.Entry):
                child.configure(state="disabled" if self.auto_angle_var.get() else "normal")
        photos = self.photos_var.get()
        self.per_pass_check.configure(state="normal" if photos else "disabled")
        # With camera spacing the photo distance comes from the front overlap; otherwise it is typed in.
        if photos and not camera:
            self.photo_dist_row.pack(fill="x", pady=3, before=self.photo_note)
        else:
            self.photo_dist_row.pack_forget()
        self.update_area_hint()
        self.schedule_update()

    def update_area_hint(self):
        if self.shape_var.get() == "box":
            text = ("Click one corner of the area on the map, then the opposite corner."
                    if self.box_anchor is None else "Now click the opposite corner.")
            if len(self.corners) == 4 and self.box_anchor is None:
                text = "Drag a corner to resize the box. Clicking the map starts a new box."
        else:
            n = len(self.corners)
            text = ("Click the map at each corner of the area, in order around it." if n < 3 else
                    f"{n} corners. Click to add more, drag a corner to move it.")
        self.area_hint.configure(text=text)
        self.undo_button.configure(state="normal" if self.corners and self.shape_var.get() == "polygon"
                                   else "disabled")

    # -- area editing (called by the map) ------------------------------------------------

    def area_click(self, lat, lon):
        if self.shape_var.get() == "box":
            if self.box_anchor is None:
                self.box_anchor = (lat, lon)
                self.corners = [(lat, lon)]
            else:
                self.corners = gs.box_corners(self.box_anchor, (lat, lon))
                self.box_anchor = None
        else:
            self.corners.append((lat, lon))
        self.update_area_hint()
        self.update_now()

    def corner_moved(self, index, lat, lon, final):
        if not 0 <= index < len(self.corners):
            return
        if self.shape_var.get() == "box" and len(self.corners) == 4:
            # Keep it a box: the corners beside the dragged one follow along one side each.
            same_lat = {0: 1, 1: 0, 2: 3, 3: 2}[index]
            same_lon = {0: 3, 3: 0, 1: 2, 2: 1}[index]
            self.corners[index] = (lat, lon)
            self.corners[same_lat] = (lat, self.corners[same_lat][1])
            self.corners[same_lon] = (self.corners[same_lon][0], lon)
        else:
            self.corners[index] = (lat, lon)
            if self.shape_var.get() == "box":
                self.box_anchor = (lat, lon)  # the single first corner of an unfinished box
        self.update_now()  # mid-drag the map moves the corner markers in place; on release it redraws them

    def shape_changed(self):
        """Polygon → box: the box around the polygon. Box → polygon: its four corners."""
        self.box_anchor = None
        if self.shape_var.get() == "box":
            if len(self.corners) == 1:
                self.corners = []
            elif len(self.corners) >= 2 and not (len(self.corners) == 4 and self._is_box()):
                lats = [c[0] for c in self.corners]
                lons = [c[1] for c in self.corners]
                self.corners = gs.box_corners((max(lats), min(lons)), (min(lats), max(lons)))
        self.update_area_hint()
        self.update_now()

    def _is_box(self):
        c = self.corners
        return c[0][0] == c[1][0] and c[2][0] == c[3][0] and c[0][1] == c[3][1] and c[1][1] == c[2][1]

    def box_from_view(self):
        """A box covering the middle half of the map view."""
        m = self.map.map
        if m is None:
            return
        w, h = max(1, m.width), max(1, m.height)
        a = m.convert_canvas_coords_to_decimal_coords(w * 0.25, h * 0.25)
        b = m.convert_canvas_coords_to_decimal_coords(w * 0.75, h * 0.75)
        self.shape_var.set("box")
        self.box_anchor = None
        self.corners = gs.box_corners(a, b)
        self.update_area_hint()
        self.update_now()

    def undo_corner(self):
        if self.corners:
            self.corners.pop()
        self.update_area_hint()
        self.update_now()

    def clear_area(self):
        self.corners = []
        self.box_anchor = None
        self.update_area_hint()
        self.update_now()

    def fit_area(self):
        points = self.corners + (self.result.points if self.result and self.result.points else [])
        self.map.fit_points(points)

    # -- planning ----------------------------------------------------------------------

    def photo_distance(self, settings) -> float | None:
        """Meters between photos, or None when photos are off. Raises ValueError for a bad entry."""
        if not self.photos_var.get():
            return None
        if settings.spacing_mode == "camera":
            return round(gs.pass_spacing(settings)[3], 1)
        try:
            meters = round(self.units.alt_si(float(self.photo_dist_var.get().strip())), 1)
        except ValueError:
            raise ValueError("Enter a number for the photo distance.") from None
        if not 0 < meters <= 1000:
            raise ValueError("Photo distance must be more than 0 and up to 1000 m.")
        return meters

    def settings(self) -> gs.GridSettings:
        """The settings in SI units; raises ValueError with a readable message for bad entries."""
        u = self.units

        def number(var, name):
            try:
                return float(var.get().strip())
            except ValueError:
                raise ValueError(f"Enter a number for {name}.") from None

        return gs.GridSettings(
            altitude_m=u.alt_si(number(self.alt_var, "altitude")),
            speed_mps=u.speed_si(number(self.speed_var, "speed")),
            spacing_mode=self.spacing_mode_var.get(),
            spacing_m=u.alt_si(number(self.spacing_var, "spacing")) if self.spacing_mode_var.get() == "fixed" else 50,
            camera_hfov_deg=number(self.hfov_var, "camera view across"),
            camera_vfov_deg=number(self.vfov_var, "camera view along"),
            side_overlap_pct=number(self.side_var, "side overlap"),
            front_overlap_pct=number(self.front_var, "front overlap"),
            angle_deg=None if self.auto_angle_var.get() else number(self.angle_var, "pass heading"),
            runout_m=u.alt_si(number(self.runout_var, "run-out")),
            start_corner=[c.capitalize() for c in gs.START_CORNERS].index(self.corner_var.get()),
        )

    def schedule_update(self):
        if self._pending is None:
            self._pending = self.after(120, self.update_now)

    def update_now(self):
        if self._pending is not None:
            self.after_cancel(self._pending)
            self._pending = None
        self.result = None
        error = None
        try:
            settings = self.settings()
        except ValueError as exc:
            settings, error = None, str(exc)
        photo_m = None
        if settings is not None:
            try:
                photo_m = self.photo_distance(settings)
            except ValueError as exc:
                error = str(exc)
        if settings is not None and len(self.corners) >= 3 and error is None:
            self.result = gs.plan_grid(self.corners, settings)
            error = self.result.error
        elif error is None:
            error = "" if self.corners else None
        closed = not (self.shape_var.get() == "box" and self.box_anchor is not None)
        preview = self.result.points if self.result and not self.result.error else []
        self.map.draw_area(self.corners, preview, closed=closed)
        self.show_stats(settings, error, photo_m)

    def show_stats(self, settings, error, photo_m=None):
        r = self.result
        u = self.units
        lines = []
        if settings is not None and settings.spacing_mode == "camera":
            across = gs.footprint_m(settings.altitude_m, settings.camera_hfov_deg)
            lines.append(f"Photo covers {u.fmt_distance(across)} across at this altitude.")
        if r is not None and not r.error:
            minutes = r.distance_m / settings.speed_mps / 60 if settings.speed_mps > 0 else None
            lines.append(f"{r.passes} passes, {u.fmt_distance(r.spacing_m)} apart, heading {r.angle_deg:.0f}°")
            lines.append(f"{len(r.points)} waypoints · {u.fmt_distance(r.distance_m)} of flying"
                         + (f" · about {math.ceil(minutes)} min" if minutes else ""))
            lines.append(f"Area: {area_text(r.area_m2, u.choice.alt)}")
            if photo_m and settings.speed_mps > 0:
                photos_n = sum(math.floor(math.dist(*pair) / photo_m) + 1 for pair in self._pass_lengths()) \
                    if self.per_pass_var.get() else math.floor(r.distance_m / photo_m) + 1
                lines.append(f"Photo every {u.fmt_distance(photo_m)} (every {photo_m / settings.speed_mps:.1f} s "
                             f"at this speed), about {photos_n} photos.")
        self.stats.configure(text="\n".join(lines))
        if photo_m is None:
            self.photo_note.configure(text="No photo commands are added.")
        else:
            self.photo_note.configure(text="Each pass starts taking photos at its first waypoint and stops at "
                                           "its last." if self.per_pass_var.get() else
                                      "Photos start at the grid's first waypoint and stop at its last.")
        notes = list(r.warnings) if r is not None else []
        if photo_m and settings is not None and settings.speed_mps > 0 and photo_m / settings.speed_mps < 0.5:
            notes.append("That is more than two photos a second, which most cameras can't keep up with. "
                         "Fly higher or slower, or use less front overlap.")
        params = self.app.param_store
        if photo_m and params.loaded and "CAM1_TYPE" in params.params and int(params.value("CAM1_TYPE")) == 0:
            notes.append("The flight controller has no camera trigger set up (CAM1_TYPE is None). "
                         "Set it in Aircraft Settings → Camera.")
        radius = self.app.default_loiter_radius()[0]
        if r is not None and not r.error and r.spacing_m < radius:
            notes.append(f"Passes are closer together than the plane's turn ({u.fmt_distance(radius)} loiter radius), "
                         "so it will swing wide at each end. Leave clear space around the area.")
        if error:
            self.message.configure(text=error, fg=ERROR)
        elif notes:
            self.message.configure(text="\n".join(notes), fg=WARN)
        else:
            self.message.configure(text="")
        self.add_button.configure(state="normal" if r is not None and not r.error and r.points else "disabled")

    # -- finish ------------------------------------------------------------------------

    def finish(self):
        self.update_now()
        if self.result is None or self.result.error or not self.result.points:
            return
        settings = self.settings()
        photo_m = self.photo_distance(settings)
        self.save_choices(settings, photo_m)
        points, replace = list(self.result.points), bool(self.replace_var.get())
        photos = gs.photo_events(len(points), photo_m or 0, self.per_pass_var.get())
        self.close()
        self.on_finish(points, settings.altitude_m, settings.speed_mps, replace, photos)

    def _pass_lengths(self):
        """(start, end) of each pass in meters on a flat local map, for counting photos."""
        pts = self.result.points
        frame = gs.frame_for(pts)
        xy = [frame.to_xy(*p) for p in pts]
        return [(xy[i], xy[i + 1]) for i in range(0, len(xy) - 1, 2)]

    def save_choices(self, s: gs.GridSettings, photo_m):
        save_setting(SETTINGS_KEY, {
            "shape": self.shape_var.get(), "spacing_mode": s.spacing_mode,
            "hfov": s.camera_hfov_deg, "vfov": s.camera_vfov_deg,
            "side_overlap": s.side_overlap_pct, "front_overlap": s.front_overlap_pct,
            "spacing_m": round(s.spacing_m, 1), "auto_angle": s.angle_deg is None,
            "angle": s.angle_deg if s.angle_deg is not None else _number_or(self.angle_var.get(), 0),
            "runout_m": round(s.runout_m, 1),
            "photos": bool(self.photos_var.get()), "photos_per_pass": bool(self.per_pass_var.get()),
            "photo_m": photo_m if photo_m and s.spacing_mode == "fixed" else
            (load_setting(SETTINGS_KEY) or {}).get("photo_m", 25),
        })

    def cancel(self):
        """Cancel or the window's close button: don't silently throw away a planned grid."""
        self.update_now()
        if self.result is not None and not self.result.error and self.result.points:
            answer = messagebox.askyesnocancel(
                "Survey Grid", f"Add this grid ({len(self.result.points)} waypoints) to the mission?\n\n"
                "Yes adds it. No discards it. Cancel goes back to editing.", parent=self)
            if answer is None:
                return
            if answer:
                self.finish()
                return
        self.close()

    def close(self):
        if self._pending is not None:
            self.after_cancel(self._pending)
            self._pending = None
        self.map.set_area_editor(None)
        self.destroy()


def _number_or(text: str, default: float) -> float:
    try:
        return float(text)
    except ValueError:
        return default


def area_text(m2: float, alt_unit: str) -> str:
    if alt_unit == "m":
        return f"{m2:,.0f} m²" if m2 < 10_000 else f"{m2 / 10_000:.2f} hectares"
    acres = m2 / 4046.8564
    return f"{m2 * 10.7639:,.0f} ft²" if acres < 1 else f"{acres:.1f} acres"
