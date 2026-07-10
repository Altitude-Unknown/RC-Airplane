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

## 2026-07-07 Bench Follow-Up: Autolevel Appears To Shut Off

Bench setup:

- Rx V4 was connected on `/dev/cu.usbmodem1101` while installed in the airplane.
- The airplane was slightly nose-high to keep the USB cable connected.
- The receiver was armed, link was healthy, and neutral/level capture completed.

Live serial observation before the debug patch:

- `apMaster=OFF`, `armed=yes`, `cap=done`, and accepted packet counts were healthy.
- The displayed `rel=0.0,0.0` was misleading because the firmware zeroed relative
  attitude whenever the pilot autolevel master was OFF.
- The captured target was roughly `target=-178.1,15.1`; current pitch was roughly
  `26.8 deg`, so the static nose-high bench attitude was only about `12 deg`
  above the captured target and should not by itself trip the `35 deg` pitch
  bailout.

Debug-build update flashed after this observation:

- Serial debug now keeps live relative roll/pitch/rates populated even when
  autolevel is OFF or in MANUAL.
- Serial debug now reports `apReason=<reason>`, `launchSeen=yes/no`, and the
  raw manual channel values.
- Repeated ON/OFF commands that do not change state now print an explicit
  `AP pilot command ignored: already ...` line, so button/packet behavior is
  visible.
- Attitude bailout now prints a one-shot detail line:
  `AP attitude bailout roll=<deg> pitch=<deg> limit=<roll>,<pitch> throttle=<us>`.

Live serial observation after the debug patch:

- After upload/reset, the receiver recaptured neutral/level and stayed
  `apMaster=OFF apReason=boot launchSeen=no`.
- Relative attitude in the nose-high USB bench position was roughly
  `rel=15 deg roll, 3 deg pitch` after the new capture.
- No left-rudder-trim autolevel ON command was observed during the monitor
  window, so the live post-patch bench state was simply "booted OFF," not an
  attitude bailout.

Interpretation:

- The known behavior remains: once throttle has crossed
  `launchDetectThrottleUs = 1120`, an active autolevel session will disable the
  pilot master if relative roll exceeds `55 deg` or relative pitch exceeds
  `35 deg`.
- On the bench, this can look like autolevel "keeps shutting off" if throttle
  has been raised above the launch threshold and the airplane is then tilted
  beyond the bailout limits while sticks are released.
- If the next bench reproduction shows `apReason=attitude-bailout`, use the new
  `AP attitude bailout ...` line to decide whether the bailout threshold or the
  level capture attitude is the real problem.

Confirmed live reproduction:

- With autolevel ON at low throttle, the Rx stayed in `mode=LEVEL` while the
  airplane was tilted well beyond the nominal bailout attitude, including roll
  errors above `55 deg`. This is expected because `launchSeen=no`.
- After throttle was raised high enough to set `launchSeen=yes`, the same tilt
  behavior shut the pilot master OFF with `apReason=attitude-bailout`.
- Post-bailout serial showed `mode=MANUAL apMaster=OFF
  apReason=attitude-bailout launchSeen=yes`.
- During the reproduction, throttle reached roughly `1999 us`; observed
  post-bailout relative attitudes included roll errors beyond `55 deg` and pitch
  errors beyond `35 deg`.
- Conclusion: the field symptom is the designed post-launch attitude bailout,
  not a missing rudder-trim ON command or LoRa packet issue.

Next test-build decision:

- Automatic attitude bailout is now disabled with
  `enableAttitudeBailout=false`.
- The bailout thresholds remain in the config so the behavior can be restored
  later, but they no longer latch autolevel OFF during the next flight test.
- Pilot safety exits for this test are manual aileron/elevator override and the
  explicit right-rudder-trim autolevel OFF command.
- Serial debug now reports `bailout=off/on` next to `launchSeen`.

## 2026-07-08 Flight Follow-Up: Abrupt Roll In Autolevel

Observed in flight:

- Multiple high-altitude calm-wind tests were made with the Rx V4 autolevel
  build.
- Sometimes autolevel held roughly level for about 5 seconds before abruptly
  rolling hard, often into a barrel roll.
- Other times the hard roll began almost immediately after engagement, with a
  dive before recovery.
- After the event, the airplane usually recovered toward something close to
  level, but pitch recovery was slow because this airframe has limited elevator
  authority.

Interpretation:

- Since `enableAttitudeBailout=false` in this test build, the abrupt roll was
  probably not the intentional bailout latch.
- The leading hypothesis is the roll/pitch attitude estimator under real flight
  acceleration. The previous guarded fusion path used accelerometer angle
  directly whenever gyro and accel disagreed. That was helpful on the bench, but
  in flight the accelerometer sees gravity plus aircraft acceleration, so it can
  briefly report a false roll angle during turns, pull-ups, bumps, or vibration.
- A sudden false roll estimate would produce a sudden large aileron correction,
  matching the random-looking "fine for a few seconds, then hard roll" behavior.
- The gyro bias captured during earlier calibration was large enough to justify
  explicit startup bias measurement before trusting gyro integration.

Next test-build changes:

- Added startup gyro bias calibration from the first 120 IMU samples. Autolevel
  neutral/level capture now waits until this bias is ready.
- Added an accelerometer magnitude reference from the same startup window. The
  estimator only uses accelerometer correction when live accel magnitude is
  within `0.65x` to `1.35x` of the startup reference.
- Replaced the flight fusion fallback: when gyro and accelerometer disagree, or
  when the accelerometer angle jumps too fast, the estimator now keeps the gyro
  prediction instead of snapping to accelerometer angle.
- Reduced accelerometer correction gain to make attitude updates more
  continuous in flight: roll accel gain `0.06`, pitch accel gain `0.08`.
- Added a `1500 ms` autolevel correction ramp so servo authority fades in
  instead of stepping immediately to full correction.
- Reduced roll authority for the next test: roll gain `6.0 us/deg`, max aileron
  correction `140 us`.
- Increased pitch authority for the weak-elevator airframe: pitch gain
  `7.5 us/deg`, max elevator correction `190 us`.
- Stick-release engage delay is now `150 ms`, still quick but less hair-trigger
  than the previous `75 ms`.
- Serial debug now reports gyro-bias readiness, live/reference accel magnitude,
  and the autolevel ramp scale.

Next bench/flight checklist:

- Keep the airplane still for several seconds after receiver boot so gyro bias
  and accel reference are captured cleanly.
- Confirm serial shows `gyroBias=yes` before arming/capture.
- Recheck surface correction direction with prop removed.
- In flight, engage autolevel briefly at high altitude and be ready to override
  with aileron/elevator stick movement or right rudder trim OFF.
- If hard roll persists, next step is to log or transmit raw `roll`, `pitch`,
  `accel`, `gyro`, and `corr` around the event, and consider a stronger
  production-grade AHRS approach rather than this lightweight experimental
  estimator.

## 2026-07-08 Bench Follow-Up: Startup Bias Timing

Live bench observation after the first gyro-bias build:

- The Rx received the left-rudder-trim command correctly:
  `apMaster=ON apReason=tx-rudder-trim-left`.
- Autolevel still stayed in `mode=MANUAL` because neutral/level capture remained
  `cap=wait`.
- Serial showed corrected gyro values around `12 deg/s` on roll and pitch while
  the airplane was physically still, so the level-capture gyro gate rejected
  capture.

Root cause:

- The Rx was capturing gyro bias immediately at receiver boot.
- The real startup workflow is battery plug-in first, then the airplane is
  placed on a level surface. Therefore the first IMU samples can be taken while
  the airplane is being handled, producing a bad gyro bias.

Firmware update:

- Gyro-bias/accel-reference capture is now deferred until after the Rx has a
  fresh transmitter link.
- Bias capture only accumulates while throttle is low, aileron/elevator sticks
  are centered, raw gyro rates are below `8 deg/s`, and the accelerometer
  attitude is within the configured level-capture attitude window.
- If those conditions are not met before bias is complete, partial bias samples
  are discarded and the capture restarts later.
- Serial debug now reports `gyroBias=yes/no(samples/120)` and `biasCap=yes/no`.

Updated bench startup:

- Power the transmitter.
- Plug in the Rx battery.
- Place the airplane in intended level-flight attitude.
- Keep aileron/elevator centered and throttle low.
- Wait for `biasCap=yes`, then `gyroBias=yes`, then `cap=done`.
- Use left rudder trim to turn autolevel master ON, and release aileron/elevator
  sticks to enter `mode=LEVEL`.

## 2026-07-08 Bench Follow-Up: Tx Channel State Blocks Capture

Live bench observation after the deferred-bias build:

- The Rx was receiving valid current-format Tx packets again:
  `rx` and accepted-packet counts climbed together, with `badLen=0(0)`.
- Autolevel stayed OFF: `apMaster=OFF apReason=boot`.
- The Rx channel stream was not centered even though the airplane was armed.
  Typical line: `manual=1586,1000,1515,1003`. In the old unlabeled debug
  output this order was `rudder,aileron,elevator,throttle`.
- This means aileron was at minimum, rudder was offset from center, and elevator
  was near center. The
  Rx correctly reported `centered=no`, `gyroBias=no(0/120)`, and `biasCap=no`.

Interpretation:

- This is not an IMU/autolevel correction event yet. The controller has not
  captured gyro bias or neutral/level targets, and it has not entered LEVEL.
- The immediate items to inspect are the transmitter channel state, stored
  model trim/subtrim/calibration, and the physical aileron trim buttons. A
  stuck or held aileron trim button would explain a slow aileron walk toward an
  endpoint.
- Left rudder trim should send only the `AUTOLEVEL_ON` aux flag in the current
  Tx code; normal rudder trim changes are skipped in flight mode.
- Rx debug labels were updated to print `des(r/a/e/t)=`,
  `manual(r/a/e/t)=`, and `aux=0x..`.

## 2026-07-08 Tx Follow-Up: Stuck Aileron-Left Trim

Live Tx serial debug with sticks centered showed:

- Raw aileron ADC was centered: `raw=1020,505,519,518`, where the order is
  `throttle,aileron,elevator,rudder`.
- Outgoing aileron command was still full-left: `ail=1000`.
- Active model aileron configuration was
  `ailCfg=50,40,-500,1000-2000,norm,ar=0`, meaning aileron subtrim had been
  driven to the maximum negative value.
- Added trim-state debug confirmed the cause:
  `trims=--,--,AL,--,--,--`. The aileron-left trim input reads pressed
  continuously.

Fix applied for the bench/autolevel test build:

- Active model aileron subtrim was reset from `-500 us` to `0 us`.
- Verification before turning debug back off:
  `ail=1498 ... ailCfg=50,40,0,1000-2000,norm,ar=0`, while the stuck trim input
  still read `AL`.
- Software root cause: the normal-mode physical trim handler had hold-repeat
  behavior (`TRIM_FIRST_REPEAT_MS` / `TRIM_REPEAT_MS`), so a stuck LOW trim
  input repeatedly called `stepTrim()` until the saved subtrim hit the clamp.
- Tx firmware was changed back to press-release trim behavior: a physical trim
  changes only when a pressed button is released. A stuck/held button can no
  longer walk trim to an endpoint.
- Final Tx build was reflashed with debug disabled. The physical aileron-left
  trim switch/button still needs hardware inspection or repair.

## 2026-07-08 Bench Follow-Up: Autolevel Too Slow

Bench observation:

- After the estimator-protection build, autolevel response on the bench was far
  too slow for a reasonable flight test.
- The likely cause is that several conservative changes stacked together:
  `1500 ms` correction ramp, reduced roll authority, and very low accelerometer
  fusion gain.

Firmware retune for the next bench build:

- Removed the autolevel correction fade-in by setting `autolevelRampMs=0`.
- Restored quick stick-release engagement with `stickReleaseHoldMs=75`.
- Increased attitude fusion correction while keeping the bad-accel safeguards:
  roll accel gain `0.18`, pitch accel gain `0.20`.
- Restored roll authority to `7.5 us/deg` and `210 us` max correction.
- Increased pitch authority to `8.5 us/deg` and `220 us` max correction for the
  weak-elevator airframe.
- Kept startup gyro-bias capture, accel magnitude trust gating, accel angle jump
  rejection, and the no-snap-to-accel behavior when gyro and accel disagree.

Interpretation:

- The hard-roll mitigation should focus on estimator validity, not on making the
  controller so slow that it cannot level the airplane.
- This build should be judged first on bench response direction and speed before
  considering another flight test.

Follow-up retune after bench response was still too slow:

- Increased accel fusion gain to `0.30` on both roll and pitch.
- Increased accel angle jump allowance to `35 deg` so normal bench tilts do not
  leave the estimator mostly gyro-only.
- Increased roll authority to `11.0 us/deg` and `300 us` max correction.
- Increased pitch authority to `12.0 us/deg` and `300 us` max correction.
- This is an assertive bench-response build. Do not flight test it until surface
  direction, response speed, and manual override behavior are rechecked.

Second follow-up retune after response was still too slow:

- Increased roll authority to `16.0 us/deg` and `450 us` max correction.
- Increased pitch authority to `18.0 us/deg` and `450 us` max correction.
- This version is intended to test whether the remaining lag is mainly servo
  authority/gain rather than estimator latency.

## 2026-07-08 Controller Shape Change: Rate-Based Cascade

Reason for change:

- Bench testing showed the surfaces moved in the correct direction, but the
  response was still slower than the earlier morning build.
- Simply increasing angle-to-servo gain risks returning to hard overshoot or
  random roll behavior.
- ArduPlane/PX4-style fixed-wing controllers separate attitude demand from rate
  control: angle error asks for a target body rate, then gyro-measured rate is
  used to decide the servo output.

Clean-room firmware update:

- Replaced direct angle-error-to-servo output with a compact cascade:
  `angle error -> target deg/s -> rate error -> servo correction`.
- Roll target-rate time constant is now `0.35 s`, limited to `120 deg/s`.
- Pitch target-rate time constant is now `0.40 s`, limited to `90 deg/s`.
- Roll servo output uses target-rate feed-forward `3.0 us/(deg/s)` plus
  rate-error P `2.5 us/(deg/s)`.
- Pitch servo output uses target-rate feed-forward `3.5 us/(deg/s)` plus
  rate-error P `3.0 us/(deg/s)`.
- Servo correction limits remain `450 us`.
- No integral term was added yet; this is intentionally a small test step.
- Serial debug now reports `rollTerms(ff,p)` and `pitchTerms(ff,p)`.

Expected effect:

- Static bench tilts should still command large, immediate surface movement.
- Once the airplane is already rotating back toward level, gyro feedback should
  reduce command sooner than the previous pure angle-gain approach.
- If this still feels too slow, inspect serial `tgtRate`, `relRate`, and
  `rollTerms/pitchTerms` to tell whether the bottleneck is estimator lag,
  commanded rate limits, rate gain, or servo authority.

## 2026-07-08 Controller Follow-Up: Rate Loop Too Jittery

Bench observation:

- The rate-cascade build behaved differently, but was still not flight worthy.
- Surfaces were jittery and occasionally made a momentary wrong-direction
  correction.

Interpretation:

- The raw rate-error P term is too sensitive for the current estimator/gyro
  signal and can briefly overpower the correct feed-forward direction.
- Until gyro-rate filtering and sign validation are stronger, the rate loop
  should not be allowed to reverse the commanded correction.

Firmware update:

- Removed full bidirectional rate-error P from the servo output.
- Increased target-rate feed-forward so static bench response remains strong:
  roll `5.0 us/(deg/s)`, pitch `5.5 us/(deg/s)`.
- Kept gyro contribution only as one-way damping:
  - roll damping `1.2 us/(deg/s)` only when roll rate is moving farther from
    level
  - pitch damping `1.4 us/(deg/s)` only when pitch rate is moving farther from
    level
- The intent is to preserve fast correction direction while preventing gyro
  noise or sign ambiguity from causing wrong-way twitches.

## 2026-07-09 Bench Record: Conservative Controller and Roll-Gyro Isolation

Changes and outcomes, in order:

- Replaced the high-authority attitude-to-rate feed-forward controller with a
  direct angle-P controller. This removed a major source of abrupt and
  unpredictable correction.
- Added explicit gyro-bias capture, acceleration-magnitude gating, a
  100 ms stick-release delay, 100 ms engagement ramp, stick hysteresis,
  captured-neutral output mixing, and a 5 s post-throttle launch lockout.
- Validated on the bench: RF-loss behavior is correct; manual aileron/elevator
  movement immediately returns control to the pilot; initial surface directions
  are correct.
- Current direct angle controller: roll `12 us/deg`, pitch `9 us/deg`, angle
  deadband `0.75 deg`, roll/pitch correction limits `220/180 us`, correction
  filter alpha `0.65`, and correction slew limits `60 us` per 20 ms tick.
- A bounded gyro damping experiment was attempted. Rapid roll produced an
  initial wrong-way correction before the correct correction appeared. Damping
  is therefore disabled (`enableRateDamping=false`).
- Roll gyro/fusion isolation was then enabled with
  `AP_BENCH_ACCEL_ONLY_ROLL=true`. With accel-only roll, both slow and rapid
  bench rolls produced fast, smooth, correct-direction correction and the
  wrong-way transient disappeared.

### Current Firmware Status: Bench Only — Do Not Fly

The current Rx V4 image is a successful diagnostic build, not a flight build.
`AP_BENCH_ACCEL_ONLY_ROLL=true` means roll uses accelerometer tilt only. In
real flight, acceleration, turns, turbulence, vibration, and thrust changes
can make an accelerometer report a false gravity direction. That can command a
dangerous false bank correction.

Conclusion:

- The roll gyro axis/sign/fusion path is the remaining root-cause area.
- Do not restore gyro damping or rate feed-forward until a controlled gyro
  roll-axis/sign test establishes that the integrated gyro roll changes in the
  same direction as the accel-derived roll during rapid motion.
- Do not conduct a flight test until gyro-assisted roll fusion has been repaired
  and then revalidated on the bench. The current fast response is evidence for
  the direct angle controller and surface mapping; it is not flight clearance.

## 2026-07-09 Roll Gyro Sign Repair and Current Bench Configuration

Dedicated diagnostic:

- Added `PCB/RxV4/IMU_Rate_Axis_Test/IMU_Rate_Axis_Test.ino`, which drives no
  radio or servos and reports raw gyro axes with accel-derived roll/pitch.
- During a controlled single-axis roll movement, raw `gx` increased whenever
  the accel-derived raw roll angle increased, and reversed when the roll was
  reversed. The former receiver code used `IMU_ROLL_RATE_SIGN=-1`, so it
  integrated roll in the opposite direction during rapid motion.
- Changed `IMU_ROLL_RATE_SIGN` to `+1` and restored guarded gyro/accel roll
  fusion (`AP_BENCH_ACCEL_ONLY_ROLL=false`). Rate damping remains disabled.

Bench result after the repair:

- Untethered aileron tests were fast, smooth, and correct for both slow and
  rapid rolls, with no initial wrong-way correction.
- The 30-degree nose-high USB position is acceptable for relative tethered
  tests but must never be used to establish the intended flight-level attitude.

Current controller settings:

- roll and pitch direct angle gain: `12 us/deg`
- roll and pitch correction limit: `220 us`
- angle correction deadband: `0.75 deg`
- stick-release delay and engagement ramp: `100 ms` each
- roll/pitch accel fusion gain: `0.06/0.07`
- correction filter alpha: `0.65`; slew limit: `60 us` per 20 ms update
- rate damping: disabled

Elevator follow-up:

- Pitch authority was increased from `9 us/deg, 180 us max` to
  `12 us/deg, 220 us max` to match the now-validated aileron authority.
- This change was flashed and requires the same prop-removed pitch-direction,
  rapid-motion, and manual-override bench validation as roll.

Flight-readiness status:

- The accel-only roll diagnostic restriction is removed; gyro-assisted roll
  fusion is now active with the measured correct gyro sign.
- The system is still not flight-cleared. Complete the updated elevator bench
  test, a final untethered intended-level capture, manual override/RF-loss
  regression, and a conservative first-flight safety plan before authorizing a
  flight test.

## First Flight-Test Protocol (After Bench Validation)

This is a cautious validation flight, not proof that the feature is
production-ready.

### Preflight

- Install the receiver in its normal rigid airframe location and disconnect
  USB. The tethered nose-high position must not define the flight-level target.
- Before arming, place the airframe in its intended straight-and-level flight
  attitude with throttle low and aileron/elevator sticks centered. Keep it
  still until gyro bias and neutral/level capture complete.
- Confirm normal manual throws, current auto-level surface directions, explicit
  right-rudder-trim OFF command, immediate stick override, and staged RF-loss
  behavior.
- Pilot master starts OFF. Autonomous launch behavior is neither expected nor
  authorized.

### Flight Sequence

1. Launch, climb, and establish straight manual flight. Do not enable
   auto-level below a safe recovery altitude or during a turn.
2. Wait at least 5 s after throttle rises above launch threshold; the firmware
   deliberately holds auto-level out during this period.
3. At altitude in calm air, command pilot master ON with left rudder trim.
4. Release aileron/elevator for only 1–2 s on the first activation. Keep hands
   positioned to override immediately.
5. Override with either aileron or elevator stick at the first unexpected
   response. Use right rudder trim to disable the pilot master completely.
6. Return to manual control and land. Do not expand duration or test maneuver
   recovery on the first flight.

### Pass / Abort Criteria

- Pass: smooth, limited return toward captured attitude; no wrong-way response;
  immediate stick override; no uncommanded oscillation or roll acceleration.
- Abort the feature for the remainder of the flight: any wrong-way response,
  repeated oscillation, unexpected large correction, delayed override, or
  behavior inconsistent with the bench test. Disable with right rudder trim
  and land manually.

### Current Flight-Test Limits

- No rate damping or rate feed-forward is enabled.
- Direct angle gains are roll/pitch `12 us/deg`; correction limits are
  `220 us` each. These are test values, not final tuning.
- No altitude hold is active.
- Use calm air only. Turbulence, high-g maneuvering, steep turns, and low
  altitude are out of scope until this controlled validation flight is
  successful and reviewed.

## 2026-07-09 Pitch Gyro Sign Repair and Safety Decision

Flight-feedback diagnosis:

- Ground pitch correction direction appeared correct, but in flight the
  airplane repeatedly pitched toward inversion and then oscillated about the
  pitch axis. Changing the captured setup attitude changed whether the initial
  motion was a climb or dive but did not prevent inversion.
- This indicates a dynamic pitch-estimator sign fault, not a static surface
  direction or level-capture problem. The simple accel pitch angle also becomes
  ambiguous near vertical/inverted attitude, so auto-level must never continue
  commanding through that region.

Pitch-axis diagnostic result:

- `IMU_Rate_Axis_Test` showed raw `gy` becomes negative when accel-derived
  pitch increases and positive when it decreases.
- The firmware formerly used `IMU_PITCH_RATE_SIGN=+1`; this integrated pitch in
  the opposite direction during rapid pitch motion.
- Changed `IMU_PITCH_RATE_SIGN` to `-1` and reflashed the receiver. Roll and
  pitch gyro signs are now both backed by captured single-axis diagnostic data.

Attitude bailout:

- Re-enabled `enableAttitudeBailout=true` for validation flights. Once throttle
  has crossed launch threshold, it disables the autolevel pilot master if
  relative roll exceeds `55 deg` or relative pitch exceeds `35 deg`.
- This does not fight the safety pilot: it removes auto-level correction and
  returns to manual surface commands. It is intentionally retained for the
  first post-repair flight because the earlier failure drove toward inversion.
- Do not remove or relax this bailout until pitch has passed rapid-motion bench
  validation and a short, high-altitude flight activation has been reviewed.

Required next bench test:

- Verify slow and rapid pitch-up/pitch-down corrections, including reversal
  through level, without a wrong-way transient.
- Verify manual override and confirm the post-launch attitude bailout turns
  autolevel OFF at the configured pitch/roll limits.

## 2026-07-09 Roll Flight-Bias Reduction and Bench Pass

Flight feedback after the pitch-gyro repair showed no further pitch-to-invert
behavior, but roll consistently settled about 20--30 degrees left of level and
oscillated around that apparent setpoint. A fresh power-up and level capture
did not change it. Ground surface-direction checks were correct, and a
restrained motor run did not show a left-roll progression.

Working diagnosis:

- The aileron TX subtrim is `-10`, but receiver manual neutral is captured
  after arming. That subtrim is therefore not the primary explanation for a
  persistent 20--30 degree auto-level attitude error.
- The previous roll accelerometer fusion value (`0.06` per 50 Hz update) could
  follow apparent gravity too quickly in a turn or slip, producing a false
  roll target. The high roll proportional gain and correction limit could then
  sustain the observed oscillation.

Roll-only revision uploaded and flash-verified:

- Reduced roll accelerometer complementary correction from `0.06` to `0.012`.
  The sign-validated gyro is now the short-term roll reference; accelerometer
  data corrects only slow drift.
- Reduced roll angle gain from `12.0` to `8.5 us/deg`.
- Reduced roll correction limit from `220` to `160 us`.
- Pitch fusion/gain/limit, gyro signs, stick override, RF-loss behavior, and
  post-launch attitude bailout are unchanged.

Bench result:

- Prop-removed bench test passed: corrections were fast, smooth, and in the
  expected directions; manual control and immediate override behaved normally.

Next flight validation:

- This build remains a controlled flight-test configuration, not a general
  flight release. At safe altitude in calm air, make only brief straight-flight
  activations after the five-second launch lockout.
- Determine whether the persistent left roll and roll oscillation are reduced
  before changing any trim or adding an in-flight level offset. Abort to manual
  immediately for any wrong-way response, sustained oscillation, or large
  correction.
