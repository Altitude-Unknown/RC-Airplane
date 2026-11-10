const map = L.map('map').setView([39.7392, -104.9903], 12);

L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
  maxZoom: 19,
  attribution: '&copy; OpenStreetMap contributors'
}).addTo(map);

let markers = new Map();
let route = L.polyline([], { color: '#0f7f8f', weight: 3 }).addTo(map);
let currentLocationMarker = null;
let currentLocationAccuracy = null;
let latestSignature = '';
let latestMission = null;
let hasFitMission = false;
let locateStatus = 'Use Locate to center the map on your current location.';

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

const LocateControl = L.Control.extend({
  options: {
    position: 'topleft'
  },

  onAdd() {
    const container = L.DomUtil.create('div', 'leaflet-bar locate-control');
    const button = L.DomUtil.create('button', 'locate-button', container);
    button.type = 'button';
    button.title = 'Center map on current location';
    button.setAttribute('aria-label', 'Center map on current location');
    button.textContent = 'Locate';

    L.DomEvent.disableClickPropagation(container);
    L.DomEvent.on(button, 'click', event => {
      L.DomEvent.stop(event);
      locateMe(button);
    });

    return container;
  }
});

map.addControl(new LocateControl());

function setLocateStatus(message) {
  locateStatus = message;
  if (latestMission) updateHud(latestMission);
}

function locateMe(button) {
  if (!navigator.geolocation) {
    setLocateStatus('Location is not available in this browser.');
    return;
  }

  button.disabled = true;
  button.classList.add('busy');
  setLocateStatus('Requesting location permission...');

  navigator.geolocation.getCurrentPosition(
    position => {
      const latLng = [position.coords.latitude, position.coords.longitude];
      const accuracy = position.coords.accuracy || 0;

      if (!currentLocationMarker) {
        currentLocationMarker = L.marker(latLng, {
          title: 'Current location',
          zIndexOffset: 1000
        }).addTo(map);
      }
      currentLocationMarker
        .setLatLng(latLng)
        .bindPopup(
          '<strong>Current location</strong><br>' +
          `Lat: ${latLng[0].toFixed(7)}<br>` +
          `Lon: ${latLng[1].toFixed(7)}<br>` +
          `Accuracy: ${Math.round(accuracy)} m`
        );

      if (!currentLocationAccuracy) {
        currentLocationAccuracy = L.circle(latLng, {
          radius: accuracy,
          color: '#2563eb',
          weight: 1,
          fillColor: '#3b82f6',
          fillOpacity: 0.12
        }).addTo(map);
      }
      currentLocationAccuracy.setLatLng(latLng);
      currentLocationAccuracy.setRadius(accuracy);

      map.setView(latLng, Math.max(map.getZoom(), 15));
      setLocateStatus(`Location centered, accuracy about ${Math.round(accuracy)} m.`);
      button.disabled = false;
      button.classList.remove('busy');
    },
    error => {
      const messages = {
        1: 'Location permission was denied.',
        2: 'Location position is unavailable.',
        3: 'Location request timed out.'
      };
      setLocateStatus(messages[error.code] || 'Location request failed.');
      button.disabled = false;
      button.classList.remove('busy');
    },
    {
      enableHighAccuracy: true,
      timeout: 10000,
      maximumAge: 30000
    }
  );
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
    latestMission = mission;
    renderMission(mission);
  } catch (err) {
    document.getElementById('hud').innerHTML =
      '<strong>Mission Planner</strong><span>Waiting for mission data.</span>';
  }
}

function renderMission(mission) {
  latestMission = mission;
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
    '<span>Click map to add waypoint.</span><br>' +
    `<span>${locateStatus}</span>`;
}

refreshMission();
setInterval(refreshMission, 1000);
