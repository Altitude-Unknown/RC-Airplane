import sys,time,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from fram_gui_models import SerialWorker,ModelsStore
from pymavlink import mavutil
out=Path(__file__).parent
c=mavutil.mavlink_connection('/dev/cu.usbmodem101',baud=115200)
try:
    hb=c.wait_heartbeat(timeout=8)
    if hb is None: raise RuntimeError('No FC heartbeat')
    print('FC heartbeat:',hb.to_dict(),flush=True)
    names=['RC6_OPTION','FLTMODE_CH','FLTMODE1','FLTMODE2','FLTMODE3','FLTMODE4','FLTMODE5','FLTMODE6','RCMAP_ROLL','RCMAP_PITCH','RCMAP_THROTTLE','RCMAP_YAW','TRIM_AUTO','SERVO_AUTO_TRIM']
    result={}
    for name in names:
        c.mav.param_request_read_send(c.target_system,c.target_component,name.encode(),-1)
        end=time.monotonic()+2
        while time.monotonic()<end:
            m=c.recv_match(type='PARAM_VALUE',blocking=True,timeout=.3)
            if m and m.param_id==name:
                result[name]=m.param_value; break
    (out/'fc-before-selected.json').write_text(json.dumps(result,indent=2)+'\n')
    print('FC selected parameters:',json.dumps(result),flush=True)
finally:
    c.close()
