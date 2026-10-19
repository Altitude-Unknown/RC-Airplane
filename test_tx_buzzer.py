"""Run the production non-blocking buzzer/timer and Config Mode test commands."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent


class TransmitterBuzzerTests(unittest.TestCase):
    def test_actual_alarm_schedule_patterns_pause_rollover_and_commands(self):
        source = (ROOT / 'PCB/TxV3/TxV3_Full_M0/flight_core.h').read_text()
        constants = source[source.index('const uint8_t PIN_BUZZER'):source.index('// ---------------- OLED Setup Menu')]
        state = source[source.index('uint32_t throttleRunMs'):source.index('// FRAM model')]
        functions = source[source.index('bool buzzerActive()'):source.index('bool menuButtonEvent(')]
        harness = r'''
#include <stdint.h>
#include <cassert>
#include <string>
#include <sstream>
#include <vector>
uint32_t clockMs = 0;
uint32_t millis() { return clockMs; }
struct String {
  std::string value;
  String(const char* s): value(s) {}
  bool operator==(const char* s) const { return value == s; }
  bool operator!=(const char* s) const { return value != s; }
};
struct Console {
  std::ostringstream buffer;
  template <typename T> void print(T v) { buffer << v; }
  template <typename T> void println(T v) { buffer << v << "\n"; }
} Serial;
struct Tone { uint32_t at; uint16_t hz; };
std::vector<Tone> tones;
int activeHz = 0;
void tone(uint8_t pin, uint16_t hz) { assert(pin == 11); activeHz = hz; tones.push_back({clockMs,hz}); }
void noTone(uint8_t pin) { assert(pin == 11); activeHz = 0; }
''' + constants + state + functions + r'''
void tick(uint32_t now, uint16_t throttle) {
  clockMs = now; updateBuzzer(now); updateThrottleTimer(throttle, now);
}
void reset() {
  processBuzzerCommand("STOP"); tones.clear();
  throttleRunMs = lastThrottleTimerMs = 0;
  nextThrottleAlarmMs = FIRST_THROTTLE_ALARM_MS;
}
int main() {
  assert(FIRST_THROTTLE_ALARM_MS == 300000 && REPEAT_THROTTLE_ALARM_MS == 60000);
  reset(); tick(100, 1000);
  for (uint32_t t = 110; t <= 600100; t += 10) tick(t, 1080);
  assert(throttleRunMs == 0 && tones.empty()); // idle never starts a warning
  reset(); tick(100, 1500);
  for (uint32_t t = 110; t < 300100; t += 10) tick(t, 1500);
  assert(tones.empty());
  tick(300100, 1500);
  assert(throttleRunMs == 300000 && activeBeepPattern == FIVE_MIN_PATTERN);
  assert(tones.size() == 1 && tones[0].hz == 2000);
  assert(nextThrottleAlarmMs == 360000);
  for (uint32_t t = 300110; t <= 306000; t += 10) tick(t, 1500);
  assert(!buzzerActive() && activeHz == 0 && tones.size() == 8);
  for (uint32_t t = 306010; t < 360100; t += 10) tick(t, 1500);
  assert(tones.size() == 8);
  tick(360100, 1500);
  assert(activeBeepPattern == ONE_MIN_PATTERN && nextThrottleAlarmMs == 420000);
  for (uint32_t t = 360110; t <= 420100; t += 10) tick(t, 1500);
  assert(tones.size() == 13 && activeBeepPattern == ONE_MIN_PATTERN);

  reset(); tick(100, 1500);
  for (uint32_t t = 110; t <= 120100; t += 10) tick(t, 1500);
  for (uint32_t t = 120110; t <= 240100; t += 10) tick(t, 1000);
  assert(throttleRunMs == 120000 && tones.empty());
  for (uint32_t t = 240110; t < 420100; t += 10) tick(t, 1500);
  assert(tones.empty()); tick(420100, 1500);
  assert(activeBeepPattern == FIVE_MIN_PATTERN); // 5min running, not wall time

  reset(); tick(UINT32_MAX - 100, 1500); tick(99, 1500);
  assert(throttleRunMs == 200); // millis rollover
  reset(); clockMs = UINT32_MAX - 100;
  processBuzzerCommand("ONE_MIN");
  assert(buzzerActive() && activeHz == 2600);
  clockMs = 258; updateBuzzer(clockMs); assert(activeHz == 2600);
  clockMs = 259; updateBuzzer(clockMs); assert(activeHz == 0);

  reset(); clockMs = 100;
  processBuzzerCommand("FIVE_MIN");
  assert(activeBeepPattern == FIVE_MIN_PATTERN && tones.size() == 1);
  processBuzzerCommand("ONE_MIN");
  assert(activeBeepPattern == FIVE_MIN_PATTERN && tones.size() == 1); // busy
  processBuzzerCommand("STOP"); assert(!buzzerActive() && activeHz == 0);
  processBuzzerCommand("ONE_MIN");
  assert(activeBeepPattern == ONE_MIN_PATTERN && tones.size() == 2);
  processBuzzerCommand("STATUS");
  assert(Serial.buffer.str().find("\"first_alarm_ms\":300000") != std::string::npos);
  assert(Serial.buffer.str().find("\"repeat_ms\":60000") != std::string::npos);
  assert(throttleRunMs == 0 && nextThrottleAlarmMs == FIRST_THROTTLE_ALARM_MS);
  processBuzzerCommand("STOP");
  const size_t count = tones.size();
  processBuzzerCommand("INVALID");
  assert(!buzzerActive() && tones.size() == count);
}
'''
        with tempfile.TemporaryDirectory() as directory:
            cpp = Path(directory) / 'buzzer.cpp'
            binary = Path(directory) / 'buzzer'
            cpp.write_text(harness)
            subprocess.run(['c++', '-std=c++11', '-Wall', '-Wextra', '-Werror',
                            str(cpp), '-o', str(binary)], check=True)
            subprocess.run([str(binary)], check=True)


if __name__ == '__main__':
    unittest.main()
