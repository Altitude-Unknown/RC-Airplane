"""Listen briefly to a transmitter's USB console without sending commands."""
import argparse
import json
import time

import serial
from serial.tools import list_ports


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", required=True)
    args = parser.parse_args()
    device = next((p for p in list_ports.comports() if p.device == args.port), None)
    if device is None or device.product != "Altitude RC TX M0":
        raise SystemExit("Expected Altitude RC TX M0 not found; no port opened.")
    captured = bytearray()
    # 115200 baud only: never use the bootloader's 1200-baud reset sequence.
    # No writes, reset, configuration command, or model change.
    with serial.Serial(args.port, baudrate=115200, timeout=0.1,
                       write_timeout=0.1, exclusive=True) as connection:
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline and len(captured) < 32768:
            captured.extend(connection.read(min(connection.in_waiting or 1, 1024)))
    lines = captured.decode("utf-8", errors="replace").splitlines()
    # Keep channel/status diagnostics; omit model names, binding records and
    # arbitrary configuration contents from the summary.
    diagnostic_lines = [line for line in lines if any(
        marker in line for marker in ("thr=", "mapped_thr=", "THROTTLE_", "BUDDY_STATUS"))]
    print(json.dumps({"product": device.product, "port": args.port,
                      "bytes_received": len(captured), "line_count": len(lines),
                      "diagnostic_lines": diagnostic_lines[-12:]}, indent=2))


if __name__ == "__main__":
    main()
