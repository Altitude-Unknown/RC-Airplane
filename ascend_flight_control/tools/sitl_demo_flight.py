#!/usr/bin/env python3
"""
Fly a short demo mission in ArduPlane SITL, so the Flight tab has something to show.

    python3 tools/sitl_demo_flight.py              # SITL's second port (the app uses 5760)
    python3 tools/sitl_demo_flight.py tcp:127.0.0.1:5763

Simulator only: it refuses non-local connections and autopilots without the
simulator's SIM_SPEEDUP parameter, so it can never arm a real aircraft.

Mission: takeoff to 60 m, a box of waypoints around home, two 80 m laps, then
return home. Open the app, connect on tcp:127.0.0.1:5760, press
"Download from FC" on the Mission tab, then watch the Flight tab.
"""

from __future__ import annotations

import math
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fc_link import FcLink, mavlink  # noqa: E402
from mission_mavlink import mission_to_items, upload_mission  # noqa: E402
from mission_schema import HomePoint, LoiterSettings, Mission, Waypoint  # noqa: E402
from param_protocol import Param, set_param  # noqa: E402

PLANE_AUTO = 10


def offset(lat, lon, north_m, east_m):
    return lat + north_m / 111_320.0, lon + east_m / (111_320.0 * math.cos(math.radians(lat)))


def demo_mission(lat, lon) -> Mission:
    m = Mission(name="SITL demo", home=HomePoint(lat, lon, 0))
    points = [(150, 0, "takeoff"), (400, 250, "waypoint"), (400, -250, "waypoint"),
              (-150, -250, "waypoint"), (-150, 250, "loiter"), (0, 0, "return_home")]
    for n, (north, east, action) in enumerate(points, start=1):
        plat, plon = offset(lat, lon, north, east)
        wp = Waypoint(n, plat, plon, altitude_m=60 if action == "takeoff" else 80, speed_mps=22, action=action)
        if action == "loiter":
            wp.loiter = LoiterSettings(mode="turns", turns=2, radius_m=80)
        m.waypoints.append(wp)
    return m


def read_param(link, name: str, timeout=2.0):
    link.drain_param_messages()
    link.send(lambda mav: mav.param_request_read_send(link.target_system, link.target_component, name.encode(), -1))
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        msg = link.wait_param_message(end - time.monotonic())
        if msg is not None and msg.param_id.rstrip("\x00") == name:
            return msg
    return None


def command(link, cmd, *params):
    p = list(params) + [0] * (7 - len(params))
    link.send(lambda mav: mav.command_long_send(link.target_system, link.target_component, cmd, 0, *p))


def main() -> int:
    device = sys.argv[1] if len(sys.argv) > 1 else "tcp:127.0.0.1:5762"
    if "127.0.0.1" not in device and "localhost" not in device:
        print("Refusing: the demo flight only runs against a simulator on this computer.")
        return 1
    link = FcLink(device)
    link.open()
    try:
        if read_param(link, "SIM_SPEEDUP") is None:
            print("Refusing: this autopilot has no SIM_SPEEDUP parameter, so it is not SITL.")
            return 1
        print("Connected to SITL:", link.status.summary())
        while link.status.lat is None or link.status.gps_fix < 3:
            print("Waiting for GPS...")
            time.sleep(1)
        home_lat, home_lon = link.status.lat, link.status.lon
        items = mission_to_items(demo_mission(home_lat, home_lon)).items
        upload_mission(link, items)
        print(f"Uploaded demo mission ({len(items) - 1} items)")
        # The demo flies without a pilot; SITL's RC inputs stay centered.
        thr = read_param(link, "THR_FAILSAFE")
        if thr is not None and thr.param_value != 0:
            set_param(link, Param("THR_FAILSAFE", thr.param_value, thr.param_type), 0)
            print("SITL: THR_FAILSAFE set to 0 for the unattended demo")
        command(link, mavlink.MAV_CMD_DO_SET_MODE, mavlink.MAV_MODE_FLAG_CUSTOM_MODE_ENABLED, PLANE_AUTO)
        for attempt in range(30):
            command(link, mavlink.MAV_CMD_COMPONENT_ARM_DISARM, 1)
            time.sleep(2)
            if link.status.armed:
                break
            if link.status.messages:
                print("FC:", link.status.messages[-1])
        if not link.status.armed:
            print("Could not arm SITL; see the messages above.")
            return 1
        print("Armed in", link.status.mode, "- the plane is taking off. Watch the Flight tab.")
        end = time.monotonic() + float(sys.argv[2]) if len(sys.argv) > 2 else None
        while end is None or time.monotonic() < end:
            st = link.status
            alt = f"{st.alt_rel:.0f} m" if st.alt_rel is not None else "?"
            gs = f"{st.groundspeed:.0f} m/s" if st.groundspeed is not None else "?"
            print(f"  {st.mode:6s} alt {alt:>6s}  gs {gs:>7s}  target item {st.wp_seq}", flush=True)
            time.sleep(5)
        return 0
    finally:
        link.close()


if __name__ == "__main__":
    sys.exit(main())
