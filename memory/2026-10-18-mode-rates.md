# CH5-linked MANUAL/FBWA rates — 2026-10-18

User explicitly requested full rates when selecting FBWA and restoration of
the selected model rates when selecting MANUAL. Prepared an opt-in per-model
V3 M0 change and updated source configurator. No ArduPlane, RX, or ESP firmware
change is needed. Surface rates alone are overridden; throttle, expo, trims,
reversal, endpoints and saved rate selection are preserved. No storage write
occurs on mode changes. The CH5 state comes from the existing debounced button
and is sent in the same packet; no FC mode feedback is available.

Model reserved[5] bits 4..5 encode off/CH5-low-full/CH5-high-full. Older models
remain off. GUI reads/writes/exports/imports the choice and checks firmware's
new `mode_rates` capability before enabling. Trainer/Student use is excluded.
The mode-rate mapping also works in USB simulator mode for bench verification.

Earlier FC backup mapped CH5 low 1000 to FBWA and high 2000 to MANUAL. The pilot
is unsure of current polarity; do not enable a polarity without current FC
verification. D7/CH6 was intentionally removed on this old TX and is not needed.

Validation so far: 14 targeted host tests passed using production C++ button
and mixer code and GUI model codecs (both polarities, release/hold/reset,
legacy/off/invalid/trainer/student behavior, restoration of selected rates,
unmodified throttle/model, expo/trim/reversal/mixing and storage/JSON roundtrip).
V3 M0 release-identity build passed on Adafruit SAMD 1.7.10, using 69448 bytes
program storage. Existing dependency warnings were HID narrowing conversion
and RadioHead unfinished file-ops warning. Build output is under
artifacts/mode-rates-2026-10-18/samd/.

User connected hardware for installation/bench validation. Initial enumeration
showed only TX serial 89CB5B3050304C59502E3120FF101E44 on cu.usbmodem1301;
requested FC USB connection before verifying polarity. Current-model backup,
installation, feature enable and hardware validation remain pending.

User declined FC connection and will perform the FC bench test afterward.
They expect the previous switch mapping to be unchanged. Proceed using the
saved low=FBWA/high=MANUAL mapping, explicitly without current FC verification.
Do not ask for FC USB again during this installation.

TX Config Mode backup succeeded: serial 89CB5B3050304C59502E3120FF101E44,
FRAM 32768 bytes, active slot 0 `Research`, CH5 Toggle and CH6 Toggle,
mode-rate feature initially off. Rates in RUD/AIL/ELE/THR order were 50/30/80/100;
expo 40/40/40/0; subtrims -35/+110/-180/0; endpoints 1000..2000 on all four;
RUD/ELE reversed. High Rates Active off. Full raw storage and decoded model
saved as artifacts/mode-rates-2026-10-18/tx-before.storage.bin and tx-before.json.

Saved current firmware as tx-before-firmware.uf2 (524288-byte virtual UF2)
before writing the candidate through the existing UF2 bootloader. Candidate
SHA256 f4211c4c744b318be3b07049d34834142c00a676a8a18661bae2fe33cd11e2a4.
Bootloader identified RC Airplane TX M0/SAMD21G18A-Altitude-RC-TX-M0-v0.
TX re-enumerated on the same port/serial. Requested Config Mode again for
capability check, complete storage comparison and feature enable. No other
processor flashed and no FC parameters changed. Desktop layout test also
passed (test_gui_scrolling); total 14 logic/codec tests plus 1 GUI layout test.

## Installation and enable readback complete

Post-flash Config Mode INFO reports mode_rates=true. Compared all 32768 FRAM
bytes with the pre-flash backup: identical before enabling. Enabled low=full
surface rates in active Research slot 0, preserving CH5 Toggle and CH6 settings.
Only reserved[5] bits 4..5 and CRC changed (model byte offsets 57,58,59; storage
offsets 313,314,315). A second full 32768-byte read verified every other byte was
unchanged. Evidence: tx-after-flash.json, tx-enable.json, tx-after-enable.json,
and tx-after.storage.bin under the artifact directory.

Current intended mapping follows the saved FC backup: CH5 low/FBWA gets 100%
RUD/AIL/ELE, CH5 high/MANUAL restores 50%/30%/80%. THR remains 100% in both.
Selected High Rates Active remains off. Trims, expo, endpoints, reverse, bind
and all other models are unchanged. This is storage/runtime capability
verification plus production-code host tests, not a live FC or flight test.
User will bench-test the FC mode mapping and received ranges. TX is left in
Config Mode and must restart normally with throttle down before radio use.

Built the updated macOS ARM64 configurator using the existing PyInstaller spec
into artifacts/mode-rates-2026-10-18/gui/Altitude Unknown RC Configurator.app.
Packaged app startup smoke check passed without opening a serial connection.
Use this updated app for future model edits; the older GUI clears the feature
when it saves a model. No installed app was overwritten, no release published,
and no git commit/push performed.

## Pilot bench acceptance — 2026-10-18

After installation and enablement, the user reports: "The bench test looks
good. The control surface deflection in FBWA and manual look close to the
same." Recorded as pilot-reported successful bench acceptance, not numerical
confirmation of RC ranges, requested angles or exact FC mode mapping. No FC
telemetry was collected by the agent for this check. The pilot plans flight
testing to confirm improved FBWA handling. The three earlier successful
flights preceded the rate update and do not validate the new handling yet.

User requested committing the changes and updating notes/manual. Updated the
manual, button-channel documentation and deployment validation with this result.
Commit scope includes this session's TX rate feature, tests, profile/operating
documentation and diagnostic/deployment evidence; unrelated RX stabilization,
V92 work and local packaged GUI/build intermediates are excluded. No push
requested. Commit identity can be obtained from git history after completion.
