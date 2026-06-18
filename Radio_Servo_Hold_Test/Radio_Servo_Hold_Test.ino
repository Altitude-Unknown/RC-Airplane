#include <Arduino.h>
#include <SPI.h>
#include <RH_RF95.h>
#include <Servo.h>

// RX isolation test:
// - Servos are held at fixed outputs.
// - LoRa is initialized and packets are drained.
// - Received packets are not allowed to change servo positions.
//
// If this twitches, the radio/SPI activity or radio power is disturbing servo pulses.
// If this does not twitch, the twitch is coming from changing control values.

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

RH_RF95 rf95(RFM95_CS, RFM95_INT);
Servo svThrottle, svAileron, svElevator, svRudder;

void hardResetRadio() {
  pinMode(RFM95_RST, OUTPUT);
  digitalWrite(RFM95_RST, HIGH);
  delay(1);
  digitalWrite(RFM95_RST, LOW);
  delay(10);
  digitalWrite(RFM95_RST, HIGH);
  delay(10);
}

void writeFixedOutputs() {
  svThrottle.writeMicroseconds(RC_MIN);
  svAileron.writeMicroseconds(RC_MID);
  svElevator.writeMicroseconds(RC_MID);
  svRudder.writeMicroseconds(RC_MID);
}

void setup() {
  svThrottle.attach(PIN_SERVO_THROTTLE);
  svAileron.attach(PIN_SERVO_AILERON);
  svElevator.attach(PIN_SERVO_ELEVATOR);
  svRudder.attach(PIN_SERVO_RUDDER);
  writeFixedOutputs();

  hardResetRadio();
  if (rf95.init()) {
    rf95.setModemConfig(RH_RF95::Bw500Cr45Sf128);
    rf95.setFrequency(RF95_FREQ);
  }
}

void loop() {
  if (rf95.available()) {
    uint8_t buf[32];
    uint8_t len = sizeof(buf);
    rf95.recv(buf, &len);
  }
  delay(1);
}
