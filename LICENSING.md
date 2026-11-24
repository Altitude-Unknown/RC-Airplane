# Licensing

This repository is open source and open hardware.

| What | License | File |
| --- | --- | --- |
| Software and firmware (transmitter, receiver, RC Configurator, ASCEND Flight Control, tools, tests) | MIT | [LICENSE](LICENSE) |
| Hardware designs (schematics, PCB layouts, Gerbers, and their PDFs, for example `PCB/`, `Transmitter*.pdf`, `Rx-*.pdf`, `Receiver-*.pdf`, `Sensor-Module*.pdf`) | CERN Open Hardware Licence v2 – Permissive (CERN-OHL-P-2.0) | [LICENSE-HARDWARE](LICENSE-HARDWARE) |

Copyright (c) 2026 Altitude Unknown, except as noted below.

## Parts under other licenses

These keep the licenses of the projects they come from:

- **`ArduPilot-PCB/`**: ArduPilot source files, board definitions (`hwdef`),
  drivers, and firmware builds (`.apj`, `.bin`, `.hex`) for the flight
  controller are ArduPilot code, licensed under the
  [GNU GPL v3](https://www.gnu.org/licenses/gpl-3.0.html) (each source file says
  so in its header). The flight controller PCB designs are under CERN-OHL-P-2.0
  like the other hardware.
- **`ardupilot_uploader.py`**: based on the PX4 firmware uploader; BSD 3-Clause
  license (in the file).

## USB IDs

The RC Airplane Transmitter (1209:A5C0) and Receiver (1209:A5C1) use USB IDs
from [pid.codes](https://pid.codes), which assigns them to open-source hardware.
Their bootloader is the
[Altitude SAMD21 Bootloader](https://github.com/Altitude-Unknown/Altitude-SAMD21-Bootloader) (MIT).
