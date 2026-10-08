"""Exercise the experimental sketch's real packet, safety, and output logic."""
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent

class AutolevelTests(unittest.TestCase):
    def test_experimental_state_machine(self):
        source = (ROOT/'rx_V4__firmware/rx_V4__firmware.ino').read_text()
        source = re.sub(r'^\s*#include.*$', '', source, flags=re.M)
        harness = (ROOT/'tests/autolevel_host.cpp').read_text()
        commands = (ROOT/'rx_V4__firmware/autolevel_commands.h').read_text().replace('#pragma once', '')
        scenarios = r'''
void send(uint16_t bind=42,uint16_t throttle=1000,uint8_t aux=0x80,bool esc=false,
          uint16_t surface=1500) {
 ControlPacket p{surface,surface,surface,throttle,
                 (uint16_t)(bind|(esc?0x8000:0)),aux,1};
 rf95.packet.assign((uint8_t*)&p,(uint8_t*)&p+sizeof(p));
 testNow+=20;loop();
}
void prepare() { g_bind={BIND_MAGIC,42,0}; bootMs=0; }
void arm() { for(int i=0;i<20;i++)send(); assert(armed); }
int main(int argc,char**argv){
 assert(argc==2); std::string test=argv[1];prepare();
 if(test=="binding"){
  g_bind={0,0,0}; for(int i=0;i<30;i++)send();
  assert(!armed && acceptedPackets==0 && cur_t==1000);
  g_bind={BIND_MAGIC,42,0}; for(int i=0;i<30;i++)send(43);
  assert(!armed && acceptedPackets==0);
  bindMode=true;for(int i=0;i<30;i++)send();assert(acceptedPackets==0);
  bindMode=false;bindRestartRequired=true;for(int i=0;i<30;i++)send();
  assert(!armed && acceptedPackets==0 && cur_t==1000);
 }else if(test=="esc"){
  bootMs=testNow;for(int i=0;i<3;i++)send(43,2000,0x80,true);
  assert(!escMode && !armed && escFlagStreak==0);
  send(42,2000,0x80,true);send(43,2000,0x80,true);
  send(42,2000,0x80,true);send(42,2000,0x80,true);assert(!escMode);
  send(42,2000,0x80,true);assert(escMode && cur_t==2000);
  testNow+=1020;loop();assert(!escMode && !armed && cur_t==1000);
 }else if(test=="boot"){
  bootMs=testNow;
  for(int i=0;i<100;i++)send();assert(!armed && cur_t==1000);
  for(int i=0;i<100;i++)send(42,1800);assert(!armed && cur_t==1000);
  arm();send(42,1800);assert(cur_t==1800);
 }else if(test=="failsafe"){
  arm();send(42,1800,0x80,false,1700);assert(cur_t==1800);
  apState.pilotAutolevelEnabled=true;apState.rollRateIntegrator=.1f;
  testNow+=160;loop();assert(!apState.pilotAutolevelEnabled);
  assert(apState.rollRateIntegrator==0 && cur_t==1800 && cur_a==1700);
  testNow+=900;loop();assert(armed && cur_t==1800);
  testNow+=160;loop();assert(!armed && cur_t==1000 && cur_a==1700);
  testNow+=1800;loop();assert(cur_a==1500 && cur_e==1500 && cur_r==1500);
  send(42,1800);assert(!armed && cur_t==1000);
  arm();assert(!apState.pilotAutolevelEnabled);
 }else if(test=="buttons"){
  armed=true;imu.ready=imu.gyroBiasReady=true;imu.lastSampleMs=testNow;
  apState.neutralCaptured=true;
  handleAutolevelAuxCommand(0x90,testNow);assert(!apState.pilotAutolevelEnabled);
  handleAutolevelAuxCommand(0x80,testNow);
  handleAutolevelAuxCommand(0x90,testNow);assert(apState.pilotAutolevelEnabled);
  handleAutolevelAuxCommand(0x80,testNow);assert(apState.pilotAutolevelEnabled);
  handleAutolevelAuxCommand(0xb0,testNow);assert(!apState.pilotAutolevelEnabled);
  handleAutolevelAuxCommand(0x90,testNow);assert(!apState.pilotAutolevelEnabled);
  handleAutolevelAuxCommand(0x80,testNow);handleAutolevelAuxCommand(0x90,testNow);
  assert(apState.pilotAutolevelEnabled);
  setPilotAutolevelEnabled(false,"fault");
  handleAutolevelAuxCommand(0x90,testNow);assert(!apState.pilotAutolevelEnabled);
  handleAutolevelAuxCommand(1,testNow);assert(!apState.pilotAutolevelEnabled);
 }else if(test=="surfaces"){
  arm();for(int v=1000;v<=2000;v++){send(42,1000,0x80,false,v);assert(cur_a==v&&cur_e==v&&cur_r==v);}
 }else if(test=="pulses"){
  cur_t=1000;cur_a=1234;cur_e=1567;cur_r=2000;emittedPulses.clear();
  writeServoFrame();
  assert(interruptsEnabled && pulseHighPin==-1 && emittedPulses.size()==4);
  assert(emittedPulses[0]==std::make_pair(PIN_SERVO_THROTTLE,1000u));
  assert(emittedPulses[1]==std::make_pair(PIN_SERVO_AILERON,1234u));
  assert(emittedPulses[2]==std::make_pair(PIN_SERVO_ELEVATOR,1567u));
  assert(emittedPulses[3]==std::make_pair(PIN_SERVO_RUDDER,2000u));
  assert(digitalPinValues[PIN_SERVO_THROTTLE]==LOW);
  assert(digitalPinValues[PIN_SERVO_AILERON]==LOW);
  assert(digitalPinValues[PIN_SERVO_ELEVATOR]==LOW);
  assert(digitalPinValues[PIN_SERVO_RUDDER]==LOW);
 }else if(test=="directions"){
  armed=true;acceptedPackets=1;apState.neutralCaptured=true;
  apState.neutralAileronUs=apState.neutralElevatorUs=1500;
  apState.sticksReleased=true;apState.pilotAutolevelEnabled=true;
  imu.ready=imu.gyroBiasReady=imu.attitudeInitialized=true;
  imu.rollDeg=apConfig.airframeLevelRollDeg+10;
  imu.pitchDeg=apConfig.airframeLevelPitchDeg+10;
  imu.gyroRollDps=imu.gyroPitchDps=0;
  apConfig.autolevelRampMs=0;
  updateAutopilotState(testNow,0);
  assert(apState.mode==AP_MODE_LEVEL_HOLD);
  assert(apState.targetAileronCorrectionUs>0);
  assert(apState.targetElevatorCorrectionUs<0);
 }else if(test=="imu"){
  imu.ready=true;imu.attitudeInitialized=true;imu.q0=NAN;
  updateQuaternionAhrs(0,0,0,0,0,1,.01f,false);
  assert(!imu.ready && !imu.attitudeInitialized);
  arm();imu.ready=false;apState.pilotAutolevelEnabled=true;
  send();assert(!apState.pilotAutolevelEnabled && armed);
 }else if(test=="bindplug"){
  groundedPin=20;BIND_STORE.data={BIND_MAGIC,42,0};setup();
  assert(bindPlugBoot && bindMode && sensorBegins==0 && !imu.ready);
  BindPacket bp{BIND_MAGIC,77,0};
  rf95.packet.assign((uint8_t*)&bp,(uint8_t*)&bp+sizeof(bp));
  testNow+=20;loop();assert(bindRestartRequired && !bindMode && g_bind.bindCode==77);
  for(int i=0;i<30;i++)send(77);assert(!armed && acceptedPackets==0 && cur_t==1000);
 }else if(test=="accelscale"){
  calibrationRequested=true; imu.ready=true; sensorBus.sample.assign(12,0);
  int16_t z=-5738; // ~0.70g with confirmed LSM6DSO32 scale must reject calibration.
  sensorBus.sample[10]=z&255;sensorBus.sample[11]=(z>>8)&255;
  for(int i=0;i<130;i++){testNow+=10;updateImuEstimate(testNow,true);}
  assert(!imu.gyroBiasReady && imu.gyroBiasSamples==0);
  z=-8192;sensorBus.sample[10]=z&255;sensorBus.sample[11]=(z>>8)&255;
  for(int i=0;i<130;i++){testNow+=10;updateImuEstimate(testNow,true);}
  assert(imu.gyroBiasReady && fabsf(imu.accelRefG-1)<.01f);
 }else if(test=="calbutton"){
  imu.ready=true;acceptedPackets=1;lastRxMs=testNow;
  serviceCalibrationButton(testNow);testNow+=50;serviceCalibrationButton(testNow);
  groundedPin=10;serviceCalibrationButton(testNow);testNow+=50;lastRxMs=testNow;
  serviceCalibrationButton(testNow);
  assert(calibrationStartPending && !calibrationRequested && !imu.gyroBiasReady);
  testNow+=999;lastRxMs=testNow;serviceCalibrationButton(testNow);
  assert(calibrationStartPending && !calibrationRequested);
  testNow+=1;lastRxMs=testNow;serviceCalibrationButton(testNow);
  assert(!calibrationStartPending && calibrationRequested && !imu.gyroBiasReady);
  testNow-=testNow%100;updateLed();assert(digitalPinValues[13]==HIGH);
  testNow+=50;updateLed();assert(digitalPinValues[13]==LOW);
  calibrationRequested=false;ledState=LED_ARMED;updateLed();
  assert(digitalPinValues[13]==HIGH); // Completed calibration returns to solid.
  testNow+=50;serviceCalibrationButton(testNow);
  assert(!calibrationRequested && !calibrationStartPending); // Held button never retriggers.
  groundedPin=-1;serviceCalibrationButton(testNow);testNow+=50;serviceCalibrationButton(testNow);
  manual_t=1800;groundedPin=10;serviceCalibrationButton(testNow);testNow+=50;lastRxMs=testNow;
  serviceCalibrationButton(testNow);assert(!calibrationRequested);
 }else if(test=="override"){
  armed=true;acceptedPackets=1;apState.neutralCaptured=true;
  imu.ready=imu.gyroBiasReady=imu.attitudeInitialized=true;
  imu.rollDeg=apConfig.airframeLevelRollDeg;
  imu.pitchDeg=apConfig.airframeLevelPitchDeg;
  setPilotAutolevelEnabled(true,"test");
  updateAutopilotState(testNow,0);testNow+=120;updateAutopilotState(testNow,0);
  assert(apState.mode==AP_MODE_LEVEL_HOLD);
  manual_a=1600;updateAutopilotState(testNow,0);applyManualOrAutopilotDesired();
  assert(apState.mode==AP_MODE_MANUAL && des_a==1600 && apState.rollRateIntegrator==0);
  manual_a=1500;apState.launchThrottleSeen=true;apState.launchThrottleSeenMs=testNow-6000;
  imu.rollDeg=apConfig.airframeLevelRollDeg+60;
  updateAutopilotState(testNow,0);testNow+=120;updateAutopilotState(testNow,0);
  assert(!apState.pilotAutolevelEnabled && apState.mode==AP_MODE_MANUAL);
 }else {assert(false);}
}
'''
        with tempfile.TemporaryDirectory() as folder:
            cpp = Path(folder)/'autolevel.cpp'
            exe = Path(folder)/'autolevel'
            cpp.write_text(harness+'\n'+commands+'\n'+source+'\n'+scenarios)
            subprocess.run(['c++','-std=c++11','-O2',str(cpp),'-o',str(exe)],check=True)
            for scenario in ('binding','esc','boot','failsafe','buttons','surfaces','pulses','directions','imu','override','bindplug','accelscale','calbutton'):
                with self.subTest(scenario=scenario):
                    subprocess.run([str(exe),scenario],check=True)


class BoundedBusTests(unittest.TestCase):
    def test_sensor_transactions_and_stuck_bus_deadline(self):
        stub = r'''
#pragma once
#include <stdint.h>
#include <cassert>
#include <deque>
const int LOW=0,HIGH=1,INPUT_PULLUP=2,OUTPUT=3;
uint32_t clockUs=0;
bool stuckClock=false;
std::deque<int> sdaReads;
int pinModes[32]={};
uint32_t micros(){return clockUs++;}
void delayMicroseconds(unsigned n){clockUs+=n;}
void digitalWrite(int,int value){assert(value==LOW);}
void pinMode(int pin,int mode){pinModes[pin]=mode;}
int digitalRead(int pin){
 if(pin==21)return stuckClock?LOW:HIGH;
 assert(!sdaReads.empty());int v=sdaReads.front();sdaReads.pop_front();return v;
}
'''
        program = r'''
#include "bounded_i2c.h"
int main(){
 BoundedI2c bus(20,21);bus.begin();
 sdaReads={HIGH,LOW,LOW,LOW,HIGH};
 assert(bus.writeRegister(0x6a,0x10,0x40));assert(sdaReads.empty());
 // Read register: START/address ACK/register ACK/repeated START/address ACK,
 // then 16 returned data bits and STOP.
 sdaReads={HIGH,LOW,LOW,HIGH,LOW};
 for(int value : {0x69,0x55})for(int bit=7;bit>=0;--bit)sdaReads.push_back((value>>bit)&1);
 sdaReads.push_back(HIGH);uint8_t data[2]={};
 assert(bus.readRegisters(0x6a,0x0f,data,2));
 assert(data[0]==0x69 && data[1]==0x55 && sdaReads.empty());
 sdaReads={HIGH,HIGH,HIGH};assert(!bus.probe(0x6a)); // NACK
 for(uint32_t start : {0u,0xffffff00u}){
  clockUs=start;stuckClock=true;sdaReads={HIGH};
  assert(!bus.probe(0x6a));
  assert((uint32_t)(clockUs-start)>=5000 && (uint32_t)(clockUs-start)<5100);
  assert(pinModes[20]==INPUT_PULLUP && pinModes[21]==INPUT_PULLUP);
 }
}
'''
        with tempfile.TemporaryDirectory() as folder:
            temp = Path(folder)
            (temp/'Arduino.h').write_text(stub)
            (temp/'bus.cpp').write_text(program)
            exe = temp/'bus'
            subprocess.run(['c++','-std=c++11','-I',str(temp),'-I',str(ROOT/'rx_V4__firmware'),
                            str(temp/'bus.cpp'),'-o',str(exe)],check=True)
            subprocess.run([str(exe)],check=True)

if __name__ == '__main__':
    unittest.main()
