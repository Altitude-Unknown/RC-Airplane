# Rx V4 Autopilot Experiment Notes

Date: 2026-06-30

## Goal

Use the flight-proven RC link as the base for an experimental receiver that can:

- auto-level the airplane when aileron and elevator sticks are released
- later add pressure-sensor altitude hold on the Rx V4 PCB

Pressure sensor from schematic:

- `U6 = MS5607-02BA03`

The proven receiver remains in:

- `rx_firmware/rx_firmware.ino`

The experimental receiver for this work is:

- `rx_V4__firmware/rx_V4__firmware.ino`

## What Is In The Experimental Sketch

- Same LoRa receive, bind, arming, and staged failsafe structure as the proven receiver
- LSM6DS IMU bring-up over I2C
- Complementary-filter roll/pitch estimate scaffold
- Stick-release detection using centered aileron and elevator
- Autolevel correction mixed into aileron and elevator outputs
- Pressure-sensor placeholder for `MS5607-02BA03`:
  - probes `0x76` and `0x77`
  - reports whether a baro device is seen
  - does not yet implement altitude calculation because we still need to confirm the live interface and reading path on hardware

## Current Autolevel Logic

Autolevel becomes eligible only when all of these are true:

- receiver is armed
- link is fresh
- not in bind mode
- not in ESC mode
- IMU is detected and sampling
- aileron and elevator sticks stay near center for `300 ms`

When active:

- rudder stays manual
- aileron gets a roll-level correction
- elevator gets a pitch-level correction
- throttle stays manual unless altitude hold is later enabled with a working baro driver

## Important Tuning Values

These are intentionally conservative starting points:

- stick deadband: `35 us`
- engage delay: `300 ms`
- level proportional gain: `7 us/deg`
- level damping gain: `1.4 us/(deg/s)`
- max aileron/elevator correction: `180 us`

These will almost certainly need tuning on the real airframe.

## Known Unknowns For Tomorrow

1. IMU axis orientation/signs still need to be confirmed on the real Rx V4 board.
2. Need to confirm how the `MS5607-02BA03` is wired on the live board and whether it responds on the expected bus/address.
3. Baro driver and altitude hold are not active yet.
4. This code compiles, but it has not yet been tested on hardware.

## Tomorrow's Bench Test Order

1. Flash `rx_V4__firmware`
2. Open serial monitor at `115200`
3. Confirm startup prints:
   - `RX V4 autolevel experiment ready`
   - IMU detected address
   - whether a baro device is seen on `0x76` or `0x77`
4. Move the receiver board by hand and verify:
   - `roll` and `pitch` change sensibly
   - signs match real board motion
5. Power the transmitter and verify packet reception
6. Let go of aileron/elevator sticks and watch:
   - mode change from `MANUAL` to `LEVEL`
   - correction values become non-zero when the board is tilted
7. Confirm servo directions are sensible before any flight test

## Before Any Flight

- confirm surface correction direction with propeller removed
- confirm no oscillation on the bench
- reduce gains or disable autolevel if signs are wrong
- leave altitude hold disabled until the pressure sensor driver is verified
