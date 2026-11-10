"""Exercise production button state, packet codec and trainer interlocks on host."""
from pathlib import Path
import subprocess
import tempfile
import unittest
from fram_gui_models import ModelsStore
from test_gui_model_codec import MemoryWorker
ROOT = Path(__file__).resolve().parent

class ButtonChannelTests(unittest.TestCase):
    def run_cpp(self, code):
        with tempfile.TemporaryDirectory() as d:
            src=Path(d)/'test.cpp'; exe=Path(d)/'test'
            src.write_text(code)
            subprocess.run(['c++','-std=c++11','-I',str(ROOT/'tx_firmware'),str(src),'-o',str(exe)],check=True)
            subprocess.run([str(exe)],check=True)

    def test_codec_and_model_round_trip(self):
        w=MemoryWorker(); s=ModelsStore(w)
        m=dict(name='Buttons', bind_code=123, rates=[100]*4, expo=[0]*4,
               subtrim=[0]*4, endpoints=[[1000,2000]]*4, active_rates=False,dr_switch=0)
        for d10 in range(3):
            for d7 in range(3):
                m.update(d10_function=d10,d7_function=d7)
                s.write_model(0,m); out=s.read_model(0)
                self.assertEqual((out['d10_function'],out['d7_function']),(d10,d7))
                self.assertTrue(out['crc_ok'])
        del m['d10_function']; del m['d7_function']
        s.write_model(0,m);out=s.read_model(0)
        self.assertEqual((out['d10_function'],out['d7_function']),(0,0))
        for invalid in (-1,3,'1',True):
            m['d10_function']=invalid
            with self.assertRaises(ValueError): s.write_model(0,m)
        m['d10_function']=1
        w.device_info={}
        with self.assertRaisesRegex(ValueError,'Update'): s.write_model(0,m)
        w.device_info={'button_channels':True,'radio_role':'STUDENT'}
        with self.assertRaisesRegex(ValueError,'reserve D10'): s.write_model(0,m)

    def test_button_press_hold_release_bounce_and_reset(self):
        self.run_cpp(r'''
#include "aux_channels.h"
#include <cassert>
using namespace AuxChannels;
int main(){
 Button m;
 assert(!m.update(false,1,25));
 assert(!m.update(true,1,30)); assert(!m.update(false,1,35));
 assert(!m.update(true,1,40)); assert(!m.update(true,1,64));
 assert(m.update(true,1,65)); assert(m.update(true,1,1000));
 assert(m.update(false,1,1001)); assert(!m.update(false,1,1026));
 Button t;
 t.update(false,2,25); t.update(true,2,30); assert(t.update(true,2,55));
 assert(t.update(true,2,2000)); t.update(false,2,2001); assert(t.update(false,2,2026));
 t.update(true,2,2030); assert(!t.update(true,2,2055));
 Button bootHeld;
 assert(!bootHeld.update(true,2,0)); assert(!bootHeld.update(true,2,100));
 bootHeld.update(false,2,200); assert(!bootHeld.update(false,2,225));
 bootHeld.update(true,2,300); assert(bootHeld.update(true,2,325));
 assert(!bootHeld.update(true,0,400));
 for(int i=0;i<128;i++) {assert(pulse(i,CH5)==1000);assert(pulse(i,CH6)==1000);}
 for(int a=0;a<2;a++)for(int b=0;b<2;b++){
   auto flags=encode(a,b);assert(pulse(flags,CH5)==(a?2000:1000));assert(pulse(flags,CH6)==(b?2000:1000));
 }
 assert(mode(3,0)==0 && mode(12,2)==0);
}
''')
        original=(ROOT/'tx_firmware/aux_channels.h').read_bytes()
        for folder in ('PCB/TxV3/TxV3_Full_M0','rx_firmware','rx_pixhawk_crsf'):
            self.assertEqual(original,(ROOT/folder/'aux_channels.h').read_bytes())

    def test_trainer_assignment_and_link_loss_do_not_reassign_button(self):
        source=(ROOT/'PCB/TxV3/TxV3_Full_M0/txv3_buddy_support.h').read_text()
        service=source[source.index('void txv3BuddyService()'):source.index('bool txv3BuddyIsStudent()')]
        select=source[source.index('bool txv3BuddySelectChannels('):]
        self.run_cpp(r'''
#include <stdint.h>
#include <cstdlib>
#include <cassert>
uint32_t now=100; uint32_t millis(){return now;}
int pressed=0; const int LOW=0; int digitalRead(int){return pressed?0:1;}
void txv3ReadUart(){} void txv3Write(const char*){}
const int TXV3_MASTER=1,TXV3_TRAINER_PIN=10,TXV3_STUDENT_TIMEOUT_MS=250,TXV3_MASTER_MOVE_US=35;
int txv3Role=1;
struct Channels {uint16_t rud,ail,ele,thr;uint8_t aux;};
Channels txv3Master{1500,1500,1500,1000,0xA0},txv3MasterAtGrant=txv3Master,txv3Student{1600,1600,1600,1000,0};
bool txv3TrainerEnabled=false,txv3StudentGranted=false,txv3AuxWasPressed=false,txv3StudentFresh=true,txv3LastReportedGrant=false;
uint32_t txv3StudentReceivedMs=100,txv3LastAuthorityHeartbeatMs=0;
''' + service + select + r'''
int main(){
 pressed=1;txv3BuddyService();pressed=0;txv3BuddyService();assert(!txv3StudentGranted);
 txv3TrainerEnabled=true;pressed=1;txv3BuddyService();pressed=0;txv3BuddyService();assert(txv3StudentGranted);
 uint16_t r=1500,a=1500,e=1500,t=1000;uint8_t aux=0xA0;
 assert(txv3BuddySelectChannels(r,a,e,t,aux));assert(r==1600 && aux==0xA0);
 now=400;txv3BuddyService();assert(!txv3StudentGranted && txv3TrainerEnabled);
 txv3StudentGranted=true;txv3TrainerEnabled=false;txv3BuddyService();assert(!txv3StudentGranted);
}
''')

    def test_crsf_channel5_and6_frame_mapping(self):
        source=(ROOT/'rx_pixhawk_crsf/rx_pixhawk_crsf.ino').read_text()
        funcs=source[source.index('static uint8_t crsfCrc8'):source.index('static void handleBindPacket')]
        self.run_cpp(r'''
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
 for(int a=0;a<2;a++)for(int b=0;b<2;b++){
 lastAuxFlags=AuxChannels::encode(a,b);sendCrsfChannels();
 assert(channel(0)==172 && channel(1)==992 && channel(2)==172 && channel(3)==1811);
 assert(channel(4)==(a?1811:172));assert(channel(5)==(b?1811:172));
 for(int ch=6;ch<16;ch++)assert(channel(ch)==992);
 assert(pixhawkSerial.data[25]==crsfCrc8(&pixhawkSerial.data[2],23));
 }
 lastAuxFlags=3;sendCrsfChannels();assert(channel(4)==172 && channel(5)==172);
}
''')

    def test_bind_plug_suppresses_channel6_pulses(self):
        source=(ROOT/'rx_firmware/rx_firmware.ino').read_text()
        func=source[source.index('void writeServoFrame()'):source.index('// A bind plug')]
        self.run_cpp('''
#include <cassert>
bool bindPlugBoot=false;
const int PIN_SERVO_THROTTLE=0,PIN_SERVO_AILERON=1,PIN_SERVO_ELEVATOR=2,PIN_SERVO_RUDDER=3,PIN_SERVO_CHANNEL5=21,PIN_SERVO_CHANNEL6=20;
int cur_t=1000,cur_a=1500,cur_e=1500,cur_r=1500,channel5Us=2000,channel6Us=2000;
int counts[22]={};void writePulse(int pin,int){counts[pin]++;}
'''+func+'''
int main(){writeServoFrame();assert(counts[20]==1 && counts[21]==1);
bindPlugBoot=true;writeServoFrame();assert(counts[20]==1 && counts[21]==2);}
''')
        setup=source[source.index('void setup()'):]
        self.assertLess(setup.index('bindPlugBoot = detectBindPlug()'),setup.index('pinMode(PIN_SERVO_CHANNEL6, OUTPUT)'))

if __name__=='__main__': unittest.main()
