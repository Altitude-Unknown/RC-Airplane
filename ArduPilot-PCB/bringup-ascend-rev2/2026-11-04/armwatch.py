# Read-only: watch RC sticks, mode, armed state and messages while the pilot tries to arm.
import sys, time
from pymavlink import mavutil
m = mavutil.mavlink_connection(sys.argv[1], baud=115200)
m.wait_heartbeat(timeout=20)
for p in ('ARMING_RUDDER','ARMING_REQUIRE','RC4_MIN','RC4_MAX','RC4_TRIM','RC4_DZ','RC4_REVERSED','RC3_MIN','RC3_TRIM','RC3_DZ','RCMAP_YAW','RCMAP_THROTTLE','THR_MIN','ARMING_SKIPCHK'):
    m.mav.param_request_read_send(m.target_system, m.target_component, p.encode(), -1)
t0, lastp, mx, mn = time.time(), 0, {}, {}
while time.time() - t0 < float(sys.argv[2]):
    msg = m.recv_match(blocking=True, timeout=1)
    if not msg: continue
    t = msg.get_type()
    if t == 'PARAM_VALUE': print('PARAM', msg.param_id, msg.param_value)
    elif t == 'STATUSTEXT': print(f'{time.time()-t0:5.1f}s MSG', msg.text, flush=True)
    elif t == 'RC_CHANNELS':
        ch = [getattr(msg, f'chan{i}_raw') for i in range(1, 6)]
        for i, v in enumerate(ch, 1): mx[i] = max(mx.get(i, 0), v); mn[i] = min(mn.get(i, 9999), v)
        if time.time() - lastp > 2: print(f'{time.time()-t0:5.1f}s RC1-5', ch, flush=True); lastp = time.time()
    elif t == 'HEARTBEAT' and msg.get_srcComponent() == 1 and msg.base_mode & 128:
        print(f'{time.time()-t0:5.1f}s ARMED', flush=True)
print('RC min', mn, 'max', mx)
