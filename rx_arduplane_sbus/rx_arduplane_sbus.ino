#include "aux_channels.h"
/*
  Rx V4 -> custom ArduPlane SBUS bridge (AI-assisted implementation).
  PB22 / MCU pin 37: non-inverted 3.3V SBUS, 100000 baud, 8E2.
  Connect to FC J4 pin 28, with common ground at J4 pin 30.
  Requires the BOREALIS V2 non-inverted SBUS serial configuration.
  Dedicated bridge: no servo PWM or receiver-side stabilization.
  Stops output after 300ms without validated bound radio packets.
*/

#include <SPI.h>
#include <RH_RF95.h>
#include <FlashStorage_SAMD.h>
#include <string.h>

// ------------------------------
// LoRa wiring and configuration
// ------------------------------
#define RFM95_CS   8
#define RFM95_INT  3
#define RFM95_RST  4
#define RF95_FREQ  915.0

RH_RF95 rf95(RFM95_CS, RFM95_INT);
const RH_RF95::ModemConfigChoice MODEM = RH_RF95::Bw500Cr45Sf128;

// ------------------------------
// Receiver controls
// ------------------------------
const int PIN_BIND_BTN = 10;
const int PIN_BIND_PLUG = SDA; // J1 pin 12, PA22; ground with J1 pin 10.

#ifndef LED_BUILTIN
  #define LED_BUILTIN 13
#endif

const bool ENABLE_USB_DEBUG = true;

// ------------------------------
// RC and link timing
// ------------------------------
const uint16_t RC_MIN = 1000;
const uint16_t RC_MID = 1500;
const uint16_t RC_MAX = 2000;

// Send SBUS at 100 Hz while the LoRa link is fresh. If accepted packets stop,
// stop sending RC frames so ArduPilot sees receiver loss and invokes its own
// configured RC failsafe. Do not replace loss with centered valid channels.
const uint32_t SBUS_FRAME_PERIOD_US = 10000;
const uint32_t SBUS_LINK_TIMEOUT_MS = 300;
const uint32_t USB_DEBUG_PERIOD_MS  = 1000;

// ------------------------------
// SBUS UART and frame constants
// ------------------------------
const uint32_t SBUS_BAUD = 100000;
const uint8_t SBUS_CHANNEL_COUNT = 16;
const uint8_t SBUS_CHANNEL_PAYLOAD_SIZE = 22;
const uint8_t SBUS_FRAME_SIZE = 25;

// The standard Feather M0 variant exposes PB22/PB23 as Serial5, but the custom
// Altitude Unknown RX target currently inherits feather_m0_express, whose
// variant constructs SERCOM5 without exposing a Serial5 Uart object or D30/D31
// pin-table entries. Configure the same peripheral and physical pins directly
// so this sketch builds correctly for the actual receiver board target.
class ReceiverV4SbusUart {
 public:
  void begin(uint32_t baud) {
    PM->APBCMASK.reg |= PM_APBCMASK_SERCOM5;
    GCLK->CLKCTRL.reg = GCLK_CLKCTRL_ID(SERCOM5_GCLK_ID_CORE) |
                        GCLK_CLKCTRL_GEN_GCLK0 |
                        GCLK_CLKCTRL_CLKEN;
    while (GCLK->STATUS.bit.SYNCBUSY) {}

    // PB22 = even half of PMUX[11], PB23 = odd half. Peripheral function D
    // routes both pins to SERCOM5 PAD2/PAD3.
    PORT->Group[1].PINCFG[22].bit.PMUXEN = 1;
    PORT->Group[1].PINCFG[23].bit.PMUXEN = 1;
    PORT->Group[1].PMUX[11].bit.PMUXE = PORT_PMUX_PMUXE_D_Val;
    PORT->Group[1].PMUX[11].bit.PMUXO = PORT_PMUX_PMUXO_D_Val;

    SERCOM5->USART.CTRLA.bit.SWRST = 1;
    while (SERCOM5->USART.CTRLA.bit.SWRST ||
           SERCOM5->USART.SYNCBUSY.bit.SWRST) {}

    // 16x arithmetic baud mode. At 48 MHz this produces the SBUS rate with
    // substantially less error than the SAMD21 fractional integer divisor.
    const uint64_t scaled = (uint64_t)65536 * 16 * baud;
    const uint16_t baudRegister =
        (uint16_t)(65536ULL - ((scaled + SystemCoreClock / 2) / SystemCoreClock));

    SERCOM5->USART.CTRLA.reg = SERCOM_USART_CTRLA_MODE_USART_INT_CLK |
                               SERCOM_USART_CTRLA_SAMPR(0) |
                               SERCOM_USART_CTRLA_TXPO(1) |
                               SERCOM_USART_CTRLA_RXPO(3) |
                               SERCOM_USART_CTRLA_DORD |
                               SERCOM_USART_CTRLA_FORM(1);
    SERCOM5->USART.BAUD.reg = baudRegister;
    SERCOM5->USART.CTRLB.reg = SERCOM_USART_CTRLB_CHSIZE(0) |
                               SERCOM_USART_CTRLB_SBMODE |
                               SERCOM_USART_CTRLB_TXEN |
                               SERCOM_USART_CTRLB_RXEN;
    while (SERCOM5->USART.SYNCBUSY.reg) {}

    SERCOM5->USART.CTRLA.bit.ENABLE = 1;
    while (SERCOM5->USART.SYNCBUSY.bit.ENABLE) {}
  }

  size_t write(const uint8_t *data, size_t length) {
    for (size_t index = 0; index < length; ++index) {
      while (!SERCOM5->USART.INTFLAG.bit.DRE) {}
      SERCOM5->USART.DATA.reg = data[index];
    }
    return length;
  }
};

ReceiverV4SbusUart flightSerial;

// ------------------------------
// Stored bind identity
// ------------------------------
#define BIND_MAGIC 0x42494E44UL

struct __attribute__((packed)) BindStore {
  uint32_t magic;
  uint16_t bindCode;
  uint16_t _pad;
};

FlashStorage(BIND_STORE, BindStore);

// These packet layouts must remain identical to the transmitter firmware.
struct __attribute__((packed)) ControlPacket {
  uint16_t ch_rud;
  uint16_t ch_ail;
  uint16_t ch_ele;
  uint16_t ch_thr;
  uint16_t flags;
  uint8_t aux_flags;
  uint16_t seq;
};

struct __attribute__((packed)) BindPacket {
  uint32_t magic;
  uint16_t code;
  uint16_t _pad;
};

BindStore bindStore = {0, 0, 0};
bool bindMode = false;
bool bindPlugBoot = false;
bool bindRestartRequired = false;
bool haveValidControl = false;

uint16_t channelRudder = RC_MID;
uint16_t channelAileron = RC_MID;
uint16_t channelElevator = RC_MID;
uint16_t channelThrottle = RC_MIN;
uint16_t lastSequence = 0;
uint8_t lastAuxFlags = 0;
int16_t lastRssi = 0;

uint32_t lastAcceptedPacketMs = 0;
uint32_t lastSbusFrameUs = 0;
uint32_t lastDebugMs = 0;
uint32_t acceptedPackets = 0;
uint32_t rejectedPackets = 0;
uint32_t malformedPackets = 0;
uint32_t sbusFrames = 0;

static bool rcValueValid(uint16_t value) {
  return value >= RC_MIN && value <= RC_MAX;
}

static bool controlPacketValid(const ControlPacket &packet) {
  return rcValueValid(packet.ch_rud) &&
         rcValueValid(packet.ch_ail) &&
         rcValueValid(packet.ch_ele) &&
         rcValueValid(packet.ch_thr);
}

static BindStore loadBindStore() {
  BindStore value;
  BIND_STORE.read(value);
  if (value.magic != BIND_MAGIC) {
    value.magic = 0;
    value.bindCode = 0;
    value._pad = 0;
  }
  return value;
}

static void saveBindCode(uint16_t code) {
  BindStore value = {BIND_MAGIC, code, 0};
  BIND_STORE.write(value);
  bindStore = value;
}

static void resetRadio() {
  pinMode(RFM95_RST, OUTPUT);
  digitalWrite(RFM95_RST, HIGH);
  delay(10);
  digitalWrite(RFM95_RST, LOW);
  delay(10);
  digitalWrite(RFM95_RST, HIGH);
  delay(10);
}

// Match ArduPilot's SBUS decoding: 200..1800 corresponds to 1000..2000us.
static uint16_t rcMicrosecondsToSbus(uint16_t microseconds) {
  if (microseconds < RC_MIN) microseconds = RC_MIN;
  if (microseconds > RC_MAX) microseconds = RC_MAX;
  return (uint16_t)(200UL + ((uint32_t)(microseconds - RC_MIN) * 8UL) / 5UL);
}

static void packSbusChannels(const uint16_t channels[SBUS_CHANNEL_COUNT],
                             uint8_t payload[SBUS_CHANNEL_PAYLOAD_SIZE]) {
  memset(payload, 0, SBUS_CHANNEL_PAYLOAD_SIZE);

  uint32_t accumulator = 0;
  uint8_t accumulatorBits = 0;
  uint8_t outputIndex = 0;

  for (uint8_t channel = 0; channel < SBUS_CHANNEL_COUNT; ++channel) {
    accumulator |= ((uint32_t)channels[channel] & 0x07FFUL) << accumulatorBits;
    accumulatorBits += 11;

    while (accumulatorBits >= 8) {
      payload[outputIndex++] = (uint8_t)(accumulator & 0xFF);
      accumulator >>= 8;
      accumulatorBits -= 8;
    }
  }
}

static void sendSbusChannels() {
  uint16_t channels[SBUS_CHANNEL_COUNT];
  const uint16_t neutral = rcMicrosecondsToSbus(RC_MID);
  for (uint8_t index = 0; index < SBUS_CHANNEL_COUNT; ++index) {
    channels[index] = neutral;
  }

  // Standard ArduPlane input order: roll, pitch, throttle, yaw.
  channels[0] = rcMicrosecondsToSbus(channelAileron);
  channels[1] = rcMicrosecondsToSbus(channelElevator);
  channels[2] = rcMicrosecondsToSbus(channelThrottle);
  channels[3] = rcMicrosecondsToSbus(channelRudder);
  channels[4] = rcMicrosecondsToSbus(AuxChannels::pulse(lastAuxFlags, AuxChannels::CH5));
  channels[5] = rcMicrosecondsToSbus(AuxChannels::pulse(lastAuxFlags, AuxChannels::CH6));

  uint8_t frame[SBUS_FRAME_SIZE] = {0};
  frame[0] = 0x0F;
  packSbusChannels(channels, &frame[1]);
  // Flags and footer are zero for fresh valid controls. On radio loss,
  // stop transmitting so FC receiver-loss handling remains authoritative.

  flightSerial.write(frame, sizeof(frame));
  sbusFrames++;
}

static void handleBindPacket(const uint8_t *buffer, uint8_t length) {
  if (!bindMode || length != sizeof(BindPacket)) return;

  BindPacket packet;
  memcpy(&packet, buffer, sizeof(packet));
  if (packet.magic != BIND_MAGIC || packet.code == 0) return;

  saveBindCode(packet.code);
  bindMode = false;
  bindRestartRequired = bindPlugBoot;
  haveValidControl = false;
  digitalWrite(LED_BUILTIN, HIGH);
  delay(400);
  digitalWrite(LED_BUILTIN, LOW);

  if (ENABLE_USB_DEBUG) {
    Serial.print("Stored bind code: ");
    Serial.println(packet.code);
  }
}

static void handleControlPacket(const uint8_t *buffer, uint8_t length, uint32_t nowMs) {
  if (bindMode || bindRestartRequired) return;
  if (length != sizeof(ControlPacket)) {
    malformedPackets++;
    return;
  }

  ControlPacket packet;
  memcpy(&packet, buffer, sizeof(packet));
  if (!controlPacketValid(packet)) {
    malformedPackets++;
    return;
  }

  const uint16_t packetBindCode = packet.flags & 0x7FFF;
  if (bindStore.magic != BIND_MAGIC ||
      bindStore.bindCode == 0 ||
      packetBindCode != bindStore.bindCode) {
    rejectedPackets++;
    return;
  }

  channelRudder = packet.ch_rud;
  channelAileron = packet.ch_ail;
  channelElevator = packet.ch_ele;
  channelThrottle = packet.ch_thr;
  lastSequence = packet.seq;
  lastAuxFlags = packet.aux_flags;
  lastRssi = rf95.lastRssi();
  lastAcceptedPacketMs = nowMs;
  haveValidControl = true;
  acceptedPackets++;
}

void setup() {
  if (ENABLE_USB_DEBUG) {
    Serial.begin(115200);
    delay(50);
  }

  pinMode(LED_BUILTIN, OUTPUT);
  pinMode(PIN_BIND_BTN, INPUT_PULLUP);
  pinMode(PIN_BIND_PLUG, INPUT_PULLUP);
  uint8_t lowSamples = 0;
  for (uint8_t i = 0; i < 8; ++i) {
    if (digitalRead(PIN_BIND_PLUG) == LOW) ++lowSamples;
    delay(2);
  }
  bindPlugBoot = lowSamples == 8;
  bindMode = digitalRead(PIN_BIND_BTN) == LOW || bindPlugBoot;
  bindStore = loadBindStore();

  flightSerial.begin(SBUS_BAUD);

  resetRadio();
  if (!rf95.init()) {
    if (ENABLE_USB_DEBUG) Serial.println("RFM95 initialization failed");
    while (true) {
      digitalWrite(LED_BUILTIN, !digitalRead(LED_BUILTIN));
      delay(100);
    }
  }
  rf95.setModemConfig(MODEM);
  rf95.setFrequency(RF95_FREQ);

  if (ENABLE_USB_DEBUG) {
    Serial.println("Receiver V4 ArduPlane SBUS prototype ready");
    Serial.println("SBUS UART: Serial5 PB22/TX PB23/RX at 100000 baud 8E2 NON-INVERTED");
    Serial.print("Stored bind code: ");
    Serial.println((bindStore.magic == BIND_MAGIC) ? bindStore.bindCode : 0);
    if (bindMode) Serial.println("Bind mode active");
  }
}

static void serviceUsbStatus() {
  static char command[16];
  static uint8_t length = 0;
  while (Serial.available()) {
    const char c = (char)Serial.read();
    if (c == '\r') continue;
    if (c == '\n') {
      command[length] = 0;
      if (strcmp(command, "STATUS") == 0) {
        Serial.print("STATUS firmware=rx-sbus-v2-bindplug tx=PB22 baud=100000 format=8E2 inverted=no bind=");
        Serial.print(bindStore.bindCode);
        Serial.print(" bindMode="); Serial.print(bindMode);
        Serial.print(" bindPlug="); Serial.print(bindPlugBoot);
        Serial.print(" restartRequired="); Serial.print(bindRestartRequired);
        Serial.print(" accepted="); Serial.print(acceptedPackets);
        Serial.print(" frames="); Serial.println(sbusFrames);
      }
      length = 0;
    } else if (length < sizeof(command)-1) {
      command[length++] = c;
    } else {
      length = 0;
    }
  }
}

void loop() {
  serviceUsbStatus();
  const uint32_t nowMs = millis();

  if (rf95.available()) {
    uint8_t buffer[sizeof(ControlPacket)];
    uint8_t length = sizeof(buffer);
    if (rf95.recv(buffer, &length)) {
      if (bindMode && length == sizeof(BindPacket)) {
        handleBindPacket(buffer, length);
      } else {
        handleControlPacket(buffer, length, nowMs);
      }
    }
  }

  const bool linkFresh = !bindMode && !bindRestartRequired && haveValidControl &&
      (uint32_t)(nowMs - lastAcceptedPacketMs) <= SBUS_LINK_TIMEOUT_MS;

  const uint32_t nowUs = micros();
  if (linkFresh &&
      (uint32_t)(nowUs - lastSbusFrameUs) >= SBUS_FRAME_PERIOD_US) {
    lastSbusFrameUs = nowUs;
    sendSbusChannels();
  }

  digitalWrite(LED_BUILTIN, bindMode ? ((nowMs / 500) & 1) : linkFresh);

  if (ENABLE_USB_DEBUG && nowMs - lastDebugMs >= USB_DEBUG_PERIOD_MS) {
    lastDebugMs = nowMs;
    Serial.print("SBUS link=");
    Serial.print(linkFresh ? "fresh" : "lost");
    Serial.print(" accepted=");
    Serial.print(acceptedPackets);
    Serial.print(" rejected=");
    Serial.print(rejectedPackets);
    Serial.print(" malformed=");
    Serial.print(malformedPackets);
    Serial.print(" frames=");
    Serial.print(sbusFrames);
    Serial.print(" seq=");
    Serial.print(lastSequence);
    Serial.print(" rssi=");
    Serial.print(lastRssi);
    Serial.print(" channels(a/e/t/r)=");
    Serial.print(channelAileron);
    Serial.print(',');
    Serial.print(channelElevator);
    Serial.print(',');
    Serial.print(channelThrottle);
    Serial.print(',');
    Serial.print(channelRudder);
    Serial.print(" aux=0x");
    if (lastAuxFlags < 0x10) Serial.print('0');
    Serial.println(lastAuxFlags, HEX);
  }
}
