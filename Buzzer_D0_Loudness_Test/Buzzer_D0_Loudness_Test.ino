/*
  Buzzer maximum-volume test on D0.

  First plays a stepped frequency sweep centered around the range that sounded
  loudest on the first test, then plays a few alert patterns near that range.
  Listen for the frequency/pattern that is loudest on the actual buzzer.
*/

const uint8_t BUZZER_PIN = 0;  // D0

void beep(uint16_t freqHz, uint16_t durationMs, uint16_t gapMs) {
  Serial.print("Tone ");
  Serial.print(freqHz);
  Serial.print(" Hz for ");
  Serial.print(durationMs);
  Serial.println(" ms");

  tone(BUZZER_PIN, freqHz);
  delay(durationMs);
  noTone(BUZZER_PIN);
  delay(gapMs);
}

void setup() {
  pinMode(BUZZER_PIN, OUTPUT);
  noTone(BUZZER_PIN);

  Serial.begin(115200);
  unsigned long startMs = millis();
  while (!Serial && millis() - startMs < 1500) {
    delay(10);
  }

  Serial.println("Buzzer loudness test on D0");
  Serial.println("Pattern repeats until power/reset.");
}

void loop() {
  Serial.println("Resonance sweep, 2700-4500 Hz");
  for (uint16_t freq = 2700; freq <= 4500; freq += 150) {
    beep(freq, 650, 250);
  }

  delay(1200);

  Serial.println("Long candidates");
  beep(3000, 1200, 500);
  beep(3150, 1200, 500);
  beep(3300, 1200, 500);
  beep(3450, 1200, 500);
  beep(3600, 1200, 900);

  Serial.println("Fast high-duty alert patterns");
  for (uint8_t i = 0; i < 10; ++i) {
    beep(3150, 90, 35);
  }
  delay(600);
  for (uint8_t i = 0; i < 10; ++i) {
    beep(3300, 90, 35);
  }
  delay(600);
  for (uint8_t i = 0; i < 10; ++i) {
    beep(3450, 90, 35);
  }

  delay(2000);
}
