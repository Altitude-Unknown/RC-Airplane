# Six-position accelerometer calibration; auto-confirms each pose once the board is still in it.
import sys, time
from pymavlink import mavutil
POS = 42429  # MAV_CMD_ACCELCAL_VEHICLE_POS
NAMES = {1: 'LEVEL', 2: 'LEFT', 3: 'RIGHT', 4: 'NOSEDOWN', 5: 'NOSEUP', 6: 'BACK'}
EXPECT = {1: (2, -1), 2: (1, 1), 3: (1, -1), 4: (0, -1), 5: (0, 1), 6: (2, 1)}  # (axis, sign) of body specific force
m = mavutil.mavlink_connection(sys.argv[1], baud=115200); m.wait_heartbeat(timeout=20)
m.mav.command_long_send(m.target_system, m.target_component,
                        mavutil.mavlink.MAV_CMD_PREFLIGHT_CALIBRATION, 0, 0, 0, 0, 0, 1, 0, 0)
want, hist, t0 = None, [], time.time()
while time.time() - t0 < 420:
    msg = m.recv_match(blocking=True, timeout=1)
    if not msg: continue
    t = msg.get_type()
    if t == 'STATUSTEXT': print(f't={time.time()-t0:.0f}s FC: {msg.text}', flush=True)
    elif t == 'COMMAND_ACK' and msg.command == mavutil.mavlink.MAV_CMD_PREFLIGHT_CALIBRATION:
        print('start ack result', msg.result, flush=True)
    elif t == 'COMMAND_LONG' and msg.command == POS:
        p = int(msg.param1)
        if p == 16777215: print('RESULT: SUCCESS', flush=True); break
        if p == 16777216: print('RESULT: FAILED', flush=True); break
        if p != want: want, hist = p, []; print(f't={time.time()-t0:.0f}s waiting for {NAMES.get(p, p)}', flush=True)
    elif t == 'RAW_IMU' and want:
        a = (msg.xacc, msg.yacc, msg.zacc); hist = (hist + [a])[-5:]
        if int(time.time()) % 5 == 0 and len(hist) % 2: print(f't={time.time()-t0:.0f}s   seeing {a}', flush=True)
        ax, sg = EXPECT[want]
        if len(hist) == 5 and all(h[ax] * sg > 800 for h in hist) and \
           max(max(h[i] for h in hist) - min(h[i] for h in hist) for i in range(3)) < 120:
            print(f't={time.time()-t0:.0f}s {NAMES[want]} held {a} -> confirm', flush=True)
            m.mav.command_long_send(m.target_system, m.target_component, POS, 0, want, 0, 0, 0, 0, 0, 0)
            hist = []; want = None
else: print('RESULT: TIMEOUT', flush=True)
