#!/usr/bin/env python3
"""Small per-user settings (settings.json in the same folder as the Units preference)."""

from __future__ import annotations

import json
from typing import Any

from units import config_dir


def _path():
    return config_dir() / "settings.json"


def load_setting(key: str, default: Any = None) -> Any:
    try:
        return json.loads(_path().read_text(encoding="utf-8")).get(key, default)
    except (OSError, ValueError, AttributeError):
        return default


def save_setting(key: str, value: Any) -> bool:
    """Store key (None removes it). Other keys, like the Units preference, are kept."""
    path = _path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            data = {}
    except (OSError, ValueError):
        data = {}
    if value is None:
        data.pop(key, None)
    else:
        data[key] = value
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return True
    except OSError:
        return False
