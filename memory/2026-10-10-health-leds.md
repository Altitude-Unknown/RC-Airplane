# BOREALIS V2 health LEDs — 2026-10-10

User reports L3 appears damaged by soldering and will repair it. User
explicitly authorized implementing the other LEDs now. Current schematics
confirm active-high LEDs through 2.2k resistors to ground:
L4 PB15 IMU, L5 PB14 pressure, L6 PB13 GPS, L7 PB12 compass.

Added board-specific GPIO93–96 and a 5 Hz Plane scheduler task. L4 uses
primary gyro+accelerometer health, L5 primary barometer health, L6 healthy
primary GPS with at least 3D fix, L7 available/detected/healthy compass.
Optional libraries are compile-time guarded; unavailable sensors remain off.
No changes to arming, motor, radio, sensor configuration or failsafes.
The existing tested ARM-button implementation is included in this build.

USB /dev/cu.usbmodem1101 is connected. Full 869-parameter backup captured
before update; FC disarmed. Live gyro, accelerometer and barometer health
bits true; GPS and compass false as expected. Receiver link unavailable:
prearm messages radio failsafe and RTL not armable. Do not alter mode or
failsafe configuration as part of LED work.

Artifacts: ArduPilot-PCB/bringup-v2/servo-enabled/health-leds/.

Full BOREALISv2Servo hardware build passed: 1,331,048 bytes flash used.
APJ board ID, decompressed BIN match, generated GPIO pin map and ELF
health-LED/ARM-button scheduler functions verified. Uploaded over USB,
bootloader flash verification passed, rebooted disarmed. Read back all 869
parameters; configuration unchanged (seven expected startup calibration/
counter differences). Post-reboot gyro+accel+barometer healthy, GPS/compass
unhealthy/absent as expected; prearm Waiting for RC. No arming command sent.
User explicitly confirmed both L4 and L5 are illuminated. Future GPS/compass
healthy indications and failure transitions remain untested. Source
snapshots, focused combined firmware patch, firmware, parameter backups,
logs and validation.json packaged. No commit/push performed; unrelated
pre-existing v92 and Rx edits untouched. APJ SHA256:
ef8c9b7aafd09ffd8910aec1c5c675c4ef3b87b466ffa136835c635f8f307a78.
