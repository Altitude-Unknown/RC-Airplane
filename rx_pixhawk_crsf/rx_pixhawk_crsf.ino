/*
  Walach Aviation Receiver V4 -> Pixhawk CRSF prototype

  This is intentionally a separate sketch from rx_firmware/rx_firmware.ino.
  The proven standalone receiver remains unchanged and continues to drive four
  PWM servo outputs. This sketch instead sends the four received controls to a
  Pixhawk-compatible UART as CRSF channel frames.

  Receiver V4 UART header (Adafruit Feather M0 core mapping):
    TX = PB22 / package pin 37 / Arduino D30 / Serial5 TX
    RX = PB23 / package pin 38 / Arduino D31 / Serial5 RX

  Bench prototype only. Do not fly until UART timing, channel mapping, receiver
  loss, Pixhawk failsafe, range, and power behavior have all been validated.
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

// Send CRSF at 100 Hz while the LoRa link is fresh. If accepted packets stop,
// stop sending RC frames so ArduPilot sees receiver loss and invokes its own
// configured RC failsafe. Do not replace loss with centered valid channels.
const uint32_t CRSF_FRAME_PERIOD_US = 10000;
const uint32_t CRSF_LINK_TIMEOUT_MS = 300;
const uint32_t USB_DEBUG_PERIOD_MS  = 1000;

// ------------------------------
// CRSF UART and frame constants
// ------------------------------
const uint32_t CRSF_BAUD = 416666;
const uint8_t CRSF_ADDRESS_FLIGHT_CONTROLLER = 0xC8;
const uint8_t CRSF_FRAMETYPE_RC_CHANNELS_PACKED = 0x16;
const uint8_t CRSF_CHANNEL_COUNT = 16;
const uint8_t CRSF_CHANNEL_PAYLOAD_SIZE = 22;
const uint8_t CRSF_FRAME_SIZE = 26;

// The standard Feather M0 variant exposes PB22/PB23 as Serial5, but the custom
// Altitude Unknown RX target currently inherits feather_m0_express, whose
// variant constructs SERCOM5 without exposing a Serial5 Uart object or D30/D31
// pin-table entries. Configure the same peripheral and physical pins directly
// so this sketch builds correctly for the actual receiver board target.
class ReceiverV4CrsfUart {
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

    // 16x arithmetic baud mode. At 48 MHz this produces the CRSF rate with
    // substantially less error than the SAMD21 fractional integer divisor.
    const uint64_t scaled = (uint64_t)65536 * 16 * baud;
    const uint16_t baudRegister =
        (uint16_t)(65536ULL - ((scaled + SystemCoreClock / 2) / SystemCoreClock));

    SERCOM5->USART.CTRLA.reg = SERCOM_USART_CTRLA_MODE_USART_INT_CLK |
                               SERCOM_USART_CTRLA_SAMPR(0) |
                               SERCOM_USART_CTRLA_TXPO(1) |
                               SERCOM_USART_CTRLA_RXPO(3) |
                               SERCOM_USART_CTRLA_DORD;
    SERCOM5->USART.BAUD.reg = baudRegister;
    SERCOM5->USART.CTRLB.reg = SERCOM_USART_CTRLB_CHSIZE(0) |
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

ReceiverV4CrsfUart pixhawkSerial;

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
bool haveValidControl = false;

uint16_t channelRudder = RC_MID;
uint16_t channelAileron = RC_MID;
uint16_t channelElevator = RC_MID;
uint16_t channelThrottle = RC_MIN;
uint16_t lastSequence = 0;
uint8_t lastAuxFlags = 0;
int16_t lastRssi = 0;

uint32_t lastAcceptedPacketMs = 0;
uint32_t lastCrsfFrameUs = 0;
uint32_t lastDebugMs = 0;
uint32_t acceptedPackets = 0;
uint32_t rejectedPackets = 0;
uint32_t malformedPackets = 0;
uint32_t crsfFrames = 0;

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

// CRC-8/DVB-S2, used by CRSF for the type and payload bytes.
static uint8_t crsfCrc8(const uint8_t *data, uint8_t length) {
  uint8_t crc = 0;
  while (length--) {
    crc ^= *data++;
    for (uint8_t bit = 0; bit < 8; ++bit) {
      crc = (crc & 0x80) ? (uint8_t)((crc << 1) ^ 0xD5) : (uint8_t)(crc << 1);
    }
  }
  return crc;
}

// CRSF nominal channel limits are 172..1811. Map the receiver's validated
// 1000..2000 us values across that range and leave clamping in this boundary.
static uint16_t rcMicrosecondsToCrsf(uint16_t microseconds) {
  if (microseconds < RC_MIN) microseconds = RC_MIN;
  if (microseconds > RC_MAX) microseconds = RC_MAX;
  return (uint16_t)(172UL +
      (((uint32_t)(microseconds - RC_MIN) * (1811UL - 172UL) + 500UL) / 1000UL));
}

static void packCrsfChannels(const uint16_t channels[CRSF_CHANNEL_COUNT],
                             uint8_t payload[CRSF_CHANNEL_PAYLOAD_SIZE]) {
  memset(payload, 0, CRSF_CHANNEL_PAYLOAD_SIZE);

  uint32_t accumulator = 0;
  uint8_t accumulatorBits = 0;
  uint8_t outputIndex = 0;

  for (uint8_t channel = 0; channel < CRSF_CHANNEL_COUNT; ++channel) {
    accumulator |= ((uint32_t)channels[channel] & 0x07FFUL) << accumulatorBits;
    accumulatorBits += 11;

    while (accumulatorBits >= 8) {
      payload[outputIndex++] = (uint8_t)(accumulator & 0xFF);
      accumulator >>= 8;
      accumulatorBits -= 8;
    }
  }
}

static void sendCrsfChannels() {
  uint16_t channels[CRSF_CHANNEL_COUNT];
  const uint16_t neutral = rcMicrosecondsToCrsf(RC_MID);
  for (uint8_t index = 0; index < CRSF_CHANNEL_COUNT; ++index) {
    channels[index] = neutral;
  }

  // Standard ArduPlane input order: roll, pitch, throttle, yaw.
  channels[0] = rcMicrosecondsToCrsf(channelAileron);
  channels[1] = rcMicrosecondsToCrsf(channelElevator);
  channels[2] = rcMicrosecondsToCrsf(channelThrottle);
  channels[3] = rcMicrosecondsToCrsf(channelRudder);

  uint8_t frame[CRSF_FRAME_SIZE];
  frame[0] = CRSF_ADDRESS_FLIGHT_CONTROLLER;
  frame[1] = 24;  // Type + 22-byte payload + CRC.
  frame[2] = CRSF_FRAMETYPE_RC_CHANNELS_PACKED;
  packCrsfChannels(channels, &frame[3]);
  frame[25] = crsfCrc8(&frame[2], 23);

  pixhawkSerial.write(frame, sizeof(frame));
  crsfFrames++;
}

static void handleBindPacket(const uint8_t *buffer, uint8_t length) {
  if (!bindMode || length != sizeof(BindPacket)) return;

  BindPacket packet;
  memcpy(&packet, buffer, sizeof(packet));
  if (packet.magic != BIND_MAGIC || packet.code == 0) return;

  saveBindCode(packet.code);
  bindMode = false;
  digitalWrite(LED_BUILTIN, HIGH);
  delay(400);
  digitalWrite(LED_BUILTIN, LOW);

  if (ENABLE_USB_DEBUG) {
    Serial.print("Stored bind code: ");
    Serial.println(packet.code);
  }
}

static void handleControlPacket(const uint8_t *buffer, uint8_t length, uint32_t nowMs) {
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
  if (bindStore.magic == BIND_MAGIC &&
      bindStore.bindCode != 0 &&
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
  bindMode = digitalRead(PIN_BIND_BTN) == LOW;
  bindStore = loadBindStore();

  pixhawkSerial.begin(CRSF_BAUD);

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
    Serial.println("Receiver V4 Pixhawk CRSF prototype ready");
    Serial.println("CRSF UART: Serial5 PB22/TX PB23/RX at 416666 baud");
    Serial.print("Stored bind code: ");
    Serial.println((bindStore.magic == BIND_MAGIC) ? bindStore.bindCode : 0);
    if (bindMode) Serial.println("Bind mode active");
  }
}

void loop() {
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

  const bool linkFresh = haveValidControl &&
      (uint32_t)(nowMs - lastAcceptedPacketMs) <= CRSF_LINK_TIMEOUT_MS;

  const uint32_t nowUs = micros();
  if (linkFresh &&
      (uint32_t)(nowUs - lastCrsfFrameUs) >= CRSF_FRAME_PERIOD_US) {
    lastCrsfFrameUs = nowUs;
    sendCrsfChannels();
  }

  digitalWrite(LED_BUILTIN, bindMode ? ((nowMs / 500) & 1) : linkFresh);

  if (ENABLE_USB_DEBUG && nowMs - lastDebugMs >= USB_DEBUG_PERIOD_MS) {
    lastDebugMs = nowMs;
    Serial.print("CRSF link=");
    Serial.print(linkFresh ? "fresh" : "lost");
    Serial.print(" accepted=");
    Serial.print(acceptedPackets);
    Serial.print(" rejected=");
    Serial.print(rejectedPackets);
    Serial.print(" malformed=");
    Serial.print(malformedPackets);
    Serial.print(" frames=");
    Serial.print(crsfFrames);
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
