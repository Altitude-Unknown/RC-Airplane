# Experimental receiver autolevel

Updated 2026-10-07. Separate from production `rx_firmware`; not packaged by the
production release workflow. This revision has passed a prop-removed bench
test, but has not completed its next flight test.

## Trainer ON / Aux OFF

Use the current production transmitter firmware and configurator. In the model's
**Button channels** settings select:

| Physical button | Model assignment | Experimental receiver action |
| --- | --- | --- |
| D10 / Trainer | Channel 5 — Momentary | Press to latch autolevel ON |
| D7 / Aux | Channel 6 — Momentary | Press to latch autolevel OFF |

Save the model, set it active, and restart the transmitter. Both assignments
must be **Momentary**, not Toggle: the receiver supplies the mode latch. The
Trainer button is reserved for autolevel on this model, so instructor/student
handoff is unavailable. Student transmitters do not provide this Trainer/CH5
command. Use the instructor/master transmitter for these tests. Rudder trims
remain ordinary trims. There is no new packet layout or transmitter code change.

- Autolevel starts OFF. Release both buttons before the first ON press.
- OFF wins when both buttons are pressed. Holding Trainer while pressing Aux,
  or while a fault occurs, cannot automatically turn leveling back on.
- Trainer ON is accepted only while armed, with gyro bias and servo-neutral
  capture complete and a fresh healthy IMU sample. A premature press is not
  queued: release and press again after capture completes.
- Normal launch lockout remains 5 seconds after throttle crosses 1120 µs.
- Stick override still returns to manual above the configured 80 µs offset
  from captured neutral. While the master is ON, centering within 35 µs for
  100 ms allows leveling again. Aux OFF keeps it OFF after centering.
- Link staleness (>150 ms) or an invalid/stale IMU drops the master OFF and
  requires release followed by another Trainer press. Link recovery does not
  silently reactivate stabilization. An IMU latched failed needs a restart.
- Post-launch attitude bailout is enabled (55° roll / 35° pitch deviation).
  A large hand-applied bench tilt can therefore latch autolevel OFF; return near
  the calibrated pose and press Trainer again before continuing a gentle test.

## Level calibration button

Calibration is intentionally required after every receiver power cycle. After
the receiver is bound, armed, stationary, and receiving centered controls at
low throttle, briefly press the receiver D10 bind button. The boot binding
gesture cannot start calibration because the button must first be released.

- Sampling begins one second after the accepted press, allowing the hand and
  airframe to settle.
- The receiver LED flashes at 10 Hz while gyro bias, physical level attitude,
  and control neutral are captured.
- The LED becomes solid when calibration is ready.
- Trainer ON is ignored until calibration finishes.

## Receiver parity and safety changes

- Explicit nonzero stored bind and matching received code are required. Bind
  mode and bind-plug restart lock reject ordinary control packets.
- Only accepted packets can build the ESC-calibration handshake or enter ESC
  mode; unrelated packets reset its streak.
- Boot arming requires completion of the 3-second guard followed by a fresh
  low-throttle hold. Final throttle selection cannot undo the guard.
- Disarmed throttle is written as exactly 1000 µs; surfaces retain 1 µs command
  resolution. Autolevel does not filter or interpolate throttle.
- Ordinary link loss retains outputs through 1200 ms, then disarms/kills
  throttle; surfaces center after 3000 ms. ESC mode cuts off after 1000 ms.
  Autolevel mode/integrators are reset separately at the 150 ms freshness limit;
  staged output hold remains in place until normal failsafe takes over.
- `STATUS` and `BOOTLOADER` USB commands are supported. STATUS identifies
  `firmware=autolevel-experimental` and reports radio, binding, mode, IMU ID,
  acceleration magnitude, bias/capture state, roll and pitch. Continuous debug
  is disabled. USB input processing is bounded and overlong commands discarded.
- SDA/D20 bind plug is detected before sensor initialization. A grounded plug
  prevents sensor-bus initialization for the entire boot, requires restart
  after binding, and never becomes a driven servo output.

## Sensor pins and timing

**D20/SDA and D21/SCL remain sensor pins.** Production's CH5/CH6 physical servo
outputs cannot coexist with the I²C sensors on these pins. This experimental
receiver therefore has four physical servo outputs; it receives CH5/CH6 over
the radio solely as mode commands. Do not attach servos to the sensor bus.

The installed SAMD Wire implementation has unbounded waits that can stall
radio/failsafe processing if the sensor bus fails. `bounded_i2c.h` replaces that
path locally with an open-drain software master. Each complete register
transaction has a 5 ms deadline (plus small cleanup/interrupt overhead),
including clock stretching; failed transactions release both pins. Servo/radio
interrupts remain enabled. No installed Arduino core or production code changes.
Bus waveform, actual sample rate, and sensor identification need hardware checks.

Outputs use the receiver's proven direct pulse generator at a nominal 50 Hz,
with 100 Hz control updates. Each pin is high with interrupts masked only for
its commanded 1000–2000 us pulse; interrupts run between channels and during
the rest of the frame. This prevents RadioHead/SPI interrupt work from delaying
an Arduino Servo-library falling edge. Five failed sensor reads latch the IMU
unavailable; sample age beyond 30 ms disables leveling sooner. Bad quaternion
normalization is rejected. Incomplete bias calibration is discarded on a
failed read.

Stationary bias capture requires 0.8–1.2 g. The installed LSM6DSO32TR identity,
scale, and orientation have been checked on hardware. Calibration captures the
installed airplane's physical level pose rather than relying on the historical
compiled offsets. Automatic aileron and elevator correction signs were reversed
after the final prop-removed direction check; manual directions remain transmitter
settings. Altitude hold is still disabled and lacks a flight pressure/altitude
driver.

## Validation and next bench test

Build:

```sh
arduino-cli compile --fqbn adafruit:samd:adafruit_feather_m0 rx_V4__firmware
python3 -m unittest test_autolevel
```

The updated sketch compiles at 62,184 bytes. The autolevel test executes the
actual sketch with mocked hardware through thirteen scenarios:
binding rejection, authenticated ESC entry, boot throttle lock, staged failsafe,
button latching/priority, 1 µs surface sweeps, interrupt-protected pulse widths,
both correction directions, IMU fault handling, stick override and bailout,
bind-plug restart, accelerometer calibration rejection, and delayed button
calibration with LED states. A separate bus test verifies register read/write,
NACK handling, stuck-clock timeout including micros rollover, and released pins
after failure.

These tests and the completed bench work do not establish aircraft stability in
flight. Before any flight evaluation, with propeller removed:

1. Preserve model settings and record binding; flashing can clear RX binding.
2. Configure both transmitter buttons as Momentary. Verify boot lock, bind,
   normal manual controls, trims/rates/reversing, and transmitter-off failsafe.
3. Read STATUS: confirm the IMU ID, approximately 1 g while stationary, correct
   roll/pitch readings, and successful bias/neutral capture.
4. Verify Trainer ON, Aux OFF, simultaneous-button OFF priority, and no
   reactivation from held buttons after faults/reconnection.
5. Verify slow and fast attitude corrections, immediate stick override, and
   post-launch attitude bailout. Confirm both correction directions on this wing.
6. Instrument output pulse widths and actual control cadence when equipment is
   available. Bench-test sensor loss and grounded SDA restart handling.

No automatic migration of settings, production integration, publication, or
general flight-clearance claim is part of this update.

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
