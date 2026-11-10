#include <Arduino.h>
#include <Wire.h>
#include <math.h>

const uint8_t LSM6DS_ADDR_LOW = 0x6A;
const uint8_t LSM6DS_ADDR_HIGH = 0x6B;

const uint8_t REG_WHO_AM_I = 0x0F;
const uint8_t REG_CTRL1_XL = 0x10;
const uint8_t REG_CTRL2_G = 0x11;
const uint8_t REG_CTRL3_C = 0x12;
const uint8_t REG_OUTX_L_G = 0x22;

const float GYRO_DPS_PER_LSB = 0.00875f;  // 245 dps full scale.
const float ACCEL_G_PER_LSB = 0.000061f;  // 2 g full scale.
const float DEG_PER_RAD = 57.2957795f;

const uint16_t SAMPLE_COUNT = 400;
const uint16_t SAMPLE_DELAY_MS = 5;

struct RawSample {
  int16_t gx;
  int16_t gy;
  int16_t gz;
  int16_t ax;
  int16_t ay;
  int16_t az;
};

struct Accumulator {
  double gx;
  double gy;
  double gz;
  double ax;
  double ay;
  double az;
};

uint8_t activeAddr = 0;
bool imuReady = false;

void printHex2(uint8_t v) {
  if (v < 16) Serial.print("0");
  Serial.print(v, HEX);
}

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
  for (uint8_t i = 0; i < len; ++i) {
    buf[i] = Wire.read();
  }
  return true;
}

int16_t s16(uint8_t lo, uint8_t hi) {
  return (int16_t)((uint16_t)lo | ((uint16_t)hi << 8));
}

bool readSample(RawSample &s) {
  uint8_t b[12];
  if (!readBytes(activeAddr, REG_OUTX_L_G, b, sizeof(b))) return false;

  s.gx = s16(b[0], b[1]);
  s.gy = s16(b[2], b[3]);
  s.gz = s16(b[4], b[5]);
  s.ax = s16(b[6], b[7]);
  s.ay = s16(b[8], b[9]);
  s.az = s16(b[10], b[11]);
  return true;
}

bool beginLsm6ds(uint8_t addr) {
  uint8_t who = 0;
  if (!readReg(addr, REG_WHO_AM_I, who)) return false;

  Serial.print("WHO_AM_I at 0x");
  printHex2(addr);
  Serial.print(" = 0x");
  printHex2(who);
  Serial.println();

  if (who != 0x69 && who != 0x6A && who != 0x6C) {
    Serial.println("Unexpected LSM6DS WHO_AM_I value.");
    return false;
  }

  if (!writeReg(addr, REG_CTRL3_C, 0x44)) return false;  // BDU + auto-increment.
  if (!writeReg(addr, REG_CTRL1_XL, 0x40)) return false; // Accel 104 Hz, +/-2g.
  if (!writeReg(addr, REG_CTRL2_G, 0x40)) return false;  // Gyro 104 Hz, 245 dps.

  activeAddr = addr;
  imuReady = true;
  return true;
}

void printPrompt() {
  Serial.println();
  Serial.println("Hold the receiver still in the requested attitude, then send:");
  Serial.println("  0 = LEVEL_FLIGHT");
  Serial.println("  p = PITCH_PLUS_30");
  Serial.println("  P = PITCH_MINUS_30");
  Serial.println("  r = ROLL_PLUS_30");
  Serial.println("  R = ROLL_MINUS_30");
  Serial.println("  s = one live sample");
  Serial.println("  h = this help");
  Serial.println();
}

const char *labelForCommand(char c) {
  switch (c) {
    case '0': return "LEVEL_FLIGHT";
    case 'p': return "PITCH_PLUS_30";
    case 'P': return "PITCH_MINUS_30";
    case 'r': return "ROLL_PLUS_30";
    case 'R': return "ROLL_MINUS_30";
    default: return "UNKNOWN";
  }
}

void printAngles(float axG, float ayG, float azG) {
  float rollDeg = atan2f(ayG, azG) * DEG_PER_RAD;
  float pitchDeg = atan2f(-axG, sqrtf(ayG * ayG + azG * azG)) * DEG_PER_RAD;
  float accelMag = sqrtf(axG * axG + ayG * ayG + azG * azG);

  Serial.print(" angles_deg roll=");
  Serial.print(rollDeg, 2);
  Serial.print(" pitch=");
  Serial.print(pitchDeg, 2);
  Serial.print(" accel_mag_g=");
  Serial.print(accelMag, 4);
}

void capturePose(const char *label) {
  if (!imuReady) {
    Serial.println("IMU is not ready.");
    return;
  }

  Serial.print("Capturing ");
  Serial.print(label);
  Serial.print(" for ");
  Serial.print((SAMPLE_COUNT * SAMPLE_DELAY_MS) / 1000.0f, 1);
  Serial.println(" s. Hold still...");

  Accumulator sum = {};
  uint16_t good = 0;

  for (uint16_t i = 0; i < SAMPLE_COUNT; ++i) {
    RawSample s;
    if (readSample(s)) {
      sum.gx += s.gx;
      sum.gy += s.gy;
      sum.gz += s.gz;
      sum.ax += s.ax;
      sum.ay += s.ay;
      sum.az += s.az;
      good++;
    }
    delay(SAMPLE_DELAY_MS);
  }

  if (good == 0) {
    Serial.println("No good IMU samples captured.");
    return;
  }

  float gxRaw = sum.gx / good;
  float gyRaw = sum.gy / good;
  float gzRaw = sum.gz / good;
  float axRaw = sum.ax / good;
  float ayRaw = sum.ay / good;
  float azRaw = sum.az / good;

  float gxDps = gxRaw * GYRO_DPS_PER_LSB;
  float gyDps = gyRaw * GYRO_DPS_PER_LSB;
  float gzDps = gzRaw * GYRO_DPS_PER_LSB;
  float axG = axRaw * ACCEL_G_PER_LSB;
  float ayG = ayRaw * ACCEL_G_PER_LSB;
  float azG = azRaw * ACCEL_G_PER_LSB;

  Serial.print("CAL ");
  Serial.print(label);
  Serial.print(" samples=");
  Serial.print(good);
  Serial.print(" raw_gxyz=");
  Serial.print(gxRaw, 2);
  Serial.print(",");
  Serial.print(gyRaw, 2);
  Serial.print(",");
  Serial.print(gzRaw, 2);
  Serial.print(" raw_axyz=");
  Serial.print(axRaw, 2);
  Serial.print(",");
  Serial.print(ayRaw, 2);
  Serial.print(",");
  Serial.print(azRaw, 2);
  Serial.print(" gyro_dps=");
  Serial.print(gxDps, 4);
  Serial.print(",");
  Serial.print(gyDps, 4);
  Serial.print(",");
  Serial.print(gzDps, 4);
  Serial.print(" accel_g=");
  Serial.print(axG, 4);
  Serial.print(",");
  Serial.print(ayG, 4);
  Serial.print(",");
  Serial.print(azG, 4);
  printAngles(axG, ayG, azG);
  Serial.println();
}

void printLiveSample() {
  RawSample s;
  if (!readSample(s)) {
    Serial.println("Sample read failed.");
    return;
  }

  float axG = s.ax * ACCEL_G_PER_LSB;
  float ayG = s.ay * ACCEL_G_PER_LSB;
  float azG = s.az * ACCEL_G_PER_LSB;

  Serial.print("LIVE raw_gxyz=");
  Serial.print(s.gx);
  Serial.print(",");
  Serial.print(s.gy);
  Serial.print(",");
  Serial.print(s.gz);
  Serial.print(" raw_axyz=");
  Serial.print(s.ax);
  Serial.print(",");
  Serial.print(s.ay);
  Serial.print(",");
  Serial.print(s.az);
  Serial.print(" accel_g=");
  Serial.print(axG, 4);
  Serial.print(",");
  Serial.print(ayG, 4);
  Serial.print(",");
  Serial.print(azG, 4);
  printAngles(axG, ayG, azG);
  Serial.println();
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
  Serial.println("Rx V4 LSM6DS IMU calibration readout");

  if (!beginLsm6ds(LSM6DS_ADDR_LOW)) {
    beginLsm6ds(LSM6DS_ADDR_HIGH);
  }

  if (imuReady) {
    Serial.print("LSM6DS ready at 0x");
    printHex2(activeAddr);
    Serial.println();
  } else {
    Serial.println("LSM6DS not detected at 0x6A or 0x6B.");
  }

  printPrompt();
}

void loop() {
  digitalWrite(LED_BUILTIN, (millis() / 500) % 2);

  if (Serial.available() <= 0) return;

  char c = Serial.read();
  if (c == '\r' || c == '\n') return;
  if (c == 'h' || c == '?') {
    printPrompt();
  } else if (c == 's') {
    printLiveSample();
  } else if (c == '0' || c == 'p' || c == 'P' || c == 'r' || c == 'R') {
    capturePose(labelForCommand(c));
  } else {
    Serial.println("Unknown command. Send h for help.");
  }
}
