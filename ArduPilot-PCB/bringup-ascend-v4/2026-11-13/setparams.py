# Set parameters and read each one back. Usage: setparams.py PORT NAME=VALUE ...
import sys, time
from pymavlink import mavutil
m = mavutil.mavlink_connection(sys.argv[1], baud=115200)
m.wait_heartbeat(timeout=20)
ok = True
for arg in sys.argv[2:]:
    name, val = arg.split('='); val = float(val)
    for attempt in range(3):
        m.mav.param_set_send(m.target_system, m.target_component, name.encode(), val,
                             mavutil.mavlink.MAV_PARAM_TYPE_REAL32)
        msg = m.recv_match(type='PARAM_VALUE', blocking=True, timeout=3,
                           condition=f'PARAM_VALUE.param_id=="{name}"')
        if msg: break
    good = msg is not None and abs(msg.param_value - val) < 1e-4
    ok &= good
    print(f"{'OK ' if good else 'BAD'}  {name} = {msg.param_value if msg else 'no reply':.4g}" if msg else f"BAD  {name}: no reply")
sys.exit(0 if ok else 1)
