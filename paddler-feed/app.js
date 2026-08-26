const map = L.map("map").setView([34.6, -119.8], 6);
L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
  maxZoom: 18,
  attribution: "&copy; OpenStreetMap contributors"
}).addTo(map);

const cards = document.querySelector("#cards");
const template = document.querySelector("#card-template");

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

function addCard(p) {
  const node = template.content.cloneNode(true);
  node.querySelector("h2").textContent = p.name;
  const status = node.querySelector(".status");
  status.textContent = p.status;
  status.dataset.status = p.status;
  node.querySelector(".activity").textContent = p.activity || "Paddler";
  node.querySelector(".updated").textContent = p.last_update_utc ? ageLabel(p.age_minutes) : "—";
  node.querySelector(".speed").textContent = p.speed_mph == null ? "—" : `${p.speed_mph.toFixed(1)} mph`;
  node.querySelector(".heading").textContent = p.heading_deg_true == null ? "—" : `${Math.round(p.heading_deg_true)}° true`;
  node.querySelector(".device").textContent = p.device_type || "—";
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
  const marker = L.marker([p.lat, p.lng], {icon}).addTo(map);
  marker.bindPopup(
    `<strong>${p.name}</strong><br>${p.status}<br>` +
    `${p.speed_mph == null ? "Speed —" : `Speed ${p.speed_mph.toFixed(1)} mph`}<br>` +
    `${p.position_precision || ""}`
  );
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
    document.querySelector("#total").textContent = paddlers.length;
    document.querySelector("#live").textContent = paddlers.filter(p => p.status === "LIVE").length;
    document.querySelector("#aging").textContent = paddlers.filter(p => p.status === "AGING").length;
    document.querySelector("#stale").textContent = paddlers.filter(p => ["STALE","STOPPED"].includes(p.status)).length;
    document.querySelector("#other").textContent = paddlers.filter(p => !["LIVE","AGING","STALE","STOPPED"].includes(p.status)).length;

    cards.replaceChildren();
    const bounds = [];
    paddlers.forEach(p => { addCard(p); addMarker(p, bounds); });
    if (bounds.length) map.fitBounds(bounds, {padding: [30,30], maxZoom: 9});
  } catch (error) {
    document.querySelector("#generated").textContent = `Feed error: ${error.message}`;
  }
}
load();
setInterval(load, 60_000);
