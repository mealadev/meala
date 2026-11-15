const PALETTE = ["#F59E0B", "#38BDF8", "#10B981", "#F43F5E"];
let allFlights = [];
let selectedIds = [];
let charts = {};
let map = null;
let trackLayer = null;

function initCharts() {
  const configs = [
    ["vbatChart", "Voltage (V)"],
    ["climbChart", "Climb Rate (m/s)"],
    ["vibeChart", "Vibe Z (m/s²)"],
    ["altChart", "Altitude (m)"]
  ];
  configs.forEach(([id, label]) => {
    const ctx = document.getElementById(id).getContext("2d");
    charts[id] = new Chart(ctx, {
      type: "line",
      data: { datasets: [] },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        parsing: false,
        scales: {
          x: { type: "linear", title: { display: true, text: "Time (s)", color: "#94a3b8" }, ticks: { color: "#94a3b8" }, grid: { color: "#1e293b" } },
          y: { ticks: { color: "#94a3b8" }, grid: { color: "#1e293b" } }
        },
        plugins: { legend: { display: false } }
      }
    });
  });
}

function initMap() {
  map = L.map("flightMap").setView([43.7764, -79.3472], 14);
  L.tileLayer("https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png", {
    attribution: "&copy; OpenStreetMap &copy; CARTO"
  }).addTo(map);
  trackLayer = L.layerGroup().addTo(map);
}

async function fetchFlights() {
  const params = new URLSearchParams();
  const q = document.getElementById("filterSearch").value.trim();
  const stack = document.getElementById("filterStack").value;
  const maxTemp = document.getElementById("filterMaxTemp").value;
  const alerts = document.getElementById("filterAlerts").checked;

  if (q) params.set("q", q);
  if (stack) params.set("autopilot_type", stack);
  if (maxTemp !== "") params.set("max_temp_c", maxTemp);
  if (alerts) params.set("only_alerts", "true");

  const res = await fetch(`/api/v1/flights?${params.toString()}`);
  allFlights = await res.json();
  renderFlightList();
  updateKPIs();
}

function updateKPIs() {
  document.getElementById("flightCount").textContent = allFlights.length;
  document.getElementById("kpiTotal").textContent = allFlights.length;
  const alertCount = allFlights.filter(f => f.had_alert).length;
  document.getElementById("kpiAlerts").textContent = alertCount;
  if (allFlights.length > 0) {
    const minT = Math.min(...allFlights.map(f => f.ambient_temp_c));
    document.getElementById("kpiMinTemp").textContent = `${minT.toFixed(1)}°C`;
  } else {
    document.getElementById("kpiMinTemp").textContent = "—";
  }
  document.getElementById("kpiSelected").textContent = `${selectedIds.length} / 4`;
}

function renderFlightList() {
  const container = document.getElementById("flightList");
  container.innerHTML = allFlights.map(f => {
    const isSel = selectedIds.includes(f.flight_id);
    return `
      <div class="flight-item ${isSel ? "selected" : ""}" onclick="toggleFlight('${f.flight_id}')">
        <div class="flight-item-top">
          <span>${f.flight_id} • ${f.vehicle_uid}</span>
          <span class="${f.had_alert ? "tag-alert" : "tag-ok"}">${f.had_alert ? "ALERT" : f.status}</span>
        </div>
        <div class="flight-item-meta">
          <span>${f.autopilot_type} | ${f.pilot || "—"}</span>
          <span>${f.ambient_temp_c}°C | Min ${f.min_battery_v}V</span>
        </div>
      </div>
    `;
  }).join("");
}

async function toggleFlight(flightId) {
  if (selectedIds.includes(flightId)) {
    selectedIds = selectedIds.filter(id => id !== flightId);
  } else {
    if (selectedIds.length >= 4) selectedIds.shift();
    selectedIds.push(flightId);
  }
  renderFlightList();
  updateKPIs();
  await refreshOverlay();
}

async function refreshOverlay() {
  const chips = document.getElementById("selectedChips");
  chips.innerHTML = selectedIds.map((id, idx) =>
    `<span class="chip" style="background:${PALETTE[idx]}">${id}</span>`
  ).join("");

  Object.values(charts).forEach(c => { c.data.datasets = []; });
  trackLayer.clearLayers();
  const bounds = [];
  const paramBlocks = [];

  for (let i = 0; i < selectedIds.length; i++) {
    const fid = selectedIds[i];
    const color = PALETTE[i];
    const meta = allFlights.find(f => f.flight_id === fid);
    if (meta) {
      paramBlocks.push(`
        <div class="param-block">
          <strong style="color:${color}">${meta.flight_id} (${meta.vehicle_uid} • ${meta.autopilot_type})</strong>
          <p class="muted" style="margin-top:4px">${meta.notes || "No notes"}</p>
          <pre>${JSON.stringify(meta.parameters_json, null, 2)}</pre>
        </div>
      `);
    }

    const res = await fetch(`/api/v1/flights/${fid}/series`);
    if (!res.ok) continue;
    const s = await res.json();

    const toPts = (arr) => s.t_sec.map((t, idx) => ({ x: t, y: arr[idx] }));
    charts.vbatChart.data.datasets.push({ label: fid, data: toPts(s.vbat_v), borderColor: color, borderWidth: 2, pointRadius: 0 });
    charts.climbChart.data.datasets.push({ label: fid, data: toPts(s.climb_rate_mps), borderColor: color, borderWidth: 2, pointRadius: 0 });
    charts.vibeChart.data.datasets.push({ label: fid, data: toPts(s.vibe_z), borderColor: color, borderWidth: 2, pointRadius: 0 });
    charts.altChart.data.datasets.push({ label: fid, data: toPts(s.alt_m), borderColor: color, borderWidth: 2, pointRadius: 0 });

    const latlngs = s.lat.map((lat, idx) => [lat, s.lon[idx]]).filter(([la, lo]) => Math.abs(la) > 0.01);
    if (latlngs.length > 0) {
      L.polyline(latlngs, { color, weight: 3 }).addTo(trackLayer);
      bounds.push(...latlngs);
    }
  }

  Object.values(charts).forEach(c => c.update());
  if (bounds.length > 0) map.fitBounds(bounds, { padding: [20, 20] });
  document.getElementById("paramsInspector").innerHTML = paramBlocks.length
    ? paramBlocks.join("")
    : '<p class="muted">Select one or more flights on the left to compare firmware parameters and pilot notes.</p>';
}

document.addEventListener("DOMContentLoaded", async () => {
  initCharts();
  initMap();

  try {
    const h = await fetch("/api/v1/health");
    document.getElementById("serverStatus").textContent = h.ok ? "API Online" : "API Offline";
  } catch {
    document.getElementById("serverStatus").textContent = "API Offline";
  }

  await fetchFlights();
  if (allFlights.length >= 2) {
    selectedIds = [allFlights[0].flight_id, allFlights[allFlights.length - 1].flight_id];
    renderFlightList();
    updateKPIs();
    await refreshOverlay();
  }

  document.getElementById("applyFiltersBtn").addEventListener("click", fetchFlights);
  document.getElementById("resetFiltersBtn").addEventListener("click", () => {
    document.getElementById("filterSearch").value = "";
    document.getElementById("filterStack").value = "";
    document.getElementById("filterMaxTemp").value = "";
    document.getElementById("filterAlerts").checked = false;
    fetchFlights();
  });

  const modal = document.getElementById("uploadModal");
  document.getElementById("openUploadBtn").addEventListener("click", () => modal.classList.remove("hidden"));
  document.getElementById("closeUploadBtn").addEventListener("click", () => modal.classList.add("hidden"));

  document.getElementById("uploadForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const fd = new FormData(e.target);
    if (!fd.get("ambient_temp_c")) fd.delete("ambient_temp_c");
    const res = await fetch("/api/v1/flights/upload", { method: "POST", body: fd });
    if (res.ok) {
      modal.classList.add("hidden");
      e.target.reset();
      setTimeout(fetchFlights, 800);
    }
  });
});
