// Pluto Cluster Monitor - local web frontend
// No external dependencies (no CDN, no build step) so this keeps working
// in a lab with no internet access. Charts are hand-drawn on <canvas>.

const MAX_HISTORY_POINTS = 120;

const els = {
  statusDot: document.getElementById("status-dot"),
  statusText: document.getElementById("status-text"),
  errorBanner: document.getElementById("error-banner"),
  connectedRadios: document.getElementById("connected-radios"),
  overallBanner: document.getElementById("overall-banner"),
  groupsGrid: document.getElementById("groups-grid"),
  btnStart: document.getElementById("btn-start"),
  btnStop: document.getElementById("btn-stop"),
  mode: document.getElementById("mode"),
  toneField: document.getElementById("tone-field"),
  digitalFields: document.getElementById("digital-fields"),
  chartPower: document.getElementById("chart-power"),
  legendPower: document.getElementById("legend-power"),
};

const configFieldIds = [
  "center_frequency_hz",
  "sample_rate_hz",
  "rx_gain_db",
  "tx_gain_db",
  "tone_frequency_hz",
  "sps",
  "data_bits",
  "update_period_s",
];

// group_name -> array of {t, value}
const powerHistory = {};
let sampleIndex = 0;

const GROUP_COLORS = {
  A: "#4f8cff", // blue
  B: "#f2b84b", // amber
};

function colorForGroup(name) {
  if (GROUP_COLORS[name]) return GROUP_COLORS[name];

  // Deterministic fallback for any future group beyond A/B.
  let hash = 0;
  for (let i = 0; i < name.length; i++) {
    hash = (hash * 31 + name.charCodeAt(i)) >>> 0;
  }
  const hue = hash % 360;
  return `hsl(${hue}, 70%, 60%)`;
}

function updateModeFieldVisibility() {
  const mode = els.mode.value;
  const isSine = mode === "SineWave";
  els.toneField.style.display = isSine ? "flex" : "none";
  els.digitalFields.style.display = isSine ? "none" : "grid";
}

function setStatus(state) {
  els.statusDot.className = `dot ${state}`;
  els.statusText.textContent = state;
  const running = state === "running" || state === "starting" || state === "stopping";
  els.btnStart.disabled = running;
  els.btnStop.disabled = !running;
}

function showError(message) {
  if (!message) {
    els.errorBanner.classList.remove("visible");
    els.errorBanner.textContent = "";
    return;
  }
  els.errorBanner.textContent = message;
  els.errorBanner.classList.add("visible");
}

async function loadConfigDefaults() {
  try {
    const res = await fetch("/api/config");
    if (!res.ok) return;
    const config = await res.json();
    const rf = config.rf || {};
    const appCfg = config.app || {};

    document.getElementById("center_frequency_hz").value = rf.center_frequency_hz ?? "";
    document.getElementById("sample_rate_hz").value = rf.sample_rate_hz ?? "";
    document.getElementById("rx_gain_db").value = rf.rx_gain_db ?? "";
    document.getElementById("tx_gain_db").value = rf.tx_gain_db ?? "";
    document.getElementById("tone_frequency_hz").value = rf.tone_frequency_hz ?? "";
    document.getElementById("sps").value = rf.sps ?? "";
    document.getElementById("data_bits").value = rf.data_bits ?? "";
    document.getElementById("update_period_s").value = appCfg.update_period_s ?? "";
    els.mode.value = appCfg.mode || "SineWave";
    updateModeFieldVisibility();
  } catch (err) {
    console.error("Could not load /api/config", err);
  }
}

function collectOverrides() {
  const overrides = { mode: els.mode.value };
  for (const id of configFieldIds) {
    const el = document.getElementById(id);
    if (el.value !== "") {
      overrides[id] = Number(el.value);
    }
  }
  return overrides;
}

async function startAcquisition() {
  showError(null);
  els.btnStart.disabled = true;
  try {
    const res = await fetch("/api/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(collectOverrides()),
    });
    const data = await res.json();
    if (!res.ok) {
      showError(data.detail || "Could not start acquisition.");
      els.btnStart.disabled = false;
      return;
    }
    setStatus(data.state);
    renderConnectedRadios(data);
    resetHistory();
  } catch (err) {
    showError(String(err));
    els.btnStart.disabled = false;
  }
}

async function stopAcquisition() {
  els.btnStop.disabled = true;
  try {
    const res = await fetch("/api/stop", { method: "POST" });
    const data = await res.json();
    if (!res.ok) {
      showError(data.detail || "Could not stop acquisition.");
      els.btnStop.disabled = false;
      return;
    }
    setStatus(data.state);
  } catch (err) {
    showError(String(err));
    els.btnStop.disabled = false;
  }
}

function resetHistory() {
  sampleIndex = 0;
  for (const key of Object.keys(powerHistory)) delete powerHistory[key];
}

function renderConnectedRadios(status) {
  const radios = status.connected_radios || [];
  els.connectedRadios.textContent = radios.length ? radios.join(", ") : "—";
}

function renderGroups(metrics) {
  if (!metrics || Object.keys(metrics.groups).length === 0) {
    els.groupsGrid.innerHTML = '<div class="empty-state">No data yet.</div>';
    els.overallBanner.textContent = "No data yet.";
    return;
  }

  els.overallBanner.innerHTML = `Strongest group right now: <strong>${metrics.strongest_group}</strong>`;

  const cards = [];
  for (const [groupName, group] of Object.entries(metrics.groups)) {
    const rows = group.radios
      .map((radio) => {
        const rowClass = radio.is_strongest ? "strongest" : radio.is_weakest ? "weakest" : "";
        const badge = radio.is_strongest
          ? '<span class="badge strong">strongest</span>'
          : radio.is_weakest
          ? '<span class="badge weak">weakest</span>'
          : "";
        const power = radio.power_db === null ? "—" : radio.power_db.toFixed(2);
        const snr = radio.snr_db === null ? "—" : radio.snr_db.toFixed(2);
        return `<tr class="${rowClass}"><td>${radio.serial || radio.uri}${badge}</td><td>${power}</td><td>${snr}</td></tr>`;
      })
      .join("");

    const meanPower = group.mean_power_db === null ? "—" : group.mean_power_db.toFixed(2);
    const meanNoise = group.mean_noise_db === null ? "—" : group.mean_noise_db.toFixed(2);

    cards.push(`
      <div class="group-card">
        <h3>Group ${groupName}</h3>
        <div class="group-summary">mean power=${meanPower} dB · mean noise=${meanNoise} dB</div>
        <table>
          <thead><tr><th>Radio</th><th>Power (dB)</th><th>SNR (dB)</th></tr></thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
    `);
  }
  els.groupsGrid.innerHTML = cards.join("");
}

function pushHistory(store, groupName, value) {
  if (value === null || value === undefined) return;
  if (!store[groupName]) store[groupName] = [];
  store[groupName].push({ t: sampleIndex, value });
  if (store[groupName].length > MAX_HISTORY_POINTS) {
    store[groupName].shift();
  }
}

function updateHistories(metrics) {
  if (!metrics) return;
  for (const [groupName, group] of Object.entries(metrics.groups)) {
    pushHistory(powerHistory, groupName, group.mean_power_db);
  }
  sampleIndex += 1;
}

function drawChart(canvas, store) {
  const ctx = canvas.getContext("2d");
  const width = canvas.width;
  const height = canvas.height;
  ctx.clearRect(0, 0, width, height);

  const groupNames = Object.keys(store);
  if (groupNames.length === 0) return;

  let minVal = Infinity;
  let maxVal = -Infinity;
  let minT = Infinity;
  let maxT = -Infinity;

  for (const name of groupNames) {
    for (const point of store[name]) {
      minVal = Math.min(minVal, point.value);
      maxVal = Math.max(maxVal, point.value);
      minT = Math.min(minT, point.t);
      maxT = Math.max(maxT, point.t);
    }
  }

  if (!isFinite(minVal) || !isFinite(maxVal)) return;
  if (minVal === maxVal) {
    minVal -= 1;
    maxVal += 1;
  }
  if (minT === maxT) maxT = minT + 1;

  const padding = 24;
  const xScale = (t) => padding + ((t - minT) / (maxT - minT)) * (width - 2 * padding);
  const yScale = (v) => height - padding - ((v - minVal) / (maxVal - minVal)) * (height - 2 * padding);

  // gridlines
  ctx.strokeStyle = "rgba(255,255,255,0.06)";
  ctx.lineWidth = 1;
  for (let i = 0; i <= 4; i++) {
    const y = padding + (i * (height - 2 * padding)) / 4;
    ctx.beginPath();
    ctx.moveTo(padding, y);
    ctx.lineTo(width - padding, y);
    ctx.stroke();
  }

  for (const name of groupNames) {
    const points = store[name];
    if (points.length === 0) continue;
    ctx.strokeStyle = colorForGroup(name);
    ctx.lineWidth = 2;
    ctx.beginPath();
    points.forEach((point, idx) => {
      const x = xScale(point.t);
      const y = yScale(point.value);
      if (idx === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });
    ctx.stroke();
  }
}

function renderLegend(container, store) {
  const names = Object.keys(store);
  container.innerHTML = names
    .map(
      (name) =>
        `<span class="legend-item"><span class="legend-swatch" style="background:${colorForGroup(name)}"></span>${name}</span>`
    )
    .join("");
}

function connectWebSocket() {
  const protocol = window.location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${protocol}://${window.location.host}/ws/metrics`);

  ws.onmessage = (event) => {
    const payload = JSON.parse(event.data);
    const status = payload.status;
    const metrics = payload.metrics;

    setStatus(status.state);
    showError(status.error);
    renderConnectedRadios(status);
    renderGroups(metrics);

    if (status.state === "running") {
      updateHistories(metrics);
      drawChart(els.chartPower, powerHistory);
      renderLegend(els.legendPower, powerHistory);
    }
  };

  ws.onclose = () => {
    setTimeout(connectWebSocket, 1500);
  };

  ws.onerror = () => {
    ws.close();
  };
}

els.mode.addEventListener("change", updateModeFieldVisibility);
els.btnStart.addEventListener("click", startAcquisition);
els.btnStop.addEventListener("click", stopAcquisition);

loadConfigDefaults();
connectWebSocket();

// Keep the "connected" state consistent on first load in case the
// service was already running before this tab was opened.
fetch("/api/status")
  .then((res) => res.json())
  .then((status) => {
    setStatus(status.state);
    renderConnectedRadios(status);
    if (status.state === "running") {
      els.btnStart.disabled = true;
      els.btnStop.disabled = false;
    }
  })
  .catch(() => {});
