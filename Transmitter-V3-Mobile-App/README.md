# Transmitter V3 Mobile App

Cross-platform iPhone and Android configurator for the Altitude Unknown Transmitter V3.

## Goal

Provide the capabilities of the existing desktop `fram_gui_models.py` configurator over a wireless connection through the transmitter's onboard ESP32.

Planned mobile features:

- Discover and connect to Transmitter V3
- Read transmitter identity, protocol version, and FRAM status
- List all 16 model slots and show the active model
- Create, edit, copy, delete, import, and export models
- Edit model name and bind code
- Edit channel rates, expo, subtrim, endpoints, and reversal
- Select the active model
- Validate model CRC before displaying or saving data
- Clearly report connection, read, write, and validation failures

## Proposed implementation

- **Mobile UI:** Flutter/Dart for a shared iOS and Android codebase
- **Phone transport:** Bluetooth Low Energy (BLE)
- **Wireless bridge:** ESP32 firmware exposing a private BLE GATT service
- **Transmitter transport:** UART between the ESP32 and SAMD21
- **Configuration storage:** Existing FRAM layout managed by the SAMD21

BLE is preferred over Bluetooth Classic because iOS does not expose arbitrary Classic Bluetooth serial-port profiles to normal applications. Wi-Fi can be added later for firmware updates or large transfers, but it is unnecessary for the current 32 KiB FRAM protocol.

## Repository status

An initial functional Flutter application and ESP32 bridge are implemented. The Android debug APK builds successfully. iOS source is generated and configured for Bluetooth, but a local iOS build still requires installing full Xcode and CocoaPods.

Implemented app features:

- BLE scan, connection, service discovery, and `PING` verification
- Transmitter `INFO` and 16-slot FRAM model list
- Model name, bind code, rates, expo, subtrim, endpoints, reverse, and active-rates editing
- Active-model selection and protected deletion
- CRC validation and bounds checking
- Save followed by complete byte-for-byte read-back verification
- JSON export through the platform share sheet
- JSON import from the clipboard
- Shared Dart codec tests matching the existing desktop/SAMD21 FRAM layout

The app cannot communicate with hardware until the SAMD21 configuration parser is exposed on the V3 hardware UART and the ESP32 pin constants are confirmed.

See [ARCHITECTURE.md](ARCHITECTURE.md) for the protocol, safety rules, and implementation plan.

## Intended layout

```text
Transmitter-V3-Mobile-App/
├── README.md
├── ARCHITECTURE.md
├── app/                 Flutter application
├── esp32_firmware/      BLE-to-UART bridge firmware
├── protocol/            Shared protocol documentation and test vectors
└── tests/               Codec, transport, and integration tests
```

## Build and test

```bash
cd app
flutter pub get
flutter test
flutter analyze
flutter build apk --debug
```

Generated Android APK:

```text
app/build/app/outputs/flutter-apk/app-debug.apk
```

## Important dependency note

The current BLE implementation uses `flutter_blue_plus` under its nonprofit/personal-use license selection. Before commercial distribution, review that package's license and either obtain the appropriate license or replace the transport plugin. This does not affect the FRAM codec or app UI architecture.
