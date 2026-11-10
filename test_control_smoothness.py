"""Run the production receiver output decision on the host, without hardware."""
import pathlib
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent


class ControlSmoothnessTests(unittest.TestCase):
    def test_surface_resolution_and_unchanged_throttle_policy(self):
        source = (ROOT / 'rx_firmware/rx_firmware.ino').read_text()
        constants = source[source.index('const uint16_t RC_MIN ='):
                           source.index('// ------------------------------\n// Failsafe')]
        helper = source[source.index('static inline void setServoIfChanged'):
                        source.index('// Create one manual servo pulse.')]
        output = source[source.index('    // ---------- Smoothing ----------'):
                        source.index('    // Auxiliary switches fail low')]
        program = r'''
#include <stdint.h>
#include <cstdlib>
#include <cassert>
''' + constants + helper + r'''
uint16_t cur_t, cur_a, cur_e, cur_r;
uint16_t filt_t, filt_a, filt_e, filt_r;
uint16_t des_t, des_a, des_e, des_r;
bool armed, escMode;
void tick() {
''' + output + r'''
}
int main() {
  // Every single-us surface target must propagate on the very next frame,
  // both directions and under every arming/ESC gate combination.
  for (int mode=0; mode<4; ++mode) {
    armed = mode & 1; escMode = mode & 2;
    cur_a=cur_e=cur_r=filt_a=filt_e=filt_r=1500;
    for (int direction : {-1, 1}) {
      for (int i=0; i<=1000; ++i) {
        des_a = direction > 0 ? 1000+i : 2000-i;
        des_e = 3000-des_a; des_r=des_a;
        des_t=1000; cur_t=filt_t=1000;
        tick();
        assert(cur_a==des_a && cur_e==des_e && cur_r==des_r);
      }
    }
    // Full current/target sweep checks the legacy throttle deadband and gate,
    // including RC_MIN and the near-minimum 1–2 us legacy hold behavior.
    for (int current=1000; current<=2000; ++current) {
      for (int target=1000; target<=2000; ++target) {
        cur_t=filt_t=current; des_t=target;
        int gated=(armed || escMode) ? target : 1000;
        int expected=abs(gated-current)>2 ? gated : current;
        tick(); assert(cur_t==expected);
      }
    }
  }
  // A failsafe/trim target 1–2 us away must be reached exactly, not held short.
  armed=escMode=false;
  cur_a=filt_a=1499; cur_e=filt_e=1502; cur_r=filt_r=1498;
  des_a=des_e=des_r=1500; des_t=1000; cur_t=filt_t=1000;
  tick();
  assert(cur_a==1500 && cur_e==1500 && cur_r==1500 && cur_t==1000);
}
'''
        # initializer_list supports the two sweep directions in the C++ harness.
        program = '#include <initializer_list>\n' + program
        with tempfile.TemporaryDirectory() as folder:
            cpp = pathlib.Path(folder) / 'outputs.cpp'
            exe = pathlib.Path(folder) / 'outputs'
            cpp.write_text(program)
            subprocess.run(['c++', '-std=c++11', '-O2', str(cpp), '-o', str(exe)],
                           check=True)
            subprocess.run([str(exe)], check=True)


if __name__ == '__main__':
    unittest.main()
