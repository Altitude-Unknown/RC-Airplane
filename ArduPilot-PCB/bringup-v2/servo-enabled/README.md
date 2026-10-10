# V2 servo-enabled ArduPlane — 2026-10-09

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
