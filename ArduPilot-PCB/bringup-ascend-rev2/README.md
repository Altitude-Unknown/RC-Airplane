# ASCEND FC Rev.2 bring-up — 2026-10-31

Board: "Arduplane Compatible Flight Controller and LoRa Rx", Rev.2, schematic
`ASCEND-Flight_Controller v70.pdf` (copied here). STM32H743VIT6, 8 MHz crystal.
ArduPilot target `ASCENDFCRev2` (private APJ_BOARD_ID 65093).

## Differences from BOREALIS V2 that matter for firmware

- Outputs 1–4 are PE9/PE11/PE13/PE14 = throttle/aileron/elevator/rudder
  (J3 pins 3/6/9/12). V2 used the reverse pin order; V2 firmware must not be
  flashed on this board, hence the separate board ID.
- MMC5983MA magnetometer on I2C1 (0x30), declared with a COMPASS line.
- NEO-M9N GPS is wired to the STM32 over I2C1 only (UART pins 20/21 not
  connected). ArduPilot has no I2C GPS driver, so GPS is disabled. A custom
  I2C (DDC) GPS driver is planned.
- Onboard SAMD21 receiver SBUS on PC7; SERIAL2_PROTOCOL defaults to 23.

## Flashing

- STM32 ROM DFU (0483:df11). `arduplane_with_bl.bin` (bootloader + app at
  0x08020000, 1,463,808 bytes) written with dfu-util and read back: exact match
  (`readback.bin`). Checksums in `sha256.json`.
- As on v92, the application USB did not enumerate after DFU leave; a
  physical USB power cycle brought up `ASCENDFCRev2_BL`, then `ASCENDFCRev2`.
- Later diagnostic images were uploaded through the ArduPilot bootloader
  (`uploader.py`, board 65093 identified); software reboot into the bootloader
  worked without a power cycle.
- The first status check sent REQUEST_DATA_STREAM, which saved MAV1_* stream
  rates of 10 Hz. Telemetry-only; restore defaults if preferred.

## Sensor results

- `first-boot-sensors.txt` (normal image): Config Error "Baro: unable to
  initialise driver"; IMU and compass not yet probed.
- `diag-baro-statustext.txt` (ASCENDFCRev2Diag): MS5611 PROM words all 0000.
- `diag-nobaro-sensors.txt` (diag image allowing boot without baro):
  - Magnetometer present (MMC5983 ID check passed on I2C1).
  - LSM6DSO32 ID 00/00; GPIO MISO test M0/M3/up/down = 00/00/FF/00, i.e. the
    IMU SDO line is floating — nothing drives it.

Rework and results:

- FILTERED-3.3V measured 3.2 V on both sides of FB3 and 3.3 V at the MS5611,
  so the shared rail was not the cause.
- With the MS5611 removed, the IMU result was unchanged (`diag-baro-removed-
  sensors.txt`); the baro was not shorting anything.
- After the MS5611 was reinstalled: PROM `00BC C06C BB27 70A6 653A 80B2 66DF
  48DA`, CRC ok; 76 live readings 852.9–853.1 hPa (`diag-after-rework-sensors.txt`).
- After the LSM6DSO32 was reflowed: gyro, accel, compass and baro all present
  and healthy (`diag-imu-reflow-sensors.txt`). Same failure signature and fix
  as the V2 IMU.
- Temperatures read high right after rework (IMU 61.9 C, baro 45–48 C) and
  fell steadily (IMU 55.7 to 48.8 C in 40 s, `temperature-trend.txt`):
  residual soldering heat. Recheck once the board is at room temperature.
- Normal `ASCENDFCRev2` image re-uploaded through the bootloader (same apj as
  `arduplane.apj`): "ArduPilot Ready", RCOut PWM 1-6, all four sensors healthy
  (`normal-image-sensors.txt`). Expected messages: MS4525 airspeed not found,
  AHRS DCM active (no GPS). RC not present (transmitter off).
- With the board flat, components up, attitude reads roll about -178 deg:
  the IMU frame is inverted relative to the board, as on V2 (V2 needed
  AHRS_ORIENTATION=14 in its airplane mounting). Not yet set for this board.

## Next

The user is washing and drying the board after rework (2026-10-31 night).
No parameters have been changed except the MAV1_* stream rates noted above.

1. Board orientation: flat, components up, note forward edge, tilt nose
   down; derive AHRS_ORIENTATION from live telemetry and confirm with user.
2. Power the bound transmitter; confirm SBUS on PC7 and channel ranges.
3. Six-position accelerometer calibration, then compass calibration
   (compass orientation unverified).
4. Servo direction/mapping check on J3 outputs (props off).
5. No-GPS training parameters as on V2: ARSPD_TYPE=0, GPS1_TYPE=0,
   GPS-free failsafe instead of RTL. Recheck temperatures at ambient.
6. Later: custom I2C (DDC) GPS driver for the onboard NEO-M9N.
