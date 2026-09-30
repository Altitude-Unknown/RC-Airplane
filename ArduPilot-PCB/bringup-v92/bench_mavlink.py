#!/usr/bin/env python3
"""Read bench telemetry and optionally exercise one bounded servo output."""

import argparse
import json
import time
from pathlib import Path

from pymavlink import mavutil


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("port")
    parser.add_argument("--seconds", type=int, default=25)
    parser.add_argument("--output", type=Path, required=True)
    output_choice = parser.add_mutually_exclusive_group()
    output_choice.add_argument("--servo-channel", type=int, choices=range(2, 7))
    output_choice.add_argument("--motor-test", action="store_true")
    parser.add_argument("--prop-removed", action="store_true")
    parser.add_argument("--motor-secured", action="store_true")
    args = parser.parse_args()
    if (args.servo_channel or args.motor_test) and not args.prop_removed:
        parser.error("output testing requires --prop-removed")
    if args.motor_test and not args.motor_secured:
        parser.error("motor testing requires --motor-secured")

    output_channel = 1 if args.motor_test else args.servo_channel

    link = mavutil.mavlink_connection(
        args.port, baud=115200, source_system=255, source_component=190
    )
    data = {
        "port": args.port, "status_text": [], "pressure": [],
        "rc_channels": [], "sys_status": [], "servo_output_raw": [],
        "servo_commands": [],
    }
    target = None
    bench_seen = False
    ins_error_seen = False
    started = time.monotonic()
    last_heartbeat = 0
    last_request = 0
    next_servo_step = None
    servo_step = 0
    accepted_steps = 0
    positions = (1000, 1000, 1080, 1150, 1000) if args.motor_test else (1500, 1600, 1400, 1500)
    step_interval = 1.5 if args.motor_test else 0.8

    try:
        while time.monotonic() - started < args.seconds:
            now = time.monotonic()
            if now - last_heartbeat >= 1:
                link.mav.heartbeat_send(
                    mavutil.mavlink.MAV_TYPE_GCS,
                    mavutil.mavlink.MAV_AUTOPILOT_INVALID,
                    0, 0, mavutil.mavlink.MAV_STATE_ACTIVE,
                )
                last_heartbeat = now
            msg = link.recv_match(blocking=True, timeout=0.2)
            if msg is not None:
                kind = msg.get_type()
                if kind == "HEARTBEAT" and msg.autopilot == mavutil.mavlink.MAV_AUTOPILOT_ARDUPILOTMEGA:
                    target = (msg.get_srcSystem(), msg.get_srcComponent())
                    data["heartbeat"] = msg.to_dict()
                if target and (msg.get_srcSystem(), msg.get_srcComponent()) == target:
                    if kind == "STATUSTEXT":
                        if msg.text not in data["status_text"]:
                            data["status_text"].append(msg.text)
                            print("Status:", msg.text, flush=True)
                        bench_seen |= "BOREALIS BENCH: outputs test-only" in msg.text
                        ins_error_seen |= "INS: unable to initialise driver" in msg.text
                    elif kind == "SCALED_PRESSURE":
                        data["pressure"].append(msg.to_dict())
                    elif kind == "RC_CHANNELS":
                        data["rc_channels"].append(msg.to_dict())
                    elif kind == "SYS_STATUS":
                        data["sys_status"].append(msg.to_dict())
                    elif kind == "SERVO_OUTPUT_RAW":
                        data["servo_output_raw"].append(msg.to_dict())
                    elif kind == "COMMAND_ACK" and msg.command == mavutil.mavlink.MAV_CMD_DO_SET_SERVO:
                        data["servo_commands"].append({"ack": msg.result})
                        print("Servo command ACK:", msg.result, flush=True)
                        if msg.result != mavutil.mavlink.MAV_RESULT_ACCEPTED:
                            raise RuntimeError("Servo command was rejected")
                        accepted_steps += 1

            if target and now - last_request >= 2:
                for msgid in (
                    mavutil.mavlink.MAVLINK_MSG_ID_SCALED_PRESSURE,
                    mavutil.mavlink.MAVLINK_MSG_ID_RC_CHANNELS,
                    mavutil.mavlink.MAVLINK_MSG_ID_SYS_STATUS,
                    mavutil.mavlink.MAVLINK_MSG_ID_SERVO_OUTPUT_RAW,
                ):
                    link.mav.command_long_send(
                        *target, mavutil.mavlink.MAV_CMD_REQUEST_MESSAGE,
                        0, msgid, 0, 0, 0, 0, 0, 0,
                    )
                last_request = now

            if output_channel and bench_seen and ins_error_seen and target:
                if next_servo_step is None:
                    next_servo_step = now
                if servo_step < len(positions) and now >= next_servo_step:
                    pwm = positions[servo_step]
                    link.mav.command_long_send(
                        *target, mavutil.mavlink.MAV_CMD_DO_SET_SERVO,
                        0, output_channel, pwm, 0, 0, 0, 0, 0,
                    )
                    data["servo_commands"].append({"channel": output_channel, "pwm": pwm})
                    print("Output", output_channel, "PWM", pwm, flush=True)
                    servo_step += 1
                    next_servo_step = now + step_interval
        if output_channel and (servo_step != len(positions) or accepted_steps != len(positions)):
            raise RuntimeError("Bench identity or all servo command ACKs were not confirmed")
    finally:
        link.close()
        data["elapsed_seconds"] = round(time.monotonic() - started, 2)
        args.output.write_text(json.dumps(data, indent=2) + "\n")

    for key in ("pressure", "rc_channels", "sys_status", "servo_output_raw"):
        print(key, "samples:", len(data[key]), flush=True)
        if data[key]:
            print("Last", key, ":", data[key][-1], flush=True)


if __name__ == "__main__":
    main()
