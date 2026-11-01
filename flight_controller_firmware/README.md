# Flight controller firmware

ArduPlane images that the configurator release publishes. The release workflow
checks `SHA256SUMS`, then packages every `<board>/arduplane.apj` into the
release manifest (`flight_controllers`). The configurator downloads them,
reboots the connected flight controller into its bootloader, and writes only
the image whose board ID matches the one the bootloader reports.

| Board | Board ID | Notes |
| --- | --- | --- |
| ASCENDFCRev2 | 65093 | ASCEND flight controller Rev.2. Outputs 1–4 are throttle/aileron/elevator/rudder. GPS is I2C-only and not yet supported. |

Each image is built from committed ArduPilot source in a clean checkout and
bench-tested on hardware before it is added here. `provenance.json` records
the source commit, build and checksum.

To add or update a board:

1. Build from a clean worktree of the committed source:
   `./waf configure --board <Board> && ./waf plane`.
2. Bench-test that exact `.apj` on the board.
3. Copy it to `<Board>/arduplane.apj`, update `<Board>/provenance.json`, and
   regenerate `SHA256SUMS` (`shasum -a 256 */arduplane.apj > SHA256SUMS`).
