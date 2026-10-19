#!/usr/bin/env python3
"""Play bounded D11 alarm patterns in TX USB Config Mode (aircraft power off)."""
import argparse
import json
from pathlib import Path
import time

import serial
from serial.tools import list_ports


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--serial', help='USB serial number when more than one TX is connected')
    parser.add_argument('--pattern', choices=('both', 'five', 'one'), default='both')
    parser.add_argument('--output', type=Path, help='Save evidence to a new JSON file')
    args = parser.parse_args()
    matches = [p for p in list_ports.comports()
               if p.vid == 0x03EB and p.pid == 0x2402 and p.product == 'Altitude RC TX M0'
               and (not args.serial or p.serial_number == args.serial)]
    if len(matches) != 1:
        raise SystemExit('Connect one Altitude TX M0, or specify its --serial number.')
    if args.output and args.output.exists():
        raise SystemExit('Output already exists; preserve it and choose a new filename.')
    record = {'serial': matches[0].serial_number, 'port': matches[0].device, 'patterns': []}
    with serial.Serial(matches[0].device, 115200, timeout=.25) as connection:
        connection.reset_input_buffer()

        def command(line):
            connection.write((line + '\n').encode('ascii'))
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                response = connection.readline().decode('ascii', errors='replace').strip()
                if response:
                    return response
            raise RuntimeError(f'No response to {line!r}')

        if command('PING') != 'PONG':
            raise SystemExit('Enter USB Config Mode and close other serial apps first.')
        record['info'] = json.loads(command('INFO'))
        if not record['info'].get('buzzer_test'):
            raise SystemExit('This firmware does not support the Config Mode buzzer test.')
        initial = json.loads(command('BEEP STATUS'))
        assert initial['pin'] == 11, 'Unexpected buzzer output pin'
        assert initial['first_alarm_ms'] == 300000 and initial['repeat_ms'] == 60000
        assert not initial['active'], 'A buzzer pattern is already playing'
        record['before'] = initial
        requested = ('FIVE_MIN', 'ONE_MIN') if args.pattern == 'both' else (
            'FIVE_MIN' if args.pattern == 'five' else 'ONE_MIN',)
        try:
            for pattern in requested:
                response = command('BEEP ' + pattern)
                assert response == 'OK BEEP ' + pattern, response
                print(f'Playing {pattern} pattern on D11', flush=True)
                started = time.monotonic()
                deadline = started + 10
                while True:
                    time.sleep(.15)
                    status = json.loads(command('BEEP STATUS'))
                    if not status['active']:
                        break
                    if time.monotonic() > deadline:
                        raise RuntimeError('Buzzer pattern did not finish on time')
                record['patterns'].append({'name': pattern, 'ack': response,
                                           'elapsed_s': round(time.monotonic() - started, 2),
                                           'final_status': status})
                assert status['throttle_run_ms'] == initial['throttle_run_ms']
                print(f'{pattern} finished; hardware sound requires listener confirmation', flush=True)
                if pattern != requested[-1]:
                    time.sleep(1)
        finally:
            command('BEEP STOP')
        record['after'] = json.loads(command('BEEP STATUS'))
    if args.output:
        with args.output.open('x') as output:
            json.dump(record, output, indent=2)
            output.write('\n')
    print(json.dumps(record, indent=2))


if __name__ == '__main__':
    main()
