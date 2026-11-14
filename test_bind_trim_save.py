"""Bind trim-save (CH7): transmitter state machine, gating, and receiver mapping."""
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent
TX = ROOT / 'PCB/TxV3/TxV3_Full_M0'


def run_cpp(code, include):
    with tempfile.TemporaryDirectory() as directory:
        source = Path(directory) / 'test.cpp'
        executable = Path(directory) / 'test'
        source.write_text(code)
        subprocess.run(['c++', '-std=c++11', '-Wall', '-Wextra', '-I', str(include),
                        str(source), '-o', str(executable)], check=True)
        subprocess.run([str(executable)], check=True)


class BindTrimSaveButtonTests(unittest.TestCase):
    def test_hold_pulse_release_inhibit_bounce_and_rollover(self):
        run_cpp(r'''
#include "bind_trim_save.h"
#include <cassert>
using BindTrimSave::Button;
int main() {
 static_assert(BindTrimSave::HOLD_MS == 1000, "1 s hold");
 static_assert(BindTrimSave::PULSE_MS == 500, "0.5 s pulse");
 Button b;
 // held at boot cannot trigger
 for(unsigned t=0;t<4000;t+=10) assert(!b.update(true,true,t));
 b.update(false,true,4000); assert(!b.update(false,true,4025));
 // press at 4100, debounced at 4125; fires exactly 1000 ms later
 b.update(true,true,4100); assert(!b.update(true,true,4125));
 assert(!b.update(true,true,5124)); assert(b.update(true,true,5125));
 // one 500 ms pulse, then low while still held
 assert(b.update(true,true,5624)); assert(!b.update(true,true,5625));
 assert(!b.update(true,true,10000));
 // release rearms; a short press (under 1 s) sends nothing
 b.update(false,true,10010); b.update(false,true,10035);
 b.update(true,true,10100); b.update(true,true,10125);
 b.update(false,true,10900); assert(!b.update(false,true,10925));
 assert(!b.update(false,true,15000));
 // inhibit cancels, even during a pulse; held through inhibit stays inert
 b.update(true,false,15010); assert(!b.update(true,true,18000));
 assert(!b.update(true,true,22000));
 b.update(false,true,22010); b.update(false,true,22035);
 b.update(true,true,22100); b.update(true,true,22125);
 assert(b.update(true,true,23125)); assert(!b.update(true,false,23126));
 assert(!b.update(true,true,30000));
 // debounce bounce and millis rollover
 Button c; c.update(false,true,0xffffff00U);
 c.update(true,true,0xffffff10U); c.update(false,true,0xffffff15U);
 c.update(true,true,0xffffff20U); assert(!c.update(true,true,0xffffff38U));
 c.update(true,true,0xffffff39U);
 assert(!c.update(true,true,(uint32_t)(0xffffff39U+999U)));
 assert(c.update(true,true,(uint32_t)(0xffffff39U+1000U)));
 assert(!c.update(true,true,(uint32_t)(0xffffff39U+1500U)));
}
''', TX)


class BindTrimSaveTransmitterSourceTests(unittest.TestCase):
    def setUp(self):
        self.source = (TX / 'flight_core.h').read_text()

    def test_standard_build_has_no_temporary_flag_or_header(self):
        self.assertNotIn('TXV3_TEMP_BIND_TRIM_SAVE', self.source)
        self.assertNotIn('temp_bind_trim.h', self.source)
        self.assertFalse((TX / 'temp_bind_trim.h').exists())
        self.assertIn('#include "bind_trim_save.h"', self.source)

    def test_gating_uses_inhibits_not_flight_mode_and_drives_ch7_only(self):
        permitted = re.search(r'const bool trimPermitted = ([^;]+);', self.source).group(1)
        for term in ('!student', '!trimHandoff', '!simulatorMode', '!txLocked'):
            self.assertIn(term, permitted)
        self.assertNotIn('CH5', permitted)
        self.assertNotIn('mode5', permitted)
        self.assertIn('trimHandoff = txv3StudentGranted;', self.source)
        self.assertIn('if (trimPulse) localAux |= AuxChannels::CH7;', self.source)
        # CH5/CH6 come only from the D10/D7 buttons.
        self.assertNotIn('AuxChannels::encode((localAux & AuxChannels::CH5) != 0', self.source)

    def test_beep_once_on_pulse_start_and_info_reports_channel(self):
        self.assertIn('if (trimPulse && !bindTrimSaveWasPulsing)', self.source)
        self.assertIn('startBuzzerPattern(TRIM_SENT_PATTERN', self.source)
        self.assertIn('\\"trim_save_channel\\":7', self.source)
        # Trim-save is decided before the throttle timer and packet send.
        self.assertLess(self.source.index('bindTrimSave.update('),
                        self.source.index('pkt.aux_flags = localAux;'))


class BindTrimSaveReceiverTests(unittest.TestCase):
    def test_sbus_channel7_follows_ch7_bit_and_others_unchanged(self):
        source = (ROOT / 'rx_firmware/rx_firmware.ino').read_text()
        start = source.index('static uint16_t rcMicrosecondsToSbus')
        end = source.index('// Return to the locked state and force throttle low.')
        run_cpp(r'''
#include "aux_channels.h"
#include <cstring>
#include <cassert>
const uint16_t RC_MIN=1000,RC_MID=1500,RC_MAX=2000;
const uint8_t SBUS_CHANNEL_COUNT=16,SBUS_CHANNEL_PAYLOAD_SIZE=22,SBUS_FRAME_SIZE=25;
uint16_t sbus_a=1000,sbus_e=1500,sbus_t=1000,sbus_r=2000;uint8_t sbusAuxFlags=0;unsigned sbusFrames=0;
struct Port {uint8_t data[25];void write(uint8_t* p,unsigned n){assert(n==25);memcpy(data,p,n);}} sbusSerial;
''' + source[start:end] + r'''
int channel(int index){
 int result=0;for(int bit=0;bit<11;bit++){
 int offset=index*11+bit;result|=((sbusSerial.data[1+offset/8]>>(offset%8))&1)<<bit;
 }return result;
}
int main(){
 for(int a=0;a<2;a++)for(int b=0;b<2;b++)for(int c=0;c<2;c++){
  sbusAuxFlags=AuxChannels::encode(a,b)|(c?AuxChannels::CH7:0);sendSbusFrame();
  assert(channel(0)==200 && channel(1)==1000 && channel(2)==200 && channel(3)==1800);
  assert(channel(4)==(a?1800:200));assert(channel(5)==(b?1800:200));
  assert(channel(6)==(c?1800:200));
  for(int ch=7;ch<16;ch++)assert(channel(ch)==1000);
 }
 // Without the marker bit (old packets) CH7 stays low.
 sbusAuxFlags=AuxChannels::CH7;sendSbusFrame();assert(channel(6)==200);
}
''', ROOT / 'rx_firmware')

    def test_crsf_channel7_follows_ch7_bit(self):
        source = (ROOT / 'rx_pixhawk_crsf/rx_pixhawk_crsf.ino').read_text()
        funcs = source[source.index('static uint8_t crsfCrc8'):source.index('static void handleBindPacket')]
        run_cpp(r'''
#include "aux_channels.h"
#include <cstring>
#include <cassert>
const int RC_MIN=1000,RC_MID=1500,RC_MAX=2000,CRSF_CHANNEL_COUNT=16,CRSF_CHANNEL_PAYLOAD_SIZE=22,CRSF_FRAME_SIZE=26;
const int CRSF_ADDRESS_FLIGHT_CONTROLLER=0xC8,CRSF_FRAMETYPE_RC_CHANNELS_PACKED=0x16;
uint16_t channelAileron=1000,channelElevator=1500,channelThrottle=1000,channelRudder=2000;
uint8_t lastAuxFlags=0;int crsfFrames=0;
struct Port {uint8_t data[26];void write(uint8_t* p,int n){assert(n==26);memcpy(data,p,n);}} pixhawkSerial;
''' + funcs + r'''
int channel(int index){
 int result=0;for(int bit=0;bit<11;bit++){
 int offset=index*11+bit;result|=((pixhawkSerial.data[3+offset/8]>>(offset%8))&1)<<bit;
 }return result;
}
int main(){
 lastAuxFlags=AuxChannels::encode(false,false)|AuxChannels::CH7;sendCrsfChannels();
 assert(channel(4)==172 && channel(5)==172 && channel(6)==1811);
 lastAuxFlags=AuxChannels::encode(true,true);sendCrsfChannels();
 assert(channel(4)==1811 && channel(5)==1811 && channel(6)==172);
}
''', ROOT / 'rx_pixhawk_crsf')


if __name__ == '__main__':
    unittest.main()
