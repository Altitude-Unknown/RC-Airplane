# Session memory: 2026-10-10 — V2 ArduPlane mounting orientation

Confirmed by user in-airplane bench testing: **AHRS_ORIENTATION=14
(Yaw270Roll180)** for components facing up, ARM-button edge toward nose,
servo-connector edge toward tail. Current sensor hwdef uses ROTATION_NONE;
this parameter finding is relative to that firmware mapping.

Trainer button switches Manual/FBWA; user reports all functions work in
Manual. Initial attitude roll jumped to extremes and ailerons saturated.
Flipping the PCB upside down plus rotating it 90 degrees restored response.
Setting 10 (Yaw90Roll180) gave smooth but reversed corrections. Screenshot
in nose-high/right-bank pose showed ATTITUDE roll=-0.6801097393 rad,
pitch=-0.5236927271 rad (about -39/-30 degrees). Setting 14 fixed physical
control-surface correction directions according to user. No servo reversals
or firmware changes made during this session.

Post-change numerical telemetry, reboot completion, six-position calibration
and level calibration were not independently confirmed. Calibration and
remaining flight-readiness checks from 2026-10-09 remain pending unless the
user supplies further results. Do not treat this bench result as flight
clearance.

Detailed finding also recorded in
ArduPilot-PCB/bringup-v2/servo-enabled/README.md.

## GPS-free training plan and setup

User plans Manual/FBWA stabilization for initial student training without GPS,
then adds GPS for autonomous student missions. No airspeed sensor planned,
but future support must remain available. User confirmed errors cleared after
advised AHRS_EKF_TYPE=0, ARMING_SKIPCHK=8 (GPS lock only), GPS1_TYPE=0;
no independent full readback. ARSPD_TYPE=0/ARSPD_USE=0 advised for absent
airspeed sensor. No settings changed through tools or firmware rebuilt.

Created servo-enabled/training-no-gps.parm and NEW_BOARD_SETUP.md for repeat
builds, linked from README. Preset import has not been hardware-tested.
Per-board calibration, radio/output configuration and GPS-free failsafes
remain required. Existing receiver-loss behavior selects RTL and must be
reconfigured before GPS-free flight. Incomplete QGC parameter download still
not independently resolved. For later GPS missions restore AHRS_EKF_TYPE=3
and ARMING_SKIPCHK=0 and validate GPS/navigation/failsafes.

Parameter diagnostic afterward: with QGC closed, FC returned all 869
parameters in 3.18 s with no missing indices. Readback confirmed orientation
14, EKF type 0, skip-check mask 8, GPS type 0 and airspeed type 0. Relaunched
QGC 5.1 with full diagnostic logging; its parameter FTP download parsed and
initial load completed successfully at ~3.5 s. Earlier failure not reproduced;
root cause unconfirmed. No firmware/settings/cache changes made. QGC left
running with diagnostic logging to /private/tmp/borealis-qgc-parameter.log.
Read-only capture saved in servo-enabled/parameter-download-diagnostic.json;
diagnostic notes added to NEW_BOARD_SETUP.md.

## Future PCB direction

User would like a future PCB combining FC, LoRa receiver and u-blox M9N GPS
with chip antenna, used inside a 3D-printed airplane. Discussed feasibility,
antenna-specific ground plane/keepout, interference and motor/servo/radio
transmit testing, an optional external GPS antenna connection and optional
GPS population for training builds. Suggested retaining the separate receiver
MCU and existing SBUS interface for the first combined revision. No schematic
or firmware implementation requested or performed. Exact antenna part number
and LoRa module/frequency remain to be established.

## End-of-session outstanding work

Calibration after final mounting, radio endpoints/CH6, GPS-free failsafe
configuration, preset import verification and experimental IMU flight timing
remain pending. Full parameter transfers succeeded independently and in QGC;
earlier failure root cause remains unknown. No flight-ready claim.
