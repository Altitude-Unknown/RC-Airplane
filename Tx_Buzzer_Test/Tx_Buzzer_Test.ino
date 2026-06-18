/*
  RC transmitter buzzer pattern test.

  Buzzer: D11
  Pattern A: 5-minute warning candidate
  Pattern B: every-minute reminder candidate
*/

const uint8_t BUZZER_PIN = 11;

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

void playPattern(const char *name, const BeepStep *pattern, uint8_t count) {
  Serial.println(name);
  for (uint8_t i = 0; i < count; ++i) {
    tone(BUZZER_PIN, pattern[i].freqHz);
    delay(pattern[i].durationMs);
    noTone(BUZZER_PIN);
    delay(pattern[i].gapMs);
  }
}

void setup() {
  pinMode(BUZZER_PIN, OUTPUT);
  noTone(BUZZER_PIN);

  Serial.begin(115200);
  unsigned long startMs = millis();
  while (!Serial && millis() - startMs < 1500) {
    delay(10);
  }

  Serial.println("TX buzzer test on D11");
}

void loop() {
  playPattern("5-minute warning pattern", FIVE_MIN_PATTERN, sizeof(FIVE_MIN_PATTERN) / sizeof(FIVE_MIN_PATTERN[0]));
  delay(2000);
  playPattern("1-minute reminder pattern", ONE_MIN_PATTERN, sizeof(ONE_MIN_PATTERN) / sizeof(ONE_MIN_PATTERN[0]));
  delay(4000);
}
