"""Back up the Tx M0 firmware from its UF2 bootloader, then copy the candidate."""
import sys, json, hashlib
from pathlib import Path
from serial.tools import list_ports
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import firmware_updater

out = Path(__file__).parent
SERIAL = '89CB5B3050304C59502E3120FF101E44'
ports = [p for p in list_ports.comports()
         if p.product == 'Altitude RC TX M0' and p.serial_number == SERIAL]
assert len(ports) == 1, 'Expected the original TX M0'
assert (out / 'tx-before.storage.bin').exists(), 'Back up model memory first'
backup_path = out / 'tx-before-firmware.uf2'
assert not backup_path.exists(), 'Preserve the existing firmware backup'
image = out / 'altitude-tx-v3-bind-trim-save.uf2'
expected = json.loads((out / 'candidate.json').read_text())['uf2_sha256']
assert hashlib.sha256(image.read_bytes()).hexdigest() == expected, 'Candidate checksum mismatch'
mount = firmware_updater.enter_samd_uf2(ports[0].device, timeout=20)
info = (mount / 'INFO_UF2.TXT').read_text()
print('Bootloader:', info, flush=True)
assert 'TX M0' in info and 'SAMD21' in info, 'Wrong bootloader identity'
backup = (mount / 'CURRENT.UF2').read_bytes()
assert len(backup) >= 262144 and len(backup) % 512 == 0
backup_path.write_bytes(backup)
result = {'serial': SERIAL, 'port': ports[0].device, 'bootloader': info,
          'firmware_backup_sha256': hashlib.sha256(backup).hexdigest(),
          'firmware_backup_bytes': len(backup), 'candidate_sha256': expected}
firmware_updater.flash_samd_uf2(image, mount)
result['write_completed'] = True
(out / 'tx-install.json').write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps(result, indent=1), flush=True)
