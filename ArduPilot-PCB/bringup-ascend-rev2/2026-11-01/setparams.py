# Set parameters and verify each by reading it back. Usage: setparams.py PORT NAME=VAL ...
import sys, time
from pymavlink import mavutil
m = mavutil.mavlink_connection(sys.argv[1], baud=115200)
m.wait_heartbeat(timeout=20)
for kv in sys.argv[2:]:
    name, val = kv.split('='); val = float(val)
    for attempt in range(3):
        m.mav.param_set_send(m.target_system, m.target_component, name.encode(), val, mavutil.mavlink.MAV_PARAM_TYPE_REAL32)
        msg = m.recv_match(type='PARAM_VALUE', blocking=True, timeout=2,
                           condition=f'PARAM_VALUE.param_id=="{name}"')
        if msg and abs(msg.param_value - val) < 1e-4: print(f'OK   {name} = {msg.param_value:g}'); break
    else: print(f'FAIL {name} (last {msg.param_value if msg else None})')
