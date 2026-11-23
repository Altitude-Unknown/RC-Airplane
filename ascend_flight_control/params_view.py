#!/usr/bin/env python3
"""
Parameter screens for ASCEND Flight Control.

ParamStore   - parameters loaded from the FC plus the staged (unsaved) changes.
SettingsTab  - the curated, plain-English Aircraft Settings.
AllParamsTab - every parameter, searchable, for advanced users.

Neither tab talks to the flight controller. They stage changes in the store,
and the app writes them when the user presses Write to Flight Controller.
"""

from __future__ import annotations

import json
import sys
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Callable

from param_catalog import CATALOG, PROTECTED, Setting
from param_protocol import Param, format_value, values_equal

# Palette shared with the rest of the app.
BG = "#f3f6f8"
PANEL = "#ffffff"
TEXT = "#17212b"
MUTED = "#60707d"
LINE = "#dde3e8"
ACCENT = "#0f7f8f"
ACCENT_DARK = "#0b6672"
CHANGED = "#b45309"
CHANGED_BG = "#fff7ed"
ERROR = "#b91c1c"

UNIT_NAMES = {"ds": "tenths of a second", "cs": "hundredths of a second", "m/s/s": "m/s²", "PWM": "µs"}


def load_metadata() -> tuple[dict, str]:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    path = base / "param_metadata" / "ArduPlane.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}, "missing"
    return data.get("params", {}), data.get("source", "unknown")


def setup_styles(root: tk.Misc) -> None:
    style = ttk.Style(root)
    style.configure("Accent.TButton", background=ACCENT, foreground="#ffffff", bordercolor=ACCENT,
                    focuscolor=ACCENT, padding=(14, 6))
    style.map("Accent.TButton",
              background=[("disabled", "#9fb7bc"), ("pressed", ACCENT_DARK), ("active", ACCENT_DARK)],
              foreground=[("disabled", "#f3f6f8")])
    style.configure("Panel.TCheckbutton", background=PANEL)
    style.configure("Changed.TCheckbutton", background=CHANGED_BG)
    style.configure("TNotebook", background=BG, borderwidth=0)
    style.configure("TNotebook.Tab", padding=(16, 6))


# --------------------------------------------------------------------------
# Store
# --------------------------------------------------------------------------

def unit_conversion(units, meta_unit: str) -> tuple[float, str] | None:
    """(factor, label) to show a meter or m/s parameter in the person's units, else None."""
    if units is None:
        return None
    if meta_unit == "m" and units.alt_label != "m":
        return units.alt(1.0), units.alt_label
    if meta_unit == "m/s" and units.speed_label != "m/s":
        return units.speed(1.0), units.speed_label
    return None


def fmt_number(value: float, converted: bool) -> str:
    if converted:
        return f"{value:.1f}".rstrip("0").rstrip(".") if abs(value) < 100 else f"{value:.0f}"
    return f"{value:g}"


class ParamStore:
    def __init__(self, metadata: dict, units=None):
        self.units = units
        self.meta = metadata
        self.params: dict[str, Param] = {}
        self.pending: dict[str, float] = {}
        self.loaded_at: str = ""
        self._listeners: list[Callable[[], None]] = []

    @property
    def loaded(self) -> bool:
        return bool(self.params)

    def subscribe(self, fn: Callable[[], None]) -> None:
        self._listeners.append(fn)

    def notify(self) -> None:
        for fn in self._listeners:
            fn()

    def set_params(self, params: dict[str, Param], loaded_at: str) -> None:
        self.params = params
        self.pending = {n: v for n, v in self.pending.items() if n in params}
        self.loaded_at = loaded_at
        self.notify()

    def info(self, name: str) -> dict:
        return self.meta.get(name, {})

    def value(self, name: str) -> float:
        return self.pending.get(name, self.params[name].value)

    def is_changed(self, name: str) -> bool:
        return name in self.pending

    def stage(self, name: str, raw: float) -> None:
        param = self.params[name]
        if param.is_int:
            raw = float(int(round(raw)))
        before = self.pending.get(name)
        if values_equal(raw, param.value, param.is_int):
            self.pending.pop(name, None)
        else:
            self.pending[name] = raw
        if self.pending.get(name) != before:
            self.notify()

    def revert(self, name: str) -> None:
        if self.pending.pop(name, None) is not None:
            self.notify()

    def discard(self) -> None:
        if self.pending:
            self.pending.clear()
            self.notify()

    def describe(self, name: str, raw: float) -> str:
        """A value as a person reads it: the option name, or number and unit."""
        param = self.params.get(name)
        is_int = param.is_int if param else False
        values = self.info(name).get("Values")
        if values:
            label = values.get(str(int(round(raw))))
            if label:
                return label
        unit = self.info(name).get("Units", "")
        conversion = unit_conversion(self.units, unit)
        if conversion:
            factor, label = conversion
            return f"{fmt_number(raw * factor, True)} {label}"
        text = format_value(raw, is_int)
        return f"{text} {unit}".strip()


def metadata_range(info: dict) -> tuple[float | None, float | None]:
    rng = info.get("Range")
    if not rng:
        return None, None
    try:
        return float(rng["low"]), float(rng["high"])
    except (KeyError, ValueError):
        return None, None


# --------------------------------------------------------------------------
# Shared widgets
# --------------------------------------------------------------------------

class ScrollFrame(ttk.Frame):
    """A vertically scrolling frame; put widgets in .body."""

    def __init__(self, parent, bg=BG):
        super().__init__(parent)
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0, borderwidth=0)
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.body = tk.Frame(self.canvas, bg=bg)
        self._window = self.canvas.create_window((0, 0), window=self.body, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")
        self.body.bind("<Configure>", lambda _e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(self._window, width=e.width))
        self.canvas.bind("<Enter>", lambda _e: self.canvas.bind_all("<MouseWheel>", self._on_wheel))
        self.canvas.bind("<Leave>", lambda _e: self.canvas.unbind_all("<MouseWheel>"))

    def _on_wheel(self, event):
        if self.canvas.yview() == (0.0, 1.0):
            return
        step = -event.delta if sys.platform == "darwin" else -event.delta // 120
        self.canvas.yview_scroll(step, "units")

    def to_top(self):
        self.canvas.yview_moveto(0)


class ChangesBar(tk.Frame):
    """Bottom bar: unsaved change count, Discard and Write to Flight Controller."""

    def __init__(self, parent, store: ParamStore, on_write: Callable[[], None]):
        super().__init__(parent, bg=PANEL, highlightbackground=LINE, highlightthickness=1)
        self.store = store
        self.label = tk.Label(self, bg=PANEL, fg=MUTED, font=("TkDefaultFont", 13))
        self.label.pack(side="left", padx=14, pady=10)
        self.write_button = ttk.Button(self, text="Write to Flight Controller", style="Accent.TButton", command=on_write)
        self.write_button.pack(side="right", padx=(6, 12), pady=8)
        self.discard_button = ttk.Button(self, text="Discard Changes", command=self.discard)
        self.discard_button.pack(side="right", pady=8)
        store.subscribe(self.refresh)
        self.refresh()

    def discard(self):
        count = len(self.store.pending)
        if count and messagebox.askyesno("Discard changes", f"Discard {count} unsaved change{'s' if count != 1 else ''}?"):
            self.store.discard()

    def refresh(self):
        count = len(self.store.pending)
        if not self.store.loaded:
            self.label.configure(text="Settings are not loaded", fg=MUTED)
        elif count:
            self.label.configure(text=f"●  {count} unsaved change{'s' if count != 1 else ''}", fg=CHANGED)
        else:
            self.label.configure(text="✓  Matches the flight controller", fg=MUTED)
        state = "normal" if count else "disabled"
        self.write_button.configure(state=state)
        self.discard_button.configure(state=state)


class TabHeader(tk.Frame):
    """Title, load status and the Load / Backup / Restore buttons."""

    def __init__(self, parent, title: str, store: ParamStore, actions: dict[str, Callable[[], None]]):
        super().__init__(parent, bg=BG)
        left = tk.Frame(self, bg=BG)
        left.pack(side="left", fill="x", expand=True)
        tk.Label(left, text=title, bg=BG, fg=TEXT, font=("TkDefaultFont", 20, "bold")).pack(anchor="w")
        self.status = tk.Label(left, bg=BG, fg=MUTED, font=("TkDefaultFont", 12))
        self.status.pack(anchor="w")
        ttk.Button(self, text="Restore Backup…", command=actions["restore"]).pack(side="right", padx=(6, 0))
        ttk.Button(self, text="Save Backup…", command=actions["backup"]).pack(side="right", padx=(6, 0))
        ttk.Button(self, text="Load from Flight Controller", command=actions["load"]).pack(side="right")
        self.store = store
        store.subscribe(self.refresh)
        self.refresh()

    def refresh(self):
        if self.store.loaded:
            self.status.configure(text=f"{len(self.store.params):,} parameters loaded from the flight controller at {self.store.loaded_at}")
        else:
            self.status.configure(text="Connect to the flight controller to load its settings.")


# --------------------------------------------------------------------------
# Aircraft Settings (curated)
# --------------------------------------------------------------------------

class SettingsTab(tk.Frame):
    def __init__(self, parent, store: ParamStore, actions: dict[str, Callable[[], None]], units=None):
        super().__init__(parent, bg=BG)
        self.units = units
        self.store = store
        self.actions = actions
        self.group_index = 0
        self.errors: dict[str, str] = {}

        TabHeader(self, "Aircraft Settings", store, actions).pack(fill="x", padx=16, pady=(14, 10))

        main = tk.Frame(self, bg=BG)
        main.pack(fill="both", expand=True, padx=16)

        nav_box = tk.Frame(main, bg=PANEL, highlightbackground=LINE, highlightthickness=1)
        nav_box.pack(side="left", fill="y")
        self.nav = tk.Listbox(
            nav_box, activestyle="none", exportselection=False, width=25, borderwidth=0,
            highlightthickness=0, bg=PANEL, fg=TEXT, font=("TkDefaultFont", 14),
            selectbackground=ACCENT, selectforeground="#ffffff",
        )
        self.nav.pack(fill="y", expand=True, padx=6, pady=6)
        self.nav.bind("<<ListboxSelect>>", self.on_nav)

        self.content = ScrollFrame(main)
        self.content.pack(side="left", fill="both", expand=True, padx=(12, 0))

        ChangesBar(self, store, actions["write"]).pack(fill="x", padx=16, pady=12)

        store.subscribe(self.on_store_change)
        self.refresh_nav()
        self.nav.selection_set(0)
        self.render_group()

    # -- navigation --------------------------------------------------------

    def refresh_nav(self):
        selected = self.group_index
        self.nav.delete(0, "end")
        for group in CATALOG:
            changed = sum(1 for s in group.settings if self.store.is_changed(s.name))
            self.nav.insert("end", f"  {group.title}" + (f"   ● {changed}" if changed else ""))
        self.nav.selection_set(selected)

    def on_nav(self, _event=None):
        sel = self.nav.curselection()
        if not sel or sel[0] == self.group_index:
            return
        self.group_index = sel[0]
        self.render_group()
        self.content.to_top()

    def on_store_change(self):
        self.refresh_nav()
        self.render_group()

    # -- group page ----------------------------------------------------------

    def render_group(self):
        body = self.content.body
        for child in body.winfo_children():
            child.destroy()
        group = CATALOG[self.group_index]

        tk.Label(body, text=group.title, bg=BG, fg=TEXT, font=("TkDefaultFont", 17, "bold")).pack(anchor="w", pady=(2, 2))
        tk.Label(body, text=group.intro, bg=BG, fg=MUTED, font=("TkDefaultFont", 13),
                 justify="left", wraplength=640).pack(anchor="w", pady=(0, 12))

        if not self.store.loaded:
            empty = tk.Frame(body, bg=PANEL, highlightbackground=LINE, highlightthickness=1)
            empty.pack(fill="x")
            tk.Label(empty, text="No settings loaded yet", bg=PANEL, fg=TEXT,
                     font=("TkDefaultFont", 14, "bold")).pack(pady=(28, 4))
            tk.Label(empty, text="Connect to the flight controller at the top of the window. Its settings load automatically.",
                     bg=PANEL, fg=MUTED, font=("TkDefaultFont", 12)).pack(pady=(0, 28))
            return

        card = tk.Frame(body, bg=PANEL, highlightbackground=LINE, highlightthickness=1)
        card.pack(fill="x")
        for i, setting in enumerate(group.settings):
            if i:
                tk.Frame(card, bg=LINE, height=1).pack(fill="x")
            self.render_setting(card, setting)

    def render_setting(self, parent, s: Setting):
        name = s.name
        available = name in self.store.params
        changed = available and self.store.is_changed(name)
        bg = CHANGED_BG if changed else PANEL

        row = tk.Frame(parent, bg=bg)
        row.pack(fill="x")
        if changed:
            tk.Frame(row, bg=CHANGED, width=4).pack(side="left", fill="y")
        inner = tk.Frame(row, bg=bg)
        inner.pack(side="left", fill="x", expand=True, padx=16, pady=12)
        inner.columnconfigure(0, weight=1)

        text = tk.Frame(inner, bg=bg)
        text.grid(row=0, column=0, sticky="nw")
        tk.Label(text, text=s.label, bg=bg, fg=TEXT, font=("TkDefaultFont", 14, "bold")).pack(anchor="w")
        tk.Label(text, text=s.help, bg=bg, fg=MUTED, font=("TkDefaultFont", 12), justify="left",
                 wraplength=420).pack(anchor="w", pady=(2, 0))

        meta_line = name
        if changed:
            meta_line += f"   ·   was {self.shown_text(s, self.store.params[name].value)}"
        tk.Label(text, text=meta_line, bg=bg, fg=CHANGED if changed else "#93a1ad",
                 font=("TkDefaultFont", 11)).pack(anchor="w", pady=(4, 0))

        control = tk.Frame(inner, bg=bg)
        control.grid(row=0, column=1, sticky="ne", padx=(16, 0))

        if not available:
            tk.Label(control, text="Not on this firmware", bg=bg, fg=MUTED, font=("TkDefaultFont", 12)).pack()
            return

        raw = self.store.value(name)
        info = self.store.info(name)
        if s.options is not None or info.get("Values"):
            self.combo_control(control, s, raw, info)
        elif info.get("Bitmask"):
            self.bitmask_control(control, s, raw, info, bg)
        else:
            self.number_control(control, s, raw, info, bg)

        if changed:
            link = tk.Label(control, text="Undo", bg=bg, fg=ACCENT, cursor="hand2", font=("TkDefaultFont", 12, "underline"))
            link.pack(anchor="e", pady=(6, 0))
            link.bind("<Button-1>", lambda _e: self.store.revert(name))

        message, color = "", ERROR
        if name in self.errors:
            message = self.errors[name]
        elif s.caution and int(round(raw)) in s.caution_values:
            message, color = "⚠  " + s.caution, CHANGED
        if message:
            tk.Label(inner, text=message, bg=bg, fg=color, font=("TkDefaultFont", 12), justify="left",
                     wraplength=620).grid(row=1, column=0, columnspan=2, sticky="w", pady=(8, 0))

    # -- controls ------------------------------------------------------------

    def shown_text(self, s: Setting, raw: float) -> str:
        options = s.options or {}
        key = int(round(raw))
        if key in options:
            return options[key].split(" - ")[0]
        if s.scale != 1.0 and s.unit:
            return f"{raw * s.scale:g} {s.unit}".strip()
        return self.store.describe(s.name, raw)

    def display_factor(self, s: Setting, info: dict) -> tuple[float, str, bool]:
        """Raw value -> shown value multiplier, the unit label, and whether units were converted."""
        unit = s.unit or info.get("Units", "")
        conversion = None if s.unit else unit_conversion(self.units, unit)
        if conversion:
            return s.scale * conversion[0], conversion[1], True
        return s.scale, UNIT_NAMES.get(unit, unit), False

    def combo_control(self, parent, s: Setting, raw: float, info: dict):
        if s.options is not None:
            options = dict(s.options)
        else:
            options = {int(k): v for k, v in info["Values"].items()}
        current = int(round(raw))
        if current not in options:
            meta_label = info.get("Values", {}).get(str(current), "custom value")
            options[current] = f"{meta_label} ({current})"
        labels = list(options.values())
        var = tk.StringVar(value=options[current])
        width = max(18, min(42, max(len(label) for label in labels) + 2))
        combo = ttk.Combobox(parent, textvariable=var, values=labels, state="readonly", width=width,
                             font=("TkDefaultFont", 13))
        combo.pack(anchor="e")
        by_label = {v: k for k, v in options.items()}
        combo.bind("<<ComboboxSelected>>", lambda _e: self.store.stage(s.name, float(by_label[var.get()])))

    def bitmask_control(self, parent, s: Setting, raw: float, info: dict, bg: str):
        bits = sorted((int(k), v) for k, v in info["Bitmask"].items())
        current = int(round(raw))
        style = "Changed.TCheckbutton" if bg == CHANGED_BG else "Panel.TCheckbutton"
        variables = []
        for bit, label in bits:
            var = tk.BooleanVar(value=bool(current & (1 << bit)))
            variables.append((bit, var))
            ttk.Checkbutton(parent, text=label, variable=var, style=style,
                            command=lambda: self.store.stage(
                                s.name, float(sum(1 << b for b, v in variables if v.get())))).pack(anchor="w")

    def number_control(self, parent, s: Setting, raw: float, info: dict, bg: str):
        factor, unit, converted = self.display_factor(s, info)
        lo, hi = self.limits(s, info, factor / s.scale)
        param = self.store.params[s.name]
        increment = 1.0 if converted else float(info.get("Increment", 1 if param.is_int else 0.1) or 1) * s.scale
        shown = raw * factor
        if converted or s.scale != 1.0:
            text = fmt_number(shown, converted)
        else:
            text = format_value(raw, param.is_int)
        var = tk.StringVar(value=text)
        line = tk.Frame(parent, bg=bg)
        line.pack(anchor="e")
        commit = lambda: self.commit_number(s, var, lo, hi, factor, unchanged_text=text)
        spin = ttk.Spinbox(line, textvariable=var, width=9, increment=increment, font=("TkDefaultFont", 13),
                           from_=lo if lo is not None else -1e9, to=hi if hi is not None else 1e9, command=commit)
        spin.pack(side="left")
        if unit:
            tk.Label(line, text=unit, bg=bg, fg=MUTED, font=("TkDefaultFont", 12)).pack(side="left", padx=(6, 0))
        if lo is not None and hi is not None:
            tk.Label(parent, text=f"{fmt_number(lo, converted)} to {fmt_number(hi, converted)}", bg=bg,
                     fg="#93a1ad", font=("TkDefaultFont", 11)).pack(anchor="e", pady=(2, 0))
        spin.bind("<Return>", lambda _e: commit())
        spin.bind("<FocusOut>", lambda _e: commit())

    def limits(self, s: Setting, info: dict, unit_factor: float = 1.0) -> tuple[float | None, float | None]:
        """Allowed range in shown units. Catalog min/max are in metric (scaled) units."""
        lo, hi = metadata_range(info)
        if lo is not None:
            lo *= s.scale
        if hi is not None:
            hi *= s.scale
        if s.min is not None:
            lo = s.min
        if s.max is not None:
            hi = s.max
        if lo is not None:
            lo *= unit_factor
        if hi is not None:
            hi *= unit_factor
        return lo, hi

    def commit_number(self, s: Setting, var: tk.StringVar, lo, hi, factor: float | None = None,
                      unchanged_text: str | None = None):
        text = var.get().strip()
        if unchanged_text is not None and text == unchanged_text:
            # Untouched: converting the rounded display back (e.g. 328 ft -> 99.97 m)
            # must not turn into a change nobody made.
            if self.errors.pop(s.name, None):
                self.render_group()
            return
        try:
            shown = float(text)
        except ValueError:
            self.set_error(s.name, f"“{text}” is not a number.")
            return
        if (lo is not None and shown < lo - 1e-6) or (hi is not None and shown > hi + 1e-6):
            converted = factor is not None and abs(factor - s.scale) > 1e-9
            self.set_error(s.name, f"Must be between {fmt_number(lo, converted)} and {fmt_number(hi, converted)}.")
            return
        had_error = self.errors.pop(s.name, None)
        before = self.store.pending.get(s.name)
        self.store.stage(s.name, shown / (factor or s.scale))
        if had_error and self.store.pending.get(s.name) == before:
            self.render_group()  # clear the message even though the value did not change

    def set_error(self, name: str, message: str):
        if self.errors.get(name) != message:
            self.errors[name] = message
            self.render_group()


# --------------------------------------------------------------------------
# All Parameters (advanced)
# --------------------------------------------------------------------------

class AllParamsTab(tk.Frame):
    def __init__(self, parent, store: ParamStore, actions: dict[str, Callable[[], None]]):
        super().__init__(parent, bg=BG)
        self.store = store
        self.selected: str | None = None

        TabHeader(self, "All Parameters", store, actions).pack(fill="x", padx=16, pady=(14, 10))

        filters = tk.Frame(self, bg=BG)
        filters.pack(fill="x", padx=16, pady=(0, 8))
        tk.Label(filters, text="Search", bg=BG, fg=TEXT, font=("TkDefaultFont", 13)).pack(side="left")
        self.search_var = tk.StringVar()
        search = ttk.Entry(filters, textvariable=self.search_var, width=32, font=("TkDefaultFont", 13))
        search.pack(side="left", padx=(8, 12))
        self.search_var.trace_add("write", lambda *_: self.refresh_table())
        self.changed_only = tk.BooleanVar(value=False)
        ttk.Checkbutton(filters, text="Changed only", variable=self.changed_only,
                        command=self.refresh_table).pack(side="left")
        self.count_label = tk.Label(filters, bg=BG, fg=MUTED, font=("TkDefaultFont", 12))
        self.count_label.pack(side="right")

        main = tk.Frame(self, bg=BG)
        main.pack(fill="both", expand=True, padx=16)

        table_box = tk.Frame(main, bg=BG)
        table_box.pack(side="left", fill="both", expand=True)
        columns = ("name", "value", "units", "title")
        self.table = ttk.Treeview(table_box, columns=columns, show="headings", selectmode="browse")
        for col, heading, width, stretch in (("name", "Name", 170, False), ("value", "Value", 110, False),
                                             ("units", "Units", 70, False), ("title", "Description", 300, True)):
            self.table.heading(col, text=heading, anchor="w")
            self.table.column(col, width=width, anchor="w", stretch=stretch)
        self.table.tag_configure("changed", background=CHANGED_BG, foreground=CHANGED)
        yscroll = ttk.Scrollbar(table_box, orient="vertical", command=self.table.yview)
        self.table.configure(yscrollcommand=yscroll.set)
        self.table.pack(side="left", fill="both", expand=True)
        yscroll.pack(side="left", fill="y")
        self.table.bind("<<TreeviewSelect>>", self.on_select)

        self.detail = tk.Frame(main, bg=PANEL, highlightbackground=LINE, highlightthickness=1, width=360)
        self.detail.pack(side="left", fill="y", padx=(12, 0))
        self.detail.pack_propagate(False)

        ChangesBar(self, store, actions["write"]).pack(fill="x", padx=16, pady=12)
        store.subscribe(self.on_store_change)
        self.refresh_table()
        self.render_detail()

    def on_store_change(self):
        self.refresh_table()
        self.render_detail()

    def refresh_table(self):
        query = self.search_var.get().strip().upper()
        changed_only = self.changed_only.get()
        self.table.delete(*self.table.get_children())
        shown = 0
        for name in sorted(self.store.params):
            info = self.store.info(name)
            title = info.get("DisplayName", "")
            if query and query not in name and query not in title.upper():
                continue
            changed = self.store.is_changed(name)
            if changed_only and not changed:
                continue
            raw = self.store.value(name)
            param = self.store.params[name]
            self.table.insert("", "end", iid=name, tags=("changed",) if changed else (),
                              values=(name, format_value(raw, param.is_int), info.get("Units", ""), title))
            shown += 1
        if self.selected and self.table.exists(self.selected):
            self.table.selection_set(self.selected)
            self.table.see(self.selected)
        total = len(self.store.params)
        self.count_label.configure(text=f"Showing {shown:,} of {total:,}" if total else "")

    def on_select(self, _event=None):
        sel = self.table.selection()
        if sel and sel[0] != self.selected:
            self.selected = sel[0]
            self.render_detail()

    def render_detail(self):
        for child in self.detail.winfo_children():
            child.destroy()
        pad = {"padx": 16, "anchor": "w"}
        name = self.selected
        if not name or name not in self.store.params:
            tk.Label(self.detail, text="Select a parameter to see what it does and change it.",
                     bg=PANEL, fg=MUTED, font=("TkDefaultFont", 12), wraplength=320,
                     justify="left").pack(pady=20, **pad)
            return
        info = self.store.info(name)
        param = self.store.params[name]
        raw = self.store.value(name)

        tk.Label(self.detail, text=name, bg=PANEL, fg=TEXT, font=("TkDefaultFont", 15, "bold")).pack(pady=(16, 0), **pad)
        if info.get("DisplayName"):
            tk.Label(self.detail, text=info["DisplayName"], bg=PANEL, fg=MUTED,
                     font=("TkDefaultFont", 12)).pack(**pad)
        if name in PROTECTED:
            tk.Label(self.detail, text="⚠  " + PROTECTED[name], bg=PANEL, fg=CHANGED, font=("TkDefaultFont", 12),
                     wraplength=320, justify="left").pack(pady=(10, 0), **pad)

        desc = info.get("Description", "No description is available for this parameter.")
        text = tk.Text(self.detail, height=9, wrap="word", bg=PANEL, fg=TEXT, relief="flat",
                       font=("TkDefaultFont", 12), highlightthickness=0, borderwidth=0)
        text.insert("1.0", desc)
        text.configure(state="disabled")
        text.pack(fill="x", padx=16, pady=(10, 6))

        facts = []
        lo, hi = metadata_range(info)
        if lo is not None:
            facts.append(f"Range: {lo:g} to {hi:g} {info.get('Units', '')}".strip())
        if info.get("RebootRequired") == "True":
            facts.append("Takes effect after a reboot")
        facts.append(f"Flight controller value: {self.store.describe(name, param.value)}")
        for fact in facts:
            tk.Label(self.detail, text=fact, bg=PANEL, fg=MUTED, font=("TkDefaultFont", 11),
                     wraplength=320, justify="left").pack(**pad)

        editor = tk.Frame(self.detail, bg=PANEL)
        editor.pack(fill="x", padx=16, pady=(12, 0))
        if info.get("ReadOnly") == "True":
            tk.Label(editor, text="Read-only", bg=PANEL, fg=MUTED, font=("TkDefaultFont", 12)).pack(anchor="w")
            return

        values = info.get("Values")
        bitmask = info.get("Bitmask")
        if values:
            options = {int(k): v for k, v in values.items()}
            current = int(round(raw))
            if current not in options:
                options[current] = f"custom value ({current})"
            labels = [f"{k}: {v}" for k, v in sorted(options.items())]
            var = tk.StringVar(value=f"{current}: {options[current]}")
            ttk.Combobox(editor, textvariable=var, values=labels, state="readonly", width=34).pack(anchor="w")
            get_value = lambda: float(var.get().split(":", 1)[0])
        elif bitmask:
            current = int(round(raw))
            box = ScrollFrame(editor, bg=PANEL)
            box.configure(height=160)
            box.pack(fill="x")
            bits = []
            for bit, label in sorted((int(k), v) for k, v in bitmask.items()):
                bvar = tk.BooleanVar(value=bool(current & (1 << bit)))
                bits.append((bit, bvar))
                ttk.Checkbutton(box.body, text=f"{label}", variable=bvar, style="Panel.TCheckbutton").pack(anchor="w")
            get_value = lambda: float(sum(1 << b for b, v in bits if v.get()))
        else:
            var = tk.StringVar(value=format_value(raw, param.is_int))
            entry = ttk.Entry(editor, textvariable=var, width=16, font=("TkDefaultFont", 13))
            entry.pack(anchor="w")
            get_value = lambda: float(var.get())
            entry.bind("<Return>", lambda _e: self.stage_from_editor(name, get_value))

        buttons = tk.Frame(self.detail, bg=PANEL)
        buttons.pack(fill="x", padx=16, pady=12)
        ttk.Button(buttons, text="Stage Change", command=lambda: self.stage_from_editor(name, get_value)).pack(side="left")
        if self.store.is_changed(name):
            ttk.Button(buttons, text="Undo", command=lambda: self.store.revert(name)).pack(side="left", padx=(6, 0))

    def stage_from_editor(self, name: str, get_value):
        try:
            value = get_value()
        except ValueError:
            messagebox.showerror("Invalid value", "Enter a number.")
            return
        info = self.store.info(name)
        lo, hi = metadata_range(info)
        if lo is not None and not lo <= value <= hi:
            if not messagebox.askyesno("Outside the normal range",
                                       f"{name} is normally between {lo:g} and {hi:g}. Stage {value:g} anyway?"):
                return
        if name in PROTECTED and not values_equal(value, self.store.params[name].value, self.store.params[name].is_int):
            if not messagebox.askyesno("Protected setting", PROTECTED[name] + "\n\nChange it anyway?", icon="warning"):
                return
        self.store.stage(name, value)
