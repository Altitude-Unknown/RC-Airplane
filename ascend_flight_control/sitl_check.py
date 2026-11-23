#!/usr/bin/env python3
"""
End-to-end check against a real ArduPilot (SITL or hardware), no GUI.

    python3 sitl_check.py tcp:127.0.0.1:5760
    python3 sitl_check.py /dev/cu.usbmodem1101 [mission.json]
    python3 sitl_check.py tcp:127.0.0.1:5760 --params

Mission check: uploads the mission (default: the sample mission below), reads
it back, compares, and prints the result.

--params: downloads every parameter, checks each Aircraft Settings entry exists
on the firmware, and writes one parameter back with its current value (no
change) to prove writes verify. Both refuse to run if the vehicle is armed.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from fc_link import FcLink
from param_catalog import CATALOG, curated_names
from param_protocol import download_all, format_value, write_changes
from mission_mavlink import compare_items, download_mission, mission_to_items, upload_mission
from mission_schema import mission_from_dict
from test_mission_mavlink import sample_mission


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    if "--params" in sys.argv:
        return check_params(sys.argv[1])
    mission = sample_mission()
    if len(sys.argv) > 2:
        mission = mission_from_dict(json.loads(Path(sys.argv[2]).read_text()))

    conversion = mission_to_items(mission)
    if conversion.errors:
        print("Mission errors:", *conversion.errors, sep="\n  ")
        return 1
    for w in conversion.warnings:
        print("warning:", w)

    link = FcLink(sys.argv[1])
    link.open()
    try:
        print("Connected:", link.status.summary())
        if link.status.armed:
            print("Vehicle is armed; refusing.")
            return 1
        upload_mission(link, conversion.items, progress=print)
        readback = download_mission(link, progress=lambda _m: None)
        problems = compare_items(conversion.items, readback)
        for seq, item in enumerate(readback):
            print(f"  {seq:2d} {item.describe():22s} frame={item.frame} p={item.params} "
                  f"{item.lat:.7f},{item.lon:.7f} alt={item.alt}")
        if problems:
            print("MISMATCH:", *problems, sep="\n  ")
            return 1
        print(f"PASS: {len(readback) - 1} items uploaded and verified.")
        return 0
    finally:
        link.close()


def check_params(device: str) -> int:
    link = FcLink(device)
    link.open()
    try:
        print("Connected:", link.status.summary())
        if link.status.armed:
            print("Vehicle is armed; refusing.")
            return 1
        params = download_all(link, progress=lambda m: None)
        print(f"Downloaded {len(params)} parameters")
        optional = {s.name for g in CATALOG for s in g.settings if s.absent_note}  # listed only once enabled
        missing = [n for n in curated_names() if n not in params and n not in optional]
        for name in sorted(optional - set(params)):
            print(f"  {name:18s} (not listed until it is enabled; fine)")
        for name in curated_names():
            if name in params:
                p = params[name]
                print(f"  {name:18s} {format_value(p.value, p.is_int)}")
        if missing:
            print("MISSING on this firmware:", ", ".join(missing))
            return 1
        probe = params["RTL_ALTITUDE"]
        (result,) = write_changes(link, params, {probe.name: probe.value})
        print(f"Rewrite {probe.name}={format_value(probe.value, probe.is_int)}: {'verified' if result.ok else result.message}")
        if not result.ok:
            return 1
        print(f"PASS: all {len(curated_names())} Aircraft Settings present; writes verify.")
        return 0
    finally:
        link.close()


if __name__ == "__main__":
    sys.exit(main())
