#!/usr/bin/env python3
"""
Walach Aviation Mission Planner.

First milestone:
- Standalone GUI, separate from the transmitter configurator.
- Click a browser map to add waypoints.
- Edit altitude, speed, waypoint action, and waypoint event metadata.
- Save/load missions as JSON.

Future milestones can add serial upload/download once the flight-controller
protocol is ready.
"""

from __future__ import annotations

import json
import os
import queue
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from mission_schema import (
    ACTION_TYPES,
    EVENT_TYPES,
    DEFAULT_ALTITUDE_M,
    DEFAULT_SPEED_MPS,
    Mission,
    Waypoint,
    WaypointEvent,
    mission_from_dict,
    mission_to_dict,
    validate_mission,
)


APP_TITLE = "Walach Aviation Mission Planner"
MAP_DIR = "mission_map"
MAP_INDEX = "index.html"
MAP_STYLE = "style.css"
MAP_SCRIPT = "mission.js"
MISSION_DATA = "mission.json"
MAP_SERVER_PORT = 8787


class ReusableThreadingHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True


def app_dir() -> Path:
    if getattr(sys, "frozen", False):
        if sys.platform == "darwin":
            return Path.home() / "Library" / "Application Support" / APP_TITLE
        if sys.platform == "win32":
            base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
            if base:
                return Path(base) / APP_TITLE
            return Path.home() / "AppData" / "Local" / APP_TITLE
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def make_map_handler(public_dir: Path, event_queue: queue.Queue):
    class MissionMapHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            parsed = urlparse(self.path)
            path = parsed.path
            if path in ("", "/", f"/{MAP_INDEX}"):
                self.send_file(public_dir / MAP_INDEX, "text/html; charset=utf-8")
            elif path == f"/{MAP_STYLE}":
                self.send_file(public_dir / MAP_STYLE, "text/css; charset=utf-8")
            elif path == f"/{MAP_SCRIPT}":
                self.send_file(public_dir / MAP_SCRIPT, "application/javascript; charset=utf-8")
            elif path == f"/{MISSION_DATA}":
                self.send_file(public_dir / MISSION_DATA, "application/json; charset=utf-8")
            else:
                self.send_error(404, "Mission planner file not found")

        def do_POST(self):
            parsed = urlparse(self.path)
            if parsed.path == "/api/add_waypoint":
                self.handle_add_waypoint()
            elif parsed.path == "/api/select_waypoint":
                self.handle_select_waypoint()
            else:
                self.send_error(404, "Mission planner API not found")

        def handle_add_waypoint(self):
            payload = self.read_json()
            try:
                lat = float(payload["lat"])
                lon = float(payload["lon"])
            except Exception:
                self.send_json({"ok": False, "error": "Invalid waypoint position"}, status=400)
                return
            event_queue.put(("add_waypoint", {"lat": lat, "lon": lon}))
            self.send_json({"ok": True})

        def handle_select_waypoint(self):
            payload = self.read_json()
            try:
                waypoint_id = int(payload["id"])
            except Exception:
                self.send_json({"ok": False, "error": "Invalid waypoint ID"}, status=400)
                return
            event_queue.put(("select_waypoint", waypoint_id))
            self.send_json({"ok": True})

        def read_json(self):
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length).decode("utf-8")
            return json.loads(body or "{}")

        def send_file(self, path: Path, content_type: str):
            try:
                body = path.read_bytes()
            except FileNotFoundError:
                self.send_error(404, f"{path.name} not found")
                return
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def send_json(self, payload: dict, status: int = 200):
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *args):
            return

    return MissionMapHandler


class MissionPlannerApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("1320x780")
        self.minsize(1080, 660)

        self.base_dir = app_dir()
        self.map_dir = self.base_dir / MAP_DIR
        self.current_file: Path | None = None
        self.mission = Mission()
        self.selected_waypoint_id: int | None = None
        self.map_server = None
        self.map_server_thread = None
        self.map_server_port = MAP_SERVER_PORT
        self.map_events = queue.Queue()
        self._loading_editor = False

        self.name_var = tk.StringVar(value=self.mission.name)
        self.status_var = tk.StringVar(value="New mission")
        self.selected_var = tk.StringVar(value="No waypoint selected")
        self.home_lat_var = tk.StringVar(value="")
        self.home_lon_var = tk.StringVar(value="")
        self.home_alt_var = tk.IntVar(value=0)
        self.altitude_var = tk.IntVar(value=DEFAULT_ALTITUDE_M)
        self.speed_var = tk.IntVar(value=DEFAULT_SPEED_MPS)
        self.action_var = tk.StringVar(value="waypoint")
        self.event_type_var = tk.StringVar(value="none")
        self.servo_channel_var = tk.StringVar(value="")
        self.servo_pwm_var = tk.StringVar(value="")
        self.hold_seconds_var = tk.IntVar(value=0)
        self.notes_var = tk.StringVar(value="")
        self.event_notes_var = tk.StringVar(value="")

        self.ensure_map_files()
        self.write_mission_data()
        self.build_ui()
        self.after(100, self.process_map_events)

    def build_ui(self):
        self.configure(bg="#eef2f5")
        style = ttk.Style(self)
        if "clam" in style.theme_names():
            style.theme_use("clam")
        style.configure("TFrame", background="#eef2f5")
        style.configure("Panel.TFrame", background="#ffffff")
        style.configure("TLabel", background="#eef2f5", foreground="#17212b")
        style.configure("Panel.TLabel", background="#ffffff", foreground="#17212b")
        style.configure("Muted.TLabel", background="#ffffff", foreground="#60707d")
        style.configure("TButton", padding=(10, 5))
        style.configure("Treeview", rowheight=28)

        root = ttk.Frame(self, padding=10)
        root.pack(fill="both", expand=True)

        toolbar = ttk.Frame(root)
        toolbar.pack(fill="x")
        ttk.Button(toolbar, text="New", command=self.new_mission).pack(side="left")
        ttk.Button(toolbar, text="Open", command=self.open_mission).pack(side="left", padx=(6, 0))
        ttk.Button(toolbar, text="Save", command=self.save_mission).pack(side="left", padx=(6, 0))
        ttk.Button(toolbar, text="Save As", command=self.save_mission_as).pack(side="left", padx=(6, 0))
        ttk.Button(toolbar, text="Open Map", command=self.open_map).pack(side="left", padx=(18, 0))
        ttk.Button(toolbar, text="Set Home From First WP", command=self.set_home_from_first_waypoint).pack(side="left", padx=(6, 0))
        ttk.Button(toolbar, text="Validate", command=self.show_validation).pack(side="left", padx=(18, 0))
        ttk.Button(toolbar, text="Upload", command=self.upload_placeholder).pack(side="left", padx=(6, 0))
        ttk.Label(toolbar, textvariable=self.status_var).pack(side="left", padx=18)

        panes = ttk.Panedwindow(root, orient="horizontal")
        panes.pack(fill="both", expand=True, pady=(10, 0))

        left = ttk.Frame(panes)
        right = ttk.Frame(panes, style="Panel.TFrame", padding=12)
        panes.add(left, weight=3)
        panes.add(right, weight=1)

        self.build_table(left)
        self.build_editor(right)

    def build_table(self, parent):
        top = ttk.Frame(parent)
        top.pack(fill="x", pady=(0, 8))
        ttk.Label(top, text="Mission Name").pack(side="left")
        name_entry = ttk.Entry(top, textvariable=self.name_var, width=36)
        name_entry.pack(side="left", padx=8)
        name_entry.bind("<FocusOut>", lambda _event: self.update_mission_name())
        name_entry.bind("<Return>", lambda _event: self.update_mission_name())
        ttk.Button(top, text="Move Up", command=lambda: self.move_selected(-1)).pack(side="left", padx=(12, 0))
        ttk.Button(top, text="Move Down", command=lambda: self.move_selected(1)).pack(side="left", padx=(6, 0))
        ttk.Button(top, text="Delete", command=self.delete_selected_waypoint).pack(side="left", padx=(6, 0))

        columns = ("seq", "id", "lat", "lon", "altitude_m", "speed_mps", "action", "event")
        self.table = ttk.Treeview(parent, columns=columns, show="headings", selectmode="browse")
        headings = {
            "seq": "#",
            "id": "ID",
            "lat": "Latitude",
            "lon": "Longitude",
            "altitude_m": "Alt m",
            "speed_mps": "Speed m/s",
            "action": "Action",
            "event": "Event",
        }
        widths = {
            "seq": 48,
            "id": 54,
            "lat": 130,
            "lon": 130,
            "altitude_m": 78,
            "speed_mps": 92,
            "action": 120,
            "event": 120,
        }
        for col in columns:
            self.table.heading(col, text=headings[col])
            self.table.column(col, width=widths[col], anchor="center", stretch=col in ("action", "event"))

        yscroll = ttk.Scrollbar(parent, orient="vertical", command=self.table.yview)
        self.table.configure(yscrollcommand=yscroll.set)
        self.table.pack(side="left", fill="both", expand=True)
        yscroll.pack(side="left", fill="y")
        self.table.bind("<<TreeviewSelect>>", self.on_table_select)

    def build_editor(self, parent):
        ttk.Label(parent, text="Waypoint Editor", style="Panel.TLabel", font=("TkDefaultFont", 15, "bold")).pack(anchor="w")
        ttk.Label(parent, textvariable=self.selected_var, style="Muted.TLabel").pack(anchor="w", pady=(2, 12))

        home_box = ttk.LabelFrame(parent, text="Home", padding=10)
        home_box.pack(fill="x", pady=(0, 12))
        self.form_entry(home_box, "Lat", self.home_lat_var)
        self.form_entry(home_box, "Lon", self.home_lon_var)
        self.form_spin(home_box, "Alt m", self.home_alt_var, -500, 10000)
        ttk.Button(home_box, text="Apply Home", command=self.apply_home).pack(fill="x", pady=(8, 0))

        waypoint_box = ttk.LabelFrame(parent, text="Selected Waypoint", padding=10)
        waypoint_box.pack(fill="x")
        self.form_spin(waypoint_box, "Altitude m", self.altitude_var, 0, 10000)
        self.form_spin(waypoint_box, "Speed m/s", self.speed_var, 0, 100)
        self.form_combo(waypoint_box, "Action", self.action_var, ACTION_TYPES)
        self.form_combo(waypoint_box, "Event", self.event_type_var, EVENT_TYPES)
        self.form_entry(waypoint_box, "Servo Ch", self.servo_channel_var)
        self.form_entry(waypoint_box, "Servo PWM", self.servo_pwm_var)
        self.form_spin(waypoint_box, "Hold sec", self.hold_seconds_var, 0, 3600)
        self.form_entry(waypoint_box, "Notes", self.notes_var)
        self.form_entry(waypoint_box, "Event Notes", self.event_notes_var)
        ttk.Button(waypoint_box, text="Apply Waypoint Changes", command=self.apply_waypoint_editor).pack(fill="x", pady=(10, 0))

        summary = ttk.LabelFrame(parent, text="Summary", padding=10)
        summary.pack(fill="both", expand=True, pady=(12, 0))
        self.summary_var = tk.StringVar(value="")
        ttk.Label(summary, textvariable=self.summary_var, style="Panel.TLabel", justify="left", wraplength=330).pack(anchor="nw", fill="x")
        self.refresh_summary()

    def form_entry(self, parent, label, variable):
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=3)
        ttk.Label(row, text=label, width=11).pack(side="left")
        ttk.Entry(row, textvariable=variable).pack(side="left", fill="x", expand=True)

    def form_spin(self, parent, label, variable, from_, to):
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=3)
        ttk.Label(row, text=label, width=11).pack(side="left")
        ttk.Spinbox(row, from_=from_, to=to, increment=1, textvariable=variable, width=10).pack(side="left")

    def form_combo(self, parent, label, variable, values):
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=3)
        ttk.Label(row, text=label, width=11).pack(side="left")
        ttk.Combobox(row, textvariable=variable, values=values, state="readonly").pack(side="left", fill="x", expand=True)

    def new_mission(self):
        self.current_file = None
        self.mission = Mission()
        self.selected_waypoint_id = None
        self.name_var.set(self.mission.name)
        self.load_home_editor()
        self.refresh_all("New mission")

    def open_mission(self):
        path = filedialog.askopenfilename(
            title="Open Mission",
            filetypes=[("Mission JSON", "*.json"), ("All Files", "*.*")],
        )
        if not path:
            return
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            self.mission = mission_from_dict(data)
        except Exception as exc:
            messagebox.showerror(APP_TITLE, f"Could not open mission:\n{exc}")
            return
        self.current_file = Path(path)
        self.selected_waypoint_id = None
        self.name_var.set(self.mission.name)
        self.load_home_editor()
        self.refresh_all(f"Opened {self.current_file.name}")

    def save_mission(self):
        self.update_mission_name()
        self.apply_home(show_errors=False)
        if not self.current_file:
            return self.save_mission_as()
        try:
            self.current_file.write_text(json.dumps(mission_to_dict(self.mission), indent=2), encoding="utf-8")
        except Exception as exc:
            messagebox.showerror(APP_TITLE, f"Could not save mission:\n{exc}")
            return False
        self.refresh_all(f"Saved {self.current_file.name}")
        return True

    def save_mission_as(self):
        self.update_mission_name()
        path = filedialog.asksaveasfilename(
            title="Save Mission",
            defaultextension=".json",
            filetypes=[("Mission JSON", "*.json"), ("All Files", "*.*")],
            initialfile=self.safe_mission_filename(),
        )
        if not path:
            return False
        self.current_file = Path(path)
        return self.save_mission()

    def safe_mission_filename(self):
        name = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in self.name_var.get().strip())
        return f"{name or 'mission'}.json"

    def update_mission_name(self):
        self.mission.name = self.name_var.get().strip() or "Untitled Mission"
        self.name_var.set(self.mission.name)
        self.write_mission_data()
        self.refresh_summary()

    def add_waypoint(self, lat: float, lon: float):
        waypoint = Waypoint(
            id=self.mission.next_waypoint_id(),
            lat=lat,
            lon=lon,
            altitude_m=self.mission.defaults.altitude_m,
            speed_mps=self.mission.defaults.speed_mps,
        )
        self.mission.waypoints.append(waypoint)
        if self.mission.home.lat is None or self.mission.home.lon is None:
            self.mission.home.lat = lat
            self.mission.home.lon = lon
            self.load_home_editor()
        self.selected_waypoint_id = waypoint.id
        self.refresh_all(f"Added waypoint {waypoint.id}")

    def on_table_select(self, _event=None):
        if self._loading_editor:
            return
        selected = self.table.selection()
        if not selected:
            return
        self.selected_waypoint_id = int(selected[0])
        self.load_waypoint_editor()
        self.write_mission_data()

    def select_waypoint(self, waypoint_id: int):
        if not self.get_waypoint(waypoint_id):
            return
        self.selected_waypoint_id = waypoint_id
        self.refresh_all(f"Selected waypoint {waypoint_id}")

    def get_waypoint(self, waypoint_id: int | None):
        if waypoint_id is None:
            return None
        for waypoint in self.mission.waypoints:
            if waypoint.id == waypoint_id:
                return waypoint
        return None

    def load_waypoint_editor(self):
        waypoint = self.get_waypoint(self.selected_waypoint_id)
        self._loading_editor = True
        try:
            if waypoint is None:
                self.selected_var.set("No waypoint selected")
                return
            self.selected_var.set(f"Waypoint {waypoint.id} at {waypoint.lat:.6f}, {waypoint.lon:.6f}")
            self.altitude_var.set(waypoint.altitude_m)
            self.speed_var.set(waypoint.speed_mps)
            self.action_var.set(waypoint.action)
            self.event_type_var.set(waypoint.event.type)
            self.servo_channel_var.set("" if waypoint.event.servo_channel is None else str(waypoint.event.servo_channel))
            self.servo_pwm_var.set("" if waypoint.event.servo_pwm is None else str(waypoint.event.servo_pwm))
            self.hold_seconds_var.set(waypoint.event.hold_seconds)
            self.notes_var.set(waypoint.notes)
            self.event_notes_var.set(waypoint.event.notes)
        finally:
            self._loading_editor = False

    def apply_waypoint_editor(self):
        waypoint = self.get_waypoint(self.selected_waypoint_id)
        if waypoint is None:
            messagebox.showwarning(APP_TITLE, "Select a waypoint first.")
            return
        try:
            waypoint.altitude_m = int(self.altitude_var.get())
            waypoint.speed_mps = int(self.speed_var.get())
            waypoint.action = self.action_var.get()
            waypoint.event = WaypointEvent(
                type=self.event_type_var.get(),
                servo_channel=self.optional_int(self.servo_channel_var.get()),
                servo_pwm=self.optional_int(self.servo_pwm_var.get()),
                hold_seconds=int(self.hold_seconds_var.get()),
                notes=self.event_notes_var.get().strip(),
            )
            waypoint.notes = self.notes_var.get().strip()
        except Exception as exc:
            messagebox.showerror(APP_TITLE, f"Could not apply waypoint changes:\n{exc}")
            return
        self.refresh_all(f"Updated waypoint {waypoint.id}")

    def apply_home(self, show_errors=True):
        try:
            self.mission.home.lat = self.optional_float(self.home_lat_var.get())
            self.mission.home.lon = self.optional_float(self.home_lon_var.get())
            self.mission.home.altitude_m = int(self.home_alt_var.get())
        except Exception as exc:
            if show_errors:
                messagebox.showerror(APP_TITLE, f"Could not apply home point:\n{exc}")
            return False
        self.refresh_all("Updated home point")
        return True

    def load_home_editor(self):
        self.home_lat_var.set("" if self.mission.home.lat is None else f"{self.mission.home.lat:.7f}")
        self.home_lon_var.set("" if self.mission.home.lon is None else f"{self.mission.home.lon:.7f}")
        self.home_alt_var.set(self.mission.home.altitude_m)

    def set_home_from_first_waypoint(self):
        if not self.mission.waypoints:
            messagebox.showwarning(APP_TITLE, "Add a waypoint before setting home.")
            return
        first = self.mission.waypoints[0]
        self.mission.home.lat = first.lat
        self.mission.home.lon = first.lon
        self.load_home_editor()
        self.refresh_all("Home set from first waypoint")

    def delete_selected_waypoint(self):
        waypoint = self.get_waypoint(self.selected_waypoint_id)
        if waypoint is None:
            return
        self.mission.waypoints = [wp for wp in self.mission.waypoints if wp.id != waypoint.id]
        self.selected_waypoint_id = self.mission.waypoints[0].id if self.mission.waypoints else None
        self.refresh_all(f"Deleted waypoint {waypoint.id}")

    def move_selected(self, delta: int):
        waypoint = self.get_waypoint(self.selected_waypoint_id)
        if waypoint is None:
            return
        index = self.mission.waypoints.index(waypoint)
        new_index = index + delta
        if new_index < 0 or new_index >= len(self.mission.waypoints):
            return
        self.mission.waypoints[index], self.mission.waypoints[new_index] = (
            self.mission.waypoints[new_index],
            self.mission.waypoints[index],
        )
        self.refresh_all(f"Moved waypoint {waypoint.id}")

    def show_validation(self):
        issues = validate_mission(self.mission)
        if issues:
            messagebox.showwarning(APP_TITLE, "Mission needs attention:\n\n" + "\n".join(f"- {issue}" for issue in issues))
        else:
            messagebox.showinfo(APP_TITLE, "Mission validation passed.")

    def upload_placeholder(self):
        messagebox.showinfo(
            APP_TITLE,
            "Mission upload will be added after the flight-controller serial protocol is defined.",
        )

    def refresh_all(self, status: str | None = None):
        self.refresh_table()
        self.load_waypoint_editor()
        self.write_mission_data()
        self.refresh_summary()
        if status:
            self.status_var.set(status)

    def refresh_table(self):
        selected_id = self.selected_waypoint_id
        self._loading_editor = True
        try:
            for item in self.table.get_children():
                self.table.delete(item)
            for index, waypoint in enumerate(self.mission.waypoints, start=1):
                self.table.insert(
                    "",
                    "end",
                    iid=str(waypoint.id),
                    values=(
                        index,
                        waypoint.id,
                        f"{waypoint.lat:.7f}",
                        f"{waypoint.lon:.7f}",
                        waypoint.altitude_m,
                        waypoint.speed_mps,
                        waypoint.action,
                        waypoint.event.type,
                    ),
                )
            if selected_id and self.get_waypoint(selected_id):
                self.table.selection_set(str(selected_id))
                self.table.see(str(selected_id))
        finally:
            self._loading_editor = False

    def refresh_summary(self):
        distance_note = "Distance estimate will come in a later pass."
        home = self.mission.home
        home_text = "not set"
        if home.lat is not None and home.lon is not None:
            home_text = f"{home.lat:.6f}, {home.lon:.6f}, {home.altitude_m} m"
        self.summary_var.set(
            f"Mission: {self.mission.name}\n"
            f"Waypoints: {len(self.mission.waypoints)}\n"
            f"Home: {home_text}\n"
            f"Default altitude: {self.mission.defaults.altitude_m} m\n"
            f"Default speed: {self.mission.defaults.speed_mps} m/s\n\n"
            f"{distance_note}"
        )

    def write_mission_data(self):
        self.map_dir.mkdir(parents=True, exist_ok=True)
        payload = mission_to_dict(self.mission)
        payload["selected_waypoint_id"] = self.selected_waypoint_id
        payload["generated_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        (self.map_dir / MISSION_DATA).write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")

    def ensure_map_files(self):
        self.map_dir.mkdir(parents=True, exist_ok=True)
        expected = {
            MAP_INDEX: INDEX_HTML,
            MAP_STYLE: STYLE_CSS,
            MAP_SCRIPT: MISSION_JS,
        }
        for filename, content in expected.items():
            path = self.map_dir / filename
            if not path.exists() or path.read_text(encoding="utf-8") != content:
                path.write_text(content, encoding="utf-8")

    def start_map_server(self):
        if self.map_server:
            return
        handler = make_map_handler(self.map_dir, self.map_events)
        try:
            self.map_server = ReusableThreadingHTTPServer(("127.0.0.1", MAP_SERVER_PORT), handler)
        except OSError:
            self.map_server = ReusableThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.map_server_port = self.map_server.server_address[1]
        self.map_server_thread = threading.Thread(target=self.map_server.serve_forever, daemon=True)
        self.map_server_thread.start()
        self.status_var.set(f"Map server running at http://127.0.0.1:{self.map_server_port}/{MAP_INDEX}")

    def open_map(self):
        self.ensure_map_files()
        self.write_mission_data()
        self.start_map_server()
        url = f"http://127.0.0.1:{self.map_server_port}/{MAP_INDEX}"
        try:
            if sys.platform == "win32":
                os.startfile(url)
            elif not webbrowser.open(url):
                raise RuntimeError("No browser accepted the map URL.")
        except Exception as exc:
            self.clipboard_clear()
            self.clipboard_append(url)
            messagebox.showerror(APP_TITLE, f"Could not open the map browser window: {exc}\n\nMap URL copied to clipboard:\n{url}")

    def process_map_events(self):
        while True:
            try:
                kind, value = self.map_events.get_nowait()
            except queue.Empty:
                break
            if kind == "add_waypoint":
                self.add_waypoint(value["lat"], value["lon"])
            elif kind == "select_waypoint":
                self.select_waypoint(value)
        self.after(100, self.process_map_events)

    @staticmethod
    def optional_int(value: str) -> int | None:
        value = value.strip()
        return None if value == "" else int(value)

    @staticmethod
    def optional_float(value: str) -> float | None:
        value = value.strip()
        return None if value == "" else float(value)


INDEX_HTML = """<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Walach Aviation Mission Planner Map</title>
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
  <link rel="stylesheet" href="style.css">
  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
</head>
<body>
  <div id="map"></div>
  <div class="hud" id="hud">
    <strong>Mission Planner</strong>
    <span>Click the map to add waypoints.</span>
  </div>
  <script src="mission.js"></script>
</body>
</html>
"""


STYLE_CSS = """html, body, #map {
  height: 100%;
  margin: 0;
}

body {
  font: 14px/1.35 system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}

.hud {
  position: absolute;
  top: 12px;
  right: 12px;
  z-index: 1000;
  min-width: 250px;
  max-width: 320px;
  padding: 10px 12px;
  background: rgba(255, 255, 255, 0.94);
  border: 1px solid #cfd8df;
  border-radius: 6px;
  box-shadow: 0 8px 22px rgba(0, 0, 0, 0.14);
  color: #17212b;
}

.hud strong {
  display: block;
  margin-bottom: 4px;
}

.waypoint-label {
  width: 26px;
  height: 26px;
  border-radius: 50%;
  border: 2px solid #ffffff;
  background: #0f7f8f;
  color: #ffffff;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 700;
  box-shadow: 0 2px 7px rgba(0, 0, 0, 0.28);
}

.waypoint-label.selected {
  background: #c2410c;
}
"""


MISSION_JS = """const map = L.map('map').setView([39.7392, -104.9903], 12);

L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
  maxZoom: 19,
  attribution: '&copy; OpenStreetMap contributors'
}).addTo(map);

let markers = new Map();
let route = L.polyline([], { color: '#0f7f8f', weight: 3 }).addTo(map);
let latestSignature = '';
let hasFitMission = false;

function waypointIcon(number, selected) {
  return L.divIcon({
    className: '',
    html: `<div class="waypoint-label ${selected ? 'selected' : ''}">${number}</div>`,
    iconSize: [26, 26],
    iconAnchor: [13, 13]
  });
}

async function postJSON(url, payload) {
  await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  });
}

map.on('click', async event => {
  await postJSON('/api/add_waypoint', {
    lat: event.latlng.lat,
    lon: event.latlng.lng
  });
  setTimeout(refreshMission, 150);
});

async function refreshMission() {
  try {
    const response = await fetch('mission.json?cache=' + Date.now());
    const mission = await response.json();
    const signature = JSON.stringify({
      waypoints: mission.waypoints,
      selected: mission.selected_waypoint_id,
      home: mission.home
    });
    if (signature === latestSignature) return;
    latestSignature = signature;
    renderMission(mission);
  } catch (err) {
    document.getElementById('hud').innerHTML =
      '<strong>Mission Planner</strong><span>Waiting for mission data.</span>';
  }
}

function renderMission(mission) {
  const waypoints = mission.waypoints || [];
  const selectedId = mission.selected_waypoint_id;
  const seen = new Set();
  const latLngs = [];

  waypoints.forEach((wp, index) => {
    const id = Number(wp.id);
    seen.add(id);
    const latLng = [Number(wp.lat), Number(wp.lon)];
    latLngs.push(latLng);
    const selected = id === selectedId;
    let marker = markers.get(id);
    if (!marker) {
      marker = L.marker(latLng, { icon: waypointIcon(index + 1, selected), draggable: false }).addTo(map);
      marker.on('click', async () => {
        await postJSON('/api/select_waypoint', { id });
        setTimeout(refreshMission, 120);
      });
      markers.set(id, marker);
    }
    marker.setLatLng(latLng);
    marker.setIcon(waypointIcon(index + 1, selected));
    marker.bindPopup(
      `<strong>Waypoint ${index + 1}</strong><br>` +
      `ID: ${wp.id}<br>` +
      `Lat: ${Number(wp.lat).toFixed(7)}<br>` +
      `Lon: ${Number(wp.lon).toFixed(7)}<br>` +
      `Alt: ${wp.altitude_m} m<br>` +
      `Speed: ${wp.speed_mps} m/s<br>` +
      `Action: ${wp.action}<br>` +
      `Event: ${(wp.event && wp.event.type) || 'none'}`
    );
  });

  for (const [id, marker] of markers.entries()) {
    if (!seen.has(id)) {
      map.removeLayer(marker);
      markers.delete(id);
    }
  }

  route.setLatLngs(latLngs);
  updateHud(mission);

  if (!hasFitMission && latLngs.length > 0) {
    map.fitBounds(L.latLngBounds(latLngs).pad(0.25));
    hasFitMission = true;
  }
}

function updateHud(mission) {
  const waypoints = mission.waypoints || [];
  const selected = waypoints.find(wp => Number(wp.id) === mission.selected_waypoint_id);
  const selectedText = selected
    ? `Selected: WP ${selected.id}, ${selected.altitude_m} m`
    : 'Selected: none';
  document.getElementById('hud').innerHTML =
    `<strong>${mission.name || 'Mission Planner'}</strong>` +
    `<span>Waypoints: ${waypoints.length}</span><br>` +
    `<span>${selectedText}</span><br>` +
    '<span>Click map to add waypoint.</span>';
}

refreshMission();
setInterval(refreshMission, 1000);
"""


if __name__ == "__main__":
    app = MissionPlannerApp()
    app.mainloop()
