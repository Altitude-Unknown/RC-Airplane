# Read-only logging: demanded vs actual pitch and elevator output at ~20 Hz.
# Uses SET_MESSAGE_INTERVAL (not saved; resets on reboot).
import sys, time, math
from pymavlink import mavutil
m = mavutil.mavlink_connection(sys.argv[1], baud=115200)
m.wait_heartbeat(timeout=20)
for mid in (36, 30, 62, 65):  # SERVO_OUTPUT_RAW, ATTITUDE, NAV_CONTROLLER_OUTPUT, RC_CHANNELS
    m.mav.command_long_send(m.target_system, m.target_component, 511, 0, mid, 50000, 0, 0, 0, 0, 0)
t0, last, lp = time.time(), {}, 0
while time.time() - t0 < float(sys.argv[2]):
    msg = m.recv_match(blocking=True, timeout=1)
    if not msg: continue
    t = msg.get_type()
    if t == 'STATUSTEXT': print(f'{time.time()-t0:5.2f} MSG {msg.text}', flush=True)
    if t in ('SERVO_OUTPUT_RAW','ATTITUDE','NAV_CONTROLLER_OUTPUT','RC_CHANNELS') or (t == 'HEARTBEAT' and msg.get_srcComponent() == 1): last[t] = msg
    if time.time() - lp > 0.05 and len(last) == 5:
        lp = time.time(); so, a, n, rc, hb = (last[k] for k in ('SERVO_OUTPUT_RAW','ATTITUDE','NAV_CONTROLLER_OUTPUT','RC_CHANNELS','HEARTBEAT'))
        print(f'{time.time()-t0:5.2f} {mavutil.mode_string_v10(hb):8} E{rc.chan2_raw} T{rc.chan3_raw} | pitch dem {n.nav_pitch:6.1f} act {math.degrees(a.pitch):6.1f} q {math.degrees(a.pitchspeed):6.1f} | ele {so.servo3_raw} | roll dem {n.nav_roll:5.1f} act {math.degrees(a.roll):5.1f} ail {so.servo2_raw}', flush=True)
