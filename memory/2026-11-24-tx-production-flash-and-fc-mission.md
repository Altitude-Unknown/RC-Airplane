# 2026-11-24: New SAMD21 bootloader on hardware, 29 Tx PCBs flashed, FC mission load and read-back

## Altitude SAMD21 Bootloader: hardware-verified

- The new SAMD21 bootloader (repo `Altitude-SAMD21-Bootloader`) works on real
  hardware. It was installed on the new Tx PCBs with the SAMD21 Bootloader
  Flasher (v1.0.0) and an Atmel-ICE.
- Verified on the board:
  - The `RCTXBOOT` drive mounted with `INFO_UF2.TXT`.
  - USB ID is 1209:A5C0.
  - SAM-BA answered.
  - BOOTPROT = 2.
  - Double-tap reset enters the bootloader.
  - Configurator UF2 firmware update works.
- Follow-up releases that day: RC-Airplane PR #16 (firmware uses the pid.codes
  IDs) and PR #17 (FC image checksum fix); transmitter-gui-v2026.11.24.1 and
  flight-control-v2026.11.24.1.

## Tx PCB production batch: 29 of 35 flashed

- 35 new Tx PCBs. 29 flashed and working on the first pass.
- Flashed with the RC Configurator built into ASCEND Flight Control: both the
  SAMD21 M0 firmware and the ESP32-C3 (TxV3 Buddy) firmware. This is the same
  route ASCEND teams will use.
- 6 boards had problems.

### The 6 problem boards

- Symptom: the M0 flashes OK but doesn't run afterward. It drops off USB and
  comes back only in the bootloader, after a double-tap reset. On the board we
  examined:
  - The ESP32-C3 answered normally (role `UNCONFIGURED`, MAC 9A:64:9B:1B:0B:C1).
  - The ESP reported `mode=UNKNOWN` and `samd_lines=1`, so it wasn't hearing
    the M0.
  - Because of that, the configurator could not set the role to Master. The
    ESP accepts `ROLE MASTER` only after a fresh M0 `MODE CONFIG`, `SIMULATOR`
    or `SETUP` heartbeat (`TxV3_Buddy_ESP32.ino` `roleChangeAllowed`).
- Diagnosis: the problem is with the board hardware, not the firmware or the
  configurator.
  - The bootloader doesn't need a crystal. It locks its clock to USB (DFLL
    USBCRM).
  - The TX firmware is built as `adafruit_feather_m0_express`, which is not
    `CRYSTALLESS`. At startup the Arduino core waits forever for the 32.768 kHz
    crystal (XOSC32K on PA00/PA01) to start, before USB comes up.
  - So a dead or marginal crystal or its load-cap joints gives exactly this
    symptom.
  - A second possible cause is the M0-to-ESP UART (PB22 to GPIO20, PB23 to
    GPIO21). If that link is broken, the M0 also stalls at boot in
    `txv3BuddyBegin()`, waiting for a role reply.
- Status:
  - The first board was fixed by reworking solder joints.
  - The other 5 were reworked and are drying. **Test on 2026-11-25.**
- Decision: keep the crystal-based firmware build. A crystalless build would
  boot without the crystal, but it would run on a less accurate clock when on
  battery with no USB connected.

## ASCEND FC: mission load and read-back

- The ASCEND FC connected to ASCEND Flight Control over USB (`/dev/cu.usbmodem1101`).
- The mission that was already on the FC was downloaded to the laptop.
- A new mission was made in the app and saved to the FC.
- Claude read it back independently with pymavlink (read-only) and it matched.
- Close the app before another tool opens the FC port, because only one program
  can hold it.
- The stored mission has 5 items: home plus 4 WAYPOINTs at 100 m relative.

  | # | Lat, Lon | Leg to next waypoint |
  |---|---|---|
  | 1 | 45.66386, −111.07842 | 225 m south |
  | 2 | 45.66185, −111.07846 | 357 m west |
  | 3 | 45.66176, −111.08306 | 252 m north |
  | 4 | 45.66401, −111.08349 | — |

  There is no TAKEOFF, LAND or DO_JUMP, so:
  - Launch in MANUAL or FBWA, then switch to AUTO in the air.
  - The mission flies once and ends in RTL.
  - With WP_RADIUS 90, the corners will be rounded.
- Key parameters:
  - CH5 flight modes: AUTO / RTL / FBWA / FBWA / MANUAL / MANUAL.
  - RTL_ALTITUDE 100.
  - THR_FAILSAFE 1. FS_LONG_ACTN 0 means it continues the mission in AUTO.
  - FENCE_ENABLE 0. CAM1_TYPE 0.
  - GPS1_TYPE 1. EK3_ENABLE 1.
- Bench health:
  - Gyro, accel, compass and baro are healthy.
  - GPS detected, but no fix indoors.
  - Pre-arm messages:
    - "EKF3 Yaw inconsistent 22 deg": bench with no GPS; should clear outdoors.
    - "GPS 1: Bad fix".
    - "Waiting for RC": the Tx was off.
  - AUTO already flew successfully on 2026-11-15 (see
    `2026-11-15-flight-tests-fbwa-auto.md`), so an outdoor fix is expected.
- Next:
  - Get an outdoor fix.
  - Do a ground mode check through AUTO and RTL.
  - Optionally add a DO_JUMP loop or a LAND item, if Mike asks.
