# BOREALIS V2 ArduPlane — three flights reported 2026-10-18

User reports three successful flights with the airplane, custom ArduPlane PCB,
custom TX and custom RX. FBWA autolevel was smooth; MANUAL worked well; repeated
MANUAL/FBWA switching worked without reported issues. This is pilot-reported
flight evidence, not an independently reviewed flight-log result. Flight dates,
conditions and final airborne parameter set were not supplied.

Remaining handling complaint: FBWA gives insufficient roll/pitch command,
producing turns so wide that the pilot switched to MANUAL to turn.

## Rate and limit findings

User confirms aileron rate remained 30% and elevator was changed to 80% for the
flights. Flight rudder rate and High Rates Active state were not supplied.
Earlier TX readback had High Rates Active off, rudder 50%, aileron 30%, elevator 50%
and expo 40% on the three surface axes; do not substitute those historical values
for confirmed flight settings. No USB serial devices were connected at this
follow-up, so no current model/FC readback or parameter change was made.

Earlier complete FC readback had ROLL_LIMIT_DEG=45, PTCH_LIM_MAX_DEG=20 and
PTCH_LIM_MIN_DEG=-25. Current flight settings need confirmation. Local
ModeFBWA::update() multiplies normalized roll input by the current roll limit
and normalized pitch input by the respective pitch limit. RC_Channel::norm_input()
normalizes around saved RC trim/min/max. Reduced transmitter rates therefore
reduce achievable requested attitude, while expo softens center response.
With matched centers/endpoints, 30% of a 45-degree roll limit illustrates about
13.5 degrees at full stick; this is not a measured flight angle and calibration,
trim offsets and other limiters can change it. This strongly fits the pilot's
wide-turn report if High Rates Active was off.

Next diagnosis: verify active rates/High Rates flag, current RC calibration and
angle limits; observe NAV_CONTROLLER_OUTPUT.nav_roll/nav_pitch alongside
RC_CHANNELS during a propeller-off stick test in FBWA. Stall prevention can
also constrain requested bank based on speed estimate; a static ground test
does not establish the available airborne limit. If requested attitude is
adequate but achieved flight attitude is not, inspect controller tracking and
flight data before changing limits or gains. No stall-prevention changes made.

To retain the pilot's preferred reduced MANUAL commands while allowing full
FBWA commands, the discussed mode-linked TX surface rates remain a possible
firmware change, not an existing feature. Turning on High Rates Active globally
also changes MANUAL response and all four channels, so it is not a transparent
fix for this preference. Raising ROLL_LIMIT_DEG alone does not remove upstream
rate reduction. No new flight-angle limits or TX rates were applied here.

The pilot also confirmed earlier in this conversation that this old TX's D7/
second-AUX connection was removed during PCB repair and a revised TX is needed.
Do not plan a physical CH6 trim-save/rate switch on this board without repair.

References: ../ardupilot/ArduPlane/mode_fbwa.cpp,
../ardupilot/libraries/RC_Channel/RC_Channel.cpp,
../ardupilot/ArduPlane/Attitude.cpp (load-factor bank limiting),
and the saved October 18 FC/TX captures discussed in the arming session notes.

## Later mode-rate update and bench result

The user subsequently authorized a TX change that selects full surface rates
in FBWA and restores the selected model rates in MANUAL. It was installed and
enabled, preserving throttle, trims and expo. The pilot reports the bench test
looks good and surface deflections in the two modes look similar. Post-update
flight testing remains pending; the original three flights above occurred
before the change. See [mode-rate installation notes](2026-10-18-mode-rates.md).
