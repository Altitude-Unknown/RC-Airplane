/*
  Transparent USB CDC <-> ESP32-C3 UART bridge for Tx V3 bring-up.

  Fixed link speed: 115200 8N1
  SAMD PB22 TX -> ESP GPIO20 RXD
  SAMD PB23 RX <- ESP GPIO21 TXD

  No LoRa, FRAM, buttons, or buzzer are initialized.
*/

#include <Arduino.h>

static constexpr uint32_t LINK_BAUD = 115200;

static void waitSync() {
  while (SERCOM5->USART.SYNCBUSY.reg) {}
}

static void linkBegin() {
  PM->APBCMASK.reg |= PM_APBCMASK_SERCOM5;
  GCLK->CLKCTRL.reg = GCLK_CLKCTRL_ID(SERCOM5_GCLK_ID_CORE) |
                      GCLK_CLKCTRL_GEN_GCLK0 |
                      GCLK_CLKCTRL_CLKEN;
  while (GCLK->STATUS.bit.SYNCBUSY) {}

  PORT->Group[1].PMUX[11].bit.PMUXE = PORT_PMUX_PMUXE_D_Val;
  PORT->Group[1].PMUX[11].bit.PMUXO = PORT_PMUX_PMUXO_D_Val;
  PORT->Group[1].PINCFG[22].bit.PMUXEN = 1;
  PORT->Group[1].PINCFG[23].bit.PMUXEN = 1;

  SERCOM5->USART.CTRLA.bit.SWRST = 1;
  while (SERCOM5->USART.CTRLA.bit.SWRST ||
         SERCOM5->USART.SYNCBUSY.bit.SWRST) {}

  const uint32_t baudTimes8 = (SystemCoreClock * 8UL) / (16UL * LINK_BAUD);
  SERCOM5->USART.CTRLA.reg = SERCOM_USART_CTRLA_MODE_USART_INT_CLK |
                             SERCOM_USART_CTRLA_SAMPR(1) |
                             SERCOM_USART_CTRLA_TXPO(1) |
                             SERCOM_USART_CTRLA_RXPO(3) |
                             SERCOM_USART_CTRLA_DORD;
  SERCOM5->USART.BAUD.FRAC.FP = baudTimes8 % 8;
  SERCOM5->USART.BAUD.FRAC.BAUD = baudTimes8 / 8;
  SERCOM5->USART.CTRLB.reg = SERCOM_USART_CTRLB_CHSIZE(0) |
                             SERCOM_USART_CTRLB_TXEN |
                             SERCOM_USART_CTRLB_RXEN;
  waitSync();
  SERCOM5->USART.CTRLA.bit.ENABLE = 1;
  waitSync();
}

void setup() {
  Serial.begin(115200);
  linkBegin();
}

void loop() {
  while (Serial.available() && SERCOM5->USART.INTFLAG.bit.DRE) {
    SERCOM5->USART.DATA.reg = static_cast<uint8_t>(Serial.read());
  }

  while (SERCOM5->USART.INTFLAG.bit.RXC && Serial.availableForWrite()) {
    if (SERCOM5->USART.STATUS.reg) {
      SERCOM5->USART.STATUS.reg = SERCOM5->USART.STATUS.reg;
    }
    Serial.write(static_cast<uint8_t>(SERCOM5->USART.DATA.reg));
  }
}
