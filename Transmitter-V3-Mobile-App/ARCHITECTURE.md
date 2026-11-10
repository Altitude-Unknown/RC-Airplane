# Architecture and Protocol Notes

Updated: 2026-07-12

## Existing system

The desktop configurator connects to the SAMD21 transmitter firmware over USB serial at 115200 baud. The SAMD21 owns the FRAM and provides a line-oriented ASCII protocol:

```text
PING
INFO
RANGE
READ <address> <length>
WRITE <address> <hex bytes>
```

Typical responses are:

```text
PONG
{"mcu":"SAMD21G18","fram_size":32768,"proto":"1.0","role":"TX"}
RANGE 32768
DATA <hex bytes>
OK
ERR
```

The Transmitter V3 schematic contains an ESP32-WROOM-class module connected to the transmitter MCU through UART TX/RX. The exact net names, UART instance, baud rate, boot interaction, and whether USB and ESP32 can drive the same SAMD21 receive pin simultaneously must be confirmed in the source schematic before firmware is finalized.

## Recommended data path

```text
iPhone / Android app
        |
        | BLE GATT
        v
ESP32 BLE bridge
        |
        | 115200 8-N-1 UART
        v
SAMD21 configuration service
        |
        v
FRAM model storage
```

The ESP32 should not interpret or directly modify the FRAM binary layout. It should provide framing, authentication, connection management, and a transparent or nearly transparent command bridge. The SAMD21 remains the authority for bounds checking and FRAM access.

## Mobile BLE service

Use a private 128-bit GATT service with two characteristics:

- **Command characteristic:** phone writes framed requests to the ESP32
- **Response characteristic:** ESP32 sends indications or notifications containing framed responses

Indications are preferable for configuration writes because they are acknowledged at the BLE layer. Notifications may be used for status or diagnostic events.

The BLE layer must handle MTU fragmentation. A model slot is 64 bytes, represented by 128 ASCII hex characters plus response text, so it may not fit in the default BLE payload. Do not assume one BLE write or notification equals one command or response.

Recommended application frame:

```text
version       1 byte
message type  1 byte
sequence      2 bytes
payload size  2 bytes
payload       N bytes
CRC-16        2 bytes
```

The first prototype may carry the existing ASCII commands inside the payload. Sequence numbers prevent a delayed response from being matched to the wrong request. A single outstanding request at a time keeps the SAMD21 protocol deterministic.

## BLE identity and security

Configuration access can change control direction and endpoints, so the app must not write to any nearby transmitter without deliberate authorization.

Minimum requirements:

- Advertise a recognizable product service UUID, not a permanent owner name
- Require a physical action on the transmitter to enable pairing/configuration
- Use BLE LE Secure Connections with bonding where supported
- Display or confirm a short pairing code on the transmitter display if feasible
- Stop advertising or reject writes during normal flight operation
- Automatically leave configuration mode after inactivity
- Never permit model writes while RF control transmission is active unless the transmitter firmware explicitly makes that safe

Do not implement a fixed password embedded in both the app and ESP32 firmware.

## FRAM layout inherited from the desktop app

The mobile codec must match `fram_gui_models.py` and `tx_firmware/tx_config.h` byte-for-byte.

```text
FRAM size:          32768 bytes
Header address:     0x0000
Header size:        32 bytes
Models base:        0x0100
Model slot spacing: 64 bytes
Packed model size:  60 bytes
Maximum slots:      16
Magic:              0x54584346
Format version:     0x0001
Byte order:         little-endian
```

Header format:

```text
uint32 magic
uint16 version
uint16 total_slots
uint16 active_slot
uint32 used_bitmap
uint8  reserved[18]
```

Packed model format:

```text
char    name[16]
uint16  bind_code
int8    rates[4]
int8    expo[4]
uint8   dr_switch
uint8   active_rates
int16   subtrim[4]
uint16  endpoints[4][2]
uint8   reserved[6]      // reserved[0] contains four channel reverse bits
uint16  crc
```

CRC is CRC-16/CCITT with polynomial `0x1021` and initial value `0xFFFF`, calculated over the first 58 packed-model bytes.

## Validation rules inherited from the desktop configurator

- Model name: at most 15 UTF-8 bytes plus null terminator
- Bind code: masked to 15 bits
- Rate: 0 through 100
- Expo: -100 through 100
- Subtrim: -500 through 500
- Reverse flags: bits 0 through 3 of `reserved[0]`
- Endpoint limits: confirm exact safe bounds in transmitter firmware before mobile editing is enabled
- Read back and verify every saved model
- Reject a model with an invalid CRC unless the user explicitly chooses a safe recovery action

Channel indexes remain:

```text
0 Rudder
1 Aileron
2 Elevator
3 Throttle
```

The UI may display them in TAER order, but must retain the firmware indexes.

## Important V3 firmware change

The current SAMD21 firmware enters USB configuration mode only when two buttons are held during boot and then processes commands using the USB `Serial` object. V3 needs a transport-independent configuration service so the same parser can receive commands from either:

- USB serial for the desktop configurator, or
- Hardware UART connected to the ESP32 for the mobile app

Refactor the parser so command execution is shared and transport selection is explicit. Do not have USB and the ESP32 write to one parser concurrently. The firmware should enter a dedicated wireless configuration state through a physical control or authenticated request, stop or safely inhibit LoRa control transmission, and visibly indicate that the transmitter is not in normal flight mode.

## App screens

1. **Connect:** scan, identify transmitter, pair, and display connection state.
2. **Models:** show 16 slots, active slot, used/empty state, and CRC health.
3. **Model editor:** name, bind code, rates, expo, trims, endpoints, reverse flags, and active-rate selection.
4. **Transfer:** read, save with read-back verification, import/export JSON, duplicate, and delete.
5. **Device:** firmware/protocol versions, FRAM status, BLE identity, and diagnostics.

The app must stage edits locally. It should never write continuously as sliders move. Saving should show a summary, issue one bounded transaction, read it back, validate the bytes and CRC, then report success.

## Shared codec strategy

Implement the FRAM codec as a UI-independent Dart package with golden test vectors generated from the existing Python implementation. Required tests include:

- Header encode/decode
- Model encode/decode
- CRC calculation
- Every minimum and maximum field value
- UTF-8 truncation at byte boundaries
- Reverse-mask mapping
- Corrupt CRC detection
- JSON import/export compatibility
- Golden 64-byte slot equality between Python, Dart, and SAMD21 C++

## Development phases

1. Confirm V3 schematic UART pins, voltage levels, and ESP32 module variant.
2. Refactor the SAMD21 config parser to work over a hardware UART without changing the desktop protocol.
3. Implement an ESP32 UART loopback and command bridge.
4. Add BLE framing, pairing, physical authorization, and timeouts.
5. Create the Flutter project and shared Dart FRAM codec. **Initial implementation complete.**
6. Add codec golden tests before building model-editing UI. **Core tests complete; cross-language golden fixture still needed.**
7. Implement connection, model list, editing, and verified save flows. **Initial implementation complete.**
8. Test Android BLE behavior on hardware.
9. Test iOS BLE behavior on hardware and add required permission descriptions.
10. Perform power-loss, disconnect, malformed-message, duplicate-message, and interrupted-write testing.

## Decisions still needed

- Exact ESP32 module/variant and Arduino versus ESP-IDF firmware environment
- Exact UART nets and whether level shifting or series isolation is present
- How the user physically enables wireless configuration mode
- Whether configuration is allowed while LoRa transmission is active (recommended: no)
- Pairing confirmation method and transmitter display support
- Whether model JSON files should use platform sharing, cloud storage, or app-local storage only
- Product/app name, bundle identifiers, signing accounts, and store-distribution plan
- Commercial BLE plugin licensing decision before any paid or commercial distribution
