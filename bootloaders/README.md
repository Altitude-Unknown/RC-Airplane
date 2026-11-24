# RC Airplane SAMD21 Bootloaders

The USB bootloaders for the RC Airplane transmitter and receiver PCBs: the
[Altitude SAMD21 Bootloader](https://github.com/Altitude-Unknown/Altitude-SAMD21-Bootloader)
1.0.0 (MIT), written for these boards. It supports Arduino uploads over USB and
a UF2 drag-and-drop drive.

| Board | File | USB ID | UF2 drive |
| --- | --- | --- | --- |
| Transmitter | `tx/bootloader-rc_tx-v1.0.0.bin` | 1209:A5C0 | `RCTXBOOT` |
| Receiver | `rx/bootloader-rc_rx-v1.0.0.bin` | 1209:A5C1 | `RCRXBOOT` |

Install them with an Atmel-ICE and the
[Altitude SAMD21 Bootloader Flasher](https://github.com/Altitude-Unknown/SAMD21-Bootloader-Flasher),
which also protects the 8 KB bootloader area. Double-tap RESET to enter the
bootloader afterwards.
