Two changes: the transmitter and receiver use their own USB IDs, and the
ASCEND flight controller image adds a CH6 AUTO switch. (The 2026.11.19.1
release with the CH6 switch was never published; it is included here.)

## Transmitter and receiver USB IDs

The RC Airplane Transmitter is now `1209:A5C0` and the receiver `1209:A5C1`:
free IDs for open-source hardware from [pid.codes](https://pid.codes). They
replace a lab placeholder (transmitter) and the Adafruit Feather M0 ID
(receiver); the receiver now shows up as **Altitude RC RX M0**. Each board's
bootloader (the new [Altitude SAMD21 Bootloader](https://github.com/Altitude-Unknown/Altitude-SAMD21-Bootloader))
uses the same ID. The configurator finds boards by the new IDs and still
recognizes boards flashed with older firmware, so update them as usual from
**Firmware Update**. Settings and models on the transmitter are kept.

The transmitter and receiver firmware is otherwise unchanged: mode-linked
rates, Bind trim-save, buttons, and alarms work as in 2026.11.19.

## CH6 AUTO switch (flight controller)

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
(`02d6a7b964`) plus this one default (`19befda7b6`). Validation: board ID
65093, `RC6_OPTION 16` in the build's defaults. Not yet flashed to hardware:
check D7/AUTO on the bench before flight.

Includes macOS Apple Silicon ARM64, Windows x64 and Raspberry Pi ARM64 apps,
plus firmware and the SHA-256 manifest.
