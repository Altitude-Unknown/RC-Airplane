# Transmitter V3 Buddy-Box Firmware

This first V3 flight-firmware build preserves the V2 receiver `ControlPacket`
format while adding a wireless instructor/student link through the two onboard
ESP32-C3 modules.

## Safety model

- Only an ESP-configured `MASTER` SAMD21 initializes the RFM95.
- A `STUDENT` SAMD21 never initializes or transmits LoRa.
- An unconfigured or missing ESP role prevents LoRa transmission.
- AUX authority changes only after a complete press-release cycle.
- Master stick movement of 35 microseconds or more revokes student authority.
- Student data older than 250 ms revokes authority.
- After movement or link-loss revocation, the master must cycle AUX again.
- ESP-NOW packets use protocol magic, version, role, and CRC checks.
- The low-latency build uses a 115200-baud internal UART and a 100 Hz student
  update rate with interrupt-driven M0 receive buffering. The master ESP
  forwards each newly received student frame immediately instead of waiting on
  a separate 50 ms forwarding interval.
- ESP-to-master control data uses fixed-length binary packets with sync magic,
  protocol version/type, channel bounds, sequence, and CRC-16. The M0 parser
  resynchronizes by scanning for the next valid magic after a damaged packet.

## ESP role setup

Flash `TxV3_Buddy_ESP32` to both ESP32-C3 modules. Open each ESP native USB
console at 115200 baud and issue one persistent role command:

```text
ROLE MASTER
ROLE STUDENT
```

`ROLE SLAVE` is accepted as an alias for `ROLE STUDENT`. Use `STATUS` to print
the stored role and MAC address. Roles are stored in ESP32 NVS.

The desktop/mobile configurator must later expose this as a guarded transmitter
role setting. The GUI should read `STATUS`, display the ESP MAC and current
role, require confirmation before changing roles, send `ROLE MASTER` or
`ROLE STUDENT`, and read `STATUS` again to verify the persistent result. Role
changes must not be offered while the master is actively transmitting LoRa.

Current bench assignment:

```text
80:F1:B2:F0:1A:E8  MASTER
80:F1:B2:F0:1A:D0  STUDENT
```

Then flash `TxV3_Full_M0` to both SAMD21 processors. The same M0 image runs on
both boards and learns its role from the local ESP32 during boot.

`TxV3_Full_M0` contains the V2 flight core: FRAM models and bind code, rates,
expo, reverse, subtrim, endpoints, persistent physical trims, USB config mode,
OLED setup mode, throttle boot lock, ESC calibration override, and the
throttle-time buzzer. The buddy layer is compiled only for V3; the standalone
V2 target retains its original behavior.

## Trainer operation

1. Power the student transmitter.
2. Power the master with its throttle low.
3. The master controls the airplane normally.
4. Press and release AUX on the master to grant the student control.
5. Press and release AUX again to take control back.
6. Moving any master stick, including throttle, immediately takes control back.
7. Following an automatic takeover, cycle AUX to grant control again.

The master LED is solid under instructor control and rapidly flashes while the
student has authority. The student LED slowly flashes.

## Current prototype limitations

- Interactive endpoint testing on the assembled master found the physical
  throttle on A3 and rudder on A0, matching V2 wiring rather than the corrected
  V3 schematic labels. Throttle low measured about 1020 ADC counts and uses an
  inverted mapping. Revalidate this harness mapping on every PCB revision.

- ESP-NOW uses broadcast frames on channel 1. CRC and role validation reject
  malformed traffic, but a later pairing step should restrict a master to one
  stored student MAC.
- Before flight, bench-test with the propeller removed, verify every channel and
  direction at both authorities, verify throttle boot lock and receiver
  failsafe, and complete a ground range test.

## 2026-07-22 integration and bench-test record

Firmware identities:

```text
MASTER  ESP MAC 80:F1:B2:F0:1A:E8
STUDENT ESP MAC 80:F1:B2:F0:1A:D0
```

Completed tests:

- Both ESP32-C3 and SAMD21 targets compiled and flashed successfully.
- Persistent master/student roles survived reflashing and reset.
- Fixed-length ESP-to-M0 packets ran continuously at 20 Hz with CRC validation,
  zero rejected packets, and zero RX-ring overflow in the final sample.
- Removed periodic ESP USB logging from the real-time loop after proving that
  disconnected native USB could block forwarding for about two seconds.
- Added role-query/READY startup gating and a one-second authority heartbeat so
  either processor can reboot independently and restore forwarding.
- AUX press-release granted student authority.
- A second AUX cycle returned authority to the instructor.
- Master stick movement revoked student authority.
- Student power loss made the link stale and revoked student authority.
- Full V2 flight features were merged through `TxV3_Full_M0`: FRAM models and
  bind code, rates, expo, reverse, subtrim, endpoints, trims, USB configuration,
  OLED setup, throttle boot lock, ESC override, and throttle-time buzzer.
- Master bound successfully to a V4 receiver. Three servos and the ESC/motor
  responded to the correct stick channels with the propeller removed.
- Receiver-observed master throttle commands were approximately 1003-1004 us
  low, 1494-1495 us at mechanical midpoint, and 1999-2000 us high.
- Direct ADC measurement was approximately 1019-1020 at throttle low and 0-1 at
  throttle high. A near-high raw value of 8-9 produced 1991-1992 us, confirming
  linear transmitter mapping. The observed motor plateau is therefore an ESC
  calibration/behavior issue, not a transmitter endpoint failure.
- High-throttle master reboot correctly transmitted no packets. The V4 receiver
  froze its packet counter, disarmed, centered the three surface outputs at
  1500 us, and commanded throttle to 1000 us. Lowering throttle and resetting
  restored a fresh link and normal arming.

Issue found, fixed, and physically retested:

- Student stick movement initially caused immediate false instructor takeover.
  The outgoing student values had overwritten the `ControlPacket` fields also
  used as the next loop's instructor smoothing history. The next loop therefore
  interpreted student deflection as master movement.
- The V3 build now keeps independent instructor smoothing variables and copies
  them into the outgoing packet before optional student substitution. This fix
  compiled and was flashed to the master.
- The follow-up bench test passed: student stick movement continued to command
  the receiver without an immediate false instructor takeover. AUX handoff,
  intentional master-stick takeover, and student link-loss takeover all behaved
  correctly with the separated smoothing state.

## 2026-08-21 low-latency update

The original conservative timing could add approximately 70-120 ms before the
normal master-to-aircraft LoRa hop: 50 ms M0 reporting, 20 ms ESP-NOW pacing,
50 ms master forwarding, and slow UART serialization could all align poorly.

The flight path now uses:

- 10 ms (100 Hz) student M0 reports.
- 10 ms (100 Hz) ESP-NOW transmit pacing.
- Immediate master ESP-to-M0 forwarding of each newest frame.
- 115200-baud UART on both M0 and ESP32-C3.

The expected buddy-only latency is roughly 10-25 ms, but this must be measured
on both assembled boards. Reflash both ESP32-C3 modules and both SAMD21 modules;
the UART baud change requires matching firmware on each processor.

Flash and link verification completed on 2026-08-21:

- Production `TxV3_Full_M0` compiled for `Altitude Unknown RC TX M0`.
- `TxV3_Buddy_ESP32` compiled for ESP32-C3 with USB CDC enabled at boot.
- Master ESP32-C3 (`80:F1:B2:F0:1A:E8`) and master SAMD21 flashed and verified.
- Master retained `MASTER`, initialized ESP-NOW, reported instructor authority,
  and resumed M0-to-ESP messages at 115200 baud.
- Student ESP32-C3 (`80:F1:B2:F0:1A:D0`) and student SAMD21 flashed and verified.
- Student retained `STUDENT`, initialized ESP-NOW, received M0 messages at the
  new baud, and advanced its ESP-NOW transmit counter at approximately 100 Hz.

Pending physical validation (propeller removed):

1. Confirm normal instructor control.
2. Cycle AUX and confirm student authority and improved response latency.
3. Move an instructor stick and confirm immediate instructor takeover.
4. Grant student authority again, power off the student, and confirm automatic
   link-loss takeover.
5. Inspect control direction, endpoints, and jitter under both authorities
   before reinstalling the propeller or attempting flight.

Bench validation completed later on 2026-08-21:

- Instructor and student controls operated correctly.
- Student response latency was greatly reduced and judged flight-ready.
- Instructor stick-movement takeover operated as expected.
- Student link-loss takeover had already passed the preceding bench sequence.

The desktop configurator must connect to the SAMD21 USB device named
`Altitude RC TX M0`, not the ESP32-C3 USB diagnostic port. Enter USB config mode
by holding Bind (D9) and Aileron Trim Right (D5) during transmitter startup. A
student transmitter was verified to return `PONG` to the configurator handshake
in this mode after the low-latency update.

During that verification, `PING`, `INFO`, and `RANGE` succeeded but every FRAM
`READ` returned `ERR`, including a one-byte read at address zero. USB config mode
and the command parser are therefore working; the student transmitter's FRAM
did not acknowledge or return data at I2C address `0x50`. Check whether the
MB85RC256V is populated, then inspect its 3.3 V supply, ground, SDA/SCL soldering,
and address pins before treating this as a configurator software failure.

Still required before flight:

- Install servos in the airframe and verify physical control-surface directions,
  neutral positions, endpoints, and absence of binding.
- Calibrate the ESC endpoints and confirm motor stop and full-range response.
- Perform a receiver failsafe test in the final installed configuration.
- Perform a ground range test with the final antennas, power system, and airframe.
- Replace ESP-NOW broadcast acceptance with stored master/student MAC pairing in
  a later hardening pass.
