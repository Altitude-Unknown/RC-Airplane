/*
  Altitude Unknown Transmitter V3 basic board diagnostic.

  This is intentionally a bring-up sketch, not flight firmware.
  - It never transmits a LoRa packet.
  - It never writes FRAM.
  - The buzzer runs only after an explicit `B` command over USB.
  - It reports gimbals and buttons every 250 ms.

  USB commands:
    H  print help
    I  scan the I2C bus
    R  retry the RFM95 initialization check
    B  short buzzer chirp
*/

#include <SPI.h>
#include <Wire.h>
#include <RH_RF95.h>

// Measured assembled V3 harness follows the V2 gimbal order.
static constexpr uint8_t PIN_THR = A3;
static constexpr uint8_t PIN_AIL = A1;
static constexpr uint8_t PIN_ELE = A2;
static constexpr uint8_t PIN_RUD = A0;

static constexpr uint8_t PIN_TRIM_RUD_L = A4;
static constexpr uint8_t PIN_TRIM_RUD_R = 12;
static constexpr uint8_t PIN_TRIM_AIL_L = 1;
static constexpr uint8_t PIN_TRIM_AIL_R = 5;
static constexpr uint8_t PIN_TRIM_ELE_UP = 2;
static constexpr uint8_t PIN_TRIM_ELE_DOWN = 0;
static constexpr uint8_t PIN_BIND = 9;
static constexpr uint8_t PIN_AUX = 10;
static constexpr uint8_t PIN_TRAINER = 7;
static constexpr uint8_t PIN_BUZZER = 11;

static constexpr uint8_t RFM95_CS = 8;
static constexpr uint8_t RFM95_INT = 3;
static constexpr uint8_t RFM95_RST = 4;

RH_RF95 radio(RFM95_CS, RFM95_INT);
bool radioPresent = false;
uint32_t lastReportMs = 0;

static bool pressed(uint8_t pin) {
  return digitalRead(pin) == LOW;
}

static void printHelp() {
  Serial.println(F("TXV3_DIAG commands: H=help I=i2c-scan R=radio-check B=buzzer"));
}

static void scanI2c() {
  uint8_t count = 0;
  Serial.println(F("I2C_SCAN_BEGIN"));
  for (uint8_t address = 1; address < 127; ++address) {
    Wire.beginTransmission(address);
    const uint8_t error = Wire.endTransmission();
    if (error == 0) {
      Serial.print(F("I2C_DEVICE 0x"));
      if (address < 16) Serial.print('0');
      Serial.println(address, HEX);
      ++count;
    }
  }
  Serial.print(F("I2C_SCAN_END count="));
  Serial.println(count);
}

static void checkRadio() {
  digitalWrite(RFM95_RST, LOW);
  delay(10);
  digitalWrite(RFM95_RST, HIGH);
  delay(10);

  radioPresent = radio.init();
  if (radioPresent) {
    radio.sleep();
    Serial.println(F("RFM95 OK sleeping_no_transmit"));
  } else {
    Serial.println(F("RFM95 FAIL"));
  }
}

static void chirpBuzzer() {
  Serial.println(F("BUZZER chirp"));
  tone(PIN_BUZZER, 2200, 150);
}

static void reportInputs() {
  Serial.print(F("INPUTS ms="));
  Serial.print(millis());
  Serial.print(F(" thr="));
  Serial.print(analogRead(PIN_THR));
  Serial.print(F(" ail="));
  Serial.print(analogRead(PIN_AIL));
  Serial.print(F(" ele="));
  Serial.print(analogRead(PIN_ELE));
  Serial.print(F(" rud="));
  Serial.print(analogRead(PIN_RUD));
  Serial.print(F(" eu="));
  Serial.print(pressed(PIN_TRIM_ELE_UP));
  Serial.print(F(" ed="));
  Serial.print(pressed(PIN_TRIM_ELE_DOWN));
  Serial.print(F(" al="));
  Serial.print(pressed(PIN_TRIM_AIL_L));
  Serial.print(F(" ar="));
  Serial.print(pressed(PIN_TRIM_AIL_R));
  Serial.print(F(" rl="));
  Serial.print(pressed(PIN_TRIM_RUD_L));
  Serial.print(F(" rr="));
  Serial.print(pressed(PIN_TRIM_RUD_R));
  Serial.print(F(" bind="));
  Serial.print(pressed(PIN_BIND));
  Serial.print(F(" aux="));
  Serial.print(pressed(PIN_AUX));
  Serial.print(F(" trainer="));
  Serial.print(pressed(PIN_TRAINER));
  Serial.print(F(" rfm95="));
  Serial.println(radioPresent ? F("OK") : F("FAIL"));
}

void setup() {
  pinMode(PIN_TRIM_RUD_L, INPUT_PULLUP);
  pinMode(PIN_TRIM_RUD_R, INPUT_PULLUP);
  pinMode(PIN_TRIM_AIL_L, INPUT_PULLUP);
  pinMode(PIN_TRIM_AIL_R, INPUT_PULLUP);
  pinMode(PIN_TRIM_ELE_UP, INPUT_PULLUP);
  pinMode(PIN_TRIM_ELE_DOWN, INPUT_PULLUP);
  pinMode(PIN_BIND, INPUT_PULLUP);
  pinMode(PIN_AUX, INPUT_PULLUP);
  pinMode(PIN_TRAINER, INPUT_PULLUP);
  pinMode(PIN_BUZZER, OUTPUT);
  digitalWrite(PIN_BUZZER, LOW);

  pinMode(RFM95_CS, OUTPUT);
  digitalWrite(RFM95_CS, HIGH);
  pinMode(RFM95_RST, OUTPUT);
  digitalWrite(RFM95_RST, HIGH);

  Serial.begin(115200);
  const uint32_t waitStart = millis();
  while (!Serial && millis() - waitStart < 3000) {}

  Serial.println(F("TXV3_DIAG v0.1 read_only_startup"));
  printHelp();
  Wire.begin();
  scanI2c();
  checkRadio();
}

void loop() {
  while (Serial.available()) {
    const char command = static_cast<char>(Serial.read());
    switch (command) {
      case 'H': case 'h': printHelp(); break;
      case 'I': case 'i': scanI2c(); break;
      case 'R': case 'r': checkRadio(); break;
      case 'B': case 'b': chirpBuzzer(); break;
      case '\r': case '\n': break;
      default: Serial.println(F("ERR unknown_command")); break;
    }
  }

  const uint32_t now = millis();
  if (now - lastReportMs >= 250) {
    lastReportMs = now;
    reportInputs();
  }
}
