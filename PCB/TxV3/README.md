# Transmitter V3 Hardware Notes

Source: corrected `Transmitter V3.pdf`, placed in the repository on 2026-07-22.

Schematic SHA-256 used for these notes:

```text
6cffe3a52656e084a8a13fb49afad3dcc04b2a79fb75967d9b633aad44a85ab6
```

## Connected prototype boards

On 2026-07-22, two boards enumerated over USB as `Altitude Unknown RC TX M0`:

```text
/dev/cu.usbmodem101
/dev/cu.usbmodem1101
```

Both use the Arduino target:

```text
AltitudeUnknown:samd:altitude_rc_tx_m0
```

Ports are assigned dynamically and must not be treated as permanent board IDs.

## Confirmed SAMD21 pin map

| Function | Arduino pin | SAMD21 pin/net | Notes |
| --- | --- | --- | --- |
| Throttle | A3 | PA04 | Measured assembled harness; low is about 1019-1020 ADC |
| Aileron | A1 | PB08 | |
| Elevator | A2 | PB09 | |
| Rudder | A0 | PA02 | Measured assembled harness; matches the V2 order |
| Rudder trim left | A4 | PA05 | Active low |
| Rudder trim right | D12 | PA19 | Active low |
| Aileron trim left | D1 | PA10 | Active low |
| Aileron trim right | D5 | PA15 | Active low |
| Elevator trim up | D2 | PA14 | Active low |
| Elevator trim down | D0 | PA11 | Active low |
| Bind button | D9 | PA07 | Active low |
| Auxiliary button | D10 | PA18 | Active low |
| Trainer button | D7 | PA21 | Active low |
| Buzzer gate | D11 | PA16 | Drives Q1, active high |
| User LED | D13 | PA17 | Schematic labels this `User LED` |
| Battery meter | D6 net | PA20 | Analog-capable MCU pin, but not ADC-enabled as D6 in the current Arduino variant |
| LoRa chip select | D8 | PA06 | RFM95 NSS |
| LoRa interrupt | D3 | PA09 | RFM95 DIO0 |
| LoRa reset | D4 | PA08 | Active low reset input |
| LoRa MOSI | MOSI | PB10 | Arduino SPI MOSI |
| LoRa MISO | MISO | PA12 | Arduino SPI MISO |
| LoRa SCK | SCK | PB11 | Arduino SPI clock |
| I2C SDA | SDA | PA22 | FRAM and LCD connector |
| I2C SCL | SCL | PA23 | FRAM and LCD connector |
| ESP UART TX | not exposed | PB22 / TXD | Connects to ESP32-C3 RXD |
| ESP UART RX | not exposed | PB23 / RXD | Connects to ESP32-C3 TXD |

The corrected V3 schematic labels throttle on A0 and rudder on A3, but both
assembled prototype harnesses tested on 2026-07-22 behave in the V2 order shown
above. Firmware and the basic diagnostic therefore use throttle A3 and rudder
A0. Revalidate this on the next PCB/harness revision rather than carrying the
prototype exception forward blindly.

## Other confirmed hardware

- MCU: ATSAMD21G18
- Wireless coprocessor: ESP32-C3-WROOM-02-H4
- FRAM: MB85RC256V, 32 KiB I2C memory
- LoRa: RFM95W-915S2-class module, 915 MHz design
- LCD connector includes SDA, SCL, 3.3 V, and ground
- Separate SAMD21 and ESP32-C3 USB connectors
- Separate reset/boot controls for the SAMD21 and ESP32-C3

## Important core mismatch

The installed `AltitudeUnknown:samd:altitude_rc_tx_m0` board currently inherits
the `feather_m0_express` variant. Its `Serial1` uses PA10/PA11 (D1/D0), which are
V3 trim buttons. The V3 PCB routes its ESP UART to PB22/PB23 instead. PB22/PB23
are not entries in that variant's Arduino pin table.

Do not use `Serial1` for the V3 ESP bridge. Before BLE/UART work, add a V3 board
variant that exposes PB22/PB23 and configures their SERCOM5 UART function, or
provide an equivalent carefully reviewed low-level driver. This should be a
separate V3 target so existing V2 boards do not change behavior.

The battery meter has a related variant issue: PA20 has ADC capability in the
MCU, but Arduino D6 is declared as a digital/timer pin with no ADC channel in the
current inherited variant. The V3 variant should expose this signal as an analog
input.

## Safe bring-up order

1. Upload `TxV3_Basic_Diagnostic` to one board only.
2. Verify all four gimbal values and nine buttons over USB.
3. Confirm the I2C scan finds FRAM (normally `0x50`) and any attached display.
4. Confirm the RFM95 initializes and is then placed in sleep; do not transmit.
5. Test the buzzer only through an explicit USB command.
6. Repeat on the second board and compare results.
7. Add and validate the V3 Arduino variant for PB22/PB23 and the battery ADC.
8. Port the existing flight firmware using the V3 pin map.
9. Add ESP UART configuration mode with LoRa transmission inhibited.

## Prototype 1 bring-up log

Tested on `/dev/cu.usbmodem1101` on 2026-07-22 with
`TxV3_Basic_Diagnostic`:

| Test | Result | Notes |
| --- | --- | --- |
| Firmware upload and verify | Pass | 42,616 flash bytes verified |
| USB serial | Pass | Stable diagnostic stream at 115200 baud |
| RFM95 SPI/init | Pass | Radio initialized, then placed in sleep without transmitting |
| Throttle ADC | Pass | Approximately 0-1020; resting reading about 509 |
| Aileron ADC | Pass | Approximately 0-1022; center about 500-501 |
| Elevator ADC | Pass | Approximately 0-1022; center about 514-516 |
| Rudder ADC | Pass | Approximately 0-1021 |
| Rudder-left trim | Pass | Released 0, pressed 1 |
| Rudder-right trim | Pass | Released 0, pressed 1 |
| Bind button | Pass | Released 0, pressed 1 |
| Auxiliary button | Pass | Released 0, pressed 1 |
| Elevator trims | Investigate | Both read continuously pressed (1) |
| Aileron trims | Investigate | Both read continuously pressed (1) |
| Trainer button | Investigate | Reads continuously pressed (1) |
| I2C scan | Expected empty | FRAM and LCD were not installed |
| Buzzer | Not tested | Required 100-ohm series resistor was not installed |

The five continuously-low inputs did not change during one-second button holds.
Because `INPUT_PULLUP` was enabled, each affected MCU input is electrically low,
not merely floating. Inspect switch orientation, solder bridges, and continuity
to ground on D2, D0, D1, D5, and D7 before flight firmware uses these inputs.

## Prototype 2 bring-up log

Tested on `/dev/cu.usbmodem1101` on 2026-07-22 after disconnecting Prototype 1:

| Test | Result | Notes |
| --- | --- | --- |
| Firmware upload and verify | Pass | Same diagnostic image as Prototype 1 |
| USB serial | Pass | Stable at 115200 baud |
| RFM95 SPI/init | Pass | Initialized and placed in sleep without transmitting |
| Four gimbal ADC inputs | Pass | All reached approximately 2-1023 |
| Rudder-left trim | Pass | Released 0, pressed 1 |
| Rudder-right trim | Pass | Released 0, pressed 1 |
| Bind button | Pass | Released 0, pressed 1 |
| Auxiliary button | Pass | Released 0, pressed 1 |
| Elevator trims | Investigate | Both continuously low, matching Prototype 1 |
| Aileron trims | Investigate | Both continuously low, matching Prototype 1 |
| Trainer button | Investigate | Continuously low, matching Prototype 1 |
| I2C and buzzer | Not tested | FRAM and buzzer series resistor not installed |

The identical five-input failure on both boards is explained by a confirmed
schematic wiring error. The four failing trim switches and trainer switch are
drawn horizontally. Their signal nets connect to switch pins 1 and 3, while
ground connects to pins 2 and 4. The footprint's internally common pairs are
1-2 and 3-4, so both internal pairs directly short the signal to ground even
while the switch is released.

The working rudder trims, bind, and AUX switches are drawn vertically and use
the correct grouping: signal on pins 1 and 2, ground on pins 3 and 4. Revise the
horizontal switch connections to use that same electrical grouping regardless
of their graphical orientation:

```text
Signal: pins 1 + 2
Ground: pins 3 + 4
```

Using only one pin from each internally common side is also electrically valid,
but assigning both pads per side preserves mechanical and routing flexibility.

Affected nets are D2 (elevator up), D0 (elevator down), D1 (aileron left), D5
(aileron right), and D7 (trainer).

### Prototype trace-cut repair test

After trace cuts on one prototype, all nine inputs returned to the correct
released state instead of being held low. Elevator up/down, aileron left,
rudder left/right, bind, and AUX produced independent released-to-pressed
transitions. Aileron right and trainer also produced transitions, but D5 and D7
changed together on every observed activation. Those two nets remain electrically
coupled and require continuity inspection before the repair is considered complete.

The D5/D7 coupling was subsequently traced to a PCB short and cut out. On this
prototype revision the physical trainer input (D7) is intentionally unusable.
AUX (D10) will serve as the trainer button for prototype firmware. The CAD source
is being corrected for the next PCB revision (V4). Do not carry this AUX-as-trainer
workaround into the V4 pin map without revalidating the corrected board.

After removing the short, aileron-right (D5) was retested with three presses. It
now transitions independently from released 0 to pressed 1 while D7 remains 0.

## ESP32-C3 bring-up

Tested on 2026-07-22 through the ESP module's separate native USB connector.

| Test | Result | Notes |
| --- | --- | --- |
| USB enumeration | Pass | Enumerated as an ESP32 Family Device using native USB Serial/JTAG |
| ROM download loader | Pass | ESP32-C3 revision v0.4, 40 MHz crystal, Wi-Fi and Bluetooth LE reported |
| Flash write and verification | Pass | Four-megabyte merged diagnostic image written and hash verified |
| Application boot | Pass | Chip left the ROM loader and executed the diagnostic from flash |
| BLE advertising | Pass | `TxV3 ESP Test` was visible on a Google Pixel |
| Arduino USB console | Investigate | Application serial text was not observed; BLE proves the diagnostic is running |

The initially missing GPIO9/BOOT pull-up prevented reliable normal boot and was
installed during bring-up. USB download mode also required GPIO8 high while
GPIO9 was held low at reset. A temporary approximately 10-kohm GPIO8 pull-up was
used for the successful loader connection. The next PCB revision should include
reviewed strapping for GPIO8, GPIO9, and GPIO2 per Espressif's ESP32-C3 hardware
design guidance.

Diagnostic source:
`TxV3_ESP32_Diagnostic/TxV3_ESP32_Diagnostic.ino`. It exercises native USB,
chip/flash identification, and BLE advertising only; it does not access the
SAMD UART, FRAM, or LoRa radio.

### SAMD21 to ESP32-C3 UART test

The internal two-way UART link passed on 2026-07-22 at 115200 baud:

```text
SAMD PB22 / SERCOM5 PAD2 TX -> ESP GPIO20 / RXD
SAMD PB23 / SERCOM5 PAD3 RX <- ESP GPIO21 / TXD
```

The inherited Arduino variant does not expose PB22/PB23, so the M0 diagnostic
configures SERCOM5 and the PB22/PB23 peripheral mux directly. The M0 sent
numbered `M0_PING` messages once per second and the ESP returned matching
`ESP_PONG` messages. Continuous observed replies through sequence 412 completed
in 2-3 ms with no timeouts or mismatches during the final sample.

Test firmware:

- `TxV3_M0_ESP_UART_Test/TxV3_M0_ESP_UART_Test.ino`
- `TxV3_ESP_UART_Test/TxV3_ESP_UART_Test.ino`

The ESP test advertises as `TxV3 UART Test`. Neither test initializes or
transmits with the LoRa radio, and neither accesses FRAM.

### Current production role and mixing protocol

The production targets are `TxV3_Full_M0` for the SAMD21 and
`TxV3_Buddy_ESP32` for the ESP32-C3. The M0 sends an internal operating-mode
heartbeat every 500 ms. The ESP reports that mode over native USB and accepts a
persistent role change only in Config, Simulator, or Setup mode. Student
ESP-NOW transmission and master forwarding require a fresh Flight heartbeat.

The desktop configurator therefore needs only the ESP USB cable for guarded
role changes when both processors have current firmware. The intended radio
assignment is ESP `80:F1:B2:F0:1A:E8` as Master and
`80:F1:B2:F0:1A:D0` as Student.

Per-model aileron-to-rudder mixing uses the existing model record's reserved
bytes, so its size and CRC layout remain compatible. Legacy models load with
mixing disabled. The GUI provides an enable control and a signed -100% to +100%
amount; negative values reverse the mix direction.

### Prototype 2 final button repair

After applying the switch trace repairs to Prototype 2, elevator up/down,
aileron left/right, rudder left/right, bind, and AUX all produced correct
released-to-pressed transitions. The first test still showed aileron-right D5
activating trainer D7 at the same time. After the additional D5/D7 isolation
cut, aileron-right was retested and changed independently from 0 to 1 and back
to 0 while trainer remained 0. Physical trainer remains intentionally unused;
AUX is the prototype trainer input.

### Prototype 2 ESP32-C3 investigation

Prototype 2's ESP32-C3 did not enumerate over native USB during the 2026-07-22
bring-up. The following checks passed:

- ESP 3.3-V supply and EN voltage
- RESET low while pressed and high when released
- GPIO8 held high for download mode
- GPIO9/BOOT high when released and low when pressed
- USB VBUS, ground, D- to GPIO18, and D+ to GPIO19 continuity
- No measured D+/D-, D+/ground, or D-/ground short
- GPIO21/TXD continuity to SAMD PB23/RX

A short at the battery connector was found after its charge LED remained on
without a battery. The short was removed and the charge LED then turned off.
Another suspected short near a repair jumper was also cleared. Do not connect a
battery until USB-powered bring-up is complete.

The M0 was flashed with
`TxV3_M0_ESP_UART_Bridge/TxV3_M0_ESP_UART_Bridge.ino` to provide a transparent
115200-baud USB-to-SERCOM5 bridge. With the ESP straps set for download mode,
esptool received no ROM response through this independent UART path. The ESP
also produced no UART boot message. Reflowing, washing, and drying all ESP
module pins did not immediately change either result.

The board will remain completely unpowered overnight to dry. The next session
should retry native USB enumeration, forced USB download mode, and the UART ROM
query in that order. If all three still fail, replace the ESP32-C3 module and
repeat the safe ESP and M0-to-ESP diagnostics.
