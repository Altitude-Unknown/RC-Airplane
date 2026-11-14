"""Read-only Tx Config Mode snapshot: INFO, header, all models, full storage.

Usage: python read_tx.py <tag>   (writes tx-<tag>.json and tx-<tag>.storage.bin)
No WRITE command is ever sent.
"""
import sys, json, hashlib
from pathlib import Path
from serial.tools import list_ports
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from fram_gui_models import SerialWorker, ModelsStore

out = Path(__file__).parent
tag = sys.argv[1]
SERIAL = '89CB5B3050304C59502E3120FF101E44'
ports = [p for p in list_ports.comports()
         if p.product == 'Altitude RC TX M0' and p.serial_number == SERIAL]
assert len(ports) == 1, 'Connect the original TX M0 in Config Mode'
storage_path = out / f'tx-{tag}.storage.bin'
assert not storage_path.exists(), 'Refusing to overwrite an existing snapshot'
w = SerialWorker()
try:
    w.open(ports[0].device)
    info = w.device_info
    size = info.get('fram_size', 32768)
    store = ModelsStore(w)
    header = store.read_header()
    storage = b''.join(w.cmd_read(a, 64) for a in range(0, size, 64))
    again = b''.join(w.cmd_read(a, 64) for a in range(0, size, 64))
    assert storage == again, 'Two storage reads differ'
    used = header['used_bitmap']
    models = {}
    for slot in range(header['total_slots']):
        if used & (1 << slot):
            models[slot] = store.read_model(slot)
    storage_path.write_bytes(storage)
    record = {'port': ports[0].device, 'serial': SERIAL, 'info': info, 'header': header,
              'models': models, 'storage_bytes': len(storage),
              'storage_sha256': hashlib.sha256(storage).hexdigest()}
    (out / f'tx-{tag}.json').write_text(json.dumps(record, indent=2) + '\n')
    a = models[header['active_slot']]
    print(json.dumps({'info': info, 'active_slot': header['active_slot'], 'active_name': a['name'],
                      'crc_ok': a['crc_ok'], 'ch5_rate_mode': a['ch5_rate_mode'],
                      'rates': a['rates'], 'subtrim': a['subtrim'], 'd10': a['d10_function'],
                      'd7': a['d7_function'], 'bind_code': a['bind_code'],
                      'slots': {s: (m['name'], m['crc_ok']) for s, m in models.items()},
                      'storage_sha256': record['storage_sha256']}, indent=1))
finally:
    w.close()
