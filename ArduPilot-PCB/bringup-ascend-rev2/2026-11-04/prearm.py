# Read-only: ask the FC to run its pre-arm checks and print every message for a while.
import sys, time
from pymavlink import mavutil
m = mavutil.mavlink_connection(sys.argv[1], baud=115200)
hb = m.wait_heartbeat(timeout=20)
print('mode', mavutil.mode_string_v10(hb), 'armed', bool(hb.base_mode & 128))
m.mav.command_long_send(m.target_system, m.target_component, 401, 0, 0, 0, 0, 0, 0, 0, 0)  # MAV_CMD_RUN_PREARM_CHECKS
seen, t0, last = [], time.time(), {}
while time.time() - t0 < float(sys.argv[2]) if len(sys.argv) > 2 else 20:
    msg = m.recv_match(blocking=True, timeout=1)
    if not msg: continue
    t = msg.get_type()
    if t == 'STATUSTEXT':
        if msg.text not in seen: seen.append(msg.text); print(f'{time.time()-t0:5.1f}s', msg.text)
    elif t == 'COMMAND_ACK': print('ACK', msg.command, msg.result)
    else: last[t] = msg
hb = last.get('HEARTBEAT'); ss = last.get('SYS_STATUS'); rc = last.get('RC_CHANNELS')
if hb: print('mode', mavutil.mode_string_v10(hb))
if ss:
    bad = ss.onboard_control_sensors_enabled & ~ss.onboard_control_sensors_health
    print('enabled-but-unhealthy bits: 0x%x' % bad, 'prearm bit healthy:', bool(ss.onboard_control_sensors_health & 0x10000000))
if rc: print('RC', [getattr(rc, f'chan{i}_raw') for i in range(1, 9)], 'rssi', rc.rssi)
