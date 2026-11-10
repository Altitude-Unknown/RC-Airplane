Updates the ArduPlane firmware for the ASCEND flight controller Rev.2 so its
sensor orientation is built in.

**ASCEND FC Rev.2 sensor rotations.** The IMU and compass rotations are now
declared in the board's firmware (ArduPilot `5c10c497a4`). The standard
mounting (components up, I2C header forward) is `AHRS_ORIENTATION=0`; you no
longer set it by hand. The previous release's firmware needed
`AHRS_ORIENTATION=14`, and its compass could fail calibration with "bad
orientation".

**If your board was set up with the previous release:** after updating, set
`AHRS_ORIENTATION=0`, then redo the accelerometer and compass calibrations
before flight. Update with Firmware Update → Flight controller → Download and
Flash Latest; parameters are kept, which is why `AHRS_ORIENTATION=14` must be
changed by hand.

The Rev.2 GPS is still not supported: its I2C GPS driver is in testing and
not in this image.

The configurator, transmitter firmware, and receiver firmware (v7) are
unchanged from 2026.11.01, and mode-linked surface rates are retained.

Includes macOS Apple Silicon ARM64, Windows x64 and Raspberry Pi ARM64 apps,
plus firmware and the SHA-256 manifest.

Validation: 32 release tests passed. On ASCEND FC Rev.2 hardware, this image
was flashed with the configurator (23 seconds). Level attitude, the
six-position accelerometer calibration, and the compass calibration (good
orientation) passed, the heading was checked against north, and all pre-arm
checks passed.

Not yet tested: Rx V4 servo outputs with receiver v7. Bench-check a Rx V4
before flight.
