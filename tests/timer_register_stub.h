#pragma once
#include <stdint.h>
#include <cassert>
const int OUTPUT=1,TC4_IRQn=19,EIC_IRQn=4,USB_IRQn=7;
const uint32_t PM_APBCMASK_TC4=1,GCLK_CLKCTRL_CLKEN=1,GCLK_CLKCTRL_GEN_GCLK0=2,GCM_TC4_TC5=3;
const uint32_t TC_CTRLA_SWRST=1,TC_CTRLA_MODE_COUNT16=2,TC_CTRLA_PRESCALER_DIV16=4,TC_CTRLA_WAVEGEN_NFRQ=8;
const uint32_t TC_READREQ_RREQ=0x8000,TC_INTFLAG_MC0=16,TC_INTENSET_MC0=16;
#define GCLK_CLKCTRL_ID(x) (x)
#define TC_READREQ_ADDR(x) (x)
struct Reg {uint32_t reg=0;};
struct Status {struct {bool SYNCBUSY=false;} bit;};
struct Control {uint32_t reg=0;struct {bool SWRST=false,ENABLE=false;} bit;};
struct PortGroup {Reg OUTCLR,OUTSET;};
struct Port {PortGroup Group[4];} port;
Port *PORT=&port;
struct PinDescription {uint8_t ulPort=0,ulPin=0;};
PinDescription g_APinDescription[32];
uint16_t liveCounter=0,cpuCounter=0;
struct ReadRequest {
 void operator=(uint32_t value) {assert(value==(TC_READREQ_RREQ|0x10));cpuCounter=liveCounter;}
} readRequest;
struct ReadReg {ReadRequest reg;};
struct CountReg {operator uint32_t() const {return cpuCounter;}};
struct Count {CountReg reg;};
struct Timer {
 struct {Control CTRLA;Status STATUS;ReadReg READREQ;Reg CC[2],INTFLAG,INTENSET;Count COUNT;} COUNT16;
} timer;
Timer *TC4=&timer;
struct Clock {Reg CLKCTRL;Status STATUS;} clockRegister;
Clock *GCLK=&clockRegister;
struct Power {Reg APBCMASK;} power;
Power *PM=&power;
void pinMode(int,int){}
uint32_t __get_PRIMASK(){return 0;}
void __disable_irq(){} void __enable_irq(){} void __DMB(){}
void NVIC_DisableIRQ(int){} void NVIC_EnableIRQ(int){}
void NVIC_ClearPendingIRQ(int){} void NVIC_SetPriority(int,int){}
