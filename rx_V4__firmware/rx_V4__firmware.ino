/*
  =======================================================
  LoRa RC Receiver V4 Autolevel Experiment (SAMD21) v0.1
  =======================================================
  This sketch is the experimental branch for the Rx V4 PCB.

  Goals for this version:
  - Preserve the proven LoRa receiver behavior and safety structure.
  - Add IMU bring-up for the on-board LSM6DS gyro/accelerometer.
  - Quaternion AHRS and cascaded attitude/rate control for bench testing.
  - Current marked CH5/CH6 protocol: Trainer ON, Aux OFF; see README.md.
  - Reserve a clean place for pressure-sensor altitude hold using the Rx V4
    MS5607-02BA03 pressure sensor once the interface and live readings are
    confirmed on hardware.

  Important:
  - The flight-proven receiver remains in rx_firmware/rx_firmware.ino.
  - This file is intentionally the experimental one for Rx V4 work.
  - Do not fly this version until it is bench-tested and tuned.
*/

#include <SPI.h>
#include "bounded_i2c.h"
#include "preemptible_rf95.h"
#include <FlashStorage_SAMD.h>
#include <Reset.h>
#include "autolevel_commands.h"
#include "attitude_control.h"
#include "timer_servos.h"
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
PreemptibleRf95 rf95(RFM95_CS, RFM95_INT);
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
const int PIN_BIND_PLUG = 20; // SDA: do not start I2C while grounded.
BoundedI2c sensorBus(20, 21);

// ------------------------------
// RC pulse ranges
// ------------------------------
const uint16_t RC_MIN = 1000;
const uint16_t RC_MID = 1500;
const uint16_t RC_MAX = 2000;
const uint32_t SERVO_PERIOD_MS = 20;
const uint32_t CONTROL_PERIOD_MS = 10;
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
const uint32_t CALIBRATION_START_DELAY_MS = 1000;
const uint32_t CALIBRATION_LED_PERIOD_MS = 100;
const uint32_t CALIBRATION_LED_ON_MS = 50;

// ------------------------------
// Battery monitor
// ------------------------------
const int VBAT_PIN = A4;
const bool ENABLE_VBAT_MONITOR = false;
const bool ENABLE_RX_DEBUG = false; // Use on-demand STATUS for bench checks.
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
  uint8_t aux_flags;
  uint16_t seq;
};
AutolevelCommands modeCommands;

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

const float LSM6DS_GYRO_DPS_PER_LSB  = 0.00875f;   // LSM6DSO32: +/-250 dps
const float LSM6DS_ACCEL_G_PER_LSB   = 0.000122f;  // BOM-confirmed LSM6DSO32: +/-4 g, CTRL1_XL=0x40
const float DEG_PER_RAD = 57.2957795f;
const float RAD_PER_DEG = 0.0174532925f;

// Preserve the fixed right-handed PCB transform and the bench-verified output signs.
const float IMU_ROLL_RATE_SIGN = 1.0f;
const float IMU_PITCH_RATE_SIGN = -1.0f;
const float IMU_YAW_RATE_SIGN = -1.0f;
const float AP_AILERON_CORRECTION_SIGN = 1.0f;
const float AP_ELEVATOR_CORRECTION_SIGN = 1.0f;
const uint16_t AP_GYRO_BIAS_SAMPLE_COUNT = 120;
const float AP_ACCEL_TRUST_MIN_RATIO = 0.85f;
const float AP_ACCEL_TRUST_MAX_RATIO = 1.15f;
const float AP_GYRO_BIAS_CAPTURE_MAX_RAW_DPS = 2.0f;
const uint8_t REG_STATUS = 0x1E;
const uint32_t AP_DEBUG_PERIOD_MS = 500;
AttitudeControl::Mount imuMount;

struct ImuState {
  bool ready = false;
  bool attitudeInitialized = false;
  uint8_t addr = 0;
  uint32_t lastSampleMs = 0;
  uint32_t lastSampleUs = 0;
  uint32_t samples = 0;
  uint32_t rejectedSamples = 0;
  uint32_t untrustedSinceMs = 0;
  uint32_t invalidAccelSinceMs = 0;
  bool healthy = false;
  const char *fault = "uncalibrated";
  float filteredRollDps = 0;
  float filteredPitchDps = 0;
  bool filterInitialized = false;
  float accelSum[3] = {0,0,0};
  float gyroSquareSum[3] = {0,0,0};
  float captureGravity[3] = {0,0,0};
  uint32_t captureStartedMs = 0;
  uint32_t lastCaptureDurationMs = 0;
  float lastCaptureVariance[3] = {0,0,0};
  uint32_t captureMotionFailures = 0;
  float calibrationRollDeg = 0;
  float calibrationPitchDeg = 0;
  float rollDeg = 0.0f;
  float pitchDeg = 0.0f;
  float gyroRollDps = 0.0f;
  float gyroPitchDps = 0.0f;
  float gyroYawDps = 0.0f;
  bool gyroBiasReady = false;
  uint16_t gyroBiasSamples = 0;
  float gyroRollBiasDps = 0.0f;
  float gyroPitchBiasDps = 0.0f;
  float gyroYawBiasDps = 0.0f;
  bool gyroBiasCaptureAllowed = false;
  float accelXg = 0.0f;
  float accelYg = 0.0f;
  float accelZg = 0.0f;
  float accelMagG = 0.0f;
  float accelRefG = 0.0f;
  uint8_t whoAmI = 0;
  uint16_t readFailures = 0;
  bool accelCorrectionUsed = false;
  // Unit quaternion: sensor frame after the right-handed X,+ / Y,- / Z,-
  // mounting transform, relative to the startup yaw frame.
  float q0 = 1.0f;
  float q1 = 0.0f;
  float q2 = 0.0f;
  float q3 = 0.0f;
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
  // There is no barometer driver or validated altitude estimate yet.
  bool enableAltitudeHold = false;
  // Conventional TAER model only. These independent input/output profiles
  // must match the airplane; automatic travel retains the previous authority.
  uint16_t aileronMinUs = 1000, aileronMaxUs = 2000;
  uint16_t elevatorMinUs = 1000, elevatorMaxUs = 2000;
  uint16_t stickDeadbandUs = 20;
  float rollInputSign = 1.0f, pitchInputSign = 1.0f;
  float maxCommandRollDeg = 30.0f;
  float maxCommandPitchUpDeg = 20.0f, maxCommandPitchDownDeg = 15.0f;
  float commandTimeConstantS = 0.12f;
  float commandRollSlewDps = 90.0f, commandPitchSlewDps = 60.0f;
  uint16_t neutralCaptureWindowUs = 80;
  uint32_t levelCaptureHoldMs = 1000;
  float levelCaptureMaxGyroDps = 1.0f;
  float levelCaptureMaxOffsetDeg = 3.0f;
  uint16_t launchDetectThrottleUs = 1120;
  uint32_t launchAutolevelLockoutMs = 5000;
  bool enableAttitudeBailout = true;
  float attitudeBailoutRollDeg = 55.0f;
  float attitudeBailoutPitchDeg = 35.0f;
  // The calibrated mounting matrix makes level zero in the estimator frame.
  float airframeLevelRollDeg = 0.0f;
  float airframeLevelPitchDeg = 0.0f;
  float flightPitchTrimDeg = 0.0f;

  // Cascaded fixed-wing controller: attitude error requests a body rate; the
  // gyro rate loop then commands normalized surface deflection.
  float rollAngleTimeConstantS = 0.85f;
  float pitchAngleTimeConstantS = 1.00f;
  float rollMaxTargetRateDps = 55.0f;
  float pitchMaxTargetRateDps = 35.0f;
  float rollRateFeedForwardPerDps = 0.0080f;
  float pitchRateFeedForwardPerDps = 0.0090f;
  float rollRateKpPerDps = 0.0040f;
  float pitchRateKpPerDps = 0.0045f;
  float rollRateKiPerDeg = 0.00035f;
  float pitchRateKiPerDeg = 0.00035f;
  float rateIntegratorLimit = 0.12f;


  float attitudeCorrectionDeadbandDeg = 0.75f;
  uint32_t autolevelRampMs = 100;
  float rollMaxCorrectionNorm = 0.32f;
  float pitchMaxCorrectionNorm = 0.44f;


  float altitudeKpUsPerMeter = 45.0f;
  uint16_t altitudeMaxCorrectionUs = 120;
};

struct AutopilotState {
  AutopilotMode mode = AP_MODE_MANUAL;
  uint32_t sticksCenteredSince = 0;
  float commandedRollDeg = 0;
  float commandedPitchDeg = 0;
  float appliedRollNorm = 0, appliedPitchNorm = 0;
  bool rollLimited = false, pitchLimited = false;
  uint32_t levelCaptureCandidateSince = 0;
  bool pilotAutolevelEnabled = false;
  bool sticksReleased = false;
  bool neutralCaptured = false;
  bool launchThrottleSeen = false;
  uint32_t launchThrottleSeenMs = 0;
  bool launchLockoutActive = false;
  const char *lastPilotToggleReason = "boot";
  uint32_t levelModeEnteredMs = 0;
  float correctionScale = 0.0f;
  uint16_t neutralAileronUs = RC_MID;
  uint16_t neutralElevatorUs = RC_MID;
  float effectiveRollDeg = 0.0f;
  float effectivePitchDeg = 0.0f;
  float effectiveRollRateDps = 0.0f;
  float effectivePitchRateDps = 0.0f;
  float rollErrDeg = 0.0f;
  float pitchErrDeg = 0.0f;
  int16_t rollAngleCorrectionUs = 0;
  int16_t pitchAngleCorrectionUs = 0;
  int16_t rollRateDampingUs = 0;
  int16_t pitchRateDampingUs = 0;
  int16_t targetAileronCorrectionUs = 0;
  int16_t targetElevatorCorrectionUs = 0;
  float altitudeTargetM = 0.0f;
  bool altitudeTargetCaptured = false;
  int16_t aileronCorrectionUs = 0;
  int16_t elevatorCorrectionUs = 0;
  int16_t throttleCorrectionUs = 0;
  float targetRollRateDps = 0.0f;
  float targetPitchRateDps = 0.0f;
  float rollRateIntegrator = 0.0f;
  float pitchRateIntegrator = 0.0f;
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
bool bindPlugBoot = false;
bool bindRestartRequired = false;
bool radioInitialized = false;
bool escMode = false;
bool armed = false;
uint32_t thrLowSince = 0;
uint32_t lastRxMs = 0;

uint16_t des_r=RC_MID, des_a=RC_MID, des_e=RC_MID, des_t=RC_MIN;
uint16_t cur_r=RC_MID, cur_a=RC_MID, cur_e=RC_MID, cur_t=RC_MIN;
uint16_t filt_r=RC_MID, filt_a=RC_MID, filt_e=RC_MID, filt_t=RC_MIN;

bool calibrationRequested = false;
bool calibrationStartPending = false;
uint32_t calibrationStartRequestedMs = 0;
bool calibrationButtonReleased = false;
bool calibrationButtonLastLow = false;
uint32_t calibrationButtonChangedMs = 0;

// Manual commands from the latest accepted radio packet.
uint16_t manual_r=RC_MID, manual_a=RC_MID, manual_e=RC_MID, manual_t=RC_MIN;

uint32_t rxPackets = 0;
uint32_t acceptedPackets = 0;
uint32_t rejectedPackets = 0;
uint32_t wrongLengthPackets = 0;
uint8_t lastWrongLength = 0;
uint32_t lastDebugMs = 0;
uint16_t lastPktBind = 0;
uint16_t lastPktSeq = 0;
uint8_t lastAuxFlags = 0;
int16_t lastRssi = 0;

float controlDtS = 0.01f;
uint32_t controlTicks = 0, controlMaxUs = 0, controlOverruns = 0;
uint32_t lastControlUs = 0;
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
  if (!isfinite(deg)) return 0; // callers reject invalid attitudes before use
  deg = fmodf(deg, 360.0f);
  if (deg > 180) deg -= 360;
  if (deg < -180) deg += 360;
  return deg;
}

static inline float applyAngleDeadband(float errorDeg, float deadbandDeg) {
  if (fabsf(errorDeg) <= deadbandDeg) return 0.0f;
  return errorDeg > 0.0f ? errorDeg - deadbandDeg : errorDeg + deadbandDeg;
}



void resetGyroBiasCapture() {
  if (imu.gyroBiasReady) return;
  imu.gyroBiasSamples = 0;
  imu.gyroRollBiasDps = 0.0f;
  imu.gyroPitchBiasDps = 0.0f;
  imu.gyroYawBiasDps = 0.0f;
  imu.accelRefG = 0.0f;
  imu.captureStartedMs = 0;
  for (uint8_t i=0;i<3;++i) {
    imu.accelSum[i] = imu.gyroSquareSum[i] = imu.captureGravity[i] = 0;
  }
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

// Publication is a few stores under an IRQ guard. TC4 generates all edges.
void writeServoFrame() {
  TimerServos::submit(cur_t, cur_a, cur_e, cur_r);
}

void disarmAndLock() {
  calibrationRequested = false;
  calibrationStartPending = false;
  armed = false;
  thrLowSince = 0;
  des_t = RC_MIN;
  apState.mode = AP_MODE_MANUAL;
  apState.pilotAutolevelEnabled = false;
  modeCommands.reset();
  apState.sticksReleased = false;
  apState.neutralCaptured = false;
  apState.launchThrottleSeen = false;
  apState.launchThrottleSeenMs = 0;
  apState.launchLockoutActive = false;
  apState.levelCaptureCandidateSince = 0;
  apState.altitudeTargetCaptured = false;
  apState.levelModeEnteredMs = 0;
  apState.correctionScale = 0.0f;
  apState.rollRateIntegrator = 0.0f;
  apState.pitchRateIntegrator = 0.0f;
  apState.appliedRollNorm = apState.appliedPitchNorm = 0;
}

void setPilotAutolevelEnabled(bool enabled, const char *reason) {
  apState.lastPilotToggleReason = reason ? reason : "unknown";
  if (apState.pilotAutolevelEnabled == enabled) {
    if (ENABLE_RX_DEBUG) {
      Serial.print("AP pilot command ignored: already ");
      Serial.print(enabled ? "ON" : "OFF");
      Serial.print(" reason=");
      Serial.println(apState.lastPilotToggleReason);
    }
    return;
  }
  apState.pilotAutolevelEnabled = enabled;
  apState.appliedRollNorm = apState.appliedPitchNorm = 0;
  apState.mode = AP_MODE_MANUAL;
  apState.sticksReleased = false;
  apState.sticksCenteredSince = 0;
  apState.altitudeTargetCaptured = false;
  apState.aileronCorrectionUs = 0;
  apState.elevatorCorrectionUs = 0;
  apState.throttleCorrectionUs = 0;
  apState.levelModeEnteredMs = 0;
  apState.correctionScale = 0.0f;
  apState.rollRateIntegrator = 0.0f;
  apState.pitchRateIntegrator = 0.0f;

  if (ENABLE_RX_DEBUG) {
    Serial.print("AP pilot toggle: ");
    Serial.print(enabled ? "ON" : "OFF");
    if (reason) {
      Serial.print(" reason=");
      Serial.print(reason);
    }
    Serial.println();
  }
}

void handleAutolevelAuxCommand(uint8_t auxFlags, uint32_t now) {
  AutolevelCommands::Command command = modeCommands.update(auxFlags);
  if (command == AutolevelCommands::DISABLE) {
    setPilotAutolevelEnabled(false, "aux-off");
  } else if (command == AutolevelCommands::ENABLE && armed && !escMode &&
             !bindMode && !bindRestartRequired && imu.ready && imu.healthy && imu.gyroBiasReady &&
             apState.neutralCaptured && (now - imu.lastSampleMs <= 30)) {
    setPilotAutolevelEnabled(true, "trainer-on");
  }
}

bool detectBindPlug() {
  pinMode(PIN_BIND_PLUG, INPUT_PULLUP);
  uint8_t lowSamples = 0;
  const uint8_t sampleCount = 8;
  for (uint8_t i = 0; i < sampleCount; ++i) {
    if (digitalRead(PIN_BIND_PLUG) == LOW) lowSamples++;
    delay(2);
  }
  return lowSamples == sampleCount;
}

void printUsbStatus() {
  Serial.print("STATUS radio=");
  Serial.print(radioInitialized ? "OK" : "ERROR");
  Serial.print(" bindMode=");
  Serial.print(bindMode ? "yes" : "no");
  Serial.print(" bindPlug=");
  Serial.print(bindPlugBoot ? "yes" : "no");
  Serial.print(" restartRequired=");
  Serial.print(bindRestartRequired ? "yes" : "no");
  Serial.print(" stored=");
  Serial.print((g_bind.magic == BIND_MAGIC) ? g_bind.bindCode : 0);
  Serial.print(" rx=");
  Serial.print(rxPackets);
  Serial.print(" accepted=");
  Serial.print(acceptedPackets);
  Serial.print(" rejected=");
  Serial.print(rejectedPackets);
  Serial.print(" pktBind=");
  Serial.print(lastPktBind);
  Serial.print(" rssi=");
  Serial.print(lastRssi);
  Serial.print(" armed=");
  Serial.print(armed ? "yes" : "no");
  Serial.print(" firmware=autolevel-fbwa-20261008 apMaster=");
  Serial.print(apState.pilotAutolevelEnabled ? "ON" : "OFF");
  Serial.print(" reason="); Serial.print(apState.lastPilotToggleReason);
  Serial.print(" mode="); Serial.print((int)apState.mode);
  Serial.print(" imu="); Serial.print(imu.ready ? "yes" : "no");
  Serial.print(" who="); Serial.print(imu.whoAmI, HEX);
  Serial.print(" accelG="); Serial.print(imu.accelMagG, 3);
  Serial.print(" bias="); Serial.print(imu.gyroBiasReady ? "yes" : "no");
  Serial.print(" calibration=");
  Serial.print(calibrationRequested ? "sampling" :
      (calibrationStartPending ? "delay" :
       (apState.neutralCaptured ? "ready" : "press-button")));
  Serial.print(" targetRoll="); Serial.print(apConfig.airframeLevelRollDeg, 2);
  Serial.print(" targetPitch="); Serial.print(apConfig.airframeLevelPitchDeg, 2);
  Serial.print(" neutral="); Serial.print(apState.neutralCaptured ? "yes" : "no");
  Serial.print(" roll="); Serial.print(imu.rollDeg, 2);
  Serial.print(" pitch="); Serial.println(imu.pitchDeg, 2);
}

void printUsbDiagnostics() {
  Serial.print("DIAG uptimeMs="); Serial.print(millis());
  Serial.print(" ticks="); Serial.print(controlTicks);
  Serial.print(" maxDtUs="); Serial.print(controlMaxUs);
  Serial.print(" overruns="); Serial.print(controlOverruns);
  Serial.print(" frames="); Serial.print(TimerServos::frames());
  Serial.print(" edgeLateUs="); Serial.print(TimerServos::maxLateUs());
  Serial.print(" timerFault="); Serial.print(TimerServos::failed());
  Serial.print(" samples="); Serial.print(imu.samples);
  Serial.print(" rejected="); Serial.print(imu.rejectedSamples);
  Serial.print(" ageMs="); Serial.print(millis()-imu.lastSampleMs);
  Serial.print(" healthy="); Serial.print(imu.healthy);
  Serial.print(" imuReason="); Serial.print(imu.fault);
  Serial.print(" biasSamples="); Serial.print(imu.gyroBiasSamples);
  Serial.print(" biasCap="); Serial.print(imu.gyroBiasCaptureAllowed);
  Serial.print(" captureMs="); Serial.print(imu.lastCaptureDurationMs);
  Serial.print(" captureVariance=");
  for (uint8_t i=0;i<3;++i) {
    if (i) Serial.print(",");
    Serial.print(imu.lastCaptureVariance[i],5);
  }
  Serial.print(" captureFailures="); Serial.print(imu.captureMotionFailures);
  Serial.print(" gyro="); Serial.print(imu.filteredRollDps,2);
  Serial.print(","); Serial.print(imu.filteredPitchDps,2);
  Serial.print(" command="); Serial.print(apState.commandedRollDeg,2);
  Serial.print(","); Serial.print(apState.commandedPitchDeg,2);
  Serial.print(" targetRate="); Serial.print(apState.targetRollRateDps,2);
  Serial.print(","); Serial.print(apState.targetPitchRateDps,2);
  Serial.print(" I="); Serial.print(apState.rollRateIntegrator,4);
  Serial.print(","); Serial.print(apState.pitchRateIntegrator,4);
  Serial.print(" limited="); Serial.print(apState.rollLimited);
  Serial.print(","); Serial.print(apState.pitchLimited);
  Serial.print(" output="); Serial.print(cur_t); Serial.print(",");
  Serial.print(cur_a); Serial.print(","); Serial.print(cur_e); Serial.print(",");
  Serial.println(cur_r);
}

// The desktop configurator uses BOOTLOADER to request the installed SAM-BA
// bootloader. STATUS is read-only and provides on-demand bench diagnostics
// without enabling continuous serial output in the flight loop.
void serviceUsbBootloaderRequest() {
  static char command[16] = {0};
  static uint8_t length = 0;
  static bool overflow = false;
  uint8_t budget = 32;
  while (budget-- && Serial.available()) {
    char c = (char)Serial.read();
    if (c == '\r') continue;
    if (c == '\n') {
      if (overflow) { overflow = false; length = 0; continue; }
      command[length] = '\0';
      if (strcmp(command, "STATUS") == 0) {
        printUsbStatus();
      } else if (strcmp(command, "DIAG") == 0) {
        printUsbDiagnostics();
      } else if (strcmp(command, "BOOTLOADER") == 0) {
        setSafeDesired();
        disarmAndLock();
        cur_t = RC_MIN;
        cur_a = cur_e = cur_r = RC_MID;
        writeServoFrame();
        delay(25); // allow one timer-generated safe frame before reset
        Serial.println("OK BOOTLOADER");
        Serial.flush();
        initiateReset(1);
        delay(1); // advances the SAMD core reset state machine once
        while (true) {}
      }
      length = 0;
    } else if (!overflow && length < sizeof(command) - 1) {
      command[length++] = c;
    } else {
      overflow = true;
    }
  }
}

void captureAutopilotNeutral() {
  apState.neutralAileronUs = manual_a;
  apState.neutralElevatorUs = manual_e;
  apState.neutralCaptured = true;
  calibrationRequested = false;
  apState.sticksCenteredSince = 0;
  apState.sticksReleased = false;

  if (ENABLE_RX_DEBUG) {
    Serial.print("AP neutral captured ail=");
    Serial.print(apState.neutralAileronUs);
    Serial.print(" ele=");
    Serial.print(apState.neutralElevatorUs);
    Serial.print(" fixedTarget=");
    Serial.print(apConfig.airframeLevelRollDeg, 1);
    Serial.print(",");
    Serial.println(apConfig.airframeLevelPitchDeg + apConfig.flightPitchTrimDeg, 1);
  }
}

bool readyToCaptureAutopilotNeutral(uint32_t now, uint32_t age) {
  if (!calibrationRequested || !armed || bindMode || escMode ||
      !apConfig.enableAutolevel || age > LINK_FRESH_MS || !imu.healthy ||
      now - imu.lastSampleMs > 30) {
    apState.levelCaptureCandidateSince = 0;
    return false;
  }
  if (!imu.ready || !imu.attitudeInitialized || !imu.gyroBiasReady) {
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
  float rollOffsetDeg = normalizeAngleDeg(imu.rollDeg - apConfig.airframeLevelRollDeg);
  float pitchOffsetDeg = imu.pitchDeg - apConfig.airframeLevelPitchDeg;
  if (fabsf(rollOffsetDeg) > apConfig.levelCaptureMaxOffsetDeg ||
      fabsf(pitchOffsetDeg) > apConfig.levelCaptureMaxOffsetDeg) {
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
  if (calibrationRequested) {
    bool shouldOn = ((now % CALIBRATION_LED_PERIOD_MS) < CALIBRATION_LED_ON_MS);
    if (shouldOn != on) {
      digitalWrite(LED_BUILTIN, shouldOn ? HIGH : LOW);
      on = shouldOn;
    }
    return;
  }
  if (ledState == LED_ARMED && apState.neutralCaptured && imu.healthy) {
    if (!on) {
      digitalWrite(LED_BUILTIN, HIGH);
      on = true;
    }
    return;
  }
  if (ledState == LED_ARMED) {
    const bool readyPulse = (now % 1000) < 100; // linked, still needs calibration
    if (readyPulse != on) { digitalWrite(LED_BUILTIN, readyPulse ? HIGH : LOW); on=readyPulse; }
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
  return sensorBus.writeRegister(addr, reg, value);
}

bool readReg(uint8_t addr, uint8_t reg, uint8_t &value) {
  return sensorBus.readRegisters(addr, reg, &value, 1);
}

bool readBytes(uint8_t addr, uint8_t reg, uint8_t *buf, uint8_t len) {
  return sensorBus.readRegisters(addr, reg, buf, len);
}

void printHex2(uint8_t v) {
  if (v < 16) Serial.print("0");
  Serial.print(v, HEX);
}

bool beginLsm6ds(uint8_t addr) {
  uint8_t who = 0;
  if (!readReg(addr, REG_WHO_AM_I, who)) return false;
  // This board uses LSM6DSO32; 0x6C alone cannot distinguish all family variants.
  if (who != 0x6C) return false;
  if (!writeReg(addr, REG_CTRL3_C, 0x44)) return false;
  if (!writeReg(addr, REG_CTRL1_XL, 0x42)) return false; // LPF2: ODR/4 = 26 Hz
  if (!writeReg(addr, 0x13, 0x02)) return false; // gyro LPF1 enabled
  if (!writeReg(addr, 0x15, 0x00)) return false; // gyro LPF1: 33 Hz at 104 Hz ODR
  if (!writeReg(addr, 0x17, 0x00)) return false; // XL LPF2 ODR/4, no high pass
  if (!writeReg(addr, REG_CTRL2_G, 0x40)) return false;
  uint8_t ctrl1 = 0, ctrl2 = 0, ctrl3 = 0;
  if (!readReg(addr, REG_CTRL1_XL, ctrl1) || ctrl1 != 0x42 ||
      !readReg(addr, REG_CTRL2_G, ctrl2) || ctrl2 != 0x40 ||
      !readReg(addr, REG_CTRL3_C, ctrl3) || ctrl3 != 0x44) return false;
  uint8_t filter = 0;
  if (!readReg(addr, 0x13, filter) || filter != 0x02 ||
      !readReg(addr, 0x15, filter) || filter != 0 ||
      !readReg(addr, 0x17, filter) || filter != 0) return false;
  imu.addr = addr;
  imu.ready = true;
  imu.attitudeInitialized = false;
  imu.gyroBiasReady = false;
  imu.gyroBiasSamples = 0;
  imu.gyroRollBiasDps = 0.0f;
  imu.gyroPitchBiasDps = 0.0f;
  imu.gyroYawBiasDps = 0.0f;
  imu.gyroBiasCaptureAllowed = false;
  imu.accelMagG = 0.0f;
  imu.accelRefG = 0.0f;
  imu.whoAmI = who;
  imu.readFailures = 0;
  imu.q0 = 1.0f; imu.q1 = 0.0f; imu.q2 = 0.0f; imu.q3 = 0.0f;
  imu.lastSampleMs = millis();
  imu.lastSampleUs = micros();
  return true;
}

void setupImu() {
  sensorBus.begin();
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

  if (sensorBus.probe(BARO_ADDR_LOW)) {
    baro.detected = true;
    baro.addr = BARO_ADDR_LOW;
    return;
  }

  if (sensorBus.probe(BARO_ADDR_HIGH)) {
    baro.detected = true;
    baro.addr = BARO_ADDR_HIGH;
  }
}

static inline int16_t s16(uint8_t lo, uint8_t hi) {
  return (int16_t)((uint16_t)lo | ((uint16_t)hi << 8));
}

static void setQuaternionFromRollPitch(float rollDeg, float pitchDeg) {
  float hr = 0.5f * rollDeg * RAD_PER_DEG;
  float hp = 0.5f * pitchDeg * RAD_PER_DEG;
  float cr = cosf(hr), sr = sinf(hr), cp = cosf(hp), sp = sinf(hp);
  imu.q0 = cr * cp;
  imu.q1 = sr * cp;
  imu.q2 = cr * sp;
  imu.q3 = -sr * sp;
}

static void updateQuaternionAhrs(float gxDps, float gyDps, float gzDps,
                                 float ax, float ay, float az,
                                 float dt, bool accelTrusted) {
  if (!isfinite(gxDps) || !isfinite(gyDps) || !isfinite(gzDps) ||
      !isfinite(ax) || !isfinite(ay) || !isfinite(az) ||
      !isfinite(dt) || dt <= 0 || dt > 0.03f) {
    imu.ready = imu.healthy = imu.attitudeInitialized = false;
    imu.fault = "numeric-or-dt";
    return;
  }
  float gx = gxDps * RAD_PER_DEG;
  float gy = gyDps * RAD_PER_DEG;
  float gz = gzDps * RAD_PER_DEG;
  imu.accelCorrectionUsed = false;
  float mag = sqrtf(ax * ax + ay * ay + az * az);
  if (accelTrusted && mag > 0.0001f) {
    ax /= mag; ay /= mag; az /= mag;
    float vx = 2.0f * (imu.q1 * imu.q3 - imu.q0 * imu.q2);
    float vy = 2.0f * (imu.q0 * imu.q1 + imu.q2 * imu.q3);
    float vz = imu.q0 * imu.q0 - imu.q1 * imu.q1 - imu.q2 * imu.q2 + imu.q3 * imu.q3;
    float alignment = ax * vx + ay * vy + az * vz;
    // A large innovation is more likely aircraft acceleration or a bad sample
    // than gyro drift.  0.906 is cos(25 degrees).
    if (alignment > 0.906f) {
      float ex = ay * vz - az * vy;
      float ey = az * vx - ax * vz;
      float ez = ax * vy - ay * vx;
      const float accelKp = 0.18f;
      gx += accelKp * ex; gy += accelKp * ey; gz += accelKp * ez;
      imu.accelCorrectionUsed = true;
    }
  }
  float halfDt = 0.5f * dt;
  float q0 = imu.q0, q1 = imu.q1, q2 = imu.q2, q3 = imu.q3;
  imu.q0 += (-q1 * gx - q2 * gy - q3 * gz) * halfDt;
  imu.q1 += ( q0 * gx + q2 * gz - q3 * gy) * halfDt;
  imu.q2 += ( q0 * gy - q1 * gz + q3 * gx) * halfDt;
  imu.q3 += ( q0 * gz + q1 * gy - q2 * gx) * halfDt;
  float normSquared = imu.q0 * imu.q0 + imu.q1 * imu.q1 +
                      imu.q2 * imu.q2 + imu.q3 * imu.q3;
  if (!isfinite(normSquared) || normSquared < 0.000001f) {
    imu.ready = imu.healthy = false;
    imu.fault = "quaternion";
    imu.attitudeInitialized = false;
    return;
  }
  float invNorm = 1.0f / sqrtf(normSquared);
  imu.q0 *= invNorm; imu.q1 *= invNorm; imu.q2 *= invNorm; imu.q3 *= invNorm;
  imu.rollDeg = atan2f(2.0f * (imu.q0 * imu.q1 + imu.q2 * imu.q3),
                       1.0f - 2.0f * (imu.q1 * imu.q1 + imu.q2 * imu.q2)) * DEG_PER_RAD;
  float sinPitch = 2.0f * (imu.q0 * imu.q2 - imu.q3 * imu.q1);
  if (sinPitch > 1.0f) sinPitch = 1.0f;
  if (sinPitch < -1.0f) sinPitch = -1.0f;
  imu.pitchDeg = asinf(sinPitch) * DEG_PER_RAD;
}

bool calibrationInputsReady(uint32_t now) {
  return !bindMode && !bindRestartRequired && !escMode && imu.ready &&
      acceptedPackets > 0 && now - lastRxMs <= LINK_FRESH_MS &&
      manual_t <= UNLOCK_THRESH_US &&
      stickNearCenter(manual_a, apConfig.neutralCaptureWindowUs) &&
      stickNearCenter(manual_e, apConfig.neutralCaptureWindowUs);
}

void beginCalibration() {
  calibrationStartPending = false;
  setPilotAutolevelEnabled(false, "calibration");
  modeCommands.reset();
  apState.neutralCaptured = false;
  apState.launchThrottleSeen = false;
  apState.launchThrottleSeenMs = 0;
  apState.levelCaptureCandidateSince = 0;
  imu.gyroBiasReady = false;
  resetGyroBiasCapture();
  imu.attitudeInitialized = false;
  imu.healthy = false;
  imu.fault = "calibrating";
  imu.filterInitialized = false;
  imu.untrustedSinceMs = imu.invalidAccelSinceMs = 0;
  imuMount = AttitudeControl::Mount{};
  calibrationRequested = true;
}

// Release after boot is required, so the boot binding gesture cannot calibrate.
void serviceCalibrationButton(uint32_t now) {
  if (calibrationStartPending &&
      now - calibrationStartRequestedMs >= CALIBRATION_START_DELAY_MS) {
    if (calibrationInputsReady(now)) beginCalibration();
    else calibrationStartPending = false;
  }

  bool low = digitalRead(PIN_BIND_BTN) == LOW;
  if (low != calibrationButtonLastLow) {
    calibrationButtonLastLow = low;
    calibrationButtonChangedMs = now;
  }
  if (now - calibrationButtonChangedMs < 40) return;
  if (!low) { calibrationButtonReleased = true; return; }
  if (!calibrationButtonReleased) return;
  calibrationButtonReleased = false;
  if (!calibrationInputsReady(now)) return;
  calibrationStartRequestedMs = now;
  calibrationStartPending = true;
}

void updateImuEstimate(uint32_t now, bool allowGyroBiasCapture) {
  if (!imu.ready) return;
  uint8_t status = 0, b[12];
  if (!readReg(imu.addr, REG_STATUS, status)) {
    resetGyroBiasCapture();
    if (++imu.readFailures >= 5) { imu.ready = imu.healthy = false; imu.fault = "i2c"; }
    return;
  }
  if ((status & 3) != 3) {
    if (now - imu.lastSampleMs > 30) {
      imu.healthy = false; imu.fault = "no-new-sample";
      resetGyroBiasCapture();
    }
    return; // never integrate or calibrate a repeated sample
  }
  if (!readBytes(imu.addr, REG_OUTX_L_G, b, sizeof(b))) {
    resetGyroBiasCapture();
    if (++imu.readFailures >= 5) { imu.ready = imu.healthy = false; imu.fault = "i2c"; }
    return;
  }
  imu.readFailures = 0;
  const uint32_t sampledUs = micros();
  float g[3] = {s16(b[0],b[1]) * LSM6DS_GYRO_DPS_PER_LSB,
                -s16(b[2],b[3]) * LSM6DS_GYRO_DPS_PER_LSB,
                -s16(b[4],b[5]) * LSM6DS_GYRO_DPS_PER_LSB};
  float a[3] = {s16(b[6],b[7]) * LSM6DS_ACCEL_G_PER_LSB,
                -s16(b[8],b[9]) * LSM6DS_ACCEL_G_PER_LSB,
                -s16(b[10],b[11]) * LSM6DS_ACCEL_G_PER_LSB};
  imu.accelMagG = sqrtf(a[0]*a[0]+a[1]*a[1]+a[2]*a[2]);
  if (imu.accelMagG < 0.05f || fabsf(g[0]) >= 245 ||
      fabsf(g[1]) >= 245 || fabsf(g[2]) >= 245) {
    ++imu.rejectedSamples;
    imu.healthy = false;
    imu.fault = imu.accelMagG < 0.05f ? "accel-invalid" : "gyro-clipped";
    resetGyroBiasCapture();
    return; // no freshness credit for an implausible measurement
  }
  bool captureOk = calibrationRequested && allowGyroBiasCapture &&
      imu.accelMagG >= 0.9f && imu.accelMagG <= 1.1f;
  for (uint8_t i=0;i<3;++i) captureOk &= fabsf(g[i]) <= AP_GYRO_BIAS_CAPTURE_MAX_RAW_DPS;
  if (!imu.gyroBiasReady && captureOk && imu.gyroBiasSamples > 0) {
    float alignment = 0;
    for (uint8_t i=0;i<3;++i) alignment += a[i]/imu.accelMagG * imu.captureGravity[i];
    captureOk = alignment > 0.99985f; // <1 degree motion across the capture window
  }
  imu.gyroBiasCaptureAllowed = captureOk;
  if (!imu.gyroBiasReady && !captureOk) resetGyroBiasCapture();
  if (!imu.gyroBiasReady && captureOk) {
    if (imu.gyroBiasSamples == 0) {
      imu.captureStartedMs = now;
      for (uint8_t i=0;i<3;++i) imu.captureGravity[i] = a[i]/imu.accelMagG;
    }
    imu.gyroRollBiasDps += g[0]; imu.gyroPitchBiasDps += g[1]; imu.gyroYawBiasDps += g[2];
    for (uint8_t i=0;i<3;++i) { imu.accelSum[i] += a[i]; imu.gyroSquareSum[i] += g[i]*g[i]; }
    imu.accelRefG += imu.accelMagG;
    ++imu.gyroBiasSamples;
    if (imu.gyroBiasSamples >= AP_GYRO_BIAS_SAMPLE_COUNT) {
      const float count = imu.gyroBiasSamples;
      float bias[3] = {imu.gyroRollBiasDps/count, imu.gyroPitchBiasDps/count, imu.gyroYawBiasDps/count};
      imu.lastCaptureDurationMs = now - imu.captureStartedMs;
      bool steady = imu.lastCaptureDurationMs >= 1000;
      for (uint8_t i=0;i<3;++i) {
        imu.lastCaptureVariance[i] = imu.gyroSquareSum[i]/count - bias[i]*bias[i];
        steady &= imu.lastCaptureVariance[i] < 0.04f;
      }
      float ax=imu.accelSum[0]/count, ay=imu.accelSum[1]/count, az=imu.accelSum[2]/count;
      if (!steady || !imuMount.setGravity(ax,ay,az)) {
        ++imu.captureMotionFailures;
        resetGyroBiasCapture();
        imu.fault = "calibration-motion";
        return;
      }
      imu.gyroRollBiasDps = bias[0]; imu.gyroPitchBiasDps = bias[1]; imu.gyroYawBiasDps = bias[2];
      imu.accelRefG /= count;
      imu.calibrationRollDeg = atan2f(ay,az)*DEG_PER_RAD;
      imu.calibrationPitchDeg = atan2f(-ax,sqrtf(ay*ay+az*az))*DEG_PER_RAD;
      imu.gyroBiasReady = true;
      imu.attitudeInitialized = false;
      imu.filterInitialized = false;
      imu.untrustedSinceMs = 0;
    }
  }
  if (imu.gyroBiasReady) {
    g[0] -= imu.gyroRollBiasDps; g[1] -= imu.gyroPitchBiasDps; g[2] -= imu.gyroYawBiasDps;
    imuMount.rotate(g[0],g[1],g[2]);
    imuMount.rotate(a[0],a[1],a[2]);
  } else {
    g[0]=g[1]=g[2]=0;
  }
  imu.accelXg=a[0]; imu.accelYg=a[1]; imu.accelZg=a[2];
  imu.gyroRollDps=g[0]; imu.gyroPitchDps=g[1]; imu.gyroYawDps=g[2];
  float dt = (sampledUs - imu.lastSampleUs) * 0.000001f;
  if (!imu.attitudeInitialized) {
    imu.rollDeg = atan2f(a[1],a[2])*DEG_PER_RAD;
    imu.pitchDeg = atan2f(-a[0],sqrtf(a[1]*a[1]+a[2]*a[2]))*DEG_PER_RAD;
    setQuaternionFromRollPitch(imu.rollDeg,imu.pitchDeg);
    imu.attitudeInitialized = true;
    dt = 0.01f;
  } else if (dt < 0.001f || dt > 0.03f) {
    // Missing angular motion cannot be reconstructed. Require a fresh ground
    // calibration, never silently snap to apparent gravity in flight.
    imu.healthy = false; imu.fault = "sample-gap";
    imu.gyroBiasReady = false; resetGyroBiasCapture();
    apState.neutralCaptured = false;
    imu.lastSampleUs = sampledUs;
    return;
  }
  imu.lastSampleUs=sampledUs; imu.lastSampleMs=now; ++imu.samples;
  bool accelTrusted = imu.accelMagG >= (imu.gyroBiasReady ? imu.accelRefG*AP_ACCEL_TRUST_MIN_RATIO : 0.9f) &&
                      imu.accelMagG <= (imu.gyroBiasReady ? imu.accelRefG*AP_ACCEL_TRUST_MAX_RATIO : 1.1f);
  updateQuaternionAhrs(g[0],g[1],g[2],a[0],a[1],a[2],dt,accelTrusted);
  if (!imu.ready) return;
  if (!imu.filterInitialized) {
    imu.filteredRollDps=g[0]; imu.filteredPitchDps=g[1]; imu.filterInitialized=true;
  } else {
    const float alpha = dt/(0.007958f+dt); // 20 Hz rate-feedback low pass
    imu.filteredRollDps += alpha*(g[0]-imu.filteredRollDps);
    imu.filteredPitchDps += alpha*(g[1]-imu.filteredPitchDps);
  }
  if (!imu.accelCorrectionUsed && imu.gyroBiasReady) {
    if (!imu.untrustedSinceMs) imu.untrustedSinceMs=now;
    if (now-imu.untrustedSinceMs > 3000) {
      imu.healthy=false; imu.fault="gravity-disagreement";
      return; // deliberately requires recalibration; no in-flight attitude reset
    }
  } else imu.untrustedSinceMs=0;
  // A degraded estimate cannot regain eligibility merely because a gate opens.
  if (imu.gyroBiasReady && (imu.fault == nullptr ||
      strcmp(imu.fault,"calibrating")==0 || strcmp(imu.fault,"uncalibrated")==0 ||
      strcmp(imu.fault,"calibration-motion")==0 || strcmp(imu.fault,"ok")==0)) {
    imu.healthy=true; imu.fault="ok";
  }
}

void updateAutopilotState(uint32_t now, uint32_t age) {
  const AutopilotMode previousMode=apState.mode;
  apState.mode=AP_MODE_MANUAL;
  apState.aileronCorrectionUs=apState.elevatorCorrectionUs=apState.throttleCorrectionUs=0;
  if (!apState.launchThrottleSeen && manual_t >= apConfig.launchDetectThrottleUs) {
    apState.launchThrottleSeen=true; apState.launchThrottleSeenMs=now;
  }
  apState.launchLockoutActive=apState.launchThrottleSeen &&
      now-apState.launchThrottleSeenMs < apConfig.launchAutolevelLockoutMs;
  // Validate before angle wrapping, division, integration, or integer conversion.
  bool numeric=isfinite(imu.rollDeg) && isfinite(imu.pitchDeg) &&
      isfinite(imu.filteredRollDps) && isfinite(imu.filteredPitchDps) &&
      isfinite(apState.rollRateIntegrator) && isfinite(apState.pitchRateIntegrator) &&
      isfinite(apState.commandedRollDeg) && isfinite(apState.commandedPitchDeg) &&
      isfinite(apState.appliedRollNorm) && isfinite(apState.appliedPitchNorm) &&
      isfinite(controlDtS) && controlDtS >= 0.001f && controlDtS <= 0.03f;
  if (!numeric) setPilotAutolevelEnabled(false,"controller-invalid");
  if (!numeric || !armed || bindMode || escMode || age>LINK_FRESH_MS ||
      !apConfig.enableAutolevel || !apState.pilotAutolevelEnabled ||
      !apState.neutralCaptured || !imu.ready || !imu.healthy ||
      !imu.attitudeInitialized || !imu.gyroBiasReady ||
      now-imu.lastSampleMs>30 || apState.launchLockoutActive) {
    apState.rollRateIntegrator=apState.pitchRateIntegrator=0;
    apState.appliedRollNorm=apState.appliedPitchNorm=0;
    apState.sticksReleased=false;
    return;
  }
  if (apConfig.aileronMinUs >= apState.neutralAileronUs ||
      apState.neutralAileronUs >= apConfig.aileronMaxUs ||
      apConfig.elevatorMinUs >= apState.neutralElevatorUs ||
      apState.neutralElevatorUs >= apConfig.elevatorMaxUs) {
    setPilotAutolevelEnabled(false,"servo-profile"); return;
  }
  apState.effectiveRollDeg=-normalizeAngleDeg(imu.rollDeg-apConfig.airframeLevelRollDeg);
  apState.effectivePitchDeg=imu.pitchDeg-apConfig.airframeLevelPitchDeg;
  apState.effectiveRollRateDps=-imu.filteredRollDps;
  apState.effectivePitchRateDps=imu.filteredPitchDps;
  if (apConfig.enableAttitudeBailout && apState.launchThrottleSeen &&
      (fabsf(apState.effectiveRollDeg)>apConfig.attitudeBailoutRollDeg ||
       fabsf(apState.effectivePitchDeg)>apConfig.attitudeBailoutPitchDeg)) {
    setPilotAutolevelEnabled(false,"attitude-bailout"); return;
  }
  const float rollInput=apConfig.rollInputSign*AttitudeControl::stick(manual_a,
      apState.neutralAileronUs,apConfig.aileronMinUs,apConfig.aileronMaxUs,apConfig.stickDeadbandUs);
  const float pitchInput=apConfig.pitchInputSign*AttitudeControl::stick(manual_e,
      apState.neutralElevatorUs,apConfig.elevatorMinUs,apConfig.elevatorMaxUs,apConfig.stickDeadbandUs);
  const float requestedRoll=rollInput*apConfig.maxCommandRollDeg;
  const float requestedPitch=pitchInput*(pitchInput>=0 ? apConfig.maxCommandPitchUpDeg :
                                        apConfig.maxCommandPitchDownDeg)+apConfig.flightPitchTrimDeg;
  if (previousMode<AP_MODE_LEVEL_HOLD) {
    apState.levelModeEnteredMs=now;
    apState.commandedRollDeg=AttitudeControl::bound(apState.effectiveRollDeg,
        -apConfig.maxCommandRollDeg,apConfig.maxCommandRollDeg);
    apState.commandedPitchDeg=AttitudeControl::bound(apState.effectivePitchDeg,
        -apConfig.maxCommandPitchDownDeg,apConfig.maxCommandPitchUpDeg);
    // Track the last surface position, bounded to existing automatic authority.
    apState.appliedRollNorm=clampFloat(((int)cur_a-(int)apState.neutralAileronUs)/500.0f,
                                     apConfig.rollMaxCorrectionNorm);
    apState.appliedPitchNorm=clampFloat(((int)cur_e-(int)apState.neutralElevatorUs)/500.0f,
                                      apConfig.pitchMaxCorrectionNorm);
  }
  const float alpha=controlDtS/(apConfig.commandTimeConstantS+controlDtS);
  apState.commandedRollDeg=AttitudeControl::approach(apState.commandedRollDeg,
      apState.commandedRollDeg+alpha*(requestedRoll-apState.commandedRollDeg),
      apConfig.commandRollSlewDps*controlDtS);
  apState.commandedPitchDeg=AttitudeControl::approach(apState.commandedPitchDeg,
      apState.commandedPitchDeg+alpha*(requestedPitch-apState.commandedPitchDeg),
      apConfig.commandPitchSlewDps*controlDtS);
  apState.rollErrDeg=applyAngleDeadband(normalizeAngleDeg(apState.commandedRollDeg-
      apState.effectiveRollDeg),apConfig.attitudeCorrectionDeadbandDeg);
  apState.pitchErrDeg=applyAngleDeadband(apState.commandedPitchDeg-
      apState.effectivePitchDeg,apConfig.attitudeCorrectionDeadbandDeg);
  apState.targetRollRateDps=clampFloat(apState.rollErrDeg/apConfig.rollAngleTimeConstantS,
                                      apConfig.rollMaxTargetRateDps);
  apState.targetPitchRateDps=clampFloat(apState.pitchErrDeg/apConfig.pitchAngleTimeConstantS,
                                       apConfig.pitchMaxTargetRateDps);
  apState.correctionScale=apConfig.autolevelRampMs ?
      AttitudeControl::bound((now-apState.levelModeEnteredMs)/(float)apConfig.autolevelRampMs,0,1) : 1;
  // No bench/ground I accumulation before the first launch. After launch, low
  // throttle may be gliding: retain normal integral control then.
  const bool integrate=apState.launchThrottleSeen && apState.correctionScale>=1;
  const float rollLow=fmaxf(-apConfig.rollMaxCorrectionNorm,
      ((int)apConfig.aileronMinUs-(int)apState.neutralAileronUs)/500.0f);
  const float rollHigh=fminf(apConfig.rollMaxCorrectionNorm,
      ((int)apConfig.aileronMaxUs-(int)apState.neutralAileronUs)/500.0f);
  const float pitchLow=fmaxf(-apConfig.pitchMaxCorrectionNorm,
      ((int)apConfig.elevatorMinUs-(int)apState.neutralElevatorUs)/500.0f);
  const float pitchHigh=fminf(apConfig.pitchMaxCorrectionNorm,
      ((int)apConfig.elevatorMaxUs-(int)apState.neutralElevatorUs)/500.0f);
  auto roll=AttitudeControl::rate(apState.targetRollRateDps,apState.effectiveRollRateDps,
      apConfig.rollRateFeedForwardPerDps,apConfig.rollRateKpPerDps,apConfig.rollRateKiPerDeg,
      controlDtS,rollLow,rollHigh,apState.appliedRollNorm,apState.correctionScale,
      apState.rollRateIntegrator,apConfig.rateIntegratorLimit,integrate);
  auto pitch=AttitudeControl::rate(apState.targetPitchRateDps,apState.effectivePitchRateDps,
      apConfig.pitchRateFeedForwardPerDps,apConfig.pitchRateKpPerDps,apConfig.pitchRateKiPerDeg,
      controlDtS,pitchLow,pitchHigh,apState.appliedPitchNorm,apState.correctionScale,
      apState.pitchRateIntegrator,apConfig.rateIntegratorLimit,integrate);
  if (!isfinite(roll.output) || !isfinite(pitch.output)) {
    setPilotAutolevelEnabled(false,"output-invalid"); return;
  }
  apState.appliedRollNorm=roll.output; apState.appliedPitchNorm=pitch.output;
  apState.rollLimited=roll.limited; apState.pitchLimited=pitch.limited;
  apState.aileronCorrectionUs=lroundf(500*AP_AILERON_CORRECTION_SIGN*roll.output);
  apState.elevatorCorrectionUs=lroundf(500*AP_ELEVATOR_CORRECTION_SIGN*pitch.output);
  apState.targetAileronCorrectionUs=apState.aileronCorrectionUs;
  apState.targetElevatorCorrectionUs=apState.elevatorCorrectionUs;
  apState.sticksReleased=true; // compatibility diagnostic: now means stabilized
  apState.mode=AP_MODE_LEVEL_HOLD;
}

void applyManualOrAutopilotDesired() {
  des_r = manual_r;
  des_a = manual_a;
  des_e = manual_e;
  des_t = manual_t;

  if (apState.mode >= AP_MODE_LEVEL_HOLD) {
    // Once level mode is active, use the captured neutral as the base output.
    // This prevents a small released-stick offset from silently commanding a
    // turn or pitch while the controller is trying to hold attitude.
    des_a = clampRc((int32_t)apState.neutralAileronUs + apState.aileronCorrectionUs);
    des_e = clampRc((int32_t)apState.neutralElevatorUs + apState.elevatorCorrectionUs);
  }

  if (apState.mode == AP_MODE_LEVEL_AND_ALT_HOLD) {
    des_t = clampRc((int32_t)manual_t + apState.throttleCorrectionUs);
  }
}

// ------------------------------
// Setup
// ------------------------------
void setup() {
  Serial.begin(115200);
  if (ENABLE_RX_DEBUG) {
    delay(50);
  }

  pinMode(LED_BUILTIN, OUTPUT);
  pinMode(PIN_BIND_BTN, INPUT_PULLUP);
  bindPlugBoot = detectBindPlug();
  bindMode = (digitalRead(PIN_BIND_BTN) == LOW) || bindPlugBoot;
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
  setSafeDesired();
  disarmAndLock();

  if (!bindPlugBoot) {
    setupImu();
    setupBaroPlaceholder();
  }

  hardResetRadio();
  radioInitialized = rf95.init();
  if (!radioInitialized) {
    while (1) {
      serviceUsbBootloaderRequest();
      digitalWrite(LED_BUILTIN, !digitalRead(LED_BUILTIN));
      delay(100);
    }
  }
  rf95.setModemConfig(MODEM);
  rf95.setFrequency(RF95_FREQ);
  TimerServos::begin(PIN_SERVO_THROTTLE, PIN_SERVO_AILERON,
                     PIN_SERVO_ELEVATOR, PIN_SERVO_RUDDER);
  writeServoFrame();

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
      Serial.print(" WHO_AM_I=0x");
      printHex2(imu.whoAmI);
      Serial.println(" registers verified");
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
  serviceUsbBootloaderRequest();
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
        if (bp.magic == BIND_MAGIC && bp.code && bp.code <= 0x7FFF) {
          g_bind.magic = BIND_MAGIC;
          g_bind.bindCode = bp.code;
          // Flash operations cannot guarantee IRQ latency. Binding is disarmed:
          // stop safe pulses during the write, then start a new safe schedule.
          TimerServos::pause();
          saveBind(g_bind);
          TimerServos::begin(PIN_SERVO_THROTTLE, PIN_SERVO_AILERON,
                             PIN_SERVO_ELEVATOR, PIN_SERVO_RUDDER);
          bindMode = false;
          bindRestartRequired = bindPlugBoot;
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

          const bool accept = !bindMode && !bindRestartRequired &&
              g_bind.magic == BIND_MAGIC && g_bind.bindCode != 0 &&
              pktBind == g_bind.bindCode;
          if (accept && pktEsc) {
            if (escFlagStreak < 255) escFlagStreak++;
          } else {
            escFlagStreak = 0;
          }
          if (accept) {
            acceptedPackets++;
            manual_r = pkt.ch_rud;
            manual_a = pkt.ch_ail;
            manual_e = pkt.ch_ele;
            manual_t = pkt.ch_thr;
            lastAuxFlags = pkt.aux_flags;
            if (now - lastRxMs > LINK_FRESH_MS) {
              setPilotAutolevelEnabled(false, "link-recovered");
              modeCommands.reset();
            }
            lastRxMs = now;
            handleAutolevelAuxCommand(pkt.aux_flags, now);
          } else {
            rejectedPackets++;
          }

          if (accept && !escMode &&
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
      } else {
        wrongLengthPackets++;
        lastWrongLength = len;
      }
    }
  }

  static uint32_t lastTick = 0;
  if (now - lastTick >= CONTROL_PERIOD_MS) {
    lastTick = now;
    const uint32_t tickUs=micros();
    const uint32_t elapsedUs=lastControlUs ? tickUs-lastControlUs : 10000;
    lastControlUs=tickUs;
    ++controlTicks;
    if (elapsedUs>controlMaxUs) controlMaxUs=elapsedUs;
    controlDtS=elapsedUs*0.000001f;
    if (elapsedUs>30000 || TimerServos::failed()) {
      ++controlOverruns;
      setPilotAutolevelEnabled(false,"timing-fault");
      modeCommands.reset();
    }
    uint32_t age = now - lastRxMs;
    if (age > LINK_FRESH_MS) {
      setPilotAutolevelEnabled(false, "link-stale");
      modeCommands.reset();
    }
    serviceCalibrationButton(now);
    bool allowGyroBiasCapture =
        !bindMode && !bindRestartRequired && !escMode && acceptedPackets > 0 &&
        age <= LINK_FRESH_MS &&
        manual_t <= UNLOCK_THRESH_US &&
        stickNearCenter(manual_a, apConfig.neutralCaptureWindowUs) &&
        stickNearCenter(manual_e, apConfig.neutralCaptureWindowUs);
    updateImuEstimate(now, allowGyroBiasCapture);
    now=millis();
    age=now-lastRxMs;
    if (!imu.ready || !imu.healthy || !imu.attitudeInitialized || now - imu.lastSampleMs > 30 ||
        !isfinite(imu.rollDeg) || !isfinite(imu.pitchDeg)) {
      setPilotAutolevelEnabled(false, "imu-invalid");
      modeCommands.reset();
    }

    bool inBootGuard = (now - bootMs) < BOOT_CALIB_GUARD_MS;
    if (inBootGuard && !escMode) {
      des_t = RC_MIN;
    }

    if (bindRestartRequired || (!bindMode && acceptedPackets == 0)) {
      setSafeDesired();
      disarmAndLock();
      ledState = LED_LOCKED;
    } else if (!bindMode && !escMode) {
      if (!armed) {
        if (!inBootGuard && age <= LINK_FRESH_MS && manual_t <= UNLOCK_THRESH_US) {
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
        if (age <= LINK_FRESH_MS) {
          updateAutopilotState(now, age);
          applyManualOrAutopilotDesired();
          ledState = LED_ARMED;
        } else if (age <= FS_THR_CUTOFF_MS) {
          // Hold the final mixed outputs briefly.  Do not abruptly remove an
          // active level correction simply because the link became stale.
          ledState = LED_LOST;
        } else if (age <= FS_THR_DISARM_MS) {
          // Match production's 1200 ms ordinary-flight throttle hold.
          ledState = LED_LOST;
        } else {
          disarmAndLock();
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
        disarmAndLock();
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

    // Enforce after desired-output selection; manual mapping must not undo it.
    if ((inBootGuard && !escMode) || (!armed && !escMode)) des_t = RC_MIN;

    auto lerp = [](uint16_t cur, uint16_t tgt, float a) {
      return (uint16_t)((1.0f - a) * cur + a * tgt + 0.5f);
    };
    filt_r = lerp(filt_r, des_r, RX_SMOOTH_ALPHA);
    filt_a = lerp(filt_a, des_a, RX_SMOOTH_ALPHA);
    filt_e = lerp(filt_e, des_e, RX_SMOOTH_ALPHA);
    filt_t = lerp(filt_t, des_t, RX_SMOOTH_ALPHA);

    if (armed || escMode) {
      setServoIfChanged(cur_t, filt_t);
      cur_a = filt_a;
      cur_e = filt_e;
      cur_r = filt_r;
    } else {
      cur_t = RC_MIN;
      cur_a = filt_a;
      cur_e = filt_e;
      cur_r = filt_r;
    }

    if (TimerServos::failed()) {
      disarmAndLock(); cur_t=RC_MIN; cur_a=cur_e=cur_r=RC_MID;
    }
    writeServoFrame(); // refresh publication watchdog at every control update
    updateLed();
  }

  if (ENABLE_RX_DEBUG && now - lastDebugMs >= AP_DEBUG_PERIOD_MS) {
    lastDebugMs = now;
    printUsbDiagnostics();
  }
}
