# BOREALIS V2 setup checklist

## Reusable training preset

[training-no-gps.parm](training-no-gps.parm) is a partial ArduPilot parameter
preset for the current BOREALISv2Servo firmware, LSM6DSO32 driver with
ROTATION_NONE, and non-inverted SBUS receiver bridge. Mount the PCB components
up, ARM-button edge toward the nose, servo-connector edge toward the tail.
Use this preset only on matching boards and firmware.

The preset configures GPS-free DCM stabilization, no compass or airspeed
sensor, no onboard logging backend, SBUS input, and TAER servo outputs.
ARMING_SKIPCHK=8 skips GPS lock only; all other arming checks remain enabled.
It preserves the ability to add GPS, compass, logging and airspeed hardware
later. No calibration values, radio endpoints, gains, servo reversals, mode
assignments or failsafe settings are copied between aircraft.

## New-board procedure

1. Remove the propeller. Verify assembly, power and connector wiring. Install
   the matching bootloader/application and receiver SBUS bridge using the
   existing bring-up instructions; bind the receiver to its transmitter.
2. Connect QGroundControl to the FC and obtain a complete parameter download.
   Export a backup before applying the preset. In Parameters, use Tools →
   Load from file (wording may vary) to load training-no-gps.parm. Review the
   changes, apply/save them, reboot and read back every listed setting. The
   preset has not yet been imported and validated as a file on hardware.
3. Check IMU and barometer health. Perform six-position accelerometer
   calibration, then level calibration with the airplane properly leveled.
   Let gyro calibration complete while stationary at startup.
4. Perform radio calibration with full stick travel. Confirm throttle low,
   stick centers, channel order, mode-switch channels and receiver recovery.
   Earlier testing left full roll endpoints and CH6 unresolved; check these
   explicitly on each installation.
5. Verify physical output mapping: 1 throttle, 2 aileron, 3 elevator, 4 rudder;
   5 and 6 unassigned. Set neutral, travel and reversals for the actual
   airframe. Verify correct stick response in Manual and FBWA.
6. Configure Manual/FBWA selection. With centered sticks, verify right-wing
   down commands right aileron down/left aileron up; nose-up commands elevator
   down. Numerical ATTITUDE roll is positive for right bank and pitch positive
   for nose-up. Check slow and rapid motion and return to level.
7. Configure GPS-free RC and GCS failsafes and bench-test transmitter loss,
   recovery and power cycles with the propeller removed. Existing testing
   switched to RTL on receiver loss; RTL is not a usable return-home strategy
   without GPS. This preset deliberately leaves failsafes for a separate
   reviewed configuration and is incomplete until that is done.
8. Verify servo power, electrical outputs, battery monitoring if installed,
   radio range and remaining pre-arm checks. Resolve incomplete parameter
   downloads. Validate the experimental IMU timing and complete aircraft
   tuning/flight validation before student use.

## Confirmed bench findings, 2026-10-10

- AHRS_ORIENTATION=14 (Yaw270Roll180) fixed attitude mapping and surface
  correction directions in the pictured mounting. Value 10 gave reversed
  roll and pitch signs. No driver change or servo reversal was needed.
- User reports the trainer button selects Manual/FBWA and Manual controls
  all airplane functions.
- User confirmed the reported errors cleared after the advised GPS-free
  settings (AHRS_EKF_TYPE=0 and GPS-lock-only ARMING_SKIPCHK=8). No independent
  full parameter readback was captured in this session.
- No airspeed sensor or GPS is installed. ARSPD_TYPE=0 and ARSPD_USE=0 are
  the no-airspeed baseline; confirm saved values on readback.

## Parameter download diagnostic, 2026-10-10

After quitting QGroundControl, a read-only MAVLink PARAM_REQUEST_LIST over
/dev/cu.usbmodem101 received all 869 advertised parameters in 3.18 seconds,
with no missing indices. Readback confirmed AHRS_ORIENTATION=14,
AHRS_EKF_TYPE=0, ARMING_SKIPCHK=8, GPS1_TYPE=0 and ARSPD_TYPE=0.
Evidence: parameter-download-diagnostic.json. ARSPD_USE was not in this
download's exposed parameter list; do not infer its saved value from the preset.

Relaunched installed QGroundControl 5.1 with diagnostic logging. Its own
parameter FTP download parsed successfully; log reported "Initial load
complete", "_parametersReady true", and "_ftpDownloadComplete : Parsed!"
at about 3.5 seconds. No firmware or parameter change, cache deletion, or
application-settings reset was needed. Earlier recurring failure was not
reproduced on this connection; root cause remains unconfirmed. If it recurs,
capture FactSystem.ParameterManager and FTP logging before resetting caches.

## Later GPS mission setup

Do not use the training preset unchanged for autonomous missions. Install and
configure GPS, restore AHRS_EKF_TYPE=3 and ARMING_SKIPCHK=0, and verify EKF
health, home establishment and outdoor GPS fix. Configure heading sources,
navigation modes, RC/GCS failsafes, RTL and mission behavior for the installed
hardware. Tune cruise throttle/pitch for operation without an airspeed sensor.
Validate navigation before student missions. If adding an airspeed sensor,
set its ARSPD_TYPE, calibrate it and select ARSPD_USE for the intended use.

A parameter preset does not program firmware or replace per-board calibration.
Keep a dated full parameter backup after commissioning each aircraft. Historic
defaults.parm and sbus/bench-hardware.parm describe earlier bring-up states;
they do not include this final training orientation/GPS configuration.
