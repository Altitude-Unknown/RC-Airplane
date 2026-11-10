# Read-only: measure IMU axes for flat and nose-down poses, track RC5/RC6.
import sys, time, math
from pymavlink import mavutil
m = mavutil.mavlink_connection(sys.argv[1], baud=115200); m.wait_heartbeat(timeout=20)
hist, flat, tilt, rc = [], None, None, {5: [9999, 0], 6: [9999, 0]}
t0 = time.time()
while time.time() - t0 < 150:
    msg = m.recv_match(type=['RAW_IMU', 'RC_CHANNELS'], blocking=True, timeout=1)
    if not msg: continue
    if msg.get_type() == 'RC_CHANNELS':
        for c in (5, 6):
            v = getattr(msg, f'chan{c}_raw')
            if v: rc[c][0] = min(rc[c][0], v); rc[c][1] = max(rc[c][1], v)
        continue
    a = (msg.xacc, msg.yacc, msg.zacc); hist = (hist + [a])[-4:]
    if len(hist) < 4 or max(max(h[i] for h in hist) - min(h[i] for h in hist) for i in range(3)) > 60: continue
    avg = tuple(sum(h[i] for h in hist) / 4 for i in range(3))
    if flat is None and max(abs(v) for v in avg) > 900 and abs(avg[2]) > 900:
        flat = avg; print(f't={time.time()-t0:.0f}s FLAT {tuple(round(v) for v in flat)}', flush=True)
    elif flat and tilt is None and math.dist(avg, flat) > 500:
        tilt = avg; print(f't={time.time()-t0:.0f}s TILT {tuple(round(v) for v in tilt)}', flush=True)
    if tilt and time.time() - t0 > 45: break
print('RC5/RC6 min,max:', rc)
if flat and tilt:
    cands = {0: lambda x,y,z: (x,y,z), 8: lambda x,y,z: (x,-y,-z), 10: lambda x,y,z: (y,x,-z),
             12: lambda x,y,z: (-x,y,-z), 14: lambda x,y,z: (-y,-x,-z),
             2: lambda x,y,z: (-y,x,z), 4: lambda x,y,z: (-x,-y,z), 6: lambda x,y,z: (y,-x,z)}
    for k, f in cands.items():
        bf, bt = f(*flat), f(*tilt)
        # level: z ~ -1g; nose down: body x clearly negative, y near zero
        ok = bf[2] < -800 and bt[0] < -400 and abs(bt[1]) < 300
        print(f'AHRS_ORIENTATION {k:2}: flat {tuple(round(v) for v in bf)} nose-down {tuple(round(v) for v in bt)} {"<== MATCH" if ok else ""}')
