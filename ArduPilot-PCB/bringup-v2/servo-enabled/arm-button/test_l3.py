"""Temporarily test GPIO90/PC12/L3 with checked relay commands, never arm."""
import json
import time
from pathlib import Path
from pymavlink import mavutil

directory = Path(__file__).resolve().parent
record = {'gpio': 90, 'pin': 'PC12', 'restored': False, 'events': []}
link = None
original = {}


def connect():
    global link
    link = mavutil.mavlink_connection('/dev/cu.usbmodem1101', baud=115200,
                                      source_system=255, source_component=190)
    heartbeat = link.wait_heartbeat(timeout=15)
    assert heartbeat and heartbeat.autopilot == 3 and heartbeat.type == 1
    assert not heartbeat.base_mode & 128, 'Aircraft armed; stopping LED test'


def receive(kind, timeout=0.2):
    msg = link.recv_match(type=kind, blocking=True, timeout=timeout)
    if msg and msg.get_type() == 'HEARTBEAT':
        assert not msg.base_mode & 128, 'Aircraft became armed'
    return msg


def read(name):
    link.mav.param_request_read_send(link.target_system, link.target_component, name.encode(), -1)
    end = time.monotonic() + 4
    while time.monotonic() < end:
        msg = receive(['PARAM_VALUE', 'HEARTBEAT'])
        if msg and msg.get_type() == 'PARAM_VALUE' and msg.param_id == name:
            return {'value': msg.param_value, 'type': msg.param_type}
    raise RuntimeError('Parameter unavailable: ' + name)


def write(name, value, param_type):
    link.mav.param_set_send(link.target_system, link.target_component, name.encode(), value, param_type)
    end = time.monotonic() + 4
    while time.monotonic() < end:
        msg = receive(['PARAM_VALUE', 'HEARTBEAT'])
        if msg and msg.get_type() == 'PARAM_VALUE' and msg.param_id == name and msg.param_value == value:
            record['events'].append({'parameter': name, 'value': value})
            return
    raise RuntimeError('Write not confirmed: ' + name)


def reboot():
    link.mav.command_long_send(link.target_system, link.target_component,
                               mavutil.mavlink.MAV_CMD_PREFLIGHT_REBOOT_SHUTDOWN,
                               0, 1, 0, 0, 0, 0, 0, 0)
    link.close()
    time.sleep(3)
    connect()


def relay(on):
    link.mav.command_long_send(link.target_system, link.target_component,
                               mavutil.mavlink.MAV_CMD_DO_SET_RELAY,
                               0, 0, int(on), 0, 0, 0, 0, 0)
    end = time.monotonic() + 4
    while time.monotonic() < end:
        msg = receive(['COMMAND_ACK', 'HEARTBEAT'])
        if msg and msg.get_type() == 'COMMAND_ACK' and msg.command == mavutil.mavlink.MAV_CMD_DO_SET_RELAY:
            assert msg.result == mavutil.mavlink.MAV_RESULT_ACCEPTED, 'Relay command rejected'
            record['events'].append({'l3_on': on, 'ack': msg.result})
            return
    raise RuntimeError('No relay acknowledgement')


try:
    connect()
    original['RELAY1_FUNCTION'] = read('RELAY1_FUNCTION')
    original['NTF_LED_TYPES'] = read('NTF_LED_TYPES')
    assert original['RELAY1_FUNCTION']['value'] == 0, 'Relay1 already assigned'
    assert read('ARMING_REQUIRE')['value'] == 1, 'Unexpected arming configuration'
    assert int(original['NTF_LED_TYPES']['value']) & 1, 'Board LED disabled'
    write('RELAY1_FUNCTION', 1, original['RELAY1_FUNCTION']['type'])
    for name in ('RELAY1_PIN', 'RELAY1_DEFAULT', 'RELAY1_INVERTED'):
        original[name] = read(name)
    record['original'] = original
    (directory / 'l3-test.json').write_text(json.dumps(record, indent=2) + '\n')
    for name, value in (('RELAY1_PIN', 90), ('RELAY1_DEFAULT', 0), ('RELAY1_INVERTED', 0)):
        write(name, value, original[name]['type'])
    write('NTF_LED_TYPES', int(original['NTF_LED_TYPES']['value']) & ~1, original['NTF_LED_TYPES']['type'])
    reboot()
    relay(True)
    print('L3 ON TEST STARTED: PC12 driven high for 45 seconds. Observe L3 now.', flush=True)
    end = time.monotonic() + 45
    while time.monotonic() < end:
        receive('HEARTBEAT', timeout=0.5)
    relay(False)
    print('L3 OFF. Restoring original LED/relay configuration.', flush=True)
finally:
    try:
        if link is not None:
            # Restore exposed relay subparameters before disabling the group.
            for name in ('RELAY1_PIN', 'RELAY1_DEFAULT', 'RELAY1_INVERTED', 'RELAY1_FUNCTION', 'NTF_LED_TYPES'):
                if name in original:
                    write(name, original[name]['value'], original[name]['type'])
            if 'NTF_LED_TYPES' in original:
                reboot()
                assert read('NTF_LED_TYPES') == original['NTF_LED_TYPES']
                assert read('RELAY1_FUNCTION') == original['RELAY1_FUNCTION']
                record['restored'] = True
                print('Original settings restored and confirmed; FC disarmed.', flush=True)
    finally:
        if link is not None:
            link.close()
        (directory / 'l3-test.json').write_text(json.dumps(record, indent=2) + '\n')
