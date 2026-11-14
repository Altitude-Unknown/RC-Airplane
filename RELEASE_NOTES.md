Makes the Bind button the trim-save button on every transmitter, and ships
the flight-tested airplane setup in the ASCEND flight controller firmware.

**Bind = trim-save.** Hold Bind for 1 second (in flight or on the ground) to
save your transmitter trims to the flight controller. The transmitter plays
two short chirps when it sends the request. In MANUAL the flight controller
saves the surface trims and stick centres together, then blinks its status
LED fast for 3 seconds. Outside MANUAL, with a stick far from centre or while
the airplane is rotating, it rejects the save and nothing changes. Leave the
transmitter trims where they are after a save. An unsaved trim stops the FC
arming ("Roll (RC1) is not neutral") and makes FBWA bank or pitch by itself;
the manual's trim section has the full procedure. This replaces the
temporary V3 Bind trim-save build. Channel 5 (D10) and Channel 6 (D7) stay
free.

**Flight-tested setup built in (ASCEND FC, ArduPilot `02d6a7b964`).** A
new board now comes up with the setup flown on 2026-11-14: CH5 low = FBWA,
high = MANUAL; roll limit 55°, pitch limit 30°; the AUTOTUNE roll and pitch
gains; trim-save on Channel 7. A builder only does the accelerometer and
compass calibrations, Level Horizon and the radio setup (bind, then trims
with the Bind button). The gains were tuned on one airframe; a different
airplane should run AUTOTUNE starting from them.

The flight controller image also adds the onboard GPS (u-blox over I2C,
EKF3, GPS lock required to arm) and a GPS LED that shows readiness: off = no
fix, blinking = fix but not yet ready to arm, solid = ready.

**Updating a board that is already set up:** firmware defaults only apply to
settings that were never saved. Your calibrations, trims, gains and mode
switch are kept. Check `RC7_OPTION` after updating and set it to 155 if it is
not; to use the new flight setup on an existing board, set the values listed
in the manual. Update all three: transmitter, receiver (the FC's built-in
receiver and any Rx V4) and flight controller. A receiver with older firmware
does not pass Channel 7, so the button does nothing. Re-bind the receiver
after updating it.

Includes macOS Apple Silicon ARM64, Windows x64 and Raspberry Pi ARM64 apps,
plus firmware and the SHA-256 manifest.

Validation: 37 release tests passed (including the new trim-save state
machine, channel 7 mapping and chirp tests). On the flown V4 airplane on
2026-11-14: transmitter, built-in receiver and flight controller updated with
backups and readbacks (transmitter model memory byte-identical, Research
model's full FBWA rates kept; receiver bind kept). Trim-save bench test:
1 s hold gave one 0.5 s channel 7 pulse; in MANUAL "trim complete", LED fast
blink and chirp; in FBWA rejected with trims unchanged. The release flight
controller image kept every saved parameter, and the firmware reports all 35
board defaults as listed.

Not yet tested: trim-save in flight, a factory-new board starting from these
defaults, and a standalone Rx V4 with this receiver firmware.
