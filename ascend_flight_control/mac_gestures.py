#!/usr/bin/env python3
"""
Trackpad pinch-to-zoom on macOS.

Tk 8.6 ignores trackpad magnify (pinch) gestures. native/libascend_pinch.dylib
watches for them in AppKit and posts each one to the widget as a normal Tk
virtual event, <<AscendPinch>>, carrying the magnification. Python handles it
through Tkinter's usual event path.

Python code must not be called directly from the AppKit callback (for example
through pyobjc): Tkinter releases the interpreter lock while it waits for
events, and the two collide with a fatal "PyEval_RestoreThread" error.

Without the library (other platforms, or a missing file) this does nothing and
the map still zooms with scroll, +/- keys and the zoom buttons.
"""

from __future__ import annotations

import ctypes
import sys
from pathlib import Path
from typing import Callable

_LIB_NAME = "libascend_pinch.dylib"


def _library_path() -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / "native" / _LIB_NAME


def install_pinch_zoom(widget, on_pinch: Callable[[float, int, int], None]) -> bool:
    """Call on_pinch(magnification, x, y) for pinches over `widget`. Returns True if active."""
    if sys.platform != "darwin":
        return False
    path = _library_path()
    if not path.exists():
        return False
    try:
        lib = ctypes.CDLL(str(path))
        lib.ascend_pinch_install.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
        lib.ascend_pinch_install.restype = ctypes.c_int
        lib.ascend_pinch_remove.argtypes = []
        lib.ascend_pinch_remove.restype = None
    except (OSError, AttributeError):
        return False

    def handle(data: str):
        try:
            magnification = float(data)
            px, py = widget.winfo_pointerxy()
            if widget.winfo_containing(px, py) is widget:
                on_pinch(magnification, px - widget.winfo_rootx(), py - widget.winfo_rooty())
        except (ValueError, tk_errors()):
            pass

    command = widget.register(handle)
    widget.tk.call("bind", str(widget), "<<AscendPinch>>", f"{command} %d")
    interp = widget.tk.interpaddr()
    if not lib.ascend_pinch_install(ctypes.c_void_p(interp), str(widget).encode("ascii")):
        return False
    widget.bind("<Destroy>", lambda _e: lib.ascend_pinch_remove(), add="+")
    widget._ascend_pinch_lib = lib  # keep the library loaded for the widget's lifetime
    return True


def tk_errors():
    import tkinter
    return tkinter.TclError
