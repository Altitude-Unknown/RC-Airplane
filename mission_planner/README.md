# Altitude Unknown Mission Planner

Standalone mission-planning GUI for the RC airplane flight-controller project.

Run it with:

```bash
python3 mission_planner.py
```

Current first milestone:

- Create a new mission.
- Open a local browser map.
- Click the map to add waypoints.
- Select waypoints from the map or table.
- Edit altitude, speed, action, and event metadata.
- Save and load missions as JSON.
- Validate basic mission data.

The `Upload` button is intentionally a placeholder until the flight-controller
serial mission protocol is defined.

The map uses Leaflet and OpenStreetMap tiles, so the browser needs internet
access for the map tiles to appear.
