# RC Airplane System Manual

Living manual for the RC airplane transmitter, receiver, and transmitter configurator GUI.

Last updated: 2026-08-21

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
| USB simulator mode | Hold AUX/trainer by itself at boot | No LoRa or trainer forwarding; USB HID joystick active |

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

1. Hold receiver bind button low at boot.
2. Put transmitter in bind mode by holding D9 low at boot.
3. Receiver waits for bind packet and stores bind code to flash.
4. After bind is stored, receiver exits bind mode.

### Arming And Failsafe

The receiver requires a fresh link and low throttle before arming.

Failsafe behavior:

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

- Confirm receiver is bound or no bind code is stored.
- Confirm transmitter is sending normal packets.
- Check receiver LED state.
- Check servo output pins and power.

### Desktop GUI Cannot Connect

- Confirm transmitter is in USB config mode, not normal mode.
- Refresh serial ports.
- Try `/dev/cu.usbmodem...` on macOS.
- Replug USB or double-tap reset if the port is missing.

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
