# V2 servo-enabled ArduPlane — 2026-10-09

Current installed image includes [live sensor-health LEDs](health-leds/README.md)
and the physical ARM-button action. Installed/flash-verified 2026-10-10;
user confirmed IMU L4 and pressure L5 illuminate. Earlier images below are
retained for continuity.

Physical ARM button update prepared on 2026-10-10:
[firmware and operating instructions](arm-button/README.md). This separate
image adds a checked two-second hold on PC10; installed and flash-verified
2026-10-10. Physical button arming and disarming were verified on 2026-10-18,
with motor operation confirmed by the user; see the linked instructions.
Earlier artifacts
below are retained.

Reusable setup: [new-board checklist](NEW_BOARD_SETUP.md) and
[GPS-free training parameter preset](training-no-gps.parm). The preset is
partial; calibration, failsafe configuration and hardware import validation
remain required.

## Three successful flights reported 2026-10-18

The pilot reports three successful flights with the custom FC, TX and RX:
smooth FBWA autolevel, satisfactory MANUAL control and repeated mode changes
without reported issues. Remaining feedback is overly wide turns and limited
pitch/roll command in FBWA. Flight aileron rate was 30%; elevator was 80%.
Reduced TX rates are a leading explanation for limited commanded attitude;
active high-rate state, current FC limits and requested angles need checking
before raising limits or changing gains. See [flight-test notes](../../../memory/2026-10-18-v2-flight-tests.md).
These are pilot-reported results; no flight logs were independently reviewed.

A later CH5-linked TX surface-rate update was installed to address limited
FBWA command range while retaining the selected MANUAL rates. The pilot reports
its bench test looks good and surface deflections in both modes look similar.
Flight testing of the rate update is pending. See [mode-rate notes](../../../memory/2026-10-18-mode-rates.md).

## 2026-10-10 GPS-free training configuration

User confirmed the reported errors cleared after setting AHRS_EKF_TYPE=0
(DCM attitude estimator) and ARMING_SKIPCHK=8 (skip GPS lock only), with
GPS1_TYPE=0 for absent GPS. Subsequent independent parameter download confirmed
all three values and AHRS_ORIENTATION=14 and ARSPD_TYPE=0. All 869 advertised
parameters downloaded with no missing indices; QGC's download also completed
after restart. See NEW_BOARD_SETUP.md and parameter-download-diagnostic.json.
No airspeed sensor is installed; advised baseline is ARSPD_TYPE=0 and
ARSPD_USE=0. These settings preserve later hardware expansion. Restore EKF3
and all arming checks when configuring GPS missions. GPS-free failsafe setup
remains pending: earlier receiver-loss testing selected RTL.

## 2026-10-10 in-airplane bench test: mounting orientation confirmed

For the user's pictured mounting (components facing up, ARM-button edge
toward the nose, servo-connector edge toward the tail), the confirmed setting
is **AHRS_ORIENTATION=14 (Yaw270Roll180)** with the current firmware's
LSM6DSO32 sensor definition using ROTATION_NONE.

- User confirmed the transmitter trainer button switches between Manual and
  FBWA, and Manual provides control of all airplane functions.
- Initial mounting produced abrupt roll indication and full aileron correction
  in either direction, while pitch responded smoothly. Physically flipping
  the PCB upside down and rotating it 90 degrees restored sensible response,
  identifying an orientation mismatch.
- AHRS_ORIENTATION=10 (Yaw90Roll180) produced smooth but reversed corrections.
  In a nose-high, right-bank pose, the user's MAVLink Inspector screenshot
  showed roll=-0.6801097393 rad (about -39 degrees) and
  pitch=-0.5236927271 rad (about -30 degrees), confirming both attitude signs
  were reversed.
- After changing to AHRS_ORIENTATION=14, user reported: "That fixed it, the
  control surfaces respond correctly." No servo reversal or code change was
  needed for this finding. This is user-reported physical bench validation;
  no independent telemetry capture after the change was obtained.

Six-position accelerometer calibration and level calibration after selecting
the final orientation remain unconfirmed. This finding validates the mounting
correction and reported surface response, not flight readiness or experimental
IMU timing. Earlier bring-up results below describe the 2026-10-09 state.

Current installed target: BOREALISv2Servo, board ID 65092. Custom
experimental LSM6DSO32 driver from the successful sensor build retained.
Six standard PWM channels now replace the diagnostic inputs/pull-downs.
Normal ArduPlane output control, arming checks and failsafes are used;
no RC bench pass-through or arming override is enabled.

| Connector output | GPIO / timer | Function |
| --- | --- | --- |
| 1 | PE14 / TIM1 CH4 | Throttle (70) |
| 2 | PE13 / TIM1 CH3 | Aileron (4) |
| 3 | PE11 / TIM1 CH2 | Elevator (19) |
| 4 | PE9 / TIM1 CH1 | Rudder (21) |
| 5 | PD12 / TIM4 CH1 | AUX1, function unassigned (0) |
| 6 | PD13 / TIM4 CH2 | AUX2, function unassigned (0) |

Build passed; application uses 1,330,272 bytes of flash. Bootloader
programming and CRC verification passed. Board enumerated as
BOREALISv2Servo over USB. All six function parameters matched firmware
defaults; no explicit parameter updates were needed. Current parameter
backup before the change is ../pre-servo-parameters.json.

119 SERVO_OUTPUT_RAW samples were captured: latest throttle 1100 us,
aileron/elevator/rudder 1500 us. AUX functions are unassigned and report
zero PWM until a function is selected or an allowed test command drives
them. Telemetry reports commanded outputs, not an electrical measurement.
IMU and barometer health remained true throughout the capture; board stayed
disarmed. No physical servo movement or signal waveform was tested because
the user reports nothing connected yet.

Next hardware test needs appropriately powered servos on the servo rail.
Receiver setup, calibration, output direction/travel, failsafe behavior,
IMU mounting orientation and experimental driver timing validation remain
necessary before flight. The polling IMU driver has no FIFO and remains
experimental; enabling PWM does not validate it for flight.

Artifacts: firmware and source board definitions, generated-hwdef.h,
build.log, upload.log, output-verification.json, test-summary.json, sha256.json.
verify_outputs.py reads parameters and output/sensor telemetry while
disarmed; --configure can set only the six requested function assignments.
