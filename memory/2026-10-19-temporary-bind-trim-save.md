# TEMPORARY TX V3 Bind -> ArduPlane trim-save — 2026-10-19

## REQUIRED REMOVAL WHEN TX V4 IS READY
User explicitly authorized this only as a temporary workaround to test the FC.
REMOVE Bind-as-trim-save when V4 is built/ready. Do not carry it into V4 firmware
or standard release images. Reassign a proper AUX input after validating V4's
pin mapping, and review/clear the FC RC6_OPTION accordingly.

Implementation uses build-only TXV3_TEMP_BIND_TRIM_SAVE=1; default is OFF.
V3 master normal operation only: CH6 replaces disabled D7/AUX2 output. CH5
must be toggle, high=MANUAL (mapping must be verified on actual FC). Hold D9
Bind for two seconds after a debounced release, producing one 500ms CH6-high
pulse; release required before another pulse. Mode change cancels it. Disabled
for student/trainer, simulator and boot throttle lock. Bind-at-boot and
Bind+D5-at-boot Config Mode are unchanged. No packet/model layout change.

ArduPlane RC6_OPTION=155 is TRIM RC/SERVO Save, not Copter Save Trim (5).
Local source requires MANUAL, valid RC, small roll/pitch input (at most 20% range),
and low rotation rate (<30 deg/s). Stores surface output neutrals AND RC
roll/pitch/yaw input centers, not throttle. Leave TX trims at their saved values
after saving; do not zero them again. FC emits 'trim complete' or rejection.
Cannot capture FBWA corrections or increase FBWA travel with this feature.

Pre-install full 32768-byte storage backup + decoded active model saved under
artifacts/temporary-bind-trim-2026-10-19/. TX identity
89CB5B3050304C59502E3120FF101E44, MASTER, Research slot0, CRC valid.
Subtrims all zero, CH5/CH6 stored toggle, ch5_rate_mode=0, selected rates
50/30/80/100 in RUD/AIL/ELE/THR order. Rate feature is OFF in current storage;
reported to user, no rate/model changes authorized by this installation.

Status: implementation/host tests prepared. Actual installation, FC parameter
assignment and live button validation remain pending; append results below.

Related flight findings: user found RX antenna unscrewed/missing after crash.
Strong explanation for link losses, not proof of the final dive/reset hypothesis
and does not explain TX startup hang. User zeroed TX subtrims and reports more
even surface movement. RC calibration/output neutral verification still needed.

## Installation progress
FC connected as BOREALISv2Servo, serial 2F0051000C51343034383933; heartbeat
disarmed. Readback confirms RC6_OPTION already 155, FLTMODE_CH=5,
FLTMODE1=5 (FBWA), FLTMODE6=0 (MANUAL). No FC parameter writes needed/made.
TX candidate compiled 70472 bytes, 16 host/regression tests passed.
Known TX bootloader identified; full 524288-byte CURRENT.UF2 backed up,
then temporary UF2 installed. Hashes/bootloader identity in artifact directory.
Awaiting Config Mode post-flash readback before live channel validation.

Post-install Config Mode readback passed: INFO reports temp_bind_trim_save=true,
CH6, 2000ms hold, 500ms pulse. All 32768 storage bytes identical to backup.
Full FC parameter request collected 870 indices while reported count changed
to 869, so generic downloader marked incomplete; do not claim complete full
parameter dump. Separate explicit RC1..4 MIN/MAX/TRIM + SERVO1..6 TRIM +
RC6_OPTION baseline succeeded. RC6_OPTION temporarily set from 155 to 0 and
read back for non-mutating pulse measurement. MUST RESTORE 155 after CH6-low
verification; current test status is captured in the artifact files.

## Bench pulse validation and FC restoration
User performed requested FBWA-side hold, MANUAL short tap, 5-second hold,
release/rehold. FC capture (20Hz) shows exactly two 2000us CH6 pulses of
0.501s and 0.500s; final CH6=1000. No repeats during held interval.
CH5-low samples kept CH6 low. FC mode history initially remained in prior
failsafe RTL after TX restart until switching to MANUAL; therefore requested
a final explicit FBWA-mode interlock test instead of calling that first interval
confirmed FBWA. Failsafe messages cleared with resumed RC. This bench event
does NOT establish the cause of the earlier flight crash.
RC6_OPTION restored to 155 with fresh CH6-low readback. All explicitly backed-up
RC1..4 MIN/MAX/TRIM and SERVO1..6 TRIM matched baseline; no trims saved by
the test. FC remains disarmed. Actual trim-write action intentionally not fired
on the bench. Firmware supports it through existing option155; final FBWA
interlock validation pending.

## Completed
Final test confirmed actual FC mode5/FBWA, CH5=1000 and CH6=1000 for
388 samples over 19.36 seconds while user held Bind.
No trim-complete message. TX installation, byte-identical model readback,
MANUAL pulse behavior and explicit FBWA interlock all verified. RC6_OPTION
restored=155; no RC/servo trims changed. TX/FC left in FBWA, disarmed.
Use: in MANUAL, establish small trim corrections, release sticks, hold Bind
2 seconds for one pulse. FC may reject save (failsafe/large input/movement);
only its 'trim complete' confirms persistence. Leave TX trims at saved values.
This does not resolve intermittent TX startup, range/power faults, missing
antenna consequences, RC calibration or disabled full-rate profile.
REMOVAL for TX V4 remains REQUIRED. No commit/push/release requested/performed.

## TX reliability follow-up
User subsequently found/reflowed a cold ESP32 power-pin joint with flux,
washed/dried board, and reports dark-LED startup issue absent so far.
Provisionally resolved pending continued tests; previous pull-up-only repair
was not the established fix. User plans flight testing 2026-10-20.

## FBWA full-rate override RESTORED later 2026-10-19
User explicitly requested restoring full rates. Original TX Config Mode INFO
confirmed temporary Bind feature still installed. Backed up current full FRAM,
changed only active Research slot0 rate-selector bits and CRC (storage offsets
313,314,315), then compared all 32768 bytes to expected image. CRC valid; every
other byte unchanged. CH5 low=FBWA now full RUD/AIL/ELE rates100%, CH5 high=
MANUAL retains selected50/30/80%; throttle remains100%. No firmware flash or
FC parameter changes. Verified current subtrims at this time were
[-50,0,-140,0] in RUD/AIL/ELE/THR order, NOT the earlier all-zero bench snapshot;
preserved exactly, with no inference about when/why user changed them.
Model memory backup/verification in artifacts/restore-fbwa-rates-2026-10-19/.
Rate selector was already0 before temporary Bind installation and entire memory
matched after that flash; cause of clearing not established. Older GUI can
clear unsupported field; use current configurator and preserve mode-linked
rate selection when saving model. Left TX in Config Mode; normal reboot with
throttle down required for radio operation. Storage readback verified; no new
live FC full-stick/end-to-end measurement performed during restoration.

## Source checkpoint publication
User subsequently requested commit/push of tonight's changes. Temporary
feature source/test, permanent full-rate preservation instructions, release
regression gate and session notes are included. No release tag or public
temporary firmware package is created by this source checkpoint.
