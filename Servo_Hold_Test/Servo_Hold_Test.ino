#include <Arduino.h>
#include <Servo.h>

// Feather M0 RX steady output test.
// No LoRa, no serial chatter, no changing commands.
const int PIN_SERVO_THROTTLE = A0;
const int PIN_SERVO_AILERON  = A1;
const int PIN_SERVO_ELEVATOR = A2;
const int PIN_SERVO_RUDDER   = A3;

const uint16_t RC_MIN = 1000;
const uint16_t RC_MID = 1500;

Servo svThrottle, svAileron, svElevator, svRudder;

void setup() {
  svThrottle.attach(PIN_SERVO_THROTTLE);
  svAileron.attach(PIN_SERVO_AILERON);
  svElevator.attach(PIN_SERVO_ELEVATOR);
  svRudder.attach(PIN_SERVO_RUDDER);

  svThrottle.writeMicroseconds(RC_MIN);
  svAileron.writeMicroseconds(RC_MID);
  svElevator.writeMicroseconds(RC_MID);
  svRudder.writeMicroseconds(RC_MID);
}

void loop() {
  delay(1000);
}
