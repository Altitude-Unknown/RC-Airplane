"""Restore only the active Research model's FBWA rate selector and CRC."""
import sys,json,struct,hashlib
from pathlib import Path
from serial.tools import list_ports
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from fram_gui_models import SerialWorker,ModelsStore,crc16_ccitt
out=Path(__file__).parent
ports=[p for p in list_ports.comports() if p.product=='Altitude RC TX M0' and p.serial_number=='89CB5B3050304C59502E3120FF101E44']
assert len(ports)==1,'Connect original TX M0 in Config Mode'
w=SerialWorker()
try:
 w.open(ports[0].device)
 assert w.device_info.get('mode_rates') and w.device_info.get('radio_role')=='MASTER'
 assert w.device_info.get('temp_bind_trim_save'),'Expected temporary Bind feature firmware'
 store=ModelsStore(w);header=store.read_header();slot=header['active_slot']
 model=store.read_model(slot)
 assert slot==0 and model['name']=='Research' and model['crc_ok'], 'Unexpected active model'
 assert model['d10_function']==2,'Expected CH5 toggle'
 before=b''.join(w.cmd_read(a,64) for a in range(0,32768,64))
 with (out/'tx-before.storage.bin').open('xb') as f:f.write(before)
 (out/'tx-before.json').write_text(json.dumps({'info':w.device_info,'header':header,'model':model},indent=2)+'\n')
 addr=store.slot_addr(slot)
 raw=bytearray(before[addr:addr+64])
 raw[57]=(raw[57]&~0x30)|0x10
 raw[58:60]=struct.pack('<H',crc16_ccitt(bytes(raw[:58])))
 expected=before[:addr]+bytes(raw)+before[addr+64:]
 changed=[i for i,(a,b) in enumerate(zip(before,expected)) if a!=b]
 assert set(changed)<=set(addr+i for i in (57,58,59))
 if changed:w.cmd_write(addr,bytes(raw))
 after=b''.join(w.cmd_read(a,64) for a in range(0,32768,64))
 (out/'tx-after.storage.bin').write_bytes(after)
 assert after==expected,'Readback mismatch'
 updated=store.read_model(slot)
 assert updated['crc_ok'] and updated['ch5_rate_mode']==1
 assert all(updated[k]==model[k] for k in model if k not in ('ch5_rate_mode','crc_ok'))
 record={'info':w.device_info,'active_slot':slot,'before_model':model,'after_model':updated,'changed_storage_offsets':changed,'all_other_storage_bytes_identical':True,'storage_before_sha256':hashlib.sha256(before).hexdigest(),'storage_after_sha256':hashlib.sha256(after).hexdigest()}
 (out/'verification.json').write_text(json.dumps(record,indent=2)+'\n')
 print(json.dumps({'FBWA_CH5_low_full_rates':True,'manual_rates':updated['rates'],'subtrim':updated['subtrim'],'temporary_bind_feature':w.device_info['temp_bind_trim_save'],'crc_ok':updated['crc_ok'],'changed_storage_offsets':changed,'all_other_storage_bytes_identical':True},indent=2))
finally:w.close()
