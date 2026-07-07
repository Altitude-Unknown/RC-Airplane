# Rx V4 Autopilot Experiment Notes

Date: 2026-06-30

## Goal

Use the flight-proven RC link as the base for an experimental receiver that can:

- auto-level the airplane when aileron and elevator sticks are released
- later add pressure-sensor altitude hold on the Rx V4 PCB

Pressure sensor from schematic:

- `U6 = MS5607-02BA03`

The proven receiver remains in:

- `rx_firmware/rx_firmware.ino`

The experimental receiver for this work is:

- `rx_V4__firmware/rx_V4__firmware.ino`

## What Is In The Experimental Sketch

- Same LoRa receive, bind, arming, and staged failsafe structure as the proven receiver
- LSM6DS IMU bring-up over I2C
- Guarded gyro/accel roll/pitch estimator for autolevel
- Preflight level capture after arming, throttle low, sticks centered, and IMU steady
- Stick-release detection using captured transmitter aileron/elevator neutral
- Autolevel correction mixed into aileron and elevator outputs
- Pressure-sensor placeholder for `MS5607-02BA03`:
  - probes `0x76` and `0x77`
  - reports whether a baro device is seen
  - does not yet implement altitude calculation because we still need to confirm the live interface and reading path on hardware

## Current State As Of 2026-07-05 Night

The latest flashed Rx V4 experimental build is on:

- branch: `feature/autolevel-altitude-hold`
- commit: `b7358f4 Tune Rx V4 experimental autolevel`
- sketch: `rx_V4__firmware/rx_V4__firmware.ino`

Important: this work intentionally stays in `rx_V4__firmware`. The proven/older receiver sketch remains in `rx_firmware/rx_firmware.ino`.

Bench status:

- Aileron autolevel correction looked good after switching away from the bad roll complementary-filter/rate path.
- Elevator autolevel correction looked good after applying guarded pitch fusion and direct pitch-angle correction.
- Wrong-way aileron twitch and hard opposite correction at center disappeared during bench testing.
- This is still experimental flight-test firmware, not a proven flight-ready autopilot.

## Current Autolevel Logic

Autolevel becomes eligible only when all of these are true:

- receiver is armed
- link is fresh
- not in bind mode
- not in ESC mode
- IMU is detected and sampling
- transmitter neutral has been captured after arming
- no launch lockout is active (`launchAutolevelLockoutMs = 0` for the current test build)
- aileron and elevator sticks stay near captured neutral for `1500 ms`

Preflight neutral/level capture happens after arming when all of these are true:

- throttle is low
- link is fresh
- aileron/elevator sticks are near center
- IMU attitude is initialized
- gyro roll/pitch rates are below `8 deg/s`
- current attitude is within `45 deg` of the saved Rx V4 calibration
- the airplane remains steady through the `1000 ms` capture window

The capture stores:

- transmitter aileron neutral
- transmitter elevator neutral
- current roll attitude as the level roll target
- current pitch attitude as the level pitch target

Power-on attitude does not define level. If the battery is plugged in while the airplane is held at an odd angle, that angle is ignored. The airplane must be placed or held in the intended level-flight attitude during the post-arm capture.

When active:

- rudder stays manual
- aileron gets direct roll-angle correction
- elevator gets direct pitch-angle correction
- throttle stays manual unless altitude hold is later enabled with a working baro driver
- moving aileron or elevator outside the `35 us` neutral deadband immediately drops back to manual control

## Important Tuning Values

Latest bench-tuned values:

- stick deadband: `35 us`
- stick-release engage delay: `1500 ms`
- neutral/level capture hold: `1000 ms`
- launch autolevel lockout: `0 ms`
- roll angle gain: `9 us/deg`
- roll rate damping: `0 us/(deg/s)` currently disabled
- max aileron correction: `220 us`
- pitch angle gain: `7 us/deg`
- max elevator correction: `180 us`
- guarded roll/pitch fusion accel gain: `0.30`
- guarded fusion agreement threshold: `0.15 deg`

These looked good on the bench, but they still need cautious flight validation on the real airframe.

## Known Unknowns For Tomorrow

1. Flight-test behavior is still unknown under real acceleration, turbulence, and turns.
2. Need to confirm how the `MS5607-02BA03` is wired on the live board and whether it responds on the expected bus/address.
3. Baro driver and altitude hold are not active yet.
4. Surface correction directions looked good on the bench, but must be rechecked before every flight test.

## Tomorrow's Bench Test Order

1. Flash `rx_V4__firmware`
2. Open serial monitor at `115200`
3. Confirm startup prints:
   - `RX V4 autolevel experiment ready`
   - IMU detected address
   - whether a baro device is seen on `0x76` or `0x77`
4. Put the airplane in intended level-flight attitude before post-arm capture
5. Arm with throttle low and transmitter sticks centered
6. Wait for neutral/level capture debug:
   - `AP neutral captured`
   - captured `calTargetRoll` / `calTargetPitch`
7. Move the receiver board/airplane by hand and verify:
   - `roll` and `pitch` change sensibly
   - signs match real board motion
8. Let go of aileron/elevator sticks and watch:
   - mode change from `MANUAL` to `LEVEL`
   - correction values become non-zero when the board is tilted
9. Touch aileron/elevator sticks and confirm immediate manual override
10. Confirm servo directions are sensible before any flight test

## Before Any Flight

- confirm surface correction direction with propeller removed
- confirm no oscillation on the bench
- reduce gains or disable autolevel if signs are wrong
- leave altitude hold disabled until the pressure sensor driver is verified

## 2026-07-02 Field Test Follow-Up

The first launch test showed that stick-release autolevel can engage during the
hand-launch phase before the pilot has both hands back on the transmitter. That
is not acceptable for early testing.

Changes made after the crash:

- Autolevel now has a launch lockout after throttle-up.
- Sticks must remain centered longer before level mode can engage.
- The level controller now commands a limited target roll/pitch rate from angle
  error, then uses gyro-rate error for servo correction. This is closer to the
  attitude-to-rate structure used by mature fixed-wing autopilots.
- Initial correction limits were reduced for safer bench and glide testing.

Next test should be manual launch/climb first, then hands-off level testing only
after the launch lockout has expired and the airplane has enough altitude for a
manual recovery.

## 2026-07-05 Rx V4 IMU Calibration Captures

Test sketch:

- `PCB/RxV4/IMU_Calibration_Readout/IMU_Calibration_Readout.ino`

Hardware:

- Rx V4 receiver on `/dev/cu.usbmodem1101`
- Target board: `AltitudeUnknown:samd:altitude_rc_rx_m0`
- LSM6DS read directly over I2C at 115200 baud

Captured averaged poses:

```text
CAL LEVEL_FLIGHT samples=400 raw_gxyz=74.83,-177.03,-60.27 raw_axyz=-1046.66,902.01,-5018.19 gyro_dps=0.6548,-1.5490,-0.5274 accel_g=-0.0638,0.0550,-0.3061 angles_deg roll=169.81 pitch=11.60 accel_mag_g=0.3175
CAL PITCH_PLUS_30 samples=400 raw_gxyz=70.83,-177.64,-47.53 raw_axyz=-4103.31,788.64,-3986.72 gyro_dps=0.6198,-1.5543,-0.4159 accel_g=-0.2503,0.0481,-0.2432 angles_deg roll=168.81 pitch=45.28 accel_mag_g=0.3523
CAL PITCH_MINUS_30 samples=400 raw_gxyz=68.93,-190.98,-35.28 raw_axyz=4216.00,1254.03,-3890.54 gyro_dps=0.6032,-1.6710,-0.3087 accel_g=0.2572,0.0765,-0.2373 angles_deg roll=162.13 pitch=-45.89 accel_mag_g=0.3582
CAL ROLL_PLUS_30_RIGHT samples=400 raw_gxyz=9.69,-200.37,-66.10 raw_axyz=836.56,5389.88,-3157.15 gyro_dps=0.0848,-1.7532,-0.5783 accel_g=0.0510,0.3288,-0.1926 angles_deg roll=120.36 pitch=-7.63 accel_mag_g=0.3844
CAL ROLL_MINUS_30_LEFT samples=400 raw_gxyz=77.42,-157.21,-45.68 raw_axyz=-127.16,-3918.76,-4098.82 gyro_dps=0.6774,-1.3756,-0.3997 accel_g=-0.0078,-0.2390,-0.2500 angles_deg roll=-136.29 pitch=1.28 accel_mag_g=0.3460
```

Interpretation relative to the level-flight reference:

- Pitch up is positive: `45.28 - 11.60 = +33.68 deg`.
- Pitch down is negative: `-45.89 - 11.60 = -57.49 deg`; this capture was likely steeper than the intended 30 deg.
- Right roll is negative: `120.36 - 169.81 = -49.45 deg`; this capture was likely steeper than the intended 30 deg.
- Left roll is positive after wrap normalization: `-136.29 - 169.81 = +53.90 deg`; this capture was likely steeper than the intended 30 deg.
- Static gyro bias near level was approximately `gx=+0.655 dps`, `gy=-1.549 dps`, `gz=-0.527 dps`.

Follow-up:

- The raw axis ratios are useful for orientation/sign calibration, but the printed `accel_mag_g` is only around `0.32-0.38 g` with the current `0.000061 g/LSB` scale. Recheck the exact LSM6DS variant, full-scale setting, and sensitivity before trusting absolute acceleration magnitude.
- Use level-flight offsets of approximately `roll=169.81 deg`, `pitch=11.60 deg` for this board orientation if keeping the current angle formula.
- For autopilot signs with the current formula: right roll is negative, left roll is positive, pitch up is positive, pitch down is negative.

Implementation update:

- `rx_V4__firmware/rx_V4__firmware.ino` now uses the calibrated level target `roll=169.81 deg`, `pitch=11.60 deg`.
- Stick-neutral capture now records transmitter aileron/elevator centers only; it no longer replaces the level attitude target with whatever attitude the airplane is in during capture.
- Controller-relative attitude convention is now right roll positive and pitch up positive.
- After flashing, serial debug near level showed `target=169.8,11.6` and relative attitude near zero: `rel=-0.1,-0.6`.
- Bench surface-direction test is still required with prop removed before any flight attempt.
- First bench surface-direction check showed aileron correction was reversed. `AP_AILERON_CORRECTION_SIGN` was changed from `-1.0` to `+1.0` and reflashed.
- Aileron correction then showed a step/center/step waggle instead of a smooth proportional response. Roll loop was softened for bench testing: slower time constant, lower max roll rate, lower rate gain, lower max correction, and smaller slew/smoothing steps.
- Softer roll tuning was worse and still showed the transient problem. Likely cause: gyro-rate damping can briefly command opposite correction during hand movement. Roll/aileron path was changed to direct angle-proportional correction only for bench testing: `rollAngleKpUsPerDeg=5.0`, `rollMaxCorrectionUs=140`, `rollCorrectionAlpha=0.65`, `rollMaxCorrectionStepUs=25`, and `rollRateKpUsPerDps=0.0`.
- Direct angle-proportional roll improved the response, but occasional initial wrong-way swing remained. Likely cause moved to the complementary filter itself: roll gyro integration sign was fighting the accel-derived roll angle during motion. `IMU_ROLL_RATE_SIGN` was changed from `+1.0` to `-1.0` and reflashed.
- Next step toward Pixhawk-like behavior: restore roll damping as an explicit angle-plus-rate controller instead of pure angle-P. Roll command is now `rollAngleKpUsPerDeg * rollErr - rollRateKdUsPerDps * effectiveRollRateDps`, with terms reported separately in serial debug as `rollTerms=angle,damping`. Debug period was reduced to `50 ms` so bench motion can be diagnosed from `rel`, `relRate`, `err`, `targetCorr`, and `rollTerms`.
- Bench response with angle-plus-rate damping was directionally good but slow to start. Roll output response was increased: `rollAngleKpUsPerDeg=7.0`, `rollRateKdUsPerDps=2.2`, `rollMaxCorrectionUs=180`, `rollCorrectionAlpha=0.90`, and `rollMaxCorrectionStepUs=45`.
- Follow-up bench response was faster but still delayed, and correction removal at level lagged. Roll response/release was increased again: `rollAngleKpUsPerDeg=9.0`, `rollRateKdUsPerDps=2.8`, `rollMaxCorrectionUs=220`, `rollCorrectionAlpha=1.0`, and `rollMaxCorrectionStepUs=90`.
- Remaining bench issue: ailerons can still briefly move the wrong way before applying the correct correction. One likely cause is stale opposite-sign output surviving through the slew limiter as the desired correction changes sign. Aileron output now uses `responsiveCorrection()`: if previous and target aileron corrections have opposite signs, it jumps directly to the new target; otherwise it still uses normal slew limiting. Elevator remains slew-limited.
- Follow-up bench issue persisted as a slight wrong-way correction. Two more stale-output sources were removed for bench testing: the armed loop now recalculates `updateAutopilotState()` before applying desired servo outputs, and aileron correction is now direct-to-target with no roll slew/smoothing memory. This should make any remaining wrong-way aileron twitch come from the attitude/rate estimate or sign math, not leftover servo correction.
- New bench observation: a slight wrong-way correction still appears, and returning to center produces a hard opposite correction stop. That points to the roll-rate damping term fighting the aircraft while it is already rolling back toward level. Roll damping is now gated so it only applies when roll angle and roll rate have the same sign, meaning the aircraft is moving farther away from level. While returning toward level, aileron correction is angle-only.
- Gated damping did not remove either symptom. Next bench isolation build disables roll-rate damping entirely and sets roll attitude to accel-only with `AP_BENCH_ACCEL_ONLY_ROLL=true`. This is not flight-ready; it is intended to prove whether the remaining wrong-way twitch comes from gyro/complementary-filter behavior rather than surface direction, stale output, or angle-proportional correction.
- Bench result from accel-only roll build: both the wrong-way aileron twitch and the hard opposite correction at center disappeared. Roll correction looked very good on the bench. This strongly points to the roll gyro/complementary-filter/rate path as the source of the previous bad transient behavior. Do not treat this as fully flight-ready yet: accel-only roll can be fooled by real flight acceleration, turbulence, and coordinated turns, so the next flight-quality step is a corrected attitude estimator rather than simply keeping accel-only roll forever.
- Next roll-estimator step: `AP_BENCH_ACCEL_ONLY_ROLL` is back to `false`, but roll now uses guarded gyro fusion. The gyro is allowed to predict roll only when its short-term delta agrees with the accel-derived roll delta; if they disagree, that frame falls back to accel-only roll. Roll-rate damping remains disabled. If this keeps the good bench behavior, apply the same estimator cleanup to pitch/elevator next.
- Bench result from guarded roll fusion: aileron response still looked good. The guarded fusion behavior is now shared by roll and pitch via `guardedFusionAngle()`, and pitch uses `AP_GUARDED_PITCH_FUSION=true` with the same conservative accel gain and agreement threshold. Elevator still needs bench validation after this flash.
- Elevator bench result after guarded pitch fusion: direction looked okay, but response was slower than the ailerons. Elevator control was changed to direct pitch-angle correction like the aileron path: `pitchAngleKpUsPerDeg=7.0`, `pitchMaxCorrectionUs=180`, no pitch-rate command, and no elevator slew/smoothing memory for this bench pass.
- Bench result from direct pitch-angle elevator build: elevator response now looks good. Roll and pitch both use guarded gyro/accel fusion, and both aileron and elevator corrections are direct angle-proportional outputs with no output slew memory for the current bench-tuned build.
- Flight-test prep: launch autolevel lockout was changed from `8000 ms` to `0 ms` so autolevel can be active for takeoff when sticks are centered. Manual override is still immediate: moving aileron or elevator outside the neutral deadband drops the controller back to manual.
- Preflight level capture update: the fixed Rx V4 calibration is no longer used as the active level target every time. After arming, with throttle low, sticks centered, and the IMU steady for the capture window, the firmware now captures the current roll/pitch attitude as the level target along with transmitter neutral. This means the airplane must be sitting or held in the intended level-flight attitude during arming/capture. Power-on while plugging in the battery at an odd angle still does not define level.

## 2026-07-06 Flight Test Feedback

Observed in flight:

- Ground checks showed correct and smooth aileron/elevator correction direction.
- In flight the airplane tended to list left. A poor level capture or IMU calibration/estimator drift is possible.
- Main safety issue: autolevel occasionally drove or allowed a full 360 degree roll/corkscrew. Manual override was required each time.
- Takeoff was difficult with autolevel allowed to engage immediately.

Next test-build changes:

- Autolevel pilot master starts `OFF` after boot/disarm.
- Rudder trims control the autolevel pilot master:
  - left rudder trim turns autolevel `ON`
  - right rudder trim turns autolevel `OFF`
  - the transmitter sends explicit `AUTOLEVEL_ON` / `AUTOLEVEL_OFF` aux packet flags
  - the receiver no longer infers commands from rudder pulse movement
  - accepted aux commands have a short `250 ms` cooldown
  - in this test build, transmitter rudder trim buttons do not also adjust rudder subtrim
- When the pilot master is `ON`, releasing aileron/elevator sticks now engages level mode after `75 ms` instead of `1500 ms`.
- Moving aileron or elevator outside the neutral deadband still returns immediately to manual control.
- Stick-release deadband is widened to `65 us` so level mode engages more reliably when the sticks are released.
- Roll/pitch authority is increased from the very soft test build:
  - roll gain `7.5 us/deg`, max aileron correction `210 us`
  - pitch gain `6.0 us/deg`, max elevator correction `160 us`
- After throttle has been raised above launch-detect threshold, autolevel disables itself if relative attitude exceeds the test bailout limits:
  - roll greater than `55 deg`
  - pitch greater than `35 deg`
- Throttle-low bench tilts do not trigger the attitude bailout.
- Serial debug now reports `apMaster=ON/OFF`.
