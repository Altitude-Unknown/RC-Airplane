#!/usr/bin/env python3
"""
The computer's location, where the operating system provides one.

- macOS: Core Location, through native/libascend_mac.dylib. macOS asks the
  person for permission the first time.
- Windows: the Windows location service, read with PowerShell's
  System.Device.Location (no extra packages). Location must be on in
  Settings > Privacy & security > Location.
- Raspberry Pi / Linux: not available; use the saved map home instead.

request_location(widget, on_done) calls on_done(LocationResult) on the Tk
thread (on Windows the lookup runs on a worker thread and is handed back
through widget.after polling).
"""

from __future__ import annotations

import queue
import subprocess
import sys
import threading
from dataclasses import dataclass
from typing import Callable

import mac_native

TIMEOUT_S = 20

WINDOWS_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
try {
  Add-Type -AssemblyName System.Device
  $w = New-Object System.Device.Location.GeoCoordinateWatcher([System.Device.Location.GeoPositionAccuracy]::Default)
  $w.Start()
  $deadline = (Get-Date).AddSeconds(15)
  while ($w.Status -ne 'Ready' -and $w.Permission -ne 'Denied' -and (Get-Date) -lt $deadline) { Start-Sleep -Milliseconds 200 }
  $loc = $w.Position.Location
  $ci = [System.Globalization.CultureInfo]::InvariantCulture
  if ($w.Permission -eq 'Denied') { 'denied' }
  elseif ($w.Status -eq 'Disabled') { 'off' }
  elseif ($loc.IsUnknown) { 'unknown' }
  else { 'ok ' + $loc.Latitude.ToString($ci) + ' ' + $loc.Longitude.ToString($ci) + ' ' + $loc.HorizontalAccuracy.ToString($ci) }
  $w.Stop()
} catch { 'error ' + $_.Exception.GetType().Name }
"""


@dataclass
class LocationResult:
    ok: bool
    lat: float | None = None
    lon: float | None = None
    accuracy_m: float | None = None
    message: str = ""


def supported() -> bool:
    if sys.platform == "darwin":
        return mac_native.load() is not None
    return sys.platform == "win32"


def parse(text: str) -> LocationResult:
    parts = (text or "").strip().split()
    if len(parts) >= 3 and parts[0] == "ok":
        try:
            lat, lon = float(parts[1]), float(parts[2])
            acc = float(parts[3]) if len(parts) > 3 else None
        except ValueError:
            return LocationResult(False, message="The computer returned a location that could not be read.")
        if -90 <= lat <= 90 and -180 <= lon <= 180:
            return LocationResult(True, lat, lon, acc)
        return LocationResult(False, message="The computer returned a location that is out of range.")
    word = parts[0] if parts else ""
    messages = {
        "denied": "Location access is turned off for this app. Allow it in your computer's privacy settings.",
        "off": "Location services are turned off on this computer.",
        "unknown": "The computer could not work out its location (no Wi-Fi or GPS position yet).",
    }
    return LocationResult(False, message=messages.get(word, "The computer's location is not available."))


def windows_lookup() -> str:
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)  # no console window flash from the windowed app
    try:
        done = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", WINDOWS_SCRIPT],
                              capture_output=True, text=True, timeout=TIMEOUT_S, creationflags=flags)
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"
    lines = [line.strip() for line in done.stdout.splitlines() if line.strip()]
    return lines[-1] if lines else "unknown"


def request_location(widget, on_done: Callable[[LocationResult], None]) -> bool:
    """Start a lookup. Returns False (and never calls on_done) where it is not supported."""
    if sys.platform == "darwin":
        state = {"answered": False}

        def answer(data: str):
            if not state["answered"]:
                state["answered"] = True
                on_done(parse(data))

        if not mac_native.request_location(widget, answer):
            return False
        # macOS may never answer (e.g. no permission prompt for Python run from source).
        widget.after(TIMEOUT_S * 1000, lambda: answer("unknown"))
        return True
    if sys.platform != "win32":
        return False
    results: queue.Queue = queue.Queue()
    threading.Thread(target=lambda: results.put(windows_lookup()), daemon=True).start()

    def poll():
        try:
            text = results.get_nowait()
        except queue.Empty:
            widget.after(200, poll)
            return
        on_done(parse(text))

    widget.after(200, poll)
    return True
