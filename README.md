# Altitude Unknown RC Configurator — Build & Run

This repository contains a Tkinter-based desktop GUI to manage transmitter models over USB serial. The radio automatically uses external FRAM when installed or the SAMD21's internal-flash fallback when FRAM is absent. The main script is `fram_gui_models.py`.

For V3 buddy-box radios, the **Instructor / Student** tab can also read and set
the persistent role through the transmitter's separate ESP32-C3 USB port. With
current M0 and ESP firmware, only the ESP cable is needed: the M0 reports its
operating mode internally and the ESP rejects role writes unless that mode is
Config, Simulator, or Setup. Keep the aircraft powered off while assigning
roles. The GUI retains a two-cable Config Mode check for older firmware.

Each model also has an optional **Mix aileron into rudder** setting. Enable it
under Control Mixing and choose a signed percentage from -100% to +100%.
Positive values move rudder with aileron; negative values reverse the mix
direction. Start around 20-30%, save the model to the radio, and verify both
directions on the bench before flight.

The **Firmware Update** tab checks the project's latest GitHub release and can
update the V3 transmitter's SAMD21/M0, ESP32-C3, or both, and can update the V4
receiver. Firmware images are SHA-256 verified before flashing. The transmitter
M0 uses automatic 1200-baud UF2 bootloader entry. Newer receivers use their
`RCRXBOOT` UF2 bootloader; original Receiver V4 boards use a guarded USB
bootloader request and the bundled BOSSA programmer. A RESET double-tap remains
the recovery fallback. The update page scrolls on smaller or scaled displays so
the flash action remains reachable. The small ESP connector uses its native
serial/JTAG bootloader. Keep the aircraft powered off, remove the propeller,
and export important models before updating.

For the full RC transmitter, receiver, and GUI operating manual, see [MANUAL.md](MANUAL.md).

Prerequisites
- Python 3 (3.8+ recommended)
- `tkinter` (usually bundled with CPython)
- `pyserial` and `esptool` (installed by `requirements.txt`)

Install dependencies

```bash
python -m pip install -r requirements.txt
```

Run from source (macOS or Windows)

```bash
python "fram_gui_models.py"
```

Windows — build an executable (recommended for distribution)

1. Install Python 3 and `pip`.
2. Install PyInstaller:

```powershell
pip install pyinstaller
```

3. Build a one-file, windowed executable (run on Windows):

```powershell
pyinstaller --onefile --windowed --name "AltitudeUnknownRCConfigurator" fram_gui_models.py

# Result: dist\AltitudeUnknownRCConfigurator.exe
```

4. Test the exe by running it and verifying the serial port list and connectivity to your device (use COMx on Windows).

macOS — build an app (optional)

Option A — run from source (simplest):

```bash
python "fram_gui_models.py"
```

Option B — bundle with PyInstaller (build on macOS):

```bash
pip install pyinstaller
pyinstaller --windowed --name "Altitude Unknown RC Configurator" fram_gui_models.py

# Result: dist/Altitude\ Unknown\ RC\ Configurator.app
```

Raspberry Pi OS (64-bit) — released executable

Download `Altitude-Unknown-RC-Configurator-Raspberry-Pi-ARM64.zip`
from the GitHub release, unzip it, and run:

```bash
chmod +x "Altitude Unknown RC Configurator"
./"Altitude Unknown RC Configurator"
```

This build is for 64-bit Raspberry Pi OS on ARM64 hardware (such as Pi 3, 4,
or 5). It is not compatible with 32-bit Raspberry Pi OS.

Notes & troubleshooting
- Serial ports differ by OS: Windows uses `COMx`; macOS uses `/dev/tty.*` or `/dev/cu.*`.
- If `tkinter` is missing on Windows, install the official Python installer from python.org and enable tcl/tk.
- If PyInstaller misses imports, run the CLI build with `--hidden-import=serial.tools.list_ports` or adjust the generated spec.
- The GUI connection status reports `fram` or `internal flash` after connecting.
- Export important models before reflashing a radio that uses internal flash; a firmware upload may reset its model storage.

Key files
- [requirements.txt](requirements.txt)
- [fram_gui_models.spec](fram_gui_models.spec)
- [MANUAL.md](MANUAL.md)

If you want, I can run a macOS build here (will install PyInstaller) or prepare a Windows build recipe/CI file. Which would you like next?
