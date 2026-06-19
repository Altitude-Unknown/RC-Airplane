# RC Airplane SAMD21 Bootloaders

Custom UF2 bootloaders for the RC Airplane transmitter and receiver PCBs.

Hardware assumptions:

- MCU: ATSAMD21G18A-AU
- Clock: external 32.768 kHz crystal
- USB: native USB D+ / D-
- Boot/status LED: Arduino D13 / `PIN_PA17`

## Files

### Transmitter

- `tx/bootloader-altitude_rc_tx_m0-v4.0.0.bin`
  - Use this for first-time bootloader flashing with Atmel-ICE/SWD.
- `tx/update-bootloader-altitude_rc_tx_m0-v4.0.0.uf2`
  - Use this only after a UF2 bootloader is already installed.

### Receiver

- `rx/bootloader-altitude_rc_rx_m0-v4.0.0.bin`
  - Use this for first-time bootloader flashing with Atmel-ICE/SWD.
- `rx/update-bootloader-altitude_rc_rx_m0-v4.0.0.uf2`
  - Use this only after a UF2 bootloader is already installed.

## Expected UF2 Drive Names

- Transmitter: `RCTXBOOT`
- Receiver: `RCRXBOOT`

## Note

These bootloaders currently use internal lab USB VID/PID placeholders. Before
sharing broadly, assign official project USB IDs.
