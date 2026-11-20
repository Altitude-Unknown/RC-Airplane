Adds a CH6 AUTO switch to the ASCEND flight controller defaults. The
configurator, transmitter and receiver are unchanged from 2026.11.19.

**CH6 selects AUTO.** The ASCEND FC (V4, board target ASCENDFCRev2) image now
sets `RC6_OPTION 16`. With the transmitter's D7 button set to
**Channel 6 — Toggle**, pressing D7 switches to AUTO, and pressing it again
returns to the mode CH5 selects (FBWA low, MANUAL high). Both buttons start
low at power-up, so the airplane starts in FBWA, not AUTO. AUTO needs a GPS
fix and a loaded mission; otherwise the FC refuses the switch and stays in
the CH5 mode.

To use it:

1. Update the flight controller from **Firmware Update → Flight controller
   (ArduPlane)**. Parameters and calibrations are kept. A board where a team
   already set `RC6_OPTION` keeps its own value; set it to 16 by hand if you
   want the AUTO switch.
2. In the **Models** tab, set **D10 / Trainer** to **Channel 5 — Toggle** and
   **D7 / Aux** to **Channel 6 — Toggle**, then **Save To Radio**.
3. With the propeller removed, check D10 toggles FBWA/MANUAL and, with a GPS
   fix and a mission loaded, D7 enters and leaves AUTO.

On the instructor's radio, D10 cannot be both the CH5 mode button and the
trainer hand-off; choose one per model.

The flight controller image is built from the 2026-11-14 source
(`02d6a7b964`) plus this one default (`19befda7b6`). Includes macOS Apple
Silicon ARM64, Windows x64 and Raspberry Pi ARM64 apps, plus firmware and the
SHA-256 manifest.

Validation: build checked for board ID 65093 with `RC6_OPTION 16` in its
defaults. Not yet flashed to hardware: check D7/AUTO on the bench before
flight.
