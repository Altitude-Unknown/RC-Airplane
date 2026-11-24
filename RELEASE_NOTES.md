The transmitter and receiver firmware now use the boards' own USB IDs, and
the configurator recognizes them. Flight controller firmware is unchanged
from 2026.11.19.1.

**New USB IDs.** The RC Airplane Transmitter is now `1209:A5C0` and the
receiver `1209:A5C1`. These are free IDs for open-source hardware from
[pid.codes](https://pid.codes). They replace a lab placeholder (the
transmitter) and the Adafruit Feather M0 ID (the receiver). The receiver now
shows up on the computer as **Altitude RC RX M0**. Each board's bootloader (the
new [Altitude SAMD21 Bootloader](https://github.com/Altitude-Unknown/Altitude-SAMD21-Bootloader))
uses the same ID.

**The configurator finds both boards by their new IDs.** It still recognizes
boards flashed with older firmware, so update them as usual from **Firmware
Update**. Settings and models on the transmitter are kept.

The transmitter and receiver firmware is otherwise unchanged: mode-linked
rates, Bind trim-save, buttons, and alarms work as in 2026.11.19.
