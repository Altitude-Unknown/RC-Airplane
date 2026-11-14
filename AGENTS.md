# Persistent TX requirements

Read `memory/2026-10-19-evening-checkpoint.md` before changing transmitter
firmware, configurator model storage, or updating the connected flight-test TX.

## Preserve FBWA full surface rates

- User explicitly requires the Research model's mode-linked full-rate setting
  to survive future firmware and configurator updates. Do not disable it unless
  the user explicitly requests that change.
- Verified FC mapping: CH5 low = FBWA, CH5 high = MANUAL. Research uses
  `ch5_rate_mode=1`: FBWA rudder/aileron/elevator rates are 100%; MANUAL retains
  selected model rates (currently 50/30/80%). Throttle remains unchanged.
- Preserve the per-model setting in binary/JSON codecs, editor load/save,
  export/import, migration and any future desktop/web shared implementation.
  Do not globally force this setting on unrelated models or Student/trainer use.
- Before updating hardware, back up firmware and complete model memory. After
  updating, read back and verify the active model's rate selector, valid CRC,
  subtrims, mode mapping and all unrelated settings. A successful compile/flash
  alone is not evidence that the setting survived.
- Older configurators/model files may omit this field. Do not silently replace
  an existing enabled setting with the missing field's default of zero. Inspect
  compatibility before using older tooling or importing legacy model files.
- Keep `test_mode_rates.py` and the release workflow's control-regression gate.
  Run codec/rate tests for relevant changes and resolve failures before release.

## Bind button = trim-save (permanent, Tx V3 and V4)

User decision 2026-11-14: the Bind button is the permanent trim-save button
on every transmitter, including Tx V4. This supersedes the earlier "remove for
V4" instruction. AUX1/CH5 (D10) and AUX2/CH6 (D7) stay free for other uses.

- In normal operation, a 1 s Bind hold sends one 0.5 s pulse on CH7 (aux bit
  0x40) and the Tx plays a short double chirp ("sent", not "accepted"). Bind
  held at power-up still enters bind mode; Config Mode combinations unchanged.
- The Tx does not gate on flight mode. It is inhibited on a student radio,
  while a student has control, in simulator mode and during throttle lock.
- Receivers output CH7 over SBUS (`rx_firmware`) and CRSF (`rx_pixhawk_crsf`).
- ArduPlane: `RC7_OPTION 155` (in the ASCEND board defaults). It saves only in
  MANUAL with sticks near centre and low rotation, then blinks the status LED
  fast for 3 s (AP_Notify `trim_saved` event). Leave Tx trims as they are after
  a save; do not zero them.
- Keep `test_bind_trim_save.py` in the release gate. Do not give CH7 to another
  function, and do not put trim-save back on CH6.
Details: `memory/2026-11-14-bind-trim-save-permanent.md`.

Do not conflate trim-save with the permanent FBWA full-rate requirement.
Changing trim-save must NOT remove mode-linked rates.
