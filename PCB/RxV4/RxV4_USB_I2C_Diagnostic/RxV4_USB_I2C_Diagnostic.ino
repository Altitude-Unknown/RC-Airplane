#include <Arduino.h>
#include <Wire.h>

const int PIN_BIND_BTN = 10;

const uint8_t LSM6DS_ADDR_LOW = 0x6A;
const uint8_t LSM6DS_ADDR_HIGH = 0x6B;
const uint8_t REG_WHO_AM_I = 0x0F;

uint32_t lastReportMs = 0;

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
  Serial.println("RxV4 USB/I2C diagnostic");
  Serial.print("Bind pin D10 reads: ");
  Serial.println(digitalRead(PIN_BIND_BTN) == LOW ? "LOW / pressed" : "HIGH / idle");
  printI2cLineLevels();
  scanI2c();
  probeLsm6ds(LSM6DS_ADDR_LOW);
  probeLsm6ds(LSM6DS_ADDR_HIGH);
  Serial.println("Diagnostic running.");
}

void loop() {
  uint32_t now = millis();
  if (now - lastReportMs >= 1000) {
    lastReportMs = now;
    digitalWrite(LED_BUILTIN, !digitalRead(LED_BUILTIN));
    Serial.print("heartbeat ms=");
    Serial.print(now);
    Serial.print(" bind=");
    Serial.print(digitalRead(PIN_BIND_BTN) == LOW ? "LOW" : "HIGH");
    Serial.print(" ");
    printI2cLineLevels();
  }
}
