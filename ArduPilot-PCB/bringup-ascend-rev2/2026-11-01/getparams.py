# Read-only full parameter download to JSON.
import sys, time, json
from pymavlink import mavutil
m = mavutil.mavlink_connection(sys.argv[1], baud=115200)
m.wait_heartbeat(timeout=20)
m.mav.param_request_list_send(m.target_system, m.target_component)
p, total, last = {}, None, time.time()
while time.time() - last < 5:
    msg = m.recv_match(type='PARAM_VALUE', blocking=True, timeout=1)
    if not msg: continue
    last = time.time(); p[msg.param_id] = msg.param_value; total = msg.param_count
    if total and len(p) >= total: break
missing = [i for i in range(total or 0)] if False else None
print(f'got {len(p)} of {total}')
json.dump(dict(sorted(p.items())), open(sys.argv[2], 'w'), indent=1)
