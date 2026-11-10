import sys,json,hashlib,shutil,time
from pathlib import Path
from serial.tools import list_ports
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
import firmware_updater
out=Path(__file__).parent
serial_number='89CB5B3050304C59502E3120FF101E44'
ports=[p for p in list_ports.comports() if p.product=='Altitude RC TX M0' and p.serial_number==serial_number]
assert len(ports)==1, 'Expected original TX M0 not found'
assert not (out/'tx-before-firmware.uf2').exists(), 'Preserve existing firmware backup'
image=out/'altitude-tx-v3-TEMP-bind-trim-save.uf2'
expected=json.loads((out/'candidate.json').read_text())['uf2_sha256']
assert hashlib.sha256(image.read_bytes()).hexdigest()==expected
mount=firmware_updater.enter_samd_uf2(ports[0].device,timeout=20)
info=(mount/'INFO_UF2.TXT').read_text()
print('Bootloader:',info,flush=True)
assert 'TX M0' in info and 'SAMD21' in info, 'Wrong bootloader identity'
backup=(mount/'CURRENT.UF2').read_bytes()
assert len(backup)>=262144 and len(backup)%512==0
(out/'tx-before-firmware.uf2').write_bytes(backup)
(out/'bootloader-info.txt').write_text(info)
result={'serial':serial_number,'port':ports[0].device,'bootloader':info,
        'firmware_backup_sha256':hashlib.sha256(backup).hexdigest(),
        'firmware_backup_bytes':len(backup),'candidate_sha256':expected}
firmware_updater.flash_samd_uf2(image,mount)
result['write_completed']=True
(out/'tx-install.json').write_text(json.dumps(result,indent=2)+'\n')
print('TX firmware backed up and temporary UF2 copied. Await re-enumeration.',flush=True)
