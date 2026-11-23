#!/usr/bin/env python3
"""
MAVLink parameter protocol for ASCEND Flight Control: download every parameter,
write changes with read-back verification, and read/write .param backup files.
"""

from __future__ import annotations

import os
import re
import struct
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

os.environ.setdefault("MAVLINK20", "1")
from pymavlink import mavutil  # noqa: E402

mavlink = mavutil.mavlink

INT_TYPES = {
    mavlink.MAV_PARAM_TYPE_UINT8, mavlink.MAV_PARAM_TYPE_INT8,
    mavlink.MAV_PARAM_TYPE_UINT16, mavlink.MAV_PARAM_TYPE_INT16,
    mavlink.MAV_PARAM_TYPE_UINT32, mavlink.MAV_PARAM_TYPE_INT32,
}

# Never restored from a file: counters, sensor IDs and values the FC manages itself.
NEVER_RESTORE = re.compile(r"^(STAT_.*|FORMAT_VERSION|SYSID_SW_MREV|.*_GND_PRESS|.*_GND_TEMP|.*DEV_?ID\d*|.*_ID\d*)$")
# Board-specific calibrations: only restored when the file came from this same board.
CALIBRATION = re.compile(
    r"^(INS_ACC\d*(OFFS|SCAL)_[XYZ]|INS_GYR\d*OFFS_[XYZ]|INS_ACC\d*_CALTEMP|INS_GYR\d*_CALTEMP|"
    r"COMPASS_(OFS|DIA|ODI|MOT)\d*_[XYZ]|COMPASS_SCALE\d*|AHRS_TRIM_[XYZ]|"
    r"RC\d+_(MIN|MAX|TRIM)|ARSPD\d*_OFFSET)$"
)


@dataclass
class Param:
    name: str
    value: float
    ptype: int
    index: int = -1

    @property
    def is_int(self) -> bool:
        return self.ptype in INT_TYPES


class ParamError(Exception):
    pass


Progress = Callable[[str], None]


def float32(value: float) -> float:
    """The value as the FC will hold it (MAVLink carries parameters as float32)."""
    return struct.unpack("<f", struct.pack("<f", value))[0]


def format_value(value: float, is_int: bool) -> str:
    if is_int:
        return str(int(round(value)))
    text = f"{float32(value):.6g}"
    return text


def values_equal(a: float, b: float, is_int: bool) -> bool:
    if is_int:
        return int(round(a)) == int(round(b))
    return float32(a) == float32(b) or abs(a - b) <= 1e-6 * max(1.0, abs(a), abs(b))


def _name(msg) -> str:
    pid = msg.param_id
    if isinstance(pid, bytes):
        pid = pid.decode("ascii", "ignore")
    return pid.rstrip("\x00")


def download_all(link, progress: Progress = lambda _m: None, stall_timeout: float = 1.0,
                 rounds: int = 8) -> dict[str, Param]:
    """Fetch every parameter. Gaps (lost packets) are re-requested by index."""
    link.drain_param_messages()
    link.send(lambda mav: mav.param_request_list_send(link.target_system, link.target_component))
    params: dict[str, Param] = {}
    seen_index: set[int] = set()
    total = None
    stalled_rounds = 0
    last_report = 0.0

    while True:
        msg = link.wait_param_message(stall_timeout)
        if msg is not None:
            if msg.param_index != 65535:
                total = msg.param_count
                seen_index.add(msg.param_index)
            name = _name(msg)
            params[name] = Param(name, msg.param_value, msg.param_type, msg.param_index)
            stalled_rounds = 0
            if total and time.monotonic() - last_report > 0.1:
                progress(f"Loading parameters {len(seen_index)}/{total}")
                last_report = time.monotonic()
            if total and len(seen_index) >= total:
                break
            continue

        # Nothing arrived for stall_timeout seconds.
        if total is None:
            stalled_rounds += 1
            if stalled_rounds > rounds:
                raise ParamError("Flight controller did not send any parameters.")
            link.send(lambda mav: mav.param_request_list_send(link.target_system, link.target_component))
            continue
        missing = [i for i in range(total) if i not in seen_index]
        if not missing:
            break
        stalled_rounds += 1
        if stalled_rounds > rounds:
            raise ParamError(f"{len(missing)} parameters never arrived from the flight controller.")
        progress(f"Re-requesting {len(missing)} missing parameters")
        for index in missing[:50]:
            link.send(lambda mav, i=index: mav.param_request_read_send(
                link.target_system, link.target_component, b"", i))

    progress(f"Loaded {len(params)} parameters")
    return params


def set_param(link, param: Param, new_value: float, timeout: float = 1.0, retries: int = 3) -> float:
    """Write one parameter and return the value the FC reports back."""
    value = float(int(round(new_value))) if param.is_int else float(new_value)
    name_bytes = param.name.encode("ascii")
    for _attempt in range(retries + 1):
        link.send(lambda mav: mav.param_set_send(
            link.target_system, link.target_component, name_bytes, value, param.ptype))
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            msg = link.wait_param_message(max(0.0, deadline - time.monotonic()))
            if msg is not None and _name(msg) == param.name:
                return msg.param_value
    raise ParamError(f"No reply from the flight controller when setting {param.name}.")


@dataclass
class WriteResult:
    name: str
    requested: float
    actual: float | None
    ok: bool
    message: str = ""


def write_changes(link, params: dict[str, Param], changes: dict[str, float],
                  progress: Progress = lambda _m: None) -> list[WriteResult]:
    results = []
    link.drain_param_messages()
    for n, (name, new_value) in enumerate(changes.items(), start=1):
        param = params[name]
        progress(f"Writing {name} ({n}/{len(changes)})")
        try:
            actual = set_param(link, param, new_value)
        except ParamError as exc:
            results.append(WriteResult(name, new_value, None, False, str(exc)))
            continue
        ok = values_equal(actual, new_value, param.is_int)
        if ok:
            param.value = actual
            message = ""
        else:
            param.value = actual
            message = f"flight controller kept {format_value(actual, param.is_int)}"
        results.append(WriteResult(name, new_value, actual, ok, message))
    return results


# --------------------------------------------------------------------------
# Backup files (Mission Planner style "NAME,VALUE"; also accepts "NAME VALUE")
# --------------------------------------------------------------------------

def save_param_file(path: Path, params: dict[str, Param], header: str = "") -> None:
    lines = []
    if header:
        lines += [f"# {line}" for line in header.splitlines()]
    for name in sorted(params):
        p = params[name]
        lines.append(f"{name},{format_value(p.value, p.is_int)}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def load_param_file(path: Path) -> dict[str, float]:
    values: dict[str, float] = {}
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        parts = re.split(r"[,\s]+", line)
        if len(parts) < 2:
            raise ParamError(f"Line {lineno} is not 'NAME,VALUE': {raw!r}")
        try:
            values[parts[0].upper()] = float(parts[1])
        except ValueError:
            raise ParamError(f"Line {lineno} has a value that is not a number: {raw!r}") from None
    return values


@dataclass
class FilePlan:
    changes: dict[str, float]
    calibration_changes: dict[str, float]
    unknown: list[str]
    skipped: list[str]


def plan_file_restore(file_values: dict[str, float], params: dict[str, Param]) -> FilePlan:
    """Sort a file's values into normal changes, calibration changes, unknown and skipped."""
    plan = FilePlan({}, {}, [], [])
    for name, value in file_values.items():
        param = params.get(name)
        if param is None:
            plan.unknown.append(name)
            continue
        if NEVER_RESTORE.match(name):
            plan.skipped.append(name)
            continue
        if values_equal(param.value, value, param.is_int):
            continue
        (plan.calibration_changes if CALIBRATION.match(name) else plan.changes)[name] = value
    return plan
