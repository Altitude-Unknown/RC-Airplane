#!/usr/bin/env python3
# AP_FLAKE8_CLEAN
"""Verify the six output assignments and capture PWM telemetry while disarmed."""
import argparse
import json
import time
from pathlib import Path
from pymavlink import mavutil

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('port')
p.add_argument('--configure', action='store_true', help='Set only the six requested output functions')
p.add_argument('--output', required=True, type=Path)
a = p.parse_args()
expected = {f'SERVO{i}_FUNCTION': value for i, value in enumerate((70, 4, 19, 21, 0, 0), 1)}
c = mavutil.mavlink_connection(a.port, baud=115200, source_system=255, source_component=190)
r = {'port': a.port, 'expected': expected, 'parameters': {}, 'messages': [], 'changes': []}
try:
    h = c.wait_heartbeat(timeout=10)
    if h is None:
        raise RuntimeError('No heartbeat')
    if h.base_mode & 128:
        raise RuntimeError('Board armed; stopping verification')
    target = (h.get_srcSystem(), h.get_srcComponent())
    names = list(expected) + ['BRD_PWM_COUNT', 'BRD_SAFETY_DEFLT', 'ARMING_CHECK']
    for name in names:
        c.mav.param_request_read_send(*target, name.encode(), -1)
    end = time.monotonic() + 8
    while time.monotonic() < end and not all(n in r['parameters'] for n in expected):
        m = c.recv_match(type='PARAM_VALUE', blocking=True, timeout=0.5)
        if m is not None and m.param_id in names:
            r['parameters'][m.param_id] = {'value': m.param_value, 'type': m.param_type}
    for name, value in expected.items():
        if name not in r['parameters']:
            raise RuntimeError(f'Missing parameter {name}')
        old = r['parameters'][name]
        if old['value'] != value:
            if not a.configure:
                raise RuntimeError(f'{name} is {old["value"]}, expected {value}')
            c.mav.param_set_send(*target, name.encode(), float(value), old['type'])
            end = time.monotonic() + 5
            confirmed = False
            while time.monotonic() < end:
                m = c.recv_match(type='PARAM_VALUE', blocking=True, timeout=0.5)
                if m is not None and m.param_id == name and m.param_value == value:
                    confirmed = True
                    r['changes'].append({'name': name, 'old': old['value'], 'new': value})
                    r['parameters'][name]['value'] = m.param_value
                    break
            if not confirmed:
                raise RuntimeError(f'{name} update not confirmed')
    for msgid in (0, 1, 27, 29, 36):
        c.mav.command_long_send(*target, mavutil.mavlink.MAV_CMD_SET_MESSAGE_INTERVAL,
                                0, msgid, 100000, 0, 0, 0, 0, 0)
    end = time.monotonic() + 12
    while time.monotonic() < end:
        m = c.recv_match(blocking=True, timeout=0.2)
        if m is None:
            continue
        if m.get_type() == 'HEARTBEAT' and m.base_mode & 128:
            raise RuntimeError('Board became armed; stopping verification')
        if m.get_type() in ('HEARTBEAT', 'SYS_STATUS', 'RAW_IMU', 'SCALED_PRESSURE', 'SERVO_OUTPUT_RAW', 'STATUSTEXT'):
            r['messages'].append(m.to_dict())
    r['assignments_verified'] = True
finally:
    c.close()
    a.output.write_text(json.dumps(r, indent=2) + '\n')
print('Assignments:', {n: v['value'] for n,v in r['parameters'].items()})
print('Changes:', r['changes'])
samples = [m for m in r['messages'] if m['mavpackettype'] == 'SERVO_OUTPUT_RAW']
print('Servo telemetry samples:', len(samples))
if samples:
    print('Latest PWM telemetry:', samples[-1])
