#include <Arduino.h>
#include <SPI.h>
#include <Wire.h>
#include <RH_RF95.h>

#define RFM95_CS   8
#define RFM95_INT  3
#define RFM95_RST  4
#define RF95_FREQ  915.0

const int PIN_BIND_BTN = 10;

const int PIN_SERVO_THROTTLE = A0;
const int PIN_SERVO_AILERON  = A1;
const int PIN_SERVO_ELEVATOR = A2;
const int PIN_SERVO_RUDDER   = A3;

const uint8_t LSM6DS_ADDR_LOW = 0x6A;
const uint8_t LSM6DS_ADDR_HIGH = 0x6B;
const uint8_t REG_WHO_AM_I = 0x0F;

const uint16_t RC_MIN = 1000;
const uint16_t RC_MID = 1500;

RH_RF95 rf95(RFM95_CS, RFM95_INT);

bool radioOk = false;
uint32_t lastReportMs = 0;
uint32_t loopCount = 0;
uint32_t radioPackets = 0;

void printHex2(uint8_t v) {
  if (v < 16) Serial.print("0");
  Serial.print(v, HEX);
}

bool readReg(uint8_t addr, uint8_t reg, uint8_t &value) {
  Wire.beginTransmission(addr);
  Wire.write(reg);
  if (Wire.endTransmission(false) != 0) return false;
  if (Wire.requestFrom((int)addr, 1) != 1) return false;
  value = Wire.read();
  return true;
}

void hardResetRadio() {
  pinMode(RFM95_RST, OUTPUT);
  digitalWrite(RFM95_RST, HIGH);
  delay(1);
  digitalWrite(RFM95_RST, LOW);
  delay(10);
  digitalWrite(RFM95_RST, HIGH);
  delay(10);
}

void pulseServo(int pin, uint16_t us) {
  digitalWrite(pin, HIGH);
  delayMicroseconds(us);
  digitalWrite(pin, LOW);
}

void writeSafeServoFrame() {
  pulseServo(PIN_SERVO_THROTTLE, RC_MIN);
  pulseServo(PIN_SERVO_AILERON, RC_MID);
  pulseServo(PIN_SERVO_ELEVATOR, RC_MID);
  pulseServo(PIN_SERVO_RUDDER, RC_MID);
}

void printI2cLineLevels() {
#if defined(PIN_WIRE_SDA) && defined(PIN_WIRE_SCL)
  Serial.print("I2C lines SDA=");
  Serial.print(digitalRead(PIN_WIRE_SDA));
  Serial.print(" SCL=");
  Serial.println(digitalRead(PIN_WIRE_SCL));
#else
  Serial.println("I2C line pins not defined by board core");
#endif
}

void scanI2c() {
  uint8_t count = 0;
  Serial.println("I2C scan:");
  for (uint8_t address = 8; address < 120; ++address) {
    Wire.beginTransmission(address);
    uint8_t error = Wire.endTransmission();
    if (error == 0) {
      Serial.print("  found 0x");
      printHex2(address);
      Serial.println();
      count++;
    } else if (error == 4) {
      Serial.print("  unknown error at 0x");
      printHex2(address);
      Serial.println();
    }
  }
  Serial.print("I2C devices found: ");
  Serial.println(count);
}

void probeLsm6ds(uint8_t addr) {
  uint8_t who = 0;
  Serial.print("LSM6DS probe 0x");
  printHex2(addr);
  Serial.print(" -> ");
  if (readReg(addr, REG_WHO_AM_I, who)) {
    Serial.print("WHO_AM_I=0x");
    printHex2(who);
    if (who == 0x69 || who == 0x6A || who == 0x6C) {
      Serial.println(" OK");
    } else {
      Serial.println(" unexpected");
    }
  } else {
    Serial.println("no response");
  }
}

void setup() {
  pinMode(LED_BUILTIN, OUTPUT);
  pinMode(PIN_BIND_BTN, INPUT_PULLUP);

  pinMode(PIN_SERVO_THROTTLE, OUTPUT);
  pinMode(PIN_SERVO_AILERON, OUTPUT);
  pinMode(PIN_SERVO_ELEVATOR, OUTPUT);
  pinMode(PIN_SERVO_RUDDER, OUTPUT);
  digitalWrite(PIN_SERVO_THROTTLE, LOW);
  digitalWrite(PIN_SERVO_AILERON, LOW);
  digitalWrite(PIN_SERVO_ELEVATOR, LOW);
  digitalWrite(PIN_SERVO_RUDDER, LOW);

#if defined(PIN_WIRE_SDA) && defined(PIN_WIRE_SCL)
  pinMode(PIN_WIRE_SDA, INPUT_PULLUP);
  pinMode(PIN_WIRE_SCL, INPUT_PULLUP);
  delay(20);
#endif

  Serial.begin(115200);
  while (!Serial && millis() < 3000) { }

  Wire.begin();
  Wire.setClock(100000);
#if defined(WIRE_HAS_TIMEOUT)
  Wire.setTimeout(50);
#endif

  Serial.println();
  Serial.println("RxV4 basic diagnostic");
  Serial.println("Target: Adafruit Feather M0 / SAMD21");

  Serial.print("Bind pin D10 reads: ");
  Serial.println(digitalRead(PIN_BIND_BTN) == LOW ? "LOW / pressed" : "HIGH / idle");

  printI2cLineLevels();
  scanI2c();
  probeLsm6ds(LSM6DS_ADDR_LOW);
  probeLsm6ds(LSM6DS_ADDR_HIGH);

  Serial.println("Initializing RFM95...");
  hardResetRadio();
  radioOk = rf95.init();
  Serial.print("RFM95 init: ");
  Serial.println(radioOk ? "OK" : "FAIL");
  if (radioOk) {
    rf95.setModemConfig(RH_RF95::Bw500Cr45Sf128);
    bool freqOk = rf95.setFrequency(RF95_FREQ);
    Serial.print("RFM95 frequency 915.0 MHz: ");
    Serial.println(freqOk ? "OK" : "FAIL");
    Serial.print("RFM95 version reg: 0x");
    printHex2(rf95.spiRead(0x42));
    Serial.println();
  }

  Serial.println("Servo outputs: throttle=1000us, aileron/elevator/rudder=1500us at 50 Hz");
  Serial.println("Diagnostic running.");
}

void loop() {
  loopCount++;

  if (radioOk && rf95.available()) {
    uint8_t buf[32];
    uint8_t len = sizeof(buf);
    if (rf95.recv(buf, &len)) {
      radioPackets++;
    }
  }

  writeSafeServoFrame();

  uint32_t now = millis();
  if (now - lastReportMs >= 1000) {
    lastReportMs = now;
    digitalWrite(LED_BUILTIN, !digitalRead(LED_BUILTIN));
    Serial.print("heartbeat ms=");
    Serial.print(now);
    Serial.print(" loops=");
    Serial.print(loopCount);
    Serial.print(" bind=");
    Serial.print(digitalRead(PIN_BIND_BTN) == LOW ? "LOW" : "HIGH");
    Serial.print(" radio=");
    Serial.print(radioOk ? "OK" : "FAIL");
    Serial.print(" packets=");
    Serial.println(radioPackets);
  }

  uint32_t elapsedMs = millis() - now;
  if (elapsedMs < 20) {
    delay(20 - elapsedMs);
  }
}
