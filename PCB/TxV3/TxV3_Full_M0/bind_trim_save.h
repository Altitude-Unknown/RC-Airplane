#pragma once
#include <stdint.h>

// Bind button as the ArduPlane trim-save button (permanent, Tx V3 and V4).
// Holding Bind for HOLD_MS in normal flight operation sends one PULSE_MS pulse
// on CH7; the FC (RC7_OPTION 155) saves the trims only in MANUAL and confirms
// by blinking its status LED. Bind held at power-up still enters bind mode.
// CH5/CH6 (D10/D7, AUX1/AUX2) stay free for other functions.
namespace BindTrimSave {
static constexpr uint32_t HOLD_MS = 1000, PULSE_MS = 500, DEBOUNCE_MS = 25;
struct Button {
    bool raw = false, stable = false, ready = false, fired = false;
    uint32_t changedAt = 0, pressedAt = 0, firedAt = 0;
    bool update(bool pressed, bool permitted, uint32_t now) {
        if (pressed != raw) { raw = pressed; changedAt = now; }
        if (!permitted) {
            ready = false; fired = false;
            // A button held while inhibited stays inert until released.
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
} // namespace BindTrimSave
