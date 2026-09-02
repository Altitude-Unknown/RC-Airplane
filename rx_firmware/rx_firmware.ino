/*
  ===========================================
  LoRa RC Receiver (Feather M0 / SAMD21) v6
  ===========================================
  - Receives RC packets (RH_RF95) ~100 Hz.
  - Channels: Rudder, Aileron, Elevator, Throttle + flags + seq.
  - D10 held LOW at power-up -> Bind Mode (slow blink).
  - Rudder signal (A3) shorted to ground at power-up -> safe bind-plug mode.
  - In Bind Mode, waits for BindPacket { 'BIND', code } and stores to Flash.
  - Normal mode: accepts control packets if pkt.flags & 0x7FFF == stored bind code.
  - ESC Mode (intentional): requires several consecutive ESC-flagged packets
    during boot window AND throttle high; then bypasses arming and outputs throttle.
  - Failsafe (all modes):
      * 0–1s no packets: hold last surfaces (motor condition per mode)
      * >=1s: kill motor (RC_MIN)
      * >=3s: neutralize surfaces (RC_MID)
  - LED meanings:
      SOLID        = Armed / outputs active
      SLOW 200/800 = Locked/disarmed
      FAST 100/100 = RF stale / lost
      BIND 600/600 = Bind mode (waiting)

  BIG PICTURE FOR BEGINNERS
  -------------------------
  This receiver is the airplane side of the RC link.

  1. The transmitter sends a small radio packet many times per second.
  2. This receiver checks that the packet is valid and belongs to this model.
  3. The packet contains four channel commands:
       - rudder
       - aileron
       - elevator
       - throttle
  4. The receiver converts those commands into servo pulses.
  5. If the radio link goes stale, the receiver enters failsafe:
       - first it kills throttle
       - later it centers the control surfaces

  IMPORTANT SAFETY IDEA:
  The receiver starts disarmed. It will not allow throttle until it sees a fresh
  radio link and the transmitter throttle is low for a short time.
*/

#include <SPI.h>
#include <RH_RF95.h>
#include <Reset.h>
#include <FlashStorage_SAMD.h>
#include <string.h>

#if defined(ARDUINO_ARCH_SAMD)
  #include "wiring_private.h"
#endif

// ------------------------------
// LoRa wiring
// ------------------------------
// These pins connect the Feather M0 to the RFM95 LoRa radio module.
// CS selects the radio on the SPI bus, INT is the radio interrupt pin, and RST
// lets the microcontroller reset the radio chip if needed.
#define RFM95_CS   8
#define RFM95_INT  3
#define RFM95_RST  4
#define RF95_FREQ  915.0
RH_RF95 rf95(RFM95_CS, RFM95_INT);

// This radio setting favors low latency. It should match the transmitter.
const RH_RF95::ModemConfigChoice MODEM = RH_RF95::Bw500Cr45Sf128;

// ------------------------------
// Outputs
// ------------------------------
// These pins generate normal RC servo pulses.
// A servo/ESC pulse is usually about:
//   1000 us = one end of travel / throttle off
//   1500 us = center
//   2000 us = the other end of travel / full throttle
const int PIN_SERVO_THROTTLE = A0;
const int PIN_SERVO_AILERON  = A1;
const int PIN_SERVO_ELEVATOR = A2;
const int PIN_SERVO_RUDDER   = A3;

// ------------------------------
// Bind button
// ------------------------------
// Hold this button low while powering the receiver to teach it the transmitter's
// bind code. The bind code prevents this receiver from listening to the wrong
// transmitter.
const int PIN_BIND_BTN = 10;

// ------------------------------
// RC pulse ranges
// ------------------------------
// These are standard RC servo pulse widths in microseconds.
const uint16_t RC_MIN = 1000;
const uint16_t RC_MID = 1500;
const uint16_t RC_MAX = 2000;

// Servos expect a new pulse about every 20 ms, which is 50 times per second.
const uint32_t SERVO_PERIOD_MS = 20;

// Ignore tiny one-or-two-microsecond changes so we do not constantly rewrite
// outputs for changes too small to matter.
const uint16_t SERVO_DEADBAND_US = 2;

// 1.0 means the receiver outputs the transmitter command immediately.
// Lower values would smooth the motion, but would also add some lag.
const float RX_SMOOTH_ALPHA = 1.0f; // Direct servo response; use TX rates/expo for feel.

// ------------------------------
// Failsafe (staged)
// ------------------------------
// Failsafe is staged so a tiny radio hiccup does not instantly jerk the plane,
// but a real loss of signal still shuts the motor down quickly.
const uint32_t LINK_FRESH_MS    = 150;   // age threshold for "fresh" link
const uint32_t FS_THR_CUTOFF_MS = 1000;  // >=1s: kill motor
const uint32_t FS_THR_HYST_MS   = 200;   // extra tolerance for brief packet dropout
const uint32_t FS_THR_DISARM_MS = FS_THR_CUTOFF_MS + FS_THR_HYST_MS;
const uint32_t FS_SAFE_MS       = 3000;  // >=3s: neutralize surfaces

// ------------------------------
// Arming
// ------------------------------
// To arm, the receiver must see a fresh radio packet and low throttle.
// This prevents accidental motor startup when the receiver first powers on.
const uint16_t UNLOCK_THRESH_US = RC_MIN + 60; // throttle must be ≤ this to arm
const uint32_t UNLOCK_HOLD_MS   = 300;         // keep low for this long

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
// This is currently disabled because A4 must have a real voltage divider before
// it can safely measure flight battery voltage. Do not enable this unless the
// hardware is built for it.
const int VBAT_PIN = A4;
const bool ENABLE_VBAT_MONITOR = false; // Set true only when A4 has a real voltage divider.

// Debug printing is disabled during normal flight so Serial work cannot slow
// down the receiver loop.
const bool ENABLE_RX_DEBUG = false;
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
// The bind code is saved in flash memory so the receiver remembers it after
// power is removed.
#define BIND_MAGIC 0x42494E44UL // 'BIND'
struct __attribute__((packed)) BindStore {
  uint32_t magic;
  uint16_t bindCode;
  uint16_t _pad;
};
FlashStorage(BIND_STORE, BindStore);

// ------------------------------
// Packets
// ------------------------------
// This is the normal flight packet sent by the transmitter.
// "__attribute__((packed))" tells the compiler not to insert extra padding bytes.
// That matters because the transmitter and receiver must agree on the exact
// byte layout of the packet.
struct __attribute__((packed)) ControlPacket {
  uint16_t ch_rud;
  uint16_t ch_ail;
  uint16_t ch_ele;
  uint16_t ch_thr;
  uint16_t flags; // bit15 = ESC mode request, lower 15 bits = bind code
  // Reserved protocol byte. Production firmware deliberately ignores it;
  // keeping it preserves the packet layout shared by current transmitters.
  uint8_t aux_flags;
  uint16_t seq;
};

// This is a special packet used only while binding.
struct __attribute__((packed)) BindPacket {
  uint32_t magic;
  uint16_t code;
  uint16_t _pad;
};

// ------------------------------
// State vars
// ------------------------------
// Stored bind data loaded from flash at startup.
BindStore g_bind = {0, 0, 0};

// bindMode means "learn a transmitter code."
// bindPlugBoot latches when A3 is grounded at startup. During that entire boot,
// A3 remains an input so firmware can never drive against the bind plug.
// bindRestartRequired prevents flight after a bind-plug bind until power is
// removed, the plug is removed, and the rudder servo is reconnected.
// escMode means "intentional ESC calibration mode."
// armed means "normal flight outputs may include throttle."
bool bindMode = false;
bool bindPlugBoot = false;
bool bindRestartRequired = false;
bool escMode = false;
bool armed = false;

// Used to prove the throttle has been low long enough to arm.
uint32_t thrLowSince = 0;

// Time when the last accepted radio packet arrived.
uint32_t lastRxMs = 0;

// "des" means desired value from the newest accepted radio packet.
// "cur" means the value currently being output to the servo pin.
// "filt" is the smoothed value between desired and current.
uint16_t des_r=RC_MID, des_a=RC_MID, des_e=RC_MID, des_t=RC_MIN;
uint16_t cur_r=RC_MID, cur_a=RC_MID, cur_e=RC_MID, cur_t=RC_MIN;
uint16_t filt_r=RC_MID, filt_a=RC_MID, filt_e=RC_MID, filt_t=RC_MIN;

// Counters used for optional debug printing.
uint32_t rxPackets = 0;
uint32_t acceptedPackets = 0;
uint32_t rejectedPackets = 0;
uint32_t lastDebugMs = 0;
uint16_t lastPktBind = 0;
uint16_t lastPktSeq = 0;
int16_t lastRssi = 0;

// Small, guarded USB command buffer used only for automatic firmware updates.
// Normal flight does not print USB diagnostics or block waiting for serial.

// --- ESC calibration safety ---
// ESC calibration is intentionally hard to enter. It must happen right after
// boot, with a special transmitter flag, and with high throttle.
uint32_t bootMs = 0;
const uint32_t BOOT_CALIB_GUARD_MS = 3000; // keep throttle low for first 3s (unless explicit ESC mode)
const uint8_t  ESC_FLAG_CONSEC     = 3;    // require this many consecutive ESC-flagged packets
uint8_t escFlagStreak = 0;

// ------------------------------
// Helpers
// ------------------------------
// Load the stored bind code. If flash does not contain our expected "magic"
// value, treat it as unbound.
static inline BindStore loadBind() {
  BindStore v; BIND_STORE.read(v);
  if (v.magic != BIND_MAGIC) { v.magic = 0; v.bindCode = 0; }
  return v;
}

// Save the bind code to flash memory.
static inline void saveBind(const BindStore& v_in) {
  BindStore v = v_in; BIND_STORE.write(v);
}

// Check one channel is inside the normal RC pulse range.
static inline bool inRange(uint16_t v) {
  return v >= RC_MIN && v <= RC_MAX;
}

// A packet is only valid if all four channel values look like real servo pulses.
static inline bool validPacket(const ControlPacket& p) {
  return inRange(p.ch_rud) && inRange(p.ch_ail) &&
         inRange(p.ch_ele) && inRange(p.ch_thr);
}

// Safe desired state: motor off and surfaces centered.
static inline void setSafeDesired() {
  des_r = RC_MID; des_a = RC_MID; des_e = RC_MID; des_t = RC_MIN;
}

// Only update the stored output value when the change is large enough to matter.
static inline void setServoIfChanged(uint16_t &cur, uint16_t target) {
  if (abs((int)target - (int)cur) > SERVO_DEADBAND_US) {
    cur = target;
  }
}

// Create one manual servo pulse.
// Interrupts are briefly disabled so the pulse width is accurate.
static inline void writePulse(int pin, uint16_t us) {
  noInterrupts();
  digitalWrite(pin, HIGH);
  delayMicroseconds(us);
  digitalWrite(pin, LOW);
  interrupts();
}

// Write servo/ESC pulses once. In bind-plug mode A3 must remain a high-impedance
// input for the entire boot, including after a bind packet has been stored.
void writeServoFrame() {
  writePulse(PIN_SERVO_THROTTLE, cur_t);
  writePulse(PIN_SERVO_AILERON,  cur_a);
  writePulse(PIN_SERVO_ELEVATOR, cur_e);
  if (!bindPlugBoot) {
    writePulse(PIN_SERVO_RUDDER, cur_r);
  }
}

// A standard bind plug replaces the rudder servo and connects A3 signal to
// ground. Multiple startup samples avoid treating a brief transient as a plug.
bool detectRudderBindPlug() {
  pinMode(PIN_SERVO_RUDDER, INPUT_PULLUP);
  uint8_t lowSamples = 0;
  const uint8_t sampleCount = 8;
  for (uint8_t i = 0; i < sampleCount; ++i) {
    if (digitalRead(PIN_SERVO_RUDDER) == LOW) lowSamples++;
    delay(2);
  }
  return lowSamples == sampleCount;
}

// Return to the locked state and force throttle low.
void disarmAndLock() {
  armed = false;
  thrLowSince = 0;
  des_t = RC_MIN;
}

// The desktop configurator uses this exact command to request the installed
// SAM-BA bootloader. Keeping the USB connection open lets the SAMD core finish
// its normal reset sequence; all unrelated serial input is ignored.
void serviceUsbBootloaderRequest() {
  static char command[16] = {0};
  static uint8_t length = 0;
  while (Serial.available()) {
    char c = (char)Serial.read();
    if (c == '\r') continue;
    if (c == '\n') {
      command[length] = '\0';
      if (strcmp(command, "BOOTLOADER") == 0) {
        setSafeDesired();
        disarmAndLock();
        cur_t = RC_MIN;
        Serial.println("OK BOOTLOADER");
        Serial.flush();
        initiateReset(1);
        delay(1); // advances the SAMD core reset state machine once
        while (true) {}
      }
      length = 0;
    } else if (length < sizeof(command) - 1) {
      command[length++] = c;
    } else {
      length = 0;
    }
  }
}

// Hardware reset of the LoRa module.
void hardResetRadio() {
  pinMode(RFM95_RST, OUTPUT);
  digitalWrite(RFM95_RST, HIGH); delay(1);
  digitalWrite(RFM95_RST, LOW); delay(10);
  digitalWrite(RFM95_RST, HIGH); delay(10);
}

// Read the flight battery voltage through a resistor divider.
// This function is not used unless ENABLE_VBAT_MONITOR is true.
uint16_t readVBATmV() {
  uint32_t acc = 0;
  for (int i=0; i<VBAT_SAMPLES; ++i) acc += analogRead(VBAT_PIN);
  float vadc = (acc / (float)VBAT_SAMPLES) * (3.3f / 1023.0f);
  float vbat = vadc * ((VBAT_RTOP_KOHM + VBAT_RBOT_KOHM) / VBAT_RBOT_KOHM);
  return (uint16_t)(vbat * 1000.0f);
}

// Roughly guess the battery cell count from total pack voltage.
uint8_t inferCells(uint16_t mv) {
  if (mv >= 21500) return 6;
  if (mv >= 17500) return 5;
  if (mv >= 13500) return 4;
  if (mv >= 9500)  return 3;
  return 0;
}

// Non-blocking LED pattern generator.
// It does not use delay(), so the receiver can keep flying while blinking.
void updateLed() {
  static bool on=false;
  uint32_t now=millis();
  if (ledState==LED_ARMED) { if(!on){digitalWrite(LED_BUILTIN,HIGH);on=true;} return; }
  uint32_t period=(ledState==LED_BIND)?1200:(ledState==LED_LOCKED?1000:200);
  uint32_t ontime=(ledState==LED_BIND)?600:(ledState==LED_LOCKED?200:100);
  bool shouldOn=((now%period)<ontime);
  if(shouldOn!=on){digitalWrite(LED_BUILTIN,shouldOn?HIGH:LOW);on=shouldOn;}
}

// ------------------------------
// Setup
// ------------------------------
void setup() {
  // USB command input remains non-blocking and silent during flight.
  Serial.begin(115200);

  // Serial debug is normally off for flying. If enabled, this opens USB serial.
  if (ENABLE_RX_DEBUG) {
    delay(50);
  }

  pinMode(LED_BUILTIN, OUTPUT);
  pinMode(PIN_BIND_BTN, INPUT_PULLUP);

  // The bind button uses INPUT_PULLUP, so the pin normally reads HIGH.
  // Pressing the button connects it to ground, making it read LOW.
  const bool bindButtonHeld = (digitalRead(PIN_BIND_BTN) == LOW);

  // Detect the optional rudder-port bind plug before any servo output is
  // configured. This result remains latched until the receiver restarts.
  bindPlugBoot = detectRudderBindPlug();
  bindMode = bindButtonHeld || bindPlugBoot;

  // Load the bind code saved from an earlier bind operation.
  g_bind = loadBind();

  // Configure servo outputs and force known-low throttle immediately.
  pinMode(PIN_SERVO_THROTTLE, OUTPUT);
  pinMode(PIN_SERVO_AILERON, OUTPUT);
  pinMode(PIN_SERVO_ELEVATOR, OUTPUT);
  if (!bindPlugBoot) pinMode(PIN_SERVO_RUDDER, OUTPUT);
  digitalWrite(PIN_SERVO_THROTTLE, LOW);
  digitalWrite(PIN_SERVO_AILERON, LOW);
  digitalWrite(PIN_SERVO_ELEVATOR, LOW);
  if (!bindPlugBoot) digitalWrite(PIN_SERVO_RUDDER, LOW);

  // Ensure the ESC sees RC_MIN from the very first pulse.
  cur_t  = RC_MIN;
  des_t  = RC_MIN;
  filt_t = RC_MIN;

  // Initialize the other channels to center so surfaces do not jump to a random
  // position on boot.
  cur_a = filt_a = des_a = RC_MID;
  cur_e = filt_e = des_e = RC_MID;
  cur_r = filt_r = des_r = RC_MID;
  writeServoFrame();

  // Start from a safe state before the radio is even initialized.
  setSafeDesired();
  disarmAndLock();

  // Reset and initialize the LoRa radio.
  hardResetRadio();
  if (!rf95.init()) {
    // Radio hardware may be unavailable when the receiver is powered only for
    // a desktop firmware update. Keep the safe error blink, but continue to
    // accept the exact configurator bootloader command over USB.
    while (1) {
      serviceUsbBootloaderRequest();
      digitalWrite(LED_BUILTIN, !digitalRead(LED_BUILTIN));
      delay(100);
    }
  }

  // The receiver and transmitter must use the same radio settings.
  rf95.setModemConfig(MODEM);
  rf95.setFrequency(RF95_FREQ);

  // Optional battery voltage setup.
  if (ENABLE_VBAT_MONITOR) {
    pinMode(VBAT_PIN, INPUT);
    vbat_mV = readVBATmV();
    vbat_cells = inferCells(vbat_mV);
  }

  bootMs  = millis();
  lastRxMs = bootMs;

  // Pick the first LED state.
  ledState = bindMode ? LED_BIND : LED_LOCKED;

  if (ENABLE_RX_DEBUG) {
    Serial.println("RX Ready");
    Serial.print("Stored bind code: ");
    Serial.println((g_bind.magic == BIND_MAGIC) ? g_bind.bindCode : 0);
    if (bindMode) Serial.println("Bind Mode Active");
    if (bindPlugBoot) Serial.println("Rudder bind plug detected; restart required after bind");
  }
}

// ------------------------------
// Loop
// ------------------------------
void loop() {
  uint32_t now = millis();

  serviceUsbBootloaderRequest();

  // Battery check.
  // This only runs if ENABLE_VBAT_MONITOR is true.
  if (ENABLE_VBAT_MONITOR && now - lastVbatMs >= VBAT_PERIOD_MS) {
    lastVbatMs = now;
    vbat_mV = readVBATmV();
    uint8_t cells = inferCells(vbat_mV);
    if (cells) vbat_cells = cells;
    if (vbat_cells >= 3 && vbat_mV < vbat_cells * LAND_PER_CELL_MV) {
      disarmAndLock();
    }
  }

  // Radio RX.
  // rf95.available() becomes true when the LoRa module has a packet waiting.
  if (rf95.available()) {
    uint8_t buf[sizeof(ControlPacket)];
    uint8_t len = sizeof(buf);
    if (rf95.recv(buf, &len)) {
      // Bind packet handling.
      // This only works in bind mode so a random packet during flight cannot
      // overwrite the stored bind code.
      if (bindMode && len == sizeof(BindPacket)) {
        BindPacket bp; memcpy(&bp, buf, sizeof(bp));
        if (bp.magic == BIND_MAGIC && bp.code) {
          g_bind.magic = BIND_MAGIC;
          g_bind.bindCode = bp.code;
          saveBind(g_bind);
          digitalWrite(LED_BUILTIN, HIGH); delay(800); digitalWrite(LED_BUILTIN, LOW);
          bindMode = false;
          bindRestartRequired = bindPlugBoot;
          ledState = LED_LOCKED;
          if (ENABLE_RX_DEBUG) {
            Serial.print("Stored Bind Code: ");
            Serial.println(bp.code);
          }
        }
      }
      // Normal control packet.
      else if (len == sizeof(ControlPacket)) {
        ControlPacket pkt; memcpy(&pkt, buf, sizeof(pkt));
        if (validPacket(pkt)) {
          rxPackets++;

          // The top bit of flags asks for ESC calibration mode.
          // The lower 15 bits carry the bind code.
          bool pktEsc      = (pkt.flags & 0x8000);
          uint16_t pktBind = (pkt.flags & 0x7FFF);
          lastPktBind = pktBind;
          lastPktSeq = pkt.seq;
          lastRssi = rf95.lastRssi();

          // Track consecutive ESC-flagged packets.
          // Requiring several in a row makes ESC mode harder to enter by
          // accident.
          if (pktEsc) {
            if (escFlagStreak < 255) escFlagStreak++;
          } else {
            escFlagStreak = 0;
          }

          // Accept controls only after an explicit bind and only when the
          // packet carries the stored code. An erased/new receiver must remain
          // in failsafe instead of accepting the first transmitter it hears.
          const bool hasBind =
            (g_bind.magic == BIND_MAGIC && g_bind.bindCode != 0);
          const bool accept = !bindMode && !bindRestartRequired &&
                              hasBind && (pktBind == g_bind.bindCode);
          if (accept) {
            acceptedPackets++;

            // Copy the newest transmitter commands into the desired outputs.
            // The servo tick below will decide whether it is safe to actually
            // output them.
            des_r = pkt.ch_rud;
            des_a = pkt.ch_ail;
            des_e = pkt.ch_ele;
            des_t = pkt.ch_thr;
            lastRxMs = now;
          } else {
            rejectedPackets++;
          }

          // Stricter ESC mode:
          // require explicit handshake, multiple packets, high throttle, and
          // only during the first few seconds after boot.
          if (!escMode &&
              escFlagStreak >= ESC_FLAG_CONSEC &&
              (now - bootMs) < 5000 &&
              des_t >= (RC_MAX - 20)) {
            escMode = true;
            armed   = true;          // allow throttle immediately in ESC mode
            ledState = LED_ARMED;
            if (ENABLE_RX_DEBUG) {
              Serial.println("ESC MODE ACTIVE (handshake confirmed)");
            }
          }
        }
      }
    }
  }

  // 50 Hz servo tick.
  // Radio packets may arrive faster than this, but servos expect pulses at
  // about 50 Hz, so all output decisions are made here.
  static uint32_t lastTick=0;
  if (now - lastTick >= SERVO_PERIOD_MS) {
    lastTick = now;

    // age is how long it has been since the last accepted packet.
    // Larger age means the radio link is getting stale.
    uint32_t age = now - lastRxMs;

    // Boot guard:
    // keep throttle at RC_MIN for the first seconds unless the user intentionally
    // entered ESC calibration mode.
    bool inBootGuard = (now - bootMs) < BOOT_CALIB_GUARD_MS;
    if (inBootGuard && !escMode) {
      des_t = RC_MIN;
    }

    // ---------- Arming + staged failsafe ----------
    if (bindRestartRequired) {
      // A bind plug was present at boot. Keep every output safe and require a
      // full restart before normal packets can arm the receiver. A3 remains an
      // input, so the grounded plug is never driven by the MCU.
      setSafeDesired();
      disarmAndLock();
      ledState = LED_LOCKED;

    } else if (!bindMode && !escMode) {
      if (!armed) {
        // Require fresh link + low throttle for UNLOCK_HOLD_MS to arm.
        if (age <= LINK_FRESH_MS && des_t <= UNLOCK_THRESH_US) {
          if (thrLowSince == 0) thrLowSince = now;
          if (now - thrLowSince >= UNLOCK_HOLD_MS) {
            armed = true;
          }
        } else {
          thrLowSince = 0;
        }

        // Disarmed: throttle is always forced low.
        des_t = RC_MIN;

        // Failsafe while disarmed.
        // If the link is gone for a while, eventually center the surfaces too.
        if (age > FS_THR_CUTOFF_MS) {
          if (age > FS_SAFE_MS) {
            des_r = RC_MID; des_a = RC_MID; des_e = RC_MID;
          }
          ledState = LED_LOST;
        } else {
          ledState = LED_LOCKED;
        }

      } else {
        // Armed flight.
        if (age <= FS_THR_CUTOFF_MS) {
          // Link is healthy enough for normal flight.
          ledState = LED_ARMED;
        } else if (age <= FS_THR_DISARM_MS) {
          // Short packet dropout: retain current outputs briefly and show lost-link state.
          // This avoids one-second motor/servo jiggers when the link is marginal.
          ledState = LED_LOST;
        } else {
          // --- FAILSAFE WHILE ARMED ---
          // The link has been gone too long. Disarm and kill throttle.
          armed = false;                 // prevents re-outputs until proper re-arm
          des_t = RC_MIN;

          // Immediate hard kill on the next manual output frame.
          cur_t = RC_MIN;

          if (age > FS_SAFE_MS) {
            des_r = RC_MID; des_a = RC_MID; des_e = RC_MID;
          }
          ledState = LED_LOST;
        }
      }

    } else if (bindMode) {
      // While binding, never let the motor run.
      setSafeDesired();
      ledState = LED_BIND;

    } else if (escMode) {
      // ESC bypass mode.
      // This allows intentional ESC calibration, but still honors failsafe
      // timing so the motor is not left running after link loss.
      if (age > FS_THR_CUTOFF_MS) {
        // Drop out of ESC mode and kill motor.
        escMode = false;
        armed   = false;
        des_t   = RC_MIN;

        // Immediate hard kill on the next manual output frame.
        cur_t = RC_MIN;

        if (age > FS_SAFE_MS) {
          des_r = RC_MID; des_a = RC_MID; des_e = RC_MID;
        }
        ledState = LED_LOST;
      } else {
        ledState = LED_ARMED;
      }
    }

    // ---------- Smoothing ----------
    // lerp means "linear interpolation."
    // With RX_SMOOTH_ALPHA set to 1.0, the filtered value jumps straight to
    // the target. If alpha were lower, it would move partway each frame.
    auto lerp = [](uint16_t cur, uint16_t tgt, float a){
      return (uint16_t)((1.0f-a)*cur + a*tgt + 0.5f);
    };
    filt_r = lerp(filt_r, des_r, RX_SMOOTH_ALPHA);
    filt_a = lerp(filt_a, des_a, RX_SMOOTH_ALPHA);
    filt_e = lerp(filt_e, des_e, RX_SMOOTH_ALPHA);
    filt_t = lerp(filt_t, des_t, RX_SMOOTH_ALPHA);

    // ---------- Outputs ----------
    // Only an armed receiver, or intentional ESC calibration mode, may output
    // throttle above RC_MIN.
    if (armed || escMode) {
      setServoIfChanged(cur_t, filt_t);
      setServoIfChanged(cur_a, filt_a);
      setServoIfChanged(cur_e, filt_e);
      setServoIfChanged(cur_r, filt_r);
    } else {
      // Disarmed:
      // throttle hard low, surfaces follow staged desired values. After a long
      // failsafe, those desired values become centered.
      setServoIfChanged(cur_t, RC_MIN);
      setServoIfChanged(cur_a, filt_a);
      setServoIfChanged(cur_e, filt_e);
      setServoIfChanged(cur_r, filt_r);
    }

    // Send the actual pulses and update the status LED once per servo frame.
    writeServoFrame();
    updateLed();
  }

  // Optional once-per-second debug print. Disabled during normal flying.
  if (ENABLE_RX_DEBUG && now - lastDebugMs >= 1000) {
    lastDebugMs = now;
    Serial.print("RX rx=");
    Serial.print(rxPackets);
    Serial.print(" ok=");
    Serial.print(acceptedPackets);
    Serial.print(" rej=");
    Serial.print(rejectedPackets);
    Serial.print(" stored=");
    Serial.print((g_bind.magic == BIND_MAGIC) ? g_bind.bindCode : 0);
    Serial.print(" pktBind=");
    Serial.print(lastPktBind);
    Serial.print(" seq=");
    Serial.print(lastPktSeq);
    Serial.print(" rssi=");
    Serial.print(lastRssi);
    Serial.print(" age=");
    Serial.print(now - lastRxMs);
    Serial.print(" armed=");
    Serial.print(armed ? "yes" : "no");
    Serial.print(" bindMode=");
    Serial.print(bindMode ? "yes" : "no");
    Serial.print(" bindPlug=");
    Serial.print(bindPlugBoot ? "yes" : "no");
    Serial.print(" restartRequired=");
    Serial.print(bindRestartRequired ? "yes" : "no");
    Serial.print(" des=");
    Serial.print(des_r); Serial.print(",");
    Serial.print(des_a); Serial.print(",");
    Serial.print(des_e); Serial.print(",");
    Serial.println(des_t);
  }
}
