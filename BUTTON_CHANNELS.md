# Button channels — implementation and bench setup

Status: implemented on 2026-09-15; GUI reviewed by the user. Hardware testing
is deferred until a receiver exposing the new signals is available. Not flashed
or published.
This feature is not in release `transmitter-gui-v2026.09.14`.

## Configurator

Load the model in **Models**, then choose the **Button channels** settings:

| Input | Assignment | Behavior |
| --- | --- | --- |
| D10 / Trainer | Trainer (existing-model default) | Trainer handoff only; Channel 5 stays low |
| D10 / Trainer | Channel 5 — Momentary | Hold for 2000 µs; release for 1000 µs |
| D10 / Trainer | Channel 5 — Toggle | Each press changes between 1000 and 2000 µs |
| D7 / Aux | Disabled (existing-model default) | Channel 6 stays low |
| D7 / Aux | Channel 6 — Momentary | Hold for 2000 µs; release for 1000 µs |
| D7 / Aux | Channel 6 — Toggle | Each press changes between 1000 and 2000 µs |

Momentary is the first enabled choice for either button. Save with **Save To
Radio**, select **Set Active** if needed, then restart in flight mode. Settings
are per model and travel with JSON exports. Switch position itself is not saved.
All switch states start low after reset. Release a button held during startup
before using it. Both edges are debounced for 25 ms; holding a toggle does not
repeat it.

The GUI refuses to save enabled button channels to M0 firmware that does not
advertise support. Use this updated GUI and firmware together; an older GUI
will erase the new assignments when it saves a model.

D10 held alone during power-up still enters Simulator mode, as before. The
new channel assignments apply after startup; they do not remove that shortcut.
In Simulator mode, enabled Channels 5 and 6 appear as USB/BLE HID buttons 1/2.

## Trainer behavior

The per-model D10 assignment controls handoff. Master role alone does not
reserve D10: a Master flying solo may select either Channel 5 behavior.

- **Trainer:** D10 can grant/revoke student control; it cannot also drive CH5.
- **Channel 5:** student handoff is disabled, even if a student connects.
- Student connection or loss never changes the saved assignment automatically.
- A Student radio reserves D10 regardless of imported/raw model settings. The
  GUI disables the D10 selector when the M0 reports Student role.
- The master retains CH5 and CH6 authority during handoff. Student stick
  channels pass through, but student button states do not replace master
  switches. D7 can therefore remain available to the instructor throughout.

The **Instructor / Student** tab reports **Student link (last read)** from the
ESP32. Use **Read Status Again** to refresh it. This reports recent valid
student packets (within 250 ms), not an enduring pairing. A student outside
Flight mode does not transmit trainer controls. Older ESP firmware reports no
student-link status; upgrade the ESP32 to obtain that indication. Reading an
ESP status does not associate an unrelated M0 USB device with that ESP.

## Receiver signals

| Logical channel | Standalone receiver signal | Pixhawk CRSF input |
| --- | --- | --- |
| Channel 5 (D10) | D21 / SCL | Channel 5 |
| Channel 6 (D7) | D20 / SDA | Channel 6 |

Use signal plus common ground and suitable servo power. These are GPIO signal
pins; they are not servo power sources. The current PCB needs access to the
SCL/SDA pins; future receiver revisions will expose dedicated connectors.
Do not use these pins for I2C peripherals while running this servo firmware.

D20 retains its bind-plug startup function. The receiver samples it as an input
before configuring outputs. A detected bind plug keeps D20 as an input for the
entire power cycle, including after binding succeeds; it never drives a pulse
against the grounded plug. Remove the plug and restart before using CH6.
A connected peripheral that holds D20 low during boot can also trigger bind
mode; check this with the actual servo/flight-controller installation.

Standalone auxiliary outputs default to 1000 µs and fail low when accepted
packets become more than 150 ms old. They work independently of throttle arming.
A fresh accepted packet restores the transmitted state. Existing four-channel
throttle/surface failsafe timings are unchanged.

The CRSF prototype retains its existing 300 ms loss-of-link behavior: it stops
sending channel frames so the flight controller can execute its configured
failsafe. Configure the controller's CH5/CH6 functions and failsafe behavior
there. The CRSF firmware remains a separate source-build prototype and is not
included in the configurator's standard Receiver download.

## Firmware and storage compatibility

- V3 M0 implements button inputs, assignments, and trainer enforcement.
- ESP32 update adds the student-link status field; existing ESP packet
  forwarding already carries the switch byte unchanged.
- Standalone receiver update enables D21/D20 servo outputs.
- `rx_pixhawk_crsf` maps switch states to CRSF channels 5 and 6. It now rejects
  unbound packets as well as mismatched bind codes.
- The legacy `tx_firmware` sketch also supports these two button inputs, but
  does not implement the V3 ESP buddy link.

The LoRa control packet remains 13 bytes and the existing buddy packet layout
is unchanged. `aux_flags` bit 7 marks this encoding; bits 4 and 5 are CH5 and
CH6 high states. Low bits from historical experimental packets are ignored.
Older receivers ignore the switch byte and continue operating the first four
channels. New receivers interpret old unmarked packets as CH5/6 low.

Model layout remains 60 bytes in each 64-byte slot. `reserved[5]` bits 0–1 store
D10 (0=Trainer, 1=Momentary, 2=Toggle), and bits 2–3 store D7 (0=Disabled,
1=Momentary, 2=Toggle). Invalid value 3 falls back to Trainer/Disabled. The CRC
covers the new settings. No existing bind code, mixing field, or trim is moved.

## Bench acceptance checklist

With motor power disabled:

1. Back up models, install the updated GUI/M0/receiver, and confirm existing
   four-channel movement and model selection.
2. Test each enabled momentary input: one output changes while held and returns
   on release. Verify 1000/2000 µs or the corresponding servo positions.
3. Test each toggle input: one change per press, none on continued hold, none
   on release. Reset while high and confirm low startup.
4. Verify D10's existing simulator boot shortcut and D7 held-at-boot handling.
5. Select Trainer on the master, connect a student, and verify handoff, master
   stick takeover, and student-loss takeover. CH5 must remain low; D7 must
   remain controlled by the master.
6. Select Channel 5 on the master, restart, then connect/disconnect a student.
   D10 must continue operating CH5 and must never grant student authority.
7. Turn off the transmitter and verify auxiliary output failsafe behavior.
8. Test D20 bind-plug startup and subsequent normal CH6 operation after removing
   the plug. Confirm the actual connected CH6 device does not falsely trigger
   bind mode during normal startup.
9. For CRSF, verify all six inputs and the controller's configured mode/action
   and receiver-loss behavior before flight.

Automated coverage exercises the production button state machine, model
round-trips, legacy packet handling, trainer interlock and ownership, CRSF
frame mapping, and D20 pulse suppression in bind-plug mode. Hardware behavior
and radio timing still require the checks above.
