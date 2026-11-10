# Flight checkpoint — 2026-10-20

## Five successful flights — user report

- User completed five test flights of the ArduPlane FC and custom TX/RX; all five went well overall.
- New RX antenna resolved the loss-of-signal issue, per user.
- FC reset once. User identified RX PCB shorting against FC, insulated the underside of the RX PCB with tape, and reports that resolved the reset issue.
- User considers yesterday's anomalies resolved. These are pilot-reported results, not independently measured electrical diagnoses.
- Tested temporary Bind-button trim save and thinks it worked; actual saved trim values were not read back during this session.
- Entered varied unusual attitudes in MANUAL, selected FBWA, and observed correct, effective recovery.

## Remaining flight issues

- FBWA bank/turn authority feels too limited for desired turn radius.
- FBWA pitch authority feels limited; user needs more pitch control to maintain altitude.
- Aircraft turns left better than right in MANUAL too, but available MANUAL aileron throw masks the issue. With FBWA's limited response, right turns are almost impossible.
- No cause established and no parameters, firmware, calibration, or hardware settings changed tonight.

## Resume troubleshooting

- IMPORTANT: custom FC PCB has NO SD card slot. Onboard `.bin` flight logs are unavailable. Do not ask for them again. Use parameter exports, available live telemetry, prop-off bench checks, and pilot observations.
- Separate limited commanded attitude from inability to track the command; FBWA stick input requests bank/pitch angle rather than direct surface travel. FBWA does not hold altitude and throttle remains pilot-controlled.
- Investigate the left/right asymmetry first because it also exists in MANUAL: compare surface travel/linkages/neutral, rudder alignment and wing geometry; verify FC-received RC centers/endpoints and active transmitter rate/mix settings.
- Inspect current parameters before recommending changes to roll/pitch limits or tuning. Parameter names discussed: ROLL_LIMIT_DEG, PTCH_LIM_MAX_DEG, PTCH_LIM_MIN_DEG. No new values selected or authorized tonight.
- Preserve the permanent full-FBWA-rate requirement and temporary V3 Bind-feature lifecycle documented in AGENTS.md and the October 19 checkpoint. Today's flight report does not independently verify the current rate selector or saved trims.
- User ended the session after requesting notes; no further work pending tonight.
