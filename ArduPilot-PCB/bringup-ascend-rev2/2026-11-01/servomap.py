# Read-only: correlate RC inputs with servo outputs while the pilot moves one stick at a time.
import sys, time
from pymavlink import mavutil
m = mavutil.mavlink_connection(sys.argv[1], baud=115200); m.wait_heartbeat(timeout=20)
rc, sv, rows, modes, t0 = None, None, [], set(), time.time()
while time.time() - t0 < 60:
    msg = m.recv_match(type=['RC_CHANNELS', 'SERVO_OUTPUT_RAW', 'HEARTBEAT'], blocking=True, timeout=1)
    if not msg: continue
    t = msg.get_type()
    if t == 'HEARTBEAT' and msg.type == 1: modes.add((msg.custom_mode, bool(msg.base_mode & 128)))
    elif t == 'RC_CHANNELS': rc = [msg.chan1_raw, msg.chan2_raw, msg.chan3_raw, msg.chan4_raw, msg.chan5_raw]
    elif rc: rows.append((rc, [msg.servo1_raw, msg.servo2_raw, msg.servo3_raw, msg.servo4_raw, msg.servo5_raw, msg.servo6_raw]))
print('modes seen (custom_mode, armed):', modes, 'samples', len(rows))
def corr(a, b):
    n = len(a); ma, mb = sum(a)/n, sum(b)/n
    va = sum((x-ma)**2 for x in a); vb = sum((y-mb)**2 for y in b)
    return 0 if va == 0 or vb == 0 else sum((x-ma)*(y-mb) for x, y in zip(a, b)) / (va*vb)**0.5
names = ['roll', 'pitch', 'throttle', 'yaw', 'ch5']
for j in range(6):
    s = [r[1][j] for r in rows]
    best = max(range(5), key=lambda i: abs(corr([r[0][i] for r in rows], s)))
    c = corr([r[0][best] for r in rows], s)
    print(f'SERVO{j+1}: range {min(s)}..{max(s)}  follows {names[best]} (corr {c:+.2f})')
for i in range(5): print(f'RC{i+1} {names[i]:8} range {min(r[0][i] for r in rows)}..{max(r[0][i] for r in rows)}')
