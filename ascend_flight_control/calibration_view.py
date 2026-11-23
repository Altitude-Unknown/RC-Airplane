#!/usr/bin/env python3
"""
Calibration tab for ASCEND Flight Control: accelerometer (IMU) and gyroscope,
level, compass and radio, one clear step at a time.

The protocol logic is in calibration.py. This file is only the screens. Every
calibration needs a connected, disarmed flight controller, and only one runs
at a time.
"""

from __future__ import annotations

import math
import queue
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk

from calibration import (
    CMD_CAL,
    POSE_BACK,
    POSE_LEFT,
    POSE_LEVEL,
    POSE_NOSEDOWN,
    POSE_NOSEUP,
    POSE_RIGHT,
    POSE_TEXT,
    RADIO_CHANNELS,
    AccelCal,
    CompassCal,
    RadioCal,
    mavlink,
    result_text,
)
from param_protocol import read_param, write_changes
from params_view import ACCENT, BG, CHANGED, ERROR, LINE, MUTED, PANEL, TEXT, ScrollFrame

OK_GREEN = "#1f8a4c"
SECTIONS = [
    ("accel", "Accelerometer"),
    ("level", "Level"),
    ("compass", "Compass"),
    ("radio", "Radio"),
]
FONT = "TkDefaultFont"


def draw_plane(canvas: tk.Canvas, pose: int, w: int = 260, h: int = 170):
    """Simple picture of the plane in an accelerometer-calibration pose."""
    canvas.delete("all")
    cx, cy = w / 2, h / 2 - 6
    canvas.create_line(20, h - 18, w - 20, h - 18, fill="#94a3b8", width=2)  # the table / ground
    side_view = pose in (POSE_NOSEDOWN, POSE_NOSEUP)
    if side_view:
        angle = {POSE_NOSEDOWN: 90, POSE_NOSEUP: -90}[pose]
        caption = "Seen from the side"
        # fuselage pointing right (nose), tail fin at the left
        shapes = [
            ("poly", [(-70, -7), (55, -7), (72, 0), (55, 7), (-70, 7)], "#0f7f8f"),
            ("poly", [(-70, -7), (-58, -7), (-66, -32), (-74, -32)], "#0a5f6b"),  # fin
            ("poly", [(-8, -3), (22, -3), (22, 3), (-8, 3)], "#0a5f6b"),  # wing (edge on)
            ("text", (82, 0), "nose"),
        ]
    else:
        angle = {POSE_LEVEL: 0, POSE_LEFT: -90, POSE_RIGHT: 90, POSE_BACK: 180}[pose]
        caption = "Seen from behind, the way the pilot looks at it"
        shapes = [
            ("poly", [(-95, -4), (95, -4), (95, 4), (-95, 4)], "#0f7f8f"),  # wing
            ("oval", (-13, -13, 13, 13), "#0a5f6b"),  # fuselage
            ("poly", [(-3, -13), (3, -13), (3, -42), (-3, -42)], "#0a5f6b"),  # fin
            ("oval", (-26, 20, -16, 30), "#334155"), ("oval", (16, 20, 26, 30), "#334155"),  # wheels
            ("poly", [(-22, 13), (-20, 13), (-20, 21), (-22, 21)], "#334155"),
            ("poly", [(20, 13), (22, 13), (22, 21), (20, 21)], "#334155"),
            ("text", (-80, -16), "L"), ("text", (80, -16), "R"),
        ]
    a = math.radians(angle)
    ca, sa = math.cos(a), math.sin(a)

    def tr(x, y):
        return cx + x * ca - y * sa, cy + x * sa + y * ca

    for kind, data, *rest in shapes:
        if kind == "poly":
            canvas.create_polygon([v for p in data for v in tr(*p)], fill=rest[0], outline="")
        elif kind == "oval":
            x0, y0, x1, y1 = data
            mx, my = tr((x0 + x1) / 2, (y0 + y1) / 2)
            r = (x1 - x0) / 2
            canvas.create_oval(mx - r, my - r, mx + r, my + r, fill=rest[0], outline="")
        else:
            x, y = tr(*data)
            canvas.create_text(x, y, text=rest[0], fill=TEXT, font=(FONT, 11, "bold"))
    canvas.create_text(w / 2, h - 6, text=caption, fill=MUTED, font=(FONT, 10))


class CalibrationTab(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, bg=BG)
        self.app = app
        self.section = "accel"
        self.status: dict[str, str] = {}  # section -> "ok" / "failed"
        self.events: queue.Queue = queue.Queue()
        self.calls: queue.Queue = queue.Queue()  # results from worker threads, run on the UI thread
        self.listening_link = None
        self.active = None  # the running calibration object
        self.active_kind = None
        self.accel_pose = None
        self.compass_progress: dict[int, int] = {}
        self.compass_results: list = []
        self.radio: RadioCal | None = None
        self.radio_plan = None
        self.result_lines: dict[str, list[tuple[str, str]]] = {}  # section -> [(text, color)]
        self.busy_label = ""

        header = tk.Frame(self, bg=BG)
        header.pack(fill="x", padx=16, pady=(14, 10))
        tk.Label(header, text="Calibration", bg=BG, fg=TEXT, font=(FONT, 20, "bold")).pack(anchor="w")
        tk.Label(header, text="Do these in order on a new or rebuilt plane: accelerometer, level, compass, then radio. "
                              "The plane must be connected and disarmed.",
                 bg=BG, fg=MUTED, font=(FONT, 12)).pack(anchor="w")

        main = tk.Frame(self, bg=BG)
        main.pack(fill="both", expand=True, padx=16, pady=(0, 16))
        nav_box = tk.Frame(main, bg=PANEL, highlightbackground=LINE, highlightthickness=1)
        nav_box.pack(side="left", fill="y")
        self.nav = tk.Listbox(nav_box, activestyle="none", exportselection=False, width=22, borderwidth=0,
                              highlightthickness=0, bg=PANEL, fg=TEXT, font=(FONT, 14),
                              selectbackground=ACCENT, selectforeground="#ffffff")
        self.nav.pack(fill="y", expand=True, padx=6, pady=6)
        self.nav.bind("<<ListboxSelect>>", self.on_nav)
        self.content = ScrollFrame(main)
        self.content.pack(side="left", fill="both", expand=True, padx=(12, 0))
        self.refresh_nav()
        self.render()
        self.after(50, self.poll)

    # -- navigation ----------------------------------------------------------------

    def refresh_nav(self):
        self.nav.delete(0, "end")
        for n, (key, title) in enumerate(SECTIONS, start=1):
            mark = {"ok": "   ✓", "failed": "   ✗"}.get(self.status.get(key), "")
            self.nav.insert("end", f"  {n}. {title}{mark}")
        self.nav.selection_set([k for k, _ in SECTIONS].index(self.section))

    def on_nav(self, _event=None):
        sel = self.nav.curselection()
        if not sel:
            return
        key = SECTIONS[sel[0]][0]
        if key == self.section:
            return
        if self.active is not None:
            messagebox.showinfo("Calibration", "Finish or stop the calibration that is running first.")
            self.refresh_nav()
            return
        self.section = key
        self.render()
        self.content.to_top()

    # -- connection helpers ----------------------------------------------------------

    def ready(self) -> bool:
        link = self.app.fc_link
        if link is None or not link.status.connected:
            messagebox.showwarning("Calibration", "Connect to the flight controller first.")
            return False
        if link.status.armed:
            messagebox.showwarning("Calibration", "The aircraft is armed. Disarm it before calibrating.")
            return False
        if self.app.fc_busy:
            messagebox.showinfo("Calibration", "A flight controller transfer is running. Try again when it finishes.")
            return False
        return True

    def begin(self, kind, obj, label):
        link = self.app.fc_link
        self.active, self.active_kind = obj, kind
        self.app.fc_busy = True
        self.busy_label = label
        self.listening_link = link
        link.add_listener(self.events.put)
        self.app.status_var.set(label)

    def end(self, status: str | None = None):
        if self.listening_link is not None:
            self.listening_link.remove_listener(self.events.put)
        self.listening_link = None
        self.active = self.active_kind = None
        self.app.fc_busy = False
        if status:
            self.status[self.section] = status
        self.refresh_nav()
        self.render()

    def poll(self):
        try:
            while True:
                msg = self.events.get_nowait()
                self.dispatch(msg)
        except queue.Empty:
            pass
        try:
            while True:
                self.calls.get_nowait()()
        except queue.Empty:
            pass
        if self.active_kind == "radio":
            self.update_radio_bars()
        link = self.app.fc_link
        if self.active is not None and (link is None or link is not self.listening_link
                                        or not link.status.connected):
            self.result_lines[self.section] = [("The connection to the flight controller was lost.", ERROR)]
            self.end("failed")
        self.after(50, self.poll)

    def dispatch(self, msg):
        if self.active_kind == "accel":
            for kind, value in self.active.on_message(msg):
                if kind == "pose":
                    self.accel_pose = value
                    self.render()
                elif kind == "done":
                    if value:
                        self.result_lines["accel"] = [
                            ("Accelerometers calibrated.", OK_GREEN),
                            ("Restart the flight controller to start using the new calibration, then do Level.", TEXT)]
                    else:
                        self.result_lines["accel"] = [
                            ("Calibration failed.", ERROR),
                            ("The plane may have moved, or a position was wrong. Try again and hold it still "
                             "in each position until the next one appears.", TEXT)]
                    self.accel_pose = None
                    self.end("ok" if value else "failed")
                elif kind == "rejected":
                    self.result_lines["accel"] = [(f"The flight controller did not start: {value}.", ERROR)]
                    self.accel_pose = None
                    self.end("failed")
        elif self.active_kind == "compass":
            for kind, value in self.active.on_message(msg):
                if kind == "progress":
                    self.compass_progress = value
                    self.update_compass_progress()
                elif kind == "result":
                    self.compass_results.append(value)
                    self.update_compass_progress()
                    if self.active.finished:
                        self.finish_compass()
                elif kind == "rejected":
                    self.result_lines["compass"] = [(f"The flight controller did not start: {value}.", ERROR)]
                    self.end("failed")
        elif self.active_kind == "radio":
            self.active.on_message(msg)
        elif self.active_kind == "command":
            if msg.get_type() == "COMMAND_ACK" and msg.command == self.active["command"]:
                self.active["on_ack"](msg.result)

    # -- page building ------------------------------------------------------------------

    def render(self):
        body = self.content.body
        for child in body.winfo_children():
            child.destroy()
        getattr(self, f"page_{self.section}")(body)

    def card(self, body, title, intro):
        tk.Label(body, text=title, bg=BG, fg=TEXT, font=(FONT, 17, "bold")).pack(anchor="w", pady=(2, 2))
        tk.Label(body, text=intro, bg=BG, fg=MUTED, font=(FONT, 13), justify="left",
                 wraplength=680).pack(anchor="w", pady=(0, 12))
        card = tk.Frame(body, bg=PANEL, highlightbackground=LINE, highlightthickness=1, padx=18, pady=16)
        card.pack(fill="x")
        return card

    def steps(self, parent, lines):
        for n, line in enumerate(lines, start=1):
            row = tk.Frame(parent, bg=PANEL)
            row.pack(fill="x", pady=2)
            tk.Label(row, text=f"{n}.", bg=PANEL, fg=ACCENT, font=(FONT, 13, "bold"), width=2,
                     anchor="ne").pack(side="left", anchor="n")
            tk.Label(row, text=line, bg=PANEL, fg=TEXT, font=(FONT, 13), justify="left",
                     wraplength=600).pack(side="left", anchor="w", padx=(4, 0))

    def show_results(self, parent, key):
        for text, color in self.result_lines.get(key, []):
            tk.Label(parent, text=text, bg=PANEL, fg=color, font=(FONT, 13, "bold" if color != TEXT else "normal"),
                     justify="left", wraplength=640).pack(anchor="w", pady=(6, 0))

    def button_row(self, parent):
        row = tk.Frame(parent, bg=PANEL)
        row.pack(fill="x", pady=(14, 0))
        return row

    def reboot_button(self, row):
        ttk.Button(row, text="Restart Flight Controller", command=self.reboot).pack(side="left", padx=(8, 0))

    def reboot(self):
        link = self.app.fc_link
        if link is None or link.status.armed:
            return
        if messagebox.askyesno("Restart", "Restart the flight controller now? It reconnects on its own in a few "
                                          "seconds over USB; keep the plane still while it starts."):
            link.reboot()
            self.app.status_var.set("Flight controller restarting…")

    # -- accelerometer + gyro --------------------------------------------------------------

    def page_accel(self, body):
        card = self.card(body, "Accelerometer (IMU)",
                         "Teaches the flight controller which way is down. You will hold the plane in six "
                         "positions; the flight controller measures each one.")
        if self.active_kind == "accel":
            if self.accel_pose is None:
                tk.Label(card, text="Starting… keep the plane still.", bg=PANEL, fg=TEXT,
                         font=(FONT, 14, "bold")).pack(anchor="w")
                return
            title, text = POSE_TEXT[self.accel_pose]
            done = len(self.active.confirmed - {self.accel_pose})
            tk.Label(card, text=f"Position {done + 1} of 6: {title}", bg=PANEL, fg=ACCENT,
                     font=(FONT, 16, "bold")).pack(anchor="w")
            row = tk.Frame(card, bg=PANEL)
            row.pack(fill="x", pady=(8, 0))
            pic = tk.Canvas(row, width=260, height=170, bg="#f8fafc", highlightthickness=1,
                            highlightbackground=LINE)
            pic.pack(side="left")
            draw_plane(pic, self.accel_pose)
            info = tk.Frame(row, bg=PANEL)
            info.pack(side="left", fill="both", expand=True, padx=(16, 0))
            tk.Label(info, text=text, bg=PANEL, fg=TEXT, font=(FONT, 14), justify="left",
                     wraplength=360).pack(anchor="w")
            waiting = self.accel_pose in self.active.confirmed
            tk.Label(info, text="Measuring… hold it still until the next position appears." if waiting else
                     "Hold it steady, then click the button.", bg=PANEL, fg=CHANGED if waiting else MUTED,
                     font=(FONT, 12), justify="left", wraplength=360).pack(anchor="w", pady=(10, 0))
            buttons = self.button_row(card)
            ttk.Button(buttons, text="The plane is in position", style="Accent.TButton",
                       command=self.accel_confirm, state="disabled" if waiting else "normal").pack(side="left")
            ttk.Button(buttons, text="Stop", command=self.accel_stop).pack(side="left", padx=(8, 0))
            return
        self.steps(card, ["Set the plane on a flat table. You will need room to turn it in every direction.",
                          "Click Start. The picture shows each position; hold the plane there and click "
                          "“The plane is in position”.",
                          "Hold it still until the next position appears. Each one takes a few seconds."])
        self.show_results(card, "accel")
        buttons = self.button_row(card)
        ttk.Button(buttons, text="Start Accelerometer Calibration", style="Accent.TButton",
                   command=self.accel_start).pack(side="left")
        if self.status.get("accel") == "ok":
            self.reboot_button(buttons)

        gyro = tk.Frame(body, bg=PANEL, highlightbackground=LINE, highlightthickness=1, padx=18, pady=14)
        gyro.pack(fill="x", pady=(12, 0))
        tk.Label(gyro, text="Gyroscopes", bg=PANEL, fg=TEXT, font=(FONT, 14, "bold")).pack(anchor="w")
        tk.Label(gyro, text="The gyroscopes calibrate themselves every time the flight controller starts, so keep "
                            "the plane still while it powers up. To recalibrate them now, set the plane down, "
                            "keep it completely still, and click below.",
                 bg=PANEL, fg=MUTED, font=(FONT, 12), justify="left", wraplength=640).pack(anchor="w", pady=(2, 0))
        self.show_results(gyro, "gyro")
        row = self.button_row(gyro)
        ttk.Button(row, text="Calibrate Gyroscopes", command=self.gyro_start).pack(side="left")

    def accel_start(self):
        if not self.ready():
            return
        cal = AccelCal(self.app.fc_link)
        self.result_lines["accel"] = []
        self.accel_pose = None
        self.begin("accel", cal, "Accelerometer calibration running")
        cal.start()
        self.render()

    def accel_confirm(self):
        if self.active_kind == "accel":
            self.active.confirm_pose()
            self.render()

    def accel_stop(self):
        self.result_lines["accel"] = [("Stopped. Nothing was saved; the flight controller gives up on its own "
                                       "after a short wait.", MUTED)]
        self.accel_pose = None
        self.end()

    def gyro_start(self):
        self.run_command("gyro", "Gyroscope calibration running", (1, 0, 0, 0, 0),
                         ok=[("Gyroscopes calibrated.", OK_GREEN)], timeout=30)

    # -- single-command calibrations (gyro, level) -------------------------------------------

    def run_command(self, key, label, params, ok, timeout=20, after_ok=None):
        if not self.ready():
            return
        state = {"command": CMD_CAL, "retries": 5}

        def on_ack(result):
            if result == mavlink.MAV_RESULT_IN_PROGRESS:
                return
            if result == mavlink.MAV_RESULT_TEMPORARILY_REJECTED and state["retries"] > 0:
                # ArduPilot refuses while it is starting up or within 5 s of another
                # calibration; try again shortly instead of failing straight away.
                state["retries"] -= 1
                self.result_lines[key] = [("The flight controller is busy; trying again…", CHANGED)]
                self.render()
                self.after(2000, lambda: self.active is state and self.app.fc_link.command(CMD_CAL, *params))
                return
            if result == mavlink.MAV_RESULT_ACCEPTED:
                self.result_lines[key] = list(ok)
                if after_ok:
                    after_ok()
                    return
                self.end("ok" if key == self.section else None)
            else:
                self.result_lines[key] = [(f"The flight controller said: {result_text(result)}.", ERROR)]
                self.end("failed" if key == self.section else None)

        state["on_ack"] = on_ack
        self.begin("command", state, label)
        self.result_lines[key] = [("Working… keep the plane still.", CHANGED)]
        self.render()
        self.app.fc_link.command(CMD_CAL, *params)

        def check_timeout(started=time.monotonic()):
            if self.active is state:
                if time.monotonic() - started > timeout:
                    self.result_lines[key] = [("No answer from the flight controller.", ERROR)]
                    self.end("failed" if key == self.section else None)
                else:
                    self.after(250, check_timeout)

        self.after(250, check_timeout)

    # -- level ------------------------------------------------------------------------------

    def page_level(self, body):
        card = self.card(body, "Level",
                         "Tells the flight controller what “level flight” looks like, so FBWA and the automatic "
                         "modes fly wings-level without the stick. Do this after the accelerometer calibration.")
        self.steps(card, ["Put the plane on a flat surface in the attitude it flies level at: wings level, and "
                          "the nose at its cruise angle. Prop the tail up if it sits nose-high on its wheels.",
                          "Keep it completely still and click Calibrate Level."])
        trims = self.level_trims()
        if trims:
            tk.Label(card, text=trims, bg=PANEL, fg=MUTED, font=(FONT, 12)).pack(anchor="w", pady=(10, 0))
        self.show_results(card, "level")
        row = self.button_row(card)
        ttk.Button(row, text="Calibrate Level", style="Accent.TButton", command=self.level_start).pack(side="left")

    def level_trims(self) -> str:
        params = self.app.param_store.params
        x, y = params.get("AHRS_TRIM_X"), params.get("AHRS_TRIM_Y")
        if x is None or y is None:
            return ""
        return f"Current level trim: roll {math.degrees(x.value):+.2f}°, pitch {math.degrees(y.value):+.2f}°"

    def level_start(self):
        def read_back():
            link = self.app.fc_link

            def work():
                x, y = read_param(link, "AHRS_TRIM_X"), read_param(link, "AHRS_TRIM_Y")
                self.calls.put(lambda: done(x, y))

            def done(x, y):
                store = self.app.param_store
                for name, value in (("AHRS_TRIM_X", x), ("AHRS_TRIM_Y", y)):
                    if value is not None and name in store.params:
                        store.params[name].value = value
                if x is not None and y is not None:
                    self.result_lines["level"].append(
                        (f"New level trim: roll {math.degrees(x):+.2f}°, pitch {math.degrees(y):+.2f}°", TEXT))
                self.end("ok")

            threading.Thread(target=work, daemon=True).start()

        self.run_command("level", "Level calibration running", (0, 0, 0, 0, 2),
                         ok=[("Level saved.", OK_GREEN)], after_ok=read_back, timeout=30)

    # -- compass ----------------------------------------------------------------------------

    def page_compass(self, body):
        card = self.card(body, "Compass",
                         "Measures the magnetic field around the plane so the heading is right. Metal, magnets "
                         "and electronics nearby spoil it, so do it outdoors.")
        if self.active_kind == "compass":
            tk.Label(card, text="Rotate the plane slowly through every direction", bg=PANEL, fg=ACCENT,
                     font=(FONT, 16, "bold")).pack(anchor="w")
            tk.Label(card, text="Point the nose up, down, and to every side; roll it onto each wingtip and upside "
                                "down; keep turning until the bar is full. Smooth, slow movements work best.",
                     bg=PANEL, fg=TEXT, font=(FONT, 13), justify="left", wraplength=640).pack(anchor="w", pady=(4, 10))
            self.compass_bars = tk.Frame(card, bg=PANEL)
            self.compass_bars.pack(fill="x")
            self.update_compass_progress()
            row = self.button_row(card)
            ttk.Button(row, text="Cancel", command=self.compass_cancel).pack(side="left")
            return
        self.steps(card, ["Take the plane outside, at least a few steps away from cars, metal benches, "
                          "phones and speakers.",
                          "Connect over USB or the telemetry radio and click Start.",
                          "Rotate the plane slowly in every direction until the bar fills. The flight controller "
                          "saves the result itself."])
        self.show_results(card, "compass")
        row = self.button_row(card)
        ttk.Button(row, text="Start Compass Calibration", style="Accent.TButton",
                   command=self.compass_start).pack(side="left")
        if self.status.get("compass") == "ok":
            self.reboot_button(row)

    def update_compass_progress(self):
        bars = getattr(self, "compass_bars", None)
        if bars is None or not bars.winfo_exists():
            return
        for child in bars.winfo_children():
            child.destroy()
        if not self.compass_progress:
            tk.Label(bars, text="Waiting for the flight controller to start…", bg=PANEL, fg=MUTED,
                     font=(FONT, 12)).pack(anchor="w")
            return
        done = {r.compass_id: r for r in self.compass_results}
        for cid, pct in sorted(self.compass_progress.items()):
            row = tk.Frame(bars, bg=PANEL)
            row.pack(fill="x", pady=3)
            tk.Label(row, text=f"Compass {cid + 1}", bg=PANEL, fg=TEXT, font=(FONT, 12), width=10,
                     anchor="w").pack(side="left")
            bar = tk.Canvas(row, width=360, height=18, bg="#e2e8f0", highlightthickness=0)
            bar.pack(side="left")
            result = done.get(cid)
            color = OK_GREEN if result and result.ok else ERROR if result else ACCENT
            bar.create_rectangle(0, 0, 360 * min(pct, 100) / 100, 18, fill=color, outline="")
            label = result.text if result else f"{pct}%"
            tk.Label(row, text=label, bg=PANEL, fg=color, font=(FONT, 12)).pack(side="left", padx=(8, 0))

    def compass_start(self):
        if not self.ready():
            return
        params = self.app.param_store.params
        dev = params.get("COMPASS_DEV_ID")
        if dev is not None and int(dev.value) == 0:
            messagebox.showwarning("Compass", "The flight controller reports no compass (COMPASS_DEV_ID is 0).")
            return
        cal = CompassCal(self.app.fc_link)
        self.compass_progress, self.compass_results = {}, []
        self.result_lines["compass"] = []
        self.begin("compass", cal, "Compass calibration running")
        cal.start()
        self.render()

    def compass_cancel(self):
        if self.active_kind == "compass":
            self.active.cancel()
        self.result_lines["compass"] = [("Canceled. The old compass calibration is still in use.", MUTED)]
        self.end()

    def finish_compass(self):
        lines = []
        all_ok = all(r.ok for r in self.compass_results)
        for r in sorted(self.compass_results, key=lambda r: r.compass_id):
            name = f"Compass {r.compass_id + 1}"
            if r.ok:
                saved = "saved" if r.autosaved else "not saved"
                lines.append((f"{name}: calibrated and {saved} (fitness {r.fitness:.1f}; lower is better).", OK_GREEN))
                if r.new_orientation != r.old_orientation:
                    lines.append((f"{name}: mounting orientation corrected from {r.old_orientation} to "
                                  f"{r.new_orientation} (COMPASS_ORIENT).", TEXT))
            else:
                lines.append((f"{name}: {r.text}.", ERROR))
        if all_ok:
            lines.append(("Restart the flight controller to start using the new calibration.", TEXT))
        self.result_lines["compass"] = lines
        self.end("ok" if all_ok else "failed")

    # -- radio ------------------------------------------------------------------------------

    def radio_roles(self) -> tuple[dict[int, str], int]:
        params = self.app.param_store.params

        def ch(name, default):
            p = params.get(name)
            return int(p.value) if p is not None else default

        roles = {ch("RCMAP_ROLL", 1): "Aileron (roll)", ch("RCMAP_PITCH", 2): "Elevator (pitch)",
                 ch("RCMAP_THROTTLE", 3): "Throttle", ch("RCMAP_YAW", 4): "Rudder (yaw)"}
        roles.setdefault(5, "Mode switch")
        roles.setdefault(6, "CH6 switch")
        return roles, ch("RCMAP_THROTTLE", 3)

    def page_radio(self, body):
        card = self.card(body, "Radio",
                         "Records how far each stick and switch on your transmitter moves, so full stick means "
                         "full control. CH1 to CH6 are calibrated.")
        roles, _thr = self.radio_roles()
        if self.active_kind == "radio":
            tk.Label(card, text="Move every stick and switch to both ends, a few times", bg=PANEL, fg=ACCENT,
                     font=(FONT, 16, "bold")).pack(anchor="w")
            tk.Label(card, text="Then center the sticks, put the throttle all the way down, and click Finish. "
                                "Do not press the Bind button.", bg=PANEL, fg=TEXT, font=(FONT, 13),
                     justify="left", wraplength=640).pack(anchor="w", pady=(4, 10))
            self.radio_widgets = {}
            for ch in range(1, RADIO_CHANNELS + 1):
                row = tk.Frame(card, bg=PANEL)
                row.pack(fill="x", pady=3)
                tk.Label(row, text=f"CH{ch}  {roles.get(ch, '')}", bg=PANEL, fg=TEXT, font=(FONT, 12), width=20,
                         anchor="w").pack(side="left")
                bar = tk.Canvas(row, width=380, height=22, bg="#e2e8f0", highlightthickness=0)
                bar.pack(side="left")
                value = tk.Label(row, text="—", bg=PANEL, fg=MUTED, font=("TkFixedFont", 11), width=16, anchor="w")
                value.pack(side="left", padx=(8, 0))
                self.radio_widgets[ch] = (bar, value)
            self.radio_signal = tk.Label(card, text="", bg=PANEL, fg=ERROR, font=(FONT, 12))
            self.radio_signal.pack(anchor="w", pady=(6, 0))
            row = self.button_row(card)
            ttk.Button(row, text="Finish", style="Accent.TButton", command=self.radio_finish).pack(side="left")
            ttk.Button(row, text="Cancel", command=self.radio_cancel).pack(side="left", padx=(8, 0))
            self.update_radio_bars()
            return
        if self.radio_plan is not None:
            self.radio_review(card, self.radio_plan)
            return
        self.steps(card, ["Remove the propeller. Turn on the transmitter and make sure the receiver is bound and "
                          "powered.",
                          "Click Start, then move every stick and switch to both ends of its travel.",
                          "Center the sticks with the throttle all the way down and click Finish. Review the "
                          "ranges, then write them to the flight controller."])
        tk.Label(card, text="Stick centers are not changed here. On ASCEND planes they are saved with the "
                            "transmitter's Bind button in MANUAL, which updates the servo trims at the same time. "
                            "CH7 is that Bind button and is left alone.",
                 bg=PANEL, fg=MUTED, font=(FONT, 12), justify="left", wraplength=640).pack(anchor="w", pady=(10, 0))
        self.show_results(card, "radio")
        row = self.button_row(card)
        ttk.Button(row, text="Start Radio Calibration", style="Accent.TButton", command=self.radio_start).pack(side="left")

    def update_radio_bars(self):
        if self.radio is None or not getattr(self, "radio_widgets", None):
            return
        lo_pwm, hi_pwm, width = 800, 2200, 380
        x = lambda pwm: (min(max(pwm, lo_pwm), hi_pwm) - lo_pwm) / (hi_pwm - lo_pwm) * width
        for ch, (bar, value) in self.radio_widgets.items():
            if not bar.winfo_exists():
                return
            rng = self.radio.ranges[ch]
            bar.delete("all")
            for pwm in (1000, 1500, 2000):
                bar.create_line(x(pwm), 0, x(pwm), 22, fill="#cbd5e1")
            if rng.seen:
                bar.create_rectangle(x(rng.lo), 3, x(rng.hi), 19, fill="#99d5dd", outline="")
                bar.create_rectangle(x(rng.now) - 2, 0, x(rng.now) + 2, 22, fill=ACCENT, outline="")
                value.configure(text=f"{rng.now:4d}  ({rng.lo}–{rng.hi})", fg=TEXT)
        stale = time.monotonic() - self.radio.last_rc_time > 1.5
        self.radio_signal.configure(text="No radio data from the flight controller. Is the transmitter on and "
                                         "the receiver bound?" if stale else "")

    def radio_start(self):
        if not self.ready():
            return
        if not self.app.param_store.loaded:
            messagebox.showinfo("Radio", "The flight controller's settings are still loading. Try again in a moment.")
            return
        self.radio = RadioCal(self.app.fc_link)
        self.radio_plan = None
        self.result_lines["radio"] = []
        self.begin("radio", self.radio, "Radio calibration running")
        self.radio.start()
        self.render()

    def radio_cancel(self):
        if self.radio is not None:
            self.radio.stop()
        self.radio = None
        self.result_lines["radio"] = [("Canceled. Nothing was changed.", MUTED)]
        self.end()

    def radio_finish(self):
        roles, throttle = self.radio_roles()
        params = {name: p.value for name, p in self.app.param_store.params.items()}
        self.radio_plan = self.radio.plan(params, roles, throttle)
        self.radio.stop()
        self.end()

    def radio_review(self, card, plan):
        tk.Label(card, text="Review the new ranges", bg=PANEL, fg=ACCENT, font=(FONT, 16, "bold")).pack(anchor="w")
        table = tk.Frame(card, bg=PANEL)
        table.pack(fill="x", pady=(8, 4))
        for col, head in enumerate(("Channel", "Control", "Before (µs)", "New (µs)")):
            tk.Label(table, text=head, bg=PANEL, fg=MUTED, font=(FONT, 12, "bold")).grid(row=0, column=col,
                                                                                       sticky="w", padx=(0, 18))
        for r, (ch, role, old, new) in enumerate(plan.rows, start=1):
            color = TEXT if new[0].isdigit() else CHANGED
            for col, text in enumerate((f"CH{ch}", role, old, new)):
                tk.Label(table, text=text, bg=PANEL, fg=color, font=(FONT, 12)).grid(row=r, column=col, sticky="w",
                                                                                   padx=(0, 18))
        for warning in plan.warnings:
            tk.Label(card, text="⚠  " + warning, bg=PANEL, fg=CHANGED, font=(FONT, 12), justify="left",
                     wraplength=640).pack(anchor="w", pady=(4, 0))
        row = self.button_row(card)
        if plan.changes:
            ttk.Button(row, text=f"Write {len(plan.changes)} Settings to Flight Controller", style="Accent.TButton",
                       command=self.radio_write).pack(side="left")
        else:
            tk.Label(row, text="Nothing to change.", bg=PANEL, fg=MUTED, font=(FONT, 12)).pack(side="left")
        ttk.Button(row, text="Discard", command=self.radio_discard).pack(side="left", padx=(8, 0))
        ttk.Button(row, text="Start Again", command=self.radio_start).pack(side="left", padx=(8, 0))

    def radio_discard(self):
        self.radio_plan = None
        self.result_lines["radio"] = [("Discarded. Nothing was changed.", MUTED)]
        self.render()

    def radio_write(self):
        if not self.ready():
            return
        plan = self.radio_plan
        link, store = self.app.fc_link, self.app.param_store
        missing = [n for n in plan.changes if n not in store.params]
        if missing:
            messagebox.showerror("Radio", "These settings are not on this flight controller: " + ", ".join(missing))
            return
        self.app.fc_busy = True
        self.app.status_var.set("Writing radio calibration…")

        def work():
            try:
                results = write_changes(link, store.params, dict(plan.changes))
            except Exception as exc:  # connection dropped mid-write
                results = exc
            self.calls.put(lambda: done(results))

        def done(results):
            self.app.fc_busy = False
            if isinstance(results, Exception):
                self.result_lines["radio"] = [(f"Writing failed: {results}", ERROR)]
                self.status["radio"] = "failed"
            else:
                bad = [r for r in results if not r.ok]
                if bad:
                    self.result_lines["radio"] = [("Some settings did not take effect: " +
                                                   ", ".join(f"{r.name} ({r.message})" for r in bad), ERROR)]
                    self.status["radio"] = "failed"
                else:
                    self.result_lines["radio"] = [(f"Radio calibration written and verified ({len(results)} "
                                                   "settings).", OK_GREEN)]
                    self.status["radio"] = "ok"
                store.notify()
            self.radio_plan = None
            self.app.status_var.set("")
            self.refresh_nav()
            self.render()

        threading.Thread(target=work, daemon=True).start()
