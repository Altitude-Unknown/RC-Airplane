/*
  Transmitter V3 SAMD21 <-> ESP32-C3 UART round-trip diagnostic.

  PB22: SAMD TX -> ESP GPIO21 RX
  PB23: SAMD RX <- ESP GPIO20 TX

  This diagnostic never initializes or transmits with the LoRa radio.
*/

#include <Arduino.h>

static constexpr uint32_t LINK_BAUD = 115200;
static constexpr uint32_t PING_INTERVAL_MS = 1000;
static constexpr uint32_t REPLY_TIMEOUT_MS = 500;

static char receiveLine[64];
static size_t receiveLength = 0;
static uint32_t sequenceNumber = 0;
static uint32_t sentAtMs = 0;
static uint32_t lastPingMs = 0;
static bool waitingForReply = false;

static void waitSync() {
  while (SERCOM5->USART.SYNCBUSY.reg) {}
}

static void linkBegin() {
  PM->APBCMASK.reg |= PM_APBCMASK_SERCOM5;
  GCLK->CLKCTRL.reg = GCLK_CLKCTRL_ID(SERCOM5_GCLK_ID_CORE) |
                      GCLK_CLKCTRL_GEN_GCLK0 |
                      GCLK_CLKCTRL_CLKEN;
  while (GCLK->STATUS.bit.SYNCBUSY) {}

  // PB22/PB23 use peripheral function D for SERCOM5 PAD2/PAD3.
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

static void linkWriteByte(char value) {
  while (!SERCOM5->USART.INTFLAG.bit.DRE) {}
  SERCOM5->USART.DATA.reg = static_cast<uint8_t>(value);
}

static void linkPrint(const char *text) {
  while (*text) linkWriteByte(*text++);
}

static int linkRead() {
  if (!SERCOM5->USART.INTFLAG.bit.RXC) return -1;
  if (SERCOM5->USART.STATUS.reg) {
    SERCOM5->USART.STATUS.reg = SERCOM5->USART.STATUS.reg;
  }
  return SERCOM5->USART.DATA.reg & 0xff;
}

static void processLine(const char *line) {
  char expected[32];
  snprintf(expected, sizeof(expected), "ESP_PONG %lu",
           static_cast<unsigned long>(sequenceNumber));

  if (waitingForReply && strcmp(line, expected) == 0) {
    const uint32_t elapsed = millis() - sentAtMs;
    waitingForReply = false;
    Serial.print(F("UART_PASS sequence="));
    Serial.print(sequenceNumber);
    Serial.print(F(" round_trip_ms="));
    Serial.println(elapsed);
  } else {
    Serial.print(F("UART_RX "));
    Serial.println(line);
  }
}

void setup() {
  Serial.begin(115200);
  linkBegin();
  delay(1000);
  Serial.println(F("TXV3_M0_ESP_UART_TEST_START"));
  Serial.println(F("LoRa disabled; sending one ping per second"));
}

void loop() {
  int incoming;
  while ((incoming = linkRead()) >= 0) {
    const char byte = static_cast<char>(incoming);
    if (byte == '\r') continue;
    if (byte == '\n') {
      if (receiveLength) {
        receiveLine[receiveLength] = '\0';
        processLine(receiveLine);
        receiveLength = 0;
      }
    } else if (receiveLength < sizeof(receiveLine) - 1) {
      receiveLine[receiveLength++] = byte;
    } else {
      receiveLength = 0;
    }
  }

  const uint32_t now = millis();
  if (waitingForReply && now - sentAtMs >= REPLY_TIMEOUT_MS) {
    waitingForReply = false;
    Serial.print(F("UART_TIMEOUT sequence="));
    Serial.println(sequenceNumber);
  }

  if (!waitingForReply && now - lastPingMs >= PING_INTERVAL_MS) {
    lastPingMs = now;
    sequenceNumber++;
    char ping[32];
    snprintf(ping, sizeof(ping), "M0_PING %lu\n",
             static_cast<unsigned long>(sequenceNumber));
    linkPrint(ping);
    sentAtMs = millis();
    waitingForReply = true;
  }
}
