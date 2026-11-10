Windows x64 and Raspberry Pi ARM64 downloads are available below.
The macOS ARM64 package is delayed: Apple notarization returned HTTP 403
because the developer team must accept a required agreement. It will be
added after that account issue is resolved.

Adds a Speaker Test tab to the desktop configurator, with buttons for the
five-minute alarm, one-minute reminder, and Stop sound. Playback is bounded
and uses the actual D11 flight alarm patterns without changing models or
advancing the flight timer. Connect the transmitter M0 in USB Config Mode
with the aircraft powered off. Listen to verify sound; command acceptance
alone cannot confirm speaker operation.

The included V3 transmitter M0 firmware adds the BEEP commands and capability
flag required by this tab. Existing older TX firmware needs updating to use
the test. The previously released mode-linked surface rates are retained.
No receiver update is required for the speaker test. Other included firmware
is built from the committed release sources; local experimental receiver
changes are excluded.

Build targets: macOS Apple Silicon ARM64, Windows x64, and Raspberry Pi ARM64,
plus firmware and the SHA-256 manifest. Existing scrolling and updater
features are retained.

Validation: 18 buzzer/timer, mode-rate, model-codec and firmware-updater tests
passed. The new tab rendered on macOS at 640x480. Both alarm patterns were
confirmed audible by the user on a V3 TX with its 100-ohm R19 fitted, including
through the GUI. Windows and Raspberry Pi interactive testing remains pending.
