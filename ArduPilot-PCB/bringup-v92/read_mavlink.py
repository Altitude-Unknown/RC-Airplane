#!/usr/bin/env python3
# AP_FLAKE8_CLEAN
"""Read a board heartbeat, version, parameters, and status text; never arm."""

import argparse
import json
import time
from pathlib import Path

from pymavlink import mavutil


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("port")
    parser.add_argument("--seconds", type=int, default=45)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    connection = mavutil.mavlink_connection(
        args.port, baud=115200, source_system=255, source_component=190
    )
    result = {"port": args.port, "heartbeats": [], "status_text": [], "parameters": {}}
    expected_count = None
    received_indices = set()
    target = None
    requested_at = None
    started = time.monotonic()
    last_heartbeat = 0
    last_retry = 0
    try:
        while time.monotonic() - started < args.seconds:
            now = time.monotonic()
            if now - last_heartbeat >= 1:
                connection.mav.heartbeat_send(
                    mavutil.mavlink.MAV_TYPE_GCS,
                    mavutil.mavlink.MAV_AUTOPILOT_INVALID,
                    0, 0, mavutil.mavlink.MAV_STATE_ACTIVE,
                )
                last_heartbeat = now
            message = connection.recv_match(blocking=True, timeout=0.2)
            if message is None:
                continue
            kind = message.get_type()
            if kind == "HEARTBEAT" and message.autopilot == mavutil.mavlink.MAV_AUTOPILOT_ARDUPILOTMEGA:
                result["heartbeats"].append(message.to_dict())
                if target is None:
                    target = (message.get_srcSystem(), message.get_srcComponent())
                    result["target"] = target
                    print("ArduPilot heartbeat:", message, flush=True)
                    connection.mav.command_long_send(
                        *target, mavutil.mavlink.MAV_CMD_REQUEST_MESSAGE,
                        0, mavutil.mavlink.MAVLINK_MSG_ID_AUTOPILOT_VERSION,
                        0, 0, 0, 0, 0, 0,
                    )
                    connection.mav.param_request_list_send(*target)
                    requested_at = now
            elif target and (message.get_srcSystem(), message.get_srcComponent()) == target:
                if kind == "AUTOPILOT_VERSION":
                    result["version"] = message.to_dict()
                    print("Firmware version:", message, flush=True)
                elif kind == "STATUSTEXT":
                    text = message.text
                    if text not in result["status_text"]:
                        result["status_text"].append(text)
                        print("Status:", text, flush=True)
                elif kind == "PARAM_VALUE":
                    expected_count = message.param_count
                    received_indices.add(message.param_index)
                    result["parameters"][message.param_id] = {
                        "value": message.param_value,
                        "type": message.param_type,
                        "index": message.param_index,
                    }
            if target and requested_at and expected_count and now - requested_at > 15 and now - last_retry > 3:
                missing = sorted(set(range(expected_count)) - received_indices)
                for index in missing[:20]:
                    connection.mav.param_request_read_send(*target, b"", index)
                last_retry = now
            if expected_count and len(received_indices) == expected_count and now - started >= 15:
                break
    finally:
        connection.close()
        result["expected_parameter_count"] = expected_count
        result["received_parameter_count"] = len(received_indices)
        result["complete_parameter_download"] = bool(expected_count and len(received_indices) == expected_count)
        result["elapsed_seconds"] = round(time.monotonic() - started, 2)
        args.output.write_text(json.dumps(result, indent=2) + "\n")
    print("Heartbeats:", len(result["heartbeats"]), flush=True)
    print("Parameters:", len(received_indices), "/", expected_count, flush=True)
    if not result["heartbeats"] or not result["complete_parameter_download"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
