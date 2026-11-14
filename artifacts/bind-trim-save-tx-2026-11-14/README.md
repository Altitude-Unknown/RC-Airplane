# Tx V3 update to permanent Bind trim-save — 2026-11-14

Transmitter: Altitude RC TX M0, serial 89CB5B3050304C59502E3120FF101E44, MASTER.

1. Model memory before (Config Mode, read-only `read_tx.py before`): 32768 bytes, two reads
   identical, `tx-before.storage.bin` (sha256 75f8359d…d393). Active slot 0 Research, CRC OK,
   ch5_rate_mode 1 (FBWA full rates), rates 50/25/100/100, subtrims 185/−30/30/0, D10 and D7
   toggle, bind 7741. Slots: Research, FlyingWing, T-Tail.
2. Firmware before: `tx-before-firmware.uf2` from CURRENT.UF2 (524288 bytes, sha256 67ef7d7e…2410),
   the temporary CH6 Bind trim-save build. Bootloader "UF2 Bootloader v4.0.0 SFHWRO, RC Airplane
   TX M0".
3. Installed `altitude-tx-v3-bind-trim-save.uf2` (`candidate.json`; standard build, CH7, 1 s
   hold, chirp) with `install_tx.py`.
4. Flash readback `tx-flash-verify.json`: 70824 image bytes compared, 0 mismatches. Excluded: the
   first app page (this bootloader reports it as FF; the same in both earlier backups) and the
   legacy `_dataBIND_STORE` page that the firmware writes at runtime.
5. Restart into Config Mode: power cycling did not reset the M0 (USB/battery kept it powered).
   The same verified UF2 was copied again while Bind+D5 were held. INFO: `bind_trim_save` true,
   channel 7, hold 1000 ms, pulse 500 ms.
6. Model memory after (`read_tx.py after`): all 32768 bytes identical to the backup. Header and
   all three models identical, CRCs OK, Research ch5_rate_mode 1.

The Tx was left in Config Mode. Restart normally (throttle low) to fly.
