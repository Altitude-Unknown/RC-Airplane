# Read-only status: sensors, RC, attitude, temperatures, selected params.
import sys, time
from pymavlink import mavutil
m = mavutil.mavlink_connection(sys.argv[1], baud=115200)
m.wait_heartbeat(timeout=20)
params = sys.argv[2].split(',') if len(sys.argv) > 2 else []
for p in params:
    m.mav.param_request_read_send(m.target_system, m.target_component, p.encode(), -1)
seen, last, pv, t0 = [], {}, {}, time.time()
rcmin, rcmax = {}, {}
dur = float(sys.argv[3]) if len(sys.argv) > 3 else 10
while time.time() - t0 < dur:
    msg = m.recv_match(blocking=True, timeout=1)
    if not msg: continue
    t = msg.get_type()
    if t == 'STATUSTEXT' and msg.text not in seen: seen.append(msg.text)
    elif t == 'PARAM_VALUE': pv[msg.param_id] = msg.param_value
    elif t == 'RC_CHANNELS':
        for i in range(1, 9):
            v = getattr(msg, f'chan{i}_raw')
            rcmin[i] = min(rcmin.get(i, 9999), v); rcmax[i] = max(rcmax.get(i, 0), v)
        last[t] = msg.to_dict()
    else: last[t] = msg.to_dict()
ss = last.get('SYS_STATUS', {})
for k, b in {'gyro':1,'accel':2,'mag':4,'baro':8,'rc':65536,'ahrs':2097152}.items():
    print(f"{k:5} present={bool(ss.get('onboard_control_sensors_present',0)&b)} enabled={bool(ss.get('onboard_control_sensors_enabled',0)&b)} healthy={bool(ss.get('onboard_control_sensors_health',0)&b)}")
a = last.get('ATTITUDE', {})
import math
if a: print('ATTITUDE roll %.1f pitch %.1f yaw %.1f' % tuple(math.degrees(a[k]) for k in ('roll','pitch','yaw')))
for k in ('RAW_IMU', 'SCALED_IMU', 'SCALED_PRESSURE', 'HEARTBEAT', 'SERVO_OUTPUT_RAW', 'RC_CHANNELS'):
    d = last.get(k); 
    if d: d.pop('mavpackettype', None); print(k, d)
if rcmin: print('RC min/max over window:', {i: (rcmin[i], rcmax[i]) for i in rcmin})
for p in params: print('PARAM', p, pv.get(p))
print('STATUSTEXT:'); [print('  ', s) for s in seen]
