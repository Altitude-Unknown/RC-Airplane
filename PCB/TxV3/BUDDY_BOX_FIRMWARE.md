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

The desktop configurator now exposes these commands in its **Instructor /
Student** tab. Connect the ESP32-C3 native USB port, read the displayed MAC and
role, then select **Set as Instructor (Master)** or **Set as Student**. The GUI
confirms the change and reads `STATUS` again to verify that it persisted.

Keep the aircraft powered off and boot the transmitter in Config or Simulator
mode before assigning a role. Current M0 firmware reports `MODE FLIGHT`,
`CONFIG`, `SIMULATOR`, `SETUP`, or `BIND` to the ESP every 500 ms. The ESP
includes that mode and its age in `STATUS` and rejects role commands unless a
fresh safe mode (`CONFIG`, `SIMULATOR`, or `SETUP`) is present. Consequently,
only the ESP USB cable is needed with current firmware. The GUI retains its M0
USB `PING` fallback for older firmware. Restart the transmitter after changing
its role and verify that exactly one radio is the master.

The ESP also requires a fresh `MODE FLIGHT` heartbeat before transmitting
student ESP-NOW frames or forwarding them to a master M0. This prevents a
still-powered ESP from reusing cached control data after the M0 restarts into a
safe mode.

Current bench assignment:

```text
80:F1:B2:F0:1A:E8  MASTER
80:F1:B2:F0:1A:D0  STUDENT
```

Then flash `TxV3_Full_M0` to both SAMD21 processors. The same M0 image runs on
both boards and learns its role from the local ESP32 during boot.

`TxV3_Full_M0` contains the V2 flight core: FRAM models and bind code, rates,
expo, reverse, subtrim, endpoints, aileron-to-rudder model mixing, persistent
physical trims, USB config mode, OLED setup mode, throttle boot lock, ESC
calibration override, and the throttle-time buzzer. The buddy layer is compiled
only for V3; the standalone V2 target retains its original behavior.

## Aileron-to-rudder mixing

Each stored model can independently enable an aileron-to-rudder mix and select
a signed amount from -100% to +100%. The GUI exposes both values under
**Control Mixing**. The mix is added to the physical rudder-stick command and
clamped to normal full travel before rudder rate, expo, reverse, subtrim, and
endpoints are applied. Aileron reverse is honored by the mix source. Negative
percentages reverse the mix direction.

The setting uses previously unused bytes in the existing 60-byte model record:
`reserved[1]` bit 0 is the enable flag and `reserved[2]` is the signed percent.
Existing models remain compatible and load with mixing disabled. Start around
20-30% and verify surface direction and maximum combined travel with the
propeller removed.

## Trainer operation

1. Power the student transmitter.
2. Power the master with its throttle low.
3. The master controls the airplane normally.
4. Press and release AUX on the master to grant the student control.
5. Press and release AUX again to take control back.
6. Moving any master stick, including throttle, immediately takes control back.
7. Following an automatic takeover, cycle AUX to grant control again.

## USB and Bluetooth flight-simulator mode

The transmitter exposes the same four calibrated channels in two ways while in
simulator mode:

- The SAMD21 USB port is a wired four-axis HID joystick.
- The ESP32-C3 advertises a Bluetooth LE HID gamepad named `Walach Tx2`.

Both transports use X/aileron, Y/elevator, Z/rudder, and Rz/throttle. The BLE
gamepad uses bonded "Just Works" pairing and sends fresh reports at the existing
100 Hz SAMD-to-ESP control-frame rate. To enter the safe simulator mode:

1. Disconnect or switch off the transmitter.
2. Hold **AUX/trainer** while powering the transmitter. The SAMD21 USB cable is
   optional when the transmitter has another power source.
3. Release AUX after the transmitter starts; the user LED remains solid.
4. For wireless use, pair `Walach Tx2` in the computer's Bluetooth
   settings. For wired use, connect the SAMD21 USB port.
5. Open the simulator's controller setup and map the four axes.

Simulator mode is selected only when AUX is held by itself at boot. The SAMD21
does not initialize LoRa or buddy control forwarding in this mode. The ESP32-C3
stops ESP-NOW before starting BLE, so neither processor can send commands to an
aircraft. Normal power-up retains flight operation and does not advertise the
BLE gamepad. Bind + aileron-right at boot retains the existing USB configurator
mode.

If a computer has cached an older HID descriptor during development, remove
`Walach Tx2` from its Bluetooth devices and pair it again. To return
to flight mode, power-cycle the transmitter without holding AUX.

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

The current firmware now probes the FRAM during boot. When address `0x50` does
not acknowledge, it transparently stores the same header and 16 model slots in
1,280 bytes of SAMD21 internal flash. `INFO` reports either `fram` or
`internal_flash`, and the desktop configurator displays the active backend.
FRAM remains preferred whenever it is installed. Internal flash is intended as
a practical fallback and should not be subjected to rapid repeated saves due to
its lower write endurance. Export important models before reflashing the M0;
unlike external FRAM, the internal storage image may be reset by a firmware
upload.

Still required before flight:

- Install servos in the airframe and verify physical control-surface directions,
  neutral positions, endpoints, and absence of binding.
- Calibrate the ESC endpoints and confirm motor stop and full-range response.
- Perform a receiver failsafe test in the final installed configuration.
- Perform a ground range test with the final antennas, power system, and airframe.
- Replace ESP-NOW broadcast acceptance with stored master/student MAC pairing in
  a later hardening pass.

## 2026-08-21 mode-interlock and mixing update

- Both transmitter M0 processors were flashed with operating-mode heartbeats
  and per-model aileron-to-rudder mixing.
- Both ESP32-C3 processors were flashed with safe-mode role-write enforcement
  and fresh-`FLIGHT` gating for ESP-NOW transmission and M0 forwarding.
- The desktop GUI was rebuilt with single-cable role configuration and signed
  aileron-to-rudder mix controls.
- Model codec/CRC tests passed, both firmware targets compiled, and both uploads
  passed flash verification.
- The GUI role-change test temporarily swapped the two radios, after which the
  user restored the intended assignment successfully using only each ESP USB
  cable:
  - `80:F1:B2:F0:1A:E8` — `MASTER`.
  - `80:F1:B2:F0:1A:D0` — `STUDENT`.
- The temporary swapped status captured during flashing was test state, not a
  new permanent assignment.
