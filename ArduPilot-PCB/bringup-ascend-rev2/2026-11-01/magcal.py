# Onboard compass calibration with autosave; prints progress and the final report.
import sys, time
from pymavlink import mavutil
m = mavutil.mavlink_connection(sys.argv[1], baud=115200); m.wait_heartbeat(timeout=20)
# DO_START_MAG_CAL: mask=0 (all), retry=0, autosave=1, delay=0, autoreboot=0
m.mav.command_long_send(m.target_system, m.target_component, 42424, 0, 0, 0, 1, 0, 0, 0, 0)
t0, lastpct = time.time(), -10
while time.time() - t0 < 240:
    msg = m.recv_match(type=['MAG_CAL_PROGRESS', 'MAG_CAL_REPORT', 'STATUSTEXT', 'COMMAND_ACK'], blocking=True, timeout=1)
    if not msg: continue
    t = msg.get_type()
    if t == 'COMMAND_ACK' and msg.command == 42424: print('start ack', msg.result, flush=True)
    elif t == 'STATUSTEXT' and 'PreArm' not in msg.text: print(f't={time.time()-t0:.0f}s FC: {msg.text}', flush=True)
    elif t == 'MAG_CAL_PROGRESS' and msg.completion_pct >= lastpct + 10:
        lastpct = msg.completion_pct; print(f't={time.time()-t0:.0f}s progress {msg.completion_pct}%', flush=True)
    elif t == 'MAG_CAL_REPORT':
        d = msg.to_dict(); d.pop('mavpackettype'); print('REPORT', d, flush=True); break
else:
    print('RESULT: TIMEOUT', flush=True)
    m.mav.command_long_send(m.target_system, m.target_component, 42426, 0, 0, 0, 0, 0, 0, 0, 0)  # cancel
