Adds flashing from a local firmware file to the configurator's Firmware
Update tab. Firmware source code is unchanged from 2026.11.14.

**Flash a file from your computer.** Under **Firmware source**, choose
**Local file on this computer**, select one processor, then **Choose File…**.
**Latest GitHub release** is still the default and works as before.

| Processor | File |
|---|---|
| Transmitter M0 | `.uf2` |
| Transmitter ESP32-C3 | merged `.bin` |
| Receiver | `.uf2`, or `.bin` for an original SAM-BA Receiver V4 |
| Flight controller | ArduPilot `.apj` |

A local file has no release checksum, so the configurator checks that it suits
the selected processor before writing anything. It rejects:

- UF2 files for another chip family, or ones that would overwrite the SAMD21
  bootloader.
- ESP images for another chip, and application-only ESP `.bin` files (no
  partition table) that would leave the transmitter unable to boot.
- Receiver `.bin` files not built to start at 0x2000.
- Flight controller `.apj` files whose board ID does not match the connected
  board.

The confirmation shows the file name and its full SHA-256. The file is read
again just before flashing and refused if it has changed. The configurator
never deletes a local file. "Transmitter — both processors" needs two files,
so it is only available for GitHub releases.

After flashing a local transmitter build, read back the active model and check
its rate selector, CRC, subtrims and mode mapping, as after any update.

**Fix:** the fallback for original Receiver V4 boards (SAM-BA) could stop
with an error after flashing because a Python import was missing. This is now
fixed.

Includes macOS Apple Silicon ARM64, Windows x64 and Raspberry Pi ARM64 apps,
plus firmware and the SHA-256 manifest. The firmware is rebuilt from the same
source as 2026.11.14, and the flight controller image is the same
ArduPilot `02d6a7b964` file.

Validation: 50 release tests passed, including 13 new tests of the
local-file checks. A GUI check from source passed: the source and processor
controls work, and the released ASCEND FC `.apj` is recognised as board ID
65093. Not yet tested: flashing hardware from a local file.
