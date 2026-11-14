# Read-only: fetch every parameter and save as JSON.
import sys, json, time
from pymavlink import mavutil
m = mavutil.mavlink_connection(sys.argv[1], baud=115200)
m.wait_heartbeat(timeout=20)
m.mav.param_request_list_send(m.target_system, m.target_component)
p, total, t0 = {}, None, time.time()
while time.time() - t0 < 60:
    msg = m.recv_match(type='PARAM_VALUE', blocking=True, timeout=3)
    if not msg:
        if total and len(p) < total:
            for i in range(total):
                pass
        break
    p[msg.param_id] = msg.param_value; total = msg.param_count
    if total and len(p) >= total: break
missing = total - len(p) if total else None
for _ in range(3):
    if not missing: break
    m.mav.param_request_list_send(m.target_system, m.target_component)
    t1 = time.time()
    while time.time() - t1 < 20:
        msg = m.recv_match(type='PARAM_VALUE', blocking=True, timeout=3)
        if not msg: break
        p[msg.param_id] = msg.param_value
        if len(p) >= total: break
    missing = total - len(p)
print('got', len(p), 'of', total)
json.dump(dict(sorted(p.items())), open(sys.argv[2], 'w'), indent=1)
