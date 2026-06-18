const map = L.map('map').setView([39.7392, -104.9903], 12);

L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
  maxZoom: 19,
  attribution: '&copy; OpenStreetMap contributors'
}).addTo(map);

let markers = new Map();
let route = L.polyline([], { color: '#0f7f8f', weight: 3 }).addTo(map);
let latestSignature = '';
let hasFitMission = false;

function waypointIcon(number, selected) {
  return L.divIcon({
    className: '',
    html: `<div class="waypoint-label ${selected ? 'selected' : ''}">${number}</div>`,
    iconSize: [26, 26],
    iconAnchor: [13, 13]
  });
}

async function postJSON(url, payload) {
  await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  });
}

map.on('click', async event => {
  await postJSON('/api/add_waypoint', {
    lat: event.latlng.lat,
    lon: event.latlng.lng
  });
  setTimeout(refreshMission, 150);
});

async function refreshMission() {
  try {
    const response = await fetch('mission.json?cache=' + Date.now());
    const mission = await response.json();
    const signature = JSON.stringify({
      waypoints: mission.waypoints,
      selected: mission.selected_waypoint_id,
      home: mission.home
    });
    if (signature === latestSignature) return;
    latestSignature = signature;
    renderMission(mission);
  } catch (err) {
    document.getElementById('hud').innerHTML =
      '<strong>Mission Planner</strong><span>Waiting for mission data.</span>';
  }
}

function renderMission(mission) {
  const waypoints = mission.waypoints || [];
  const selectedId = mission.selected_waypoint_id;
  const seen = new Set();
  const latLngs = [];

  waypoints.forEach((wp, index) => {
    const id = Number(wp.id);
    seen.add(id);
    const latLng = [Number(wp.lat), Number(wp.lon)];
    latLngs.push(latLng);
    const selected = id === selectedId;
    let marker = markers.get(id);
    if (!marker) {
      marker = L.marker(latLng, { icon: waypointIcon(index + 1, selected), draggable: false }).addTo(map);
      marker.on('click', async () => {
        await postJSON('/api/select_waypoint', { id });
        setTimeout(refreshMission, 120);
      });
      markers.set(id, marker);
    }
    marker.setLatLng(latLng);
    marker.setIcon(waypointIcon(index + 1, selected));
    marker.bindPopup(
      `<strong>Waypoint ${index + 1}</strong><br>` +
      `ID: ${wp.id}<br>` +
      `Lat: ${Number(wp.lat).toFixed(7)}<br>` +
      `Lon: ${Number(wp.lon).toFixed(7)}<br>` +
      `Alt: ${wp.altitude_m} m<br>` +
      `Speed: ${wp.speed_mps} m/s<br>` +
      `Action: ${wp.action}<br>` +
      `Event: ${(wp.event && wp.event.type) || 'none'}`
    );
  });

  for (const [id, marker] of markers.entries()) {
    if (!seen.has(id)) {
      map.removeLayer(marker);
      markers.delete(id);
    }
  }

  route.setLatLngs(latLngs);
  updateHud(mission);

  if (!hasFitMission && latLngs.length > 0) {
    map.fitBounds(L.latLngBounds(latLngs).pad(0.25));
    hasFitMission = true;
  }
}

function updateHud(mission) {
  const waypoints = mission.waypoints || [];
  const selected = waypoints.find(wp => Number(wp.id) === mission.selected_waypoint_id);
  const selectedText = selected
    ? `Selected: WP ${selected.id}, ${selected.altitude_m} m`
    : 'Selected: none';
  document.getElementById('hud').innerHTML =
    `<strong>${mission.name || 'Mission Planner'}</strong>` +
    `<span>Waypoints: ${waypoints.length}</span><br>` +
    `<span>${selectedText}</span><br>` +
    '<span>Click map to add waypoint.</span>';
}

refreshMission();
setInterval(refreshMission, 1000);
