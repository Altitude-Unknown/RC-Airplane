# Read-only: print mode, RC in, servo out and attitude for N seconds.
import sys, time, math
from pymavlink import mavutil
m = mavutil.mavlink_connection(sys.argv[1], baud=115200)
m.wait_heartbeat(timeout=20)
m.mav.request_data_stream_send(m.target_system, m.target_component, 0, 10, 1)
t0, last, lp = time.time(), {}, 0
while time.time() - t0 < float(sys.argv[2]):
    msg = m.recv_match(blocking=True, timeout=1)
    if not msg: continue
    last[msg.get_type()] = msg
    if time.time() - lp > 1 and all(k in last for k in ('HEARTBEAT','RC_CHANNELS','SERVO_OUTPUT_RAW','ATTITUDE')):
        lp = time.time(); rc, so, a = last['RC_CHANNELS'], last['SERVO_OUTPUT_RAW'], last['ATTITUDE']
        print(f"{lp-t0:5.1f}s {mavutil.mode_string_v10(last['HEARTBEAT']):9} RC1-4 {[getattr(rc,f'chan{i}_raw') for i in range(1,5)]} ch5 {rc.chan5_raw} rssi {rc.rssi} | SRV1-4 {[getattr(so,f'servo{i}_raw') for i in range(1,5)]} | roll {math.degrees(a.roll):5.1f} pitch {math.degrees(a.pitch):5.1f}")
    if msg.get_type()=='STATUSTEXT': print('  MSG', msg.text)
