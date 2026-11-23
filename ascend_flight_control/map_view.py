#!/usr/bin/env python3
"""
Mission map for ASCEND Flight Control, drawn inside the app with tkintermapview
(OpenStreetMap tiles on a Tk canvas; no browser needed).

- Click the map to add a waypoint; click a waypoint to select it; drag a waypoint to move it.
- Survey area editing: clicks place the area's corners, corners can be dragged,
  and the planned grid is drawn as a preview (the Survey Grid window drives it).
- Numbered waypoint markers, the route line and the home point.
- The aircraft's live position and heading while connected.
"""

from __future__ import annotations

import math
import queue
import sys
import threading
import time
import tkinter as tk
import webbrowser
from tkinter import ttk
from typing import Callable

from PIL import Image, ImageDraw, ImageFont, ImageTk

import airspace_layers as airspace
from mac_native import install_pinch_zoom

try:
    import tkintermapview
except ImportError:  # shown as a message in the map area
    tkintermapview = None

TEAL = "#0f7f8f"
ORANGE = "#c2410c"
HOME = "#1f2937"
AIRCRAFT = "#2563eb"
AREA = "#d97706"
GRID = "#7c3aed"
DRAG_START_PX = 4  # a press has to move this far before it becomes a drag (smaller = a click)
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
                 on_select: Callable[[int], None] | None, live_view: bool = False,
                 on_move: Callable[[int, float, float], None] | None = None):
        """live_view=True: the Flight tab's map (no editing, follows the aircraft, shows a trail).
        on_move(waypoint_id, lat, lon) is called when a waypoint has been dragged to a new place."""
        super().__init__(parent, bg="#f3f6f8")
        self.live_view = live_view
        self._trail = None
        self._trail_points: list[tuple[float, float]] = []
        self.on_add = on_add
        self.on_select = on_select
        self.on_move = on_move
        self._press = None  # (target, x, y) when a press landed on something draggable
        self._dragging = False
        # Survey area editing (set by the Survey Grid window): an object with
        # area_click(lat, lon) and corner_moved(index, lat, lon, final).
        self.area_editor = None
        self._area_markers: list = []
        self._area_outline = None
        self._area_preview = None
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
        self.default_hint = ("Live view · drag to move · scroll or +/− to zoom" if live_view else
                             "Click the map to add a waypoint · drag a waypoint to move it · scroll or +/− to zoom")
        hint = self.default_hint
        self.hint = tk.Label(bar, text=hint,
                             bg="#f3f6f8", fg="#60707d", font=("TkDefaultFont", 12))
        self.hint.pack(side="left")
        self.aircraft_button = ttk.Button(bar, text="Go to Aircraft", command=self.go_to_aircraft, state="disabled")
        self.aircraft_button.pack(side="right")
        # Map ▾ menu (my location, map home). The app supplies the items: menu_provider(map) -> [(label, cmd, enabled)]
        self.menu_provider = None
        self.map_menu_button = ttk.Menubutton(bar, text="Map ▾")
        self.map_menu = tk.Menu(self.map_menu_button, tearoff=0, postcommand=self._fill_menu)
        self.map_menu_button["menu"] = self.map_menu
        self.map_menu_button.pack(side="right", padx=(0, 6))
        # Layers ▾: base map (street / VFR sectional) and FAA airspace overlays.
        self.layers_button = ttk.Menubutton(bar, text="Layers ▾")
        self.layers_menu = tk.Menu(self.layers_button, tearoff=0, postcommand=self._fill_layers_menu)
        self.layers_button["menu"] = self.layers_menu
        self.layers_button.pack(side="right", padx=(0, 6))
        self.on_layers_changed = None  # callback(state) so the app can save it and sync the other map
        self.base = "street"
        self.overlays: set[str] = set()
        self._shapes: dict[str, list] = {}  # layer id -> drawn polygons
        self._labels: dict[str, list] = {}  # layer id -> label markers
        self._layer_data: dict[str, dict] = {}  # layer id -> {"bbox", "zoom", "time", "features", "error"}
        self._fetching: set[str] = set()
        self._results: queue.Queue = queue.Queue()
        self._label_icons: dict = {}
        self.user_moved = False  # set once the person pans or zooms; late location answers then leave the view alone
        self._you_marker = None
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
        # Our own drag/release handlers wrap the map's: a press on a waypoint (or a survey
        # corner) drags it; anywhere else the map pans as before.
        self._map_mouse_move = self.map.mouse_move
        self._map_mouse_release = self.map.mouse_release
        self.map.canvas.bind("<B1-Motion>", self._on_motion)
        self.map.canvas.bind("<ButtonRelease-1>", self._on_release)
        for sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            self.map.canvas.bind(sequence, self._mark_moved, add="+")
        # Runs before the map's own release handler; remembers if the press hit a map control.
        self.map.canvas.bind("<Button-1>", self._on_press, add="+")
        self._install_zoom_controls()
        self.attribution = tk.Label(holder, text=airspace.BASE_MAPS["street"][3], bg="#ffffff", fg="#60707d",
                                    font=("TkDefaultFont", 10))
        self.attribution.place(relx=1.0, rely=1.0, anchor="se")
        self.legend = tk.Frame(holder, bg="#ffffff", highlightbackground="#cbd5e1", highlightthickness=1)
        self._original_fetch = self.map.request_image_from_server
        self.map.request_image_from_server = self._fetch_tile
        self.map.add_right_click_menu_command("What airspace is here?", self._whats_here, pass_coords=True)
        self.after(700, self._layers_tick)

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

    # -- map menu, views and "you are here" ---------------------------------------

    def _fill_menu(self):
        self.map_menu.delete(0, "end")
        items = self.menu_provider(self) if self.menu_provider else []
        for item in items:
            if item is None:
                self.map_menu.add_separator()
                continue
            label, command, enabled = item
            self.map_menu.add_command(label=label, command=command, state="normal" if enabled else "disabled")

    # -- layers -------------------------------------------------------------------

    def _fill_layers_menu(self):
        m = self.layers_menu
        m.delete(0, "end")
        m.add_command(label="Base map", state="disabled")
        self._base_var = tk.StringVar(value=self.base)
        for key, (label, *_rest) in airspace.BASE_MAPS.items():
            m.add_radiobutton(label="   " + label, value=key, variable=self._base_var,
                              command=lambda k=key: self._set_and_report(base=k))
        m.add_separator()
        m.add_command(label="FAA airspace (United States)", state="disabled")
        self._overlay_vars = {}
        for lid, layer in airspace.LAYERS.items():
            var = tk.BooleanVar(value=lid in self.overlays)
            self._overlay_vars[lid] = var
            m.add_checkbutton(label="   " + layer.name, variable=var,
                              command=lambda l=lid: self._toggle_overlay(l))
        m.add_separator()
        m.add_command(label="Turn Off All Airspace Layers", command=lambda: self._set_and_report(overlays=set()),
                      state="normal" if self.overlays else "disabled")
        m.add_command(label="About These Layers…", command=self._about_layers)

    def _toggle_overlay(self, lid):
        overlays = set(self.overlays)
        overlays.symmetric_difference_update({lid})
        self._set_and_report(overlays=overlays)

    def _set_and_report(self, base=None, overlays=None):
        self.set_layers(base or self.base, self.overlays if overlays is None else overlays)
        if self.on_layers_changed:
            self.on_layers_changed(self.layer_state())

    def layer_state(self) -> dict:
        return {"base": self.base, "overlays": sorted(self.overlays)}

    def set_layers(self, base: str, overlays):
        if self.map is None:
            return
        overlays = {o for o in overlays if o in airspace.LAYERS}
        if base not in airspace.BASE_MAPS:
            base = "street"
        if base != self.base:
            self.base = base
            _label, url, max_zoom, credit = airspace.BASE_MAPS[base]
            self.map.set_tile_server(url, max_zoom=max_zoom)
            if self.map.zoom > max_zoom:
                self.map.set_zoom(max_zoom)
            self.attribution.configure(text=credit)
        for lid in self.overlays - overlays:
            self._clear_layer(lid)
        self.overlays = overlays
        self._layers_tick(schedule=False)
        self._update_legend()

    def _fetch_tile(self, tile_server, zoom, x, y):
        if tile_server == airspace.SECTIONAL_TILES:
            return airspace.sectional_tile(zoom, x, y)
        return self._original_fetch(tile_server, zoom, x, y)

    def _view_bbox(self):
        w, h = max(1, self.map.width), max(1, self.map.height)
        north, west = self.map.convert_canvas_coords_to_decimal_coords(0, 0)
        south, east = self.map.convert_canvas_coords_to_decimal_coords(w, h)
        return min(south, north), min(west, east), max(south, north), max(west, east)

    def _layers_tick(self, schedule=True):
        """Every 0.7 s: fetch overlay data for the area on screen when needed, and draw what arrived."""
        try:
            while True:
                lid, bbox, zoom, features, error = self._results.get_nowait()
                self._fetching.discard(lid)
                if lid in self.overlays:
                    self._layer_data[lid] = {"bbox": bbox, "zoom": zoom, "time": time.monotonic(),
                                             "features": features, "error": error}
                    if error is None:
                        self._draw_layer(lid, features)
                    self._update_legend()
        except queue.Empty:
            pass
        # Only the map on screen fetches (the other tab's map catches up when shown): fewer FAA requests.
        if self.map is not None and self.overlays and self.winfo_viewable():
            zoom = int(round(self.map.zoom))
            view = self._view_bbox()
            for lid in self.overlays:
                layer = airspace.LAYERS[lid]
                if zoom < layer.min_zoom:
                    if self._shapes.get(lid):
                        self._clear_layer(lid)
                        self._update_legend()
                    continue
                data = self._layer_data.get(lid)
                fresh = (data is not None and data["error"] is None and airspace.bbox_contains(data["bbox"], view)
                         and abs(data["zoom"] - zoom) < 2 and time.monotonic() - data["time"] < 600)
                if fresh:
                    labels_wanted = lid == "uasfm" and zoom >= 14
                    if labels_wanted != bool(self._labels.get(lid)) or not self._shapes.get(lid) and data["features"]:
                        self._draw_layer(lid, data["features"])
                    continue
                wait = 180 if data is not None and "busy" in (data["error"] or "") else 30
                retry_wait = data is not None and data["error"] is not None and time.monotonic() - data["time"] < wait
                if lid not in self._fetching and not retry_wait:
                    self._start_fetch(lid, airspace.expand_bbox(view), zoom)
        if schedule:
            self.after(700, self._layers_tick)

    def _start_fetch(self, lid, bbox, zoom):
        self._fetching.add(lid)
        self._update_legend()

        def work():
            try:
                features, error = airspace.LAYERS[lid].fetch(bbox, zoom), None
            except Exception as exc:  # offline or FAA service trouble: shown in the legend
                features, error = [], airspace.short_error(exc)
            self._results.put((lid, bbox, zoom, features, error))

        threading.Thread(target=work, daemon=True).start()

    def _clear_layer(self, lid):
        for shape in self._shapes.pop(lid, []):
            shape.delete()
        for marker in self._labels.pop(lid, []):
            self._drop_marker(marker)

    def _drop_marker(self, marker):
        # tkintermapview's marker.delete() runs the Tk event loop; remove it directly instead.
        canvas = self.map.canvas
        for item in (marker.canvas_icon, marker.canvas_text, marker.polygon, marker.big_circle, marker.canvas_image):
            if item is not None:
                canvas.delete(item)
        marker.deleted = True
        if marker in self.map.canvas_marker_list:
            self.map.canvas_marker_list.remove(marker)

    def _draw_layer(self, lid, features):
        self._clear_layer(lid)
        shapes, labels = [], []
        show_labels = lid == "uasfm" and int(round(self.map.zoom)) >= 14
        for f in features:
            for ring in f.rings:
                # tkintermapview fills with a stipple pattern so the map shows through; Tk on macOS
                # has no stipple and would paint the fill solid over the chart, so outline only there.
                fill = None if sys.platform == "darwin" else f.fill
                width = (2 if sys.platform == "darwin" else 1) if lid == "uasfm" else 2
                shape = self.map.set_polygon(ring, outline_color=f.color, fill_color=fill, border_width=width)
                if f.dash and shape.canvas_polygon is not None:
                    self.map.canvas.itemconfigure(shape.canvas_polygon, dash=f.dash)
                shapes.append(shape)
                if show_labels and f.label:
                    lat = sum(p[0] for p in ring) / len(ring)
                    lon = sum(p[1] for p in ring) / len(ring)
                    icon = self.icon(("label", f.label, f.color), lambda t=f.label, c=f.color: text_icon(t, c))
                    labels.append(self.map.set_marker(lat, lon, icon=icon))
        self._shapes[lid] = shapes
        self._labels[lid] = labels
        self.map.manage_z_order()  # waypoints, route and the aircraft stay on top
        self._raise_aircraft()

    def _update_legend(self):
        for child in self.legend.winfo_children():
            child.destroy()
        if not self.overlays:
            self.legend.place_forget()
            return
        zoom = int(round(self.map.zoom)) if self.map is not None else 0
        tk.Label(self.legend, text="Planning only · not for navigation", bg="#ffffff", fg="#b45309",
                 font=("TkDefaultFont", 10, "bold")).pack(anchor="w", padx=6, pady=(4, 2))
        for lid in airspace.LAYERS:
            if lid not in self.overlays:
                continue
            layer = airspace.LAYERS[lid]
            data = self._layer_data.get(lid)
            if zoom < layer.min_zoom:
                status = "zoom in to see"
            elif lid in self._fetching:
                status = "loading…"
            elif data and data["error"]:
                status = f"not available ({data['error']})"
            elif data:
                status = f"{len(data['features'])} in view" if data["features"] else "none here"
            else:
                status = ""
            row = tk.Frame(self.legend, bg="#ffffff")
            row.pack(anchor="w", padx=6, pady=1)
            tk.Label(row, text="■", bg="#ffffff", fg=layer.color, font=("TkDefaultFont", 12)).pack(side="left")
            tk.Label(row, text=f"{layer.legend}: {status}", bg="#ffffff", fg="#17212b",
                     font=("TkDefaultFont", 10)).pack(side="left", padx=(3, 0))
        if "uasfm" in self.overlays and zoom >= airspace.LAYERS["uasfm"].min_zoom:
            row = tk.Frame(self.legend, bg="#ffffff")
            row.pack(anchor="w", padx=6, pady=(1, 4))
            for value, color in airspace.UASFM_COLORS.items():
                tk.Label(row, text=f"{value}", bg=color, fg="#ffffff", font=("TkDefaultFont", 9, "bold"),
                         padx=3).pack(side="left", padx=1)
        self.legend.place(relx=0.0, rely=1.0, anchor="sw", x=6, y=-6)

    def _about_layers(self):
        win = tk.Toplevel(self)
        win.title("About the map layers")
        win.transient(self.winfo_toplevel())
        body = tk.Frame(win, bg="#ffffff", padx=18, pady=14)
        body.pack(fill="both")
        tk.Label(body, text="Map layers", bg="#ffffff", fg="#17212b", font=("TkDefaultFont", 15, "bold")).pack(anchor="w")
        tk.Label(body, text=airspace.DISCLAIMER, bg="#ffffff", fg="#b45309", wraplength=460, justify="left",
                 font=("TkDefaultFont", 12)).pack(anchor="w", pady=(6, 10))
        text = ("VFR sectional chart: FAA Aeronautical Information Services. Closer than zoom 12 the chart is enlarged.\n"
                "TFRs: tfr.faa.gov, refreshed every 10 minutes.\n"
                "UAS Facility Map: the LAANC grid; the number in each square is the maximum altitude (ft above "
                "ground) the FAA may authorize there.\n"
                "Controlled airspace, special use airspace and national security restrictions: FAA ArcGIS data.\n\n"
                "Right-click the map and choose “What airspace is here?” to check one spot against every layer.")
        tk.Label(body, text=text, bg="#ffffff", fg="#17212b", wraplength=460, justify="left",
                 font=("TkDefaultFont", 12)).pack(anchor="w")
        ttk.Button(body, text="Close", command=win.destroy).pack(anchor="e", pady=(12, 0))

    def _whats_here(self, coords):
        lat, lon = coords
        results: queue.Queue = queue.Queue()
        threading.Thread(target=lambda: results.put(airspace.whats_here(lat, lon)), daemon=True).start()
        win = tk.Toplevel(self)
        win.title("What airspace is here?")
        win.transient(self.winfo_toplevel())
        body = tk.Frame(win, bg="#ffffff", padx=18, pady=14)
        body.pack(fill="both", expand=True)
        tk.Label(body, text=f"{lat:.5f}, {lon:.5f}", bg="#ffffff", fg="#17212b",
                 font=("TkDefaultFont", 15, "bold")).pack(anchor="w")
        status = tk.Label(body, text="Checking FAA airspace data…", bg="#ffffff", fg="#60707d",
                          font=("TkDefaultFont", 12))
        status.pack(anchor="w", pady=(4, 8))

        def show():
            try:
                found, errors = results.get_nowait()
            except queue.Empty:
                if win.winfo_exists():
                    win.after(200, show)
                return
            if not win.winfo_exists():
                return
            status.configure(text="No FAA airspace layers here." if not found else
                             f"{len(found)} {'area' if len(found) == 1 else 'areas'} here:")
            for f in found:
                row = tk.Frame(body, bg="#ffffff")
                row.pack(anchor="w", fill="x", pady=4)
                tk.Label(row, text="■", bg="#ffffff", fg=f.color, font=("TkDefaultFont", 14)).pack(side="left", anchor="n")
                text = tk.Frame(row, bg="#ffffff")
                text.pack(side="left", fill="x", padx=(4, 0))
                tk.Label(text, text=f.title, bg="#ffffff", fg="#17212b", font=("TkDefaultFont", 13, "bold"),
                         wraplength=440, justify="left").pack(anchor="w")
                tk.Label(text, text=f.detail, bg="#ffffff", fg="#334155", font=("TkDefaultFont", 12),
                         wraplength=440, justify="left").pack(anchor="w")
                if f.link:
                    link = tk.Label(text, text="Open the TFR on tfr.faa.gov", bg="#ffffff", fg="#0f7f8f",
                                    cursor="hand2", font=("TkDefaultFont", 12, "underline"))
                    link.pack(anchor="w")
                    link.bind("<Button-1>", lambda _e, url=f.link: webbrowser.open(url))
            for error in errors:
                tk.Label(body, text=f"Could not check {error}", bg="#ffffff", fg="#b91c1c",
                         font=("TkDefaultFont", 11), wraplength=460, justify="left").pack(anchor="w")
            tk.Label(body, text=airspace.DISCLAIMER, bg="#ffffff", fg="#b45309", font=("TkDefaultFont", 11),
                     wraplength=460, justify="left").pack(anchor="w", pady=(10, 0))
            ttk.Button(body, text="Close", command=win.destroy).pack(anchor="e", pady=(10, 0))

        win.after(200, show)

    def _mark_moved(self, _event=None):
        self.user_moved = True

    def view(self) -> tuple[float, float, int] | None:
        if self.map is None:
            return None
        lat, lon = self.map.get_position()
        return lat, lon, int(round(self.map.zoom))

    def go_to(self, lat: float, lon: float, zoom: int | None = None):
        if self.map is None:
            return
        if zoom is not None:
            self.map.set_zoom(zoom)
        self.map.set_position(lat, lon)

    def show_you(self, lat: float, lon: float):
        """Blue dot where the computer says it is."""
        if self.map is None:
            return
        if self._you_marker is not None:
            self._you_marker.delete()
        icon = self.icon("you", lambda: circle_icon("", "#2563eb", 16))
        self._you_marker = self.map.set_marker(lat, lon, icon=icon)
        self._raise_aircraft()

    @property
    def has_content(self) -> bool:
        """A mission or the aircraft is on the map (so don't move the view on its own)."""
        return bool(self._waypoints) or self._aircraft_pos is not None

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
        self._press, self._dragging = None, False
        if hit & self._control_items():
            self._suppress_click = True
            self.after(400, lambda: setattr(self, "_suppress_click", False))
            return
        target = self._drag_target(hit)
        if target is not None:
            self._press = (target, event.x, event.y)

    def _drag_target(self, hit: set):
        """What a press on these canvas items would drag: ("corner", index), ("wp", id) or None.
        Survey corners win over waypoints; the marker list may have just been redrawn by the
        click's own selection, so targets are kept by id, never by marker object."""
        if self.area_editor is not None:
            for marker in reversed(self._area_markers):
                if marker.canvas_icon in hit:
                    return marker.data
        if self.on_move is not None:
            for marker in reversed(self._markers):
                if marker.canvas_icon in hit and marker.data is not None:
                    return ("wp", marker.data)
        return None

    def _on_motion(self, event):
        if self._press is None:
            self._mark_moved()
            self._map_mouse_move(event)  # pan the map
            return
        target, x0, y0 = self._press
        if not self._dragging:
            if abs(event.x - x0) < DRAG_START_PX and abs(event.y - y0) < DRAG_START_PX:
                return
            self._dragging = True
            self.map.canvas.config(cursor="fleur")
        lat, lon = self._event_coords(event)
        if target[0] == "corner":
            self.area_editor.corner_moved(target[1], lat, lon, final=False)
        else:
            self._drag_waypoint_to(target[1], lat, lon)

    def _on_release(self, event):
        press, dragging = self._press, self._dragging
        self._press, self._dragging = None, False
        if press is None:
            self._map_mouse_release(event)  # click (add a waypoint / corner) or end of a pan
            return
        self.map.fading_possible = True
        self.map.move_velocity = (0, 0)  # no leftover "fling" from an earlier pan
        if not dragging:
            return  # a plain click on a marker: its own handler selected it
        self.map.canvas.config(cursor="arrow")
        self._suppress_click = False
        target = press[0]
        lat, lon = self._event_coords(event)
        if target[0] == "corner":
            self.area_editor.corner_moved(target[1], lat, lon, final=True)
        elif self.on_move is not None:
            self.on_move(target[1], lat, lon)

    def _event_coords(self, event) -> tuple[float, float]:
        x = min(max(event.x, 0), max(1, self.map.width))
        y = min(max(event.y, 0), max(1, self.map.height))
        return self.map.convert_canvas_coords_to_decimal_coords(x, y)

    def _drag_waypoint_to(self, wp_id, lat, lon):
        """Move the waypoint's marker, the route and its loiter circle while dragging.
        The mission itself changes once, on release (on_move)."""
        for marker in self._markers:
            if marker.data == wp_id:
                marker.set_position(lat, lon)
        self._waypoints = [(i, lat, lon, a) if i == wp_id else (i, la, lo, a)
                           for i, la, lo, a in self._waypoints]
        if self._path is not None:
            self._path.set_position_list([(la, lo) for _i, la, lo, _a in self._waypoints])
        for circle in self._circles:
            if circle.data == wp_id:
                circle.position_list = circle_points(lat, lon, circle.name)
                circle.draw()
        self._signature = None  # the next render redraws from the mission
        self._raise_aircraft()

    def _map_clicked(self, coords):
        if self._suppress_click:  # the click landed on a marker or a zoom button
            self._suppress_click = False
            return
        if self.area_editor is not None:
            self.area_editor.area_click(coords[0], coords[1])
            return
        if self.on_add is not None:
            self.on_add(coords[0], coords[1])

    # -- survey area (Survey Grid window) ------------------------------------------

    def set_area_editor(self, editor):
        """Start (editor) or stop (None) survey area editing: map clicks then place corners."""
        self.area_editor = editor
        self.hint.configure(text="Survey grid · click to place the area's corners · drag a corner to move it"
                            if editor is not None else self.default_hint)
        if editor is None:
            self.draw_area([], [], closed=False)

    def draw_area(self, corners, preview, closed=True):
        """The survey area (orange outline + draggable corners) and the planned passes (purple)."""
        if self.map is None:
            return
        ring = list(corners) + ([corners[0]] if closed and len(corners) >= 3 else [])
        self._area_outline = self._update_path(self._area_outline, ring, AREA, 3)
        self._area_preview = self._update_path(self._area_preview, list(preview), GRID, 2, dash=(6, 4))
        if self._press is not None and self._dragging and len(self._area_markers) == len(corners):
            for marker, (lat, lon) in zip(self._area_markers, corners):
                marker.set_position(lat, lon)  # mid-drag: move in place, keep the grabbed marker
        else:
            for marker in self._area_markers:
                self._drop_marker(marker)
            icon = self.icon("corner", lambda: circle_icon("", AREA, 18))
            self._area_markers = [self.map.set_marker(lat, lon, icon=icon, data=("corner", i))
                                  for i, (lat, lon) in enumerate(corners)]
        self.map.manage_z_order()
        self._raise_aircraft()

    def _update_path(self, path, points, color, width, dash=None):
        if len(points) < 2:
            if path is not None:
                path.delete()
            return None
        if path is None:
            path = self.map.set_path(points, color=color, width=width)
            if dash and path.canvas_line is not None:
                self.map.canvas.itemconfigure(path.canvas_line, dash=dash)
            path.dash = dash
            return path
        path.set_position_list(points)
        if path.dash and path.canvas_line is not None:
            self.map.canvas.itemconfigure(path.canvas_line, dash=path.dash)
        return path

    def fit_points(self, points):
        if self.map is None or len(points) < 2:
            return
        lats = [p[0] for p in points]
        lons = [p[1] for p in points]
        pad_lat = max(0.0008, (max(lats) - min(lats)) * 0.15)
        pad_lon = max(0.0008, (max(lons) - min(lons)) * 0.15)
        self.map.fit_bounding_box((max(lats) + pad_lat, min(lons) - pad_lon),
                                  (min(lats) - pad_lat, max(lons) + pad_lon))

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
        circles = [(wp.id, wp.lat, wp.lon, loiter_radius(wp, default_loiter_radius))
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

        for wp_id, lat, lon, radius in circles:
            # data = waypoint id and name = radius, so a dragged waypoint can move its circle.
            circle = self.map.set_polygon(circle_points(lat, lon, radius), outline_color=TEAL,
                                          fill_color=None, border_width=2, data=wp_id, name=radius)
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
        self.fit_points(points)

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

    def shutdown(self, wait_s: float = 2.0):
        """Stop the map's tile-loading threads and wait briefly for them.

        tkintermapview's threads create Tk images; if one is still running while
        the program exits, the process can crash (seen on Raspberry Pi)."""
        if self.map is None:
            return
        self.map.running = False
        threads = [getattr(self.map, "pre_cache_thread", None)] + list(getattr(self.map, "image_load_thread_pool", []))
        deadline = time.monotonic() + wait_s
        for thread in threads:
            if thread is not None and thread.is_alive():
                thread.join(max(0.0, deadline - time.monotonic()))

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


def text_icon(text: str, color: str) -> ImageTk.PhotoImage:
    """Small rounded label (UAS Facility Map ceiling) drawn at a grid square's center."""
    font = _font(11 * SS)
    w = (len(text) * 7 + 10) * SS
    h = 16 * SS
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle((0, 0, w - 1, h - 1), radius=5 * SS, fill=color)
    draw.text((w / 2, h / 2), text, fill="#ffffff", font=font, anchor="mm")
    return ImageTk.PhotoImage(img.resize((w // SS, h // SS), Image.LANCZOS))
