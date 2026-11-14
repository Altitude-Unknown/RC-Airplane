# Read-only: run the pre-arm checks and report status, GPS, sensors, mode.
import sys, time
from pymavlink import mavutil
m = mavutil.mavlink_connection(sys.argv[1], baud=115200); m.wait_heartbeat(timeout=20)
m.mav.request_data_stream_send(m.target_system, m.target_component, 0, 4, 1)
m.mav.command_long_send(m.target_system, m.target_component, 401, 0, 0,0,0,0,0,0,0)  # RUN_PREARM_CHECKS
t = time.time(); texts=[]; gps=None; sys_s=None; ek=None; rc=None
while time.time() - t < float(sys.argv[2] if len(sys.argv)>2 else 20):
    x = m.recv_match(blocking=True, timeout=1)
    if not x: continue
    ty = x.get_type()
    if ty == 'STATUSTEXT' and x.text not in texts: texts.append(x.text); print('MSG', x.text, flush=True)
    elif ty == 'GPS_RAW_INT': gps = x
    elif ty == 'SYS_STATUS': sys_s = x
    elif ty == 'EKF_STATUS_REPORT': ek = x
    elif ty == 'RC_CHANNELS': rc = x
    elif ty == 'COMMAND_ACK' and x.command == 401: print('ACK prearm', x.result)
print('mode', m.flightmode, 'armed', m.motors_armed())
if gps: print(f'GPS fix_type {gps.fix_type} sats {gps.satellites_visible} hdop {gps.eph/100:.2f} hacc {getattr(gps,"h_acc",0)/1000:.1f} m')
if sys_s:
    bad = sys_s.onboard_control_sensors_present & sys_s.onboard_control_sensors_enabled & ~sys_s.onboard_control_sensors_health
    names = {v.name: k for k, v in mavutil.mavlink.enums['MAV_SYS_STATUS_SENSOR'].items()}
    print('unhealthy:', [v.name for k, v in mavutil.mavlink.enums['MAV_SYS_STATUS_SENSOR'].items() if bad & k] or 'none')
    print(f'battery {sys_s.voltage_battery/1000:.2f} V')
if ek: print(f'EKF flags 0x{ek.flags:x} vel {ek.velocity_variance:.2f} pos {ek.pos_horiz_variance:.2f} compass {ek.compass_variance:.2f}')
if rc: print('RC', [getattr(rc, f"chan{i}_raw") for i in range(1, 6)], 'rssi', rc.rssi)
