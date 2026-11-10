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

## Temporary V3 Bind trim-save: remove for V4

`TXV3_TEMP_BIND_TRIM_SAVE=1` is a temporary V3-only test image, default OFF in
standard builds. It reserves CH6 for a deliberate Bind hold in MANUAL. Remove
this Bind feature when TX V4 is ready, review the FC's `RC6_OPTION=155`, and
validate the corrected V4 AUX pin map before assigning a replacement button.
Details: `memory/2026-10-19-temporary-bind-trim-save.md`.

Do not conflate that temporary feature with the permanent FBWA full-rate
requirement. Removing Bind trim-save must NOT remove mode-linked rates.
