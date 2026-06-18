#include <Arduino.h>
#include <Servo.h>

// Feather M0 RX output pin test.
// Throttle stays at RC_MIN for safety. Aileron, elevator, and rudder sweep.
const int PIN_SERVO_THROTTLE = A0;
const int PIN_SERVO_AILERON  = A1;
const int PIN_SERVO_ELEVATOR = A2;
const int PIN_SERVO_RUDDER   = A3;

const uint16_t RC_MIN = 1000;
const uint16_t RC_MID = 1500;
const uint16_t RC_LOW = 1200;
const uint16_t RC_HIGH = 1800;

Servo svThrottle, svAileron, svElevator, svRudder;

void writeAllSurfaces(uint16_t us) {
  svAileron.writeMicroseconds(us);
  svElevator.writeMicroseconds(us);
  svRudder.writeMicroseconds(us);
}

void setup() {
  Serial.begin(115200);
  while (!Serial && millis() < 1500) { }

  svThrottle.attach(PIN_SERVO_THROTTLE);
  svAileron.attach(PIN_SERVO_AILERON);
  svElevator.attach(PIN_SERVO_ELEVATOR);
  svRudder.attach(PIN_SERVO_RUDDER);

  svThrottle.writeMicroseconds(RC_MIN);
  writeAllSurfaces(RC_MID);

  Serial.println("Servo output test ready");
  Serial.println("Throttle A0 held at 1000 us");
  Serial.println("A1/A2/A3 sweep 1200 -> 1800 -> 1500 us");
}

void loop() {
  Serial.println("Surfaces 1200 us");
  svThrottle.writeMicroseconds(RC_MIN);
  writeAllSurfaces(RC_LOW);
  delay(1200);

  Serial.println("Surfaces 1800 us");
  svThrottle.writeMicroseconds(RC_MIN);
  writeAllSurfaces(RC_HIGH);
  delay(1200);

  Serial.println("Surfaces 1500 us");
  svThrottle.writeMicroseconds(RC_MIN);
  writeAllSurfaces(RC_MID);
  delay(1200);
}
