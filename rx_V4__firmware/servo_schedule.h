#pragma once
#include <stdint.h>

// Hardware-independent TAER pulse schedule. The timer consumes one event at a
// time; the foreground publishes a complete frame under a brief IRQ guard.
class ServoSchedule {
 public:
  struct Edge { int8_t low; int8_t high; uint16_t delayUs; };
  uint16_t pending[4] = {1000, 1500, 1500, 1500};
  uint16_t active[4] = {1000, 1500, 1500, 1500};
  volatile uint32_t frames = 0;
  volatile uint32_t submittedFrame = 0;
  uint8_t phase = 0;
  volatile bool stalled = false;
  volatile bool fault = false;
  void submit(uint16_t t, uint16_t a, uint16_t e, uint16_t r) {
    const uint16_t values[4] = {t, a, e, r};
    for (uint8_t i = 0; i < 4; ++i)
      pending[i] = values[i] < 1000 ? 1000 : (values[i] > 2000 ? 2000 : values[i]);
    submittedFrame = frames;
  }
  Edge next() {
    if (phase == 0) {
      ++frames;
      // This watchdog is for a stalled foreground, not RF loss. The foreground
      // continues publishing the existing staged RF-failsafe outputs normally.
      stalled = frames - submittedFrame > 5;
      if (stalled) fault = true; // reset required after an execution failure
      for (uint8_t i = 0; i < 4; ++i)
        active[i] = fault ? (i == 0 ? 1000 : 1500) : pending[i];
      phase = 1;
      return {-1, 0, active[0]};
    }
    const int8_t finished = phase - 1;
    if (phase < 4) {
      const int8_t started = phase++;
      return {finished, started, active[started]};
    }
    phase = 0;
    uint16_t used = 0;
    for (uint8_t i = 0; i < 4; ++i) used += active[i];
    return {finished, -1, (uint16_t)(20000 - used)};
  }
};
