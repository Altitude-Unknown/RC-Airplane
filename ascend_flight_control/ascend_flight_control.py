#!/usr/bin/env python3
"""
ASCEND Flight Control: ground station for the ASCEND flight controller (ArduPlane).

- Click the in-app map to add waypoints; see the aircraft live while connected.
- Edit altitude, speed, waypoint action, and waypoint event metadata.
- Save/load missions as JSON.
- Connect to the flight controller over MAVLink (USB, telemetry radio or SITL).
- Upload missions with read-back verification, and download missions.
- Aircraft Settings: curated, plain-English parameter editor; All Parameters
  for everything else. Changes are staged, reviewed, written and verified.
"""

from __future__ import annotations

import json
import os
import queue
import sys
import threading
import time
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from fc_link import FcLink, VehicleStatus, list_connection_choices

# The RC Configurator (transmitter models, firmware updates, instructor/student)
# lives one folder up in RC-Airplane and is shown as its own tab.
_RC_DIR = Path(__file__).resolve().parent.parent
if str(_RC_DIR) not in sys.path:
    sys.path.append(str(_RC_DIR))
try:
    import fram_gui_models as rc_configurator
    RC_CONFIGURATOR_ERROR = None
except Exception as exc:  # e.g. a missing serial or esptool package
    rc_configurator = None
    RC_CONFIGURATOR_ERROR = exc
from mission_mavlink import (
    MissionTransferError,
    compare_items,
    download_mission,
    items_to_mission,
    mission_to_items,
    upload_mission,
)
from param_catalog import CATALOG, PROTECTED
from param_protocol import (
    ParamError,
    download_all,
    load_param_file,
    plan_file_restore,
    save_param_file,
    write_changes,
)
from calibration_view import CalibrationTab
from flight_view import FlightTab
from map_view import MissionMap
from mission_mavlink import NAV_COMMANDS
from units import ALT_NAMES, PRESETS, SPEED_NAMES, VSPEED_NAMES, Units
from version import APP_VERSION
from params_view import AllParamsTab, ParamStore, SettingsTab, load_metadata, setup_styles
from mission_schema import (
    ACTION_TYPES,
    EVENT_TYPES,
    DEFAULT_ALTITUDE_M,
    DEFAULT_SPEED_MPS,
    LOITER_MAX_RADIUS_M,
    LoiterSettings,
    Mission,
    Waypoint,
    WaypointEvent,
    mission_from_dict,
    mission_to_dict,
    validate_mission,
)


APP_TITLE = "ASCEND Flight Control"
LOITER_MODE_LABELS = {"time": "A set time", "turns": "A number of laps", "forever": "Until the mode changes"}
DIRECTION_LABELS = {True: "Clockwise", False: "Counter-clockwise"}
ARDUPLANE_DEFAULT_LOITER_RAD = 60  # WP_LOITER_RAD default, used until settings are loaded
BAUD_RATES = ["115200", "57600", "921600"]


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


class FlightControlApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"{APP_TITLE} {APP_VERSION}")
        self.geometry("1320x780")
        self.minsize(1080, 660)

        self.base_dir = app_dir()
        self.current_file: Path | None = None
        self.mission = Mission()
        self.selected_waypoint_id: int | None = None
        self.ui_events = queue.Queue()
        self._loading_editor = False
        self.fc_link: FcLink | None = None
        self.fc_busy = False
        self.home_auto = True  # home follows the first waypoint until the user sets it
        self.units = Units.load()
        self.unit_labels: list[tuple[tk.Widget, str]] = []  # widgets whose text names a unit
        self._target_cache = (None, {})
        metadata, self.metadata_source = load_metadata()
        self.param_store = ParamStore(metadata, self.units)
        self.setting_labels = {s.name: s.label for g in CATALOG for s in g.settings}

        self.conn_var = tk.StringVar(value="")
        self.baud_var = tk.StringVar(value=BAUD_RATES[0])
        self.fc_status_var = tk.StringVar(value="Not connected")
        self.name_var = tk.StringVar(value=self.mission.name)
        self.status_var = tk.StringVar(value="New mission")
        self.selected_var = tk.StringVar(value="No waypoint selected")
        self.home_lat_var = tk.StringVar(value="")
        self.home_lon_var = tk.StringVar(value="")
        self.home_alt_var = tk.StringVar(value="0")
        self.altitude_var = tk.StringVar(value=str(DEFAULT_ALTITUDE_M))
        self.speed_var = tk.StringVar(value=str(DEFAULT_SPEED_MPS))
        self.action_var = tk.StringVar(value="waypoint")
        self.event_type_var = tk.StringVar(value="none")
        self.servo_channel_var = tk.StringVar(value="")
        self.servo_pwm_var = tk.StringVar(value="")
        self.loiter_mode_var = tk.StringVar(value=LOITER_MODE_LABELS["time"])
        self.loiter_seconds_var = tk.IntVar(value=30)
        self.loiter_turns_var = tk.IntVar(value=3)
        self.loiter_radius_var = tk.StringVar(value="0")
        self.loiter_dir_var = tk.StringVar(value=DIRECTION_LABELS[True])
        self.loiter_hint_var = tk.StringVar(value="")
        self.notes_var = tk.StringVar(value="")
        self.event_notes_var = tk.StringVar(value="")

        self.build_ui()
        self.units.subscribe(self.apply_units)
        self.refresh_map()
        self.after(100, self.process_ui_events)
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    def on_close(self):
        count = len(self.param_store.pending)
        if count and not messagebox.askyesno(
            APP_TITLE, f"You have {count} setting change{'s' if count != 1 else ''} that were not written "
                       "to the flight controller. Quit anyway?"):
            return
        if self.fc_link:
            self.fc_link.close()
        if self.configurator is not None:
            self.configurator.shutdown()
        # Stop the map tile threads before Tk goes away (they create Tk images).
        self.mission_map.shutdown()
        self.flight_tab.map.shutdown()
        self.destroy()

    def build_ui(self):
        self.configure(bg="#f3f6f8")
        style = ttk.Style(self)
        if "clam" in style.theme_names():
            style.theme_use("clam")
        if rc_configurator is not None:
            # One look for the whole program: the RC Configurator's theme (same
            # palette), with the system font so every tab reads the same.
            rc_configurator.install_style(self)
            style.configure(".", font="TkDefaultFont")
        else:
            style.configure("TFrame", background="#f3f6f8")
            style.configure("Panel.TFrame", background="#ffffff")
            style.configure("TLabel", background="#f3f6f8", foreground="#17212b")
            style.configure("Panel.TLabel", background="#ffffff", foreground="#17212b")
            style.configure("Muted.TLabel", background="#ffffff", foreground="#60707d")
            style.configure("Treeview", rowheight=28)

        setup_styles(self)

        # Connection strip, shared by every tab.
        connbar = tk.Frame(self, bg="#ffffff", highlightbackground="#dde3e8", highlightthickness=1)
        connbar.pack(fill="x")
        tk.Label(connbar, text="ASCEND Flight Control", bg="#ffffff", fg="#17212b",
                 font=("TkDefaultFont", 15, "bold")).pack(side="left", padx=(14, 24), pady=10)
        tk.Label(connbar, text="Flight controller", bg="#ffffff", fg="#60707d").pack(side="left")
        self.conn_combo = ttk.Combobox(connbar, textvariable=self.conn_var, width=30)
        self.conn_combo.pack(side="left", padx=(8, 0))
        ttk.Combobox(connbar, textvariable=self.baud_var, values=BAUD_RATES, width=8, state="readonly").pack(side="left", padx=(6, 0))
        ttk.Button(connbar, text="Refresh", command=self.refresh_ports).pack(side="left", padx=(6, 0))
        ttk.Button(connbar, text="Units…", command=self.show_units_dialog).pack(side="right", padx=(0, 14))
        self.connect_button = ttk.Button(connbar, text="Connect", style="Accent.TButton", command=self.toggle_connection)
        self.connect_button.pack(side="left", padx=(6, 0))
        self.fc_status_label = tk.Label(connbar, textvariable=self.fc_status_var, bg="#ffffff", fg="#60707d",
                                        font=("TkDefaultFont", 13))
        self.fc_status_label.pack(side="left", padx=18)
        tk.Label(connbar, textvariable=self.status_var, bg="#ffffff", fg="#60707d",
                 font=("TkDefaultFont", 12)).pack(side="right", padx=14)
        self.refresh_ports()

        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True, pady=(8, 0))
        root = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(root, text="Mission")
        self.flight_tab = FlightTab(self.notebook, self.units)
        self.notebook.add(self.flight_tab, text="Flight")
        param_actions = {
            "load": self.load_params,
            "backup": self.save_param_backup,
            "restore": self.restore_param_backup,
            "write": self.write_params,
        }
        self.settings_tab = SettingsTab(self.notebook, self.param_store, param_actions, self.units)
        self.notebook.add(self.settings_tab, text="Aircraft Settings")
        self.calibration_tab = CalibrationTab(self.notebook, self)
        self.notebook.add(self.calibration_tab, text="Calibration")
        self.all_params_tab = AllParamsTab(self.notebook, self.param_store, param_actions)
        self.notebook.add(self.all_params_tab, text="All Parameters")
        self.configurator = None
        if rc_configurator is not None:
            self.configurator = rc_configurator.ConfiguratorFrame(
                self.notebook, embedded=True, before_fc_flash=self.release_fc_port)
            self.notebook.add(self.configurator, text="RC Configurator")
        else:
            missing = tk.Frame(self.notebook, bg="#f3f6f8")
            tk.Label(missing, text=f"The RC Configurator could not be loaded:\n{RC_CONFIGURATOR_ERROR}\n\n"
                                   "Install the packages in RC-Airplane/requirements.txt.",
                     bg="#f3f6f8", fg="#17212b", justify="center").pack(expand=True)
            self.notebook.add(missing, text="RC Configurator")

        toolbar = ttk.Frame(root)
        toolbar.pack(fill="x")
        ttk.Button(toolbar, text="New", command=self.new_mission).pack(side="left")
        ttk.Button(toolbar, text="Open", command=self.open_mission).pack(side="left", padx=(6, 0))
        ttk.Button(toolbar, text="Save", command=self.save_mission).pack(side="left", padx=(6, 0))
        ttk.Button(toolbar, text="Save As", command=self.save_mission_as).pack(side="left", padx=(6, 0))
        ttk.Button(toolbar, text="Set Home From First WP", command=self.set_home_from_first_waypoint).pack(side="left", padx=(18, 0))
        ttk.Button(toolbar, text="Validate", command=self.show_validation).pack(side="left", padx=(18, 0))
        ttk.Button(toolbar, text="Upload to FC", command=self.upload_to_fc).pack(side="left", padx=(6, 0))
        ttk.Button(toolbar, text="Download from FC", command=self.download_from_fc).pack(side="left", padx=(6, 0))

        panes = ttk.Panedwindow(root, orient="horizontal")
        panes.pack(fill="both", expand=True, pady=(10, 0))

        left = ttk.Panedwindow(panes, orient="vertical")
        right = ttk.Frame(panes, style="Panel.TFrame", padding=12)
        panes.add(left, weight=3)
        panes.add(right, weight=1)

        self.mission_map = MissionMap(left, on_add=self.add_waypoint, on_select=self.select_waypoint)
        table_area = ttk.Frame(left)
        left.add(self.mission_map, weight=3)
        left.add(table_area, weight=1)
        # Give the map about 70% of the height once the window has its real size.
        self.after(150, lambda: left.sashpos(0, int(left.winfo_height() * 0.7)))

        self.build_table(table_area)
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
        self.table = ttk.Treeview(parent, columns=columns, show="headings", selectmode="browse", height=5)
        headings = {
            "seq": "#",
            "id": "ID",
            "lat": "Latitude",
            "lon": "Longitude",
            "altitude_m": "Alt {alt}",
            "speed_mps": "Speed {speed}",
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
            if "{" in headings[col]:
                self.unit_labels.append((("heading", col), headings[col]))
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
        self.unit_row(self.form_spin(home_box, "Alt ({alt})", self.home_alt_var, -2000, 40000), "Alt ({alt})")
        ttk.Button(home_box, text="Apply Home", command=self.apply_home).pack(fill="x", pady=(8, 0))

        waypoint_box = ttk.LabelFrame(parent, text="Selected Waypoint", padding=10)
        waypoint_box.pack(fill="x")
        self.unit_row(self.form_spin(waypoint_box, "Alt ({alt})", self.altitude_var, 0, 40000), "Alt ({alt})")
        self.unit_row(self.form_spin(waypoint_box, "Speed ({speed})", self.speed_var, 0, 400), "Speed ({speed})")
        self.action_row = self.form_combo(waypoint_box, "Action", self.action_var, ACTION_TYPES)
        self.action_row.combo.bind("<<ComboboxSelected>>", lambda _e: self.update_loiter_box())
        self.build_loiter_box(waypoint_box)
        self.form_combo(waypoint_box, "Event", self.event_type_var, EVENT_TYPES)
        self.form_entry(waypoint_box, "Servo Ch", self.servo_channel_var)
        self.form_entry(waypoint_box, "Servo PWM", self.servo_pwm_var)
        self.form_entry(waypoint_box, "Notes", self.notes_var)
        self.form_entry(waypoint_box, "Event Notes", self.event_notes_var)
        ttk.Button(waypoint_box, text="Apply Waypoint Changes", command=self.apply_waypoint_editor).pack(fill="x", pady=(10, 0))

        summary = ttk.LabelFrame(parent, text="Summary", padding=10)
        summary.pack(fill="both", expand=True, pady=(12, 0))
        self.summary_var = tk.StringVar(value="")
        ttk.Label(summary, textvariable=self.summary_var, style="Panel.TLabel", justify="left", wraplength=330).pack(anchor="nw", fill="x")
        self.refresh_summary()

    # -- units -------------------------------------------------------------------

    def unit_row(self, row, template: str):
        label = row.winfo_children()[0]
        self.unit_labels.append((label, template))
        label.configure(text=self.unit_text(template))
        return row

    def unit_text(self, template: str) -> str:
        return template.format(alt=self.units.alt_label, speed=self.units.speed_label)

    def fmt_alt_input(self, metres: float) -> str:
        return f"{self.units.alt(metres):.0f}"

    def fmt_speed_input(self, mps: float) -> str:
        value = self.units.speed(mps)
        return f"{value:.1f}".rstrip("0").rstrip(".")

    def apply_units(self):
        """Re-label and re-display everything after the Units preference changes."""
        for widget, template in self.unit_labels:
            if isinstance(widget, tuple):
                self.table.heading(widget[1], text=self.unit_text(template))
            else:
                widget.configure(text=self.unit_text(template))
        self.load_home_editor()
        self.refresh_all("Units changed")
        self.update_loiter_box()
        self.param_store.notify()

    def show_units_dialog(self):
        u = self.units.choice
        win = tk.Toplevel(self)
        win.title("Units")
        win.transient(self)
        win.resizable(False, False)
        win.configure(bg="#ffffff")
        body = tk.Frame(win, bg="#ffffff", padx=20, pady=16)
        body.pack(fill="both")
        tk.Label(body, text="Display units", bg="#ffffff", fg="#17212b",
                 font=("TkDefaultFont", 16, "bold")).grid(row=0, column=0, columnspan=2, sticky="w")
        tk.Label(body, text="Used for missions, Aircraft Settings and the Flight tab. "
                            "All Parameters always shows ArduPilot's own units.",
                 bg="#ffffff", fg="#60707d", wraplength=380, justify="left").grid(row=1, column=0, columnspan=2,
                                                                                  sticky="w", pady=(2, 12))
        speed = tk.StringVar(value=SPEED_NAMES[u.speed])
        alt = tk.StringVar(value=ALT_NAMES[u.alt])
        vspeed = tk.StringVar(value=VSPEED_NAMES[u.vspeed])
        presets = tk.Frame(body, bg="#ffffff")
        presets.grid(row=2, column=0, columnspan=2, sticky="w", pady=(0, 12))
        for name, (sp, al, vs) in PRESETS.items():
            ttk.Button(presets, text=name, command=lambda sp=sp, al=al, vs=vs: (
                speed.set(SPEED_NAMES[sp]), alt.set(ALT_NAMES[al]), vspeed.set(VSPEED_NAMES[vs]))
                       ).pack(side="left", padx=(0, 6))
        for row, (label, var, names) in enumerate((("Speed", speed, SPEED_NAMES), ("Altitude and distance", alt, ALT_NAMES),
                                                    ("Climb rate", vspeed, VSPEED_NAMES)), start=3):
            tk.Label(body, text=label, bg="#ffffff", fg="#17212b").grid(row=row, column=0, sticky="w", pady=4, padx=(0, 12))
            ttk.Combobox(body, textvariable=var, values=list(names.values()), state="readonly",
                         width=28).grid(row=row, column=1, sticky="w", pady=4)
        buttons = tk.Frame(body, bg="#ffffff")
        buttons.grid(row=6, column=0, columnspan=2, sticky="e", pady=(14, 0))

        def key(names, label):
            return next(k for k, v in names.items() if v == label)

        def save():
            self.units.set(key(SPEED_NAMES, speed.get()), key(ALT_NAMES, alt.get()), key(VSPEED_NAMES, vspeed.get()))
            win.destroy()

        ttk.Button(buttons, text="Cancel", command=win.destroy).pack(side="right")
        ttk.Button(buttons, text="Apply", style="Accent.TButton", command=save).pack(side="right", padx=(0, 6))
        win.grab_set()

    def build_loiter_box(self, parent):
        box = ttk.LabelFrame(parent, text="Loiter", padding=(10, 6))
        self.loiter_box = box
        mode_row = self.form_combo(box, "Loiter for", self.loiter_mode_var, list(LOITER_MODE_LABELS.values()))
        mode_row.combo.bind("<<ComboboxSelected>>", lambda _e: self.update_loiter_box())
        self.loiter_time_row = self.form_spin(box, "Time (s)", self.loiter_seconds_var, 1, 65535)
        self.loiter_turns_row = self.form_spin(box, "Laps", self.loiter_turns_var, 1, 255)
        self.loiter_radius_row = self.form_spin(box, "Radius ({alt})", self.loiter_radius_var, 0, 9000)
        self.unit_row(self.loiter_radius_row, "Radius ({alt})")
        self.loiter_dir_row = self.form_combo(box, "Direction", self.loiter_dir_var, list(DIRECTION_LABELS.values()))
        self.loiter_hint = ttk.Label(box, textvariable=self.loiter_hint_var, style="Muted.TLabel",
                                     wraplength=280, justify="left")
        self.loiter_hint.pack(fill="x", pady=(4, 0))

    def default_loiter_radius(self) -> tuple[int, str]:
        """The FC's default loiter radius and where it came from."""
        param = self.param_store.params.get("WP_LOITER_RAD")
        if param is not None:
            return abs(int(round(param.value))), "from the flight controller"
        return ARDUPLANE_DEFAULT_LOITER_RAD, "ArduPlane default"

    def loiter_mode(self) -> str:
        label = self.loiter_mode_var.get()
        return next((k for k, v in LOITER_MODE_LABELS.items() if v == label), "time")

    def update_loiter_box(self):
        """Show the loiter options only for loiter waypoints, and only the ones that apply."""
        if self.action_var.get() != "loiter":
            self.loiter_box.pack_forget()
            return
        self.loiter_box.pack(fill="x", pady=(4, 6), after=self.action_row)
        mode = self.loiter_mode()
        for row in (self.loiter_time_row, self.loiter_turns_row, self.loiter_radius_row, self.loiter_dir_row):
            row.pack_forget()
        if mode == "time":
            self.loiter_time_row.pack(fill="x", pady=3, before=self.loiter_hint)
        elif mode == "turns":
            self.loiter_turns_row.pack(fill="x", pady=3, before=self.loiter_hint)
        self.loiter_radius_row.pack(fill="x", pady=3, before=self.loiter_hint)
        self.loiter_dir_row.pack(fill="x", pady=3, before=self.loiter_hint)
        default, source = self.default_loiter_radius()
        if mode == "time":
            self.loiter_radius_row.spin.configure(state="disabled")
            self.loiter_hint_var.set(f"ArduPlane always circles timed loiters at the default radius: "
                                     f"{self.units.fmt_alt(default)} ({source}, WP_LOITER_RAD). The timer "
                                     "starts once the plane reaches the circle.")
        else:
            self.loiter_radius_row.spin.configure(state="normal")
            hint = f"Radius 0 uses the default, {self.units.fmt_alt(default)} ({source})."
            if mode == "forever":
                hint += " Circles until you change the flight mode."
            self.loiter_hint_var.set(hint)

    def form_entry(self, parent, label, variable):
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=3)
        ttk.Label(row, text=label, width=11).pack(side="left")
        ttk.Entry(row, textvariable=variable).pack(side="left", fill="x", expand=True)
        return row

    def form_spin(self, parent, label, variable, from_, to):
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=3)
        ttk.Label(row, text=label, width=11).pack(side="left")
        spin = ttk.Spinbox(row, from_=from_, to=to, increment=1, textvariable=variable, width=10)
        spin.pack(side="left")
        row.spin = spin
        return row

    def form_combo(self, parent, label, variable, values):
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=3)
        ttk.Label(row, text=label, width=11).pack(side="left")
        combo = ttk.Combobox(row, textvariable=variable, values=values, state="readonly")
        combo.pack(side="left", fill="x", expand=True)
        row.combo = combo
        return row

    def new_mission(self):
        self.current_file = None
        self.mission = Mission()
        self.selected_waypoint_id = None
        self.name_var.set(self.mission.name)
        self.home_auto = True
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
        self.home_auto = False
        self.load_home_editor()
        self.mission_map.reset_fit()
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
        self.refresh_map()
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
        self.refresh_map()

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
            self.altitude_var.set(self.fmt_alt_input(waypoint.altitude_m))
            self.speed_var.set(self.fmt_speed_input(waypoint.speed_mps))
            self.action_var.set(waypoint.action)
            self.event_type_var.set(waypoint.event.type)
            self.servo_channel_var.set("" if waypoint.event.servo_channel is None else str(waypoint.event.servo_channel))
            self.servo_pwm_var.set("" if waypoint.event.servo_pwm is None else str(waypoint.event.servo_pwm))
            lo = waypoint.loiter
            self.loiter_mode_var.set(LOITER_MODE_LABELS.get(lo.mode, LOITER_MODE_LABELS["time"]))
            self.loiter_seconds_var.set(lo.seconds)
            self.loiter_turns_var.set(lo.turns)
            self.loiter_radius_var.set(self.fmt_alt_input(lo.radius_m))
            self.loiter_dir_var.set(DIRECTION_LABELS[lo.clockwise])
            self.notes_var.set(waypoint.notes)
            self.event_notes_var.set(waypoint.event.notes)
        finally:
            self._loading_editor = False
            self.update_loiter_box()

    def apply_waypoint_editor(self):
        waypoint = self.get_waypoint(self.selected_waypoint_id)
        if waypoint is None:
            messagebox.showwarning(APP_TITLE, "Select a waypoint first.")
            return
        try:
            # Only convert fields that were edited; rounding the display (328 ft for 100 m)
            # must not nudge stored values.
            if self.altitude_var.get().strip() != self.fmt_alt_input(waypoint.altitude_m):
                waypoint.altitude_m = round(self.units.alt_si(float(self.altitude_var.get())), 2)
            if self.speed_var.get().strip() != self.fmt_speed_input(waypoint.speed_mps):
                waypoint.speed_mps = round(self.units.speed_si(float(self.speed_var.get())), 2)
            waypoint.action = self.action_var.get()
            waypoint.event = WaypointEvent(
                type=self.event_type_var.get(),
                servo_channel=self.optional_int(self.servo_channel_var.get()),
                servo_pwm=self.optional_int(self.servo_pwm_var.get()),
                hold_seconds=waypoint.event.hold_seconds,  # kept from older files; not edited here
                notes=self.event_notes_var.get().strip(),
            )
            waypoint.notes = self.notes_var.get().strip()
            if waypoint.action == "loiter":
                radius_m = waypoint.loiter.radius_m
                if self.loiter_radius_var.get().strip() != self.fmt_alt_input(radius_m):
                    radius_m = int(round(self.units.alt_si(float(self.loiter_radius_var.get()))))
                waypoint.loiter = LoiterSettings(
                    mode=self.loiter_mode(),
                    seconds=int(self.loiter_seconds_var.get()),
                    turns=int(self.loiter_turns_var.get()),
                    radius_m=radius_m,
                    clockwise=self.loiter_dir_var.get() == DIRECTION_LABELS[True],
                )
        except Exception as exc:
            messagebox.showerror(APP_TITLE, f"Could not apply waypoint changes:\n{exc}")
            return
        self.refresh_all(f"Updated waypoint {waypoint.id}")

    def apply_home(self, show_errors=True):
        try:
            self.mission.home.lat = self.optional_float(self.home_lat_var.get())
            self.mission.home.lon = self.optional_float(self.home_lon_var.get())
            if self.home_alt_var.get().strip() != self.fmt_alt_input(self.mission.home.altitude_m):
                self.mission.home.altitude_m = int(round(self.units.alt_si(float(self.home_alt_var.get()))))
            if show_errors:  # pressed Apply Home
                self.home_auto = False
        except Exception as exc:
            if show_errors:
                messagebox.showerror(APP_TITLE, f"Could not apply home point:\n{exc}")
            return False
        self.refresh_all("Updated home point")
        return True

    def load_home_editor(self):
        self.home_lat_var.set("" if self.mission.home.lat is None else f"{self.mission.home.lat:.7f}")
        self.home_lon_var.set("" if self.mission.home.lon is None else f"{self.mission.home.lon:.7f}")
        self.home_alt_var.set(self.fmt_alt_input(self.mission.home.altitude_m))

    def set_home_from_first_waypoint(self):
        if not self.mission.waypoints:
            messagebox.showwarning(APP_TITLE, "Add a waypoint before setting home.")
            return
        first = self.mission.waypoints[0]
        self.mission.home.lat = first.lat
        self.mission.home.lon = first.lon
        self.home_auto = True
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

    # -- flight controller ------------------------------------------------

    def refresh_ports(self):
        choices = list_connection_choices()
        self.conn_combo["values"] = choices
        if not self.conn_var.get() and choices:
            self.conn_var.set(choices[0])

    def release_fc_port(self, port: str):
        """Called by the RC Configurator just before it flashes the flight controller."""
        if self.fc_link is None or self.fc_link.device.startswith(("tcp:", "udp:")):
            return
        self.disconnect_fc()
        self.status_var.set("Disconnected so the RC Configurator can update the flight controller. "
                            "Connect again when the update finishes.")

    def disconnect_fc(self):
        if self.fc_link:
            self.fc_link.close()
            self.fc_link = None
            self.mission_map.clear_aircraft()
            self.flight_tab.map.clear_aircraft()
            self.connect_button.configure(text="Connect")
            self.fc_status_var.set("Not connected")
            self.fc_status_label.configure(fg="#60707d")

    def configurator_port(self) -> str | None:
        """The transmitter port the RC Configurator has open, if any."""
        worker = getattr(self.configurator, "w", None)
        ser = getattr(worker, "ser", None)
        return getattr(ser, "port", None) if ser is not None and getattr(ser, "is_open", False) else None

    def toggle_connection(self):
        if self.fc_busy:
            return
        if self.fc_link:
            self.disconnect_fc()
            return
        device = self.conn_var.get().strip()
        if device and device == self.configurator_port():
            messagebox.showwarning(APP_TITLE, f"{device} is the transmitter, open in the RC Configurator tab. "
                                              "Choose the flight controller's port instead.")
            return
        if not device:
            messagebox.showwarning(APP_TITLE, "Choose a serial port or network connection first.")
            return
        baud = int(self.baud_var.get())
        self.fc_status_var.set(f"Connecting to {device}...")
        self.connect_button.configure(state="disabled")

        def work():
            link = FcLink(device, baud, on_status=lambda st: self.ui_events.put(("fc_status", st)))
            try:
                link.open()
            except Exception as exc:
                self.ui_events.put(("fc_connect_failed", str(exc)))
                return
            self.ui_events.put(("fc_connected", link))

        threading.Thread(target=work, daemon=True).start()

    def require_link(self) -> bool:
        if self.fc_busy:
            messagebox.showinfo(APP_TITLE, "A flight controller transfer is already running.")
            return False
        if not self.fc_link or not self.fc_link.status.connected:
            messagebox.showwarning(APP_TITLE, "Connect to the flight controller first.")
            return False
        if self.fc_link.status.mode == "INITIALISING":
            messagebox.showinfo(APP_TITLE, "The flight controller is still starting up. Try again in a few seconds.")
            return False
        return True

    def upload_to_fc(self):
        self.update_mission_name()
        self.apply_home(show_errors=False)
        issues = validate_mission(self.mission)
        conversion = mission_to_items(self.mission)
        errors = issues + conversion.errors
        if errors:
            messagebox.showerror(APP_TITLE, "Fix these before uploading:\n\n" + "\n".join(f"- {e}" for e in errors))
            return
        if not self.require_link():
            return
        lines = [f"Upload {len(self.mission.waypoints)} waypoints ({len(conversion.items) - 1} mission items) to the flight controller?",
                 "This replaces the mission currently on the flight controller."]
        if conversion.warnings:
            lines.append("\nWarnings:\n" + "\n".join(f"- {w}" for w in conversion.warnings))
        if self.fc_link.status.armed:
            lines.append("\nTHE AIRCRAFT IS ARMED. The new mission takes effect immediately if it is flying in AUTO.")
        if not messagebox.askyesno(APP_TITLE, "\n".join(lines), icon="warning" if self.fc_link.status.armed else "question"):
            return

        link = self.fc_link
        items = conversion.items
        progress = lambda text: self.ui_events.put(("fc_progress", text))

        def work():
            try:
                upload_mission(link, items, progress)
                progress("Reading mission back to verify")
                readback = download_mission(link, progress)
                problems = compare_items(items, readback)
            except Exception as exc:
                self.ui_events.put(("fc_done", ("error", f"Upload failed: {exc}")))
                return
            if problems:
                self.ui_events.put(("fc_done", ("error", "Upload finished but the read-back does not match:\n\n" + "\n".join(problems))))
            else:
                self.ui_events.put(("fc_done", ("info", f"Mission uploaded and verified: {len(items) - 1} items on the flight controller.")))

        self.start_fc_job(work, "Uploading mission")

    def download_from_fc(self):
        if not self.require_link():
            return
        if self.mission.waypoints and not messagebox.askyesno(
            APP_TITLE, "Replace the mission in the editor with the one on the flight controller?\nUnsaved changes will be lost."
        ):
            return
        link = self.fc_link
        progress = lambda text: self.ui_events.put(("fc_progress", text))

        def work():
            try:
                items = download_mission(link, progress)
            except Exception as exc:
                self.ui_events.put(("fc_done", ("error", f"Download failed: {exc}")))
                return
            self.ui_events.put(("fc_downloaded", items))

        self.start_fc_job(work, "Downloading mission")

    # -- parameters --------------------------------------------------------

    def load_params(self, quiet=False):
        if self.fc_busy:
            if not quiet:
                messagebox.showinfo(APP_TITLE, "A flight controller transfer is already running.")
            return
        if not self.fc_link or not self.fc_link.status.connected:
            if not quiet:
                messagebox.showwarning(APP_TITLE, "Connect to the flight controller first.")
            return
        if self.param_store.pending and not messagebox.askyesno(
            APP_TITLE, "Reloading keeps your unsaved changes but refreshes every other value. Continue?"):
            return
        link = self.fc_link
        progress = lambda text: self.ui_events.put(("fc_progress", text))

        def work():
            try:
                params = download_all(link, progress)
            except Exception as exc:
                self.ui_events.put(("fc_params_failed", (quiet, f"Could not load parameters: {exc}")))
                return
            self.ui_events.put(("fc_params_loaded", params))

        self.start_fc_job(work, "Loading parameters")

    def change_line(self, name: str, new_value: float) -> str:
        store = self.param_store
        old = store.describe(name, store.params[name].value)
        new = store.describe(name, new_value)
        label = self.setting_labels.get(name)
        title = f"{label} ({name})" if label else name
        return f"{title}:  {old}  →  {new}"

    def write_params(self):
        store = self.param_store
        if not store.pending:
            return
        if self.fc_busy:
            messagebox.showinfo(APP_TITLE, "A flight controller transfer is already running.")
            return
        if not self.fc_link or not self.fc_link.status.connected:
            messagebox.showwarning(APP_TITLE, "Connect to the flight controller first. Your changes are kept.")
            return
        if self.fc_link.status.armed:
            messagebox.showwarning(APP_TITLE, "The aircraft is armed. Disarm it before changing settings.")
            return
        changes = dict(store.pending)
        lines = [self.change_line(n, v) for n, v in changes.items()]
        shown = lines[:20] + ([f"…and {len(lines) - 20} more"] if len(lines) > 20 else [])
        if not messagebox.askyesno(
            APP_TITLE, f"Write {len(changes)} change{'s' if len(changes) != 1 else ''} to the flight controller?\n\n"
                       + "\n".join(shown)):
            return
        link = self.fc_link
        params = store.params
        progress = lambda text: self.ui_events.put(("fc_progress", text))

        def work():
            try:
                results = write_changes(link, params, changes, progress)
            except Exception as exc:
                self.ui_events.put(("fc_done", ("error", f"Writing settings failed: {exc}")))
                return
            self.ui_events.put(("fc_params_written", results))

        self.start_fc_job(work, "Writing settings")

    def finish_param_write(self, results):
        store = self.param_store
        for r in results:
            if r.ok and r.name in store.pending and store.pending[r.name] == r.requested:
                del store.pending[r.name]
        store.notify()
        self.refresh_map()
        self.update_loiter_box()
        good = [r for r in results if r.ok]
        bad = [r for r in results if not r.ok]
        reboot = [r.name for r in good if store.info(r.name).get("RebootRequired") == "True"]
        self.status_var.set(f"Wrote {len(good)} of {len(results)} settings")
        if bad:
            messagebox.showerror(
                APP_TITLE,
                f"{len(good)} setting{'s' if len(good) != 1 else ''} written and verified.\n\n"
                "These did not take effect:\n" + "\n".join(f"- {r.name}: {r.message}" for r in bad)
                + "\n\nThey are still marked as unsaved changes.")
        else:
            messagebox.showinfo(APP_TITLE, f"{len(good)} setting{'s' if len(good) != 1 else ''} written and verified.")
        if reboot and self.fc_link and not self.fc_link.status.armed:
            if messagebox.askyesno(APP_TITLE, "These changes take effect after the flight controller restarts:\n\n"
                                   + "\n".join(f"- {n}" for n in reboot) + "\n\nRestart it now?"):
                self.fc_link.reboot()
                self.status_var.set("Flight controller restarting…")

    def save_param_backup(self):
        store = self.param_store
        if not store.loaded:
            messagebox.showwarning(APP_TITLE, "Load the settings from the flight controller first.")
            return
        if store.pending:
            messagebox.showinfo(APP_TITLE, "The backup holds the values on the flight controller. "
                                           "Your unsaved changes are not included.")
        path = filedialog.asksaveasfilename(
            title="Save Settings Backup", defaultextension=".param",
            initialfile=time.strftime("ascend-fc-settings-%Y-%m-%d.param"),
            filetypes=[("Parameter file", "*.param"), ("All Files", "*.*")])
        if not path:
            return
        header = (f"ASCEND Flight Control settings backup {time.strftime('%Y-%m-%d %H:%M')}\n"
                  f"Connection: {self.fc_link.device if self.fc_link else 'unknown'}")
        try:
            save_param_file(Path(path), store.params, header)
        except Exception as exc:
            messagebox.showerror(APP_TITLE, f"Could not save the backup:\n{exc}")
            return
        self.status_var.set(f"Saved {len(store.params)} settings to {Path(path).name}")

    def restore_param_backup(self):
        store = self.param_store
        if not store.loaded:
            messagebox.showwarning(APP_TITLE, "Load the settings from the flight controller first, "
                                              "so the backup can be compared with it.")
            return
        path = filedialog.askopenfilename(
            title="Restore Settings Backup",
            filetypes=[("Parameter file", "*.param *.parm *.txt"), ("All Files", "*.*")])
        if not path:
            return
        try:
            plan = plan_file_restore(load_param_file(Path(path)), store.params)
        except (OSError, ParamError) as exc:
            messagebox.showerror(APP_TITLE, f"Could not read the backup:\n{exc}")
            return
        changes = dict(plan.changes)
        if plan.calibration_changes:
            if messagebox.askyesno(
                APP_TITLE,
                f"The file has {len(plan.calibration_changes)} calibration values (accelerometer, compass, "
                "level and radio calibration) that differ from this flight controller.\n\n"
                "Only restore them if the file came from this same board. Restore calibrations too?",
                icon="warning", default="no"):
                changes.update(plan.calibration_changes)
        for name, value in changes.items():
            store.pending[name] = float(int(round(value))) if store.params[name].is_int else value
        store.notify()
        notes = []
        if plan.unknown:
            notes.append(f"{len(plan.unknown)} names in the file are not on this firmware and were ignored.")
        if plan.skipped:
            notes.append(f"{len(plan.skipped)} counters and sensor IDs were skipped.")
        protected = [n for n in changes if n in PROTECTED]
        if protected:
            notes.append("Check these protected settings before writing: " + ", ".join(protected))
        messagebox.showinfo(
            APP_TITLE,
            f"{len(changes)} setting{'s' if len(changes) != 1 else ''} from {Path(path).name} differ from the "
            "flight controller and are now staged as unsaved changes. Review them, then press "
            "Write to Flight Controller.\n\n" + "\n".join(notes))

    def start_fc_job(self, work, label):
        self.fc_busy = True
        self.status_var.set(label + "...")
        threading.Thread(target=work, daemon=True).start()

    def handle_fc_event(self, kind, value):
        if kind == "fc_status":
            st: VehicleStatus = value
            self.fc_status_var.set(st.summary() if st.connected else "Connection lost - no heartbeat")
            self.fc_status_label.configure(fg="#0f7f8f" if st.connected else "#b91c1c")
            heading = st.yaw if st.yaw is not None else st.heading
            self.mission_map.set_aircraft(st.lat, st.lon, heading)
            self.flight_tab.map.set_aircraft(st.lat, st.lon, heading)
            if st.lat is not None and st.armed:
                self.flight_tab.map.add_trail_point(st.lat, st.lon)
        elif kind == "fc_connected":
            self.fc_link = value
            self.connect_button.configure(text="Disconnect", state="normal")
            self.fc_status_var.set(self.fc_link.status.summary())
            self.fc_status_label.configure(fg="#0f7f8f")
            self.status_var.set(f"Connected to {value.device}")
            self.after(1500, lambda: self.load_params(quiet=True))
        elif kind == "fc_connect_failed":
            self.connect_button.configure(text="Connect", state="normal")
            self.fc_status_var.set("Not connected")
            messagebox.showerror(APP_TITLE, f"Could not connect:\n{value}")
        elif kind == "fc_progress":
            self.status_var.set(value)
        elif kind == "fc_done":
            self.fc_busy = False
            level, text = value
            self.status_var.set(text.splitlines()[0])
            (messagebox.showerror if level == "error" else messagebox.showinfo)(APP_TITLE, text)
        elif kind == "fc_params_loaded":
            self.fc_busy = False
            params = value
            self.param_store.set_params(params, time.strftime("%H:%M"))
            self.refresh_map()  # loiter circles use the FC's WP_LOITER_RAD
            self.update_loiter_box()
            arspd = params.get("ARSPD_TYPE")
            estimated = arspd is None or int(arspd.value) == 0
            self.flight_tab.pfd.airspeed_estimated = estimated
            if estimated:
                self.flight_tab.estimate_note.pack(anchor="w", pady=(4, 8), after=self.flight_tab.pfd)
            else:
                self.flight_tab.estimate_note.pack_forget()
            self.status_var.set(f"Loaded {len(params)} parameters")
        elif kind == "fc_params_failed":
            self.fc_busy = False
            quiet, text = value
            self.status_var.set(text)
            if not quiet:
                messagebox.showerror(APP_TITLE, text)
        elif kind == "fc_params_written":
            self.fc_busy = False
            self.finish_param_write(value)
        elif kind == "fc_downloaded":
            self.fc_busy = False
            mission, notes = items_to_mission(value, name="Mission from FC")
            self.current_file = None
            self.mission = mission
            self.selected_waypoint_id = None
            self.name_var.set(mission.name)
            self.home_auto = False
            self.load_home_editor()
            self.mission_map.reset_fit()
            self.refresh_all(f"Downloaded {len(mission.waypoints)} waypoints from the flight controller")
            if notes:
                messagebox.showwarning(APP_TITLE, "Some items could not be shown in the editor:\n\n" + "\n".join(f"- {n}" for n in notes))

    def follow_auto_home(self):
        """Until the user sets home, it sits on the first waypoint (and goes away with it)."""
        if not self.home_auto:
            return
        first = self.mission.waypoints[0] if self.mission.waypoints else None
        new = (first.lat, first.lon) if first else (None, None)
        if (self.mission.home.lat, self.mission.home.lon) != new:
            self.mission.home.lat, self.mission.home.lon = new
            self.load_home_editor()

    def refresh_all(self, status: str | None = None):
        self.follow_auto_home()
        self.refresh_table()
        self.load_waypoint_editor()
        self.refresh_map()
        self.refresh_summary()
        if status:
            self.status_var.set(status)

    @staticmethod
    def action_text(waypoint) -> str:
        if waypoint.action != "loiter":
            return waypoint.action
        lo = waypoint.loiter
        detail = {"time": f"{lo.seconds} s", "turns": f"{lo.turns} laps", "forever": "forever"}.get(lo.mode, lo.mode)
        return f"loiter {detail}"

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
                        self.fmt_alt_input(waypoint.altitude_m),
                        self.fmt_speed_input(waypoint.speed_mps),
                        self.action_text(waypoint),
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
            home_text = f"{home.lat:.6f}, {home.lon:.6f}, {self.units.fmt_alt(home.altitude_m)}"
        self.summary_var.set(
            f"Mission: {self.mission.name}\n"
            f"Waypoints: {len(self.mission.waypoints)}\n"
            f"Home: {home_text}\n"
            f"Default altitude: {self.units.fmt_alt(self.mission.defaults.altitude_m)}\n"
            f"Default speed: {self.units.fmt_speed(self.mission.defaults.speed_mps)}\n\n"
            f"{distance_note}"
        )

    def refresh_map(self):
        radius = self.default_loiter_radius()[0]
        self.mission_map.render(self.mission, self.selected_waypoint_id, radius)
        if hasattr(self, "flight_tab"):
            self.flight_tab.map.render(self.mission, None, radius)

    def process_ui_events(self):
        latest_status = None
        while True:
            try:
                kind, value = self.ui_events.get_nowait()
            except queue.Empty:
                break
            if kind == "fc_status":
                latest_status = value  # telemetry arrives many times a second; draw the newest once
            elif kind.startswith("fc_"):
                self.handle_fc_event(kind, value)
        if latest_status is not None:
            self.handle_fc_event("fc_status", latest_status)
        self.update_flight_tab()
        self.after(100, self.process_ui_events)

    def update_flight_tab(self):
        if self.notebook.select() != str(self.flight_tab):
            return
        st = self.fc_link.status if self.fc_link else None
        home = (st.home_lat, st.home_lon) if st is not None and st.home_lat is not None else \
            (self.mission.home.lat, self.mission.home.lon)
        self.flight_tab.update_view(st, self.target_text(st), home)

    def target_text(self, st) -> str:
        """Which waypoint the aircraft is flying to. Mission item numbers are mapped to the
        editor's waypoint numbers when the editor holds the same mission as the FC."""
        if st is None or st.wp_seq is None:
            return "—"
        key = repr(mission_to_dict(self.mission))
        if self._target_cache[0] != key:
            items = mission_to_items(self.mission).items
            numbers = {wp.id: n for n, wp in enumerate(self.mission.waypoints, start=1)}
            self._target_cache = (key, {seq: numbers.get(it.source_wp) for seq, it in enumerate(items)
                                        if it.command in NAV_COMMANDS and it.source_wp is not None})
        number = self._target_cache[1].get(st.wp_seq)
        where = f"WP {number}" if number else f"item {st.wp_seq}"
        if st.wp_dist is not None and st.mode in ("AUTO", "GUIDED", "RTL", "LOITER"):
            return f"{where} · {self.units.fmt_distance(st.wp_dist)}"
        return where

    @staticmethod
    def optional_int(value: str) -> int | None:
        value = value.strip()
        return None if value == "" else int(value)

    @staticmethod
    def optional_float(value: str) -> float | None:
        value = value.strip()
        return None if value == "" else float(value)



def self_test() -> int:
    """Used by the release build: open the app, check every bundled piece loads, close.
    Catches modules or data files that PyInstaller left out."""
    problems = []
    app = FlightControlApp()
    app.update()
    try:
        from pymavlink import mavutil
        mavutil.mavlink.MAVLink_heartbeat_message  # the MAVLink 2 ardupilotmega dialect
        if mavutil.mavlink.WIRE_PROTOCOL_VERSION != "2.0":
            problems.append("MAVLink 2 dialect not loaded")
    except Exception as exc:
        problems.append(f"pymavlink: {exc}")
    if app.mission_map.map is None:
        problems.append("tkintermapview missing (no map)")
    if len(app.param_store.meta) < 1000:
        problems.append("parameter metadata missing")
    if app.configurator is None:
        problems.append(f"RC Configurator missing: {RC_CONFIGURATOR_ERROR}")
    if sys.platform == "darwin" and not app.mission_map.pinch_enabled:
        problems.append("macOS pinch helper (native/libascend_pinch.dylib) missing")
    tabs = [app.notebook.tab(t, "text") for t in app.notebook.tabs()]
    app.on_close()
    lines = [f"{APP_TITLE} {APP_VERSION} self-test; tabs: {', '.join(tabs)}"]
    lines += [f"FAIL: {problem}" for problem in problems]
    lines.append("PASS" if not problems else "FAILED")
    print("\n".join(lines))
    log = os.environ.get("ASCEND_SELFTEST_LOG")  # a windowed Windows .exe has no console
    if log:
        Path(log).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 1 if problems else 0


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        sys.exit(self_test())
    app = FlightControlApp()
    if "--connect" in sys.argv:  # e.g. --connect tcp:127.0.0.1:5760 for SITL
        app.conn_var.set(sys.argv[sys.argv.index("--connect") + 1])
        app.after(300, app.toggle_connection)
    app.mainloop()
