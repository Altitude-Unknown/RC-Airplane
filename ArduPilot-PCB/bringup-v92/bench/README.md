# BOREALIS v92 bench-only test image

Prepared and tested 2026-09-29. The first bench image tested servo
outputs 2–6; `arduplane-bench-servo-only.apj` preserves that image. The
revised `arduplane-bench.apj` tested the ESC-connected throttle output.
Afterward, the known-good diagnostic ArduPlane image at `../arduplane.apj`
was restored, and USB telemetry confirmed its restart.

This ArduPlane 4.7.1 variant keeps the normal missing-IMU configuration
error. While in that error loop, it updates the installed MS5611 and RC
channels so USB MAVLink can report pressure, temperature, and receiver
inputs. It reports `BOREALIS BENCH: outputs test-only` over MAVLink.

The six PWM channels are mapped as follows. Each J4 row is signal, 5 V
servo rail, ground. The servo rail needs an external 5 V supply; USB
alone does not power it.

| Bench channel | Function label | MCU/timer | J4 signal | J4 5 V | J4 ground |
| --- | --- | --- | ---: | ---: | ---: |
| 1 | Throttle | PE14 / TIM1_CH4 | 1 | 2 | 3 |
| 2 | Aileron | PE13 / TIM1_CH3 | 4 | 5 | 6 |
| 3 | Elevator | PE11 / TIM1_CH2 | 7 | 8 | 9 |
| 4 | Rudder | PE9 / TIM1_CH1 | 10 | 11 | 12 |
| 5 | AUX1 | PD12 / TIM4_CH1 | 13 | 14 | 15 |
| 6 | AUX2 | PD13 / TIM4_CH2 | 16 | 17 | 18 |

Outputs start disabled. In the missing-IMU error loop, a MAVLink
`MAV_CMD_DO_SET_SERVO` request for channels 2–6 is accepted only at
1300–1700 µs. In the revised image, channel 1 accepts only
1000–1150 µs for a low-throttle ESC test. It enables one channel at a
time and disables it after
2.5 seconds without another command. The accompanying
`../bench_mavlink.py` script only sends a test sequence after seeing the
bench firmware status and the missing-IMU error. Its output mode also
requires `--prop-removed`. A motor test requires `--motor-test` and
`--motor-secured`; its 1000/1080/1150/1000-us sequence explicitly
drives channel 1. Channels 2–6 can be tested while the ESC supplies the
5 V rail, leaving channel 1 disabled. Remove the propeller.

Receiver connectors on schematic v92:

- J5 pin 1 = USART1 RX (PB7), pin 2 = USART1 TX (PB6), pin 3 = ground.
  J5 has no receiver power pin. USART1 is shared with the GPS connector.
- J4 pin 25 = USART6 TX (PC6), pin 28 = USART6 RX / `RCIN_SBUS` (PC7);
  pins 26/29 are the 5 V servo rail and 27/30 are ground.
- Whether the Spektrum signal belongs on RX or TX, the serial options,
  and the safe receiver supply voltage depend on the exact receiver
  model/protocol. Check these before connecting it.

The user's receiver photo appears to show a Spektrum AR6210 DSMX.
Spektrum documents its THRO/AILE/ELEV/RUDD/GEAR/AUX1 sockets as
individual servo outputs, and its BIND/DATA socket for binding and the
Flight Log accessory. There is no documented combined serial RC-channel
output on this receiver. Do not wire BIND/DATA to a flight-controller
UART as if it were DSM or SRXL2. A serial-output receiver or an external
PWM-to-serial/PPM converter is needed to bring all of its channels into
this PCB's current RC input arrangement.

The newly found FlySky FS-iA6B was used for that input test. Its
`SERVO` i-BUS port supplies serial RC data; the `SENS` connector is for
sensor telemetry, and `PPM/CH1` is a different output. With power off,
map its SERVO signal to J4 pin 28 (USART6 RX), plus to J4 pin 29 (5 V),
and ground to J4 pin 30. The ESC/BEC already supplies this 5 V rail.
Select i-BUS in the FlySky transmitter's receiver output mode and set
`SERIAL2_PROTOCOL=23` (RCIN) on the flight controller; the small
`../configure_ibus_rcin.py` helper writes and reads back that parameter.
The normal diagnostic image also reports `RC_CHANNELS` after its
missing-IMU startup error; the bench image was used for the main
stick-motion capture and then the normal APJ was restored.

Source is `hwdef.dat` and `ardupilot-bench.patch`, applied to the local
ArduPilot checkout. The APJ board ID is 65092. The first image SHA-256 is
`14b51454f414b3595724933b80347bd1e1ac0d9c251bfd65f2597b4294d348d6`;
the revised image SHA-256 is
`82dec384be0e652753befd2079e05579f16645075d91fc55062951180c58154f`.
The bootloader is the existing v92 bootloader. After bench testing,
restore `../arduplane.apj`; this bench image is not flight firmware.
The normal board build configuration was restored after bench testing.
An earlier rebuild of its APJ exactly matched the archived known-good image
(`632f38f5a67b412acd7b29280f1f9ef6408135f77aafe5235045dd36007c4cdf`).

## Hardware results (2026-09-29)

- Uploader identified bootloader board ID 65092, erased, programmed, and
  verified this bench APJ. The application re-enumerated on USB and
  reported `BOREALIS BENCH: outputs test-only` plus the expected absent-IMU
  configuration error.
- The installed MS5611 produced 44 live pressure samples from
  847.654 to 847.771 hPa and 25.59 to 25.68 C. This passes the
  pressure/temperature conversion check; calibration and altitude
  checks await a complete flight stack.
- RC telemetry reports zero channels because no compatible serial RC
  receiver is attached. The pictured AR6210 cannot supply the needed
  serial channel stream directly.
- PWM channels 2 (AILERON), 3 (ELEVATOR), 5 (AUX1), and 6 (AUX2)
  each accepted four 1500/1600/1400/1500-us commands and the user saw
  the corresponding servo move.
- Channel 4 (RUDDER) initially accepted those commands but its
  original servo did not move. After swapping the known-good AILERON
  servo into the RUDDER row, it moved as expected. `SERVO_OUTPUT_RAW`
  reported 1400, 1500, and 1600 us for channel 4. The original RUDDER
  servo also moved on the known-good AILERON row. The initial miss was
  therefore likely a loose or misplaced connector; recheck its seating.
- Channel 1 (THROTTLE) accepted five 1000/1000/1080/1150/1000-us
  commands, all ACKed. `SERVO_OUTPUT_RAW` reported 1080 and 1150 us,
  and the user confirmed the propeller-free motor briefly spun and
  stopped. This verifies the throttle signal path through the ESC;
  a standalone servo was not connected to that row.
- The normal ArduPlane APJ was restored by the USB bootloader and
  verified. It reports the expected missing-IMU error, no bench identity,
  and has no PWM-capable pins mapped in its hwdef. Its barometer telemetry
  is zero in that configuration-error loop; the bench image provided the
  live barometer readings above.
- A bound FlySky FS-iA6B was connected via i-BUS SERVO to J4 pins
  28/29/30 with the ESC/BEC powering the receiver. `SERIAL2_PROTOCOL`
  was set to 23 and read back after reboot. ArduPilot decoded 14 channel
  slots. During transmitter stick movement, CH1 ranged 1014–1991 us,
  CH2 1088–1989 us, CH3 1005–1992 us, and CH4 1151–1746 us. A separate
  low-throttle check read CH3 at 1006 us. The bench image showed zero
  physical output channels throughout the receiver test. After normal
  firmware restoration, `RC_CHANNELS` still showed 14 slots and low
  throttle at 1006 us. `SERVO_OUTPUT_RAW` on normal firmware contains
  software output values, but its hwdef does not map these to PWM pins;
  the user confirmed the motor remained stopped.
