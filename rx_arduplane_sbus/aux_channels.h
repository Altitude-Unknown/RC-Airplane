#pragma once
#include <stdint.h>

// Model reserved[5]: bits 0..1 D10 (0=trainer,1=momentary,2=toggle),
// bits 2..3 D7 (0=disabled,1=momentary,2=toggle). Invalid values default off.
// Existing control/ESP packets retain their length. Bit 7 marks the new
// encoding; bits 4/5 carry CH5/6. Old experimental low bits are never decoded.
namespace AuxChannels {
static const uint8_t MARKER = 0x80, CH5 = 0x10, CH6 = 0x20;
inline uint8_t mode(uint8_t config, uint8_t shift) {
  uint8_t value = (config >> shift) & 3;
  return value <= 2 ? value : 0;
}
inline uint8_t encode(bool five, bool six) {
  return MARKER | (five ? CH5 : 0) | (six ? CH6 : 0);
}
inline uint16_t pulse(uint8_t flags, uint8_t channelMask) {
  return (flags & MARKER) && (flags & channelMask) ? 2000 : 1000;
}

// Debounce both edges, toggle only on a press, and require release after boot.
// All states are RAM-only: a reset starts low, even if a button is held.
struct Button {
  bool raw = false, stable = false, ready = false, high = false;
  uint32_t changedAt = 0;
  bool update(bool pressed, uint8_t behavior, uint32_t now) {
    if (pressed != raw) { raw = pressed; changedAt = now; }
    if ((uint32_t)(now - changedAt) >= 25) {
      bool wasPressed = stable;
      stable = raw;
      if (!stable) ready = true;
      if (behavior == 2 && ready && stable && !wasPressed) high = !high;
    }
    if (behavior == 0) high = false;
    else if (behavior == 1) high = ready && stable;
    return high;
  }
};
}
