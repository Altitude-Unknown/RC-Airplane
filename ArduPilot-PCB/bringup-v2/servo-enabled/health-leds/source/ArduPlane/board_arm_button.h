#pragma once

#include <stdint.h>

// A momentary board button must be released after boot, rejection or action.
class BoardArmButton {
public:
    bool update(uint32_t now_ms, bool pressed, bool allowed)
    {
        if (!pressed) {
            holding = false;
            if (!releasing) {
                releasing = true;
                release_ms = now_ms;
            }
            if (uint32_t(now_ms - release_ms) >= 100) {
                waiting_release = false;
            }
            return false;
        }
        releasing = false;
        if (waiting_release) {
            return false;
        }
        if (!allowed) {
            holding = false;
            waiting_release = true;
            return false;
        }
        if (!holding) {
            holding = true;
            press_ms = now_ms;
        }
        if (uint32_t(now_ms - press_ms) < 2000) {
            return false;
        }
        waiting_release = true;
        holding = false;
        return true;
    }

private:
    bool waiting_release = true;
    bool releasing = false;
    bool holding = false;
    uint32_t release_ms = 0;
    uint32_t press_ms = 0;
};
