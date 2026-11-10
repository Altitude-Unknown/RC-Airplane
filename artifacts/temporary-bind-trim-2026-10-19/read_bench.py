import sys,time,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from fram_gui_models import SerialWorker,ModelsStore
from pymavlink import mavutil
out=Path(__file__).parent
w=SerialWorker()
try:
    w.open('/dev/cu.usbmodem11301')
    store=ModelsStore(w)
    hdr=store.read_header()
    raw=b''.join(w.cmd_read(a,min(64,32768-a)) for a in range(0,32768,64))
    model=store.read_model(hdr['active_slot'])
    (out/'tx-before.storage.bin').write_bytes(raw)
    (out/'tx-before.json').write_text(json.dumps({'info':w.device_info,'header':hdr,'model':model},indent=2)+'\n')
    print('TX backup:',json.dumps({'info':w.device_info,'active_slot':hdr['active_slot'],'crc_ok':model['crc_ok'],'ch5':model.get('d10_function'),'ch6':model.get('d7_function'),'rate_mode':model.get('ch5_rate_mode'),'subtrim':model['subtrim']}),flush=True)
finally:
    w.close()
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
