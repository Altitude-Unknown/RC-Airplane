# Physical ARM button follow-up — 2026-10-10

User reports ESC beeps interpreted as calibration at boot and motor will not
run, although MANUAL/FBWA control surfaces work. Pressing the PCB ARM button
did nothing. Board is mounted in aircraft and USB/QGC currently inaccessible.
User authorized fixing the button.

Reviewed prior V2/SBUS memory and full saved parameter capture. Physical
PC10 ARMING_BUTTON was INPUT PULLUP without an action. Saved ARMING_REQUIRE=1,
BRD_SAFETY_DEFLT=0; SERVO1_FUNCTION=70, MIN/TRIM=1100, MAX=1900,
REVERSED=0. RC3_MIN/TRIM=1003, MAX=1998, REVERSED=0, DZ=30.
SBUS bridge does not implement standalone receiver ESC/arming logic.

Prepared board-specific hold-to-toggle arming through normal ArduPlane checks:
GPIO92=PC10 active-low; release after boot; hold two seconds; one attempt per
press; release at least 100 ms. Requires healthy RC no older than 300 ms,
zero calibrated throttle, not flying, and MANUAL/FBWA throughout hold.
Invalid eligibility consumes press. Existing status LED is solid armed unless
failsafe indication takes priority. No Tx/Rx changes or parameter writes.

Artifacts/instructions: ArduPilot-PCB/bringup-v2/servo-enabled/arm-button/.
Original installed firmware retained. No physical upload or motor test done.
ESC startup issue remains unresolved; enabling arming is only one part.
Unrelated pre-existing v92 bench and standalone Rx autolevel edits preserved.

Validation completed: host state-machine tests passed; BOREALISv2Servo full
hardware build passed with 1,330,632 bytes flash used. Generated GPIO map
confirms GPIO92=PC10; ELF contains Plane::update_board_arm_button. APJ board
ID 65092 and decompressed application matches BIN exactly. APJ SHA256:
1ff01b252ede5937fd487edcb386b05d4ebdd6e3e088571068ca4ad117630593.
Source snapshots, focused patch, build log and validation.json packaged in
arm-button directory. No commit/push or hardware/parameter changes performed.

## USB installation follow-up

User connected USB and authorized installation through task continuation.
Identified BOREALISv2Servo serial 2F0051000C51343034383933 on
/dev/cu.usbmodem1101, disarmed. Backed up all 869 parameters, uploaded the
prepared APJ through normal ArduPilot bootloader (board ID 65092), verified
flash and rebooted. Post-upload capture read all 869 parameters and confirmed
the aircraft configuration unchanged. Seven normal startup values changed:
boot/runtime counters, gyro offsets/calibration temperature and ground
pressure. Initial exact-parameter assertion flagged these normal changes;
reviewed them and updated capture script to distinguish configuration.
After reboot FC reported ArduPlane 4.7.1 (d276581b), disarmed, throttle
telemetry 1100 us, and "PreArm: Waiting for RC"; RC channel count was zero.
No tool sent an arm command. Button polarity/physical hold and motor behavior
remain untested. Propeller removal and valid Rx/Tx link are needed before
user bench tests. Deployment evidence stored alongside firmware.

## User physical test result

User confirms PCB button now arms/disarms and motor operates when armed.
Only power LED is visible; no indicator LEDs observed. IMU/barometer/GPS/mag
LEDs PB15/PB14/PB13/PB12 are explicitly held off in current hwdef. L3 on
PC12/GPIO90 is configured for AP_Notify; saved NTF_LED_TYPES=123079 includes
the onboard LED bit and brightness=3. Thus missing L3 indication is still
unexplained; do not claim an LED hardware fault or polarity fix without
inspection. USB no longer enumerated at this turn, so live GPIO/telemetry
checks require reconnection. User confirmation validates arm/disarm/motor,
not held-at-boot/high-throttle lockout or LED indication.

## L3 isolation test

User supplied current schematics confirming active-high L3 through R5 2.2k
from BLINK=PC12 (MCU pin80) to ground; health LEDs likewise active-high.
USB reconnected as /dev/cu.usbmodem1101. Read-only capture confirmed onboard
notification LED enabled and driver/scheduler present in installed image.
Board disarmed. Temporarily used unused RELAY1_FUNCTION=1 with PIN=90,
DEFAULT=0, INVERTED=0 and disabled only NTF_LED_TYPES onboard bit, rebooted,
then sent accepted DO_SET_RELAY high for 45 seconds. This bypasses normal
notification patterns and targets GPIO90=PC12 only. User reports L3 stayed
dark. No motor/arming commands sent.
Turned relay off, restored all original relay subparameters (-1/0/0), relay
function0 and NTF_LED_TYPES=123079, rebooted and readback-confirmed restored
function/LED settings and disarmed heartbeat. Evidence l3-test.json;
test_l3.py can repeat finite test. No new firmware flashed or LED mapping
changed. Direct pin voltage has not been measured: suspected LED circuit,
assembly or PC12 electrical output issue remains unconfirmed. Next useful
test requires meter on R5 BLINK side relative to GND during steady-on test,
then LED-side voltage/polarity/continuity checks as needed.

## Follow-up — 2026-10-18

User reports no code changes since the working configuration, but the motor no
longer arms/runs. Aileron, elevator and rudder respond normally; MANUAL/FBWA
switching works, and FBWA corrects pitch/roll motion as expected. User has repaired
L3 and now reports a slow blink. IMU and BARO health LEDs are illuminated.
The earlier damaged-L3 observation no longer describes the current hardware.

Reviewed the configured GPIO_LED_1 driver: a regular slow cycle (approximately
1.5 seconds on / 1.7 seconds off) indicates READY_TO_ARM while disarmed; solid
indicates ARMED unless a higher-priority indication is active. FAILSAFE is
approximately 0.4 seconds on/off; NOT_READY_TO_ARM has unequal pulse lengths.
The user's description alone has not established the exact pattern.

The custom button separately requires fresh healthy RC, calibrated zero throttle,
MANUAL/FBWA and not-flying status for the entire two-second hold. A release of at
least 100 ms is required after boot or an invalid/consumed press. Healthy sensor
LEDs do not establish these button conditions. Asked for L3's behavior during and
after a prop-off, idle-throttle button hold. No USB serial device was detected;
current telemetry and pre-arm reasons have not been read. No firmware, parameter,
arming, motor-output or hardware changes were made by the agent.

User confirms L3 keeps the same slow blink after the prop-off, MANUAL,
idle-throttle two-second button hold. No transition to the normal solid armed
indication was observed. Requested USB connection for telemetry, transmitter on,
throttle down, QGC closed. Saved RC3 calibration is MIN=1003, DZ=30,
REVERSED=0, so the current firmware maps input at or below 1033 us to zero
if those settings remain unchanged. Current throttle input, arming heartbeat,
button electrical state and pre-arm messages are still unknown.

## Transmitter-only diagnostic — 2026-10-18

The FC USB port is inaccessible. User instead connected the transmitter M0,
identified as Altitude RC TX M0 (VID 0x03eb / PID 0x2402), initially on
/dev/cu.usbmodem1201. An eight-second passive serial listen at 115200 baud
received zero bytes, consistent with ENABLE_TX_DEBUG=false in normal firmware.
No commands, resets, model writes or firmware uploads were sent. Source/manual
review also confirms there is no physical throttle trim on this transmitter;
the earlier generic raised-throttle-trim suggestion does not apply.

User confirmed powering off the aircraft and restarting the transmitter into
its existing AUX/trainer-at-boot simulator mode, with throttle fully down.
A temporary native IOKit HID input reader matched only that device's joystick
interface and received 519 throttle values in eight seconds. Converted back
through the firmware's HID axis mapping, idle ranged 1002.00..1004.99 us,
last 1002.99 us. The same shaped/smoothed local channel feeds USB HID and the
normal outgoing control packet before optional trainer selection. This confirms
the tested transmitter's local idle is below the saved FC threshold of 1033 us;
it does not independently measure radio delivery, FC input, button state, final
arming checks or armed status. No full-throttle movement was requested or tested.

Instructed the user to restart the transmitter normally with no buttons held and
throttle low before powering the aircraft again: simulator mode sends no LoRa
controls. Next investigation if failure persists is the FC's ARM-button signal
and remaining button/arming eligibility. Source uses PC10/GPIO92 active-low with
pull-up. Live telemetry or an electrical check is needed to distinguish them.

## FC capture: confirmed arming rejection — 2026-10-18

User made FC USB accessible. Identified the original BOREALISv2Servo serial
2F0051000C51343034383933 on /dev/cu.usbmodem1101. Read all 869 parameters and
requested pre-arm checks without writing parameters or sending arm/disarm/output
commands. Current orientation, DCM/no-GPS setup, throttle calibration, RC mapping,
SERIAL2 input protocol and throttle output function match the October 10 final
parameter-download baseline. Embedded firmware reports ArduPlane 4.7.1 d276581b.
Readback is in servo-enabled/arm-button/arming-diagnostic-2026-10-18.json.

FC was disarmed in FBWA, with healthy RC/gyro/accelerometer/barometer and the
PREARM_CHECK health bit set. Actual received throttle was 1001..1003 us over a
subsequent 90-second observation; landed_state=ON_GROUND. User repeated a physical
three-second ARM-button hold with the propeller removed. FC emitted:

    Arm: Roll (RC1) is not neutral

This proves the button attempt reached the normal arming checks. The observed
rejection is not explained by an unregistered physical button or high throttle
in this capture. FC remained disarmed throughout; no motor command was sent by
the diagnostic scripts. Observation is in button-observation-2026-10-18.json.

Received roll was approximately 1675 us; RC1_TRIM=1565 and RC1_DZ=30, so neutral
is 1535..1595 us. Pitch was about1420 matching RC2_TRIM=1420, and yaw1465..1466
matching RC4_TRIM=1466. RC_OPTIONS=32 retains throttle checking and does not set
the separate RPY-neutral-check skip bit. Source performs this neutral-input test
at the arming attempt, which explains why the periodic pre-arm/LED indication
could report ready while actual arming was refused.

Asked whether the aileron stick is physically centered/released and whether the
user adjusted aileron trim or selected a different model since the last working
motor test. Those facts are not yet confirmed. Do not change RC1_TRIM, widen its
deadzone, or skip RPY checks without identifying why the neutral input shifted.

User confirms the aileron stick is centered/released and suspects an accidental
aileron-trim press, though trim history is uncertain. Started a separate read-only
roll monitor and requested five press/release taps of aileron-left trim to verify
direction and step size before restoring the prior FC-neutral value. The normal
transmitter code adjusts that trim in 5 us steps after input shaping; no FC
calibration or arming-check parameter has been changed. Correction/re-arm result
is not yet confirmed.

The trim monitor observed roll decrease 1675 -> 1670 -> 1665 -> 1660 us,
confirming the requested aileron-left trim changes the actual FC input by -5 us
per received press/release. Another button attempt still reported Roll (RC1)
not neutral. At about 39.5 seconds, RC failsafe activated and mode changed
FBWA -> CIRCLE -> RTL. Roll simultaneously displayed1565, but this is not proof
of corrected transmitter trim: Plane::control_failsafe() explicitly substitutes
RC1/2/4 saved radio-trim values while failsafe is active. The USB serial device
then disconnected and the read-only monitor stopped with Device not configured;
partial evidence was saved to trim-observation-2026-10-18.json. Asked whether the
user intentionally disconnected/powered off hardware or whether the link/USB
loss occurred while everything remained powered. No cause of this disconnect
has been established. Further trim/arming verification needs healthy RC and
FC telemetry restored. Do not count the failsafe-centered1565 as a repair.

## User reset all TX subtrims to zero — 2026-10-18

User used the transmitter configurator to set every subtrim to zero, saved and
reset the TX/FC, but still could not arm. Both devices then enumerated on USB.
New full FC readback (after-zero-tx-subtrims-2026-10-18.json) retained all old
FC RC centers. Initial pre-arm messages were Radio failsafe on and RTL mode not
armable. Asked user to leave TX configuration mode, restore receiver power and
select MANUAL/FBWA. User confirmed responding controls; telemetry subsequently
confirmed healthy RC and transitions RTL -> MANUAL -> FBWA.

Healthy-link measurements with the centered sticks after zeroing TX subtrims:

| Channel | Received center | Saved FC center | Required TX correction |
| --- | --- | --- | --- |
| Roll / aileron | 1495 us | 1565 us | +70 us |
| Pitch / elevator | 1495 us | 1420 us | -75 us |
| Yaw / rudder | 1500..1501 us | 1466 us | -35 us |

Thus zeroing the TX alone left its input centers inconsistent with the FC's
existing radio calibration. During subsequent user control movements, throttle
went to1998..2000 us and stayed high through the end of the capture; explicitly
instructed lowering it before attempting arming. FC remained disarmed.

To retain the existing FC calibration and restore the prior matched centers,
requested active TX model subtrims Aileron+70, Elevator-75, Rudder-35, Throttle0
through the user's configurator. Aircraft power off for configuration, then
normal TX restart, receiver power restored, MANUAL/FBWA selected, centered
sticks and throttle down, propeller removed. These are calculated targets based
on live input and the verified -5 us aileron-left step; actual post-save received
centers must still be verified. No FC parameters, deadzones, safety checks,
firmware, or actuator outputs were changed by the agent. Correction completion
and successful arming remain pending.

User confirmed saving the requested TX subtrims. A fresh read-only capture
observed healthy RC with roll1558..1560, pitch1420..1421, yaw1465..1466 and
throttle1002..1003 us. All three surface inputs are now within the existing
FC neutral deadzones, and throttle is at idle. Initial failsafe-replaced samples
were excluded from this conclusion. FC remains disarmed in RTL and reports
`PreArm: RTL mode not armable`; requested a physical mode-control cycle back to
MANUAL/FBWA before the next user-operated ARM-button test. This verifies the
center correction, but successful arming/motor operation is still pending.
Evidence: restored-tx-trims-monitor-2026-10-18.json (written when capture ends).

After the user cycled mode control, fresh telemetry confirmed MANUAL, healthy
RC, neutral inputs, idle throttle and ON_GROUND. During the requested physical
three-second ARM-button hold, FC emitted `Throttle armed` and its heartbeat
changed to armed=true in MANUAL. Successful arming is now verified. No agent
arming command or FC parameter write was involved. Requested a brief user-run
propeller-off motor check followed by idle throttle and physical-button disarm;
motor response and final disarmed state remain pending. Evidence capture:
restored-trims-arm-test-2026-10-18.json.

User confirms L3 is solid and the motor spins/responds to transmitter throttle.
Thus physical arming and motor operation are restored. Explained the confirmed
neutral-input mismatch and restored TX offsets; accidental original trim change
is suspected by the user but its history is not proven. Asked user to return
throttle to idle and physically disarm; final disarmed state is not yet verified.

Final telemetry then emitted `Throttle disarmed` at capture elapsed87.57 s,
followed by heartbeat armed=false in MANUAL at87.99 s. Healthy RC and idle
throttle1002 us remained present. Final disarmed state is verified.

User also confirms physical-button disarming works. After verified disarming,
RC link was lost around109.5 s and USB disconnected around116 s; capture saved
partial events in finally. Shutdown/disconnection intent was not established;
this later loss does not change the preceding healthy-link arm/disarm evidence.

## Reusable profile arming policy — 2026-10-18

User elected RC_OPTIONS=96 and requested it in the existing setup profile.
Added it to servo-enabled/training-no-gps.parm: bit5 retains idle-throttle
checking; bit6 permits non-neutral roll/pitch/yaw during arming. Updated the
new-board checklist to explain the deliberate-stick-deflection tradeoff,
preserved custom-button requirements, full-rate calibration followed by
optional lower Manual rates, and required propeller-off verification. This
parameter does not save trims or change FBWA command interpretation. No FC
parameter was written by the agent; user plans to set it on the current FC.
Profile import and behavior at96 remain unverified on hardware. Automatic
mode-linked rates would still require transmitter code changes; manually
selecting rates and following calibration/trim procedures does not.

## Operator procedures and manual updated — 2026-10-18

Updated the main MANUAL.md with a separate custom BOREALIS V2 ArduPlane section
and linked it from the new-board checklist and physical-button instructions.
It covers RC_OPTIONS=96 and the exact QGroundControl checkboxes, retained
idle-throttle/button checks, full-rate calibration followed by optional lower
Manual rates, FBWA attitude-command behavior, and the distinction between
arming policy and saving trims. No firmware changes were made.

Verified local Plane::trim_radio() and AUX function155: in MANUAL it saves
current aileron/elevator/rudder (and supported mixed-surface) servo outputs,
then current roll/pitch/yaw RC centers. It rejects RC failsafe, non-Manual,
large roll/pitch input and excessive angular rate. Function155 does not require
GPS. It is available but not assigned or hardware validated in this session.
Documented keeping TX trims at their saved positions afterward, using a separate
unused channel and a deliberate save rather than auto-saving at mode changes.
SERVO_AUTO_TRIM remains unsuitable to assume operational without adequate
speed estimates in the present GPS-free configuration.

Rate selection is currently model-based. Lower rates reduce pilot commands
without invalidating a previously saved full-range calibration. They also
reduce FBWA's available commanded attitudes, not its corrective servo authority.
High Rates Active overrides all four channels, so throttle range must be
checked too. Automatic AUX-linked rates/trim profiles are not implemented and
would still require TX firmware changes; the no-code procedure can use one
lower rate setting in both modes with that FBWA command-range limitation.

Latest supplied QGroundControl screenshot showed RC_OPTIONS32 with idle-throttle
checked and neutral-RPY skip unchecked. User was instructed to check the latter,
confirm96 and Save. No subsequent readback/save confirmation or value96 bench
test has been received; do not claim the live FC has been changed. Previously
recorded physical arm/motor/disarm success was at32 after matching centers.

## Second AUX for deliberate trim-save — 2026-10-18

User selected the other AUX channel for trim-save. Source mapping is D7/Aux
to CH6; configure the TX per-model button assignment as Momentary, then use
RC6_OPTION155. The SBUS bridge maps the corresponding aux bit to channel6.
Latest full backup has FLTMODE_CH5, RC5_OPTION0, RC6_OPTION0; CH6 was fixed low
in earlier captures, so physical press/release delivery remains unverified.
Keep CH5 for mode selection. Confirm CH6 low/high at the FC before assigning
the save function, then bench-verify function155 with released sticks in
MANUAL. At this follow-up, USB port enumeration found no connected USB serial
devices; no live check or parameter/model write was possible. Added the planned
mapping and verification sequence to MANUAL.md without changing the reusable
profile or claiming the assignment has been applied.
