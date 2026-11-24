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
  chartNoise: document.getElementById("chart-noise"),
  legendPower: document.getElementById("legend-power"),
  legendNoise: document.getElementById("legend-noise"),
};

// Mode name -> control group ("tone" or "digital"), from /api/config.
const modeControls = new Map([["SineWave", "tone"], ["BPSK", "digital"], ["QPSK", "digital"], ["16QAM", "digital"]]);

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
const noiseHistory = {};
let historyStart = null;
let historySession = null;
const lastSampleByGroup = new Map();
const chartRanges = new Map();

// Keep each group the same color in both charts and their legends.
const GROUP_PALETTE = ["#56B4E9", "#E69F00", "#009E73", "#CC79A7", "#F0E442", "#D55E00"];
const groupColors = new Map([["A", GROUP_PALETTE[0]], ["B", GROUP_PALETTE[1]]]);

function colorForGroup(name) {
  if (!groupColors.has(name)) {
    groupColors.set(name, GROUP_PALETTE[groupColors.size % GROUP_PALETTE.length]);
  }
  return groupColors.get(name);
}

function updateModeFieldVisibility() {
  const isSine = modeControls.get(els.mode.value) !== "digital";
  els.toneField.style.display = isSine ? "flex" : "none";
  els.digitalFields.style.display = isSine ? "none" : "grid";
}

// Start stays disabled until the form holds the server configuration.
let configLoaded = false;
// Error of the last Start/Stop request; status updates must not erase it.
let requestError = null;

function setStatus(state) {
  els.statusDot.className = `dot ${state}`;
  els.statusText.textContent = state;
  const running = state === "running" || state === "starting" || state === "stopping";
  els.btnStart.disabled = running || !configLoaded;
  els.btnStop.disabled = !running;
  for (const id of [...configFieldIds, "mode", "transmit_enabled"]) {
    document.getElementById(id).disabled = running;
  }
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
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
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
    if (Array.isArray(config.modes) && config.modes.length) {
      modeControls.clear();
      els.mode.replaceChildren(...config.modes.map((mode) => {
        modeControls.set(mode.name, mode.controls);
        return new Option(mode.name, mode.name);
      }));
    }
    els.mode.value = appCfg.mode || "SineWave";
    document.getElementById("transmit_enabled").checked = appCfg.transmit_enabled ?? true;
    updateModeFieldVisibility();
    configLoaded = true;
    requestError = null;
    els.btnStart.disabled = false;
  } catch (err) {
    requestError = `Could not load the configuration (${err.message}). Retrying...`;
    showError(requestError);
    setTimeout(loadConfigDefaults, 2000);
  }
}

function collectOverrides() {
  const overrides = { mode: els.mode.value, transmit_enabled: document.getElementById("transmit_enabled").checked };
  for (const id of configFieldIds) {
    const el = document.getElementById(id);
    if (el.value !== "") {
      overrides[id] = Number(el.value);
    }
  }
  return overrides;
}

async function startAcquisition() {
  requestError = null;
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
      requestError = typeof data.detail === "string" ? data.detail : "Could not start acquisition.";
      showError(requestError);
      els.btnStart.disabled = false;
      return;
    }
    setStatus(data.state);
    renderConnectedRadios(data);
    resetHistory();
  } catch (err) {
    requestError = String(err);
    showError(requestError);
    els.btnStart.disabled = false;
  }
}

async function stopAcquisition() {
  requestError = null;
  els.btnStop.disabled = true;
  try {
    const res = await fetch("/api/stop", { method: "POST" });
    const data = await res.json();
    if (!res.ok) {
      requestError = typeof data.detail === "string" ? data.detail : "Could not stop acquisition.";
      showError(requestError);
      els.btnStop.disabled = false;
      return;
    }
    setStatus(data.state);
  } catch (err) {
    requestError = String(err);
    showError(requestError);
    els.btnStop.disabled = false;
  }
}

function resetHistory() {
  historyStart = null;
  historySession = null;
  lastSampleByGroup.clear();
  chartRanges.clear();
  for (const key of Object.keys(powerHistory)) delete powerHistory[key];
  for (const key of Object.keys(noiseHistory)) delete noiseHistory[key];
}

function renderConnectedRadios(status) {
  els.connectedRadios.replaceChildren();
  if (!status.nodes) {
    const radios = status.connected_radios || [];
    els.connectedRadios.textContent = radios.length ? radios.join(", ") : "No radios detected.";
    return;
  }
  const groups = new Map();
  for (const node of Object.values(status.nodes)) {
    const group = node.group || "?";
    if (!groups.has(group)) groups.set(group, []);
    groups.get(group).push(node);
  }
  for (const [group, nodes] of groups) {
    const section = document.createElement("div");
    section.className = "radio-inventory-group";
    const title = document.createElement("strong");
    title.textContent = "Group " + group;
    title.style.color = colorForGroup(group);
    section.append(title);
    for (const node of nodes) {
      const offline = node.state === "offline" || node.age_s === null || node.age_s > 10;
      const radios = node.radios || [];
      if (!radios.length) {
        const row = document.createElement("div");
        row.textContent = offline ? "Node offline" : "Waiting for radio discovery...";
        section.append(row);
      }
      for (const radio of radios) {
        const row = document.createElement("div");
        row.className = "radio-inventory-item";
        const label = document.createElement("span");
        label.textContent = radio.label || "Radio";
        const serial = document.createElement("code");
        serial.textContent = radio.serial || radio.uri || "Serial unavailable";
        row.append(label, serial);
        const detail = offline ? "Node offline" : radio.connected === false
          ? "Not detected" : radio.connected == null ? "Detection unavailable" : "";
        if (detail) {
          const note = document.createElement("span");
          note.textContent = detail;
          row.append(note);
        }
        section.append(row);
      }
    }
    els.connectedRadios.append(section);
  }
  if (!groups.size) els.connectedRadios.textContent = "No receiver groups available.";
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);
}

function renderGroups(metrics) {
  if (!metrics || Object.keys(metrics.groups).length === 0) {
    els.groupsGrid.innerHTML = '<div class="empty-state">No data yet.</div>';
    els.overallBanner.textContent = "No data yet.";
    return;
  }

  els.overallBanner.innerHTML = `Strongest group right now: <strong>${escapeHtml(metrics.strongest_group)}</strong>`;

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
        const adcPeak = !Number.isFinite(radio.adc_peak) ? "—"
          : radio.adc_peak < 8 ? `${radio.adc_peak} (too low: raise RX gain)`
          : radio.adc_peak > 1900 ? `${radio.adc_peak} (saturating: lower RX gain)` : radio.adc_peak;
        const ber = Number.isFinite(radio.ber) ? radio.ber.toExponential(1) : "—";
        return `<tr class="${rowClass}"><td>${escapeHtml(radio.serial || radio.uri)}${badge}</td><td>${power}</td><td>${snr}</td><td>${ber}</td><td>${adcPeak}</td></tr>`;
      })
      .join("");

    const meanPower = group.mean_power_db === null ? "—" : group.mean_power_db.toFixed(2);
    const meanNoise = group.mean_noise_db === null ? "—" : group.mean_noise_db.toFixed(2);

    cards.push(`
      <div class="group-card">
        <h3>Group ${escapeHtml(groupName)}</h3>
        <div class="group-summary">mean power=${meanPower} dB · mean noise=${meanNoise} dB</div>
        <table>
          <thead><tr><th>Radio</th><th>Power (dB)</th><th>Est. SNR (dB)</th><th>BER</th><th>ADC peak / 2048</th></tr></thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
    `);
  }
  els.groupsGrid.innerHTML = cards.join("");
}

function pushHistory(store, groupName, value, time) {
  if (!store[groupName]) store[groupName] = [];
  store[groupName].push({ t: time, value: Number.isFinite(value) ? value : null });
  if (store[groupName].length > MAX_HISTORY_POINTS) store[groupName].shift();
}

function updateHistories(metrics) {
  if (!metrics) return;
  if (historySession !== metrics.session_id) {
    resetHistory();
    historySession = metrics.session_id;
  }
  for (const [groupName, group] of Object.entries(metrics.groups)) {
    const timestamp = group.timestamp ?? metrics.timestamp;
    if (!Number.isFinite(timestamp)) continue;
    const key = String(group.sequence ?? "") + ":" + timestamp;
    if (lastSampleByGroup.get(groupName) === key) continue;
    lastSampleByGroup.set(groupName, key);
    if (historyStart === null) historyStart = timestamp;
    const time = timestamp - historyStart;
    pushHistory(powerHistory, groupName, group.mean_power_db, time);
    pushHistory(noiseHistory, groupName, group.mean_noise_db, time);
  }
}

function drawChart(canvas, store) {
  const ctx = canvas.getContext("2d");
  const width = canvas.width, height = canvas.height;
  ctx.clearRect(0, 0, width, height);
  const points = Object.values(store).flat();
  const valid = points.filter(point => Number.isFinite(point.value));
  if (!valid.length) {
    ctx.fillStyle = "#8b96ad";
    ctx.font = "12px sans-serif";
    ctx.fillText("No valid measurements yet", 55, 30);
    return;
  }

  // Keep at least a 20 dB span and expand only during this session.
  // Small fluctuations must not fill the full chart height.
  const low = Math.floor(Math.min(...valid.map(p => p.value)) / 10) * 10;
  const high = Math.ceil(Math.max(...valid.map(p => p.value)) / 10) * 10;
  const previous = chartRanges.get(canvas.id);
  let minVal = previous ? Math.min(previous.min, low) : low;
  let maxVal = previous ? Math.max(previous.max, high) : Math.max(high, low + 20);
  if (maxVal - minVal < 20) maxVal = minVal + 20;
  chartRanges.set(canvas.id, { min: minVal, max: maxVal });
  const minT = Math.min(...points.map(p => p.t));
  const maxT = Math.max(minT + 1, ...points.map(p => p.t));
  const left = 55, right = 15, top = 15, bottom = 38;
  const xScale = t => left + (t - minT) / (maxT - minT) * (width - left - right);
  const yScale = v => height - bottom - (v - minVal) / (maxVal - minVal) * (height - top - bottom);
  ctx.font = "11px sans-serif";
  ctx.lineWidth = 1;
  for (let i = 0; i <= 4; i++) {
    const value = minVal + i * (maxVal - minVal) / 4;
    const y = yScale(value);
    ctx.strokeStyle = "rgba(255,255,255,0.08)";
    ctx.beginPath(); ctx.moveTo(left, y); ctx.lineTo(width - right, y); ctx.stroke();
    ctx.fillStyle = "#8b96ad";
    ctx.textAlign = "right";
    ctx.fillText(value.toFixed(1), left - 7, y + 4);
    const time = minT + i * (maxT - minT) / 4;
    ctx.textAlign = "center";
    ctx.fillText(time.toFixed(1), xScale(time), height - bottom + 16);
  }
  ctx.textAlign = "left";
  ctx.fillText("dB (IQ units)", left, 11);
  ctx.textAlign = "center";
  ctx.fillText("Elapsed time (s)", (left + width - right) / 2, height - 5);
  for (const [name, values] of Object.entries(store)) {
    ctx.strokeStyle = colorForGroup(name);
    ctx.fillStyle = colorForGroup(name);
    ctx.lineWidth = 2;
    ctx.beginPath();
    let penDown = false;
    for (const point of values) {
      if (!Number.isFinite(point.value)) { penDown = false; continue; }
      const x = xScale(point.t), y = yScale(point.value);
      if (penDown) ctx.lineTo(x, y); else ctx.moveTo(x, y);
      penDown = true;
    }
    ctx.stroke();
    for (const point of values) {
      if (!Number.isFinite(point.value)) continue;
      ctx.beginPath(); ctx.arc(xScale(point.t), yScale(point.value), 2, 0, 2 * Math.PI); ctx.fill();
    }
  }
}

function renderLegend(container, store) {
  const names = Object.keys(store);
  container.innerHTML = names
    .map(
      (name) =>
        `<span class="legend-item"><span class="legend-swatch" style="background:${colorForGroup(name)}"></span>${escapeHtml(name)}</span>`
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
    showError(requestError || status.error);
    renderConnectedRadios(status);
    renderGroups(metrics);
    document.getElementById("session-info").textContent = status.session_id
      ? "Session: " + status.session_id + " · TX " + (status.tx?.state === "running" ? "on" : "off") + " · Metrics saved on server"
      : "No measurement session yet." ;

    if (status.state === "running") {
      updateHistories(metrics);
      drawChart(els.chartPower, powerHistory);
      drawChart(els.chartNoise, noiseHistory);
      renderLegend(els.legendPower, powerHistory);
      renderLegend(els.legendNoise, noiseHistory);
    }
  };

  ws.onclose = () => {
    els.statusDot.className = "dot error";
    els.statusText.textContent = "server unreachable";
    els.btnStart.disabled = true;
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
