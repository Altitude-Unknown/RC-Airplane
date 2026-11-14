# Read-only: average attitude over a window while the airplane sits still.
import sys, time, math, statistics as st
from pymavlink import mavutil
m = mavutil.mavlink_connection(sys.argv[1], baud=115200)
m.wait_heartbeat(timeout=20)
for p in ('AHRS_TRIM_X','AHRS_TRIM_Y','AHRS_ORIENTATION'):
    m.mav.param_request_read_send(m.target_system, m.target_component, p.encode(), -1)
r, p, t0 = [], [], time.time()
while time.time() - t0 < float(sys.argv[2]):
    msg = m.recv_match(type=['ATTITUDE','PARAM_VALUE'], blocking=True, timeout=1)
    if not msg: continue
    if msg.get_type() == 'PARAM_VALUE': print('PARAM', msg.param_id, round(msg.param_value, 4)); continue
    r.append(math.degrees(msg.roll)); p.append(math.degrees(msg.pitch))
print(f'samples {len(r)}  roll mean {st.mean(r):.1f} (min {min(r):.1f} max {max(r):.1f})  pitch mean {st.mean(p):.1f} (min {min(p):.1f} max {max(p):.1f})')
