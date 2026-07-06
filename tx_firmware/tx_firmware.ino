/*
  ---------------------------------------------------------------------------
  Feather M0 (SAMD21) RC Transmitter
  LoRa + Physical Trims + Bind (D9) + Throttle Safety + ESC Calibration Override (D5)
  + FRAM-backed Models (rates/expo/subtrim/endpoints/bind)
  + USB Config Mode (hold D9 + D5 on boot) for GUI READ/WRITE/INFO/RANGE
  ---------------------------------------------------------------------------

  HOW TO USE
  ----------
  • Normal: Power up with throttle low → LED solid → sending.
  • Safety Lock: Power up throttle high → LED fast blink → sends nothing.
  • ESC Calibration: Power up throttle high + hold D5/aileron-right trim → LED 3x flash → solid → sends throttle immediately.
  • Bind Mode: Hold D9 LOW on boot → LED slow blink → sends BindPacket repeatedly.
  • Config Mode (GUI): Hold BOTH D9 + D5 LOW on boot → LED slow blink, USB answers PING/READ/WRITE.
  • Setup Mode: Hold BOTH rudder trims on boot → OLED setup menu, no LoRa transmit.

  BIG PICTURE FOR BEGINNERS
  -------------------------
  This sketch runs the handheld radio transmitter.

  Every pass through loop() in normal mode does the same basic job:

    1. Read the four stick/gimbal analog voltages.
    2. Convert each reading into a servo-style pulse width, normally 1000-2000us.
    3. Apply the active model's rates, expo, reverse, endpoints, and trims.
    4. Put those four channel values into a small ControlPacket struct.
    5. Send that packet to the airplane receiver with the RFM95 LoRa radio.

  The control loop is intentionally simple and fast. Features that could slow
  down control response, such as OLED drawing or USB configuration, are kept in
  separate boot modes. The buzzer timer below is written as a non-blocking state
  machine so it can beep without pausing radio packets.
*/

#include <SPI.h>
#include <RH_RF95.h>
#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include "tx_config.h"

#if __has_include(<FlashStorage_SAMD.h>)
  #include <FlashStorage_SAMD.h>
  #define HAVE_FLASH 1
#else
  #define HAVE_FLASH 0
#endif

// ---------------- LED Modes ----------------
// The transmitter has one built-in LED. Instead of scattering raw blink timings
// through the code, we use these names and let driveBlink() do the actual work.
enum LedMode : uint8_t { LED_SOLID, LED_FAST, LED_SLOW };

// ---------------- LoRa Pins ----------------
// These are the wires between the Feather M0 and the RFM95 radio module.
//
// CS  = chip select. The microcontroller pulls this low when talking to RFM95.
// INT = interrupt from the radio. The RadioHead library uses it internally.
// RST = reset line. We pulse this at boot to put the radio in a known state.
#define RFM95_CS   8
#define RFM95_INT  3
#define RFM95_RST  4
#define RF95_FREQ  915.0
RH_RF95 rf95(RFM95_CS, RFM95_INT);

// ---------------- Buttons -----------------
#ifndef LED_BUILTIN
  #define LED_BUILTIN 13
#endif
// These buttons are only checked during boot. Holding different combinations
// chooses a different operating mode before normal control packets start.
#define PIN_BIND_BTN 9   // Bind Mode (hold at boot)
#define PIN_ESC_BTN  5   // ESC Calibration Override (shared with aileron-right trim at boot)

// ---------------- Gimbals -----------------
// The gimbals are potentiometers. analogRead() converts each voltage into a
// number from roughly 0 to 1023. adcToNorm() later turns that into -1.0..+1.0.
const uint8_t PIN_THR = A3;
const uint8_t PIN_AIL = A1;
const uint8_t PIN_ELE = A2;
const uint8_t PIN_RUD = A0;

// ---------------- Physical Trims -----------------
// Each trim button nudges the matching surface slightly. These are regular
// digital inputs using INPUT_PULLUP, so "pressed" reads LOW, not HIGH.
const uint8_t PIN_TRIM_RUD_L = A4;
const uint8_t PIN_TRIM_RUD_R = 12;
const uint8_t PIN_TRIM_AIL_L = 1;
const uint8_t PIN_TRIM_AIL_R = 5;
const uint8_t PIN_TRIM_ELE_D = 2;
const uint8_t PIN_TRIM_ELE_U = 0;
const int16_t TRIM_STEP_US = 5;
const int16_t TRIM_MIN_US = -500;
const int16_t TRIM_MAX_US = 500;
const uint16_t TRIM_FIRST_REPEAT_MS = 450;
const uint16_t TRIM_REPEAT_MS = 140;

// ---------------- Flight Timer / Buzzer -----------------
// The buzzer is used as a simple "land soon" reminder. We count only actual
// throttle-on time, not wall-clock time. This avoids penalizing long glides.
const uint8_t PIN_BUZZER = 11;
const uint16_t THROTTLE_TIMER_ON_US = 1080;
const uint32_t FIRST_THROTTLE_ALARM_MS = 5UL * 60UL * 1000UL;
const uint32_t REPEAT_THROTTLE_ALARM_MS = 60UL * 1000UL;

// A beep pattern is a small script. Each row says:
//   frequency to play, how long to play it, and how long to wait afterward.
// updateBuzzer() walks through these rows without using delay().
struct BeepStep {
  uint16_t freqHz;
  uint16_t durationMs;
  uint16_t gapMs;
};

const BeepStep FIVE_MIN_PATTERN[] = {
  {2000, 360, 180},
  {2800, 360, 180},
  {2000, 360, 180},
  {2800, 900, 280},
  {2000, 360, 180},
  {2800, 360, 180},
  {2000, 360, 180},
  {2800, 1300, 0},
};

const BeepStep ONE_MIN_PATTERN[] = {
  {2600, 360, 240},
  {2600, 360, 360},
  {2600, 360, 240},
  {2600, 360, 0},
};

// ---------------- OLED Setup Menu -----------------
// OLED setup mode is deliberately separate from flight mode. In setup mode the
// transmitter does not start LoRa and does not send packets, so menu work cannot
// move the airplane controls by accident.
const uint8_t OLED_ADDR = 0x3D;
const uint8_t OLED_W = 128;
const uint8_t OLED_H = 64;
Adafruit_SSD1306 display(OLED_W, OLED_H, &Wire, -1);

// ---------------- RC Range ----------------
// RC servos and ESCs are normally commanded with pulse widths around:
//   1000us = one end / throttle low
//   1500us = center
//   2000us = other end / throttle high
const uint16_t RC_MIN = 1000, RC_MID = 1500, RC_MAX = 2000;

// ---------------- ADC Calibration (expo now from model) ----
// Calibration tells the code what analogRead() value means minimum, center,
// and maximum for each stick. invert flips a channel if the physical pot moves
// opposite the desired direction.
struct Cal {
  int minV, midV, maxV; bool invert;
  constexpr Cal(int a=0,int b=512,int c=1023,bool inv=false)
    : minV(a), midV(b), maxV(c), invert(inv) {}
};
Cal calThr{0,512,1023,true };
Cal calAil{0,512,1023,false};
Cal calEle{0,512,1023,false};
Cal calRud{0,512,1023,false};

// ---------------- Packets -----------------
// These structs describe the bytes that go over the air.
//
// __attribute__((packed)) is important: it tells the compiler not to insert
// padding bytes between fields. The receiver expects this exact byte layout.
struct __attribute__((packed)) ControlPacket {
  uint16_t ch_rud, ch_ail, ch_ele, ch_thr;
  uint16_t flags;  // bindCode + optional high bit for ESC mode
  uint16_t seq;
};
struct __attribute__((packed)) BindPacket {
  uint32_t magic; uint16_t code; uint16_t _pad;
};
#define BIND_MAGIC 0x42494E44UL  // 'BIND'

// ---------------- Bind Store (legacy fallback) --------------
// Newer model data lives in FRAM through tx_config.h/cpp. This legacy flash
// bind store is kept as a fallback so older/unconfigured transmitters can still
// generate and remember a bind code.
struct __attribute__((packed)) BindStore {
  uint32_t magic; uint16_t bindCode; uint16_t _pad;
};
#if HAVE_FLASH
  FlashStorage(BIND_STORE, BindStore);
#endif
BindStore g_bind = {0, 0, 0};
static inline void saveBind(const BindStore &v_in) {
#if HAVE_FLASH
  BindStore v = v_in; BIND_STORE.write(v);
#endif
}
static inline void loadBind() {
#if HAVE_FLASH
  BindStore v; BIND_STORE.read(v);
  if (v.magic == BIND_MAGIC && v.bindCode != 0) { g_bind = v; return; }
#endif
  g_bind.magic = 0; g_bind.bindCode = 0;
}
static inline uint16_t generateBindCode() {
  randomSeed(analogRead(PIN_THR) ^ analogRead(PIN_AIL) ^ micros());
  uint16_t c = (uint16_t)random(1, 65535);
  return c ? c : 1;
}
static inline void ensureBindCode() {
  if (g_bind.magic != BIND_MAGIC || g_bind.bindCode == 0) {
    g_bind.magic = BIND_MAGIC; g_bind.bindCode = generateBindCode();
    saveBind(g_bind);
  }
}

// ---------------- Helpers -----------------
// Exponential moving average. This smooths sudden changes a little:
//   alpha close to 1.0 = faster response
//   alpha closer to 0.0 = smoother/slower response
static inline uint16_t emaU16(uint16_t prev, uint16_t now, float alpha) {
  float y = (1.0f - alpha)*float(prev) + alpha*float(now);
  return (uint16_t)(y + 0.5f);
}
void driveBlink(LedMode m){
  // This function is non-blocking: it checks millis() and changes the LED only
  // when needed. That keeps the main control loop moving quickly.
  static bool on=false; uint32_t now=millis();
  if(m==LED_SOLID){ if(!on){digitalWrite(LED_BUILTIN,HIGH);on=true;} return; }
  uint32_t period=(m==LED_SLOW)?1200:200;
  bool shouldOn=((now%period)<(period/2));
  if(shouldOn!=on){digitalWrite(LED_BUILTIN,shouldOn?HIGH:LOW);on=shouldOn;}
}
void ledTripleFlash(){
  // Used only during boot to acknowledge intentional ESC calibration override.
  // It uses delay(), but that is acceptable here because we are not flying yet.
  for(int i=0;i<3;i++){
    digitalWrite(LED_BUILTIN,HIGH); delay(100);
    digitalWrite(LED_BUILTIN,LOW);  delay(100);
  }
}
float adcToNorm(int raw, const Cal& c, bool throttle=false) {
  // Convert a raw analogRead() number into a normalized stick position.
  //
  // For rudder/aileron/elevator:
  //   center is 0.0, one side is -1.0, the other side is +1.0.
  //
  // For throttle:
  //   the pot has no useful center detent, so we map the whole travel linearly.
  raw = constrain(raw, c.minV, c.maxV);
  if (!throttle) {
    float spanNeg = max(1, c.midV - c.minV);
    float spanPos = max(1, c.maxV - c.midV);
    float x = (raw >= c.midV) ? float(raw - c.midV)/spanPos : -float(c.midV - raw)/spanNeg;
    if (c.invert) x = -x;
    return constrain(x, -1.0f, 1.0f);
  } else {
    float t = float(raw - c.minV) / max(1, (c.maxV - c.minV)); // [0..1]
    if (c.invert) t = 1.0f - t;
    float x = t*2.0f - 1.0f;
    return constrain(x, -1.0f, 1.0f);
  }
}

// ---------------- USB Config Mode protocol helpers -----------
// In config mode, the Python GUI talks to this firmware using short text
// commands over USB serial. The GUI does not know how to directly talk to FRAM;
// instead it asks this firmware to READ and WRITE raw FRAM bytes.
static String gLine;
static uint8_t hexVal(char c) {
  if (c >= '0' && c <= '9') return c - '0';
  if (c >= 'a' && c <= 'f') return 10 + (c - 'a');
  if (c >= 'A' && c <= 'F') return 10 + (c - 'A');
  return 255;
}
static bool parseUint32(const String &tok, uint32_t &out) {
  char *endptr = nullptr;
  const char *c = tok.c_str();
  if (tok.startsWith("0x") || tok.startsWith("0X")) out = strtoul(c, &endptr, 16);
  else out = strtoul(c, &endptr, 10);
  return endptr && *endptr == '\0';
}
static int parseHexBlob(const String &hex, uint8_t *buf, size_t maxlen) {
  if (hex.length() % 2 != 0) return -1;
  size_t n = hex.length() / 2;
  if (n > maxlen) return -1;
  for (size_t i=0;i<n;i++) {
    uint8_t hi = hexVal(hex[2*i]), lo = hexVal(hex[2*i+1]);
    if (hi==255 || lo==255) return -1;
    buf[i] = (hi<<4) | lo;
  }
  return (int)n;
}
static String bytesToHex(const uint8_t *buf, size_t n) {
  static const char *hex = "0123456789ABCDEF";
  String s; s.reserve(n*2);
  for (size_t i=0;i<n;i++){ s += hex[(buf[i]>>4)&0xF]; s += hex[buf[i]&0xF]; }
  return s;
}
static void processConfigLine(const String &line) {
  // Each command is one line of text ending in '\n'.
  // Examples:
  //   PING
  //   INFO
  //   READ 0 32
  //   WRITE 64 AABBCCDD
  int sp = line.indexOf(' ');
  String cmd = (sp < 0) ? line : line.substring(0, sp);
  cmd.toUpperCase();

  if (cmd == "PING") { Serial.println("PONG"); return; }

  if (cmd == "INFO") {
    Serial.print("{\"mcu\":\"SAMD21G18\",\"fram_size\":");
    Serial.print(TXCF::framSize());
    Serial.println(",\"proto\":\"1.0\",\"role\":\"TX\"}");
    return;
  }
  if (cmd == "RANGE") {
    Serial.print("RANGE "); Serial.println(TXCF::framSize());
    return;
  }
  if (cmd == "READ") {
    int sp2 = line.indexOf(' ', sp+1);
    if (sp2 < 0) { Serial.println("ERR"); return; }
    String tAddr = line.substring(sp+1, sp2); tAddr.trim();
    String tLen  = line.substring(sp2+1);     tLen.trim();
    uint32_t addr, len;
    if (!parseUint32(tAddr, addr) || !parseUint32(tLen, len)) { Serial.println("ERR"); return; }
    if (len == 0 || addr + len > TXCF::framSize()) { Serial.println("ERR"); return; }
    static uint8_t buf[256];
    if (len > sizeof(buf)) { Serial.println("ERR"); return; }
    if (!TXCF::rawRead((uint16_t)addr, buf, (size_t)len)) { Serial.println("ERR"); return; }
    Serial.print("DATA "); Serial.println(bytesToHex(buf, (size_t)len));
    return;
  }
  if (cmd == "WRITE") {
    int sp2 = line.indexOf(' ', sp+1);
    if (sp2 < 0) { Serial.println("ERR"); return; }
    String tAddr = line.substring(sp+1, sp2); tAddr.trim();
    String hex   = line.substring(sp2+1);     hex.trim();
    uint32_t addr;
    if (!parseUint32(tAddr, addr)) { Serial.println("ERR"); return; }
    static uint8_t buf[256];
    int n = parseHexBlob(hex, buf, sizeof(buf));
    if (n < 0 || (addr + (uint32_t)n) > TXCF::framSize()) { Serial.println("ERR"); return; }
    bool ok = TXCF::rawWrite((uint16_t)addr, buf, (size_t)n);
    Serial.println(ok ? "OK" : "ERR");
    return;
  }
  Serial.println("ERR");
}

// ---------------- Globals -----------------
// These variables hold the transmitter's current operating state. They are
// global because setup(), loop(), menu handlers, and helper functions all need
// to see the same state.
ControlPacket pkt; uint16_t seqCounter=0;
bool bindMode=false;
bool escOverride=false;
bool configMode=false;
bool setupMode=false;
bool txLocked=false;
const bool ENABLE_TX_DEBUG = false;
const bool ENABLE_TX_BOOT_LOCK = true;
const bool FORCE_THROTTLE_SAFE_LOW = false;
const float TX_SMOOTH_ALPHA = 0.65f;   // Higher = faster stick response, lower = smoother output.
const uint8_t TX_LOOP_DELAY_MS = 2;    // Small pacing delay after each LoRa packet.
const uint16_t UNLOCK_THRESH_US = RC_MIN + 60;
const uint16_t MENU_REPEAT_MS = 180;
uint32_t lastDebugMs = 0;

// Accumulated throttle-on time. This pauses when throttle is at idle and is not
// saved across power cycles. It is meant as a flight-session reminder.
uint32_t throttleRunMs = 0;
uint32_t lastThrottleTimerMs = 0;
uint32_t nextThrottleAlarmMs = FIRST_THROTTLE_ALARM_MS;

// Buzzer state machine. The active pattern pointer is null when no beep is
// playing. updateBuzzer() advances from tone to gap to next tone using millis().
const BeepStep *activeBeepPattern = nullptr;
uint8_t activeBeepCount = 0;
uint8_t activeBeepIndex = 0;
bool activeBeepToneOn = false;
uint32_t nextBeepTransitionMs = 0;

// FRAM model
// gModel is the active model loaded from FRAM. It contains rates, expo, trims,
// endpoints, reverse flags, bind code, etc. gModelLoaded tells us whether FRAM
// data was valid; if not, the transmitter falls back to simple direct mapping.
txcf_model_v1_t gModel;
bool gModelLoaded = false;

// Small record for each trim button. nextMs lets a held button repeat without
// changing the trim every single loop pass.
struct TrimButton {
  uint8_t pin;
  uint8_t ch;
  int8_t dir;
  bool wasPressed;
  uint32_t nextMs;
};

TrimButton trimButtons[] = {
  {PIN_TRIM_RUD_L, 0, -1, false, 0},
  {PIN_TRIM_RUD_R, 0,  1, false, 0},
  {PIN_TRIM_AIL_L, 1, -1, false, 0},
  {PIN_TRIM_AIL_R, 1,  1, false, 0},
  {PIN_TRIM_ELE_D, 2, -1, false, 0},
  {PIN_TRIM_ELE_U, 2,  1, false, 0},
};
const uint8_t TRIM_BUTTON_COUNT = sizeof(trimButtons) / sizeof(trimButtons[0]);
int16_t runtimeTrimUs[4] = {0, 0, 0, 0};

enum MenuItem : uint8_t { MENU_REVERSE=0, MENU_RATE=1, MENU_EXPO=2, MENU_COUNT=3 };
const char *CHANNEL_NAMES[4] = {"RUD", "AIL", "ELE", "THR"};
const uint8_t MENU_CHANNELS[] = {0, 1, 2}; // Rudder, aileron, elevator only. No throttle setup.
const uint8_t MENU_CHANNEL_COUNT = sizeof(MENU_CHANNELS) / sizeof(MENU_CHANNELS[0]);
const char *MENU_NAMES[MENU_COUNT] = {"REVERSE", "RATE", "EXPO"};
uint8_t menuChannelIndex = 1; // Start on aileron.
uint8_t menuChannel = MENU_CHANNELS[menuChannelIndex];
uint8_t menuItem = MENU_REVERSE;
bool setupDisplayOk = false;
bool setupDirty = true;
bool setupSaveOk = true;

enum MenuButtonIndex : uint8_t {
  MB_RUD_L=0, MB_RUD_R=1, MB_AIL_L=2, MB_AIL_R=3, MB_ELE_D=4, MB_ELE_U=5, MB_COUNT=6
};
const uint8_t menuButtonPins[MB_COUNT] = {
  PIN_TRIM_RUD_L, PIN_TRIM_RUD_R, PIN_TRIM_AIL_L, PIN_TRIM_AIL_R, PIN_TRIM_ELE_D, PIN_TRIM_ELE_U
};
bool menuButtonWasPressed[MB_COUNT] = {false, false, false, false, false, false};
uint32_t menuButtonNextMs[MB_COUNT] = {0, 0, 0, 0, 0, 0};

static inline uint16_t addTrimUs(uint16_t us, int16_t trim) {
  // Add a trim amount in microseconds, then keep the result in servo range.
  return (uint16_t)constrain((long)us + (long)trim, (long)RC_MIN, (long)RC_MAX);
}

void setupTrimPins() {
  // INPUT_PULLUP means the microcontroller provides a weak internal pull-up
  // resistor. The pin reads HIGH when idle and LOW when the button shorts it to
  // ground.
  for (uint8_t i = 0; i < TRIM_BUTTON_COUNT; ++i) {
    pinMode(trimButtons[i].pin, INPUT_PULLUP);
  }
}

void stepTrim(uint8_t ch, int8_t dir) {
  // ch is the channel number: 0 rudder, 1 aileron, 2 elevator.
  // dir is -1 or +1 depending on which trim button was pressed.
  if (ch > 2) return; // No throttle trim.
  int16_t before = gModelLoaded ? gModel.subtrim_us[ch] : runtimeTrimUs[ch];
  int16_t after = constrain((int16_t)(before + dir * TRIM_STEP_US), TRIM_MIN_US, TRIM_MAX_US);
  if (after == before) return;

  if (gModelLoaded) {
    // Preferred path: update the active model in FRAM so the trim survives a
    // power cycle.
    gModel.subtrim_us[ch] = after;
  } else {
    // Fallback path: if no FRAM model is active, keep the trim only in RAM.
    runtimeTrimUs[ch] = after;
  }

  if (gModelLoaded && !TXCF::saveActiveModel(gModel) && ENABLE_TX_DEBUG) {
    Serial.println("TRIM save failed");
  }

  if (ENABLE_TX_DEBUG) {
    Serial.print("trim ch=");
    Serial.print(ch);
    Serial.print(" us=");
    Serial.println(after);
  }
}

void updatePhysicalTrims() {
  // Called from the fast transmit loop. It checks each trim button and performs
  // one trim step on the first press, then repeated steps if the button is held.
  uint32_t now = millis();
  for (uint8_t i = 0; i < TRIM_BUTTON_COUNT; ++i) {
    TrimButton &b = trimButtons[i];
    bool pressed = (digitalRead(b.pin) == LOW);
    if (!pressed) {
      b.wasPressed = false;
      b.nextMs = 0;
      continue;
    }

    if (!b.wasPressed) {
      stepTrim(b.ch, b.dir);
      b.wasPressed = true;
      b.nextMs = now + TRIM_FIRST_REPEAT_MS;
    } else if ((int32_t)(now - b.nextMs) >= 0) {
      stepTrim(b.ch, b.dir);
      b.nextMs = now + TRIM_REPEAT_MS;
    }
  }
}

bool buzzerActive() {
  // A null activeBeepPattern means the buzzer is idle.
  return activeBeepPattern != nullptr;
}

void startBuzzerPattern(const BeepStep *pattern, uint8_t count, uint32_t now) {
  // Do not interrupt an existing alarm pattern. Missing an overlap is better
  // than chopping up a warning in the middle.
  if (buzzerActive() || count == 0) return;
  activeBeepPattern = pattern;
  activeBeepCount = count;
  activeBeepIndex = 0;
  activeBeepToneOn = true;
  tone(PIN_BUZZER, activeBeepPattern[0].freqHz);
  nextBeepTransitionMs = now + activeBeepPattern[0].durationMs;
}

void updateBuzzer(uint32_t now) {
  // Non-blocking buzzer player. The important idea: this function returns
  // immediately unless it is time to start/stop the next tone. That protects
  // control response because radio packets keep flowing while the buzzer plays.
  if (!buzzerActive() || (int32_t)(now - nextBeepTransitionMs) < 0) return;

  const BeepStep &step = activeBeepPattern[activeBeepIndex];
  if (activeBeepToneOn) {
    noTone(PIN_BUZZER);
    activeBeepToneOn = false;
    if (step.gapMs > 0) {
      nextBeepTransitionMs = now + step.gapMs;
      return;
    }
  }

  activeBeepIndex++;
  if (activeBeepIndex >= activeBeepCount) {
    activeBeepPattern = nullptr;
    activeBeepCount = 0;
    activeBeepIndex = 0;
    activeBeepToneOn = false;
    nextBeepTransitionMs = 0;
    return;
  }

  tone(PIN_BUZZER, activeBeepPattern[activeBeepIndex].freqHz);
  activeBeepToneOn = true;
  nextBeepTransitionMs = now + activeBeepPattern[activeBeepIndex].durationMs;
}

void updateThrottleTimer(uint16_t throttleUs, uint32_t now) {
  // Count only time spent above the throttle threshold. This is intentionally
  // based on the final commanded throttle pulse, not the raw analog value.
  if (lastThrottleTimerMs == 0) {
    lastThrottleTimerMs = now;
    return;
  }

  uint32_t elapsed = now - lastThrottleTimerMs;
  lastThrottleTimerMs = now;

  if (throttleUs <= THROTTLE_TIMER_ON_US) return;
  throttleRunMs += elapsed;

  if (throttleRunMs < nextThrottleAlarmMs) return;

  if (nextThrottleAlarmMs == FIRST_THROTTLE_ALARM_MS) {
    startBuzzerPattern(FIVE_MIN_PATTERN, sizeof(FIVE_MIN_PATTERN) / sizeof(FIVE_MIN_PATTERN[0]), now);
  } else {
    startBuzzerPattern(ONE_MIN_PATTERN, sizeof(ONE_MIN_PATTERN) / sizeof(ONE_MIN_PATTERN[0]), now);
  }

  nextThrottleAlarmMs += REPEAT_THROTTLE_ALARM_MS;
}

bool menuButtonEvent(uint8_t button, uint32_t now) {
  // Shared helper for OLED setup mode. It reports "true" once when a button is
  // first pressed and then repeats at MENU_REPEAT_MS while held.
  bool pressed = (digitalRead(menuButtonPins[button]) == LOW);
  if (!pressed) {
    menuButtonWasPressed[button] = false;
    menuButtonNextMs[button] = 0;
    return false;
  }
  if (!menuButtonWasPressed[button]) {
    menuButtonWasPressed[button] = true;
    menuButtonNextMs[button] = now + TRIM_FIRST_REPEAT_MS;
    return true;
  }
  if ((int32_t)(now - menuButtonNextMs[button]) >= 0) {
    menuButtonNextMs[button] = now + MENU_REPEAT_MS;
    return true;
  }
  return false;
}

void resetMenuButtons() {
  uint32_t now = millis() + TRIM_FIRST_REPEAT_MS;
  for (uint8_t i = 0; i < MB_COUNT; ++i) {
    menuButtonWasPressed[i] = (digitalRead(menuButtonPins[i]) == LOW);
    menuButtonNextMs[i] = now;
  }
}

bool channelReversed(uint8_t ch) {
  // Reverse flags are packed into gModel.reserved[0], one bit per channel.
  return (gModel.reserved[0] & (1 << ch)) != 0;
}

void setChannelReversed(uint8_t ch, bool reversed) {
  if (reversed) gModel.reserved[0] |= (1 << ch);
  else gModel.reserved[0] &= ~(1 << ch);
}

int currentMenuValue() {
  // Return the value that should be displayed for the currently selected menu
  // item. Reverse is shown as 0/1 internally, then drawn as NORMAL/REV.
  if (!gModelLoaded) return 0;
  switch (menuItem) {
    case MENU_REVERSE: return channelReversed(menuChannel) ? 1 : 0;
    case MENU_RATE: return gModel.rates_pct[menuChannel];
    case MENU_EXPO: return gModel.expo_pct[menuChannel];
    default: return 0;
  }
}

void adjustMenuValue(int8_t dir) {
  // Aileron trim buttons call this in setup mode. Values are saved immediately
  // so there is no separate "save" command for the pilot to remember.
  if (!gModelLoaded) return;

  if (menuItem == MENU_REVERSE) {
    setChannelReversed(menuChannel, !channelReversed(menuChannel));
  } else if (menuItem == MENU_RATE) {
    int v = constrain((int)gModel.rates_pct[menuChannel] + dir * 5, 0, 100);
    gModel.rates_pct[menuChannel] = (int8_t)v;
  } else if (menuItem == MENU_EXPO) {
    int v = constrain((int)gModel.expo_pct[menuChannel] + dir * 5, -100, 100);
    gModel.expo_pct[menuChannel] = (int8_t)v;
  }

  setupSaveOk = TXCF::saveActiveModel(gModel);
  setupDirty = true;
}

void drawSetupMenu() {
  // Drawing the OLED is relatively slow compared with sending packets. That is
  // why this screen exists only in setup mode, where LoRa transmit is disabled.
  if (!setupDisplayOk) return;
  display.clearDisplay();
  display.setTextColor(SSD1306_WHITE);

  if (!gModelLoaded) {
    display.setTextSize(1);
    display.setCursor(0, 0);
    display.println("SETUP MODE");
    display.println();
    display.println("No active");
    display.println("FRAM model");
    display.println();
    display.println("No transmit");
    display.display();
    return;
  }

  display.setTextSize(1);
  display.setCursor(0, 0);
  display.print("SETUP  ");
  display.print(setupSaveOk ? "SAVED" : "SAVE ERR");
  display.setCursor(0, 12);
  display.print("<");
  display.print(CHANNEL_NAMES[menuChannel]);
  display.print(">  ");
  display.print(MENU_NAMES[menuItem]);

  display.setTextSize(2);
  display.setCursor(0, 30);
  if (menuItem == MENU_REVERSE) {
    display.print(channelReversed(menuChannel) ? "REV" : "NORMAL");
  } else {
    display.print(currentMenuValue());
    display.print("%");
  }

  display.setTextSize(1);
  display.setCursor(0, 56);
  display.print("RUD=CH ELE=MODE AIL=VAL");
  display.display();
}

void updateSetupMenu() {
  // Setup mode is intentionally slow and human-paced. It blinks the LED, reads
  // buttons, redraws only when something changes, and sends no RC packets.
  driveBlink(LED_SLOW);
  uint32_t now = millis();

  if (menuButtonEvent(MB_RUD_L, now)) {
    menuChannelIndex = (menuChannelIndex + MENU_CHANNEL_COUNT - 1) % MENU_CHANNEL_COUNT;
    menuChannel = MENU_CHANNELS[menuChannelIndex];
    setupDirty = true;
  }
  if (menuButtonEvent(MB_RUD_R, now)) {
    menuChannelIndex = (menuChannelIndex + 1) % MENU_CHANNEL_COUNT;
    menuChannel = MENU_CHANNELS[menuChannelIndex];
    setupDirty = true;
  }
  if (menuButtonEvent(MB_ELE_D, now)) {
    menuItem = (menuItem + MENU_COUNT - 1) % MENU_COUNT;
    setupDirty = true;
  }
  if (menuButtonEvent(MB_ELE_U, now)) {
    menuItem = (menuItem + 1) % MENU_COUNT;
    setupDirty = true;
  }
  if (menuButtonEvent(MB_AIL_L, now)) adjustMenuValue(-1);
  if (menuButtonEvent(MB_AIL_R, now)) adjustMenuValue(1);

  if (setupDirty) {
    setupDirty = false;
    drawSetupMenu();
  }
  delay(10);
}

// ---------------- Setup -------------------
void setup() {
  // setup() runs once after reset/power-up. Its job is to choose the boot mode,
  // initialize only the hardware needed for that mode, and leave loop() ready.
  pinMode(LED_BUILTIN,OUTPUT);
  pinMode(PIN_BUZZER, OUTPUT);
  noTone(PIN_BUZZER);
  pinMode(PIN_BIND_BTN,INPUT_PULLUP);
  pinMode(PIN_ESC_BTN, INPUT_PULLUP);
  setupTrimPins();

  bool bindHeld = (digitalRead(PIN_BIND_BTN)==LOW);
  bool escHeld  = (digitalRead(PIN_ESC_BTN)==LOW);
  bool setupHeld = (digitalRead(PIN_TRIM_RUD_L)==LOW && digitalRead(PIN_TRIM_RUD_R)==LOW);

  // Modes
  // These mode checks happen before LoRa is initialized. That lets setup/config
  // modes avoid transmitting anything.
  setupMode  = setupHeld;                // Both rudder trims -> OLED Setup Mode (no LoRa)
  configMode = (!setupMode && bindHeld && escHeld);   // BOTH held -> Config Mode (for GUI)
  bindMode   = (!setupMode && bindHeld && !escHeld);  // Only bind   -> Bind Mode
  escOverride= (!setupMode && !bindHeld && escHeld);  // Only ESC    -> ESC override

  if (configMode || ENABLE_TX_DEBUG) {
    // Serial is normally off in flight mode because debug printing can slow the
    // control loop. It is enabled for the desktop GUI and optional debugging.
    Serial.begin(115200);
    while (!Serial && millis() < (configMode ? 1500 : 1200)) { }
  }

  // Init I2C / FRAM header
  // TXCF handles the external FRAM model storage. begin(true) also makes sure
  // the FRAM header exists so model reads/writes have a known layout.
  TXCF::begin(true);

  if (setupMode) {
    // OLED setup mode is a safe "airplane should not move" mode. We return
    // before LoRa setup, so this mode cannot send stale controls by accident.
    gModelLoaded = TXCF::loadActiveModel(gModel);
    setupDisplayOk = display.begin(SSD1306_SWITCHCAPVCC, OLED_ADDR);
    resetMenuButtons();
    drawSetupMenu();
    return; // No LoRa init and no RC packets in setup mode.
  }

  if (configMode) {
    // USB config protocol (no LoRa)
    Serial.println("READY");
    return; // loop() handles config-mode serial
  }

  // Legacy bind (fallback) — keep your existing mechanism
  // If no FRAM model supplies a bind code, this fallback creates one in flash.
  loadBind(); ensureBindCode();

  // LoRa init
  // Reset the radio module, then let RadioHead configure it. If init fails,
  // blinking forever is safer than pretending the transmitter is working.
  pinMode(RFM95_RST,OUTPUT);
  digitalWrite(RFM95_RST,LOW); delay(10);
  digitalWrite(RFM95_RST,HIGH); delay(10);
  if(!rf95.init()){
    while(1){digitalWrite(LED_BUILTIN,!digitalRead(LED_BUILTIN));delay(100);}
  }
  rf95.setModemConfig(RH_RF95::Bw500Cr45Sf128);
  rf95.setFrequency(RF95_FREQ);
  rf95.setTxPower(17,false);

  // Load model
  // The model can override the fallback bind code. Only the lower 15 bits are
  // used because the top bit of packet flags is reserved for ESC override.
  gModelLoaded = TXCF::loadActiveModel(gModel);
  if (gModelLoaded && (gModel.bind_code & 0x7FFF)) {
    g_bind.magic = BIND_MAGIC;
    g_bind.bindCode = (gModel.bind_code & 0x7FFF);
  }

  // Throttle safety
  // This is a critical safety check. If the transmitter powers up with throttle
  // high, normal mode locks and sends nothing. That prevents an unexpected
  // motor start after a reset or battery plug-in.
  int rawThr = analogRead(PIN_THR);
  float xThr  = adcToNorm(rawThr, calThr, true);
  bool highRates = (gModelLoaded && gModel.active_rates == 1);
  uint16_t thr = gModelLoaded
    ? (uint16_t)TXCF::channelToUs(xThr, 3, gModel, highRates) // ch3 = throttle
    : (uint16_t)constrain((int)(RC_MIN + (xThr+1.0f)*0.5f*(RC_MAX-RC_MIN) + 0.5f), RC_MIN, RC_MAX);

  txLocked = (ENABLE_TX_BOOT_LOCK && !escOverride && (thr > UNLOCK_THRESH_US));
  if (escOverride) ledTripleFlash();

  pkt.ch_rud=RC_MID; pkt.ch_ail=RC_MID; pkt.ch_ele=RC_MID; pkt.ch_thr=RC_MIN;
  pkt.flags=g_bind.bindCode; pkt.seq=0;

  if (ENABLE_TX_DEBUG) {
    Serial.print("TX Ready bind=");
    Serial.print(g_bind.bindCode & 0x7FFF);
    Serial.print(" model=");
    Serial.print(gModelLoaded ? "yes" : "no");
    Serial.print(" boot_thr=");
    Serial.print(thr);
    Serial.print(" locked=");
    Serial.println(txLocked ? "yes" : "no");
  }
}

// ---------------- Loop --------------------
void loop() {
  // loop() runs forever. In normal mode, every pass builds and sends one fresh
  // control packet. Keep this path short and predictable.
  uint32_t loopNow = millis();

  // The buzzer is checked first so alarm tones continue even while the rest of
  // the loop is sending packets. It does not block.
  updateBuzzer(loopNow);

  if (setupMode) {
    updateSetupMenu();
    return;
  }

  // Config Mode (USB proxy for GUI)
  if (configMode) {
    // In config mode the transmitter is just a USB-to-FRAM helper for the GUI.
    // No control packets are sent in this branch.
    driveBlink(LED_SLOW);
    while (Serial.available()) {
      char c = (char)Serial.read();
      if (c == '\r') continue;
      if (c == '\n') {
        String ln = gLine; gLine = ""; ln.trim();
        if (ln.length() > 0) processConfigLine(ln);
      } else {
        if (gLine.length() < 256) gLine += c;
      }
    }
    delay(5);
    return;
  }

  // Bind Mode
  if(bindMode){
    // Bind packets are sent slowly because bind mode is not about fast control;
    // it is just teaching the receiver the transmitter's bind code.
    driveBlink(LED_SLOW);
    BindPacket bp{BIND_MAGIC, (uint16_t)(g_bind.bindCode & 0x7FFF), 0};
    rf95.send((uint8_t*)&bp,sizeof(bp));
    rf95.waitPacketSent();
    if (ENABLE_TX_DEBUG && millis() - lastDebugMs >= 1000) {
      lastDebugMs = millis();
      Serial.print("TX bind packet code=");
      Serial.println(g_bind.bindCode & 0x7FFF);
    }
    delay(100);
    return;
  }

  // Read sticks
  // analogRead() samples the physical gimbals. These raw values are still just
  // ADC counts; adcToNorm() converts them into normalized stick positions.
  int rawThr=analogRead(PIN_THR);
  int rawAil=analogRead(PIN_AIL);
  int rawEle=analogRead(PIN_ELE);
  int rawRud=analogRead(PIN_RUD);

  float xThr = adcToNorm(rawThr, calThr, true);
  float xAil = adcToNorm(rawAil, calAil, false);
  float xEle = adcToNorm(rawEle, calEle, false);
  float xRud = adcToNorm(rawRud, calRud, false);

  // High/Low rates source:
  // For now, high/low rates come from the active model setting in FRAM.
  bool highRates = (gModelLoaded && gModel.active_rates == 1);
  // TODO: If you want a physical switch to toggle DR, read it here
  // and override 'highRates', optionally saving back to FRAM.

  updatePhysicalTrims();

  uint16_t thr, ail, ele, rud;
  if (gModelLoaded) {
    // Normal path: tx_config.cpp applies model settings, including endpoints,
    // rates, expo, subtrim, and reverse.
    // Channel order: 0:RUD,1:AIL,2:ELE,3:THR (matches ControlPacket)
    rud = TXCF::channelToUs(xRud, 0, gModel, highRates);
    ail = TXCF::channelToUs(xAil, 1, gModel, highRates);
    ele = TXCF::channelToUs(xEle, 2, gModel, highRates);
    thr = TXCF::channelToUs(xThr, 3, gModel, highRates);
  } else {
    // Fallback mapping (no FRAM model)
    // This makes the transmitter still basically usable if FRAM/model data is
    // missing. It does not have rates/expo/reverse, only simple scaling.
    auto lerpUs = [&](float x)->uint16_t{
      float t = (x+1.0f)*0.5f;
      return (uint16_t)constrain((int)(RC_MIN + t*(RC_MAX-RC_MIN) + 0.5f), RC_MIN, RC_MAX);
    };
    rud = lerpUs(xRud);
    ail = lerpUs(xAil);
    ele = lerpUs(xEle);
    thr = lerpUs(xThr);
    rud = addTrimUs(rud, runtimeTrimUs[0]);
    ail = addTrimUs(ail, runtimeTrimUs[1]);
    ele = addTrimUs(ele, runtimeTrimUs[2]);
  }

  if (FORCE_THROTTLE_SAFE_LOW) {
    thr = RC_MIN;
  }

  // Smoothing
  // Smooth each outgoing channel a little. The value is stored back into pkt so
  // the next loop can smooth from the previous transmitted command.
  pkt.ch_thr=emaU16(pkt.ch_thr,thr,TX_SMOOTH_ALPHA);
  pkt.ch_ail=emaU16(pkt.ch_ail,ail,TX_SMOOTH_ALPHA);
  pkt.ch_ele=emaU16(pkt.ch_ele,ele,TX_SMOOTH_ALPHA);
  pkt.ch_rud=emaU16(pkt.ch_rud,rud,TX_SMOOTH_ALPHA);

  // Safety
  if(txLocked){
    // In safety lock we intentionally do NOT send packets. The receiver will
    // failsafe/hold safe outputs. The pilot must lower throttle and reset.
    driveBlink(LED_FAST);
    if (ENABLE_TX_DEBUG && millis() - lastDebugMs >= 1000) {
      lastDebugMs = millis();
      Serial.print("TX LOCKED boot safety: lower throttle and reset. bind=");
      Serial.print(g_bind.bindCode & 0x7FFF);
      Serial.print(" raw_thr=");
      Serial.print(rawThr);
      Serial.print(" mapped_thr=");
      Serial.println(thr);
    }
    delay(10);
    return;
  }

  updateThrottleTimer(pkt.ch_thr, loopNow);

  // Send LoRa packet
  // flags contains the bind code plus an optional ESC calibration bit. seq is a
  // rolling counter that helps with debugging and packet-loss checks.
  pkt.flags = (uint16_t)( (g_bind.bindCode & 0x7FFF) | (escOverride ? 0x8000 : 0) ); // bit15 = ESC mode
  pkt.seq = ++seqCounter;
  rf95.send((uint8_t*)&pkt,sizeof(pkt));
  rf95.waitPacketSent();
  if (ENABLE_TX_DEBUG && millis() - lastDebugMs >= 1000) {
    lastDebugMs = millis();
    Serial.print("TX seq=");
    Serial.print(pkt.seq);
    Serial.print(" bind=");
    Serial.print(pkt.flags & 0x7FFF);
    Serial.print(" thr=");
    Serial.print(pkt.ch_thr);
    Serial.print(" ail=");
    Serial.print(pkt.ch_ail);
    Serial.print(" ele=");
    Serial.print(pkt.ch_ele);
    Serial.print(" rud=");
    Serial.print(pkt.ch_rud);
    Serial.print(" raw=");
    Serial.print(rawThr);
    Serial.print(",");
    Serial.print(rawAil);
    Serial.print(",");
    Serial.print(rawEle);
    Serial.print(",");
    Serial.print(rawRud);
    Serial.print(" model=");
    Serial.println(gModelLoaded ? "yes" : "no");
  }

  driveBlink(LED_SOLID);
  delay(TX_LOOP_DELAY_MS);
}
