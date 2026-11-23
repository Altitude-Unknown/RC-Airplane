#!/usr/bin/env python3
"""
macOS helpers from native/libascend_mac.dylib: trackpad pinch and the computer's location.

Tk 8.6 ignores trackpad pinch gestures, and location comes from Apple's Core
Location. Both are handled in native code, which hands results to Tk as
ordinary virtual events (<<AscendPinch>>, <<AscendLocation>>) that Python
receives through Tkinter's normal event path.

Python must not be called directly from AppKit or Core Location callbacks (for
example through pyobjc): Tkinter releases the interpreter lock while it waits
for events, and the two collide with a fatal "PyEval_RestoreThread" error.

On other platforms, or if the library is missing, everything here reports
"not available" and the app carries on without it.
"""

from __future__ import annotations

import ctypes
import sys
import tkinter
from pathlib import Path
from typing import Callable

_LIB_NAME = "libascend_mac.dylib"
_lib = None
_lib_tried = False


def library_path() -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / "native" / _LIB_NAME


def load():
    """The native library, or None (not macOS, or the file is missing)."""
    global _lib, _lib_tried
    if _lib_tried:
        return _lib
    _lib_tried = True
    if sys.platform != "darwin" or not library_path().exists():
        return None
    try:
        lib = ctypes.CDLL(str(library_path()))
        lib.ascend_pinch_install.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
        lib.ascend_pinch_install.restype = ctypes.c_int
        lib.ascend_pinch_remove.argtypes = []
        lib.ascend_pinch_remove.restype = None
        lib.ascend_location_request.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
        lib.ascend_location_request.restype = ctypes.c_int
    except (OSError, AttributeError):
        return None
    _lib = lib
    return lib


def _bind(widget, event: str, handler: Callable[[str], None]) -> None:
    command = widget.register(handler)
    widget.tk.call("bind", str(widget), event, f"{command} %d")


def install_pinch_zoom(widget, on_pinch: Callable[[float, int, int], None]) -> bool:
    """Call on_pinch(magnification, x, y) for pinches over `widget`. Returns True if active."""
    lib = load()
    if lib is None:
        return False

    def handle(data: str):
        try:
            magnification = float(data)
            px, py = widget.winfo_pointerxy()
            if widget.winfo_containing(px, py) is widget:
                on_pinch(magnification, px - widget.winfo_rootx(), py - widget.winfo_rooty())
        except (ValueError, tkinter.TclError):
            pass

    _bind(widget, "<<AscendPinch>>", handle)
    if not lib.ascend_pinch_install(ctypes.c_void_p(widget.tk.interpaddr()), str(widget).encode("ascii")):
        return False
    widget.bind("<Destroy>", lambda _e: lib.ascend_pinch_remove(), add="+")
    return True


def request_location(widget, on_result: Callable[[str], None]) -> bool:
    """Ask Core Location once; on_result gets "ok <lat> <lon> <acc>", "denied", "off" or "error <code>".
    Returns False if the native helper is not available."""
    lib = load()
    if lib is None:
        return False
    if not getattr(widget, "_ascend_location_bound", False):
        _bind(widget, "<<AscendLocation>>", lambda data: widget._ascend_location_callback(data))
        widget._ascend_location_bound = True
    widget._ascend_location_callback = on_result
    return bool(lib.ascend_location_request(ctypes.c_void_p(widget.tk.interpaddr()), str(widget).encode("ascii")))
