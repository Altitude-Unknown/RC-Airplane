# Rx V4 to custom ArduPlane SBUS bridge

AI-assisted implementation, installed 2026-10-09. Dedicated radio-to-flight-controller firmware; standalone PWM outputs and Rx-side stabilization are not used.

Wiring with USB power on both boards:

- Rx TX PB22 (MCU pin 37) -> FC J4 pin 28 (PC7 / USART6 RX).
- Rx ground -> FC J4 pin 30.
- Leave J4 pin 29 (5 V servo rail) disconnected for this USB test.

Output is **non-inverted SBUS**, 3.3 V, 100000 baud, even parity, two stop bits. It requires the matching custom BOREALIS V2 firmware serial-search setting; an ordinary inverted SBUS-only input needs an inverter. FC SERIAL2_PROTOCOL is set to 23 (RC input).

Input channel order is roll, pitch, throttle, yaw, CH5, CH6. This is independent of the FC servo output order, which remains throttle, aileron, elevator, rudder. Only correctly sized, range-valid radio packets matching the stored bind code are accepted. SBUS sends at 100 Hz while packets are fresh and stops after 300 ms without accepted control packets. It never substitutes centered valid controls for lost radio input. ArduPlane retains responsibility for arming and configured RC failsafe actions.

Receiver flash was fully backed up in receiver-before-sbus.bin. receiver-sbus.bin is the installed image with the existing bind code 7741 retained at its new flash-storage location. A normal source rebuild produces unbound flash storage; rebind after an ordinary Arduino upload.

To bind with a plug: disconnect Rx USB, short J1 pin 12 (SDA / PA22) to J1 pin 10 (GND), reconnect USB, then start the transmitter's normal bind procedure. After binding, disconnect USB, remove the plug and reconnect. SDA stays an input with pullup; I2C is not started. Bind-plug startup blocks control output until a restart even after storing the bind code. The D10 button method remains available. Firmware ID: rx-sbus-v2-bindplug. Physical plug detection still requires the user to install the plug for a hardware check.

Validation completed: Arduino Feather M0 compile; flash write/read verification; live USB firmware status and accepted radio packets; C++ packing test for 16000 channel values with an independent bit decoder and endpoint assertions; matching FC hardware build and uploader verification. Physical signal timing, FC channel movement, transmitter-loss behavior, range and power testing remain pending.

Source build:

```
arduino-cli compile --fqbn adafruit:samd:adafruit_feather_m0 rx_arduplane_sbus
clang++ tests/rx_sbus/packing-test.cpp -o /tmp/rx-sbus-pack-test
/tmp/rx-sbus-pack-test
```

Firmware is a bench bridge until the pending hardware tests pass.

## Corrected build

The earlier bind-plug upload accidentally included a desktop C++ test with its own main(), which prevented Arduino USB/startup from running. The desktop test now lives outside the sketch directory in tests/rx_sbus. The corrected ELF entry point was inspected and calls USB initialization, setup(), and loop(). Flash verification alone did not catch this startup error.

## Connected spare hardware test

Corrected firmware enumerates on USB and accepts the preserved bind code 7741. With the documented signal and ground wires connected, ArduPlane reported healthy receiver input. A 35-second movement capture recorded 361 RC samples: roll 1345..1792, pitch 1000..1922, throttle 1001..2000, yaw 1000..1962, CH5 1000..2000, CH6 fixed at 1000. All 362 receiver-health samples were healthy. CH6 operation and full roll endpoints remain unverified; radio calibration is still required. Evidence: fc-connected-status.json and fc-channel-movement.json.

Transmitter-off/on check passed: FC RC health changed healthy -> lost -> healthy. It reported throttle failsafe, short RC failsafe, long RC failsafe switching to RTL, then failsafe clearing after reception resumed. FC remained disarmed. This verifies loss detection and recovery on the bench; it does not validate airborne failsafe flight behavior or exact detection latency. Evidence: fc-link-loss-test.json.
