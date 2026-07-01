# Walach Aviation Transmitter Configurator — Build & Run

This repository contains a Tkinter-based desktop GUI to manage TX models via serial (FRAM). The main script is `fram_gui_models.py`.

For the full RC transmitter, receiver, and GUI operating manual, see [MANUAL.md](MANUAL.md).

Prerequisites
- Python 3 (3.8+ recommended)
- `tkinter` (usually bundled with CPython)
- `pyserial` (install via `pip`)

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
pyinstaller --onefile --windowed --name "WalachTransmitterConfigurator" fram_gui_models.py

# Result: dist\WalachTransmitterConfigurator.exe
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
pyinstaller --windowed --name "Walach Aviation Transmitter Configurator" fram_gui_models.py

# Result: dist/Walach\ Aviation\ Transmitter\ Configurator.app
```

Raspberry Pi OS (64-bit) — released executable

Download `Walach-Aviation-Transmitter-Configurator-Raspberry-Pi-ARM64.zip`
from the GitHub release, unzip it, and run:

```bash
chmod +x "Walach Aviation Transmitter Configurator"
./"Walach Aviation Transmitter Configurator"
```

This build is for 64-bit Raspberry Pi OS on ARM64 hardware (such as Pi 3, 4,
or 5). It is not compatible with 32-bit Raspberry Pi OS.

Notes & troubleshooting
- Serial ports differ by OS: Windows uses `COMx`; macOS uses `/dev/tty.*` or `/dev/cu.*`.
- If `tkinter` is missing on Windows, install the official Python installer from python.org and enable tcl/tk.
- If PyInstaller misses imports, run the CLI build with `--hidden-import=serial.tools.list_ports` or adjust the generated spec.

Key files
- [requirements.txt](requirements.txt)
- [fram_gui_models.spec](fram_gui_models.spec)
- [MANUAL.md](MANUAL.md)

If you want, I can run a macOS build here (will install PyInstaller) or prepare a Windows build recipe/CI file. Which would you like next?
