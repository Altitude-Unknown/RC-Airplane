# TX startup fault, speaker release, and flight incident — 2026-10-19

## Resume tonight
User requested notes and plans to return tonight for bench tests/debugging.
Aircraft is NOT connected. Custom ArduPlane FC PCB has NO SD card, so no
onboard flight logs are available. Do not ask for nonexistent SD logs.
Current flight testing is FBWA only. User clarified earlier “auto” meant
FBWA self-leveling, NOT AUTO mission mode. GPS/AUTO testing is deferred until
the new flight-controller PCB arrives and is built.

## Speaker and GUI release
User fitted the missing 100-ohm R19 on TX V3. Both existing Config Mode D11
alarm patterns were acknowledged and completed; user confirmed audible sound.
Evidence: artifacts/buzzer-test-2026-10-18/sound-test-after-r19-2026-10-19.json.
Volume acceptable indoors; outdoor adequacy unverified. User considered 29 ohms;
no resistor change authorized/performed, speaker rating not established.
Added GUI Speaker Test tab (five-minute pattern, one-minute reminder, Stop),
firmware capability check and Config Mode handshake. User tested GUI successfully.
Commit 41aa1ef on feature/rx-v4-pixhawk-crsf pushed; release tag
transmitter-gui-v2026.10.19 published on GitHub with Windows x64, Raspberry Pi
ARM64 and firmware assets. 18 tests passed; local macOS tab layout checked.
Mac build/signing passed but Apple notarization failed HTTP 403 for a required
unsigned/expired developer agreement. User will accept agreement LATER; rerun
failed release jobs and verify/add Mac package afterward. Do not claim Mac
2026.10.19 package is published. Existing release notes explain partial availability.
Release: https://github.com/Altitude-Unknown/RC-Airplane/releases/tag/transmitter-gui-v2026.10.19
Run: https://github.com/Altitude-Unknown/RC-Airplane/actions/runs/39317492673

## TX V3 intermittent startup — UNRESOLVED
User reports intermittent failure to enter Bind/Config; D13 sometimes dark.
M0 enumerated as /dev/cu.usbmodem1201 but PING produced no response in failed
Config startup. No reset/reflash/settings writes performed during diagnosis.
Holding AUX during startup entered simulator mode with D13 SOLID (user report).
Battery connected. M0 reset is physically inaccessible; full power cycling
requires disconnecting USB AND switching battery off.
Moving cable to ESP32 USB: no USB serial device appeared, including after
clean power cycle with all buttons released. User pressed both ESP buttons
while uncertain which was reset; later clean power cycle ruled out simply
leaving BOOT held. No ESP firmware/role changes performed.

Firmware inspection: txv3BuddyBegin() waits indefinitely for ROLE response
before USB Config handling/normal startup. Simulator bypasses that wait.
Bind and Config share slow LED pattern; dark LED is consistent with early
startup stall but does not establish precise stall location. Boot button
inputs are sampled once soon after pull-up initialization; no debounce fix made.
IMPORTANT: indefinite STARTUP handshake does not by itself explain in-flight
link interruptions after successful boot. Do not conflate these mechanisms.

User identifies V3 known faults: AUX-to-D5 short fixed by cutting AUX 2 trace,
and missing ESP pull-up repaired with jumper. Existing board notes identify
GPIO9/BOOT pull-up and flag GPIO8/other strap review; do not assume continuity
or voltage is good. User resoldered suspect jumper, washed/dried board; initial
recovery was TEMPORARY. Fault recurred; repeated power cycles sometimes recover.
No multimeter readings or boot UART capture obtained. Suggested failed-state
measurements at ESP 3.3V, EN/reset and module-side GPIO9 (released, near 3.3V).
User ordered V4 TX with both known PCB faults corrected; expected next week.

## Flight incident — pilot observations, causes NOT established
Aircraft used faulty-startup TX V3, custom RX, custom ArduPlane FC.
FBWA autolevel reportedly works well; yesterday's CH5-linked full-rate change
helped but handling problems remain:
- Turns right well, poor left response; more right than left aileron deflection.
- Elevator authority in FBWA could improve.
- One or two hard roll/inversion events, then self-righting. User suspects FC
  resets based on observed boot surface sweep. RESET NOT CONFIRMED.
- Several apparent control/link losses; first events recovered.
- Final event: motor cut, wings-level glide, then reconnection, motor powered
  up and aircraft nose-dived into ground; motor mount broken.
No evidence yet distinguishes TX outage, RX fault, FC/power reset, channel
corruption, mode/failsafe recovery, attitude upset or mechanical causes.
Level glide/motor cut is consistent with failsafe, not verified from telemetry.
Do not claim startup jumper explains crash, or certify failsafe recovery safe.

## Bench plan agreed for later (propeller removed)
1. Read-only FC identity, parameters, RC channels, mode and available telemetry;
   identify actual installed RX firmware/output protocol before assumptions.
2. Compare centers/full-left/full-right input at TX, FC RC input and servo
   commands; check mechanical travel, RC calibration/endpoints/trim/reversal.
3. Check pitch input and requested FBWA attitude/correction direction. FBWA
   sticks request attitude, not direct servo travel; do not blindly raise limits.
4. Repeated controlled link-loss/recovery tests, monitoring throttle, pitch,
   mode and failsafe transitions. Verify recovery, not only motor-off behavior.
5. Check FC/RX supply/connectors under servo load; capture live telemetry to
   computer if possible (does not reconstruct today's flight).
6. User has another TX proposed for tomorrow's flight. First verify mapping,
   endpoints/centers/reversal, CH5 mode/rate behavior, ground link recovery and
   range. Alternate TX is diagnostic comparison, not proof remaining system safe.
Keep intermittent TX out of flight service; bench/range checks before another
flight. No new flight tuning, firmware patch or flashing authorized/performed
in this troubleshooting segment. Preserve unrelated local RX experiments.

## Later update: ESP32 power-pin cold joint repaired
User found a cold solder joint on the ESP32 POWER PIN, reflowed it with flux
and soldering iron, then washed and dried the board. User reports no dark-D13
startup failures since this repair and will continue testing. This supersedes
the earlier tentative attribution to the GPIO9 pull-up jumper alone. Inadequate
ESP power is consistent with missing ESP USB/ROLE response while M0 simulator
startup worked. Status: PROVISIONALLY RESOLVED by user report, not conclusively
validated across repeated starts, range, load or flight. Do not claim flight
link faults or the final dive are conclusively explained by this repair.
Separately, user found RX antenna unscrewed/missing; that remains strong
evidence for RF loss during the incident, not proof of all incident causes.
User plans test flight tomorrow (2026-10-20), with continued TX reliability
checks. Bench verification before flying should cover correct secured RX
antenna/connector, repeated cold starts, ground range/link loss and recovery,
RC centers/endpoints and surface directions/neutrals after zeroing subtrims.
Temporary Bind trim-save installed and pulse/interlock verified; see
2026-10-19-temporary-bind-trim-save.md. Must remove feature for TX V4.
Current recorded model has ch5_rate_mode=0 and 50/30/80% surface rates; no
full-rate override restoration or calibration changes performed in this session.

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
