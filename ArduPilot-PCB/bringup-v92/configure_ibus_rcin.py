#!/usr/bin/env python3
"""Configure v92 USART6 (SERIAL2) as an ArduPilot serial RC input."""

import argparse
import time

from pymavlink import mavutil


def read_parameter(link, target, name, timeout=8):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        link.mav.param_request_read_send(*target, name.encode(), -1)
        reply = link.recv_match(type="PARAM_VALUE", blocking=True, timeout=0.5)
        if reply and reply.param_id.rstrip("\x00") == name:
            return reply.param_value
    raise TimeoutError(f"No {name} response from board")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("port")
    args = parser.parse_args()
    link = mavutil.mavlink_connection(args.port, baud=115200)
    try:
        heartbeat = link.wait_heartbeat(timeout=10)
        if heartbeat is None or heartbeat.autopilot != mavutil.mavlink.MAV_AUTOPILOT_ARDUPILOTMEGA:
            raise RuntimeError("ArduPilot heartbeat not found")
        target = (heartbeat.get_srcSystem(), heartbeat.get_srcComponent())
        current = read_parameter(link, target, "SERIAL2_PROTOCOL")
        print("SERIAL2_PROTOCOL before:", current, flush=True)
        if current not in (0, 23):
            raise RuntimeError("SERIAL2_PROTOCOL is not unused or already RCIN")
        if current != 23:
            link.mav.param_set_send(*target, b"SERIAL2_PROTOCOL", 23,
                                    mavutil.mavlink.MAV_PARAM_TYPE_INT32)
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                if read_parameter(link, target, "SERIAL2_PROTOCOL", timeout=2) == 23:
                    break
            else:
                raise RuntimeError("SERIAL2_PROTOCOL did not read back as 23")
            print("SERIAL2_PROTOCOL verified: 23 (RCIN); reboot required", flush=True)
        else:
            print("SERIAL2_PROTOCOL verified: 23 (RCIN)", flush=True)
    finally:
        link.close()


if __name__ == "__main__":
    main()
