# ASCEND FC V4 — flight-test setup

V4 is the only board going forward (GPS antenna fix verified 2026-11-12: 3D fix, 12 sats).
Firmware defaults: GPS1_TYPE 1, AHRS_EKF_TYPE 3, ARMING_SKIPCHK 0, ARSPD_TYPE 0, LOG_BACKEND_TYPE 0.

## 2026-11-13: rates before the first V4 AUTOTUNE flights

- Mike did Level Horizon in QGroundControl with the airplane level in the fixture
  (AHRS_TRIM_X 0.0100, AHRS_TRIM_Y 0.0088). Live check: roll −0.2°, pitch 0.0°.
- Backup before changes: `2026-11-13/params-before-rates.json` (877 params, all tuning stock).
- Applied the Rev.2 response changes (Mike asked; read back OK, `2026-11-13/param-change-rates.txt`):
  ROLL_LIMIT_DEG 45→55, PTCH_LIM_MAX_DEG 20→30, RLL_RATE_FF 0.345→0.5,
  PTCH_RATE_FF 0.345→0.7, RLL2SRV_TCONST 0.5→0.3, PTCH2SRV_TCONST 0.5→0.45,
  AUTOTUNE_LEVEL 6→7. To revert: 45 / 20 / 0.345 / 0.345 / 0.5 / 0.5 / 6.
- Rate P/I/D left stock on purpose: the Rev.2 AUTOTUNE gains were learned without GPS airspeed.
- Trim check (`2026-11-13/center-check.txt`, MANUAL, sticks centred): RC1 1487 = RC1_TRIM 1487,
  RC2 1492 ≈ RC2_TRIM 1493, so no hidden Tx-trim offset for AUTOTUNE (the Rev.2 right-roll cause).
- Mode switch not changed (FLTMODE1 MANUAL, FLTMODE6 FBWA); Mike will put AUTOTUNE on it himself.

## 2026-11-13 afternoon: "won't arm" at the field

- Indoors the board showed "EKF3 Yaw inconsistent ~103°". That's expected without GPS: on a plane, EKF3 doesn't
  initialise until there is a 3D fix (`AP_NavEKF3_core.cpp:474`), so its yaw is 0 while DCM reads the real heading.
- Outdoors (11 sats, hacc 3–4 m) EKF3 started and pre-arm passed. The GPS LED is a true 3D-fix indicator (`Plane.cpp:377`).
- Real cause: the ARM button was refused with "Arm: Roll (RC1) is not neutral" and "Pitch (RC2) is not neutral".
  Mike had re-trimmed the Tx at the field; centred sticks read RC1 1452 / RC2 1627 vs RC_TRIM 1487 / 1493 (DZ 30).
- Trim transfer (Mike set the trims deliberately; `2026-11-13/param-change-trim-transfer.txt`):
  SERVO2_TRIM 1500→1472, RC1_TRIM 1487→1452, SERVO3_TRIM 1500→1606, RC2_TRIM 1493→1627,
  SERVO4_TRIM 1500→1489, RC4_TRIM 1500→1486. MANUAL centre outputs unchanged (1472/1606/1489).
  Armed with the board button in MANUAL (`armwatch-after-trim.txt`). To revert: see `params-after-field.json`.
- Team-guide note: any Tx re-trim must be transferred to the FC, or arming fails and FBWA/AUTOTUNE ignore it.

## 2026-11-13 field: MANUAL at 100% rates; mode switch flipped

- The Tx mode-rate feature (2026-10-18, slot `Research`) gives full surface rates with CH5 LOW and the selected
  rates (30%) with CH5 HIGH, built for the Rev.2 layout. V4 had low = MANUAL, high = AUTOTUNE, so MANUAL got 100%.
- Fix (Mike's choice): FLTMODE1 0→8 (low = AUTOTUNE, full rates), FLTMODE6 8→0 (high = MANUAL, 30%).
  Arm with the switch HIGH (button works only in MANUAL/FBWA). Verified both positions (`modeswitch-centers.txt`).
- Mike re-trimmed elevator again (centre 1627 → 1522). Transferred: RC2_TRIM 1627→1522, SERVO3_TRIM 1606→1521
  (MANUAL output at centre 1521 unchanged). Aileron centre 1452 (low) / 1461 (high), within RC1_DZ 30; left as is.
- Next pre-arm: "Check mag field (z diff 249>200)" — magnetic interference near the airplane at the field
  (passed outdoors earlier). Not a trim issue.

## 2026-11-13 field: back to stock response for an FBWA baseline

- Mike flew FBWA (he set FLTMODE1 5 = FBWA low, FLTMODE6 0 = MANUAL high) and asked for stock ArduPlane settings.
- AUTOTUNE never saved gains today (rate P/I/D/FF untouched by it). Backup: `2026-11-13/params-before-stock-revert.json`.
- Reverted (`param-change-stock-revert.txt`): ROLL_LIMIT_DEG 45, PTCH_LIM_MAX_DEG 20, RLL_RATE_FF 0.345,
  PTCH_RATE_FF 0.345, RLL2SRV_TCONST 0.5, PTCH2SRV_TCONST 0.5, AUTOTUNE_LEVEL 6. Kept: calibrations, trims, modes.
- USB on J2 failed to enumerate at the field (no USB events at all; same cable worked with a phone), then came
  back on a later reseat. Inspect J2 solder joints on the bench.

## 2026-11-13 evening: lab rework and GPS "ready" LED

- Mike's rework: BARO LED had been fitted backwards (fixed), J2 USB-C pins reflowed, board washed and dried.
  After: USB enumerates cleanly; IMU/compass/baro healthy (baro 840.5 hPa) (`2026-11-13/after-usb-reflow.txt`).
- Board was running a `2719570b`-based image (Rev.2 test fixes). Flashed `arduplane-gps-ready-led.apj`
  (sha256 73b9354d…fedc): ardupilot `f05fc066` + uncommitted roll-airspeed fallback, DCM assumed TAS and the
  GPS LED change in `ArduPlane/Plane.cpp`. `ardupilot_uploader.py`, board fe45 identified, verify 100%.
  All 877 params unchanged (`params-before/after-led-flash.json`).
- GPS LED now: off = no 3D fix; 1 Hz blink = 3D fix but AHRS not ready (`ahrs.pre_arm_check(true)` failing or
  home not set); solid = ready, i.e. GPS/AHRS will not block arming. Field case it addresses: 3D fix with
  6–7 sats, HDOP 5–7, hacc 22–56 m, arming refused with "AHRS: not using configured AHRS type".
- Not yet verified with real sky. Not committed.

## 2026-11-13 night: FBWA dives — Rev.2 test fixes removed, clean firmware flashed

- Mike's report (field, stock response params): FBWA did not hold level; it dove, sometimes rolled over and dove
  (one crash, prop replaced). After landing in MANUAL, picking the airplane up and switching to FBWA drove the
  ailerons to their limits. After a reboot in the lab, FBWA levelled correctly on the bench. No log (no SD card).
- Leading explanation (not proven, no log): the uncommitted DCM fix (AP_AHRS_DCM_NO_GPS_ASSUMED_TAS 12) runs when
  DCM sees no 3D fix or < AHRS_GPS_MINSATS (6) sats while armed. The field GPS was marginal (6–7 sats, hacc
  22–56 m), and while armed with a 3D fix but EKF3 not fusing GPS, AHRS falls back to DCM (AP_AHRS.cpp ~2159).
  On the ground (carried/rotated while armed) the assumed 12 m/s along the nose creates false accelerations
  (~2 g for a 90°/s turn) that corrupt DCM attitude: matches the post-landing full-aileron. In flight, toggling
  across 6 sats switches between GPS velocity and the assumption, kicking the attitude estimate.
- Action (Mike's choice, no bench reproduction): removed both Rev.2 test fixes from the ardupilot checkout
  (saved as `2026-11-13/rev2-test-fixes-removed.patch`), built `f05fc066` + GPS LED change only
  (`arduplane-clean-gps-led.apj`, sha256 a386fc65…e3c4), flashed with `ardupilot_uploader.py` (fe45, verify 100%).
  Board reports `f05fc066`, sensors healthy, params unchanged (`params-before/after-clean-flash.json`).
- Still open: GPS reception fell from 11–17 sats (morning) to 6–7 (field). Check antenna area and placement.
  No FBWA/AUTOTUNE flight until GPS goes solid quickly outdoors with ≥10 sats.

## 2026-11-13 late: AUTO mission flown into the ground (clean firmware, stock gains)

- FBWA flight on clean firmware: OK apart from a slight descent (no dive/roll-over this time).
- AUTO mission (QGC plan: TAKEOFF 22.9 m, 4 WPs at 22.9 m rel, legs 52–132 m; Mike put AUTO on switch low,
  FLTMODE1 10). Entered AUTO from MANUAL at ~50 ft (~15 m): motor note changed (Mike thinks throttle down),
  turned to a heading, descended, nosed in hard. Only a 3D-printed motor mount broke. No log.
- Board afterwards (`2026-11-13/auto-crash-board-state.txt`): mission on board = the plan; WP_RADIUS still 90;
  IMU 1.00 g at rest, vibe ~0.02, no clipping, compass |B| 544 mG, baro healthy: no sensor damage.
- Likely contributors (unproven): stock pitch gains too soft to arrest a descent (seen on Rev.2 11-03 and as
  today's FBWA sink), AUTO starting at the TAKEOFF item below its altitude (holds course, levels off within
  TKOFF_LVL_ALT 10 m), no-airspeed TECS cutting throttle with nose-down pitch, WP_RADIUS 90 vs short legs, 15 m margin.
- Response settings restored (`param-change-rates-restored.txt`): ROLL_LIMIT_DEG 55, PTCH_LIM_MAX_DEG 30,
  RLL_RATE_FF 0.5, PTCH_RATE_FF 0.7, RLL2SRV_TCONST 0.3, PTCH2SRV_TCONST 0.45, AUTOTUNE_LEVEL 7.
- Next: AUTOTUNE on V4; TRIM_PITCH_DEG for FBWA level at cruise; next AUTO test without a TAKEOFF item,
  ≥60 m, WP_RADIUS 20, legs ≥150 m; flight logging (telemetry radio or SD/flash on the next PCB).

## 2026-11-14 field: AUTOTUNE flight — saved airplane profile

- Mike redid Level Horizon before flight (AHRS_TRIM_Y 0.0088 → 0.0959 rad, about 5.5°;
  AHRS_TRIM_X 0.0100 → 0.0151). That fixed the FBWA diving. A full battery in AUTOTUNE
  followed, and the airplane flew well.
- Read back without changing anything (only PARAM_REQUEST_LIST, then a passive listen):
  `2026-11-14/params-after-autotune-flight.json` (877 params).
  Restorable profile: `2026-11-14/ascend-v4-plane-autotuned-2026-11-14.param` (867 params,
  Mission Planner/MAVProxy format; STAT_*, *_GND_PRESS and FORMAT_VERSION omitted). Checksums in
  `2026-11-14/sha256.txt`. Firmware: `2026-11-13/arduplane-clean-gps-led.apj`.
- AUTOTUNE-saved gains (stock or response values before → after):
  - Roll: P 0.08 → 0.059, I 0.15 → 0.059, D 0 → 0.0033, FF 0.5 → 0.090, FLTT 5.3, RMAX 90.
  - Pitch: P 0.04 → 0.125, I 0.15 → 0.667, D 0 → 0.0034, FF 0.7 → 0.667, FLTT 3.5,
    RMAX up/down 90.
  - Pitch is close to the Rev.2 result (FF and I 0.632). Roll FF is much lower than Rev.2's 0.5.
- Unchanged from 2026-11-13: ROLL_LIMIT_DEG 55, PTCH_LIM_MAX_DEG 30, RLL2SRV_TCONST 0.3,
  PTCH2SRV_TCONST 0.45, AUTOTUNE_LEVEL 7, trims, GPS/EKF3. FLTMODE1 is 8 (AUTOTUNE, switch low),
  FLTMODE6 0 (MANUAL, switch high). MAV1_ADSB and MAV1_RAW_CTRL 4 → 5 were set by the ground station.
- Live state at readback: 3D fix with 18 sats, hacc 1.7 m; baro 840.1 hPa; relative altitude 0 m
  with home set.
- Note: AUTOTUNE stays on switch low. Each time AUTOTUNE is flown, it keeps adjusting the gains and
  saves them, so this profile is the reference to compare against or restore.

## 2026-11-14: trim-save candidate image (not flashed)

- `2026-11-14/arduplane-trim-save-led.apj` (sha256 976beb79…1435): the flown image's source
  plus the trim-save LED (status LED blinks fast for 3 s after "trim complete") and the board
  default `RC7_OPTION 155`. Pairs with the Tx/receiver Bind trim-save on CH7
  (`memory/2026-11-14-bind-trim-save-permanent.md`). Back up first. After flashing, read back
  and set `RC7_OPTION` to 155 if it was not picked up from the new default. Then re-verify the
  AUTOTUNE profile against `ascend-v4-plane-autotuned-2026-11-14.param`.

## 2026-11-14 bench: FC onboard receiver flashed with CH7 trim-save support

- Device: the FC's onboard SAMD21 receiver, USB serial 8EACFE7950304C59502E3120FF0E1005. Before:
  `rx-v7-pwm-sbus`, radio OK, bound to 7741.
- Backup: full 256 KB flash read twice with BOSSA, both reads identical
  (`2026-11-14/receiver/receiver-before-full.bin`, sha256 89296a06…fa42). Bind record at 0xC600:
  magic BIND, code 7741.
- Image: `rx_firmware` from the Bind trim-save change (SBUS CH7 = aux bit 0x40). The new build's
  BIND_STORE is also at 0xC600, so the 8-byte record was copied into the empty store
  (`receiver/rx-v7-ch7-bind7741.bin`, sha256 a834793d…406d; unbound build kept beside it).
- Flashed with BOSSA (offset 0x2000, erase/write/verify, reset): "Verify successful". After the
  reset, STATUS: radio OK, stored 7741, firmware rx-v7-pwm-sbus. The ID string did not change, so
  the BOSSA verify is the evidence of the new image.
- SBUS CH7 now idles at 1000 µs (was neutral 1500). The FC currently has RC7_OPTION 0, so this has
  no effect until the FC update.
- Still to do: Tx firmware, FC firmware `arduplane-trim-save-led.apj` + RC7_OPTION 155, then the
  bench check (CH7 pulse, chirp, MANUAL-only save, LED blink, trim readback).

## 2026-11-14 bench: FC flashed with the trim-save LED image

- Before: ArduPlane 4.7.1 git f05fc066 (`2026-11-13/arduplane-clean-gps-led.apj`), disarmed,
  MANUAL. Params backed up: `2026-11-14/params-before-trim-save-flash.json` (877). Since the field
  readback, Mike set FLTMODE1 8 → 5 (FBWA on switch low). Gains are unchanged.
- Flashed `2026-11-14/arduplane-trim-save-led.apj` (sha256 checked) with `ardupilot_uploader.py`.
  Board fe45, chip sn 003c00243034510332333739, verify 100% (`flash-trim-save-led.log`).
- After: git 243905c9, disarmed. Indoor pre-arm messages only (no GPS fix, RC off, EKF yaw).
  Baro 843.6 hPa. `params-after-trim-save-flash.json`: the only changes are RC7_OPTION 0 → 155
  (picked up from the new board default; never saved before) and boot-time gyro/baro values.
  All 74 tuning/limit/AHRS-trim/RC/servo-trim parameters match the AUTOTUNE profile.
- The profile `.param` now has RC7_OPTION 155, so restoring it keeps trim-save enabled.
- Next: Tx firmware (back up firmware and model memory first), then the bench trim-save check.

## 2026-11-14 bench: Bind trim-save end-to-end test — PASSED

Setup: Tx (new firmware, Research model), FC onboard receiver (CH7 firmware), FC (243905c9,
RC7_OPTION 155), props off, disarmed. Evidence: `2026-11-14/trim-save-bench-test.txt`,
`trim-save-bench-fbwa.txt`.

- Idle CH7 1000 µs. A 1 s Bind hold gave one CH7 pulse of 0.50 s each time.
- MANUAL: "trim complete" 0.1 s after the pulse. Mike saw the FC LED blink fast and heard the Tx
  chirp. Saved: RC1_TRIM 1452 → 1466, RC4_TRIM 1486 → 1685, SERVO2_TRIM 1472 → 1483,
  SERVO4_TRIM 1489 → 1649; elevator unchanged (stick at its trim). New RC centres = stick positions
  at the save, so centred sticks read neutral.
- The rudder offset is the Tx rudder subtrim of +185, which Mike confirmed is correct (new tail).
- FBWA: pulse → "trim failed, not in manual mode"; all six trims unchanged.
- Full snapshot after the test: `2026-11-14/params-after-trim-save-bench-test.json`. Only the four
  trims (and COMPASS_DEC from GPS) changed since the flash. The AUTOTUNE `.param` profile still
  holds the pre-tail-change trims; use this snapshot for this airframe's current trims.
