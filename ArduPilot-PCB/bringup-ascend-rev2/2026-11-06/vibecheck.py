# Read-only: uptime, vibration/clipping counters, attitude, RC, mode.
import sys, time, math
from pymavlink import mavutil
m = mavutil.mavlink_connection(sys.argv[1], baud=115200)
m.wait_heartbeat(timeout=20)
m.mav.request_data_stream_send(m.target_system, m.target_component, 0, 5, 1)
for mid in (241, 2):  # VIBRATION, SYSTEM_TIME
    m.mav.command_long_send(m.target_system, m.target_component, 511, 0, mid, 500000, 0, 0, 0, 0, 0)
last, t0 = {}, time.time()
while time.time() - t0 < float(sys.argv[2]):
    msg = m.recv_match(blocking=True, timeout=1)
    if msg: last[msg.get_type()] = msg
    if msg and msg.get_type() == 'STATUSTEXT': print('MSG', msg.text)
for k in ('SYSTEM_TIME', 'VIBRATION', 'ATTITUDE', 'AHRS2', 'RC_CHANNELS', 'HEARTBEAT', 'SYS_STATUS'):
    v = last.get(k)
    if not v: print(k, 'none'); continue
    if k == 'SYSTEM_TIME': print('uptime s', v.time_boot_ms / 1000)
    elif k == 'VIBRATION': print('VIBE x/y/z', round(v.vibration_x, 3), round(v.vibration_y, 3), round(v.vibration_z, 3), 'clip', v.clipping_0, v.clipping_1, v.clipping_2)
    elif k in ('ATTITUDE', 'AHRS2'): print(k, 'roll', round(math.degrees(v.roll), 2), 'pitch', round(math.degrees(v.pitch), 2))
    elif k == 'RC_CHANNELS': print('RC', [getattr(v, f'chan{i}_raw') for i in range(1, 7)])
    elif k == 'HEARTBEAT': print('mode', mavutil.mode_string_v10(v))
