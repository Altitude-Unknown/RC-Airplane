#!/usr/bin/env python3
"""Read barometer telemetry from a disarmed ArduPilot board over USB."""

import argparse
import json
import time
from pathlib import Path

from pymavlink import mavutil


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("port")
    parser.add_argument("--seconds", type=int, default=20)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    connection = mavutil.mavlink_connection(
        args.port, baud=115200, source_system=255, source_component=190
    )
    result = {"port": args.port, "status_text": [], "pressure": [], "sys_status": []}
    target = None
    started = time.monotonic()
    last_heartbeat = 0
    last_request = 0
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
                target = (message.get_srcSystem(), message.get_srcComponent())
                result["target"] = target
                result["heartbeat"] = message.to_dict()
            if not target or (message.get_srcSystem(), message.get_srcComponent()) != target:
                continue
            if now - last_request >= 3:
                for msgid in (mavutil.mavlink.MAVLINK_MSG_ID_SCALED_PRESSURE,
                              mavutil.mavlink.MAVLINK_MSG_ID_SYS_STATUS):
                    connection.mav.command_long_send(
                        *target, mavutil.mavlink.MAV_CMD_REQUEST_MESSAGE,
                        0, msgid, 0, 0, 0, 0, 0, 0,
                    )
                last_request = now
            if kind == "STATUSTEXT" and message.text not in result["status_text"]:
                result["status_text"].append(message.text)
                print("Status:", message.text, flush=True)
            elif kind == "SCALED_PRESSURE":
                sample = message.to_dict()
                result["pressure"].append(sample)
                if len(result["pressure"]) <= 3:
                    print("Pressure:", sample, flush=True)
            elif kind == "SYS_STATUS":
                result["sys_status"].append(message.to_dict())
    finally:
        connection.close()
        result["elapsed_seconds"] = round(time.monotonic() - started, 2)
        args.output.write_text(json.dumps(result, indent=2) + "\n")
    print("Pressure samples:", len(result["pressure"]), flush=True)
    print("System status samples:", len(result["sys_status"]), flush=True)
    if result["sys_status"]:
        status = result["sys_status"][-1]
        flag = mavutil.mavlink.MAV_SYS_STATUS_SENSOR_ABSOLUTE_PRESSURE
        print("Barometer flags:", {
            "present": bool(status["onboard_control_sensors_present"] & flag),
            "enabled": bool(status["onboard_control_sensors_enabled"] & flag),
            "healthy": bool(status["onboard_control_sensors_health"] & flag),
        }, flush=True)


if __name__ == "__main__":
    main()
