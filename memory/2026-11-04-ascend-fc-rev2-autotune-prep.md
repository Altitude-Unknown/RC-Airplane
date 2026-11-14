# ASCEND FC Rev.2 — AUTOTUNE prep, 2026-11-04

Follows `2026-11-03-ascend-fc-rev2-first-flight.md`. Evidence is in `ArduPilot-PCB/bringup-ascend-rev2/2026-11-04/`.

## Problem

In AUTOTUNE the airplane only rolled about 5° with full stick, so Mike had to switch to MANUAL to turn.

## Ruled out on the bench

- **Tx rates:** full stick range in the AUTOTUNE switch position.
- **Level reference:** pitch −1.0°, roll +0.3° with the airplane level.
- **Control directions:** ailerons, rudder and elevator correct, including the stabilization response when the airplane is tilted by hand. The rudder mix (KFF_RDDRMIX 0.5) is not fighting the ailerons.

## Elevator "pulsing" in AUTOTUNE (bench only)

- **What was seen:** `pitch-pulse-bench.txt` shows a sawtooth. The elevator ramps about 190 µs/s, then snaps back.
- **Cause:** ArduPlane `Attitude.cpp`. Before takeoff, with zero throttle, relative altitude under 5 m, baro climb rate under 0.5 m/s and groundspeed under 3 m/s, it zeroes the roll/pitch/yaw integrators. Handling the airplane makes the baro climb rate cross 0.5 m/s, so the pitch I-term builds and resets over and over. MANUAL doesn't use the controller, so it holds steady.
- **Not a flight issue:** it is designed to stop integrator wind-up before takeoff.

## Change made (with Mike's OK)

- **RLL_RATE_FF 0.345 → 0.5**, read back OK (`param-change-rll-ff.txt`).
- **PTCH_RATE_FF 0.345 → 0.5**, read back OK (`param-change-ptch-ff.txt`). Mike reported pitch is just as soft as roll: on 11-03 he could not pull out of a slight dive in AUTOTUNE and had to switch to MANUAL.
- **To revert:** set both back to 0.345 (backup: `params-before-autotune-flight2.json`).
- **STAB_PITCH_DOWN=2:** adds up to 2° nose-down when throttle is low in FBWA-type modes. Keep cruise throttle in AUTOTUNE.

## Notes

- **Airspeed with no sensor or GPS:**
  - The controllers use (AIRSPEED_MIN + AIRSPEED_MAX)/2 = 15.5 m/s. Autotune only runs above AIRSPEED_MIN 9, so it does run.
  - The speed scaler, once armed, is sqrt(45 / throttle%), clamped 0.6–1.67.
- **Arming:** the ARM button works only in MANUAL/FBWA, so arm in MANUAL.

## 2026-11-05 readback after three AUTOTUNE flights

- Full parameter set read over USB (869/869): `ArduPilot-PCB/bringup-ascend-rev2/2026-11-05/params-after-autotune-flights.json`, compared with `2026-11-04/params-before-autotune-flight2.json`.
- **AUTOTUNE saved nothing.** RLL_/PTCH_RATE P/I/D are still stock (roll P 0.08, I 0.15; pitch P 0.04, I 0.15, D 0). FF is still exactly 0.5, the value set by hand on 11-04. RLL2SRV_RMAX and PTCH2SRV_RMAX_UP/DN are still 0 and TCONST 0.5. AUTOTUNE writes those when it saves, so it never got to a save.
- Other differences are not tuning: boot gyro offsets, baro ground pressure, boot/runtime counters, and EK3_IMU_MASK 3 → 1. Nov 1 also read 1, so the Nov 4 backup is the odd one. Cause unknown.
- STAT_FLTCNT and STAT_FLTTIME are still 0. With no GPS or airspeed sensor, the FC never logged a flight.
- Likely cause: ArduPlane AUTOTUNE saves every 10 s. On leaving the mode it restores the gains from about 10 s earlier. Short bursts and quick switches to MANUAL throw the work away. It also only learns from sharp, full-stick roll and pitch inputs. Asked Mike how long each AUTOTUNE stretch lasted.

## 2026-11-05 pilot report and response changes

- **Mike:** the FF 0.5 change helped roll, now about 20° of bank. Pitch is barely responsive, so his yank-and-bank turns don't work. AUTOTUNE "level" holds a slight right roll, which hurts left turns. AUTOTUNE stretches are still short because he can't turn in it. He adjusted Tx trims at the end of the last flight; the result is untested.
- **Found in source** (`libraries/APM_Control/AP_AutoTune.cpp`):
  - On entry, AUTOTUNE starts from the TCONST params and moves tau 15% per step toward the AUTOTUNE_LEVEL target. Pitch uses 1.5× tau.
  - At level 6 the targets are roll 0.5 and **pitch 0.75**, so AUTOTUNE softened pitch from 0.5 during flight. RMAX starts at 75 when it is 0.
  - Each mode exit restores the old values.
- **Changes** (Mike asked for them; read back OK in `ArduPilot-PCB/bringup-ascend-rev2/2026-11-05/param-change-autotune-response.txt`):
  - AUTOTUNE_LEVEL 6 → 7 (targets: roll tau 0.3, pitch 0.45, rmax 90)
  - RLL2SRV_TCONST 0.5 → 0.3
  - PTCH2SRV_TCONST 0.5 → 0.45
  - PTCH_RATE_FF 0.5 → 0.7
  - Estimate: about 1.5× aileron and about 2× elevator for the same stick in AUTOTUNE.
  - **To revert:** 6 / 0.5 / 0.5 / 0.5.
- **SERVO_AUTO_TRIM can't work here.** It needs groundspeed ≥ 8 m/s, and there is no GPS.
- **Right roll, open:** Possible causes are:
  - SERVO2_TRIM 1500 is not the aileron's flying neutral. MANUAL hides this via Tx trim; AUTOTUNE ignores Tx trim.
  - The Tx trim has moved RC1 off RC1_TRIM (1522, DZ 30), which commands a bank.
  - Fix: with the Tx on and sticks centred, read RC1 and transfer the offset into SERVO2_TRIM and RC1_TRIM.
  - At the 11-05 readback the board read roll 8.2° (Tx off). How it was sitting is unknown.

## 2026-11-05 trim transfer (Tx trim → FC), with Mike's go

- **Centre stick, by switch position:**
  - AUTOTUNE: Tx sends RC1 1487, RC2 1348, RC4 1451.
  - MANUAL: Tx sends RC1 1495, RC2 1347, RC4 1450. Servo outputs SRV2 1478, SRV3 1494, SRV4 1500.
  - The Tx mode rates change the aileron centre by 8 µs between positions.
  - Files: `2026-11-05/trim-center-manual.txt`.
- **Written and read back** (`2026-11-05/param-change-trim-transfer.txt`):
  - SERVO2_TRIM 1500 → 1478, RC1_TRIM 1522 → 1495
  - SERVO3_TRIM 1500 → 1494, RC2_TRIM 1353 → 1347
  - Rudder left as is.
  - MANUAL centre outputs verified unchanged (`trim-after-manual.txt`).
  - **To revert:** 1500 / 1522 / 1500 / 1353.
- **Right roll explained:** Mike's Tx carries about 22 µs of left-aileron trim. AUTOTUNE ignored it (SERVO2_TRIM 1500, offset inside RC1_DZ 30), hence the right roll.
- **Mike:** keep the current Tx trims and don't re-trim. Mistaken "unbound" scare: Mike had picked up the wrong Tx. No changes were made to either Tx.
- AUTOTUNE check (`trim-after-autotune.txt`): RC1 1487 (8 µs from new trim, inside DZ 30, so zero bank command) and RC2 1347–1348. Verified.

## 2026-11-06 readback after Mike's 11-05/11-06 AUTOTUNE flights

- Full read, 869/869: `ArduPilot-PCB/bringup-ascend-rev2/2026-11-06/params-after-autotune-flights.json`. Port is now `/dev/cu.usbmodem101`. QGroundControl had it open; Mike closed it.
- **AUTOTUNE saved pitch:**
  - PTCH_RATE_FF 0.7 → 0.632
  - PTCH_RATE_P 0.04 → 0.074
  - PTCH_RATE_I 0.15 → 0.632
  - PTCH_RATE_D 0 → 0.0021
  - PTCH_RATE_FLTD 12 → 10, FLTT 3 → 3.54
  - PTCH2SRV_RMAX_UP/DN 0 → 90
  - PTCH2SRV_TCONST stays 0.45 (the level-7 target).
- **Roll:** only RLL2SRV_RMAX 0 → 90 was saved. RLL_RATE_FF 0.5, P 0.08, I 0.15, D 0 and TCONST 0.3 are unchanged, so roll gains were not learned.
- **Not tuning:**
  - MAV1_ADSB 5 → 10 and MAV1_RAW_CTRL 1 → 10 (stream rates; probably QGroundControl).
  - Gyro offsets, baro ground pressure and the counters, as usual.
- Trims and AUTOTUNE_LEVEL are unchanged from 11-05.

## 2026-11-06 integrator lock found; level recalibrated

- **Mike's report:**
  - Still hard to stay in AUTOTUNE. Pitch is still too conservative.
  - Roll is equal left/right, but "level" is rolled slightly right, so left stick only levels it. He used rudder to turn.
  - He wants an accurate level calibration and more roll and pitch movement.
- **Root cause found** (`libraries/APM_Control/AP_FW_Controller.cpp`, `_get_rate_out`):
  - With no airspeed sensor and no GPS (AHRS_EKF_TYPE 0, DCM), `airspeed_EAS()` returns false. `get_airspeed()` then returns 0, so `is_underspeed()` is always true and the roll, pitch and yaw integrators stay locked at 0 in flight.
  - Steady offsets are never trimmed out, and AUTOTUNE's saved PTCH_RATE_I does nothing.
  - No parameter can fix it: 0 <= AIRSPEED_MIN is always true.
  - Proposed firmware fix: fall back to AIRSPEED_CRUISE when there is no estimate. Awaiting Mike's decision.
- **Level calibration** (MAV_CMD_PREFLIGHT_CALIBRATION param5=2, ACK accepted; `2026-11-06/levelcal.txt`):
  - Mike set the airplane level.
  - Before: steady roll −0.80°, pitch +0.88° (`levelcheck-before-2.txt`).
  - AHRS_TRIM_X 0.0058 → −0.0078, AHRS_TRIM_Y −0.0257 → −0.0098.
  - After: roll −0.08°, pitch −0.22° (`levelcheck-after.txt`).
  - The first sample run (`levelcheck-before.txt`) included movement; ignore it.
- **Proposed, not done:** ROLL_LIMIT_DEG 45 → 55, PTCH_LIM_MAX_DEG 20 → 30. Hold AUTOTUNE_LEVEL at 7.
- **Correction:** only ROLL is locked.
  - AP_PitchController::get_airspeed already falls back to (MIN+MAX)/2 = 15.5, and pitch underspeed is < 0.5×MIN. So the pitch I-term works and AUTOTUNE's PTCH_RATE_I is active.
  - Yaw rate controller uses 0, but YAW_RATE_ENABLE=0, so it is unused.
- **Mike approved both fixes:**
  - ROLL_LIMIT_DEG 45 → 55 and PTCH_LIM_MAX_DEG 20 → 30, read back OK (`2026-11-06/param-change-limits.txt`).
  - Roll fix in ardupilot `libraries/APM_Control/AP_RollController.cpp` `get_airspeed()`: no estimate → 0.5×(AIRSPEED_MIN + AIRSPEED_MAX), same as pitch. Uncommitted on `borealis-v92-bringup`.
- **Built ASCENDFCRev2:** apj sha256 b7eb5039…4214, board_id 65093, base 2719570b. The pre-existing uncommitted BOREALIS RC-bench edits are gated by HAL_BOREALIS_RC_BENCH_TEST, so they are not in this build.
- **Backup before flashing:** `2026-11-06/params-before-roll-integrator-flash.json`. Flash awaiting Mike's go.
- **Flashed 2026-11-06** with `ardupilot_uploader.py` (board-ID check, no --force), because `firmware_updater.py` needs `certifi`, which the ardupilot venv lacks.
  - Board fe45 (65093). Program and verify 100%. Log: `2026-11-06/flash-roll-integrator.log`; it contains NULs, so read it with `tr '\0' ' '`.
  - The first upload's output was hidden by a filter. STAT_BOOTCNT +2 suggests it also flashed the same image; harmless.
  - Image copy: `2026-11-06/arduplane-roll-integrator-fix.apj` (+ .sha256).
- **After the flash:**
  - All 869 params kept. Only gyro offsets, baro ground pressure and counters changed.
  - Pre-arm healthy, no unhealthy sensors (`2026-11-06/prearm-after-flash.txt`).
  - RC live at the new trims.
- **Next:** Mike flies AUTOTUNE. Watch for roll holding level hands-off, more bank (55) and more pitch (30). Then read back the AUTOTUNE roll gains. Commit the roll fix after it flies OK.

## 2026-11-07 AUTOTUNE "snaps right and locks 15–20° right"

- **Mike:** after the roll-integrator flash, it is the same or worse. Entering AUTOTUNE snaps right and holds a stable 15–20° right bank. Left stick reaches only level or slightly left. MANUAL flies fine. He flies mostly **left** circuits.
- The board had rebooted (uptime 135 s), so there is no flight data. Bench: VIBE 0.03/0.03/0.09, clip 0.
- **Ruled out:**
  - DCM turn drift as the cause of the *snap*: after left circuits it would snap left.
  - Integrator wind-up in MANUAL: ModeManual::run() calls reset_controllers() every loop.
- **Explained:** the "lock". DCM no-GPS branch (`AP_AHRS_DCM::drift_correction`) uses `_last_airspeed_TAS` = 0, so there is no centripetal correction. A steady coordinated turn becomes "level", which is a neutral-stability trap.
- **Still open:** the initial right snap. Suspect vibration-induced accel bias with the motor running. A prop-off/prop-on bench motor test is proposed.
- **Fix 2, approved by Mike** (uncommitted on `borealis-v92-bringup`, built, NOT yet flashed). apj sha256 20378f90…89fb.
  - DCM: when `AP_AHRS_DCM_NO_GPS_ASSUMED_TAS` is defined, there is no airspeed sensor, the vehicle is fly_forward and it is armed, use that TAS for the centripetal correction. Reset `_last_velocity` when the assumption toggles.
  - The Rev.2 hwdef defines 12.0f.
  - Caveat: armed on the ground, yawing the airplane by hand creates false corrections.
- Mike's new PCB with the GPS antenna fix is on order. That is the long-term fix.
- **Prop-on motor test** (secured, MANUAL, armed at 4.7 s; `ArduPilot-PCB/bringup-ascend-rev2/2026-11-07/vibetest-prop-on.{txt,csv}`):
  - The roll estimate drifted from −2.3° to about 0° at ~50% throttle and to +3.5° at full.
  - When the motor stopped, the accel went back instantly while the estimate took ~40 s to decay. So it was an estimate error, not real motion.
  - **Sign:** "thinks rolled right", which would make AUTOTUNE roll left. Magnitude a few degrees. **Not the cause of the right snap.**
  - Vibration at full throttle is about 10/24/28 m/s² (x/y/z), with no clipping. Worth reducing later (prop balance, mounting).
- **Rudder ruled out:** YAW2SRV_DAMP=0, so the yaw controller returns 0. Rudder = pilot + KFF_RDDRMIX 0.5 × aileron; the mix direction was verified on 11-04.
- **Next proposal:** flash fix 2, then a diagnostic flight.
  - Straight and level in MANUAL for 15 s, then AUTOTUNE hands off. Note whether it snaps right immediately or rolls right gradually.
  - Repeat at idle throttle in a glide.
- **Flashed fix 2 on 2026-11-07** (DCM assumed TAS 12 m/s while armed, no GPS/airspeed). Board fe45; erase, program and verify 100%.
  - Image: `2026-11-07/arduplane-dcm-assumed-tas.apj` (sha256 20378f90…). Log: `2026-11-07/flash-dcm-fix.log`.
  - All 869 params kept: only gyro offsets, baro and counters changed (backup `2026-11-07/params-before-dcm-fix-flash.json`).
  - Pre-arm healthy, RC live.
  - Both firmware fixes are still uncommitted on ardupilot `borealis-v92-bringup`.
- **Next:** the diagnostic flight above. Ask whether the snap is immediate or gradual, whether it recovers, and whether gliding is any different.
