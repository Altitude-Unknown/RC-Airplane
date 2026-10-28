#pragma once
#include <RH_RF95.h>

// SAMD21-only adapter for this single-SPI-device receiver. RadioHead's SPI
// helpers globally mask IRQs, including during the entire FIFO burst. Protect
// the SPI bus by masking EIC (the only other SPI caller) instead, allowing TC4
// and SysTick to run. No other ISR may access SPI in this sketch.
//
// RadioHead enters beginTransaction with PRIMASK=1; endTransaction restores
// PRIMASK=1 before RadioHead's enclosing ATOMIC_RESTORESTATE restores the
// caller's original state. Radio operations must never be called from another
// application critical section. No installed library is modified.
class PreemptibleRf95 : public RH_RF95 {
 public:
  PreemptibleRf95(uint8_t cs, uint8_t irq) : RH_RF95(cs, irq) {}
 protected:
  bool eicWasEnabled = false;
  void beginTransaction() override {
    eicWasEnabled = (NVIC->ISER[0] & (1ul << EIC_IRQn)) != 0;
    NVIC_DisableIRQ(EIC_IRQn);
    __DSB(); __ISB();
    __enable_irq();
    RHSPIDriver::beginTransaction();
  }
  void endTransaction() override {
    RHSPIDriver::endTransaction();
    __disable_irq();
    if (eicWasEnabled) NVIC_EnableIRQ(EIC_IRQn);
  }
};
