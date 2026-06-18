#include <Arduino.h>
#include <SPI.h>
#include <RH_RF95.h>

// RX isolation test:
// - No Servo library.
// - Servo pulses are generated manually once every 20 ms.
// - Interrupts are disabled only during the pulse train, so RadioHead cannot
//   stretch a servo pulse with RFM95/SPI interrupt work.

#define RFM95_CS   8
#define RFM95_INT  3
#define RFM95_RST  4
#define RF95_FREQ  915.0

const int PIN_SERVO_THROTTLE = A0;
const int PIN_SERVO_AILERON  = A1;
const int PIN_SERVO_ELEVATOR = A2;
const int PIN_SERVO_RUDDER   = A3;

const uint16_t RC_MIN = 1000;
const uint16_t RC_MID = 1500;
const uint32_t FRAME_US = 20000;

RH_RF95 rf95(RFM95_CS, RFM95_INT);

void hardResetRadio() {
  pinMode(RFM95_RST, OUTPUT);
  digitalWrite(RFM95_RST, HIGH);
  delay(1);
  digitalWrite(RFM95_RST, LOW);
  delay(10);
  digitalWrite(RFM95_RST, HIGH);
  delay(10);
}

static inline void writePulse(int pin, uint16_t us) {
  digitalWrite(pin, HIGH);
  delayMicroseconds(us);
  digitalWrite(pin, LOW);
}

void writeServoFrame() {
  noInterrupts();
  writePulse(PIN_SERVO_THROTTLE, RC_MIN);
  writePulse(PIN_SERVO_AILERON, RC_MID);
  writePulse(PIN_SERVO_ELEVATOR, RC_MID);
  writePulse(PIN_SERVO_RUDDER, RC_MID);
  interrupts();
}

void setup() {
  pinMode(PIN_SERVO_THROTTLE, OUTPUT);
  pinMode(PIN_SERVO_AILERON, OUTPUT);
  pinMode(PIN_SERVO_ELEVATOR, OUTPUT);
  pinMode(PIN_SERVO_RUDDER, OUTPUT);
  digitalWrite(PIN_SERVO_THROTTLE, LOW);
  digitalWrite(PIN_SERVO_AILERON, LOW);
  digitalWrite(PIN_SERVO_ELEVATOR, LOW);
  digitalWrite(PIN_SERVO_RUDDER, LOW);

  hardResetRadio();
  if (rf95.init()) {
    rf95.setModemConfig(RH_RF95::Bw500Cr45Sf128);
    rf95.setFrequency(RF95_FREQ);
  }
}

void loop() {
  uint32_t frameStart = micros();
  writeServoFrame();

  while ((uint32_t)(micros() - frameStart) < FRAME_US) {
    if (rf95.available()) {
      uint8_t buf[32];
      uint8_t len = sizeof(buf);
      rf95.recv(buf, &len);
    }
  }
}
