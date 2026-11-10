# Session memory: 2026-10-31 — ASCEND FC Rev.2 first bring-up

New combined board: "Arduplane Compatible Flight Controller and LoRa Rx" Rev.2,
schematic `ASCEND-Flight_Controller v70.pdf` (copy in
`ArduPilot-PCB/bringup-ascend-rev2/`). STM32H743VIT6 FC plus onboard SAMD21 +
RFM95W receiver, LSM6DSO32, MS5611, MMC5983MA compass, NEO-M9N GPS, no SD card.
Full evidence and next steps: `ArduPilot-PCB/bringup-ascend-rev2/README.md`.

## Firmware

- New ArduPilot target `ASCENDFCRev2`, private board ID 65093 (V2 is 65092).
  Committed on ardupilot `borealis-v92-bringup` (eaf9c23702..25c94416c5); not pushed.
- Outputs 1–4 are PE9/PE11/PE13/PE14 = throttle/aileron/elevator/rudder, the
  REVERSE of V2's pin order. Never flash V2 firmware on this board.
- Compass declared explicitly (COMPASS MMC5XX3 I2C:0:0x30). SERIAL2 defaults to
  RC input for the onboard receiver SBUS on PC7.
- GPS disabled: the NEO-M9N connects to the STM32 over I2C only. User wants a
  custom I2C (DDC) GPS driver written later; I2C bus sharing with the compass is
  intended by design.
- `ASCENDFCRev2Diag` (not for flight) adds MS5611 PROM reporting and allows boot
  without a barometer.
- Build tools now persistent: `~/opt/gcc-arm-none-eabi-10-2020-q4-major`,
  `~/opt/ardupilot-venv` (old /tmp copies were wiped). dfu-util via Homebrew.

## Hardware results

- Initial DFU flash read back exactly. As on v92, the app needed a physical USB
  power cycle after DFU leave; bootloader uploads (uploader.py) did not.
- IMU and baro initially silent (MISO floating). Rail fine (3.2–3.3 V). User
  reinstalled the MS5611 and reflowed the LSM6DSO32; afterwards gyro, accel,
  compass and baro were all healthy. Same IMU fix as V2.
- High post-rework temperatures were falling steadily (residual heat); recheck.
- Board currently runs the normal `ASCENDFCRev2` image. Only parameter change:
  MAV1_* stream rates saved at 10 Hz by a stream request (telemetry only).
- Attitude reads ~upside down flat; orientation not yet set (V2 used 14).

## Tomorrow

User is washing/drying the board. Resume with orientation, receiver SBUS,
accel and compass calibration, servo mapping (props off), no-GPS training
parameters, and a temperature recheck. No flight-ready claim.
