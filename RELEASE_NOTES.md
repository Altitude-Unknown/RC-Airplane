Slow stick movements now produce finer receiver servo commands: aileron,
elevator, and rudder accept 1 µs changes instead of accumulating changes into
steps of at least 3 µs. No additional filtering delay is introduced.

Only the receiver needs updating for this improvement. Transmitter firmware,
packet compatibility, throttle handling, arming/failsafe logic, model settings,
trims, rates, expo, and reversing are unchanged. The receiver image also includes
the USB STATUS diagnostic used to check radio health and binding.

Validation: receiver compilation and 27 automated tests passed, including
single-microsecond surface sweeps and exhaustive throttle-output comparisons.
The receiver was flashed and verified; the pilot's bench test reported visibly
smoother surface motion. This change has not yet been flight-tested. Existing
servo timing irregularities are documented in CONTROL_SMOOTHNESS_REVIEW.md and
are not changed in this release.

Flashing may clear the receiver bind; it did on the tested board. Rebind if
needed, then check directions, travel, trims, arming, and link-loss failsafe
with the propeller removed before flight.

Includes configurator apps for macOS ARM64, Windows x64, and Raspberry Pi
ARM64; transmitter M0/ESP32 firmware; receiver firmware; and SHA-256 manifest.

This release also carries the previously committed configurable CH5/CH6 button
assignments, which were not in release 2026.09.14. Those optional features have
automated test coverage but still await dedicated hardware validation. Existing
models retain trainer/disabled defaults. To use button assignments, update the
configurator and corresponding transmitter firmware together; older GUI
versions do not preserve the assignments. See BUTTON_CHANNELS.md. This is
separate from the receiver-only smoothness update.
