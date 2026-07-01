#include <Wire.h>

const uint8_t LSM6DS_ADDR_LOW = 0x6A;   // SA0 / address select tied to GND
const uint8_t LSM6DS_ADDR_HIGH = 0x6B;  // SA0 tied high

const uint8_t REG_WHO_AM_I = 0x0F;
const uint8_t REG_CTRL1_XL = 0x10;
const uint8_t REG_CTRL2_G = 0x11;
const uint8_t REG_CTRL3_C = 0x12;
const uint8_t REG_OUTX_L_G = 0x22;

uint8_t activeAddr = LSM6DS_ADDR_LOW;
bool sensorReady = false;

bool writeReg(uint8_t addr, uint8_t reg, uint8_t value) {
  Wire.beginTransmission(addr);
  Wire.write(reg);
  Wire.write(value);
  return Wire.endTransmission() == 0;
}

bool readReg(uint8_t addr, uint8_t reg, uint8_t &value) {
  Wire.beginTransmission(addr);
  Wire.write(reg);
  if (Wire.endTransmission(false) != 0) return false;
  if (Wire.requestFrom((int)addr, 1) != 1) return false;
  value = Wire.read();
  return true;
}

bool readBytes(uint8_t addr, uint8_t reg, uint8_t *buf, uint8_t len) {
  Wire.beginTransmission(addr);
  Wire.write(reg);
  if (Wire.endTransmission(false) != 0) return false;
  if (Wire.requestFrom((int)addr, (int)len) != len) return false;
  for (uint8_t i = 0; i < len; ++i) buf[i] = Wire.read();
  return true;
}

void printHex2(uint8_t v) {
  if (v < 16) Serial.print("0");
  Serial.print(v, HEX);
}

void printAddrResult(uint8_t addr) {
  Wire.beginTransmission(addr);
  uint8_t err = Wire.endTransmission();
  Serial.print("Probe 0x");
  printHex2(addr);
  Serial.print(" -> ");
  Serial.println(err == 0 ? "ACK" : "no response");
}

bool beginLsm6ds(uint8_t addr) {
  uint8_t who = 0;
  if (!readReg(addr, REG_WHO_AM_I, who)) return false;

  Serial.print("WHO_AM_I at 0x");
  printHex2(addr);
  Serial.print(" = 0x");
  printHex2(who);
  Serial.println();

  // Common LSM6DS family IDs include 0x69, 0x6A, and 0x6C depending on variant.
  if (who != 0x69 && who != 0x6A && who != 0x6C) {
    Serial.println("Unexpected WHO_AM_I for LSM6DS family.");
    return false;
  }

  // CTRL3_C: block data update + register auto-increment.
  if (!writeReg(addr, REG_CTRL3_C, 0x44)) return false;
  // CTRL1_XL: accel 104 Hz, +/-2g.
  if (!writeReg(addr, REG_CTRL1_XL, 0x40)) return false;
  // CTRL2_G: gyro 104 Hz, 245 dps.
  if (!writeReg(addr, REG_CTRL2_G, 0x40)) return false;

  uint8_t ctrl1 = 0, ctrl2 = 0, ctrl3 = 0;
  readReg(addr, REG_CTRL1_XL, ctrl1);
  readReg(addr, REG_CTRL2_G, ctrl2);
  readReg(addr, REG_CTRL3_C, ctrl3);
  Serial.print("Configured CTRL1_XL=0x");
  printHex2(ctrl1);
  Serial.print(" CTRL2_G=0x");
  printHex2(ctrl2);
  Serial.print(" CTRL3_C=0x");
  printHex2(ctrl3);
  Serial.println();
  return true;
}

int16_t s16(uint8_t lo, uint8_t hi) {
  return (int16_t)((uint16_t)lo | ((uint16_t)hi << 8));
}

void setup() {
  pinMode(LED_BUILTIN, OUTPUT);
  Serial.begin(115200);
  while (!Serial && millis() < 3000) { }

#if defined(PIN_WIRE_SDA) && defined(PIN_WIRE_SCL)
  pinMode(PIN_WIRE_SDA, INPUT_PULLUP);
  pinMode(PIN_WIRE_SCL, INPUT_PULLUP);
  delay(20);
#endif

  Wire.begin();
  Wire.setClock(100000);
#if defined(WIRE_HAS_TIMEOUT)
  Wire.setTimeout(50);
#endif

  Serial.println();
  Serial.println("LSM6DS I2C gyro/accel diagnostic");
  Serial.println("SA0/address select expected LOW -> 0x6A");
#if defined(PIN_WIRE_SDA) && defined(PIN_WIRE_SCL)
  Serial.print("Idle lines: SDA=");
  Serial.print(digitalRead(PIN_WIRE_SDA));
  Serial.print(" SCL=");
  Serial.println(digitalRead(PIN_WIRE_SCL));
#endif

  printAddrResult(LSM6DS_ADDR_LOW);
  printAddrResult(LSM6DS_ADDR_HIGH);

  if (beginLsm6ds(LSM6DS_ADDR_LOW)) {
    activeAddr = LSM6DS_ADDR_LOW;
    sensorReady = true;
  } else if (beginLsm6ds(LSM6DS_ADDR_HIGH)) {
    activeAddr = LSM6DS_ADDR_HIGH;
    sensorReady = true;
  }

  Serial.println(sensorReady ? "LSM6DS ready. Move/rotate the board to watch values change." :
                               "LSM6DS not ready. Check power, SDA/SCL, pullups, orientation, and SA0 strap.");
}

void loop() {
  digitalWrite(LED_BUILTIN, !digitalRead(LED_BUILTIN));

  if (!sensorReady) {
#if defined(PIN_WIRE_SDA) && defined(PIN_WIRE_SCL)
    Serial.print("Lines now: SDA=");
    Serial.print(digitalRead(PIN_WIRE_SDA));
    Serial.print(" SCL=");
    Serial.println(digitalRead(PIN_WIRE_SCL));
#endif
    printAddrResult(LSM6DS_ADDR_LOW);
    printAddrResult(LSM6DS_ADDR_HIGH);
    delay(2000);
    return;
  }

  uint8_t b[12];
  if (!readBytes(activeAddr, REG_OUTX_L_G, b, sizeof(b))) {
    Serial.println("Sample read failed");
    delay(500);
    return;
  }

  int16_t gx = s16(b[0], b[1]);
  int16_t gy = s16(b[2], b[3]);
  int16_t gz = s16(b[4], b[5]);
  int16_t ax = s16(b[6], b[7]);
  int16_t ay = s16(b[8], b[9]);
  int16_t az = s16(b[10], b[11]);

  Serial.print("0x");
  printHex2(activeAddr);
  Serial.print(" G raw x/y/z: ");
  Serial.print(gx);
  Serial.print(", ");
  Serial.print(gy);
  Serial.print(", ");
  Serial.print(gz);
  Serial.print(" | A raw x/y/z: ");
  Serial.print(ax);
  Serial.print(", ");
  Serial.print(ay);
  Serial.print(", ");
  Serial.println(az);

  delay(250);
}
