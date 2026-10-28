import argparse,json,time
from pathlib import Path
from serial.tools import list_ports
from pymavlink import mavutil
p=argparse.ArgumentParser()
p.add_argument('action',choices=['disable','capture','restore'])
a=p.parse_args()
out=Path(__file__).parent
ports=[p for p in list_ports.comports() if p.serial_number=='2F0051000C51343034383933']
assert len(ports)==1,'Expected FC not connected'
c=mavutil.mavlink_connection(ports[0].device,baud=115200,source_system=255,source_component=190)
last_hb=0

def beat():
 global last_hb
 if time.monotonic()-last_hb>1:
  c.mav.heartbeat_send(mavutil.mavlink.MAV_TYPE_GCS,mavutil.mavlink.MAV_AUTOPILOT_INVALID,0,0,mavutil.mavlink.MAV_STATE_ACTIVE)
  last_hb=time.monotonic()

def getparam(name):
 for attempt in range(3):
  c.mav.param_request_read_send(c.target_system,c.target_component,name.encode(),-1)
  end=time.monotonic()+2
  while time.monotonic()<end:
   beat()
   m=c.recv_match(type='PARAM_VALUE',blocking=True,timeout=.2)
   if m and m.param_id==name:return m.param_value
 raise RuntimeError('No parameter '+name)

def setparam(name,value):
 c.mav.param_set_send(c.target_system,c.target_component,name.encode(),float(value),mavutil.mavlink.MAV_PARAM_TYPE_INT32)
 actual=getparam(name)
 assert actual==value,(name,actual,value)

try:
 hb=c.wait_heartbeat(timeout=6)
 assert hb and hb.type==1 and not hb.base_mode & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED,'FC must be disarmed'
 names=[f'RC{i}_{s}' for i in range(1,5) for s in ['MIN','MAX','TRIM']]+[f'SERVO{i}_TRIM' for i in range(1,7)]
 if a.action=='disable':
  assert not (out/'fc-trim-baseline.json').exists(),'Preserve baseline'
  baseline={n:getparam(n) for n in names+['RC6_OPTION']}
  assert baseline['RC6_OPTION']==155
  (out/'fc-trim-baseline.json').write_text(json.dumps(baseline,indent=2)+'\n')
  setparam('RC6_OPTION',0)
  print('RC6_OPTION verified 0; trim saving disabled for pulse test.',flush=True)
 elif a.action=='restore':
  assert getparam('RC6_OPTION')==0
  actual={n:getparam(n) for n in names}
  baseline=json.loads((out/'fc-trim-baseline.json').read_text())
  changes={n:[baseline[n],actual[n]] for n in names if baseline[n]!=actual[n]}
  assert not changes,changes
  # Observe a fresh CH6-low sample before re-enabling the action.
  c.mav.request_data_stream_send(c.target_system,c.target_component,mavutil.mavlink.MAV_DATA_STREAM_RC_CHANNELS,10,1)
  deadline=time.monotonic()+6
  low=False
  while time.monotonic()<deadline:
   beat()
   m=c.recv_match(type='RC_CHANNELS',blocking=True,timeout=.3)
   if m and m.chan6_raw==1000 and m.rssi!=0:
    low=True;break
  assert low,'No fresh CH6 low: leave option disabled until verified'
  setparam('RC6_OPTION',155)
  (out/'fc-restored.json').write_text(json.dumps({'RC6_OPTION':getparam('RC6_OPTION'),'trims_unchanged':True,'trims':actual},indent=2)+'\n')
  print('RC6_OPTION restored and verified 155; RC/servo trims unchanged.',flush=True)
 else:
  assert getparam('RC6_OPTION')==0,'Disable action before pulse measurement'
  c.mav.request_data_stream_send(c.target_system,c.target_component,mavutil.mavlink.MAV_DATA_STREAM_RC_CHANNELS,20,1)
  c.mav.request_data_stream_send(c.target_system,c.target_component,mavutil.mavlink.MAV_DATA_STREAM_EXTENDED_STATUS,2,1)
  result={'RC6_OPTION_during_test':0,'rc':[],'heartbeats':[],'status':[]}
  start=time.monotonic(); previous=None
  print('Recording CH5/CH6 for up to 180 seconds.',flush=True)
  try:
   while time.monotonic()-start<180 and not (out/'capture-stop').exists():
    beat()
    m=c.recv_match(blocking=True,timeout=.2)
    if m is None:continue
    d=m.to_dict();t=round(time.monotonic()-start,3)
    if m.get_type()=='RC_CHANNELS':
     result['rc'].append({'t':t,**d})
     pair=(m.chan5_raw,m.chan6_raw)
     if pair!=previous:
      print('t=',t,'CH5/CH6=',pair,flush=True);previous=pair
    elif m.get_type()=='HEARTBEAT':result['heartbeats'].append({'t':t,**d})
    elif m.get_type()=='STATUSTEXT':
     result['status'].append({'t':t,**d});print('FC:',m.text,flush=True)
  finally:
   (out/'channel-pulse-test.json').write_text(json.dumps(result,indent=2)+'\n')
  print('Capture saved; RC6_OPTION remains 0 pending restore.',flush=True)
finally:c.close()
