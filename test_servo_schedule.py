"""Exercise actual pulse scheduling and RadioHead preemption adapter contracts."""
from pathlib import Path
import subprocess
import tempfile
import unittest
ROOT = Path(__file__).resolve().parent

class ServoScheduleTests(unittest.TestCase):
    def test_frames_publication_watchdog_and_rollover(self):
        code = r'''
#include "servo_schedule.h"
#include <cassert>
int main(){
 ServoSchedule s;
 const uint16_t widths[4]={1000,1234,1567,2000};
 uint16_t timer=65000;
 for(int frame=0;frame<1000;frame++){
  s.submit(widths[0],widths[1],widths[2],widths[3]);
  unsigned elapsed=0;int high=-1;
  for(int phase=0;phase<5;phase++){
   auto e=s.next();
   if(e.low>=0){assert(e.low==high);high=-1;}
   if(e.high>=0){assert(high==-1);high=e.high;assert(e.delayUs==widths[high]);}
   timer+=(uint16_t)(e.delayUs*3);elapsed+=e.delayUs;
   if(phase==1)s.submit(2000,2000,2000,2000); // current frame remains coherent
  }
  assert(elapsed==20000 && high==-1 && !s.fault);
 }
 assert(timer==(uint16_t)(65000u+1000u*60000u));
 for(int i=0;i<35;i++)s.next();
 assert(s.fault && s.stalled && s.active[0]==1000 && s.active[1]==1500);
 s.submit(2000,2000,2000,2000);
 for(int i=0;i<5;i++)s.next();
 assert(s.fault && s.active[0]==1000); // reset required, no automatic restart
 ServoSchedule wrap;wrap.frames=0xfffffffe;wrap.submit(999,2001,1500,1500);
 for(int i=0;i<10;i++)wrap.next();
 assert(!wrap.fault && wrap.active[0]==1000 && wrap.active[1]==2000);
}
'''
        with tempfile.TemporaryDirectory() as folder:
            cpp=Path(folder)/'test.cpp';exe=Path(folder)/'test'
            cpp.write_text(code)
            subprocess.run(['c++','-std=c++11','-I',str(ROOT/'rx_V4__firmware'),str(cpp),'-o',str(exe)],check=True)
            subprocess.run([str(exe)],check=True,timeout=5)

    def test_actual_timer_isr_reads_synchronized_counter(self):
        code = r'''
#include "timer_servos.h"
int main(){
 for(int i=0;i<4;i++){TimerServos::ports[i]=&port.Group[i];TimerServos::masks[i]=1u<<i;}
 TimerServos::deadline=65000;
 for(int event=0;event<1000;event++){
  TimerServos::submit(1000,1500,1500,1500);
  liveCounter=(uint16_t)(TimerServos::deadline+9);cpuCounter=0; // CPU copy stale
  timer.COUNT16.INTFLAG.reg=TC_INTFLAG_MC0;
  TC4_Handler();
  assert(!TimerServos::failed() && TimerServos::maxLateUs()==3);
 }
 assert(TimerServos::frames()==200);
 liveCounter=TimerServos::deadline+301;
 TC4_Handler();assert(TimerServos::failed());
 for(int i=0;i<4;i++)assert(port.Group[i].OUTCLR.reg==(1u<<i));
}
'''
        with tempfile.TemporaryDirectory() as folder:
            temp=Path(folder)
            (temp/'Arduino.h').write_text((ROOT/'tests/timer_register_stub.h').read_text())
            (temp/'wiring_private.h').write_text('#pragma once\n')
            (temp/'test.cpp').write_text(code)
            subprocess.run(['c++','-std=c++11','-I',str(temp),'-I',str(ROOT/'rx_V4__firmware'),str(temp/'test.cpp'),'-o',str(temp/'test')],check=True)
            subprocess.run([str(temp/'test')],check=True,timeout=5)

    def test_spi_adapter_preserves_eic_and_atomic_exit(self):
        stub = r'''
#pragma once
#include <stdint.h>
#include <cassert>
const int EIC_IRQn=4;
struct Nvic {uint32_t ISER[1]={0xFFFFFFFF};} nvic;
Nvic *NVIC=&nvic;
bool masked=true;
void NVIC_DisableIRQ(int n){nvic.ISER[0]&=~(1ul<<n);}
void NVIC_EnableIRQ(int n){nvic.ISER[0]|=1ul<<n;}
void __DSB(){} void __ISB(){}
void __enable_irq(){masked=false;}
void __disable_irq(){masked=true;}
class RHSPIDriver {
 protected:
 virtual void beginTransaction(){assert(!masked && !(nvic.ISER[0]&(1ul<<EIC_IRQn)));}
 virtual void endTransaction(){assert(!masked && !(nvic.ISER[0]&(1ul<<EIC_IRQn)));}
};
class RH_RF95: public RHSPIDriver {public: RH_RF95(uint8_t,uint8_t){}};
'''
        code = r'''
#include "preemptible_rf95.h"
struct TestRadio: PreemptibleRf95 {
 TestRadio():PreemptibleRf95(8,3){}
 using PreemptibleRf95::beginTransaction;
 using PreemptibleRf95::endTransaction;
};
int main(){
 TestRadio r;
 for(bool enabled: {true,false}) {
  if(enabled)NVIC_EnableIRQ(EIC_IRQn);else NVIC_DisableIRQ(EIC_IRQn);
  const uint32_t before=nvic.ISER[0];masked=true;
  r.beginTransaction();assert(!masked);r.endTransaction();
  assert(masked && nvic.ISER[0]==before);
 }
}
'''
        with tempfile.TemporaryDirectory() as folder:
            temp=Path(folder);(temp/'RH_RF95.h').write_text(stub)
            (temp/'test.cpp').write_text('#include <initializer_list>\n'+code)
            subprocess.run(['c++','-std=c++11','-I',str(temp),'-I',str(ROOT/'rx_V4__firmware'),str(temp/'test.cpp'),'-o',str(temp/'test')],check=True)
            subprocess.run([str(temp/'test')],check=True,timeout=5)

if __name__ == '__main__':
    unittest.main()
