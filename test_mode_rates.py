"""Exercise CH5 rate profiles using production button, mixer and model codecs."""
import json
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest

from fram_gui_models import MODEL_FMT, ModelsStore, button_config
from test_gui_model_codec import MemoryWorker

ROOT = Path(__file__).resolve().parent
TX = ROOT / 'PCB/TxV3/TxV3_Full_M0'


class ModeRateTests(unittest.TestCase):
    def model(self):
        return dict(name='Mode rates', bind_code=7741, rates=[50, 30, 80, 60],
                    expo=[40, 40, 40, 0], subtrim=[-35, 70, -75, 0],
                    endpoints=[[1000, 2000] for _ in range(4)],
                    active_rates=False, dr_switch=0, d10_function=2,
                    d7_function=0, ch5_rate_mode=1)

    def test_storage_and_json_round_trip_preserve_selected_controls(self):
        worker = MemoryWorker()
        worker.device_info = {'button_channels': True, 'mode_rates': True, 'radio_role': 'MASTER'}
        store = ModelsStore(worker)
        for polarity in (0, 1, 2):
            for other_aux in (0, 1, 2):
                model = self.model()
                model.update(ch5_rate_mode=polarity, d7_function=other_aux)
                model = json.loads(json.dumps(model))
                store.write_model(0, model)
                decoded = store.read_model(0)
                for field in ('rates', 'expo', 'subtrim', 'endpoints', 'active_rates',
                              'ch5_rate_mode', 'd10_function', 'd7_function'):
                    self.assertEqual(decoded[field], model[field])
                self.assertTrue(decoded['crc_ok'])
                raw = worker.cmd_read(store.slot_addr(0), 60)
                self.assertEqual(struct.unpack(MODEL_FMT, raw)[24][5],
                                 2 | (other_aux << 2) | (polarity << 4))
        legacy = self.model()
        del legacy['ch5_rate_mode']
        store.write_model(0, legacy)
        self.assertEqual(store.read_model(0)['ch5_rate_mode'], 0)

    def test_invalid_assignments_and_old_firmware_are_rejected_before_write(self):
        worker = MemoryWorker()
        worker.device_info = {'button_channels': True, 'radio_role': 'MASTER'}
        store = ModelsStore(worker)
        before = bytes(worker.data)
        with self.assertRaisesRegex(ValueError, 'mode-linked rates'):
            store.write_model(0, self.model())
        self.assertEqual(bytes(worker.data), before)
        for invalid in (-1, 3, '1', True):
            model = self.model()
            model['ch5_rate_mode'] = invalid
            with self.assertRaises(ValueError):
                button_config(model)
        model = self.model()
        model['d10_function'] = 0
        with self.assertRaisesRegex(ValueError, 'Trainer'):
            button_config(model)
        worker.device_info.update(mode_rates=True, radio_role='STUDENT')
        with self.assertRaisesRegex(ValueError, 'Student'):
            store.write_model(0, self.model())
        self.assertEqual(bytes(worker.data), before)

    def test_production_rate_mapping_and_button_transitions(self):
        header = (TX / 'tx_config.h').read_text()
        structs = header[header.index('// 32-byte header'):header.index('namespace TXCF')]
        source = (TX / 'tx_config.cpp').read_text()
        mixers = source[source.index('int16_t channelToUs'):source.index('// ---------- Raw')]
        harness = r'''
#include "mode_rates.h"
#include <cassert>
#include <cmath>
#include <cstring>
#define constrain(x,l,h) ((x)<(l)?(l):((x)>(h)?(h):(x)))
''' + structs + r'''
float applyExpo(float x, int8_t e) { return x*(1-e/100.0f)+x*x*x*(e/100.0f); }
''' + mixers + r'''
int main() {
  using namespace AuxChannels;
  const uint8_t lowFull = 2 | (1 << 4), highFull = 2 | (2 << 4);
  for (bool high : {false, true}) {
    uint8_t flags = encode(high, false);
    assert(ModeRates::fullSurfaces(lowFull, flags, false) == !high);
    assert(ModeRates::fullSurfaces(highFull, flags, false) == high);
    assert(!ModeRates::fullSurfaces(2, flags, false)); // existing models
    assert(!ModeRates::fullSurfaces(2 | (3 << 4), flags, false)); // invalid
    assert(!ModeRates::fullSurfaces(1 << 4, flags, false)); // trainer
    assert(!ModeRates::fullSurfaces(lowFull, flags, true)); // student
    assert(!ModeRates::fullSurfaces(lowFull, high ? CH5 : 0, false)); // unmarked
    assert(ModeRates::fullSurfaces(lowFull, encode(high, true), false) == !high);
  }
  // Toggle: low on reset, held at boot cannot toggle, then one action per press.
  Button button;
  bool high = button.update(true, 2, 0);
  assert(!high && ModeRates::fullSurfaces(lowFull, encode(high, false), false));
  assert(!button.update(true, 2, 100));
  button.update(false, 2, 200); button.update(false, 2, 225);
  button.update(true, 2, 300); high = button.update(true, 2, 325);
  assert(high && !ModeRates::fullSurfaces(lowFull, encode(high, false), false));
  assert(button.update(true, 2, 2000)); // holding cannot repeat
  button.update(false, 2, 2001); button.update(false, 2, 2026);
  button.update(true, 2, 2030); high = button.update(true, 2, 2055);
  assert(!high && ModeRates::fullSurfaces(lowFull, encode(high, false), false));
  Button momentary;
  momentary.update(false, 1, 25); momentary.update(true, 1, 30);
  assert(ModeRates::fullSurfaces(1 | (2 << 4), encode(momentary.update(true, 1, 55), false), false));
  momentary.update(false, 1, 60);
  assert(!ModeRates::fullSurfaces(1 | (2 << 4), encode(momentary.update(false, 1, 85), false), false));

  txcf_model_v1_t model{};
  const int rates[] = {50, 30, 80, 60};
  const int trims[] = {-35, 70, -75, 0};
  for (int ch = 0; ch < 4; ++ch) {
    model.rates_pct[ch] = rates[ch]; model.subtrim_us[ch] = trims[ch];
    model.expo_pct[ch] = ch == 3 ? 0 : 40;
    model.endpoints_us[ch][0] = 1000; model.endpoints_us[ch][1] = 2000;
  }
  model.reserved[0] = 5; // reverse yaw and pitch
  model.reserved[1] = 1; model.reserved[2] = 25; // coordinated mix
  for (int type = 0; type <= 2; ++type) {
    model.reserved[3] = type;
    auto original = model;
    auto full = model;
    for (int ch = 0; ch < 3; ++ch) full.rates_pct[ch] = 100;
    for (bool selectedHigh : {false, true}) {
      for (float x : {-1.0f, -.5f, 0.0f, .5f, 1.0f}) {
        uint16_t selected[4], assisted[4], expected[4], restored[4];
        controlsToUs(x, x, x, x, model, selectedHigh, selected);
        controlsToUsForMode(x, x, x, x, model, selectedHigh, true, assisted);
        controlsToUs(x, x, x, x, full, selectedHigh, expected);
        assert(memcmp(assisted, expected, sizeof(expected)) == 0);
        assert(assisted[3] == selected[3]); // throttle unchanged at every input
        controlsToUsForMode(x, x, x, x, model, selectedHigh, false, restored);
        assert(memcmp(restored, selected, sizeof(selected)) == 0);
        assert(memcmp(&model, &original, sizeof(model)) == 0); // no model mutation
      }
    }
  }
  // Concrete conventional output check with expo and trims retained.
  model.reserved[0] = model.reserved[1] = model.reserved[3] = 0;
  uint16_t manual[4], fbwa[4];
  controlsToUsForMode(1, 1, 1, -1, model, false, false, manual);
  controlsToUsForMode(1, 1, 1, -1, model, false, true, fbwa);
  assert(manual[0] == 1715 && manual[1] == 1720 && manual[2] == 1825);
  assert(fbwa[0] == 1965 && fbwa[1] == 2000 && fbwa[2] == 1925);
  assert(manual[3] == 1200 && fbwa[3] == 1200);
  controlsToUsForMode(0, .5, 0, -1, model, false, true, fbwa);
  assert(fbwa[1] == 1745); // expo40: .5 -> .35, not linear .5
}
'''
        harness = harness.replace('#include <cstring>', '#include <cstring>\n#include <initializer_list>')
        with tempfile.TemporaryDirectory() as directory:
            cpp = Path(directory) / 'mode_rates.cpp'
            binary = Path(directory) / 'mode_rates'
            cpp.write_text(harness)
            subprocess.run(['c++', '-std=c++11', '-Wall', '-Wextra', '-Werror',
                            '-I', str(TX), str(cpp), '-o', str(binary)], check=True)
            subprocess.run([str(binary)], check=True)


if __name__ == '__main__':
    unittest.main()
