# 2026-11-14: Bind button is the permanent trim-save button

Supersedes the "temporary, remove for V4" status in
`2026-10-19-temporary-bind-trim-save.md`.

## User decisions (2026-11-14)

- Bind is the trim-save button on Tx V3 and Tx V4 and in standard builds.
  The user wants AUX2/CH6 kept free for other functions.
- Trim-save gets its own channel, CH7. The Tx does not guess the flight mode;
  the FC alone enforces MANUAL.
- Hold time 1 s (2 s felt far too long in flight). Pulse 0.5 s.
- Tx beeps when the pulse is sent, so the pilot knows it was sent in flight.
- The FC status LED blinks fast for a few seconds when the save is accepted,
  for confirmation on the ground.

## Why

Every builder trims their airplane. A Tx trim that the FC does not know about
fails the stick-neutral arming check ("Roll (RC1) is not neutral") and acts as
a constant FBWA command. ArduPlane option 155 saves servo trims and RC stick
centres together (`ArduPlane/radio.cpp` trim_radio), so nothing moves at the
save and the Tx trims must stay where they are afterwards.

## Implementation

- Tx V3 (`PCB/TxV3/TxV3_Full_M0`): `bind_trim_save.h` (renamed from
  `temp_bind_trim.h`, HOLD_MS 1000) is always built. Inhibits: student radio,
  student has control (`txv3StudentGranted`), simulator, throttle lock. Pulse
  sets `AuxChannels::CH7` (0x40). Double chirp `TRIM_SENT_PATTERN`, 3.4 kHz,
  which never interrupts a timer alarm. INFO reports `bind_trim_save`,
  `trim_save_channel` 7, hold and pulse times.
- `aux_channels.h` (all four identical copies): `CH7 = 0x40`. Packet layout
  unchanged.
- `rx_firmware`: SBUS channel 7. `rx_pixhawk_crsf`: CRSF channel 7. Low
  (1000 µs) when not pulsed; it used to be neutral 1500.
- ArduPilot: AP_Notify event `trim_saved`. GPIO_LED_1 toggles every 60 ms for
  3 s (about 8 Hz, faster than the 5 Hz boot pattern), then resumes the normal
  pattern. Plane `trim_radio()` raises the event. `ASCENDFCRev2/defaults.parm`
  sets `RC7_OPTION 155`. Copter does not implement 155, so the quad targets do
  not set it.
- Tests: `test_bind_trim_save.py` (state machine, gating, SBUS and CRSF CH7)
  replaces `test_temp_bind_trim.py` in the release gate. `test_tx_buzzer.py`
  covers the chirp. `test_button_channels.py` CRSF test expects CH7 low.
  Local runs: Anaconda Python plus an arm64 `c++` wrapper (the x86_64 Python
  cannot run the arm64-only Xcode tools).

## Not done yet (needs the bench and the user's go)

- Flash Tx, receiver(s) and FC. Back up Tx firmware and full model memory,
  FC firmware and parameters first (AGENTS.md).
- The existing V4 board has `RC7_OPTION` 0. A changed default applies only if
  the parameter was never saved, so read back after flashing and set it if
  needed.
- Bench check: CH7 1000/2000 µs, chirp, rejection outside MANUAL, accepted
  save in MANUAL, LED fast blink, RC/SERVO trims read back. Then a flight.

## Progress

- 2026-11-14: FC onboard receiver (serial 8EACFE79…1005) flashed and verified, bind 7741 kept by
  copying the BIND_STORE record (see the V4 bring-up README). Tx and FC not yet flashed.
- 2026-11-14: FC flashed (git 243905c9). RC7_OPTION became 155 from the new default; the AUTOTUNE
  profile is unchanged; the profile .param now sets RC7_OPTION 155. The Tx is still to be flashed.
- 2026-11-14: Tx flashed and verified (artifacts/bind-trim-save-tx-2026-11-14/README.md). Model
  memory byte-identical; Research ch5_rate_mode 1 kept. INFO reports CH7, 1000 ms. All three parts
  are now updated; the bench trim-save test is still pending.
- Tip: the Tx M0 stays powered (and in the UF2 bootloader) through a power-switch cycle. To restart
  it into Config Mode, copy the same verified UF2 to RCTXBOOT while holding Bind+D5.
- 2026-11-14 bench test PASSED: CH7 0.5 s pulse, MANUAL save accepted (LED fast blink and chirp
  confirmed by the user), FBWA rejected with trims unchanged. Flight test still to do.
