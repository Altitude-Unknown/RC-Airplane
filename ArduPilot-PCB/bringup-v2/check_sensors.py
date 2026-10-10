#!/usr/bin/env python3
# AP_FLAKE8_CLEAN
"""Capture disarmed V2 sensor telemetry; never changes parameters or arms."""
import argparse
import json
import math
import time
from collections import Counter
from pathlib import Path
from pymavlink import mavutil

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('port')
p.add_argument('--seconds', type=int, default=30)
p.add_argument('--output', type=Path, required=True)
a = p.parse_args()
c = mavutil.mavlink_connection(a.port, baud=115200, source_system=255, source_component=190)
result = {'port': a.port, 'messages': [], 'status_text': []}
started = time.monotonic()
last_heartbeat = 0
last_request = 0
target = None
try:
    while time.monotonic() - started < a.seconds:
        now = time.monotonic()
        if now - last_heartbeat >= 1:
            c.mav.heartbeat_send(mavutil.mavlink.MAV_TYPE_GCS, mavutil.mavlink.MAV_AUTOPILOT_INVALID,
                                 0, 0, mavutil.mavlink.MAV_STATE_ACTIVE)
            last_heartbeat = now
        m = c.recv_match(blocking=True, timeout=0.2)
        if m is None:
            continue
        kind = m.get_type()
        if kind == 'HEARTBEAT' and m.autopilot == mavutil.mavlink.MAV_AUTOPILOT_ARDUPILOTMEGA:
            target = (m.get_srcSystem(), m.get_srcComponent())
            if m.base_mode & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED:
                raise RuntimeError('Board is armed; stopping diagnostic capture')
        if target is None or (m.get_srcSystem(), m.get_srcComponent()) != target:
            continue
        if now - last_request >= 5:
            for msgid in (0, 1, 26, 27, 29, 30, 116, 129, 147, 148):
                c.mav.command_long_send(*target, mavutil.mavlink.MAV_CMD_SET_MESSAGE_INTERVAL,
                                        0, msgid, 100000, 0, 0, 0, 0, 0)
            for param in ('INS_ACC_ID', 'INS_GYR_ID', 'INS_ACC2_ID', 'INS_GYR2_ID', 'BARO1_DEVID'):
                c.mav.param_request_read_send(*target, param.encode(), -1)
            last_request = now
        if kind == 'STATUSTEXT':
            if m.text not in result['status_text']:
                result['status_text'].append(m.text)
                print('Status:', m.text, flush=True)
        if kind in ('HEARTBEAT', 'SYS_STATUS', 'RAW_IMU', 'SCALED_IMU', 'SCALED_IMU2',
                    'SCALED_IMU3', 'SCALED_PRESSURE', 'ATTITUDE', 'PARAM_VALUE', 'AUTOPILOT_VERSION'):
            result['messages'].append({'elapsed': round(now - started, 3), **m.to_dict()})
finally:
    c.close()
    result['elapsed_seconds'] = round(time.monotonic() - started, 2)
    a.output.write_text(json.dumps(result, indent=2) + '\n')
counts = Counter(m['mavpackettype'] for m in result['messages'])
print('Messages:', dict(counts))
for kind in ('SCALED_PRESSURE', 'RAW_IMU', 'SCALED_IMU', 'SCALED_IMU2', 'SYS_STATUS'):
    samples = [m for m in result['messages'] if m['mavpackettype'] == kind]
    if samples:
        print(kind, 'first:', samples[0], 'last:', samples[-1])
        if kind.startswith('SCALED_IMU') or kind == 'RAW_IMU':
            norms = [math.sqrt(sum(m[f'{axis}acc'] ** 2 for axis in 'xyz')) for m in samples]
            print('Acceleration magnitude mg min/mean/max:', min(norms), sum(norms)/len(norms), max(norms))
