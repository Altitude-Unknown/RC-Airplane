# ASCEND Flight Control

Ground station for the ASCEND flight controller (ArduPlane firmware). It talks
to the flight controller over MAVLink by USB, a telemetry radio, or ArduPilot
SITL.

Run it with:

```bash
pip install -r ../requirements.txt
python3 ascend_flight_control.py
```

## What it does now

- Plan missions on the map inside the Mission tab: click to add waypoints,
  click a waypoint to select it, then edit altitude, speed, action and events.
  Save and load missions as JSON.
- See the aircraft's live position and heading on the map while connected
  (Go to Aircraft, Follow aircraft).
- Connect to the flight controller and show live status (armed, mode, GPS,
  battery).
- **Upload to FC**: converts the mission to ArduPlane mission items, uploads
  it, then reads it back and checks every item matches.
- **Download from FC**: loads the flight controller's mission into the editor.
- **Flight** tab: monitor a flight in progress. Glass-cockpit display (attitude
  indicator, airspeed and altitude tapes, vertical speed, heading), readouts
  (ground speed, altitude above home and sea level, climb, throttle, distance
  home, target waypoint, flight time, GPS), the flight controller's messages,
  and a live map with the aircraft's trail. Airspeed is marked as an estimate
  when no airspeed sensor is configured (`ARSPD_TYPE` 0).
- **Calibration** tab, in the recommended order:
  - *Accelerometer*: six positions, with a picture of each; the flight
    controller asks for each pose and the app confirms it. Gyroscopes calibrate
    at every start-up, and can be redone from the same page.
  - *Level*: the normal level-flight attitude (`AHRS_TRIM_X/Y`).
  - *Compass*: ArduPilot's onboard calibration with a progress bar per compass;
    the result is saved by the flight controller (and `COMPASS_ORIENT` corrected
    if needed). Restart afterwards.
  - *Radio*: live bars for CH1-CH6; writes `RCn_MIN`/`RCn_MAX` and the throttle
    low point, verified. Stick centers are left to the Bind-button trim-save
    (it updates servo trims too) and CH7 is not touched.
- **RC Configurator** tab: the full RC Configurator (transmitter Models,
  Instructor / Student, Firmware Update, Speaker Test), the same code as the
  standalone `fram_gui_models.py`, which still runs on its own. Before the
  configurator flashes the flight controller, ASCEND Flight Control closes its
  own USB connection to the FC so the two don't fight over the port; connect
  again when the update finishes.
- **Units…** (top right): Metric, US (mph/ft) or Aviation (knots/ft), or set
  speed, altitude and climb rate separately. Applies to missions, Aircraft
  Settings and the Flight tab; saved per user. All Parameters keeps
  ArduPilot's own units. Missions and the flight controller always store SI.
- **Aircraft Settings** tab: about 30 settings students need, in plain-English
  groups (Flight Modes, Return Home, Speed & Throttle, Flight Limits, Takeoff &
  Landing, Failsafes, Geofence, Arming). Settings load automatically on connect.
- **All Parameters** tab: every parameter, searchable, with ArduPilot's own
  description, range and options.
- Changes are staged (marked in amber with an Undo link) until you press
  **Write to Flight Controller**, review the list, and confirm. Each write is
  read back to confirm the FC kept it. Writes are blocked while armed.
- **Save Backup / Restore Backup**: `.param` files (Mission Planner format).
  Restoring stages the differences for review; calibration values are only
  restored if you confirm the file came from the same board.

## Parameter metadata

`param_metadata/ArduPlane.json` holds the names, ranges, options and
descriptions for the ASCEND firmware. Regenerate it when the firmware moves to
a new ArduPilot version:

```bash
~/opt/ardupilot-venv/bin/python3 tools/make_param_metadata.py ../../ardupilot-ascend-release
python3 -m unittest test_params   # checks every Aircraft Setting still exists
```

The curated list lives in `param_catalog.py`. CH7 (`RC7_OPTION`) is reserved
for the Bind-button trim-save and is not offered there; the All Parameters tab
asks for confirmation before changing it.

## How missions map to ArduPlane

| Editor | ArduPlane mission item |
| --- | --- |
| Home | Item 0 (ArduPilot keeps its own home once it has GPS) |
| `waypoint` | `NAV_WAYPOINT` |
| `takeoff` | `NAV_TAKEOFF` (15° pitch) |
| `loiter`, for a set time | `NAV_LOITER_TIME` (seconds; always flies the default radius `WP_LOITER_RAD`) |
| `loiter`, for a number of laps | `NAV_LOITER_TURNS` (1-255 laps; radius exact to 255 m, then 10 m steps to 2550 m) |
| `loiter`, until the mode changes | `NAV_LOITER_UNLIM` (radius) |
| `set_servo` | `NAV_WAYPOINT` then `DO_SET_SERVO` (Servo Ch, Servo PWM) |
| `camera_trigger` | `NAV_WAYPOINT` then `DO_DIGICAM_CONTROL` |
| `return_home` | `NAV_RETURN_TO_LAUNCH` |
| `land` | `NAV_LAND` |
| Speed change | `DO_CHANGE_SPEED` (airspeed) before the waypoint |
| Event `servo` / `payload` | `DO_SET_SERVO` after the waypoint |
| Event `camera` | `DO_DIGICAM_CONTROL` after the waypoint |
| Event `relay` | `DO_SET_RELAY`: Servo Ch is the relay number (1 = RELAY1), Servo PWM 0 = off |

Loiter radius 0 means the flight controller's default (`WP_LOITER_RAD`).
Direction is sent as the sign of the radius, so counter-clockwise laps or
endless loiters need a radius entered. The map draws each loiter circle at the
radius the plane will actually fly.

Altitudes are meters above home. Planes ignore hold time except on loiter
waypoints; the app warns about this.

## Releases

Push a tag `flight-control-v<version>` matching `version.py` and
`.github/workflows/ascend-flight-control-release.yml` builds the Mac (signed
and notarized), Windows and Raspberry Pi apps, checks each with
`--self-test`, and publishes a GitHub pre-release. Pull requests that touch
the app run the same builds without publishing. ASCEND Flight Control
releases are never marked "latest": the RC Configurator finds its firmware
through the latest release. Build locally with:

```bash
python3 -m PyInstaller --clean --noconfirm "ASCEND Flight Control.spec"   # from RC-Airplane/
```

## Testing

```bash
python3 -m unittest test_mission_mavlink test_params   # fake flight controller
python3 sitl_check.py tcp:127.0.0.1:5760              # mission check, SITL or hardware
python3 sitl_check.py tcp:127.0.0.1:5760 --params     # parameter check
python3 ascend_flight_control.py --connect tcp:127.0.0.1:5760   # app against SITL
python3 tools/sitl_demo_flight.py                              # fly a demo mission in SITL (port 5762)
```

Map layers (United States): **Layers ▾** switches the base map between the
street map and the FAA VFR sectional chart, and turns on FAA airspace overlays:
TFRs (live from tfr.faa.gov), UAS Facility Map ceilings (the LAANC grid),
controlled airspace where Part 107 needs authorization (Class B, C, D and the
Class E surface areas), special use airspace, and national security UAS
restrictions. Clicking still adds waypoints inside them; right-click →
**What airspace is here?** checks one spot against every layer. Data is
fetched for the area on screen from FAA services (`airspace_layers.py`), only
for the map you can see, and backs off when the FAA service is busy. These
layers are for planning only: pilots must still check NOTAMs and get LAANC or
DroneZone authorization.

Where the map opens: **Map ▾ → Set Map Home to This View** saves the current
view, and the map opens there from then on. Without a map home it opens at the
computer's location where the operating system provides one: macOS (Core
Location; macOS asks for permission the first time, and only the packaged app
can ask) and Windows (Location must be on in Settings). Raspberry Pi and Linux
use the map home. **Map ▾ → Go to My Location** recenters on demand.

Map zoom: scroll wheel or two-finger scroll, the +/− buttons, or the + and −
keys (arrow keys pan) on every platform. Trackpad pinch works on macOS (through
`native/libascend_mac.dylib`; rebuild with `tools/build_mac_native.sh`) and on Windows precision touchpads (they send pinch as Ctrl+scroll).
Raspberry Pi and Linux do not pass pinch gestures to Tk apps, so use the wheel,
buttons or keys there.

The map is drawn with `tkintermapview` using OpenStreetMap tiles, so map
tiles need an internet connection. Waypoints, the route and the aircraft still
show without one, on a blank background.
