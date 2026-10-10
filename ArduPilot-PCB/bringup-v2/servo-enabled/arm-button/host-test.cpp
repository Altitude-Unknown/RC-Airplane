#include "../../ardupilot/ArduPlane/board_arm_button.h"
#include <cassert>
#include <cstdio>

static void release(BoardArmButton &button, uint32_t now)
{
    assert(!button.update(now, false, true));
    assert(!button.update(now + 100, false, true));
}

int main()
{
    BoardArmButton button;
    // Held at boot cannot trigger, even after a long delay.
    assert(!button.update(0, true, true));
    assert(!button.update(10000, true, true));
    release(button, 10020);
    assert(!button.update(10140, true, true));
    assert(!button.update(12139, true, true));
    assert(button.update(12140, true, true));
    assert(!button.update(20000, true, true));
    // Release bounce and short presses must not retrigger.
    assert(!button.update(20020, false, true));
    assert(!button.update(20040, true, true));
    assert(!button.update(23000, true, true));
    release(button, 23020);
    assert(!button.update(23140, true, true));
    assert(!button.update(24000, false, true));
    assert(!button.update(24020, true, true));
    assert(!button.update(26019, true, true));
    assert(button.update(26020, true, true));
    // Unsafe start or loss of any eligibility gate consumes the press.
    release(button, 27000);
    assert(!button.update(27120, true, false));
    assert(!button.update(30000, true, true));
    release(button, 30020);
    assert(!button.update(30140, true, true));
    assert(!button.update(31000, true, false));
    assert(!button.update(34000, true, true));
    release(button, 34020);
    assert(!button.update(34140, true, true));
    assert(button.update(36140, true, true));
    // Millisecond counter wrap must preserve the hold interval.
    BoardArmButton wrap;
    release(wrap, UINT32_MAX - 3000);
    assert(!wrap.update(UINT32_MAX - 1000, true, true));
    assert(!wrap.update(998, true, true));
    assert(wrap.update(999, true, true));
    std::puts("PASS: boot lock, hold duration, one action per press, bounce, eligibility loss, timer wrap");
}
