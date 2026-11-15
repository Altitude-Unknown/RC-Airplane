# 2026-11-15: Flight tests on the V4 airplane: FBWA, MANUAL and AUTO

Pilot report from the user. Firmware is the 2026-11-14 update: Tx, receivers and
ASCEND FC flashed with the bind trim-save changes (see
`2026-11-14-bind-trim-save-permanent.md`, release `transmitter-gui-v2026.11.14`).

## Flight 1: FBWA and MANUAL

- Flew FBWA and MANUAL with all of the 2026-11-14 code changes loaded.
- Result: the airplane flew perfectly in both modes.

## Between flights

- Landed and connected the FC to the laptop over USB-C to load an AUTO mission.
- The FC's USB-C port was unreliable and the board did not enumerate on the Mac
  at first. The user suspects a bad solder joint on the connector. This is a
  hardware fault on this board and an easy fix, not a firmware problem.
  **To do:** reflow or repair the FC USB-C connector.

## Flight 2: AUTO mission

- Took off in MANUAL, switched to AUTO in flight.
- Flew the whole mission well, then loitered at the end as programmed.
- Switched back and landed uneventfully in MANUAL.

## Conclusion

The user considers the ArduPlane autopilot on the ASCEND FC V4 working:
FBWA, MANUAL and AUTO (waypoints plus end-of-mission loiter) are flight-proven
on the 2026.11.14 firmware.

## Not covered by these flights

- The report did not mention an in-flight Bind trim-save (CH7). The bench test
  passed on 2026-11-14; an in-flight trim-save is still to be confirmed.
- Do not take these flights as a reason to change the FBWA full-rate setting
  (Research `ch5_rate_mode=1`). It stays as it is (AGENTS.md).
