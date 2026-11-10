# BOREALIS V2 live sensor LEDs — 2026-10-10

AI-assisted firmware update for BOREALISv2Servo, board ID 65092. Includes
the tested physical ARM-button behavior from the arm-button image.

Source commit: [15bb8cb](https://github.com/mwalach76/ardupilot/commit/15bb8cb),
branch `borealis-v92-bringup`. The installed binary was built from the same
source before committing; its embedded version hash is the base `d276581b`.

The four active-high sensor LEDs update five times per second:

| LED | Schematic net | MCU pin | GPIO | Illuminated when |
| --- | --- | --- | --- | --- |
| L4 | IMU-HEALTH | PB15 / pin54 | 93 | Primary gyro and accelerometer both report healthy |
| L5 | PRESSURE-HEALTH | PB14 / pin53 | 94 | Primary barometer reports healthy |
| L6 | GPS-HEALTH | PB13 / pin52 | 95 | Primary GPS is healthy and has at least a 3D fix |
| L7 | MAGNATOMETER-HEALTH | PB12 / pin51 | 96 | Compass is available, detected, and healthy |

Each LED turns off when its condition fails. GPS/compass indicators remain
off if the corresponding hardware is absent or disabled. These indicators
report sensor status, not completion of calibration or flight readiness.
All four pins start low at boot. Optional sensor libraries are guarded so
an omitted library leaves its LED off.

L3/BLINK on PC12 remains the existing arming/status indicator. User reports
L3 appears damaged by soldering; it stayed dark during a steady-on GPIO
test. Its repair is independent of this update.

No sensor configuration, radio mapping, calibration, throttle endpoint,
arming-check or failsafe changes are part of this update. Installation and
verification results are recorded in validation.json.

Installed through the USB bootloader on 2026-10-10; board ID 65092 matched
and flash verification passed. Post-reboot capture read all 869 parameters;
aircraft configuration was preserved, with only normal startup sensor
calibration values and counters changing. FC remained disarmed. Gyro,
accelerometer and barometer telemetry reported healthy. User confirmed both
L4 and L5 illuminate. GPS and compass healthy-state illumination and sensor
failure transitions remain untested because those sensors are not installed.
