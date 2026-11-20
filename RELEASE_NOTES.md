Fixes transmitter M0 updates on brand-new boards. Firmware is unchanged from
2026.11.14 and 2026.11.15.

**Fix: new transmitter boards can be flashed straight after the bootloader.**
A transmitter M0 that has only had its UF2 bootloader installed has no
firmware to run, so it stays in the bootloader with its `RCTXBOOT` drive
already showing. The configurator waited for a *new* drive to appear, which
never happened, so the update failed. The "double-tap RESET" fallback failed
the same way, because the drive came back at the same location. Uploading any
sketch (such as Blink) first was the workaround.

The configurator now flashes a transmitter bootloader drive that is already
mounted, as the receiver update already did, and accepts the drive coming
back at the same location after a manual RESET double-tap. It only reuses a
drive that identifies itself as the transmitter, so a mounted receiver drive is
never written by mistake.

New board order: flash the bootloader with the Atmel-ICE, connect the M0 USB,
then in **Firmware Update** choose **Transmitter — both processors** (or
**Transmitter M0 only**) and click **Download and Flash Latest**.

Includes macOS Apple Silicon ARM64, Windows x64 and Raspberry Pi ARM64 apps,
plus firmware and the SHA-256 manifest. The firmware is rebuilt from the same
source as 2026.11.14, and the flight controller image is the same
ArduPilot `02d6a7b964` file.

Validation: 5 new tests of the bootloader-drive handling; all updater and GUI
tests pass. Not yet tested on hardware: the first new board flashed with this
release is the hardware test.
