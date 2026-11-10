"""Execute production C++ mixers on the host, without a connected transmitter."""
import pathlib
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent

class AircraftMixTests(unittest.TestCase):
    def test_production_mixers(self):
        for folder in ('tx_firmware', 'PCB/TxV3/TxV3_Full_M0'):
            header = (ROOT/folder/'tx_config.h').read_text()
            structs = header[header.index('// 32-byte header'):header.index('namespace TXCF')]
            source = (ROOT/folder/'tx_config.cpp').read_text()
            funcs = source[source.index('int16_t channelToUs'):source.index('// ---------- Raw')]
            harness = r'''
#include <stdint.h>
#include <cmath>
#include <cassert>
#define constrain(x,l,h) ((x)<(l)?(l):((x)>(h)?(h):(x)))
''' + structs + r'''
float applyExpo(float x, int8_t e) { return x*(1-e/100.0f)+x*x*x*(e/100.0f); }
''' + funcs + r'''
int main() {
 txcf_model_v1_t m{};
 for(int i=0;i<4;i++){m.rates_pct[i]=100;m.endpoints_us[i][0]=1000;m.endpoints_us[i][1]=2000;}
 uint16_t o[4];
 controlsToUs(.2,.4,.6,-1,m,false,o);
 assert(o[0]==1600 && o[1]==1700 && o[2]==1800 && o[3]==1000);
 for(int type=1;type<=2;type++) {
  m.reserved[3]=type; int ch=type==1?0:1;
  controlsToUs(0,0,1,-1,m,false,o);
  assert(o[ch]==2000 && o[2]==2000 && o[3]==1000);
  controlsToUs(type==1?1:0,type==2?1:0,0,-1,m,false,o);
  assert(o[ch]==2000 && o[2]==1000);
  controlsToUs(1,1,1,-1,m,false,o);
  assert(o[ch]==2000 && o[2]==1500);
  m.subtrim_us[2]=100;
  controlsToUs(0,0,0,-1,m,false,o);
  assert(o[ch]==1600 && o[2]==1600);
  m.subtrim_us[2]=0;
  m.reserved[0]=1<<ch;
  controlsToUs(0,0,1,-1,m,false,o);
  assert(o[ch]==1000 && o[2]==2000);
  m.reserved[0]=0;
  m.rates_pct[2]=50; m.expo_pct[2]=100;
  controlsToUs(0,0,.5,-1,m,false,o);
  assert(o[ch]==1531 && o[2]==1531);
  m.rates_pct[2]=100; m.expo_pct[2]=0;
 }
 // Axis reversal changes yaw only, with both physical output reversals set.
 m.reserved[3]=1; m.reserved[0]=5;
 uint16_t baseline[4];
 controlsToUs(0,0,.5,-1,m,false,baseline);
 m.reserved[4]=1;
 controlsToUs(0,0,.5,-1,m,false,o);
 assert(o[0]==baseline[0] && o[2]==baseline[2]);
 controlsToUs(1,0,0,-1,m,false,o);
 assert(o[0]==2000 && o[2]==1000);
 m.subtrim_us[0]=100;
 controlsToUs(0,0,0,-1,m,false,o);
 assert(o[0]==1600 && o[2]==1400);
 m.subtrim_us[0]=0;
 // The option is ignored for flying wings and conventional models.
 m.reserved[3]=2; m.reserved[0]=0;
 controlsToUs(0,1,0,-1,m,false,o);
 assert(o[1]==2000 && o[2]==1000);
 m.reserved[3]=255;
 controlsToUs(.2,.4,.6,-1,m,false,o);
 assert(o[0]==1600 && o[1]==1700 && o[2]==1800);
}
'''
            with tempfile.TemporaryDirectory() as tmp:
                cpp = pathlib.Path(tmp)/'mix.cpp'
                cpp.write_text(harness)
                exe = pathlib.Path(tmp)/'mix'
                subprocess.run(['c++','-std=c++11',str(cpp),'-o',str(exe)],check=True)
                subprocess.run([str(exe)],check=True)

if __name__ == '__main__':
    unittest.main()
