#!/usr/bin/env python3
"""Bounded USB bench status capture, or the receiver's existing bootloader request."""
import argparse
import time
import serial
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("port")
parser.add_argument("--command", choices=("STATUS", "DIAG", "BOOTLOADER"), default="STATUS")
parser.add_argument("--count", type=int, default=1)
parser.add_argument("--interval", type=float, default=1)
parser.add_argument("--output", type=Path)
args = parser.parse_args()
if not 1 <= args.count <= 60 or args.interval < 0.1:
    parser.error("Use 1–60 samples with at least 0.1 seconds between requests")
started = time.monotonic()
with serial.Serial(args.port, 115200, timeout=0.1, write_timeout=1) as port:
    for sample in range(args.count):
        port.write((args.command + "\n").encode())
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            try:
                line = port.readline().decode(errors="replace").strip()
            except serial.SerialException:
                if args.command == "BOOTLOADER":
                    break
                raise
            if line:
                record=f"hostElapsed={time.monotonic()-started:.3f}s {line}"
                print(record, flush=True)
                if args.output:
                    with args.output.open("a") as capture:
                        capture.write(record+"\n")
                break
        else:
            raise SystemExit("No receiver reply within two seconds")
        if sample + 1 < args.count:
            time.sleep(args.interval)
