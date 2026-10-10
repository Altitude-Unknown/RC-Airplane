from pymavlink import mavutil
from pathlib import Path
import json,time
m=mavutil.mavlink_connection('/dev/cu.usbmodem101',baud=115200);h=m.wait_heartbeat(timeout=10)
assert h and not h.base_mode & 128
names=['COMPASS_ENABLE','GPS1_TYPE','LOG_BACKEND_TYPE','ARMING_SKIPCHK','SERIAL2_PROTOCOL']
before={}
for name in names:
 m.mav.param_request_read_send(m.target_system,m.target_component,name.encode(),-1)
 end=time.time()+4
 while time.time()<end:
  p=m.recv_match(type='PARAM_VALUE',blocking=True,timeout=.3)
  if p and p.param_id==name:before[name]={'value':p.param_value,'type':p.param_type};break
assert len(before)==len(names),before
path=Path('RC-Airplane/ArduPilot-PCB/bringup-v2/servo-enabled/sbus')
(path/'hardware-parameters-before.json').write_text(json.dumps(before,indent=2))
after={}
for name in names[:3]:
 m.mav.param_set_send(m.target_system,m.target_component,name.encode(),0,before[name]['type'])
 end=time.time()+5
 while time.time()<end:
  p=m.recv_match(type='PARAM_VALUE',blocking=True,timeout=.3)
  if p and p.param_id==name and p.param_value==0:after[name]=p.param_value;break
 else:raise RuntimeError('Write unconfirmed: '+name)
(path/'hardware-parameters-applied.json').write_text(json.dumps(after,indent=2))
print('Verified parameter changes',after,'arming checks preserved',before['ARMING_SKIPCHK'],flush=True)
m.mav.command_long_send(m.target_system,m.target_component,mavutil.mavlink.MAV_CMD_PREFLIGHT_REBOOT_SHUTDOWN,0,1,0,0,0,0,0,0);m.close()
