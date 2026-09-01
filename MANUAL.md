# RC Airplane System Manual

Living manual for the Altitude Unknown RC transmitter, receiver, and configurator GUI.

Last updated: 2026-09-01

## System Overview

The RC airplane system has three main pieces:

- **Transmitter V3 M0 firmware:** `PCB/TxV3/TxV3_Full_M0/TxV3_Full_M0.ino`
- **Transmitter V3 buddy firmware:** `PCB/TxV3/TxV3_Buddy_ESP32/TxV3_Buddy_ESP32.ino`
- **Receiver firmware:** `rx_firmware/rx_firmware.ino`
- **Desktop configurator GUI:** `fram_gui_models.py`

The master transmitter sends LoRa control packets to the receiver. A student
transmitter sends controls to the master over ESP-NOW; only the master M0 is
allowed to initialize LoRa. The receiver drives throttle, aileron, elevator,
and rudder outputs. Model setup data uses external FRAM when installed and the
M0 internal-flash fallback otherwise. It can be edited with the desktop GUI or
the transmitter OLED setup menu.

## Hardware Targets

Both Tx and Rx currently build for:

```text
adafruit:samd:adafruit_feather_m0
```

Common upload command:

```bash
arduino-cli upload -p /dev/cu.usbmodem1101 --fqbn adafruit:samd:adafruit_feather_m0 "path/to/sketch"
```

Port names vary by computer and OS.

## PCB Schematics

Hardware schematic PDFs are kept in this repo for quick reference:

| PCB | Schematic |
| --- | --- |
| Transmitter V2 | `Transmitter-V2-Schematic.pdf` |
| Receiver V4 | `Receiver-V4-Schematic.pdf` |

## Transmitter

### Transmitter Pinout

| Function | Pin | Notes |
| --- | --- | --- |
| LoRa CS | D8 | RFM95 chip select |
| LoRa IRQ | D3 | RFM95 interrupt |
| LoRa RST | D4 | RFM95 reset |
| Bind button | D9 | Hold at boot for bind mode |
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
| USB config mode | Hold both D9 and D5 low at boot | No LoRa transmit; desktop GUI can read/write FRAM |
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
elevator have trims. Throttle has no trim.

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

Changes are saved to the active radio storage immediately.

### Instructor / Student Operation

The V3 radios use persistent roles stored by the local ESP32-C3. The intended
assignment is:

| ESP MAC | Role |
| --- | --- |
| `80:F1:B2:F0:1A:E8` | Instructor / Master |
| `80:F1:B2:F0:1A:D0` | Student |

Normal trainer operation:

1. Power the student transmitter.
2. Power the master with throttle low.
3. Press and release AUX on the master to grant student control.
4. Press and release AUX again to take control back.
5. Moving any master stick immediately takes control back.
6. Student link loss also returns authority to the master.

The ESP requires a fresh M0 `FLIGHT` heartbeat before sending or forwarding
trainer controls. Role changes are accepted only while the M0 reports Config,
Simulator, or Setup mode.

### Aileron-to-Rudder Mixing

Mixing is stored separately for every model. In the desktop GUI, enable **Mix
aileron into rudder** and set **Rudder amount** from -100% to +100%.

- Start around 20-30%.
- Positive values mix rudder in the normal aileron direction.
- Negative values reverse the mix direction.
- Physical rudder input remains available and is added to the mix.
- The combined command is clamped before rudder rate, expo, reverse, subtrim,
  and endpoints are applied.

Save the model to the radio, remove the propeller, and verify direction and
combined full-stick travel before flight.

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

Compile the V3 M0:

```bash
arduino-cli compile --fqbn AltitudeUnknown:samd:altitude_rc_tx_m0 "PCB/TxV3/TxV3_Full_M0"
```

Compile the V3 ESP32-C3 with USB CDC enabled:

```bash
arduino-cli compile --fqbn esp32:esp32:esp32c3 --board-options CDCOnBoot=cdc "PCB/TxV3/TxV3_Buddy_ESP32"
```

Both processors on both transmitters must run matching current firmware for
single-cable role assignment and the mode interlock. ESP uploads retain the
role in NVS. Export important models before M0 flashing when internal-flash
storage is in use.

## Receiver

### Receiver Pinout

| Function | Pin | Notes |
| --- | --- | --- |
| LoRa CS | D8 | RFM95 chip select |
| LoRa IRQ | D3 | RFM95 interrupt |
| LoRa RST | D4 | RFM95 reset |
| Bind button | D10 | Hold low at boot for bind mode |
| Throttle output | A0 | Servo/ESC pulse |
| Aileron output | A1 | Servo pulse |
| Elevator output | A2 | Servo pulse |
| Rudder output | A3 | Servo pulse; also detects signal-to-ground bind plug at boot |
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

#### Binding With A Rudder-Port Bind Plug

This method avoids holding the receiver's D10 button while connecting the
aircraft battery:

1. Turn off the transmitter and receiver and remove the propeller.
2. Disconnect the rudder servo from the receiver.
3. Insert a standard bind plug that connects only the rudder connector's
   **signal** pin to its **ground** pin. Never short 5 V to ground.
4. Power the receiver. It detects the grounded A3 signal at startup and enters
   bind mode.
5. Start the transmitter while holding its Bind button (D9).
6. Wait for the receiver's bind confirmation, then release the transmitter
   Bind button.
7. Turn off the receiver. The bind-plug startup intentionally cannot transition
   into flight during the same power cycle.
8. Remove the bind plug, reconnect the rudder servo in the correct orientation,
   and restart the transmitter and receiver normally.
9. Verify rudder direction, every other surface, throttle safety, and failsafe
   before flight.

For electrical safety, receiver firmware latches bind-plug mode at boot and
keeps A3 as a high-impedance input for that entire power cycle. It never sends
rudder PWM while the plug may be grounding the signal. After storing the bind
code, the receiver remains disarmed and rejects normal control packets until it
is restarted without the plug. The original D10 receiver Bind button remains
supported.

### Arming And Failsafe

The receiver requires a fresh link and low throttle before arming.

Failsafe behavior:

- No stored bind code: reject all normal control packets, remain disarmed, and
  hold failsafe outputs.
- Wrong bind code: reject the packet and remain in the existing failsafe/link
  state.
- 0-1 seconds without packets: hold last surfaces, preserve staged motor behavior.
- Around 1 second: throttle kill.
- Around 3 seconds: surfaces neutralize.

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
- Configure per-model aileron-to-rudder mixing.
- Read and assign the V3 Instructor / Student role through the ESP USB port.
- Set active model.
- Import/export model JSON files.

### Running The GUI

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
5. Use Load From Radio / Save To Radio.

The connection status identifies the active storage backend as `fram` or
`internal flash`.

### Updating transmitter or receiver firmware from the configurator

Open **Firmware Update** in **Altitude Unknown RC Configurator** and click
**Check GitHub**. The configurator reads the
latest release's firmware manifest and verifies each downloaded image with its
published SHA-256 checksum. Choose **Transmitter — both processors** after a
transmitter firmware/protocol change so the SAMD21 and ESP32-C3 remain
compatible. Choose **Receiver** to update Receiver V4 directly.

The updater supports Altitude Unknown Transmitter V3 and Receiver V4 hardware.
It downloads these release assets automatically:

- `altitude-unknown-tx-v3-samd21.uf2` for the transmitter M0.
- `altitude-unknown-tx-v3-esp32c3.bin` for the ESP32-C3.
- `altitude-unknown-rx-v4-samd21.uf2` for the receiver M0.
- `transmitter-firmware-manifest.json` containing the expected SHA-256 values.

The official desktop builds include the ESP flashing tool and a trusted TLS CA
bundle; the user does not need Arduino IDE, Arduino CLI, or a separate Python
installation to perform an update.

For a transmitter M0 update, select its USB port. The configurator requests
bootloader mode automatically, detects the UF2 drive, and copies the verified
firmware. For a Receiver V4 update, select its USB port; the receiver accepts
an exact guarded bootloader request, forces outputs safe, and the configurator
uses its bundled BOSSA programmer to erase, write, and verify the serial image.
This also works when USB-only power leaves the LoRa hardware unavailable.
Double-tap RESET is only a recovery fallback. For the ESP32-C3 stage, connect
the small **ESP** USB
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

Release `transmitter-gui-v2026.09.01.2` adds the safe rudder-port bind-plug
startup described above. It was validated with an actual bind and control check
on the airplane before publication.

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
- Check servo output pins and power.

### Desktop GUI Cannot Connect

- Confirm transmitter is in USB config mode, not normal Flight Mode. Hold Bind
  and Aileron Trim Right while powering the transmitter, then release them
  after startup.
- Refresh serial ports.
- Select the **Altitude RC TX M0** `/dev/cu.usbmodem...` port on macOS, not the
  separate ESP32-C3 port.
- Replug USB or double-tap reset if the port is missing.

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
