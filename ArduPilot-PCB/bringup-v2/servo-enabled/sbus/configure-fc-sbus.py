import json,time
from pymavlink import mavutil
m=mavutil.mavlink_connection('/dev/cu.usbmodem101',baud=115200)
h=m.wait_heartbeat(timeout=15)
assert h and not h.base_mode & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED
names=['SERIAL2_PROTOCOL','SERIAL2_OPTIONS','RCMAP_ROLL','RCMAP_PITCH','RCMAP_THROTTLE','RCMAP_YAW','RC_OPTIONS']
values={}
for name in names:
 m.mav.param_request_read_send(m.target_system,m.target_component,name.encode(),-1)
 end=time.time()+3
 while time.time()<end:
  msg=m.recv_match(type='PARAM_VALUE',blocking=True,timeout=.3)
  if msg and msg.param_id==name: values[name]=msg.param_value;break
print('before',values,flush=True)
assert len(values)==len(names)
json.dump(values,open('RC-Airplane/ArduPilot-PCB/bringup-v2/servo-enabled/sbus/parameters-before.json','w'),indent=2)
assert [values[n] for n in names[2:6]]==[1,2,3,4], 'Unexpected input mapping; review before modifying'
m.mav.param_set_send(m.target_system,m.target_component,b'SERIAL2_PROTOCOL',23,mavutil.mavlink.MAV_PARAM_TYPE_INT8)
end=time.time()+5
while time.time()<end:
 msg=m.recv_match(type='PARAM_VALUE',blocking=True,timeout=.3)
 if msg and msg.param_id=='SERIAL2_PROTOCOL' and msg.param_value==23:break
else:raise RuntimeError('SERIAL2_PROTOCOL write not confirmed')
print('SERIAL2_PROTOCOL=23 confirmed; rebooting disarmed FC',flush=True)
m.mav.command_long_send(m.target_system,m.target_component,mavutil.mavlink.MAV_CMD_PREFLIGHT_REBOOT_SHUTDOWN,0,1,0,0,0,0,0,0)
m.close()
