**ASCEND Flight Control** is the ground station for the ASCEND flight
controller. It plans and uploads missions, shows a flight in progress, changes
settings, runs the calibrations, and includes the RC Configurator.

This is a **beta**. It has been tested against the ArduPlane simulator but not
yet on many real airplanes. Back up your settings (**Aircraft Settings → Save
Backup…**) before changing anything, and tell us what goes wrong.

## New in this version

- **Drag waypoints.** Click, hold and drag a waypoint on the map to move it.
  A plain click still selects it.
- **Survey grids.** **Survey Grid…** on the Mission tab lays out back-and-forth
  passes over an area. Draw a box or a polygon on the map and drag its corners
  to adjust. Set the altitude, the side overlap between passes (from your
  camera's field of view) or a fixed spacing, the direction of the passes, and
  how far each pass runs past the edge so the plane is flying straight before
  it is over the area. The window shows the passes on the map, the flight
  distance and time, and the number of photos.
- **Photos by distance.** A survey grid can have the flight controller take a
  photo every so many meters, on each pass and not in the turns. Any waypoint
  can also start or stop photos (Event `camera_distance`).
- **Camera settings.** **Aircraft Settings → Camera** sets how the flight
  controller fires the shutter. Photos are only taken once **Shutter trigger**
  is set, and **Upload to FC** warns you if it isn't.

Earlier in this beta: FAA map layers (VFR sectional chart, TFRs, UAS Facility
Map, airspace), and the map opening at your location or a saved map home.

## Download

| Computer | File |
| --- | --- |
| Mac (Apple silicon: M1 or newer) | `ASCEND-Flight-Control-macOS-ARM64.zip` |
| Windows 10 or 11 (64-bit) | `ASCEND-Flight-Control-Windows-x64.zip` |
| Raspberry Pi 4 or 5 (64-bit Raspberry Pi OS) | `ASCEND-Flight-Control-Raspberry-Pi-ARM64.zip` |

**Mac:** unzip, drag **ASCEND Flight Control** into Applications, and open it.

**Windows:** unzip and run **ASCEND-Flight-Control.exe**. Windows may show
"Windows protected your PC" the first time; click **More info → Run anyway**.

**Raspberry Pi:** unzip, then in a terminal in that folder run `./install.sh`.
Open **ASCEND Flight Control** from the Programming menu. To use USB, your
user must be in the `dialout` group; the installer tells you if it is not.

## What it does

- **Mission:** click the map to add waypoints and drag them to move them; set
  altitude, speed and actions; loiter for a set time, a number of laps, or
  until the mode changes. **Survey Grid…** covers an area with passes and photos.
  **Upload to FC** checks the mission by reading it back.
- **Flight:** attitude indicator, airspeed and altitude tapes, heading,
  ground speed, distance home, the next waypoint, the flight controller's
  messages, and the airplane's track on the map.
- **Aircraft Settings:** the settings you are most likely to change, in plain
  English. **All Parameters** has everything else.
- **Calibration:** accelerometer, level, compass and radio, step by step.
- **RC Configurator:** the same transmitter, receiver and firmware tools as
  the separate RC Configurator.
- **Units…** (top right): metric, mph and feet, or knots and feet.

## Getting connected

Plug in the flight controller by USB (or a telemetry radio), choose its port
at the top left, and click **Connect**. Settings load automatically.

The map needs an internet connection to show the background map. Waypoints,
the route and the airplane still show without one.
