#pragma once
#include "servo_schedule.h"
#include <Arduino.h>
#include "wiring_private.h"

// Rx V4 A0 has no timer output mux. TC4 therefore schedules short GPIO edge
// interrupts. No pulse-width busy waits; radio/USB/SysTick can run between edges.
// TC4: 48 MHz / 16 = 3 MHz, free-running 16-bit counter, compare channel 0.
// No Servo/tone/analogWrite use is permitted on this dedicated timer.
namespace TimerServos {
static ServoSchedule schedule;
static PortGroup *ports[4];
static uint32_t masks[4];
static uint16_t deadline;
static volatile uint16_t maxLateTicks = 0;

inline void submit(uint16_t t, uint16_t a, uint16_t e, uint16_t r) {
  uint32_t primask = __get_PRIMASK();
  __disable_irq();
  schedule.submit(t, a, e, r);
  __DMB();
  if (!primask) __enable_irq();
}
inline bool failed() { return schedule.fault; }
inline uint32_t frames() { return schedule.frames; }
inline uint16_t maxLateUs() { return (maxLateTicks + 2) / 3; }

inline void pause() {
  NVIC_DisableIRQ(TC4_IRQn);
  TC4->COUNT16.CTRLA.bit.ENABLE = 0;
  while (TC4->COUNT16.STATUS.bit.SYNCBUSY) {}
  for (uint8_t i=0;i<4;++i) ports[i]->OUTCLR.reg=masks[i];
}

inline void begin(int t, int a, int e, int r) {
  schedule = ServoSchedule{};
  maxLateTicks = 0;
  const int pins[4] = {t, a, e, r};
  for (uint8_t i = 0; i < 4; ++i) {
    pinMode(pins[i], OUTPUT);
    const PinDescription &p = g_APinDescription[pins[i]];
    ports[i] = &PORT->Group[p.ulPort];
    masks[i] = 1ul << p.ulPin;
    ports[i]->OUTCLR.reg = masks[i];
  }
  PM->APBCMASK.reg |= PM_APBCMASK_TC4;
  GCLK->CLKCTRL.reg = GCLK_CLKCTRL_CLKEN | GCLK_CLKCTRL_GEN_GCLK0 |
                     GCLK_CLKCTRL_ID(GCM_TC4_TC5);
  while (GCLK->STATUS.bit.SYNCBUSY) {}
  TC4->COUNT16.CTRLA.reg = TC_CTRLA_SWRST;
  while (TC4->COUNT16.STATUS.bit.SYNCBUSY || TC4->COUNT16.CTRLA.bit.SWRST) {}
  TC4->COUNT16.CTRLA.reg = TC_CTRLA_MODE_COUNT16 | TC_CTRLA_PRESCALER_DIV16 |
                          TC_CTRLA_WAVEGEN_NFRQ;
  while (TC4->COUNT16.STATUS.bit.SYNCBUSY) {}
  deadline = 3000; // first safe pulse one millisecond after enabling
  TC4->COUNT16.CC[0].reg = deadline;
  while (TC4->COUNT16.STATUS.bit.SYNCBUSY) {}
  TC4->COUNT16.INTFLAG.reg = TC_INTFLAG_MC0;
  TC4->COUNT16.INTENSET.reg = TC_INTENSET_MC0;
  NVIC_ClearPendingIRQ(TC4_IRQn);
  NVIC_SetPriority(TC4_IRQn, 0);
  NVIC_SetPriority(EIC_IRQn, 2);
  NVIC_SetPriority(USB_IRQn, 1);
  NVIC_EnableIRQ(TC4_IRQn);
  TC4->COUNT16.CTRLA.bit.ENABLE = 1;
  while (TC4->COUNT16.STATUS.bit.SYNCBUSY) {}
}

inline void interrupt() {
  if (!(TC4->COUNT16.INTFLAG.reg & TC_INTFLAG_MC0)) return;
  TC4->COUNT16.INTFLAG.reg = TC_INTFLAG_MC0;
  // COUNT is in the timer clock domain. A pre-enable continuous read request
  // does not keep this SAMD21's CPU-side COUNT current. Synchronize each read;
  // unlike a servo-width busy wait, this takes only a few peripheral cycles.
  TC4->COUNT16.READREQ.reg = TC_READREQ_RREQ | TC_READREQ_ADDR(0x10);
  uint8_t budget=64;
  while (TC4->COUNT16.STATUS.bit.SYNCBUSY && --budget) {}
  if (!budget) {
    for (uint8_t i=0;i<4;++i) ports[i]->OUTCLR.reg=masks[i];
    schedule.fault=true;
    schedule.phase=0;
    deadline+=3000;
    TC4->COUNT16.CC[0].reg=deadline;
    return;
  }
  const uint16_t count = TC4->COUNT16.COUNT.reg;
  const uint16_t late = (uint16_t)(count - deadline);
  if (late > maxLateTicks) maxLateTicks = late;
  if (late > 300) { // >100 us late: stop active pulses, latch safe outputs
    for (uint8_t i = 0; i < 4; ++i) ports[i]->OUTCLR.reg = masks[i];
    schedule.fault = true;
    schedule.phase = 0;
    deadline = count + 3000;
  } else {
    const ServoSchedule::Edge event = schedule.next();
    if (event.low >= 0) ports[event.low]->OUTCLR.reg = masks[event.low];
    if (event.high >= 0) ports[event.high]->OUTSET.reg = masks[event.high];
    deadline += event.delayUs * 3;
  }
  TC4->COUNT16.CC[0].reg = deadline;
}
} // namespace TimerServos

void TC4_Handler() { TimerServos::interrupt(); }
