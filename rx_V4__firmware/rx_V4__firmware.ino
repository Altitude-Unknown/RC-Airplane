/*
  =======================================================
  LoRa RC Receiver V4 Autolevel Experiment (SAMD21) v0.1
  =======================================================
  This sketch is the experimental branch for the Rx V4 PCB.

  Goals for this version:
  - Preserve the proven LoRa receiver behavior and safety structure.
  - Add IMU bring-up for the on-board LSM6DS gyro/accelerometer.
  - Add a simple "sticks released" autolevel scaffold for bench testing.
  - Reserve a clean place for pressure-sensor altitude hold using the Rx V4
    MS5607-02BA03 pressure sensor once the interface and live readings are
    confirmed on hardware.

  Important:
  - The flight-proven receiver remains in rx_firmware/rx_firmware.ino.
  - This file is intentionally the experimental one for Rx V4 work.
  - Do not fly this version until it is bench-tested and tuned.
*/

#include <SPI.h>
#include <Wire.h>
#include <RH_RF95.h>
#include <FlashStorage_SAMD.h>
#include <string.h>
#include <math.h>

#if defined(ARDUINO_ARCH_SAMD)
  #include "wiring_private.h"
#endif

// ------------------------------
// LoRa wiring
// ------------------------------
#define RFM95_CS   8
#define RFM95_INT  3
#define RFM95_RST  4
#define RF95_FREQ  915.0
RH_RF95 rf95(RFM95_CS, RFM95_INT);
const RH_RF95::ModemConfigChoice MODEM = RH_RF95::Bw500Cr45Sf128;

// ------------------------------
// Outputs
// ------------------------------
const int PIN_SERVO_THROTTLE = A0;
const int PIN_SERVO_AILERON  = A1;
const int PIN_SERVO_ELEVATOR = A2;
const int PIN_SERVO_RUDDER   = A3;

// ------------------------------
// Bind button
// ------------------------------
const int PIN_BIND_BTN = 10;

// ------------------------------
// RC pulse ranges
// ------------------------------
const uint16_t RC_MIN = 1000;
const uint16_t RC_MID = 1500;
const uint16_t RC_MAX = 2000;
const uint32_t SERVO_PERIOD_MS = 20;
const uint16_t SERVO_DEADBAND_US = 2;
const float RX_SMOOTH_ALPHA = 1.0f;

// ------------------------------
// Failsafe
// ------------------------------
const uint32_t LINK_FRESH_MS    = 150;
const uint32_t FS_THR_CUTOFF_MS = 1000;
const uint32_t FS_THR_HYST_MS   = 200;
const uint32_t FS_THR_DISARM_MS = FS_THR_CUTOFF_MS + FS_THR_HYST_MS;
const uint32_t FS_SAFE_MS       = 3000;

// ------------------------------
// Arming
// ------------------------------
const uint16_t UNLOCK_THRESH_US = RC_MIN + 60;
const uint32_t UNLOCK_HOLD_MS   = 300;

// ------------------------------
// LED
// ------------------------------
#ifndef LED_BUILTIN
  #define LED_BUILTIN 13
#endif
enum LedState { LED_LOCKED=0, LED_ARMED=1, LED_LOST=2, LED_BIND=3 };
LedState ledState = LED_LOCKED;

// ------------------------------
// Battery monitor
// ------------------------------
const int VBAT_PIN = A4;
const bool ENABLE_VBAT_MONITOR = false;
const bool ENABLE_RX_DEBUG = true;
const float VBAT_RTOP_KOHM = 10.0f;
const float VBAT_RBOT_KOHM = 1.0f;
const uint16_t VBAT_SAMPLES = 8;
const uint32_t VBAT_PERIOD_MS = 500;
const uint16_t LAND_PER_CELL_MV = 3500;
uint16_t vbat_mV = 0;
uint8_t  vbat_cells = 0;
uint32_t lastVbatMs = 0;

// ------------------------------
// Flash bind-store
// ------------------------------
#define BIND_MAGIC 0x42494E44UL
struct __attribute__((packed)) BindStore {
  uint32_t magic;
  uint16_t bindCode;
  uint16_t _pad;
};
FlashStorage(BIND_STORE, BindStore);

// ------------------------------
// Packets
// ------------------------------
struct __attribute__((packed)) ControlPacket {
  uint16_t ch_rud;
  uint16_t ch_ail;
  uint16_t ch_ele;
  uint16_t ch_thr;
  uint16_t flags;
  uint16_t seq;
};

struct __attribute__((packed)) BindPacket {
  uint32_t magic;
  uint16_t code;
  uint16_t _pad;
};

// ------------------------------
// IMU / baro bring-up
// ------------------------------
const uint8_t LSM6DS_ADDR_LOW  = 0x6A;
const uint8_t LSM6DS_ADDR_HIGH = 0x6B;
const uint8_t REG_WHO_AM_I     = 0x0F;
const uint8_t REG_CTRL1_XL     = 0x10;
const uint8_t REG_CTRL2_G      = 0x11;
const uint8_t REG_CTRL3_C      = 0x12;
const uint8_t REG_OUTX_L_G     = 0x22;

// Rx V4 schematic: U6 is MS5607-02BA03.
// This sketch currently only probes likely barometer addresses so tomorrow we
// can confirm the live bus/interface before adding full compensation math.
const uint8_t BARO_ADDR_LOW  = 0x76;
const uint8_t BARO_ADDR_HIGH = 0x77;

const float LSM6DS_GYRO_DPS_PER_LSB  = 0.00875f;   // 245 dps full scale
const float LSM6DS_ACCEL_G_PER_LSB   = 0.000061f;  // 2 g full scale
const float DEG_PER_RAD = 57.2957795f;
const float RAD_PER_DEG = 0.0174532925f;

// Rx V4 IMU calibration captured 2026-07-05.
// Raw angle formula: level roll=169.81, pitch=11.60.
// Relative convention used by the controller: right roll positive, pitch up positive.
const float IMU_CAL_LEVEL_ROLL_DEG   = 169.81f;
const float IMU_CAL_LEVEL_PITCH_DEG  = 11.60f;
const float IMU_CAL_ROLL_OUTPUT_SIGN = -1.0f;
const float IMU_CAL_PITCH_OUTPUT_SIGN = 1.0f;

const float IMU_ROLL_FROM_ACCEL_SIGN  = 1.0f;
const float IMU_PITCH_FROM_ACCEL_SIGN = 1.0f;
const float IMU_ROLL_RATE_SIGN        = -1.0f;
const float IMU_PITCH_RATE_SIGN       = 1.0f;
const float AP_AILERON_CORRECTION_SIGN  = 1.0f;
const float AP_ELEVATOR_CORRECTION_SIGN = -1.0f;
const uint32_t AP_DEBUG_PERIOD_MS = 50;

struct ImuState {
  bool ready = false;
  bool attitudeInitialized = false;
  uint8_t addr = 0;
  uint32_t lastSampleMs = 0;
  float rollDeg = 0.0f;
  float pitchDeg = 0.0f;
  float gyroRollDps = 0.0f;
  float gyroPitchDps = 0.0f;
  float accelXg = 0.0f;
  float accelYg = 0.0f;
  float accelZg = 0.0f;
};

struct BaroState {
  bool detected = false;
  uint8_t addr = 0;
  bool altitudeReady = false;
  float altitudeM = 0.0f;
};

enum AutopilotMode {
  AP_MODE_MANUAL = 0,
  AP_MODE_LEVEL_HOLD = 1,
  AP_MODE_LEVEL_AND_ALT_HOLD = 2
};

struct AutopilotConfig {
  bool enableAutolevel = true;
  bool enableAltitudeHold = true;
  uint16_t stickDeadbandUs = 35;
  uint16_t neutralCaptureWindowUs = 250;
  uint32_t stickReleaseHoldMs = 1500;
  uint32_t levelCaptureHoldMs = 1000;
  float levelCaptureMaxGyroDps = 8.0f;
  uint16_t launchDetectThrottleUs = 1120;
  uint32_t launchAutolevelLockoutMs = 8000;
  float levelTargetRollDeg = IMU_CAL_LEVEL_ROLL_DEG;
  float levelTargetPitchDeg = IMU_CAL_LEVEL_PITCH_DEG;
  float rollTimeConstantS = 0.80f;
  float pitchTimeConstantS = 0.85f;
  float rollMaxRateDps = 45.0f;
  float pitchMaxRateDps = 35.0f;
  float rollAngleKpUsPerDeg = 9.0f;
  float rollRateKdUsPerDps = 2.8f;
  float pitchRateKpUsPerDps = 3.0f;
  uint16_t rollMaxCorrectionUs = 220;
  uint16_t pitchMaxCorrectionUs = 140;
  float rollCorrectionAlpha = 1.0f;
  float pitchCorrectionAlpha = 0.80f;
  int16_t rollMaxCorrectionStepUs = 90;
  int16_t pitchMaxCorrectionStepUs = 22;
  float altitudeKpUsPerMeter = 45.0f;
  uint16_t altitudeMaxCorrectionUs = 120;
};

struct AutopilotState {
  AutopilotMode mode = AP_MODE_MANUAL;
  uint32_t sticksCenteredSince = 0;
  uint32_t levelCaptureCandidateSince = 0;
  bool sticksReleased = false;
  bool neutralCaptured = false;
  bool launchThrottleSeen = false;
  uint32_t launchThrottleSeenMs = 0;
  bool launchLockoutActive = false;
  uint16_t neutralAileronUs = RC_MID;
  uint16_t neutralElevatorUs = RC_MID;
  float effectiveRollDeg = 0.0f;
  float effectivePitchDeg = 0.0f;
  float effectiveRollRateDps = 0.0f;
  float effectivePitchRateDps = 0.0f;
  float rollErrDeg = 0.0f;
  float pitchErrDeg = 0.0f;
  int16_t rollAngleCorrectionUs = 0;
  int16_t rollDampingCorrectionUs = 0;
  float targetRollRateDps = 0.0f;
  float targetPitchRateDps = 0.0f;
  int16_t targetAileronCorrectionUs = 0;
  int16_t targetElevatorCorrectionUs = 0;
  float altitudeTargetM = 0.0f;
  bool altitudeTargetCaptured = false;
  int16_t aileronCorrectionUs = 0;
  int16_t elevatorCorrectionUs = 0;
  int16_t throttleCorrectionUs = 0;
};

ImuState imu;
BaroState baro;
AutopilotConfig apConfig;
AutopilotState apState;

// ------------------------------
// State vars
// ------------------------------
BindStore g_bind = {0, 0, 0};
bool bindMode = false;
bool escMode = false;
bool armed = false;
uint32_t thrLowSince = 0;
uint32_t lastRxMs = 0;

uint16_t des_r=RC_MID, des_a=RC_MID, des_e=RC_MID, des_t=RC_MIN;
uint16_t cur_r=RC_MID, cur_a=RC_MID, cur_e=RC_MID, cur_t=RC_MIN;
uint16_t filt_r=RC_MID, filt_a=RC_MID, filt_e=RC_MID, filt_t=RC_MIN;

// Manual commands from the latest accepted radio packet.
uint16_t manual_r=RC_MID, manual_a=RC_MID, manual_e=RC_MID, manual_t=RC_MIN;

uint32_t rxPackets = 0;
uint32_t acceptedPackets = 0;
uint32_t rejectedPackets = 0;
uint32_t lastDebugMs = 0;
uint16_t lastPktBind = 0;
uint16_t lastPktSeq = 0;
int16_t lastRssi = 0;

uint32_t bootMs = 0;
const uint32_t BOOT_CALIB_GUARD_MS = 3000;
const uint8_t  ESC_FLAG_CONSEC     = 3;
uint8_t escFlagStreak = 0;

// ------------------------------
// Helpers
// ------------------------------
static inline BindStore loadBind() {
  BindStore v;
  BIND_STORE.read(v);
  if (v.magic != BIND_MAGIC) {
    v.magic = 0;
    v.bindCode = 0;
  }
  return v;
}

static inline void saveBind(const BindStore& v_in) {
  BindStore v = v_in;
  BIND_STORE.write(v);
}

static inline bool inRange(uint16_t v) {
  return v >= RC_MIN && v <= RC_MAX;
}

static inline bool validPacket(const ControlPacket& p) {
  return inRange(p.ch_rud) && inRange(p.ch_ail) &&
         inRange(p.ch_ele) && inRange(p.ch_thr);
}

static inline uint16_t clampRc(int32_t us) {
  if (us < RC_MIN) return RC_MIN;
  if (us > RC_MAX) return RC_MAX;
  return (uint16_t)us;
}

static inline int16_t clampSigned(int32_t v, int16_t limit) {
  if (v > limit) return limit;
  if (v < -limit) return -limit;
  return (int16_t)v;
}

static inline float clampFloat(float v, float limit) {
  if (v > limit) return limit;
  if (v < -limit) return -limit;
  return v;
}

static inline float normalizeAngleDeg(float deg) {
  while (deg > 180.0f) deg -= 360.0f;
  while (deg < -180.0f) deg += 360.0f;
  return deg;
}

static inline int16_t smoothCorrection(int16_t previous, int16_t target, float alpha) {
  return (int16_t)lroundf((1.0f - alpha) * previous + alpha * target);
}

static inline int16_t slewLimitCorrection(int16_t previous, int16_t target, int16_t maxStep) {
  int16_t delta = target - previous;
  if (delta > maxStep) return previous + maxStep;
  if (delta < -maxStep) return previous - maxStep;
  return target;
}

static inline int16_t responsiveCorrection(int16_t previous, int16_t target, int16_t maxStep) {
  bool signChanged = (previous > 0 && target < 0) || (previous < 0 && target > 0);
  if (signChanged) return target;
  return slewLimitCorrection(previous, target, maxStep);
}

static inline bool stickNearCenter(uint16_t us, uint16_t deadbandUs) {
  return abs((int)us - (int)RC_MID) <= (int)deadbandUs;
}

static inline bool stickNearNeutral(uint16_t us, uint16_t neutralUs, uint16_t deadbandUs) {
  return abs((int)us - (int)neutralUs) <= (int)deadbandUs;
}

static inline void setSafeDesired() {
  des_r = RC_MID;
  des_a = RC_MID;
  des_e = RC_MID;
  des_t = RC_MIN;
}

static inline void setServoIfChanged(uint16_t &cur, uint16_t target) {
  if (abs((int)target - (int)cur) > SERVO_DEADBAND_US) {
    cur = target;
  }
}

static inline void writePulse(int pin, uint16_t us) {
  noInterrupts();
  digitalWrite(pin, HIGH);
  delayMicroseconds(us);
  digitalWrite(pin, LOW);
  interrupts();
}

void writeServoFrame() {
  writePulse(PIN_SERVO_THROTTLE, cur_t);
  writePulse(PIN_SERVO_AILERON,  cur_a);
  writePulse(PIN_SERVO_ELEVATOR, cur_e);
  writePulse(PIN_SERVO_RUDDER,   cur_r);
}

void disarmAndLock() {
  armed = false;
  thrLowSince = 0;
  des_t = RC_MIN;
  apState.mode = AP_MODE_MANUAL;
  apState.sticksReleased = false;
  apState.neutralCaptured = false;
  apState.launchThrottleSeen = false;
  apState.launchThrottleSeenMs = 0;
  apState.launchLockoutActive = false;
  apState.levelCaptureCandidateSince = 0;
  apState.altitudeTargetCaptured = false;
}

void captureAutopilotNeutral() {
  apState.neutralAileronUs = manual_a;
  apState.neutralElevatorUs = manual_e;
  apState.neutralCaptured = true;
  apState.sticksCenteredSince = 0;
  apState.sticksReleased = false;
  apConfig.levelTargetRollDeg = IMU_CAL_LEVEL_ROLL_DEG;
  apConfig.levelTargetPitchDeg = IMU_CAL_LEVEL_PITCH_DEG;

  if (ENABLE_RX_DEBUG) {
    Serial.print("AP neutral captured ail=");
    Serial.print(apState.neutralAileronUs);
    Serial.print(" ele=");
    Serial.print(apState.neutralElevatorUs);
    Serial.print(" calTargetRoll=");
    Serial.print(apConfig.levelTargetRollDeg, 1);
    Serial.print(" calTargetPitch=");
    Serial.println(apConfig.levelTargetPitchDeg, 1);
  }
}

bool readyToCaptureAutopilotNeutral(uint32_t now, uint32_t age) {
  if (!armed || bindMode || escMode || !apConfig.enableAutolevel) return false;
  if (age > LINK_FRESH_MS) return false;
  if (!imu.ready || !imu.attitudeInitialized) {
    apState.levelCaptureCandidateSince = 0;
    return false;
  }
  if (manual_t > UNLOCK_THRESH_US) {
    apState.levelCaptureCandidateSince = 0;
    return false;
  }
  if (!stickNearCenter(manual_a, apConfig.neutralCaptureWindowUs) ||
      !stickNearCenter(manual_e, apConfig.neutralCaptureWindowUs)) {
    apState.levelCaptureCandidateSince = 0;
    return false;
  }
  if (fabsf(imu.gyroRollDps) > apConfig.levelCaptureMaxGyroDps ||
      fabsf(imu.gyroPitchDps) > apConfig.levelCaptureMaxGyroDps) {
    apState.levelCaptureCandidateSince = 0;
    return false;
  }

  if (apState.levelCaptureCandidateSince == 0) {
    apState.levelCaptureCandidateSince = now;
    return false;
  }
  return (now - apState.levelCaptureCandidateSince) >= apConfig.levelCaptureHoldMs;
}

void hardResetRadio() {
  pinMode(RFM95_RST, OUTPUT);
  digitalWrite(RFM95_RST, HIGH); delay(1);
  digitalWrite(RFM95_RST, LOW); delay(10);
  digitalWrite(RFM95_RST, HIGH); delay(10);
}

uint16_t readVBATmV() {
  uint32_t acc = 0;
  for (int i = 0; i < VBAT_SAMPLES; ++i) acc += analogRead(VBAT_PIN);
  float vadc = (acc / (float)VBAT_SAMPLES) * (3.3f / 1023.0f);
  float vbat = vadc * ((VBAT_RTOP_KOHM + VBAT_RBOT_KOHM) / VBAT_RBOT_KOHM);
  return (uint16_t)(vbat * 1000.0f);
}

uint8_t inferCells(uint16_t mv) {
  if (mv >= 21500) return 6;
  if (mv >= 17500) return 5;
  if (mv >= 13500) return 4;
  if (mv >= 9500)  return 3;
  return 0;
}

void updateLed() {
  static bool on = false;
  uint32_t now = millis();
  if (ledState == LED_ARMED) {
    if (!on) {
      digitalWrite(LED_BUILTIN, HIGH);
      on = true;
    }
    return;
  }
  uint32_t period = (ledState == LED_BIND) ? 1200 : (ledState == LED_LOCKED ? 1000 : 200);
  uint32_t ontime = (ledState == LED_BIND) ? 600 : (ledState == LED_LOCKED ? 200 : 100);
  bool shouldOn = ((now % period) < ontime);
  if (shouldOn != on) {
    digitalWrite(LED_BUILTIN, shouldOn ? HIGH : LOW);
    on = shouldOn;
  }
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
  for (uint8_t i = 0; i < len; ++i) buf[i] = Wire.read();
  return true;
}

void printHex2(uint8_t v) {
  if (v < 16) Serial.print("0");
  Serial.print(v, HEX);
}

bool beginLsm6ds(uint8_t addr) {
  uint8_t who = 0;
  if (!readReg(addr, REG_WHO_AM_I, who)) return false;
  if (who != 0x69 && who != 0x6A && who != 0x6C) return false;
  if (!writeReg(addr, REG_CTRL3_C, 0x44)) return false;
  if (!writeReg(addr, REG_CTRL1_XL, 0x40)) return false;
  if (!writeReg(addr, REG_CTRL2_G, 0x40)) return false;
  imu.addr = addr;
  imu.ready = true;
  imu.attitudeInitialized = false;
  imu.lastSampleMs = millis();
  return true;
}

void setupImu() {
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

  imu.ready = false;
  imu.addr = 0;
  if (!beginLsm6ds(LSM6DS_ADDR_LOW)) {
    beginLsm6ds(LSM6DS_ADDR_HIGH);
  }
}

void setupBaroPlaceholder() {
  baro.detected = false;
  baro.addr = 0;
  baro.altitudeReady = false;

  Wire.beginTransmission(BARO_ADDR_LOW);
  if (Wire.endTransmission() == 0) {
    baro.detected = true;
    baro.addr = BARO_ADDR_LOW;
    return;
  }

  Wire.beginTransmission(BARO_ADDR_HIGH);
  if (Wire.endTransmission() == 0) {
    baro.detected = true;
    baro.addr = BARO_ADDR_HIGH;
  }
}

static inline int16_t s16(uint8_t lo, uint8_t hi) {
  return (int16_t)((uint16_t)lo | ((uint16_t)hi << 8));
}

void updateImuEstimate(uint32_t now) {
  if (!imu.ready) return;

  uint8_t b[12];
  if (!readBytes(imu.addr, REG_OUTX_L_G, b, sizeof(b))) {
    imu.ready = false;
    return;
  }

  int16_t gxRaw = s16(b[0], b[1]);
  int16_t gyRaw = s16(b[2], b[3]);
  int16_t gzRaw = s16(b[4], b[5]);
  int16_t axRaw = s16(b[6], b[7]);
  int16_t ayRaw = s16(b[8], b[9]);
  int16_t azRaw = s16(b[10], b[11]);
  (void)gzRaw;

  imu.gyroRollDps = IMU_ROLL_RATE_SIGN * gxRaw * LSM6DS_GYRO_DPS_PER_LSB;
  imu.gyroPitchDps = IMU_PITCH_RATE_SIGN * gyRaw * LSM6DS_GYRO_DPS_PER_LSB;
  imu.accelXg = axRaw * LSM6DS_ACCEL_G_PER_LSB;
  imu.accelYg = ayRaw * LSM6DS_ACCEL_G_PER_LSB;
  imu.accelZg = azRaw * LSM6DS_ACCEL_G_PER_LSB;

  float rollAcc = IMU_ROLL_FROM_ACCEL_SIGN *
                  atan2f(imu.accelYg, imu.accelZg) * DEG_PER_RAD;
  float pitchAcc = IMU_PITCH_FROM_ACCEL_SIGN *
                   atan2f(-imu.accelXg,
                          sqrtf(imu.accelYg * imu.accelYg +
                                imu.accelZg * imu.accelZg)) * DEG_PER_RAD;

  if (!imu.attitudeInitialized) {
    imu.rollDeg = rollAcc;
    imu.pitchDeg = pitchAcc;
    imu.attitudeInitialized = true;
    imu.lastSampleMs = now;
    return;
  }

  float dt = (imu.lastSampleMs == 0) ? 0.02f : (now - imu.lastSampleMs) / 1000.0f;
  if (dt < 0.001f) dt = 0.001f;
  if (dt > 0.1f) dt = 0.1f;
  imu.lastSampleMs = now;

  const float alpha = 0.94f;
  imu.rollDeg = alpha * (imu.rollDeg + imu.gyroRollDps * dt) + (1.0f - alpha) * rollAcc;
  imu.pitchDeg = alpha * (imu.pitchDeg + imu.gyroPitchDps * dt) + (1.0f - alpha) * pitchAcc;
}

void updateAutopilotState(uint32_t now, uint32_t age) {
  apState.mode = AP_MODE_MANUAL;
  apState.rollErrDeg = 0.0f;
  apState.pitchErrDeg = 0.0f;
  apState.effectiveRollDeg = 0.0f;
  apState.effectivePitchDeg = 0.0f;
  apState.effectiveRollRateDps = 0.0f;
  apState.effectivePitchRateDps = 0.0f;
  apState.rollAngleCorrectionUs = 0;
  apState.rollDampingCorrectionUs = 0;
  apState.targetRollRateDps = 0.0f;
  apState.targetPitchRateDps = 0.0f;
  apState.targetAileronCorrectionUs = 0;
  apState.targetElevatorCorrectionUs = 0;
  int16_t prevAileronCorrectionUs = apState.aileronCorrectionUs;
  int16_t prevElevatorCorrectionUs = apState.elevatorCorrectionUs;
  apState.aileronCorrectionUs = 0;
  apState.elevatorCorrectionUs = 0;
  apState.throttleCorrectionUs = 0;

  bool freshLink = (age <= LINK_FRESH_MS);
  bool centered = apState.neutralCaptured &&
                  stickNearNeutral(manual_a, apState.neutralAileronUs, apConfig.stickDeadbandUs) &&
                  stickNearNeutral(manual_e, apState.neutralElevatorUs, apConfig.stickDeadbandUs);

  if (!apState.launchThrottleSeen && manual_t >= apConfig.launchDetectThrottleUs) {
    apState.launchThrottleSeen = true;
    apState.launchThrottleSeenMs = now;
  }
  apState.launchLockoutActive =
      apState.launchThrottleSeen &&
      (now - apState.launchThrottleSeenMs < apConfig.launchAutolevelLockoutMs);

  if (!freshLink || !armed || bindMode || escMode || !apConfig.enableAutolevel ||
      !apState.neutralCaptured || apState.launchLockoutActive) {
    apState.sticksReleased = false;
    apState.sticksCenteredSince = 0;
    apState.altitudeTargetCaptured = false;
    return;
  }

  if (centered) {
    if (apState.sticksCenteredSince == 0) apState.sticksCenteredSince = now;
    if (now - apState.sticksCenteredSince >= apConfig.stickReleaseHoldMs) {
      apState.sticksReleased = true;
    }
  } else {
    apState.sticksReleased = false;
    apState.sticksCenteredSince = 0;
    apState.altitudeTargetCaptured = false;
    return;
  }

  if (!apState.sticksReleased || !imu.ready) {
    return;
  }

  float rawRollDeg = normalizeAngleDeg(imu.rollDeg);
  float rollDeviationDeg =
      normalizeAngleDeg(rawRollDeg - apConfig.levelTargetRollDeg);
  float pitchDeviationDeg = imu.pitchDeg - apConfig.levelTargetPitchDeg;
  float effectiveRollDeg = IMU_CAL_ROLL_OUTPUT_SIGN * rollDeviationDeg;
  float effectivePitchDeg = IMU_CAL_PITCH_OUTPUT_SIGN * pitchDeviationDeg;
  float effectiveRollRateDps = IMU_CAL_ROLL_OUTPUT_SIGN * imu.gyroRollDps;
  float effectivePitchRateDps = IMU_CAL_PITCH_OUTPUT_SIGN * imu.gyroPitchDps;
  float rollErr = -effectiveRollDeg;
  float pitchErr = -effectivePitchDeg;
  apState.effectiveRollDeg = effectiveRollDeg;
  apState.effectivePitchDeg = effectivePitchDeg;
  apState.effectiveRollRateDps = effectiveRollRateDps;
  apState.effectivePitchRateDps = effectivePitchRateDps;
  apState.rollErrDeg = rollErr;
  apState.pitchErrDeg = pitchErr;

  float targetRollRate =
      clampFloat(rollErr / apConfig.rollTimeConstantS, apConfig.rollMaxRateDps);
  float targetPitchRate =
      clampFloat(pitchErr / apConfig.pitchTimeConstantS, apConfig.pitchMaxRateDps);
  apState.targetRollRateDps = targetRollRate;
  apState.targetPitchRateDps = targetPitchRate;

  float pitchRateErr = targetPitchRate - effectivePitchRateDps;
  int16_t rollAngleUs =
      (int16_t)lroundf(rollErr * apConfig.rollAngleKpUsPerDeg);
  int16_t rollDampingUs =
      (int16_t)lroundf(-effectiveRollRateDps * apConfig.rollRateKdUsPerDps);
  apState.rollAngleCorrectionUs = rollAngleUs;
  apState.rollDampingCorrectionUs = rollDampingUs;
  int32_t ailUs = (int32_t)lroundf(AP_AILERON_CORRECTION_SIGN *
                                   (rollAngleUs + rollDampingUs));
  int32_t eleUs = (int32_t)lroundf(AP_ELEVATOR_CORRECTION_SIGN *
                                   pitchRateErr * apConfig.pitchRateKpUsPerDps);

  int16_t targetAil =
      clampSigned(ailUs, (int16_t)apConfig.rollMaxCorrectionUs);
  int16_t targetEle =
      clampSigned(eleUs, (int16_t)apConfig.pitchMaxCorrectionUs);
  apState.targetAileronCorrectionUs = targetAil;
  apState.targetElevatorCorrectionUs = targetEle;
  int16_t smoothAil =
      smoothCorrection(prevAileronCorrectionUs, targetAil, apConfig.rollCorrectionAlpha);
  int16_t smoothEle =
      smoothCorrection(prevElevatorCorrectionUs, targetEle, apConfig.pitchCorrectionAlpha);
  apState.aileronCorrectionUs =
      responsiveCorrection(prevAileronCorrectionUs, smoothAil, apConfig.rollMaxCorrectionStepUs);
  apState.elevatorCorrectionUs =
      slewLimitCorrection(prevElevatorCorrectionUs, smoothEle, apConfig.pitchMaxCorrectionStepUs);
  apState.mode = AP_MODE_LEVEL_HOLD;

  if (apConfig.enableAltitudeHold && baro.altitudeReady) {
    if (!apState.altitudeTargetCaptured) {
      apState.altitudeTargetM = baro.altitudeM;
      apState.altitudeTargetCaptured = true;
    }
    float altErr = apState.altitudeTargetM - baro.altitudeM;
    int32_t thrUs = (int32_t)lroundf(altErr * apConfig.altitudeKpUsPerMeter);
    apState.throttleCorrectionUs =
        clampSigned(thrUs, (int16_t)apConfig.altitudeMaxCorrectionUs);
    apState.mode = AP_MODE_LEVEL_AND_ALT_HOLD;
  }
}

void applyManualOrAutopilotDesired() {
  des_r = manual_r;
  des_a = manual_a;
  des_e = manual_e;
  des_t = manual_t;

  if (apState.mode >= AP_MODE_LEVEL_HOLD) {
    des_a = clampRc((int32_t)manual_a + apState.aileronCorrectionUs);
    des_e = clampRc((int32_t)manual_e + apState.elevatorCorrectionUs);
  }

  if (apState.mode == AP_MODE_LEVEL_AND_ALT_HOLD) {
    des_t = clampRc((int32_t)manual_t + apState.throttleCorrectionUs);
  }
}

// ------------------------------
// Setup
// ------------------------------
void setup() {
  if (ENABLE_RX_DEBUG) {
    Serial.begin(115200);
    delay(50);
  }

  pinMode(LED_BUILTIN, OUTPUT);
  pinMode(PIN_BIND_BTN, INPUT_PULLUP);
  bindMode = (digitalRead(PIN_BIND_BTN) == LOW);
  g_bind = loadBind();

  pinMode(PIN_SERVO_THROTTLE, OUTPUT);
  pinMode(PIN_SERVO_AILERON, OUTPUT);
  pinMode(PIN_SERVO_ELEVATOR, OUTPUT);
  pinMode(PIN_SERVO_RUDDER, OUTPUT);
  digitalWrite(PIN_SERVO_THROTTLE, LOW);
  digitalWrite(PIN_SERVO_AILERON, LOW);
  digitalWrite(PIN_SERVO_ELEVATOR, LOW);
  digitalWrite(PIN_SERVO_RUDDER, LOW);

  cur_t  = RC_MIN;
  des_t  = RC_MIN;
  filt_t = RC_MIN;
  manual_t = RC_MIN;

  cur_a = filt_a = des_a = manual_a = RC_MID;
  cur_e = filt_e = des_e = manual_e = RC_MID;
  cur_r = filt_r = des_r = manual_r = RC_MID;
  writeServoFrame();

  setSafeDesired();
  disarmAndLock();

  setupImu();
  setupBaroPlaceholder();

  hardResetRadio();
  if (!rf95.init()) {
    while (1) {
      digitalWrite(LED_BUILTIN, !digitalRead(LED_BUILTIN));
      delay(100);
    }
  }
  rf95.setModemConfig(MODEM);
  rf95.setFrequency(RF95_FREQ);

  if (ENABLE_VBAT_MONITOR) {
    pinMode(VBAT_PIN, INPUT);
    vbat_mV = readVBATmV();
    vbat_cells = inferCells(vbat_mV);
  }

  bootMs = millis();
  lastRxMs = bootMs;
  ledState = bindMode ? LED_BIND : LED_LOCKED;

  if (ENABLE_RX_DEBUG) {
    Serial.println("RX V4 autolevel experiment ready");
    Serial.print("Stored bind code: ");
    Serial.println((g_bind.magic == BIND_MAGIC) ? g_bind.bindCode : 0);
    Serial.print("IMU: ");
    if (imu.ready) {
      Serial.print("LSM6DS @ 0x");
      printHex2(imu.addr);
      Serial.println();
    } else {
      Serial.println("not detected");
    }
    Serial.print("Baro probe: ");
    if (baro.detected) {
      Serial.print("device seen @ 0x");
      printHex2(baro.addr);
      Serial.println(" MS5607 candidate seen (driver pending)");
    } else {
      Serial.println("not detected");
    }
    if (bindMode) Serial.println("Bind Mode Active");
  }
}

// ------------------------------
// Loop
// ------------------------------
void loop() {
  uint32_t now = millis();

  if (ENABLE_VBAT_MONITOR && now - lastVbatMs >= VBAT_PERIOD_MS) {
    lastVbatMs = now;
    vbat_mV = readVBATmV();
    uint8_t cells = inferCells(vbat_mV);
    if (cells) vbat_cells = cells;
    if (vbat_cells >= 3 && vbat_mV < vbat_cells * LAND_PER_CELL_MV) {
      disarmAndLock();
    }
  }

  if (rf95.available()) {
    uint8_t buf[sizeof(ControlPacket)];
    uint8_t len = sizeof(buf);
    if (rf95.recv(buf, &len)) {
      if (bindMode && len == sizeof(BindPacket)) {
        BindPacket bp;
        memcpy(&bp, buf, sizeof(bp));
        if (bp.magic == BIND_MAGIC && bp.code) {
          g_bind.magic = BIND_MAGIC;
          g_bind.bindCode = bp.code;
          saveBind(g_bind);
          digitalWrite(LED_BUILTIN, HIGH); delay(800); digitalWrite(LED_BUILTIN, LOW);
          bindMode = false;
          ledState = LED_LOCKED;
          if (ENABLE_RX_DEBUG) {
            Serial.print("Stored Bind Code: ");
            Serial.println(bp.code);
          }
        }
      } else if (len == sizeof(ControlPacket)) {
        ControlPacket pkt;
        memcpy(&pkt, buf, sizeof(pkt));
        if (validPacket(pkt)) {
          rxPackets++;

          bool pktEsc = (pkt.flags & 0x8000);
          uint16_t pktBind = (pkt.flags & 0x7FFF);
          lastPktBind = pktBind;
          lastPktSeq = pkt.seq;
          lastRssi = rf95.lastRssi();

          if (pktEsc) {
            if (escFlagStreak < 255) escFlagStreak++;
          } else {
            escFlagStreak = 0;
          }

          bool accept = true;
          if (g_bind.magic == BIND_MAGIC && g_bind.bindCode != 0) {
            accept = (pktBind == g_bind.bindCode);
          }
          if (accept) {
            acceptedPackets++;
            manual_r = pkt.ch_rud;
            manual_a = pkt.ch_ail;
            manual_e = pkt.ch_ele;
            manual_t = pkt.ch_thr;
            lastRxMs = now;
          } else {
            rejectedPackets++;
          }

          if (!escMode &&
              escFlagStreak >= ESC_FLAG_CONSEC &&
              (now - bootMs) < 5000 &&
              manual_t >= (RC_MAX - 20)) {
            escMode = true;
            armed = true;
            ledState = LED_ARMED;
            if (ENABLE_RX_DEBUG) {
              Serial.println("ESC MODE ACTIVE (handshake confirmed)");
            }
          }
        }
      }
    }
  }

  static uint32_t lastTick = 0;
  if (now - lastTick >= SERVO_PERIOD_MS) {
    lastTick = now;
    updateImuEstimate(now);

    uint32_t age = now - lastRxMs;
    bool inBootGuard = (now - bootMs) < BOOT_CALIB_GUARD_MS;
    if (inBootGuard && !escMode) {
      des_t = RC_MIN;
    }

    if (!bindMode && !escMode) {
      if (!armed) {
        if (age <= LINK_FRESH_MS && manual_t <= UNLOCK_THRESH_US) {
          if (thrLowSince == 0) thrLowSince = now;
          if (now - thrLowSince >= UNLOCK_HOLD_MS) {
            armed = true;
          }
        } else {
          thrLowSince = 0;
        }

        des_t = RC_MIN;
        des_r = manual_r;
        des_a = manual_a;
        des_e = manual_e;

        if (age > FS_THR_CUTOFF_MS) {
          if (age > FS_SAFE_MS) {
            des_r = RC_MID;
            des_a = RC_MID;
            des_e = RC_MID;
          }
          ledState = LED_LOST;
        } else {
          ledState = LED_LOCKED;
        }
      } else {
        if (!apState.neutralCaptured && readyToCaptureAutopilotNeutral(now, age)) {
          captureAutopilotNeutral();
        }
        if (age <= FS_THR_CUTOFF_MS) {
          applyManualOrAutopilotDesired();
          updateAutopilotState(now, age);
          applyManualOrAutopilotDesired();
          ledState = LED_ARMED;
        } else if (age <= FS_THR_DISARM_MS) {
          ledState = LED_LOST;
        } else {
          armed = false;
          des_t = RC_MIN;
          cur_t = RC_MIN;
          if (age > FS_SAFE_MS) {
            des_r = RC_MID;
            des_a = RC_MID;
            des_e = RC_MID;
          }
          ledState = LED_LOST;
        }
      }
    } else if (bindMode) {
      setSafeDesired();
      ledState = LED_BIND;
    } else if (escMode) {
      if (age > FS_THR_CUTOFF_MS) {
        escMode = false;
        armed = false;
        des_t = RC_MIN;
        cur_t = RC_MIN;
        if (age > FS_SAFE_MS) {
          des_r = RC_MID;
          des_a = RC_MID;
          des_e = RC_MID;
        }
        ledState = LED_LOST;
      } else {
        des_r = manual_r;
        des_a = manual_a;
        des_e = manual_e;
        des_t = manual_t;
        ledState = LED_ARMED;
      }
    }

    auto lerp = [](uint16_t cur, uint16_t tgt, float a) {
      return (uint16_t)((1.0f - a) * cur + a * tgt + 0.5f);
    };
    filt_r = lerp(filt_r, des_r, RX_SMOOTH_ALPHA);
    filt_a = lerp(filt_a, des_a, RX_SMOOTH_ALPHA);
    filt_e = lerp(filt_e, des_e, RX_SMOOTH_ALPHA);
    filt_t = lerp(filt_t, des_t, RX_SMOOTH_ALPHA);

    if (armed || escMode) {
      setServoIfChanged(cur_t, filt_t);
      setServoIfChanged(cur_a, filt_a);
      setServoIfChanged(cur_e, filt_e);
      setServoIfChanged(cur_r, filt_r);
    } else {
      setServoIfChanged(cur_t, RC_MIN);
      setServoIfChanged(cur_a, filt_a);
      setServoIfChanged(cur_e, filt_e);
      setServoIfChanged(cur_r, filt_r);
    }

    writeServoFrame();
    updateLed();
  }

  if (ENABLE_RX_DEBUG && now - lastDebugMs >= AP_DEBUG_PERIOD_MS) {
    lastDebugMs = now;
    Serial.print("RXV4 mode=");
    switch (apState.mode) {
      case AP_MODE_MANUAL: Serial.print("MANUAL"); break;
      case AP_MODE_LEVEL_HOLD: Serial.print("LEVEL"); break;
      case AP_MODE_LEVEL_AND_ALT_HOLD: Serial.print("LEVEL+ALT"); break;
    }
    Serial.print(" imu=");
    Serial.print(imu.ready ? "yes" : "no");
    Serial.print(" roll=");
    Serial.print(imu.rollDeg, 1);
    Serial.print(" pitch=");
    Serial.print(imu.pitchDeg, 1);
    Serial.print(" gyro=");
    Serial.print(imu.gyroRollDps, 1);
    Serial.print(",");
    Serial.print(imu.gyroPitchDps, 1);
    Serial.print(" relRate=");
    Serial.print(apState.effectiveRollRateDps, 1);
    Serial.print(",");
    Serial.print(apState.effectivePitchRateDps, 1);
    Serial.print(" baro=");
    Serial.print(baro.detected ? "seen" : "none");
    Serial.print(" altReady=");
    Serial.print(baro.altitudeReady ? "yes" : "no");
    Serial.print(" centered=");
    Serial.print(apState.sticksReleased ? "yes" : "no");
    Serial.print(" launchLock=");
    Serial.print(apState.launchLockoutActive ? "yes" : "no");
    Serial.print(" cap=");
    if (apState.neutralCaptured) {
      Serial.print("done");
    } else if (apState.levelCaptureCandidateSince == 0) {
      Serial.print("wait");
    } else {
      Serial.print(now - apState.levelCaptureCandidateSince);
    }
    Serial.print(" neutral=");
    Serial.print(apState.neutralAileronUs);
    Serial.print(",");
    Serial.print(apState.neutralElevatorUs);
    Serial.print(" target=");
    Serial.print(apConfig.levelTargetRollDeg, 1);
    Serial.print(",");
    Serial.print(apConfig.levelTargetPitchDeg, 1);
    Serial.print(" rel=");
    Serial.print(apState.effectiveRollDeg, 1);
    Serial.print(",");
    Serial.print(apState.effectivePitchDeg, 1);
    Serial.print(" err=");
    Serial.print(apState.rollErrDeg, 1);
    Serial.print(",");
    Serial.print(apState.pitchErrDeg, 1);
    Serial.print(" tgtRate=");
    Serial.print(apState.targetRollRateDps, 1);
    Serial.print(",");
    Serial.print(apState.targetPitchRateDps, 1);
    Serial.print(" targetCorr=");
    Serial.print(apState.targetAileronCorrectionUs);
    Serial.print(",");
    Serial.print(apState.targetElevatorCorrectionUs);
    Serial.print(" rollTerms=");
    Serial.print(apState.rollAngleCorrectionUs);
    Serial.print(",");
    Serial.print(apState.rollDampingCorrectionUs);
    Serial.print(" corr=");
    Serial.print(apState.aileronCorrectionUs);
    Serial.print(",");
    Serial.print(apState.elevatorCorrectionUs);
    Serial.print(",");
    Serial.print(apState.throttleCorrectionUs);
    Serial.print(" des=");
    Serial.print(des_r); Serial.print(",");
    Serial.print(des_a); Serial.print(",");
    Serial.print(des_e); Serial.print(",");
    Serial.print(des_t);
    Serial.print(" age=");
    Serial.print(now - lastRxMs);
    Serial.print(" armed=");
    Serial.print(armed ? "yes" : "no");
    Serial.print(" rx=");
    Serial.print(acceptedPackets);
    Serial.print("/");
    Serial.println(rxPackets);
  }
}
