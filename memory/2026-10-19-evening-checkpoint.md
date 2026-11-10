# Evening checkpoint — 2026-10-19 (latest state)

## Permanent user requirement: retain full rates in future updates
User explicitly says full FBWA rates must stay enabled through future updates.
Research slot0 now VERIFIED ch5_rate_mode=1: CH5 low/FBWA full100% surface
rates, CH5 high/MANUAL selected RUD/AIL/ELE50/30/80%; throttle100% unchanged.
Rate restoration changed only FRAM offsets313–315 (selector+CRC), with all
32768 bytes compared against expected readback. Evidence:
artifacts/restore-fbwa-rates-2026-10-19/verification.json.
Current subtrims RUD/AIL/ELE/THR=-50/0/-140/0, preserved; earlier all-zero bench
snapshot no longer describes the latest model. Do not zero/restore trims without
checking the current FC input calibration and servo neutral setup.
Temporary Bind feature remains installed. TX was left in USB Config Mode after
rate restoration, needs normal restart with throttle down for radio operation.

Why override was cleared remains UNCONFIRMED. It was already off before Bind
installation; that installation preserved every FRAM byte. Older GUI/model-file
handling can omit rate field. Do not attribute to a specific user action without
evidence. Current source GUI supports the field; use compatible tooling and
verify the active selection after edits/imports/updates.

Added repository AGENTS.md with mandatory preservation/readback instructions,
including future desktop/web shared code. Added release workflow gate running
existing rate/model/button/buzzer/updater tests before app and firmware builds.
The user subsequently requested committing/pushing these changes with the
evening checkpoint. Existing published 2026.10.19 release predates this gate. Old
installed apps cannot be fixed by notes/CI; avoid unsupported model editors.

## Temporary trim-save installation: REMOVE FOR TX V4
User authorized temporary Bind hold while testing FC. Opt-in build flag
TXV3_TEMP_BIND_TRIM_SAVE=1, defaultOFF for standard releases. Bind-at-boot and
Config combinations unchanged. In normal MASTER operation, CH5 high/MANUAL
permits debounced2s Bind hold -> single0.5s CH6 pulse; release to rearm.
Inhibited in FBWA, Student/trainer, simulator and throttle lock.
TX firmware backed up from identified bootloader, new image installed, INFO
capability and full model-memory preservation verified. Host/regression tests
passed. Live FC received two MANUAL pulses0.501s/0.500s; confirmed actual
mode5/FBWA with CH6 continuously1000 while Bind held.
FC ArduPlane4.7.1 d276581b BOREALISv2Servo, RC6_OPTION already155. Temporarily
set0 for pulse measurement, restored155 afterward and verified. All explicitly
backed-up RC1..4 MIN/MAX/TRIM and SERVO1..6 TRIM remained unchanged. Actual
trim write deliberately not triggered; only FC 'trim complete' confirms save.
MANUAL/validRC/small roll-pitch input/lowrotation required. Leave TX trims at
saved positions after saving. Does not capture FBWA stabilization corrections.
User expects TX V4 next week. REMOVE Bind trim-save for V4 and review RC6
assignment/AUX hardware mapping, but KEEP permanent full-rate support.

## Hardware/flight findings
User found RX antenna unscrewed and missing after today's flight; strong cause
candidate for link losses, not proof of final dive/hard roll causes. Replace
with proper antenna, inspect/secure connector and ground range/recovery test.
TX V3 ESP32 power pin had cold solder joint. User reflowed with flux/iron,
washed/dried board; no dark-D13 failure since repair so far. Provisionally
resolved pending repeated cold starts and continued tests. Earlier pull-up
jumper resolder alone was not the established fix. Startup ROLE wait remains
unbounded in firmware; simulator bypass explained symptom difference, but
startup hang alone does not explain in-flight interruptions.
FBWA-only flight: autolevel good; left/right asymmetry, limited authority,
hard roll/inversion and repeated control losses. Final motor-off glide,
reconnection/motor restart and nose-dive broke motor mount. FC reset suspected
by user but UNCONFIRMED. FC has no SD card/no flight logs. Actual AUTO/GPS
missions deferred until new FC PCB. User plans flight test2026-10-20.
Outstanding bench items: RC calibration/centers/endpoints with latest trims and
restored rate profile, surface direction/neutral/travel, power/connectors under
servo load, repeated cold starts and failsafe recovery. Capture computer
telemetry when available. Do not claim crash cause or entire system cleared.

## Apps/releases
Speaker works after100ohmR19 fitted; GUI Speaker Test user-verified.
Commit41aa1ef/tagtransmitter-gui-v2026.10.19 published Windows/Pi/firmware.
Mac build/sign passed but notarization blocked HTTP403: developer agreement
needs acceptance. User deferred. Rerun failed release jobs after acceptance,
verify/add Mac asset. No new temporary Bind firmware release published. Source/notes are included
in the user-requested evening commit; standard release builds leave it OFF.

See detailed files2026-10-19-flight-and-tx-debug.md and
2026-10-19-temporary-bind-trim-save.md; preserve unrelated RX/V92 changes.
