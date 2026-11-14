# Read-only: per-second attitude means, plus mean/median of the steady part.
import sys, time, math, statistics as st
from pymavlink import mavutil
m = mavutil.mavlink_connection(sys.argv[1], baud=115200)
m.wait_heartbeat(timeout=20)
m.mav.request_data_stream_send(m.target_system, m.target_component, 0, 10, 1)
r, p, t0, sec = [], [], time.time(), []
while time.time() - t0 < float(sys.argv[2]):
    msg = m.recv_match(type='ATTITUDE', blocking=True, timeout=1)
    if not msg: continue
    s = int(time.time() - t0)
    r.append((s, math.degrees(msg.roll))); p.append((s, math.degrees(msg.pitch)))
for s in sorted({x[0] for x in r}):
    rr = [v for k, v in r if k == s]; pp = [v for k, v in p if k == s]
    print(f'{s:2d}s roll {st.mean(rr):6.2f} (spread {max(rr)-min(rr):4.2f})  pitch {st.mean(pp):6.2f}')
rv = [v for _, v in r]; pv = [v for _, v in p]
print(f'ALL median roll {st.median(rv):.2f}  pitch {st.median(pv):.2f}  roll range {min(rv):.2f}..{max(rv):.2f}')
