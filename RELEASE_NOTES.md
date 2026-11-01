Adds flight controller updates to the configurator, and makes one receiver
firmware work on both the Rx V4 and the receiver built into the ASCEND flight
controller.

**Flight controller (ArduPlane) updates.** The Firmware Update tab has a new
Flight controller option. Connect the flight controller's USB port, select it
(only ArduPilot boards are listed), and click Download and Flash Latest. The
configurator restarts the board into its bootloader and reads which board it
is. It then writes only the firmware built for that board, so firmware for a
different board is never installed. Parameters and calibrations are kept.
This release includes ArduPlane for the ASCEND flight controller Rev.2
(ASCENDFCRev2). Its GPS is not supported yet. Set `AHRS_ORIENTATION=14` for the
standard mounting (components up, I2C header forward).

**One receiver firmware (v7).** The receiver still drives servos directly on a
Rx V4, with the same arming and failsafe. It now also sends SBUS to a flight
controller on PB22, which is how the ASCEND board's built-in receiver talks
to ArduPlane. Update that receiver through its own USB connector. Receiver
updates clear the bind code: rebind, then check every control, the throttle
safety and the failsafe with the propeller removed before flight.

The receiver's automatic bootloader entry now also works on receivers with
the UF2 bootloader. The older-receiver fallback no longer opens unrelated USB
devices.

Transmitter firmware is unchanged in behavior from 2026.10.19, and
mode-linked surface rates are retained.

Includes macOS Apple Silicon ARM64, Windows x64 and Raspberry Pi ARM64 apps,
plus firmware and the SHA-256 manifest.

Validation: 32 release tests passed. On ASCEND FC Rev.2 hardware:
- The receiver updated through the configurator.
- ArduPlane received healthy SBUS with full stick ranges.
- The configurator flashed the flight controller in 23 seconds, keeping all
  parameters.

Not yet tested: Rx V4 servo outputs with receiver v7. Bench-check a Rx V4
before flight.
