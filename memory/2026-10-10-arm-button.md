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
