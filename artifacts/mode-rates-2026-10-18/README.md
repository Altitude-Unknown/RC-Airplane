# V3 M0 mode-linked rates — installed 2026-10-18

Installed on TX serial 89CB5B3050304C59502E3120FF101E44 and enabled in Research
slot 0. CH5 low uses full rudder/aileron/elevator rates; CH5 high restores the
selected rates (rudder 50%, aileron 30%, elevator 80%). This follows the earlier
FC backup's low=FBWA/high=MANUAL mapping. The pilot performed the subsequent
bench test without an agent FC connection and reports it looks good, with
similar-looking surface deflection in both modes. No FC/RX/ESP update.

Throttle, expo, subtrims, endpoints, reversals, selected rates, bind code and
other model storage were preserved. At installation completion, TX was left
in Config Mode; it must restart normally with throttle down for radio use.

## Files

- altitude-tx-v3-mode-rates.uf2: installed M0 firmware image.
- samd/: compiler outputs, including the binary and ELF.
- tx-before-firmware.uf2: rollback firmware saved from the TX bootloader.
- tx-before.storage.bin and tx-before.json: full original FRAM and model backup.
- tx-after-flash.json: capability and full FRAM preservation check after flashing.
- tx-enable.json: exact setting change and CRC readback.
- tx-after.storage.bin and tx-after-enable.json: final full storage verification.
- tx-install.json and validation.json: install identity, hashes and check results.
- gui/Altitude Unknown RC Configurator.app: updated local macOS ARM64 app.

Use the updated app when editing the model. Its Button channels → Mode-linked
rates selector controls the feature; older GUI versions clear the new setting.
The current low-FBWA choice starts at full surface rates after each TX reboot,
because CH5 starts low. A mode-button press selects high/MANUAL and restores
the selected rates. Trim and expo do not change with the button.

Validation: 14 logic/codec tests, one desktop layout test, M0 compile, packaged
GUI startup, runtime mode_rates capability, and full storage comparisons passed.
Only storage bytes 313..315 changed when enabling (new rate-link field plus CRC).
The pilot then reported a successful bench check. No numerical FC range/mode
data was collected by the agent and post-update flight testing is still pending.

The firmware, backups, validation and small readback records are versioned.
The packaged GUI and compiler intermediates stay local and can be rebuilt from
the committed sources/spec. The installed .bin is retained to match its hash
in validation.json; the UF2 is the corresponding deployable image.
