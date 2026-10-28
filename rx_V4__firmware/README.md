# Experimental Rx V4 stabilized attitude mode

Updated 2026-10-08. Firmware ID: `autolevel-fbwa-20261008`.
This is the first implementation following the engineering review, not a
flight-qualified release. Production `rx_firmware` and the transmitter are unchanged.

## Pilot controls

- Production Tx V3 Master, conventional TAER airplane profile only.
- CH5/Trainer **Momentary** latches stabilization ON; CH6/Aux **Momentary**
  immediately selects manual. OFF wins; release before a fresh ON press.
- **Moving the sticks no longer switches to manual.** Aileron requests up to
  ±30 degrees bank; elevator requests +20/-15 degrees pitch. Center requests
  calibrated level. Targets use a 0.12 s time constant and 90/60 deg/s slew caps.
- Rudder and throttle remain manual, subject to the existing receiver safety path.
- Retained: five-second launch lockout after throttle crosses 1120 us, and
  post-launch bailout above 55 degrees roll or 35 degrees pitch. Bailout/fault
  latches the mode OFF. These guards mean this is not full ArduPlane FBWA.
- No altitude hold, airspeed scaling, stall protection, or automatic recovery
  from an unreliable attitude solution. The MS5607 remains a probe placeholder.

## Calibration and mounting

On every power cycle: bind/link, keep throttle low and sticks centered, place
in the intended level-flight pose, release the Rx bind button after boot,
then press it once. Sampling begins after **one second**, with a fast 10 Hz
LED flash. Stay still through 120 fresh gyro/accel samples and the additional
one-second neutral hold. Solid LED means armed with calibration complete and
healthy sensing; a brief once-per-second pulse while armed means calibration
is still required. No calibration is saved across power cycles.

Capture uses averaged gravity, gyro variance and <1 degree gravity-direction
change, 0.9–1.1 g, and raw gyro magnitude <=2 deg/s per axis. Neutral sticks must
be within 80 us of center. The calibrated gravity vector defines a proper 3D
mounting rotation for both gyro and accel; PCB forward must still align with
airplane forward because gravity alone cannot establish mounting yaw. Keep
still, including in yaw; constant slow yaw cannot be separated from gyro bias
by an accelerometer alone. Recalibration resets the launch detector.

## Controller and actuator profile

The existing outer angle loop and inner PI plus feedforward rate controller
are retained. The rate loop uses measured elapsed time and 20 Hz filtered gyro
feedback. Conditional integration considers applied output, including ramp,
slew, filtering and endpoint limits. Integral is inhibited before first launch
to prevent ground/bench accumulation; low throttle after launch is treated as
possible gliding. There is no derivative term.

The receiver's `AutopilotConfig` contains independent input signs, command-angle
limits and servo endpoints. Defaults retain the previous 1000–2000 us envelope
and automatic authority of ±160 us aileron / ±220 us elevator. Both automatic
correction signs retain the user's 2026-10-07 bench reversal. **Mechanical travel
limits and input directions still require confirmation on the mounted airplane.**
The receiver does not download endpoint/reversal/mixing settings from the Tx.
Do not use this automatic mode with V-tail/elevon/mixed output channels.

## Timing and sensor health

- TC4 schedules four sequential GPIO pulses every 20 ms, with a short highest-
  priority edge ISR. No 1–2 ms interrupt-disabled busy waits remain.
- TC4 runs at 3 MHz; TC3 is avoided because installed RadioHead defines its ISR.
  A0 has no PWM mux, so the driver uses scheduled GPIO edges rather than native
  PWM on all channels. Do not add Servo/tone/analogWrite timer users here.
- `preemptible_rf95.h` changes only SPI transaction interrupt protection for
  this sketch: EIC, the only other SPI caller, is masked while TC4/SysTick run.
  No installed RadioHead files are modified. Do not add another SPI ISR or call
  radio methods from an application critical section without revisiting this.
- Timer publication stops for bind flash writes (binding is disarmed) and then
  resumes. A foreground stall >5 frames or servo edge lateness >100 us latches
  safe outputs and requires reset. This is separate from RF failsafe.
- Control remains nominal 100 Hz, with measured `micros()` elapsed time and
  overrun counters. The previous SysTick-losing pulse implementation is removed.
- IMU remains 104 Hz / ±4 g / ±250 deg/s. Explicit accel LPF2 is 26 Hz and gyro
  LPF1 is 33 Hz. Data-ready is checked before consuming each sample.
- Bus transactions retain their 5 ms deadline. No new data, implausible zero-g
  blocks, clipping, numeric errors, and sample gaps invalidate eligibility.
  Five failed reads latch the IMU unavailable (reset required).
- A sample gap >30 ms requires recalibration. Sustained gravity disagreement
  >3 seconds also disables eligibility until ground recalibration. There is no
  in-flight snap to apparent gravity. Sustained-turn accuracy is still limited
  by six-axis sensing; accelerations cannot be fully separated from gravity.

## Preserved receiver failsafe

Binding/packet validation, ESC handshake, boot throttle guard and low-throttle
arming remain. At link age >150 ms stabilization latches OFF and outputs hold.
Normal throttle cutoff/disarm is >1200 ms; ESC-mode cutoff is >1000 ms. The first
update after normal disarming selects the last manual surface values; at >3000
ms surfaces center. This subtle pre-existing transition is covered by a test.
Reconnection does not automatically re-enable stabilization or arm at high throttle.

## Diagnostics and validation

USB `STATUS` reports firmware identity, binding and calibration. `DIAG` reports
uptime, control count/max interval/overruns, servo frames/max ISR lateness/fault,
IMU sample count/age/rejections/health, requested attitude/rate, integral,
limiting and TAER outputs. These records are on demand to avoid continuous
serial load. `BOOTLOADER` publishes a safe frame before requesting reset.

```
arduino-cli compile --fqbn adafruit:samd:adafruit_feather_m0 rx_V4__firmware
python3 -m unittest test_autolevel test_servo_schedule -v
python3 tools/rx_usb_status.py /dev/cu.usbmodem101 --command DIAG --count 10
```

The host suite executes 25 actual-sketch scenarios, a bounded-I2C test, the
real portable pulse scheduler, a synchronized timer-register model, and the
RadioHead adapter's IRQ contract.
Hardware registers, GPIO waveform and aircraft dynamics are not mocked into
proof of flight stability. Before flight, check mounted directions, endpoint
travel, ±10/20/30-degree disturbances, fast/slow rotation, sticks while tilted,
release, manual escape, saturation, sensor failure and RF loss with prop removed.
Confirm timer diagnostics during RF traffic; external scope checks remain required
for electrical pulse accuracy. Stage aircraft tuning from rate feedback outward.

## Deployment record

Flashed and read-back verified, preserving bind code 7741. Live RF capture:
100 Hz control, 49.94 Hz servo frames, 82.73 fresh IMU samples/s, maximum measured
ISR lateness 4 us, zero timing overruns/faults. Physical waveform and calibrated
mounted-control validation remain outstanding. The first timer synchronization
issue was fixed and verified in the final image. Full deployment results are in
`PCB/RxV4/AUTOPILOT_EXPERIMENT_NOTES.md` and workspace `PROJECT_MEMORY.md`.

## Historical bench record (superseded by the implementation above)

## 2026-10-07 new Rx V4 bench upload

BOM confirms U4 LSM6DSO32TR and U6 MS560702BA03-50. Corrected acceleration
scale to 0.000122 g/LSB at CTRL1_XL=0x40 (+/-4 g); gyro remains 0.00875
dps/LSB (+/-250 dps). Expected identity restricted to 0x6C, although this ID
alone does not distinguish all family variants. Updated raw-sample regression
fixture to 8192 counts/g; calibration still rejects out-of-range acceleration.
Compile passed (62696 bytes); both test_autolevel suites passed, including ten
state-machine scenarios and bounded bus checks. Uploaded and flash-verified.
Live STATUS: radio=OK imu=yes who=6C accelG=0.985–0.993, armed=no,
apMaster=OFF. stored=0: receiver needs rebinding. bias=no/neutral=no expected
without accepted radio packets; calibration requires fresh link, low throttle,
centered controls, and stationary IMU. Current board USB-only, no aircraft.
Pressure passed separate diagnostic; altitude hold remains disabled.
Old airframe offsets/correction signs still require verification on this airplane.
Raw STATUS saved in PCB/RxV4/RxV4_Sensor_Diagnostic/autolevel-status-2026-10-07.txt.

## 2026-10-07 final prop-removed bench result

- After an accidental four-position TAER connector offset heated the sensors,
  a USB-only diagnostic repeatedly read the correct IMU identity/configuration
  and 0.991–0.995 g stationary magnitude. The MS5607 returned its exact earlier
  factory PROM, matching CRC4, plausible 857.24–857.32 hPa pressure, and a
  smoothly cooling 30.98–28.76 C temperature. This found no functional damage,
  but does not prove accuracy or exclude latent damage.
- The transmitter ESP role had been cleared, which forced safe Config Mode and
  disabled LoRa. Restoring the Instructor/Master role restored RF. Receiver
  binding code 7741 was then stored and ordinary packets were accepted.
- Restoring the direct interrupt-protected pulse generator removed the visible
  multi-axis twitch. The user confirmed normal manual control on all servos.
- The one-second delayed calibration, fast LED flash, and solid-ready indication
  worked on hardware. Trainer ON entered level-hold mode; an initially apparent
  failure was the configured attitude bailout after an excessive hand roll.
- Both automatic surface responses were backward on this installation. The
  aileron and elevator correction signs were reversed, reflashed, and the final
  prop-removed bench test looked correct. Manual directions were unchanged.
- A controlled test flight at the user's normal test site remains pending. Use
  brief activations at safe altitude and return to manual immediately for any
  wrong-way response, oscillation, or excessive correction.
