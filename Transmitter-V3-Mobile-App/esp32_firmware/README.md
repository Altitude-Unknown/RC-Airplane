# ESP32 BLE Bridge

`tx_v3_ble_bridge/tx_v3_ble_bridge.ino` exposes the private BLE service expected by the Flutter application and forwards complete command lines to the SAMD21 UART.

Before compiling or connecting hardware:

1. Confirm the exact ESP32 module and Arduino board target.
2. Confirm and set `SAMD_RX_PIN` and `SAMD_TX_PIN` from the source schematic/netlist.
3. Confirm `CONFIG_ENABLE_PIN` and its physical authorization behavior.
4. Refactor the SAMD21 configuration parser to accept its hardware UART as described in `ARCHITECTURE.md`.
5. Ensure the transmitter cannot emit normal LoRa control traffic while wireless configuration writes are accepted.

The UUIDs must remain synchronized with `app/lib/protocol/ble_transport.dart`.

The prototype uses encrypted BLE characteristics and requires bonding. A production pairing UX still needs a confirmed display/physical-button design on the transmitter.
