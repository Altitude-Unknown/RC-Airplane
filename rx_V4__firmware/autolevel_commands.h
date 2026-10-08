#pragma once
#include <stdint.h>

// Current TX protocol: marked CH5 = Trainer, CH6 = Aux, both Momentary.
// The receiver latches the mode; holding ON must never defeat OFF or a fault.
struct AutolevelCommands {
  enum Command { NONE, ENABLE, DISABLE };
  bool released = false;
  bool onWasHigh = false;

  void reset() { released = false; onWasHigh = false; }

  Command update(uint8_t flags) {
    if (!(flags & 0x80)) { reset(); return DISABLE; }
    bool on = flags & 0x10;
    bool off = flags & 0x20;
    if (off) { reset(); return DISABLE; }
    if (!on) { released = true; onWasHigh = false; return NONE; }
    bool press = released && !onWasHigh;
    onWasHigh = true;
    return press ? ENABLE : NONE;
  }
};
