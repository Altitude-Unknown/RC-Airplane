# BOREALIS V2 physical ARM button — updated 2026-10-18

AI-assisted firmware change for BOREALISv2Servo, board ID 65092.
PC10 (MCU pin 78) is exposed as GPIO 92 with its existing pull-up.
The momentary switch is treated as active-low. No receiver or transmitter
firmware update is needed.

## Operation after installing this firmware

Remove the propeller for initial testing. Turn on the transmitter, select
MANUAL or FBWA, and put throttle fully down. Allow startup calibration to
complete, with the button released. Hold the PCB ARM button continuously
for two seconds to request arming. Release it afterward. The existing L3
status LED is solid when armed, except when a failsafe pattern takes priority.
Hold the button again for two seconds at idle, on the ground, to disarm.

The button requires a healthy, recent RC input, zero calibrated throttle,
an on-ground state, and MANUAL or FBWA throughout the hold. An invalid
condition consumes the press; release for at least 100 ms before retrying.
A button held at power-up cannot arm until released and pressed again.
A short press does nothing. A sustained press causes at most one attempt,
including when ArduPlane rejects arming. All normal configured arming checks
still apply; this uses the same checked arming entry point as an auxiliary
RC switch. This button is not an emergency motor-stop control.

Arming failures remain available in QGroundControl messages. If the LED does
not show armed, reconnect telemetry to inspect the reason. Do not infer
arming from working control surfaces.

## Flight trims and current bench result

The [training preset](../training-no-gps.parm) now includes `RC_OPTIONS=96`:
idle-throttle checking stays enabled, while the neutral-roll/pitch/yaw arming
check is skipped. This permits arming after a transmitter trim change, including
with deliberately deflected surface-control sticks. All other configured
checks and the button's eligibility/hold requirements remain. It does not save
new trims or change FBWA command interpretation. See the [operator manual](../../../../MANUAL.md#borealis-v2-arduplane-operation)
for QGroundControl checkboxes, rate calibration and trim-saving procedures.

On 2026-10-18, a physical button attempt reached normal arming logic and was
rejected with `Arm: Roll (RC1) is not neutral`. Correcting the TX/FC center
mismatch and reselecting MANUAL after RTL allowed physical-button arming.
Telemetry recorded `Throttle armed`, armed heartbeats, then `Throttle disarmed`
and disarmed heartbeats. The user confirmed solid L3, motor response and button
disarming. These tests used `RC_OPTIONS=32`; the new value 96 and profile import
have not yet been hardware validated. Detailed evidence and diagnosis are in
[the session notes](../../../../memory/2026-10-10-arm-button.md).

## Installing

Use `arduplane.apj` in this directory with the existing USB ArduPilot uploader
or QGroundControl custom-firmware workflow once the FC USB port is accessible.
Target BOREALISv2Servo only. A bootloader replacement is unnecessary. Back up
the aircraft parameters first; preserve existing calibration, orientation,
GPS-free settings, receiver configuration and servo setup. Do not reset
parameters as part of the update.

The new image was flashed on 2026-10-10 over /dev/cu.usbmodem1101. Bootloader
board ID 65092 matched and flash verification passed. After reboot, all 869
parameters were read back; configuration was preserved. Boot/runtime counters,
gyro startup calibration and ground pressure changed normally. The board
remained disarmed and reported "PreArm: Waiting for RC" with zero active RC
channels. At that initial installation, physical button and motor testing were
pending; the later result is recorded above. The earlier
image remains in the parent directory.
Hardware checks must confirm button polarity, hold/release behavior,
rejected arming at high throttle or missing RC, LED indication, and normal
arming/disarming with the propeller removed.

This change enables the missing arming input. It does not diagnose or alter
ESC calibration, PWM endpoints, or startup pulses. The latest saved throttle
output range is 1100–1900 us; ESC initialization still needs investigation
if its tones persist after successful arming.

## Validation

The host test in `tests/board_arm_button.cpp` exercises held-at-boot lock,
two-second timing, single action, release bounce, short press, interrupted
eligibility and millisecond rollover. Build and artifact results are recorded
in `validation.json`. Physical arming/motor/disarming results are recorded
above; remaining commissioning includes high-throttle and missing-RC rejection
checks and the revised RC_OPTIONS policy.
