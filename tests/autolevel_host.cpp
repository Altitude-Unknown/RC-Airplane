// Hardware substitutes only. The production sketch is inserted after these.
#include <stdint.h>
#include <cmath>
#include <cstring>
#include <cstdlib>
#include <cassert>
#include <vector>
#include <string>
#include <algorithm>
using std::isfinite;
const int A0=14,A1=15,A2=16,A3=17,A4=18;
const int LOW=0,HIGH=1,INPUT=0,INPUT_PULLUP=2,OUTPUT=3,HEX=16;
uint32_t testNow=4000;
uint32_t millis(){return testNow;}
void delay(unsigned t){testNow+=t;}
void pinMode(int,int){}
int groundedPin=-1;
int digitalPinValues[64]={};
bool interruptsEnabled=true;
int pulseHighPin=-1;
std::vector<std::pair<int,unsigned>> emittedPulses;
int digitalRead(int pin){return pin==groundedPin ? LOW : (pin==13 ? digitalPinValues[pin] : HIGH);}
void digitalWrite(int pin,int value){
 if(pin>=0 && pin<64)digitalPinValues[pin]=value;
 if(value==HIGH)pulseHighPin=pin;else if(pin==pulseHighPin)pulseHighPin=-1;
}
void noInterrupts(){assert(interruptsEnabled);interruptsEnabled=false;}
void interrupts(){assert(!interruptsEnabled);interruptsEnabled=true;}
void delayMicroseconds(unsigned us){
 assert(!interruptsEnabled && pulseHighPin>=0);
 emittedPulses.push_back({pulseHighPin,us});
}
int analogRead(int){return 0;}
void initiateReset(int){}
struct SerialMock {
 void begin(int){} int available(){return 0;} int read(){return 0;} void flush(){}
 template<typename T> void print(T){}
 template<typename T,typename U> void print(T,U){}
 template<typename T> void println(T){}
 template<typename T,typename U> void println(T,U){}
 void println(){}
} Serial;
int sensorBegins=0;
struct BoundedI2c {
 std::vector<uint8_t> sample;
 BoundedI2c(int,int){} void begin(){sensorBegins++;}
 bool writeRegister(uint8_t,uint8_t,uint8_t){return false;}
 bool probe(uint8_t){return false;}
 bool readRegisters(uint8_t,uint8_t,uint8_t* out,uint8_t n){
  if(sample.size()!=n)return false;
  memcpy(out,sample.data(),n);return true;
 }
};
template<class T> struct Storage {
 T data{};
 void read(T &v){v=data;} void write(T v){data=v;}
};
#define FlashStorage(name,type) Storage<type> name
struct RH_RF95 {
 enum ModemConfigChoice {Bw500Cr45Sf128};
 std::vector<uint8_t> packet;
 RH_RF95(int,int){}
 bool init(){return true;} void setModemConfig(ModemConfigChoice){}
 void setFrequency(float){} int lastRssi(){return -45;}
 bool available(){return !packet.empty();}
 bool recv(uint8_t* out,uint8_t* n){
  *n=std::min<size_t>(*n,packet.size());memcpy(out,packet.data(),*n);packet.clear();return true;
 }
};
