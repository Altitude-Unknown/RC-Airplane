# Project Notes

## Initial build — 2026-07-12

### Objective

Create a shared iPhone/Android application that provides the model-management functions of the existing desktop `fram_gui_models.py` configurator through the Transmitter V3 onboard ESP32.

### Implemented

- Installed Flutter 3.44.6 and Android Studio 2026.1.1.10.
- Installed Android SDK platforms 35 and 36, build tools 36, NDK 28.2, and CMake 3.22.
- Generated Flutter Android and iOS projects under `app/`.
- Implemented BLE discovery, connection, GATT service discovery, and transmitter `PING` validation.
- Implemented the existing 32 KiB FRAM header and 60-byte model codec in Dart.
- Preserved the desktop/SAMD21 little-endian layout and CRC-16/CCITT calculation.
- Implemented the 16-slot model list and active-slot display.
- Implemented editing for model name, bind code, rates, expo, subtrim, endpoints, reversal, and active-rate selection.
- Implemented active-model selection and deletion protection for the active slot.
- Implemented model JSON export through the platform share sheet.
- Implemented JSON import from the platform clipboard.
- Implemented bounded writes with complete byte-for-byte read-back verification.
- Added Android BLE permissions and iOS Bluetooth usage descriptions.
- Added an initial ESP32 NimBLE-to-UART bridge sketch.
- Documented architecture, protocol, security expectations, and implementation phases.

### Verification

Completed successfully on 2026-07-12:

```text
flutter analyze
No issues found

flutter test
5 tests passed

flutter build apk --debug
APK built successfully
```

Test coverage currently includes:

- Standard CRC-16/CCITT check vector
- FRAM header round trip
- Complete model round trip
- Corruption/CRC failure detection
- Rejection of unsafe field ranges

The generated debug APK is located at:

```text
app/build/app/outputs/flutter-apk/app-debug.apk
```

Flutter build products are intentionally ignored and are not stored in Git. Rebuild the APK from source when needed.

### Confirmed architecture

```text
iPhone or Android
       |
       | Bluetooth Low Energy
       v
ESP32 BLE/UART bridge
       |
       | 115200 baud UART
       v
SAMD21 configuration parser
       |
       v
32 KiB transmitter FRAM
```

The ESP32 does not own or interpret the FRAM structure. The SAMD21 remains responsible for address bounds, configuration state, and the actual FRAM access.

### Hardware and firmware blockers

The mobile source is functional, but real-transmitter communication is not yet ready. Before flashing or hardware testing:

1. Confirm the ESP32 module variant and Arduino target.
2. Confirm the ESP32-to-SAMD21 UART pins from the editable schematic or PCB netlist.
3. Confirm the UART voltage levels and whether series isolation is present.
4. Define a physical action that authorizes wireless configuration.
5. Refactor the SAMD21 command parser so USB and hardware UART share command execution without concurrent access.
6. Add a dedicated wireless configuration state to the SAMD21.
7. Inhibit normal LoRa control transmission whenever wireless writes are accepted.
8. Display a clear configuration-mode warning on the transmitter.
9. Test BLE fragmentation, disconnects, timeouts, interrupted writes, and power loss on hardware.

The ESP32 sketch contains placeholder constants for the UART and configuration-enable pins. They must not be treated as confirmed wiring.

### iOS status

The iOS Flutter project and Bluetooth permission descriptions exist. A local iOS build has not been performed because full Xcode and CocoaPods are not installed. Completing iOS requires:

- Full Xcode installation
- Xcode first-launch setup and license acceptance
- CocoaPods
- Apple developer team and bundle-signing configuration
- Testing on a physical iPhone because BLE behavior cannot be fully validated in the simulator

### Dependency note

The initial BLE transport uses `flutter_blue_plus` with its personal/noncommercial license selection. Before commercial distribution, review its current license and either obtain the appropriate license or migrate the transport to a commercially compatible BLE package. The app controller, model codec, UI, and ESP32 protocol are isolated from the BLE implementation to make replacement practical.

### Next milestone

The next useful milestone is a complete hardware loop:

1. Confirm V3 UART pins.
2. Implement the SAMD21 hardware-UART configuration transport.
3. Compile and flash the ESP32 bridge.
4. Install the Android debug APK on a physical phone.
5. Verify `PING`, `INFO`, `RANGE`, header read, model read, model save, and read-back verification.
6. Confirm that entering configuration mode disables flight transmission and that leaving it restores normal operation safely.
