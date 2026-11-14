# Read-only recorder: attitude, vibration, raw accel and throttle while the motor runs.
# Usage: vibetest.py PORT SECONDS OUTFILE.csv
import sys, time, math, csv
from pymavlink import mavutil
m = mavutil.mavlink_connection(sys.argv[1], baud=115200)
m.wait_heartbeat(timeout=20)
m.mav.request_data_stream_send(m.target_system, m.target_component, 0, 10, 1)
for mid in (241, 26):  # VIBRATION, SCALED_IMU
    m.mav.command_long_send(m.target_system, m.target_component, 511, 0, mid, 100000, 0, 0, 0, 0, 0)
last, rows, t0, nxt = {}, [], time.time(), 0.0
while time.time() - t0 < float(sys.argv[2]):
    msg = m.recv_match(blocking=True, timeout=1)
    if not msg: continue
    t = msg.get_type(); last[t] = msg
    if t == 'STATUSTEXT': print(f'{time.time()-t0:5.1f}s MSG {msg.text}', flush=True)
    now = time.time() - t0
    if now >= nxt and all(k in last for k in ('ATTITUDE', 'SERVO_OUTPUT_RAW', 'HEARTBEAT')):
        nxt = now + 0.1
        a, so, hb = last['ATTITUDE'], last['SERVO_OUTPUT_RAW'], last['HEARTBEAT']
        v, imu = last.get('VIBRATION'), last.get('SCALED_IMU')
        rows.append(dict(t=round(now, 2), armed=int(bool(hb.base_mode & 128)),
            thr_pct=round((so.servo1_raw - 1100) / 8.0, 1),
            roll=round(math.degrees(a.roll), 2), pitch=round(math.degrees(a.pitch), 2),
            ax=imu.xacc if imu else '', ay=imu.yacc if imu else '', az=imu.zacc if imu else '',
            vx=round(v.vibration_x, 3) if v else '', vy=round(v.vibration_y, 3) if v else '',
            vz=round(v.vibration_z, 3) if v else '', clip=(v.clipping_0 if v else '')))
with open(sys.argv[3], 'w', newline='') as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
# Summary per 2-second window.
print(' t(s) armed thr%  roll  pitch   ay(mg)  vibeX/Y/Z        clip')
for s in range(0, int(rows[-1]['t']) + 1, 2):
    win = [r for r in rows if s <= r['t'] < s + 2]
    if not win: continue
    mean = lambda k: sum(float(r[k]) for r in win if r[k] != '') / max(1, sum(1 for r in win if r[k] != ''))
    print(f"{s:4d} {win[-1]['armed']:4d} {mean('thr_pct'):5.0f} {mean('roll'):6.2f} {mean('pitch'):6.2f} {mean('ay'):8.0f}  "
          f"{mean('vx'):.2f}/{mean('vy'):.2f}/{mean('vz'):.2f}  {win[-1]['clip']}")
