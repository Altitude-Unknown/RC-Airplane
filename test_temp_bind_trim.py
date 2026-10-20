"""Temporary V3 trim-save control: production state machine regression checks."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent

class TemporaryBindTrimTests(unittest.TestCase):
    def test_hold_pulse_release_mode_cancel_bounce_and_rollover(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'test.cpp'
            executable = Path(directory) / 'test'
            source.write_text('#include "temp_bind_trim.h"\n#include <cassert>\nusing TempBindTrim::Button;\nint main() {\n Button b;\n // held at boot cannot trigger\n for(unsigned t=0;t<4000;t+=10) assert(!b.update(true,true,t));\n b.update(false,true,4000); assert(!b.update(false,true,4025));\n b.update(true,true,4100); assert(!b.update(true,true,4125));\n assert(!b.update(true,true,6124)); assert(b.update(true,true,6125));\n assert(b.update(true,true,6624)); assert(!b.update(true,true,6625));\n assert(!b.update(true,true,10000));\n // release rearms; short press cancels\n b.update(false,true,10010); b.update(false,true,10035);\n b.update(true,true,10100); b.update(true,true,10125);\n b.update(false,true,11000); assert(!b.update(false,true,11025));\n assert(!b.update(false,true,15000));\n // mode change must cancel, even during pulse; held on mode entry stays inert\n b.update(true,false,15010); assert(!b.update(true,true,18000));\n assert(!b.update(true,true,22000));\n b.update(false,true,22010); b.update(false,true,22035);\n b.update(true,true,22100); b.update(true,true,22125);\n assert(b.update(true,true,24125)); assert(!b.update(true,false,24126));\n assert(!b.update(true,true,30000));\n // debounce bounce and millis rollover\n Button c; c.update(false,true,0xffffff00U);\n c.update(true,true,0xffffff10U); c.update(false,true,0xffffff15U);\n c.update(true,true,0xffffff20U); assert(!c.update(true,true,0xffffff38U));\n c.update(true,true,0xffffff39U);\n assert(!c.update(true,true,(uint32_t)(0xffffff39U+1999U)));\n assert(c.update(true,true,(uint32_t)(0xffffff39U+2000U)));\n assert(!c.update(true,true,(uint32_t)(0xffffff39U+2500U)));\n}\n')
            subprocess.run(['c++', '-std=c++11', '-I',
                            str(ROOT / 'PCB/TxV3/TxV3_Full_M0'),
                            str(source), '-o', str(executable)], check=True)
            subprocess.run([str(executable)], check=True)

if __name__ == '__main__':
    unittest.main()
