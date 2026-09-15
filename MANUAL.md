# RC Airplane System Manual

Living manual for the Altitude Unknown RC transmitter, receiver, and configurator GUI.

Last updated: 2026-09-14

This manual describes production release `transmitter-gui-v2026.09.14`.
[Download the configurator and matching firmware](https://github.com/Altitude-Unknown/RC-Airplane/releases/tag/transmitter-gui-v2026.09.14).
V-tail controls have passed the pilot's bench and flight tests. Elevon mixing
has automated tests but has not yet been tested on an airplane.

## Unreleased Button-Channel Update

The next firmware/configurator update adds D10/Channel 5 and D7/Channel 6
momentary or toggle control, per-model trainer assignment, D21/SCL and D20/SDA
receiver outputs, and CRSF channel mapping. This is not part of the 2026.09.14
release described below. See [button-channel setup and bench checks](BUTTON_CHANNELS.md).

## Contents

- [System Overview](#system-overview)
- [Hardware Targets](#hardware-targets)
- [Transmitter](#transmitter)
- [Aircraft Type And Control Mixing](#aircraft-type-and-control-mixing)
- [Receiver](#receiver)
- [Desktop Transmitter Configurator](#desktop-transmitter-configurator)
- [Troubleshooting](#troubleshooting)
- [Known Good Fallback Points](#known-good-fallback-points)

## System Overview

The RC airplane system contains these components:

- **Transmitter V3 M0 firmware:** `PCB/TxV3/TxV3_Full_M0/TxV3_Full_M0.ino`
- **Transmitter V3 buddy firmware:** `PCB/TxV3/TxV3_Buddy_ESP32/TxV3_Buddy_ESP32.ino`
- **Receiver firmware:** `rx_firmware/rx_firmware.ino`
- **Desktop configurator GUI:** `fram_gui_models.py`

The master transmitter sends LoRa control packets to the receiver. A student
transmitter sends controls to the master over ESP-NOW; only the master M0 is
allowed to initialize LoRa. The receiver drives throttle, aileron, elevator,
and rudder outputs. Model setup data uses external FRAM when installed and the
M0 internal-flash fallback otherwise. The desktop GUI edits the complete model;
the OLED setup menu edits reverse, rate, and expo for RUD, AIL, and ELE only.

## Hardware Targets

Use the target that matches the processor:

| Processor / sketch | Arduino target |
| --- | --- |
| V3 M0, `PCB/TxV3/TxV3_Full_M0` | `adafruit:samd:adafruit_feather_m0_express` with the release USB identity flags |
| V3 ESP32-C3, `PCB/TxV3/TxV3_Buddy_ESP32` | `esp32:esp32:esp32c3`, `CDCOnBoot=cdc` |
| Receiver, `rx_firmware` | `adafruit:samd:adafruit_feather_m0` |
| Legacy transmitter, `tx_firmware` | `adafruit:samd:adafruit_feather_m0` |

The locally installed `AltitudeUnknown:samd:altitude_rc_tx_m0` definition is an
alternative V3 M0 target. The release workflow uses the Adafruit Express target
with explicit USB identity flags; see [Transmitter Firmware Flashing](#transmitter-firmware-flashing).
Published V3 M0 images use `TxV3_Full_M0`, not the legacy transmitter sketch.

Use `arduino-cli board list` to identify connected ports. Port names vary by
computer and OS; do not assume `/dev/cu.usbmodem1101` always identifies the same
board. The M0 and ESP USB connectors belong to different processors.

## PCB Schematics

Hardware schematic PDFs are kept in this repo for quick reference:

| PCB | Schematic |
| --- | --- |
| Transmitter V2 | `Transmitter-V2-Schematic.pdf` |
| Transmitter V3 | `Transmitter V3.pdf` |
| Receiver V4 | `Receiver-V4-Schematic.pdf` |

## Transmitter

### Transmitter Pinout

| Function | Pin | Notes |
| --- | --- | --- |
| LoRa CS | D8 | RFM95 chip select |
| LoRa IRQ | D3 | RFM95 interrupt |
| LoRa RST | D4 | RFM95 reset |
| Bind button | D9 | Hold at boot for bind mode |
| AUX / trainer | D10 | Trainer handoff; hold alone at boot for Simulator mode |
| ESC override / aileron-right trim | D5 | Hold at boot for ESC calibration override |
| Throttle gimbal | A3 | Analog input |
| Aileron gimbal | A1 | Analog input |
| Elevator gimbal | A2 | Analog input |
| Rudder gimbal | A0 | Analog input |
| Rudder trim left | A4 | Physical trim |
| Rudder trim right | D12 | Physical trim |
| Aileron trim left | D1 | Physical trim |
| Aileron trim right | D5 | Physical trim |
| Elevator trim down | D2 | Physical trim |
| Elevator trim up | D0 | Physical trim |
| OLED I2C address | `0x3D` | Setup menu display |
| Buzzer | D11 | Throttle timer alarm |

### Transmitter Boot Modes

| Mode | How to Enter | Behavior |
| --- | --- | --- |
| Normal | Power up with throttle low | Sends RC control packets |
| Safety lock | Power up with throttle high | Sends nothing until reset with throttle low |
| ESC calibration override | Power up with throttle high and hold D5 / aileron-right trim | Sends throttle immediately for intentional ESC calibration |
| Bind mode | Hold D9 low at boot | Repeatedly sends bind packets |
| USB config mode | Hold both D9 and D5 low at boot | No LoRa transmit; desktop GUI can read/write model storage |
| OLED setup mode | Hold both rudder trims at boot | No LoRa transmit; setup menu shown on OLED |
| Simulator mode | Hold AUX/trainer by itself at boot | No LoRa or trainer forwarding; USB and BLE HID gamepads active |

### Normal Transmitter Operation

1. Set throttle low.
2. Power on transmitter.
3. Confirm LED goes solid.
4. Power on receiver.
5. Move controls and verify surfaces.

If the LED fast-blinks after boot, the transmitter is in throttle safety lock. Lower throttle and reset.

### Physical Trims

Physical trims update the active model subtrim in the selected radio storage
(external FRAM or internal flash) when a model is loaded. Rudder, aileron, and
elevator have trims. Throttle has no trim. Each press-and-release changes the
stored trim by 5 µs, limited to −500 through +500 µs. Holding a button does not
repeat the trim. With mixed surfaces, trim follows the logical control axis as
described in [Aircraft Type And Control Mixing](#aircraft-type-and-control-mixing).
Without a loaded model, trims are temporary and reset at power-off.

Trim pins:

- Rudder left/right: `A4`, `D12`
- Aileron left/right: `D1`, `D5`
- Elevator down/up: `D2`, `D0`

### OLED Setup Menu

Enter setup mode by holding both rudder trim buttons while powering on.

In setup mode:

- LoRa is not initialized.
- No RC packets are sent.
- Throttle cannot be edited.

Controls:

| Buttons | Action |
| --- | --- |
| Rudder trims | Select channel: RUD, AIL, ELE |
| Elevator trims | Select setting: REVERSE, RATE, EXPO |
| Aileron trims | Change selected value |

Changes are saved to the active radio storage immediately. Aircraft type,
V-tail rudder-input reversal, endpoints, and aileron-to-rudder mixing are edited
in the desktop configurator.

### Instructor / Student Operation

The V3 radios use persistent roles stored by the local ESP32-C3. The recorded
assignment for the two project radios is:

| ESP MAC | Role |
| --- | --- |
| `80:F1:B2:F0:1A:E8` | Instructor / Master |
| `80:F1:B2:F0:1A:D0` | Student |

Other radios have different MAC addresses; read the connected radio's identity
in the configurator before assigning its role.

Normal trainer operation:

1. Power the student transmitter.
2. Power the master with throttle low.
3. Press and release AUX on the master to grant student control.
4. Press and release AUX again to take control back.
5. Moving a master stick sufficiently from its handoff position takes control back.
6. Student link loss also returns authority to the master.

The ESP requires a fresh M0 `FLIGHT` heartbeat before sending or forwarding
trainer controls. Role changes are accepted only while the M0 reports Config,
Simulator, or Setup mode.

### Aileron-to-Rudder Mixing

This setting is saved per model. Enable **Mix aileron into rudder** and set
**Rudder amount** from −100% to +100%. Changing the sign reverses the added
rudder contribution; it does not reverse the physical rudder stick.

The mix follows the configured AIL output reversal and is added to rudder
stick input, then clamped before rudder rate and expo. Aircraft mixing follows.
For V-tail, **Reverse rudder input** reverses both the rudder-stick and the
aileron-to-rudder contributions. Therefore a sign that works for one model may
need reversing on another. Judge the direction from the airplane's movement.

For initial surface setup, leave this option off. Once elevator and rudder
stick directions are correct, enable a small amount and check the direction.
For example, changing −50% to +50% reverses coordinated rudder while retaining
the established elevator and rudder-stick directions. Save and restart in
flight mode after editing.

### Throttle Timer / Buzzer Alarm

The transmitter includes a throttle-on timer to help estimate flight time without adding telemetry lag.

Behavior:

- Timer counts only while commanded throttle is above `1080us`.
- Timer pauses when throttle is pulled back to idle.
- First alarm: 5 minutes of accumulated throttle-on time.
- Follow-up alarm: every 1 additional throttle-on minute.
- The 5-minute alarm pattern is different from the 1-minute reminder pattern.
- Buzzer logic is non-blocking and does not use `delay()` in the flight loop.

Standalone buzzer test sketch:

```text
Tx_Buzzer_Test/Tx_Buzzer_Test.ino
```

### Transmitter Firmware Flashing

For routine updates, use the configurator's **Firmware Update** tab. For source
builds, run from the repository root. The V3 M0 release command is:

```bash
arduino-cli compile --output-dir firmware-build/samd \
  --fqbn adafruit:samd:adafruit_feather_m0_express \
  --build-property 'build.usb_product="Altitude RC TX M0"' \
  --build-property 'build.usb_manufacturer="Altitude Unknown"' \
  --build-property build.vid=0x03EB \
  --build-property build.pid=0x2402 \
  --build-property 'build.extra_flags=-D__SAMD21G18A__ -DARDUINO_SAMD_FEATHER_M0 -DARDUINO_SAMD_ZERO -DARM_MATH_CM0PLUS -DALTITUDE_RC_TX_M0 {build.usb_flags}' \
  PCB/TxV3/TxV3_Full_M0
```

The release workflow pins Adafruit SAMD core 1.7.10 and ESP32 core 3.3.10;
its complete build/package steps are in
[the release workflow](.github/workflows/transmitter-gui-release.yml).

Compile the V3 ESP32-C3 with USB CDC enabled:

```bash
arduino-cli compile --fqbn esp32:esp32:esp32c3 --board-options CDCOnBoot=cdc "PCB/TxV3/TxV3_Buddy_ESP32"
```

Both processors on both transmitters must run matching current firmware for
single-cable role assignment and the mode interlock. ESP uploads retain the
role in NVS. Export important models before M0 flashing when internal-flash
storage is in use.

## Aircraft Type And Control Mixing

In the Models editor, select **Aircraft Type**, save the model, and make it the
active model before restarting the transmitter in flight mode. Use configurator
and transmitter M0 firmware from `transmitter-gui-v2026.09.14` or later. Older
firmware ignores aircraft type; older configurators erase these new settings
when saving a model. Restart an already-open older GUI after updating.
The selection is saved per model and included in JSON exports. Existing models
and older JSON files default to Conventional / T-tail.

| Aircraft type | Receiver output connections | Mixing |
| --- | --- | --- |
| Conventional / T-tail | RUD: rudder; AIL: aileron; ELE: elevator | Separate controls |
| V-tail (ruddervators) | RUD: first ruddervator; ELE: second ruddervator; AIL: aileron | RUD = elevator + rudder; ELE = elevator − rudder |
| Flying wing (elevons) | AIL: first elevon; ELE: second elevon | AIL = elevator + aileron; ELE = elevator − aileron |

These equations describe normalized commands before output reversal and travel
mapping, not a universal left/right servo installation. Identify the receiver
socket labels instead of relying on connector position.

Throttle is unchanged. Flying wings retain an independent RUD output if needed.
Each shaped axis is added at full weight; combined commands are clipped to the
configured output travel. Rates and expo apply to the logical stick axes before
mixing. **High Rates Active** overrides all four stored rates to 100%; expo
remains active. For mixed surfaces, subtrim and physical trim follow those axes (500 µs
is one normalized unit), so elevator trim moves both surfaces together.
Reverse and endpoints apply to each physical output after mixing. Set servo
neutral mechanically, then adjust endpoints to set individual output midpoint and travel. Unequal
endpoint changes also move the midpoint; recheck both neutral and full travel.
Optional aileron-to-rudder mixing is applied before aircraft mixing.

With the motor disabled, verify both surfaces respond correctly to pitch and
yaw/roll commands before flying. Servo installation determines the necessary
output reversal and which surface uses the first versus second output. Check
combined full-stick travel for binding as well as single-axis commands.

### Correct elevator response but reversed V-tail rudder response

Keep the servo connections and output reversal settings that give correct
pitch movement. Enable **Reverse rudder input (V-tail only)** and save the model,
then restart in flight mode. This reverses the yaw contribution (including yaw
trim and optional aileron-to-rudder mix) without reversing pitch. It requires
updated transmitter firmware and is ignored for other aircraft types.

### First Setup And Direction Checks

1. Disable motor power or remove the propeller. Export the existing model.
2. Select the aircraft type and turn off aileron-to-rudder mixing initially.
3. Connect V-tail servos to RUD and ELE, or elevons to AIL and ELE.
4. Check neutral trim and endpoints; start with modest rates and travel.
5. Move only the elevator stick. Set each participating output's **Reverse**
   value so both surfaces produce the intended pitch response.
6. For V-tail, move only the rudder stick. If yaw is backward but pitch is
   correct, toggle **Reverse rudder input (V-tail only)**. Keep the connections
   and output reversals that gave correct pitch. Cable swapping is not a
   reliable substitute across different servo installations.
7. For elevons, check roll separately. There is no independent roll-input
   reversal option in this release; establish the appropriate output assignment
   and reversals for the installation and repeat the pitch check.
8. Save with **Save To Radio**, use **Set Active** if necessary, and restart in
   flight mode. Repeat the checks after every change.
9. If desired, enable aileron-to-rudder mixing and choose its sign from the
   resulting yaw direction. Check combined full-stick travel for binding.

V-tail rudder-input reversal also reverses the yaw-trim contribution, so recheck
neutral trim after changing it. Neither that option nor aileron-to-rudder mix
sign changes the elevator contribution.

## Receiver

### Receiver Pinout

| Function | Pin | Notes |
| --- | --- | --- |
| LoRa CS | D8 | RFM95 chip select |
| LoRa IRQ | D3 | RFM95 interrupt |
| LoRa RST | D4 | RFM95 reset |
| Bind button | D10 | Hold low at boot for bind mode |
| Bind plug | D20 / SDA | Short to ground at boot for bind mode |
| Throttle output | A0 | Servo/ESC pulse |
| Aileron output | A1 | Servo pulse |
| Elevator output | A2 | Servo pulse |
| Rudder output | A3 | Servo pulse |
| Battery monitor | A4 | Disabled unless voltage divider is fitted |

### Receiver LED Meanings

| LED Pattern | Meaning |
| --- | --- |
| Solid | Armed / outputs active |
| Slow blink | Locked or disarmed |
| Fast blink | RF stale / link lost |
| Bind blink | Bind mode waiting |

### Receiver Bind Mode

The receiver must have an explicitly stored, nonzero bind code before it will
accept control packets. An unbound receiver remains disarmed in failsafe even
if valid packets are present on the correct LoRa channel.

Use this sequence:

1. Turn off both transmitter and receiver and remove the propeller.
2. Hold the receiver Bind button (D10) while powering or resetting the receiver.
3. Release the receiver Bind button after it enters bind mode.
4. Hold the transmitter Bind button (D9) while powering or resetting the
   transmitter.
5. Wait for the receiver's bind confirmation. It stores the transmitted bind
   code in flash and exits bind mode.
6. Release the transmitter Bind button.
7. Restart the transmitter normally with throttle low. Power-cycle the receiver
   as well if its normal armed/linked indication does not appear.
8. Verify all surfaces, throttle safety, and failsafe behavior before flight.

Changing the active model's bind code in the configurator does not update an
already-bound receiver. Save the new code to the transmitter, restart it, and
repeat the complete bind sequence above for every receiver that should accept
that model.

Flashing receiver firmware can clear its stored bind code. Treat a freshly
flashed receiver as unbound and bind it again before testing controls.

#### Binding With A D20/SDA Bind Plug

This method avoids holding the receiver's D10 button while connecting the
aircraft battery:

1. Turn off the transmitter and receiver and remove the propeller.
2. Connect a bind plug between D20/SDA and ground. Never short 3.3 V or 5 V to
   ground.
3. Power the receiver. It detects the grounded D20/SDA pin at startup and enters
   bind mode.
4. Start the transmitter while holding its Bind button (D9).
5. Wait for the receiver's bind confirmation, then release the transmitter
   Bind button.
6. Turn off the receiver. The bind-plug startup intentionally cannot transition
   into flight during the same power cycle.
7. Remove the bind plug and restart the transmitter and receiver normally.
8. Verify rudder direction, every other surface, throttle safety, and failsafe
   before flight.

For electrical safety, receiver firmware latches bind-plug mode at boot and
keeps D20/SDA as a high-impedance input for that entire power cycle. After
storing the bind code, the receiver remains disarmed and rejects normal control
packets until it is restarted without the plug. The original D10 receiver Bind
button remains supported.

### Arming And Failsafe

The receiver requires packets no older than 150 ms and commanded throttle at
or below 1060 µs for 300 ms before normal arming. Control surfaces can still
move while throttle is disarmed; the LED alone does not prove every output is
working.

Failsafe behavior:

- No stored bind code: reject all normal control packets, remain disarmed, and
  hold failsafe outputs.
- Wrong bind code: reject the packet and remain in the existing failsafe/link
  state.
- While armed, up to 1 second without accepted packets: retain the last commands.
- Between 1 and 1.2 seconds: show lost-link status while retaining outputs.
- Beyond 1.2 seconds: disarm and force throttle to 1000 µs.
- Beyond 3 seconds: command RUD, AIL, and ELE to 1500 µs.
- Rearming requires fresh matching packets and low throttle again.

The 1500 µs failsafe positions are fixed receiver values, not the model's
trimmed neutrals or endpoint midpoints. Verify the resulting surface positions
on mixed aircraft. These timings describe normal operation, not intentional
ESC calibration override.

The receiver directly outputs servo pulses in software. Avoid adding blocking code to the receiver loop.

### Receiver Battery Monitor

The receiver has disabled battery monitor code on `A4`.

Do not enable it unless the PCB has a proper voltage divider. Current values in firmware assume:

- Top resistor: `10k`
- Bottom resistor: `1k`

Battery telemetry back to the transmitter is not currently implemented. The control link is currently one-way.

### Receiver Firmware Flashing

Compile:

```bash
arduino-cli compile --fqbn adafruit:samd:adafruit_feather_m0 "rx_firmware"
```

Upload:

```bash
arduino-cli upload -p /dev/cu.usbmodem1101 --fqbn adafruit:samd:adafruit_feather_m0 "rx_firmware"
```

## Desktop Transmitter Configurator

Main file:

```text
fram_gui_models.py
```

Purpose:

- Read and write model slots in external FRAM or M0 internal flash.
- Edit model name, bind code, rates, expo, subtrim, endpoints, and reverse flags.
- Select conventional, V-tail, or elevon mixing per model.
- Reverse V-tail rudder input independently of elevator.
- Configure per-model aileron-to-rudder mixing.
- Download and flash released transmitter and receiver firmware.
- Read and assign the V3 Instructor / Student role through the ESP USB port.
- Set active model.
- Import/export model JSON files.

### Running The GUI

Packaged apps are available for macOS ARM64, Windows x64, and Raspberry Pi OS
ARM64 from the release link above. The macOS package is signed and notarized.
For source execution:

Install dependencies:

```bash
cd "RC-Airplane"
python3 -m pip install -r requirements.txt
```

Run:

```bash
python3 fram_gui_models.py
```

### Connecting The GUI

1. Put transmitter into USB config mode by holding both D9 and D5 low at boot.
2. Launch GUI.
3. Select serial port.
4. Click Connect.
5. Select a model slot and click **Load From Radio**.
6. Edit its fields; double-click channel names or table values to edit them.
7. Click **Save To Radio**. This saves the selected slot but does not make it active.
8. Click **Set Active** to choose the flight model. The active slot has a `*`.
9. Disconnect and restart in normal flight mode to use the saved model.

The connection status identifies the active storage backend as `fram` or
`internal flash`.

### Model Fields And Backups

The table displays **Throttle, Aileron, Elevator, Rudder**. Internal channel
numbers are **0=RUD, 1=AIL, 2=ELE, 3=THR**. Changing a channel name changes its
label only; it does not remap a receiver output. Custom labels are stored on
the computer and included in JSON exports.

| Field | Meaning |
| --- | --- |
| Rate | 0–100% control-axis response; applies unless High Rates Active is checked |
| Expo | −100–100%; positive values soften response around center |
| Subtrim | −500–500 µs; mixed-axis behavior is described in the aircraft section |
| Endpoints | Output minimum/maximum; use 1000–2000 µs with the production receiver and keep minimum below maximum |
| Reverse | Reverses the output's control direction; for mixed surfaces it applies after mixing |
| High Rates Active | Overrides all four rates to 100% |
| DR Switch | Stored field; the production flight loop does not implement a physical dual-rate switch |
| New Bind | Generates a new model bind code; save and rebind its receiver afterward |

**Endpoint compatibility:** the GUI currently permits 800–2200 µs, but the
production receiver accepts only 1000–2000 µs on every channel. If even one
command is outside that receiver range, it rejects the entire packet. Keep
all output endpoints within 1000–2000 µs for this release; a wider GUI range
does not mean the receiver supports wider pulses.

**Export Model (.json)** reads the saved radio slot, not unsaved editor values.
Save first, then export each model you need to back up. **Import Model (.json)**
writes directly into the selected slot, including its bind code; choose the
slot carefully and load it afterward to inspect the result. Import does not
select the active flight model. Older JSON files default to conventional
with V-tail rudder-input reversal off.

### Updating transmitter or receiver firmware from the configurator

Open **Firmware Update** in **Altitude Unknown RC Configurator** and click
**Check GitHub**. The configurator reads the
latest release's firmware manifest and verifies each downloaded image with its
published SHA-256 checksum. Choose **Transmitter — both processors** after a
transmitter firmware/protocol change so the SAMD21 and ESP32-C3 remain
compatible. For the aircraft-mixing change from the matched 2026.09.01.5
baseline, **Transmitter M0 only** is sufficient; the ESP32 and receiver do not
perform the aircraft mix. Choose **Receiver** to update Receiver V4 directly.

The updater supports Altitude Unknown Transmitter V3 and Receiver V4 hardware.
It downloads these release assets automatically:

- `altitude-unknown-tx-v3-samd21.uf2` for the transmitter M0.
- `altitude-unknown-tx-v3-esp32c3.bin` for the ESP32-C3.
- `altitude-unknown-rx-v4-samd21.uf2` for the receiver M0.
- `altitude-unknown-rx-v4-samd21.bin` for receiver BOSSA fallback.
- `transmitter-firmware-manifest.json` containing the expected SHA-256 values.

The official desktop builds include the ESP flashing tool and a trusted TLS CA
bundle; the user does not need Arduino IDE, Arduino CLI, or a separate Python
installation to perform an update.

For a transmitter M0 update, select its USB port. The configurator requests
bootloader mode automatically, detects the UF2 drive, and copies the verified
firmware. For a receiver update, select its USB port. Newer receivers mount an
`RCRXBOOT` UF2 volume and receive the verified receiver UF2 directly. Original
Receiver V4 boards retain their 2016 SAM-BA bootloader; if UF2 is not detected,
the configurator automatically falls back to its bundled BOSSA programmer and
the verified serial image. Current receiver firmware accepts an exact guarded
bootloader request and forces outputs safe before resetting. This also works
when USB-only power leaves the LoRa hardware unavailable. Double-tap RESET is
only a recovery fallback. The Firmware Update tab is vertically scrollable so
the flash button remains reachable on smaller or scaled displays. For the
ESP32-C3 stage, connect the small **ESP** USB
connector, select its serial port, and follow the prompt. If automatic ESP
bootloader entry fails, hold BOOT, tap RESET, release BOOT, and retry.

Receiver firmware older than the automatic-update bridge may require one final
manual-reset/Arduino upload. Later receiver updates can then be completed from
the configurator without reaching the RESET button.

Receiver flashing may erase the stored bind code. Rebind the receiver after an
update and complete a propeller-off control, direction, throttle-safety, and
failsafe check before flight.

Before updating, power off the aircraft, remove the propeller, and export
important models. Do not disconnect USB during a write. After both stages,
power-cycle the transmitter and bench-check its model selection, roles, stick
directions, endpoints, failsafe behavior, and buddy-box handoff before flight.

If the transmitter uses the M0 internal-flash model-storage fallback, firmware
flashing may reset its stored models. Export important models first. External
FRAM models normally survive, but they must still be inspected after updating.

The first updater-enabled, end-to-end validated release is
`transmitter-gui-v2026.08.30.2`. Its signed/notarized macOS, Windows x64, and
Raspberry Pi ARM64 packages and both firmware images were built by GitHub
Actions. Live latest-release discovery, TLS download, and checksum validation
passed for both images. A physical Transmitter V3 was then updated through the
GUI, power-cycled, and reported working normally in the post-update bench test.

Release `transmitter-gui-v2026.09.01.1` is the minimum receiver safety baseline.
It includes the receiver UF2 and prevents an unbound receiver from
accepting every otherwise-valid control packet. The correction was verified on
physical hardware: the unbound receiver rejected packets and stayed in
failsafe, then stored bind code `9905` during an explicit bind and accepted
matching packets afterward. Flight-control surface movement was confirmed.

The bind-plug pin was subsequently moved to **D20/SDA** in commit `6d8f184`,
included in `transmitter-gui-v2026.09.14`. Follow the D20/SDA instructions in this
manual for this release; do not use older rudder-port bind-plug instructions.

Release `transmitter-gui-v2026.09.01.4` adds automatic support for newer
receiver hardware with the `RCRXBOOT` UF2 bootloader while preserving the
original Receiver V4 BOSSA path. It also makes the Firmware Update tab
scrollable. The newer receiver was flashed through the GUI, rebound, and passed
the flight-control bench test before publication.

Release `transmitter-gui-v2026.09.01.5` restores both rudder buttons to
press-release rudder trim. They no longer emit the temporary experimental
autolevel commands. The production receiver retains the current packet's
reserved auxiliary byte for Tx/Rx layout compatibility but deliberately ignores
it and contains no autolevel control path. Because this corrects the over-air
packet match, update the transmitter M0 and receiver from the same release,
rebind, and complete the full propeller-off control and failsafe test before
flight. Physical testing confirmed the rudder trims and matched production
Tx/Rx controls operate correctly after the `.5` update.

Release `transmitter-gui-v2026.09.14` adds aircraft selection and independent
V-tail rudder-input reversal to the configurator and transmitter firmware.
The pilot confirmed V-tail operation on the bench and in flight. Elevon
coverage is currently automated testing only. This release does not change
the production over-air control packet format.

### Assigning Instructor or Student Role

With current V3 firmware, only the ESP32-C3 USB cable is needed:

1. Keep the aircraft powered off.
2. Start the transmitter in Config, Simulator, or Setup mode.
3. Open the **Instructor / Student** tab.
4. Select the ESP32-C3 USB port and click **Connect**.
5. Confirm the displayed MAC address, M0 mode, and existing role.
6. Select **Set as Instructor (Master)** or **Set as Student**.
7. Confirm the warning and wait for readback verification.
8. Restart the transmitter before normal operation.

The firmware refuses role changes in Flight or Bind mode. When either processor
has older firmware that does not report M0 mode, connect the M0 USB port through
the Models header as a Config Mode safety proof, or update both processors.

Never leave both radios assigned as Master or both assigned as Student.

The config protocol uses text commands such as `PING`, `INFO`, `READ`, `WRITE`, and `RANGE`.

## Mission Planner

The RC project also contains a standalone mission planner:

```text
mission_planner/mission_planner.py
```

Run:

```bash
cd "mission_planner"
python3 mission_planner.py
```

The upload button is currently a placeholder until a flight-controller mission protocol is defined.

## Known Good Fallback Points

Important commits/tags:

| Commit / Tag | Meaning |
| --- | --- |
| `rc-lag-flight-proven-2026-06-17` | Flight-proven low-lag RC control behavior |
| `rc-trims-flight-proven-2026-06-17` | Flight-proven physical trims |
| `675cd95` | Adds throttle timer buzzer warning |
| `transmitter-gui-v2026.09.01.5` | Validated matched production Tx/Rx packet layout and rudder trim |
| `transmitter-gui-v2026.09.14` | Aircraft-type GUI and firmware; V-tail bench/flight-tested, elevons awaiting hardware testing |

## Troubleshooting

### Transmitter Does Not Send

- Check throttle was low at boot.
- Make sure not in setup mode or config mode.
- Check LoRa wiring: CS D8, IRQ D3, RST D4.
- Reflash transmitter firmware.

### Receiver Does Not Move Servos

- Confirm the receiver has been explicitly bound to the active transmitter
  model. A receiver with no stored bind code intentionally rejects all control
  packets.
- If the receiver was just flashed, repeat the complete bind sequence; flashing
  may clear its stored bind code.
- If the bind code was changed in the GUI, save it to the transmitter, restart
  the transmitter, and rebind the receiver.
- Confirm transmitter is sending normal packets.
- Check receiver LED state.
- Keep all channel endpoints within 1000–2000 µs. An out-of-range command on
  any channel causes the receiver to reject the entire packet.
- Check servo output pins and power.

### Only One Mixed Surface Moves

- V-tail needs the RUD and ELE receiver sockets; elevons need AIL and ELE.
- Confirm the aircraft type is saved in the active model and the M0 has current firmware.
- Check both output endpoint ranges and the relevant axis rates/trims.
- Move pitch and yaw/roll separately; simultaneous commands can cancel on one
  output or reach its limit.
- With power off, swap servos between sockets to determine whether the symptom
  follows a servo or an output. Return to the known wiring afterward; this is
  a diagnostic step, not a general direction correction.

### V-tail Pitch Is Correct But Yaw Is Backward

Toggle **Reverse rudder input (V-tail only)**, save, and restart in flight mode.
Keep the wiring and output reversal settings that give correct pitch. Recheck
trim. If only the aileron-to-rudder contribution is backward, change the sign
of **Rudder amount** instead.

### Desktop GUI Cannot Connect

- Confirm transmitter is in USB config mode, not normal Flight Mode. Hold Bind
  and Aileron Trim Right while powering the transmitter, then release them
  after startup.
- Refresh serial ports.
- Select the **Altitude RC TX M0** `/dev/cu.usbmodem...` port on macOS, not the
  separate ESP32-C3 port.
- Replug a known data-capable USB cable if the port is missing. Double-tap
  RESET enters the bootloader for recovery; it does not enter Config Mode.
- Close other serial monitors or configurator instances using the same port.

Seeing a serial device in the list does not prove Config Mode is active. The
GUI connects only after the M0 configurator service answers its `PING` command.

### Firmware Update Cannot Check GitHub

- Confirm the computer has internet access and GitHub is reachable.
- Use configurator release `transmitter-gui-v2026.08.30.2` or later; older
  releases do not contain the firmware manifest and verified images.
- Do not bypass a checksum failure. Retry the download and report the release
  tag and error if it fails again.

### SAMD21 UF2 Drive Does Not Appear

- Confirm the larger M0 USB connector is attached.
- Double-tap the SAMD RESET button when the updater prompts.
- Try a known data-capable USB cable and connect directly to the computer.

### ESP32-C3 Flashing Cannot Connect

- Confirm the small ESP USB connector and its serial port are selected.
- Hold BOOT, tap RESET, release BOOT, and retry.
- Do not select the **Altitude RC TX M0** port for the ESP32-C3 stage.

### Buzzer Too Quiet

Current hardware uses a low-side 2N7002 driver on D11. The software cannot significantly increase volume beyond pattern/frequency changes. Future hardware revisions should consider a louder active buzzer, a better piezo transducer, or a stronger driver.

## Maintenance Notes

Update this manual whenever:

- Pin mappings change.
- Boot modes change.
- New setup menu items are added.
- Firmware warning behavior changes.
- GUI fields or serial protocol change.
- A new flight-proven fallback tag is created.
