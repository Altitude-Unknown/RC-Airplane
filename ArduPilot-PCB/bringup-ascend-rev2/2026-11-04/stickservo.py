# Read-only: log RC in, servo out, mode and attitude ~5 Hz for a bench stick test.
import sys, time, math
from pymavlink import mavutil
m = mavutil.mavlink_connection(sys.argv[1], baud=115200)
m.wait_heartbeat(timeout=20)
t0, last, lp = time.time(), {}, 0
while time.time() - t0 < float(sys.argv[2]):
    msg = m.recv_match(blocking=True, timeout=1)
    if not msg: continue
    t = msg.get_type()
    if t == 'STATUSTEXT': print(f'{time.time()-t0:5.1f} MSG {msg.text}', flush=True)
    if t in ('RC_CHANNELS','SERVO_OUTPUT_RAW','ATTITUDE') or (t == 'HEARTBEAT' and msg.get_srcComponent() == 1): last[t] = msg
    if time.time() - lp > 0.2 and len(last) == 4:
        lp = time.time(); rc, so, a, hb = last['RC_CHANNELS'], last['SERVO_OUTPUT_RAW'], last['ATTITUDE'], last['HEARTBEAT']
        print(f'{time.time()-t0:5.1f} {mavutil.mode_string_v10(hb):9} armed={int(bool(hb.base_mode&128))} RC A{rc.chan1_raw} E{rc.chan2_raw} T{rc.chan3_raw} R{rc.chan4_raw} | OUT thr{so.servo1_raw} ail{so.servo2_raw} ele{so.servo3_raw} rud{so.servo4_raw} | roll {math.degrees(a.roll):5.1f} pitch {math.degrees(a.pitch):5.1f}', flush=True)
