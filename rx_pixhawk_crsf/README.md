# Receiver V4 Pixhawk CRSF Prototype

This sketch adds a Pixhawk output path without modifying the known-working
standalone receiver firmware in `../rx_firmware/rx_firmware.ino`.

## Firmware choices

- Standalone airplane with receiver-driven servos: flash `rx_firmware`.
- Pixhawk/ArduPlane installation: flash `rx_pixhawk_crsf`.

The Pixhawk build receives the existing LoRa control packet and sends 16-channel
CRSF frames over the Receiver V4 UART header. The first four channels are:

1. Aileron / roll
2. Elevator / pitch
3. Throttle
4. Rudder / yaw

Channels 5 through 16 are initially centered.

## Receiver V4 UART

The shared SAMD21/Feather M0 mapping previously verified on Yellowstone is:

| Header function | SAMD21 pin | Arduino mapping |
| --- | --- | --- |
| TX | PB22, package pin 37 | D30, `Serial5` TX |
| RX | PB23, package pin 38 | D31, `Serial5` RX |

Do not use `Serial1`; on the Feather M0 core it maps to PA10/PA11 and does not
reach this header. The installed custom RX board target currently inherits the
`feather_m0_express` variant, which does not expose a `Serial5` Arduino object.
The sketch therefore configures the underlying SERCOM5 and PB22/PB23 pin mux
directly. This leaves the installed board package unchanged.

## Wiring

```text
Receiver TX/PB22  -> Pixhawk UART RX
Receiver RX/PB23  <- Pixhawk UART TX
Receiver GND      -- Pixhawk GND
Receiver 3.3 V    -- not connected to the Pixhawk UART power pin
```

Power the receiver from its normal regulated input. Do not connect its 3.3 V
header pin to a Pixhawk 5 V pin.

## Initial ArduPilot configuration

Select an unused full UART and set its corresponding parameters:

```text
SERIALx_PROTOCOL = 23
RSSI_TYPE = 3
```

The baud rate is selected automatically by ArduPilot for an RC-input serial
port. The receiver sends CRSF at 416666 baud.

## Failsafe behavior

CRSF channel frames are emitted at 100 Hz only while authenticated LoRa control
packets are fresh. They stop 300 ms after the last accepted packet. This is
intentional: ArduPilot must see receiver loss and execute its configured RC
failsafe instead of receiving indefinitely held or centered valid controls.

Configure and verify ArduPlane's RC failsafe before any powered-propeller test.

## Bench status

This is an unflown prototype. With no Receiver V4 and Pixhawk presently
available, the following remain required:

1. Confirm `Serial5` output on the Receiver V4 header with a logic analyzer.
2. Confirm 416666-baud timing and CRSF frame CRC/packing.
3. Confirm ArduPilot detects all four channels in Radio Calibration.
4. Confirm channel order, endpoints, centers, and direction.
5. Remove transmitter power and confirm ArduPilot reports RC failsafe after the
   receiver's 300 ms frame timeout.
6. Confirm receiver power behavior when the Pixhawk is powered by USB, its power
   module, and the airplane BEC.
7. Perform range and interference testing before flight.

The first prototype intentionally sends RC channels only. CRSF link-statistics
frames and return telemetry can be added after the basic control/failsafe path
is validated.
