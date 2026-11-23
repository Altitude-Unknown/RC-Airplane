#!/usr/bin/env python3
"""
Regenerate param_metadata/ArduPlane.json from an ArduPilot source tree.

    ~/opt/ardupilot-venv/bin/python3 tools/make_param_metadata.py ../../ardupilot-ascend-release

Run it whenever the ASCEND firmware moves to a new ArduPilot version, so the
editor's names, ranges and option lists match the firmware on the board.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

KEEP = ("DisplayName", "Description", "Units", "Range", "Values", "Bitmask",
        "Increment", "RebootRequired", "ReadOnly", "User")
OUT = Path(__file__).resolve().parent.parent / "param_metadata" / "ArduPlane.json"


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    tree = Path(sys.argv[1]).resolve()
    parser = tree / "Tools" / "autotest" / "param_metadata" / "param_parse.py"
    commit = subprocess.run(["git", "-C", str(tree), "rev-parse", "--short", "HEAD"],
                            capture_output=True, text=True).stdout.strip()
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run([sys.executable, str(parser), "--vehicle", "Plane", "--format", "json"],
                       cwd=tmp, check=True, capture_output=True)
        raw = json.loads((Path(tmp) / "apm.pdef.json").read_text())
    params = {}
    for group in raw.values():
        for name, info in group.items():
            if not isinstance(info, dict):
                continue  # the {"json": {"version": 0}} format marker
            params[name] = {k: info[k] for k in KEEP if k in info}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"source": f"{tree.name}@{commit}", "params": params},
                              separators=(",", ":"), sort_keys=True))
    print(f"Wrote {len(params)} parameters from {tree.name}@{commit} to {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
