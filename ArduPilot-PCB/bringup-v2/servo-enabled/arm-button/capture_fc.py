"""Back up parameters and telemetry without arming or writing parameters."""
import argparse
import json
import time
from pathlib import Path
from pymavlink import mavutil

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--port', required=True)
parser.add_argument('--output', required=True, type=Path)
parser.add_argument('--compare', type=Path)
parser.add_argument('--prearm-checks', action='store_true')
args = parser.parse_args()
c = mavutil.mavlink_connection(args.port, baud=115200, source_system=255, source_component=190)
try:
    heartbeat = c.wait_heartbeat(timeout=12)
    assert heartbeat is not None, 'No heartbeat'
    assert heartbeat.autopilot == mavutil.mavlink.MAV_AUTOPILOT_ARDUPILOTMEGA, 'Unexpected autopilot'
    assert heartbeat.type == mavutil.mavlink.MAV_TYPE_FIXED_WING, 'Unexpected vehicle'
    assert not heartbeat.base_mode & 128, 'Aircraft armed; stopping'
    target = (heartbeat.get_srcSystem(), heartbeat.get_srcComponent())
    c.mav.param_request_list_send(*target)
    parameters = {}
    count = None
    messages = []
    start = time.monotonic()
    requested = False
    while time.monotonic() - start < 25:
        msg = c.recv_match(blocking=True, timeout=0.2)
        if msg is None or (msg.get_srcSystem(), msg.get_srcComponent()) != target:
            continue
        if msg.get_type() == 'HEARTBEAT':
            assert not msg.base_mode & 128, 'Aircraft armed during capture'
        if msg.get_type() == 'STATUSTEXT':
            messages.append(msg.to_dict())
        if msg.get_type() == 'PARAM_VALUE':
            count = msg.param_count
            parameters[msg.param_index] = msg.to_dict()
            if len(parameters) == count:
                break
        if time.monotonic() - start > 10 and count and not requested:
            for index in range(count):
                if index not in parameters:
                    c.mav.param_request_read_send(*target, b'', index)
            requested = True
    assert count and len(parameters) == count, f'Incomplete parameter backup {len(parameters)}/{count}'
    values = {p['param_id']: p['param_value'] for p in parameters.values()}
    assert values['SERVO1_FUNCTION'] == 70 and values['SERIAL2_PROTOCOL'] == 23, 'Unexpected FC configuration'
    for msgid in (0, 1, 36, 65, 148):
        c.mav.command_long_send(*target, mavutil.mavlink.MAV_CMD_REQUEST_MESSAGE,
                                0, msgid, 0, 0, 0, 0, 0, 0)
    if args.prearm_checks:
        c.mav.command_long_send(*target, mavutil.mavlink.MAV_CMD_RUN_PREARM_CHECKS,
                                0, 0, 0, 0, 0, 0, 0, 0)
    end = time.monotonic() + 5
    while time.monotonic() < end:
        msg = c.recv_match(blocking=True, timeout=0.2)
        if msg is None or (msg.get_srcSystem(), msg.get_srcComponent()) != target:
            continue
        if msg.get_type() == 'HEARTBEAT':
            assert not msg.base_mode & 128, 'Aircraft armed during telemetry'
        if msg.get_type() in ('HEARTBEAT', 'SYS_STATUS', 'SERVO_OUTPUT_RAW', 'RC_CHANNELS',
                             'AUTOPILOT_VERSION', 'STATUSTEXT'):
            messages.append(msg.to_dict())
    record = {'port': args.port, 'heartbeat': heartbeat.to_dict(), 'count': count,
              'parameters': parameters, 'values': values, 'messages': messages}
    if args.compare:
        before = json.loads(args.compare.read_text())['values']
        record['parameter_changes'] = {name: [before.get(name), values.get(name)]
                                       for name in set(before) | set(values)
                                       if before.get(name) != values.get(name)}
        startup_parameters = {'STAT_BOOTCNT', 'STAT_RUNTIME', 'INS_GYROFFS_X',
                              'INS_GYROFFS_Y', 'INS_GYROFFS_Z', 'INS_GYR1_CALTEMP',
                              'BARO1_GND_PRESS'}
        record['configuration_changes'] = {name: change for name, change in record['parameter_changes'].items()
                                           if name not in startup_parameters}
    args.output.write_text(json.dumps(record, indent=2) + '\n')
    print(f'FC identified; disarmed; captured {count} parameters')
    print({k: values[k] for k in ('AHRS_ORIENTATION', 'AHRS_EKF_TYPE', 'ARMING_SKIPCHK',
                                'ARMING_REQUIRE', 'SERVO1_MIN', 'SERVO1_MAX', 'SERVO1_TRIM', 'SERIAL2_PROTOCOL')})
    print('Messages:', [m['text'] for m in messages if m['mavpackettype'] == 'STATUSTEXT'])
    if args.compare:
        print('Parameter changes:', record['parameter_changes'])
        assert not record['configuration_changes'], 'Configuration changes detected; review capture'
finally:
    c.close()
