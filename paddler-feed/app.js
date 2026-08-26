const map = L.map("map").setView([34.6, -119.8], 6);
L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
  maxZoom: 18,
  attribution: "&copy; OpenStreetMap contributors"
}).addTo(map);

const cards = document.querySelector("#cards");
const template = document.querySelector("#card-template");
const selection = document.querySelector("#selection");
const markerLayer = L.layerGroup().addTo(map);
let trackLayer = L.layerGroup().addTo(map);
let paddlersById = new Map();
let markersById = new Map();
let selectedId = null;

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>'"]/g, ch => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;"
  })[ch]);
}

function ageLabel(minutes) {
  if (minutes == null) return "Unknown";
  if (minutes < 1) return "<1 min ago";
  if (minutes < 120) return `${Math.round(minutes)} min ago`;
  if (minutes < 2880) return `${Math.round(minutes / 60)} hr ago`;
  return `${Math.round(minutes / 1440)} days ago`;
}

function markerColor(status) {
  if (status === "LIVE") return "#1f9d55";
  if (status === "AGING") return "#e3a008";
  if (status === "STALE" || status === "STOPPED") return "#7b8794";
  return "#b5472f";
}

function coordinateLabel(p) {
  if (typeof p.lat !== "number" || typeof p.lng !== "number") return "—";
  const digits = p.position_precision === "exact-opt-in" ? 6 : 3;
  return `${p.lat.toFixed(digits)}, ${p.lng.toFixed(digits)}`;
}

function trackLabel(p) {
  if (p.breadcrumbs_available && Array.isArray(p.track_points) && p.track_points.length >= 2) {
    return `${p.track_points.length} points`;
  }
  if (p.position_precision !== "exact-opt-in") return "Not shared";
  return "No recent track";
}

function setSelectionMessage(p, trackShown) {
  if (!p) {
    selection.innerHTML = "<strong>No paddler selected</strong><span>Tap a paddler marker or choose Select on Map. Only the selected paddler's breadcrumb trail will be shown.</span>";
    return;
  }
  const position = coordinateLabel(p);
  const trail = trackShown
    ? `${p.track_points.length} recent breadcrumb points shown`
    : (p.position_precision === "exact-opt-in" ? "No recent breadcrumb trail available" : "Breadcrumb trail not shared for this public research feed");
  selection.innerHTML = `<strong>${escapeHtml(p.name)} — ${escapeHtml(p.status)}</strong><span>Last confirmed position: ${escapeHtml(position)} • ${escapeHtml(ageLabel(p.age_minutes))} • ${escapeHtml(trail)}</span>`;
}

function clearTrack() {
  map.removeLayer(trackLayer);
  trackLayer = L.layerGroup().addTo(map);
}

function drawSelectedTrack(p) {
  clearTrack();
  const points = Array.isArray(p.track_points)
    ? p.track_points.filter(q => typeof q.lat === "number" && typeof q.lng === "number")
    : [];
  if (points.length < 2) return false;

  const latlngs = points.map(q => [q.lat, q.lng]);
  L.polyline(latlngs, {color: "#1769aa", weight: 4, opacity: 0.85}).addTo(trackLayer);
  points.forEach((q, index) => {
    const isLatest = index === points.length - 1;
    L.circleMarker([q.lat, q.lng], {
      radius: isLatest ? 5 : 3,
      color: "#ffffff",
      weight: 1,
      fillColor: "#1769aa",
      fillOpacity: isLatest ? 1 : 0.65
    }).bindPopup(
      `<strong>${escapeHtml(p.name)} recent track</strong><br>${escapeHtml(new Date(q.time_utc).toLocaleString())}` +
      `<br>${q.speed_mph == null ? "Speed —" : `Speed ${Number(q.speed_mph).toFixed(1)} mph`}`
    ).addTo(trackLayer);
  });
  return true;
}

function selectPaddler(id, moveMap = true) {
  const p = paddlersById.get(id);
  if (!p) return;
  selectedId = id;
  const trackShown = drawSelectedTrack(p);
  setSelectionMessage(p, trackShown);

  document.querySelectorAll(".card").forEach(card => {
    card.classList.toggle("selected", card.dataset.paddlerId === id);
  });

  if (!moveMap) return;
  const marker = markersById.get(id);
  const trackPoints = trackShown ? p.track_points.map(q => [q.lat, q.lng]) : [];
  if (trackPoints.length >= 2) {
    if (typeof p.lat === "number" && typeof p.lng === "number") trackPoints.push([p.lat, p.lng]);
    map.fitBounds(trackPoints, {padding: [40, 40], maxZoom: 14});
  } else if (marker) {
    map.setView(marker.getLatLng(), Math.max(map.getZoom(), 12));
    marker.openPopup();
  }
}

function addCard(p) {
  const node = template.content.cloneNode(true);
  const card = node.querySelector(".card");
  card.dataset.paddlerId = p.id;
  node.querySelector("h2").textContent = p.name;
  const status = node.querySelector(".status");
  status.textContent = p.status;
  status.dataset.status = p.status;
  node.querySelector(".activity").textContent = p.activity || "Paddler";
  node.querySelector(".updated").textContent = p.last_update_utc ? ageLabel(p.age_minutes) : "—";
  node.querySelector(".position").textContent = coordinateLabel(p);
  node.querySelector(".speed").textContent = p.speed_mph == null ? "—" : `${Number(p.speed_mph).toFixed(1)} mph`;
  node.querySelector(".heading").textContent = p.heading_deg_true == null ? "—" : `${Math.round(p.heading_deg_true)}° true`;
  node.querySelector(".track-status").textContent = trackLabel(p);
  node.querySelector(".device").textContent = p.device_type || "—";

  const selectButton = node.querySelector(".select-paddler");
  const hasPosition = typeof p.lat === "number" && typeof p.lng === "number";
  selectButton.disabled = !hasPosition;
  selectButton.textContent = p.breadcrumbs_available ? "Show Recent Track" : "Select on Map";
  selectButton.addEventListener("click", () => selectPaddler(p.id, true));

  const link = node.querySelector(".mapshare");
  link.href = p.mapshare_url;
  cards.appendChild(node);
}

function addMarker(p, bounds) {
  if (typeof p.lat !== "number" || typeof p.lng !== "number") return;
  const icon = L.divIcon({
    className: "",
    html: `<div class="marker-dot" style="width:16px;height:16px;background:${markerColor(p.status)}"></div>`,
    iconSize: [16, 16],
    iconAnchor: [8, 8]
  });
  const marker = L.marker([p.lat, p.lng], {icon}).addTo(markerLayer);
  marker.bindPopup(
    `<strong>${escapeHtml(p.name)}</strong><br>${escapeHtml(p.status)}<br>` +
    `${escapeHtml(coordinateLabel(p))}<br>` +
    `${p.speed_mph == null ? "Speed —" : `Speed ${Number(p.speed_mph).toFixed(1)} mph`}<br>` +
    `${escapeHtml(p.position_precision || "")}`
  );
  marker.on("click", () => selectPaddler(p.id, false));
  markersById.set(p.id, marker);
  bounds.push([p.lat, p.lng]);
}

async function load() {
  try {
    const response = await fetch(`./data/paddlers-live.json?t=${Date.now()}`, {cache: "no-store"});
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    document.querySelector("#generated").textContent =
      data.generated_at_utc ? `Collector run: ${new Date(data.generated_at_utc).toLocaleString()}` : "Collector has not run yet";

    const paddlers = data.paddlers || [];
    paddlersById = new Map(paddlers.map(p => [p.id, p]));
    markersById = new Map();
    markerLayer.clearLayers();
    cards.replaceChildren();

    document.querySelector("#total").textContent = paddlers.length;
    document.querySelector("#live").textContent = paddlers.filter(p => p.status === "LIVE").length;
    document.querySelector("#aging").textContent = paddlers.filter(p => p.status === "AGING").length;
    document.querySelector("#stale").textContent = paddlers.filter(p => ["STALE", "STOPPED"].includes(p.status)).length;
    document.querySelector("#other").textContent = paddlers.filter(p => !["LIVE", "AGING", "STALE", "STOPPED"].includes(p.status)).length;

    const bounds = [];
    paddlers.forEach(p => { addCard(p); addMarker(p, bounds); });
    if (selectedId && paddlersById.has(selectedId)) {
      selectPaddler(selectedId, false);
    } else {
      selectedId = null;
      clearTrack();
      setSelectionMessage(null, false);
      if (bounds.length) map.fitBounds(bounds, {padding: [30, 30], maxZoom: 9});
    }
  } catch (error) {
    document.querySelector("#generated").textContent = `Feed error: ${error.message}`;
  }
}

load();
setInterval(load, 60_000);
