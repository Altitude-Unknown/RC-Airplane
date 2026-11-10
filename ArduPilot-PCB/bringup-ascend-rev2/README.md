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

## 2026-11-01 bench session

Evidence, scripts and parameter captures are in `2026-11-01/` and `receiver/`.

- Temperatures at room temperature: IMU 28–31 C, baro 25–27 C. The earlier
  high readings were residual rework heat.
- Receiver: the onboard SAMD21 was running the configurator's standalone
  receiver firmware (linked, bind 7741), which never outputs SBUS, so the FC
  saw no RC. Installed the Rx V4 SBUS bridge `rx_arduplane_sbus/receiver-sbus.bin`
  (bind 7741 baked in) as UF2 through the custom `RCRXBOOT` bootloader
  (UF2 Bootloader v4.0.0, board `SAMD21G18A-Altitude-RC-RX-M0-v0`).
  The previous flash is backed up as `receiver/receiver-before-sbus.uf2`.
  The receiver pinout matches Rx V4 (NSS D8, RST D4, DIO0 D3, BIND D10,
  LED D13, SBUS PB22). **Do not update this receiver with the configurator's
  release firmware; it removes the SBUS output.**
  - The configurator's `BOOTLOADER` USB command did not reset this board; the
    receiver hung in the command's safe loop until SW2 was double-pressed.
  - During that attempt the configurator flashing routine, which tries every
    usbmodem port, also probed the FC port with BOSSA. It stopped at "Device
    unsupported" without erasing or writing; the FC kept running.
- FC RC: healthy, 16 channels. CH5 (Aux 1) 1000–2000 switches FBWA/Manual.
  CH6 fixed at 1000 because this transmitter's Aux 2 is faulty (fixed in the
  next Tx revision).
- Parameters copied from the last V2 flight set (2026-10-19), excluding
  hardware-specific and calibration values: GPS1_TYPE=0, ARSPD_TYPE=0,
  LOG_BACKEND_TYPE=0, AHRS_EKF_TYPE=0, ARMING_SKIPCHK=8, FLTMODE_CH=5,
  FLTMODE1=5, RC6_OPTION=155, RC_OPTIONS=96, MAV1_ADSB=5, MAV1_RAW_CTRL=1.
  COMPASS_ENABLE kept at 1 (V2 had no working compass).
- Radio calibration from a stick capture: RC1 1036/1522/2000, RC2
  1000/1353/1857, RC3 1003/1003/1998, RC4 1000/1451/1947. The pitch centre
  of 1353 suggests the Tx elevator trim is off-centre.
- Orientation measured (flat, then nose down): **AHRS_ORIENTATION=14**, same
  as V2. Mounting: components up, I2C header forward, servo header aft.
- Accelerometer six-position calibration: success (scales 0.990–1.005,
  offsets ≤0.18 m/s²). Its level trim (roll 1.86 deg) is the bench tilt;
  redo the level step once the board is installed in the airplane.
- Compass: with orientation 14 the MMC5983 vertical axis reads inverted
  (flat: z = −502 mG), so it needs its own rotation. Onboard calibration with
  COMPASS_AUTO_ROT=3 failed (fitness 25, ofs_x 2089, nothing saved): the
  3-inch USB cable kept the board beside the laptop and limited rotation.
  Field magnitude was steady (~560 mG flat and on its side), so the sensor
  itself looks fine. PreArm "Compass not calibrated" remains.
- Output mapping (Manual and FBWA, disarmed): SERVO1 throttle held at 1100,
  SERVO2 follows roll, SERVO3 pitch, SERVO4 yaw, SERVO5/6 off. Physical
  surface movement on J3 not yet observed.

Remaining:

1. Compass calibration with a longer USB cable, away from the laptop,
   ideally installed in the airplane; then put the confirmed compass rotation
   in hwdef (`COMPASS MMC5XX3 ... ROTATION_x`).
2. Physical servo/surface direction check on J3 (props off).
3. Level trim in the airplane; Tx elevator trim review.
4. RC-loss failsafe bench check with the bridge (Tx off → FC failsafe).
5. Custom I2C (DDC) GPS driver for the NEO-M9N.

### Combined receiver firmware and configurator flight controller update

- `rx_firmware` v7 (PWM + SBUS on PB22, one image for Rx V4 and the ASCEND
  board) flashed to the onboard receiver through the configurator's UF2 path
  (1200-baud touch mounted RCRXBOOT, no button). Test image:
  `receiver/rx-firmware-v7-test.uf2`. The update cleared the bind; the user
  rebound with SW1 + SW2.
- Before rebinding: packets with bind 7741 were rejected and no SBUS was sent
  (`sbusFrames=0`). After: 1279 accepted, 0 rejected, 2355 SBUS frames (~100 Hz).
- FC RC healthy over the v7 SBUS: RC1 1036–2000, RC2 1000–1852, RC3 1001–1998,
  RC4 1000–1947, RC5 1000–2000.
- The fixed `BOOTLOADER` USB command (UF2 double-tap magic + reset) entered
  RCRXBOOT without a button and kept the application; it hung the old
  configurator receiver firmware on this board.
- FC USB did not enumerate while the receiver USB was connected first; an
  unplug/replug of both fixed it.
- Configurator updater `flash_flight_controller` flashed the release image
  `flight_controller_firmware/ASCENDFCRev2/arduplane.apj` (clean build of
  ardupilot 25c94416c5, `release-build.log`): bootloader board ID 65093
  identified, written in 23 s, board re-enumerated without a replug, and
  AUTOPILOT_VERSION reports 25c94416. All 869 parameters kept; only the
  per-boot gyro offsets, baro ground pressure and boot count changed
  (`params-before/after-configurator-update.json`). All sensors and RC healthy.
- Not tested: Rx V4 servo PWM with the v7 image (no Rx V4 connected).

### Sensor rotations in firmware (AHRS_ORIENTATION=0)

- Compass calibration with a long USB cable fitted well (fitness 2.1) but was
  rejected: "Mag(0) internal bad orientation: 10 30.5". ArduPilot never
  auto-fixes an internal compass (`compass-cal-bad-orientation.txt`).
- ardupilot `5c10c497a4` declares the rotations in hwdef: IMU
  `ROTATION_ROLL_180_YAW_270` (previously AHRS_ORIENTATION=14), compass
  `ROTATION_YAW_180` (ROLL_180_YAW_90 composed with the board rotation).
  Clean-worktree build flashed with the configurator updater (23 s);
  AHRS_ORIENTATION set to 0.
- Flat on the bench: roll -0.8, pitch -2.1, compass z +476 mG (down, correct).
- Accelerometer six-position calibration: success, level trim roll 0.33,
  pitch -1.47 (`accel-cal-rotation-fixed.txt`).
- Compass calibration: "good orientation: 0", fitness 2.9, offsets 51/132/27,
  saved (`compass-cal-rotation-fixed.txt`).
- After reboot: all sensors and RC healthy, no pre-arm failures in 40 s.
  Nose pointed north by the user: heading settled at 9–17 deg (no GPS, so no
  declination correction; Montana declination is about 11 deg E).
- `flight_controller_firmware/ASCENDFCRev2/arduplane.apj` updated to this image.

### Onboard GPS over I2C (driver committed, no fix yet)

- ardupilot `e9dcbe3df6` (NEO-M9V identified as M9), `0450d91a4c` (u-blox
  over I2C/DDC port), `2719570b35` (Rev.2 enables it; GPS1_TYPE default 0).
- The module reports as **NEO-M9V** (`u-blox NEO-M9V 1 HW: 00190000 SW: EXT
  CORE 1.00 (add159)`), not the NEO-M9N in the schematic.
- With GPS1_TYPE=1: detected over I2C, configured, about 3 kB/s of UBX with
  zero I2C errors.
- No fix in 10 minutes from a covered porch in rain (`2026-11-01/gps-porch-no-fix.txt`).
  The user attributes it to too little ground-plane clearance at the antenna,
  as on the ASCEND Logger, and will fix it in the next PCB revision.
- Board left on firmware `2719570b` with GPS1_TYPE=0: all pre-arm checks pass
  without GPS. Set GPS1_TYPE=1 to test the GPS again.
- `flight_controller_firmware/ASCENDFCRev2` (release image) is still
  `5c10c497`, without the I2C GPS driver.
