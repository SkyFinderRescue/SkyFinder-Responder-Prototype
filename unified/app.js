const PARAGLIDER_FEED = "https://raw.githubusercontent.com/SkyFinderRescue/Sky-Finder/data-live/latest.json";
const PADDLER_FEED = "../paddler-feed/data/paddlers-live.json";

const map = L.map("map", {zoomControl: true}).setView([34.45, -119.7], 7);
L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
  maxZoom: 18,
  attribution: "&copy; OpenStreetMap contributors"
}).addTo(map);

const paragliderLayer = L.layerGroup().addTo(map);
const paddlerLayer = L.layerGroup().addTo(map);
const targetLayer = L.layerGroup().addTo(map);
const results = document.querySelector("#results");
const template = document.querySelector("#result-template");
const searchInput = document.querySelector("#search");
const showParagliders = document.querySelector("#showParagliders");
const showPaddlers = document.querySelector("#showPaddlers");
const clearTargetButton = document.querySelector("#clearTarget");
const targetName = document.querySelector("#targetName");
const targetMeta = document.querySelector("#targetMeta");

let objects = [];
let markers = new Map();
let activeTarget = null;

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>'"]/g, ch => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;"
  })[ch]);
}

function ageMinutesFromEpoch(epochSeconds) {
  if (!Number.isFinite(Number(epochSeconds))) return null;
  return Math.max(0, (Date.now() / 1000 - Number(epochSeconds)) / 60);
}

function ageLabel(minutes) {
  if (minutes == null) return "time unknown";
  if (minutes < 1) return "<1 min ago";
  if (minutes < 120) return `${Math.round(minutes)} min ago`;
  if (minutes < 2880) return `${Math.round(minutes / 60)} hr ago`;
  return `${Math.round(minutes / 1440)} days ago`;
}

function paragliderStatus(p) {
  if (String(p.type) === "3") return "HELP";
  const age = ageMinutesFromEpoch(p.timestamp);
  if (age == null) return "UNKNOWN";
  if (age <= 120) return "RECENT";
  if (age <= 720) return "AGING";
  return "STALE";
}

function iconFor(kind) {
  return L.divIcon({
    className: "",
    html: `<div class="map-icon" aria-hidden="true">${kind === "PARAGLIDER" ? "🪂" : "🛶"}</div>`,
    iconSize: [28, 28],
    iconAnchor: [14, 14]
  });
}

function normalizedParagliders(data) {
  return (data.pilots || []).flatMap(p => {
    if (!Number.isFinite(Number(p.lat)) || !Number.isFinite(Number(p.lng))) return [];
    const age = ageMinutesFromEpoch(p.timestamp);
    return [{
      id: `pg:${p.pilot_id || p.name}`,
      kind: "PARAGLIDER",
      name: p.name || "Unknown paraglider",
      source: "XCFind / SkyFinder",
      lat: Number(p.lat),
      lng: Number(p.lng),
      timestamp: Number(p.timestamp) || null,
      ageMinutes: age,
      status: paragliderStatus(p),
      altitudeFt: Number.isFinite(Number(p.alt_ft)) ? Number(p.alt_ft) : null,
      targetEligible: true,
      precision: "confirmed GPS"
    }];
  });
}

function normalizedPaddlers(data) {
  return (data.paddlers || []).flatMap(p => {
    if (!Number.isFinite(Number(p.lat)) || !Number.isFinite(Number(p.lng))) return [];
    const exact = p.position_precision === "exact-opt-in";
    return [{
      id: `paddle:${p.id}`,
      kind: "PADDLER",
      name: p.name || "Unknown paddler",
      source: "Garmin MapShare",
      lat: Number(p.lat),
      lng: Number(p.lng),
      timestamp: p.last_update_utc ? Date.parse(p.last_update_utc) / 1000 : null,
      ageMinutes: Number.isFinite(Number(p.age_minutes)) ? Number(p.age_minutes) : null,
      status: p.status || "UNKNOWN",
      activity: p.activity || "Paddler / kayak",
      speedMph: Number.isFinite(Number(p.speed_mph)) ? Number(p.speed_mph) : null,
      heading: Number.isFinite(Number(p.heading_deg_true)) ? Number(p.heading_deg_true) : null,
      targetEligible: exact,
      precision: exact ? "confirmed opt-in GPS" : "coarse research position"
    }];
  });
}

function targetMetaText(item) {
  const coordinate = `${item.lat.toFixed(6)}, ${item.lng.toFixed(6)}`;
  return `${item.kind === "PARAGLIDER" ? "Paraglider" : "Paddler / kayak"} • ${coordinate} • ${ageLabel(item.ageMinutes)} • ${item.source}`;
}

function setActiveTarget(item) {
  if (!item?.targetEligible) return;
  activeTarget = {...item, rescueTargetVersion: 1, confirmed: true};
  targetLayer.clearLayers();
  const ring = L.divIcon({
    className: "",
    html: '<div class="target-ring" aria-hidden="true"></div>',
    iconSize: [30, 30],
    iconAnchor: [15, 15]
  });
  L.marker([item.lat, item.lng], {icon: ring, interactive: false}).addTo(targetLayer);
  targetName.textContent = `${item.kind === "PARAGLIDER" ? "🪂" : "🛶"} ${item.name}`;
  targetMeta.textContent = targetMetaText(item);
  clearTargetButton.disabled = false;
  map.setView([item.lat, item.lng], Math.max(map.getZoom(), 13));
  renderResults();
}

function clearActiveTarget() {
  activeTarget = null;
  targetLayer.clearLayers();
  targetName.textContent = "None selected";
  targetMeta.textContent = "Tap a marker or choose a search result.";
  clearTargetButton.disabled = true;
  renderResults();
}

function popupHtml(item) {
  const canTarget = item.targetEligible;
  const extra = item.kind === "PARAGLIDER"
    ? (item.altitudeFt == null ? "" : `<br>Altitude ${Math.round(item.altitudeFt).toLocaleString()} ft`)
    : `${item.speedMph == null ? "" : `<br>Speed ${item.speedMph.toFixed(1)} mph`}${item.heading == null ? "" : `<br>Heading ${Math.round(item.heading)}° true`}`;
  return `<strong>${escapeHtml(item.name)}</strong><br>${escapeHtml(item.kind === "PARAGLIDER" ? "Paraglider" : item.activity)}` +
    `<br>${escapeHtml(item.status)} • ${escapeHtml(ageLabel(item.ageMinutes))}` +
    `<br>${item.lat.toFixed(6)}, ${item.lng.toFixed(6)}${extra}` +
    `<br><em>${escapeHtml(item.precision)}</em>` +
    (canTarget ? "<br><strong>Tap the matching card to set as rescue target.</strong>" : "<br>Research-only coarse position; rescue targeting disabled.");
}

function addMarker(item) {
  const layer = item.kind === "PARAGLIDER" ? paragliderLayer : paddlerLayer;
  const marker = L.marker([item.lat, item.lng], {icon: iconFor(item.kind)}).addTo(layer);
  marker.bindPopup(popupHtml(item));
  marker.on("click", () => {
    searchInput.value = item.name;
    renderResults();
  });
  markers.set(item.id, marker);
}

function visibleByLayer(item) {
  return item.kind === "PARAGLIDER" ? showParagliders.checked : showPaddlers.checked;
}

function matchingObjects() {
  const q = searchInput.value.trim().toLowerCase();
  return objects.filter(item => visibleByLayer(item) && (!q || item.name.toLowerCase().includes(q))).slice(0, 80);
}

function renderResults() {
  results.replaceChildren();
  const matches = matchingObjects();
  if (!matches.length) {
    const empty = document.createElement("div");
    empty.className = "notice";
    empty.textContent = "No matching visible targets.";
    results.appendChild(empty);
    return;
  }

  for (const item of matches) {
    const node = template.content.cloneNode(true);
    const card = node.querySelector(".result-card");
    card.classList.toggle("selected", activeTarget?.id === item.id);
    node.querySelector(".kind").textContent = item.kind === "PARAGLIDER" ? "🪂" : "🛶";
    node.querySelector(".name").textContent = item.name;
    node.querySelector(".status").textContent = item.status;
    const details = [
      item.kind === "PARAGLIDER" ? "Paraglider" : (item.activity || "Paddler / kayak"),
      ageLabel(item.ageMinutes),
      item.precision
    ];
    node.querySelector(".detail").textContent = details.join(" • ");
    const button = node.querySelector(".select-target");
    if (!item.targetEligible) {
      button.disabled = true;
      button.textContent = "Coarse Research Position Only";
    } else if (activeTarget?.id === item.id) {
      button.textContent = "Active Rescue Target";
    } else {
      button.addEventListener("click", () => setActiveTarget(item));
    }
    card.addEventListener("click", event => {
      if (event.target.closest("button")) return;
      const marker = markers.get(item.id);
      if (marker) {
        map.setView(marker.getLatLng(), Math.max(map.getZoom(), 12));
        marker.openPopup();
      }
    });
    results.appendChild(node);
  }
}

function syncLayers() {
  if (showParagliders.checked) {
    if (!map.hasLayer(paragliderLayer)) paragliderLayer.addTo(map);
  } else if (map.hasLayer(paragliderLayer)) map.removeLayer(paragliderLayer);
  if (showPaddlers.checked) {
    if (!map.hasLayer(paddlerLayer)) paddlerLayer.addTo(map);
  } else if (map.hasLayer(paddlerLayer)) map.removeLayer(paddlerLayer);
  renderResults();
}

function fitAll() {
  const points = objects.filter(visibleByLayer).map(x => [x.lat, x.lng]);
  if (points.length) map.fitBounds(points, {padding: [30, 30], maxZoom: 8});
}

async function load() {
  const stamp = Date.now();
  const [pgResult, paddlerResult] = await Promise.allSettled([
    fetch(`${PARAGLIDER_FEED}?t=${stamp}`, {cache: "no-store"}).then(r => {
      if (!r.ok) throw new Error(`Paraglider HTTP ${r.status}`);
      return r.json();
    }),
    fetch(`${PADDLER_FEED}?t=${stamp}`, {cache: "no-store"}).then(r => {
      if (!r.ok) throw new Error(`Paddler HTTP ${r.status}`);
      return r.json();
    })
  ]);

  const loaded = [];
  const notes = [];
  if (pgResult.status === "fulfilled") {
    loaded.push(...normalizedParagliders(pgResult.value));
    notes.push(`${pgResult.value.pilot_count ?? pgResult.value.pilots?.length ?? 0} paragliders`);
  } else {
    notes.push("paraglider feed unavailable");
  }
  if (paddlerResult.status === "fulfilled") {
    loaded.push(...normalizedPaddlers(paddlerResult.value));
    notes.push(`${paddlerResult.value.paddlers?.length ?? 0} paddler feeds`);
  } else {
    notes.push("paddler feed unavailable");
  }

  objects = loaded;
  markers.clear();
  paragliderLayer.clearLayers();
  paddlerLayer.clearLayers();
  objects.forEach(addMarker);
  document.querySelector("#updated").textContent = `Loaded ${notes.join(" • ")}`;
  renderResults();
  fitAll();
}

searchInput.addEventListener("input", renderResults);
showParagliders.addEventListener("change", syncLayers);
showPaddlers.addEventListener("change", syncLayers);
document.querySelector("#showAll").addEventListener("click", () => {
  searchInput.value = "";
  renderResults();
  fitAll();
});
clearTargetButton.addEventListener("click", clearActiveTarget);

load().catch(error => {
  document.querySelector("#updated").textContent = `Feed load error: ${error.message}`;
});
