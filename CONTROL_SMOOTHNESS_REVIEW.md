# Control smoothness review — 2026-09-22

## Scope and evidence

Reviewed the release transmitter (`PCB/TxV3/TxV3_Full_M0/flight_core.h`,
`tx_config.cpp`, buddy support), the legacy `tx_firmware`, production
`rx_firmware/rx_firmware.ino`, and the ESP32 buddy transport. The release workflow
builds TxV3_Full_M0 and rx_firmware, not rx_V4__firmware or rx_pixhawk_crsf.
The existing uncommitted receiver USB STATUS changes are preserved.

This is a source diagnosis, not a measurement of connected hardware. Actual
pot travel, ADC noise, installed firmware versions, packet loss, pulse widths,
and wall-clock update intervals still require bench measurements. Timing
estimates below describe normal instructor/local-stick flight, without trim
writes, USB traffic, or debug printing.

## Diagnostic report BEFORE changes

| Quantity | Current implementation / estimate |
| --- | --- |
| ADC sampling | One returned reading per stick per TX loop; approximately 70–73 readings/s/channel in normal LoRa flight, estimate, not measured. Four sequential reads, not simultaneous. |
| ADC resolution | 10 bits (0–1023), explicitly the default hardware and returned resolution in installed Adafruit SAMD 1.7.10. No firmware call selects 12 bits. |
| Stick resolution | At most 1024 raw positions; fewer if physical gimbal travel uses only part of the ADC range. No measured effective noise-free bit count available. |
| Processing rate | One normalization/model/filter calculation per packet, approximately 70–73 Hz under the same assumptions. No independent fast sampling task. |
| RF update | 13-byte packed application packet + 4 RadioHead header bytes. SF7, 500 kHz, CR4/5, CRC, explicit header, 8-symbol preamble: calculated airtime 11.584 ms. Blocking transmit wait + 2 ms delay + processing gives >13.584 ms/packet, hence <73.62 Hz even before other work. |
| Receiver processing | Polls continuously outside servo frames; processes at most one packet per loop. Accepted update rate cannot exceed incoming valid packets. Six sequential pulses block main-loop processing for 6–12 ms/frame. |
| Servo rate | Requested every 20 Arduino milliseconds (nominal 50 Hz); actual wall-clock rate is not assured because pulse generation can lose SysTick ticks. |
| Servo command resolution | Packet and desired value: 1 µs, 1000–2000 inclusive (1001 possible values). Current-output deadband requires a change strictly greater than 2 µs: minimum movement is 3 µs. |
| Filtering | TX EMA alpha=0.65, after rounding to integer microseconds, on all four channels including throttle. RX alpha=1.0 (no effective smoothing). No ADC average or adaptive filter. |
| Significant jitter | Interrupt masking and sequential servo pulses; TX trim persistence, V3 UART heartbeats, receiver USB STATUS output; asynchronous radio and servo schedules. |

The 70–73 Hz range is only a rough engineering description: the calculated
upper bound is 73.62 Hz, and blocking work can reduce the rate substantially.
The ADC core performs a discarded first conversion then a returned conversion
per analogRead; these are not two averaged samples. Raw ADC conversion speed
does not imply the firmware samples sticks at that speed.

### Stick processing and resolution

Calibration uses fixed 0/512/1023 endpoints/center. There is no input dead zone.
Normalization, cubic expo (`x*(1-e)+x^3*e`), rates, and mixing use float; the
normal path rounds once to microseconds. There is no integer `map()` bottleneck.
Subtrim uses integer microseconds; physical trim steps are intentionally 5 µs.
Endpoint clamping, reduced rates, and positive expo intentionally compress
travel near center. Negative expo can make some regions steeper. None should
be removed to improve smoothness.

At full rate with zero expo and 1000–2000 endpoints:

`<=1024 ADC positions -> float normalization/model -> <=1001 integer µs values
-> rounded TX EMA -> same uint16 packet values -> RX deadband -> manual pulses`.

The deadband is history dependent, not a fixed 334-position grid: a slow
monotonic 1 µs sweep from 1000 to 2000 yields only 334 emitted levels
(1000,1003,...,1999), roughly 8.4 bits. The packet supports 1001 levels,
roughly 10 bits. Thus the receiver deadband is the clearest avoidable
small-movement resolution loss. At higher stick speed, per-frame motion is
larger anyway. Actual angular movement also depends on servo deadband,
mechanics, power, and linkage; pulse-command resolution is not angular accuracy.

The rounded alpha=0.65 EMA still reaches a target 1 µs away; it does not get
stuck there. Its small-signal low-frequency delay is approximately
`(1-alpha)/alpha * sample_period`, about 7–8 ms at this rate. A large step is
about 96% complete after three updates. Lowering alpha adds lag and is not
the first fix. Fractional filter state could reduce rounding bias, but the
maximum improvement is small compared with the receiver deadband.

### Timing and pulse generation

Each `writePulse` disables interrupts for its entire 1000–2000 µs busy wait.
The installed SAMD core increments millis once per serviced 1 ms SysTick.
Multiple ticks while interrupts are masked collapse into one pending tick.
Therefore millis can fall behind real time; micros uses that same tick count
and does not repair multiple lost ticks. Merely replacing millis with micros
would not fix this implementation.

Across six pulses, as much as roughly 6 ms of ticks can be lost per frame
(phase and GPIO overhead matter). A commanded 20 ms period can therefore be
roughly 20–26 ms in real time (~38–50 Hz), plus other work. This is an
illustrative bound/estimate, not a measured range. Pulse widths change with
stick position, so clock error and frame interval can change with commands.
Later channels' rising edges also move when preceding channels change widths.
Radio ISR service may be delayed up to a pulse duration, and application
packet consumption waits until the full frame finishes; buffered packets may
be dropped if the consumer cannot keep up. USB service is delayed too.

Existing link/arming timing uses the affected millis clock: fresh-link 150 ms,
low-throttle arming hold 300 ms, ordinary armed throttle disarm after 1200 ms,
ESC-mode cutoff after 1000 ms, surfaces safe after 3000 ms. The comment saying
ordinary flight kills at 1000 ms is misleading: code intentionally holds
through the additional 200 ms. Real-time timeouts may run longer due to lost
ticks. This predates the proposed change and is a reason to prioritize a
separate timer-output validation effort.

Flight loop display/config work is separated into non-flight modes. Normal
debug is disabled. Buzzer scheduling is nonblocking. However, every physical
trim step synchronously saves the model: I2C FRAM takes transfer time, and the
V3 fallback writes a complete flash image. Those can cause outliers while
trimming. V3 blocking 115200-baud UART messages add approximately 0.087 ms per
character, including periodic mode/authority heartbeats. Buddy student inputs
have additional 10 ms publication/ESP-NOW schedules and UART delays; they do
not have the same latency as instructor-local inputs. Receiver STATUS is
on-demand but serial writes can block; avoid polling it during timing captures.

### Filtering, oversampling, RF, and commercial comparison

Noise cannot be inferred from source. Capture stationary center and near-end
ADC readings before adding stronger filters. Native 12-bit acquisition is
preferable to synthesizing more bits by oversampling a 10-bit conversion, but
needs consistent calibration/boot-safety scaling. Merely selecting 12 bits
with today's 1023-scale calibration would saturate controls. Twelve ADC bits
would improve representation of limited pot travel and nonlinear shaping;
the compatible packet still caps commands at 1 µs. Oversampling requires
suitable noise/dither for extra effective bits; averaging can reduce random
noise but cannot recover motion between identical quantized readings.

If noise is measured, evaluate a small fractional-state EMA on surface inputs,
with a short, time-based constant and faster response during deliberate motion.
Avoid thresholds that themselves create discontinuities. Retain throttle's
safety path. Do not add receiver interpolation now: past-to-new interpolation
adds latency, while extrapolation risks inventing commands through loss of
link. Current incoming rate already exceeds nominal servo rate. Increasing RF
rate by removing 2 ms has only limited headroom (airtime alone caps ~86 Hz)
and does not fix receiver pulse timing. Keep the current RF settings and
packet layout for this increment.

Spektrum documents 11/22 ms, 2048-step channels as a modern reference:
[Spektrum frame/resolution explanation](https://wiki.spektrumrc.com/spektrum/dx18-compatibility-mode).
This does not establish the exact settings or filtering of the user's DX6e
and receiver. It does show that ultra-fast PWM is not required to be smooth.
The custom system's minimum 3 µs steps and irregular pulse schedule are
credible explanations for the observed difference, not proof of its sole cause.
Radio definitions are also documented in the
[RadioHead RF95 reference](https://www.airspayce.com/mikem/arduino/RadioHead/classRH__RF95.html).

## Ranked software changes and incremental decision

1. **Remove surface output deadband. Implement first.** Accept every 1 µs
   aileron/elevator/rudder change at the existing output tick. No added latency,
   no prediction, no model/packet changes. Leave throttle deadband and gating
   untouched. Possible tradeoff: reveals existing input noise as servo chatter.
2. **Native 12-bit stick acquisition with correctly scaled calibration.**
   Low algorithmic latency, but must validate center, endpoints, reversing,
   boot throttle thresholds, and noise before adopting. Defer until first
   receiver comparison establishes whether more acquisition resolution helps.
3. **Timer-driven 50 Hz servo generation.** Highest likely timing benefit;
   higher implementation/validation risk. Audit timer/pin resources and
   demonstrate pulse accuracy, rollover, failsafe wall time, radio reception,
   and grounded-bind-plug handling on hardware. Do not simply enable interrupts
   inside existing delayMicroseconds calls or switch clocks to micros.
4. **Reduce persistence/UART timing outliers.** Preserve durable trim/settings
   semantics; measure FRAM versus flash stalls before changing save policy.
5. **Measured-noise-driven filtering/faster independent stick sampling.**
   Only if needed after the above. Avoid stacking extra lag on the existing EMA.
6. **RF rate increases or receiver interpolation.** Lowest priority here;
   limited evidence of benefit and more timing/safety tradeoffs.

## First-increment bench comparison

Use the existing transmitter unchanged, the same servo, supply, and linkage.
Remove the propeller for powered testing. Export settings/record bind first;
flashing can clear receiver bind storage. Compare baseline receiver with the
surface-deadband change alone. No hardware has been flashed by this review.

* Sweep surfaces very slowly through center and endpoints, then make rapid
  reversals. Check stationary chatter and exact return to trim/center.
* Verify trim, low/high rates, expo, reversing, any V-tail/elevon mixing,
  CH5/CH6, throttle boot lock and low-throttle arming.
* Switch off TX; confirm throttle shutdown and eventual surface centering.
  Check rearming and bind-plug restart behavior. Measure real elapsed times.
* With a logic analyzer/scope, record pulse widths/frame intervals at center,
  extremes, while trimming, and during buddy handoff. Compare a later channel
  with throttle and inspect RF completion/packet intervals if accessible.
* Log stationary ADC min/max/distribution in a separate non-flight diagnostic
  before deciding whether the next increment should be acquisition or filtering.

Stop after this first firmware increment for the physical comparison. Timer
and ADC redesigns are deliberately not bundled into a change whose benefit
can be isolated by updating only the receiver.

## Implementation and verification

Implemented the first increment only: surface commands copy the filtered
desired microseconds directly into current outputs in both armed and disarmed
states. The filter is still alpha=1.0. The original throttle helper/deadband,
safety state machine, pulse scheduler, RF packet, and storage remain unchanged.
This also lets safe centering and trim targets finish exactly instead of
stopping 1–2 µs short. It does not fix the timing problem described above.

* `arduino-cli compile --fqbn adafruit:samd:adafruit_feather_m0 --output-dir
  /private/tmp/rc-smoothness-rx-build rx_firmware` passed: 45,896 bytes flash.
* 27 host tests passed: new output-resolution/throttle-policy test, aircraft
  mixing, button channels, bind-plug safety, trims, reversing, GUI codecs,
  firmware updater. The new test executes the production C++ output block,
  sweeps surfaces in 1 µs steps under all arm/ESC combinations, and checks all
  1001×1001 current/target throttle combinations under each gate state.
* `git diff --check` passed. Existing receiver USB edits were retained.

These are software checks, not proof of physical pulse accuracy or flight
validation. No transmitter update is required for this increment. At the time of software verification no firmware had been flashed.
Subsequently the receiver was flashed and BOSSA verification passed. Radio
status was OK; binding was cleared and required rebinding. The pilot then
bench-tested the change and reported visibly smoother movement. Flight
validation and instrumented timing/noise measurements remain outstanding.
