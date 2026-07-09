#include <Arduino.h>
#include <Wire.h>
#include <math.h>

// Rx V4 prop-removed diagnostic.  This sketch intentionally does not drive
// servos or radio.  It reports raw gyro axes and accel tilt while the airframe
// is moved through controlled roll/pitch tests.
const uint8_t ADDR_LOW = 0x6A;
const uint8_t ADDR_HIGH = 0x6B;
const uint8_t WHO_AM_I = 0x0F;
const uint8_t CTRL1_XL = 0x10;
const uint8_t CTRL2_G = 0x11;
const uint8_t CTRL3_C = 0x12;
const uint8_t OUTX_L_G = 0x22;
const float GYRO_DPS_PER_LSB = 0.00875f;
const float ACCEL_G_PER_LSB = 0.000061f;
const float DEG_PER_RAD = 57.2957795f;

uint8_t imuAddr = 0;

static bool writeReg(uint8_t reg, uint8_t value) {
  Wire.beginTransmission(imuAddr);
  Wire.write(reg);
  Wire.write(value);
  return Wire.endTransmission() == 0;
}

static bool readBytes(uint8_t reg, uint8_t *buf, uint8_t len) {
  Wire.beginTransmission(imuAddr);
  Wire.write(reg);
  if (Wire.endTransmission(false) != 0) return false;
  if (Wire.requestFrom((int)imuAddr, (int)len) != len) return false;
  for (uint8_t i = 0; i < len; ++i) buf[i] = Wire.read();
  return true;
}

static int16_t s16(uint8_t lo, uint8_t hi) {
  return (int16_t)((uint16_t)lo | ((uint16_t)hi << 8));
}

static bool beginImu(uint8_t addr) {
  uint8_t who = 0;
  Wire.beginTransmission(addr);
  Wire.write(WHO_AM_I);
  if (Wire.endTransmission(false) != 0 || Wire.requestFrom((int)addr, 1) != 1) return false;
  who = Wire.read();
  if (who != 0x69 && who != 0x6A && who != 0x6C) return false;
  imuAddr = addr;
  return writeReg(CTRL3_C, 0x44) && writeReg(CTRL1_XL, 0x40) && writeReg(CTRL2_G, 0x40);
}

void setup() {
  Serial.begin(115200);
  Wire.begin();
  Wire.setClock(100000);
  delay(50);
  bool found = beginImu(ADDR_LOW) || beginImu(ADDR_HIGH);
  Serial.println(found ? "RXV4_IMU_RATE_TEST_READY" : "RXV4_IMU_NOT_FOUND");
  Serial.println("Move one axis at a time: right-wing-down, left-wing-down, nose-up, nose-down.");
  Serial.println("Columns: gx_dps,gy_dps,gz_dps,roll_acc_deg,pitch_acc_deg");
}

void loop() {
  static uint32_t lastPrint = 0;
  if (millis() - lastPrint < 50) return;
  lastPrint = millis();
  uint8_t b[12];
  if (!readBytes(OUTX_L_G, b, sizeof(b))) {
    Serial.println("READ_FAIL");
    return;
  }
  float gx = s16(b[0], b[1]) * GYRO_DPS_PER_LSB;
  float gy = s16(b[2], b[3]) * GYRO_DPS_PER_LSB;
  float gz = s16(b[4], b[5]) * GYRO_DPS_PER_LSB;
  float ax = s16(b[6], b[7]) * ACCEL_G_PER_LSB;
  float ay = s16(b[8], b[9]) * ACCEL_G_PER_LSB;
  float az = s16(b[10], b[11]) * ACCEL_G_PER_LSB;
  float rollAcc = atan2f(ay, az) * DEG_PER_RAD;
  float pitchAcc = atan2f(-ax, sqrtf(ay * ay + az * az)) * DEG_PER_RAD;
  Serial.print("RATE ");
  Serial.print(gx, 2); Serial.print(',');
  Serial.print(gy, 2); Serial.print(',');
  Serial.print(gz, 2); Serial.print(',');
  Serial.print(rollAcc, 2); Serial.print(',');
  Serial.println(pitchAcc, 2);
}
