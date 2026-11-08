# Run ArduPilot level (AHRS trim) calibration: MAV_CMD_PREFLIGHT_CALIBRATION param5=2.
import sys, time
from pymavlink import mavutil
m = mavutil.mavlink_connection(sys.argv[1], baud=115200)
hb = m.wait_heartbeat(timeout=20)
if hb.base_mode & 128: sys.exit('ARMED - refusing')
def rd(p):
    m.mav.param_request_read_send(m.target_system, m.target_component, p.encode(), -1)
    msg = m.recv_match(type='PARAM_VALUE', blocking=True, timeout=3, condition=f'PARAM_VALUE.param_id=="{p}"')
    return msg.param_value if msg else None
print('before AHRS_TRIM_X', rd('AHRS_TRIM_X'), 'AHRS_TRIM_Y', rd('AHRS_TRIM_Y'))
m.mav.command_long_send(m.target_system, m.target_component, 241, 0, 0, 0, 0, 0, 2, 0, 0)
t0 = time.time()
while time.time() - t0 < 30:
    msg = m.recv_match(type=['COMMAND_ACK','STATUSTEXT'], blocking=True, timeout=1)
    if not msg: continue
    if msg.get_type() == 'STATUSTEXT': print('MSG', msg.text)
    elif msg.command == 241: print('ACK result', msg.result, '(0=accepted)'); break
time.sleep(1)
print('after  AHRS_TRIM_X', rd('AHRS_TRIM_X'), 'AHRS_TRIM_Y', rd('AHRS_TRIM_Y'))
