import time,json
from pathlib import Path
from pymavlink import mavutil
out=Path(__file__).parent
c=mavutil.mavlink_connection('/dev/cu.usbmodem101',baud=115200,source_system=255,source_component=190)
result={'rc':[],'heartbeats':[],'status':[]}
try:
 hb=c.wait_heartbeat(timeout=6)
 assert hb and not hb.base_mode & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED
 c.mav.request_data_stream_send(c.target_system,c.target_component,mavutil.mavlink.MAV_DATA_STREAM_RC_CHANNELS,20,1)
 start=time.monotonic();lastBeat=0;lastMode=None
 print('Recording FBWA interlock check for 90 seconds.',flush=True)
 while time.monotonic()-start<90 and not (out/'fbwa-stop').exists():
  t=time.monotonic()-start
  if t-lastBeat>=1:
   c.mav.heartbeat_send(mavutil.mavlink.MAV_TYPE_GCS,mavutil.mavlink.MAV_AUTOPILOT_INVALID,0,0,mavutil.mavlink.MAV_STATE_ACTIVE);lastBeat=t
  m=c.recv_match(blocking=True,timeout=.2)
  if not m:continue
  d={'t':round(t,3),**m.to_dict()}
  if m.get_type()=='RC_CHANNELS':result['rc'].append(d)
  elif m.get_type()=='HEARTBEAT':
   result['heartbeats'].append(d)
   if m.custom_mode!=lastMode:print('FC mode:',m.custom_mode,flush=True);lastMode=m.custom_mode
  elif m.get_type()=='STATUSTEXT':result['status'].append(d);print('FC:',m.text,flush=True)
finally:
 c.close()
 (out/'fbwa-interlock-test.json').write_text(json.dumps(result,indent=2)+'\n')
 print('FBWA capture saved.',flush=True)
