#!/usr/bin/env python3
"""Run the bounded BOREALIS v92 TAER receiver-to-output bench test."""

import argparse
import json
import time
from pathlib import Path

from pymavlink import mavutil


def send_gate(link, target, pwm):
    link.mav.command_long_send(
        *target, mavutil.mavlink.MAV_CMD_DO_SET_SERVO,
        0, 7, pwm, 0, 0, 0, 0, 0,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("port")
    parser.add_argument("--seconds", type=int, default=60)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--enable-outputs", action="store_true")
    parser.add_argument("--prop-removed", action="store_true")
    parser.add_argument("--motor-secured", action="store_true")
    args = parser.parse_args()
    if not (args.enable_outputs and args.prop_removed and args.motor_secured):
        parser.error("TAER test requires --enable-outputs, --prop-removed, and --motor-secured")
    if not 1 <= args.seconds <= 75:
        parser.error("--seconds must be 1..75 (firmware hard limit: 90)")

    link = mavutil.mavlink_connection(
        args.port, baud=115200, source_system=255, source_component=190
    )
    data = {"status_text": [], "rc_channels": [], "servo_output_raw": [],
            "command_acks": []}
    target = None
    bench_seen = False
    ins_error_seen = False
    start_requested = False
    low_since = None
    active_since = None
    last_gate = 0
    last_heartbeat = 0
    last_request = 0
    started = time.monotonic()

    try:
        while time.monotonic() - started < 25 or active_since is not None:
            now = time.monotonic()
            if now - last_heartbeat >= 1:
                link.mav.heartbeat_send(
                    mavutil.mavlink.MAV_TYPE_GCS,
                    mavutil.mavlink.MAV_AUTOPILOT_INVALID,
                    0, 0, mavutil.mavlink.MAV_STATE_ACTIVE,
                )
                last_heartbeat = now
            msg = link.recv_match(blocking=True, timeout=0.15)
            if msg is not None:
                kind = msg.get_type()
                if (kind == "HEARTBEAT" and
                        msg.autopilot == mavutil.mavlink.MAV_AUTOPILOT_ARDUPILOTMEGA):
                    target = (msg.get_srcSystem(), msg.get_srcComponent())
                if target and (msg.get_srcSystem(), msg.get_srcComponent()) == target:
                    if kind == "STATUSTEXT":
                        if msg.text not in data["status_text"]:
                            data["status_text"].append(msg.text)
                            print("Status:", msg.text, flush=True)
                        bench_seen |= "BOREALIS TAER TEST: USB start required" in msg.text
                        ins_error_seen |= "INS: unable to initialise driver" in msg.text
                        if "BOREALIS TAER STOP:" in msg.text:
                            break
                    elif kind == "RC_CHANNELS":
                        data["rc_channels"].append(msg.to_dict())
                        if msg.chancount >= 4 and msg.chan3_raw <= 1050:
                            if low_since is None:
                                low_since = now
                        else:
                            low_since = None
                    elif kind == "SERVO_OUTPUT_RAW":
                        data["servo_output_raw"].append(msg.to_dict())
                    elif (kind == "COMMAND_ACK" and
                          msg.command == mavutil.mavlink.MAV_CMD_DO_SET_SERVO):
                        data["command_acks"].append({"result": msg.result})
                        if msg.result != mavutil.mavlink.MAV_RESULT_ACCEPTED:
                            raise RuntimeError(f"TAER gate command rejected: {msg.result}")
                        if start_requested and active_since is None:
                            active_since = now
                            print("TAER gate accepted; move the transmitter controls now", flush=True)

            if target and now - last_request >= 2:
                for msgid in (mavutil.mavlink.MAVLINK_MSG_ID_RC_CHANNELS,
                              mavutil.mavlink.MAVLINK_MSG_ID_SERVO_OUTPUT_RAW):
                    link.mav.command_long_send(
                        *target, mavutil.mavlink.MAV_CMD_REQUEST_MESSAGE,
                        0, msgid, 0, 0, 0, 0, 0, 0,
                    )
                last_request = now

            if (active_since is None and target and bench_seen and ins_error_seen and
                    low_since is not None and now - low_since >= 2 and
                    now - last_gate >= 1):
                send_gate(link, target, 1500)
                start_requested = True
                last_gate = now
            elif active_since is not None:
                if now - active_since >= args.seconds:
                    break
                if now - last_gate >= 0.8:
                    send_gate(link, target, 1500)
                    last_gate = now
        if active_since is None:
            raise RuntimeError("TAER firmware, receiver, and low throttle were not confirmed")
    finally:
        stop_sent = False
        try:
            if target is not None and bench_seen and ins_error_seen:
                for _ in range(3):
                    try:
                        send_gate(link, target, 1000)
                        stop_sent = True
                    except (OSError, ValueError):
                        break
                    time.sleep(0.1)
        finally:
            link.close()
            data["elapsed_seconds"] = round(time.monotonic() - started, 2)
            args.output.write_text(json.dumps(data, indent=2) + "\n")
        if stop_sent:
            print("STOP sent; firmware also stops on USB loss or after 90 s", flush=True)
        elif start_requested:
            print("USB STOP unavailable; firmware timeout is 2 s after link loss", flush=True)

    print("RC samples:", len(data["rc_channels"]), flush=True)
    print("Output samples:", len(data["servo_output_raw"]), flush=True)


if __name__ == "__main__":
    main()
