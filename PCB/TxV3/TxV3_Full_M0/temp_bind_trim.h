#pragma once
#include <stdint.h>

// TEMPORARY V3 bench/flight-test workaround. REMOVE when TX V4 is ready.
// CH6 is reserved for this action; never combine with D7's old assignment.
namespace TempBindTrim {
static constexpr uint32_t HOLD_MS = 2000, PULSE_MS = 500, DEBOUNCE_MS = 25;
struct Button {
    bool raw = false, stable = false, ready = false, fired = false;
    uint32_t changedAt = 0, pressedAt = 0, firedAt = 0;
    bool update(bool pressed, bool permitted, uint32_t now) {
        if (pressed != raw) { raw = pressed; changedAt = now; }
        if (!permitted) {
            ready = false; fired = false;
            // A held button cannot arm when switching into MANUAL.
            stable = raw;
            return false;
        }
        if ((uint32_t)(now - changedAt) >= DEBOUNCE_MS) {
            bool wasPressed = stable;
            stable = raw;
            if (!stable) { ready = true; fired = false; }
            if (stable && !wasPressed && ready) pressedAt = now;
        }
        if (!stable || !ready) return false;
        if (!fired && (uint32_t)(now - pressedAt) >= HOLD_MS) {
            fired = true; firedAt = now;
        }
        // Single bounded pulse; another pulse requires a debounced release.
        return fired && (uint32_t)(now - firedAt) < PULSE_MS;
    }
};
} // namespace TempBindTrim
