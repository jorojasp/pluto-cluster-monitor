// Pluto Cluster Monitor - local web frontend
// No external dependencies (no CDN, no build step) so this keeps working
// in a lab with no internet access. Charts are hand-drawn on <canvas>.

const MAX_HISTORY_POINTS = 120;

const els = {
  statusDot: document.getElementById("status-dot"),
  statusText: document.getElementById("status-text"),
  errorBanner: document.getElementById("error-banner"),
  overallBanner: document.getElementById("overall-banner"),
  groupsGrid: document.getElementById("groups-grid"),
  btnStart: document.getElementById("btn-start"),
  btnStop: document.getElementById("btn-stop"),
  mode: document.getElementById("mode"),
  toneField: document.getElementById("tone-field"),
  digitalFields: document.getElementById("digital-fields"),
  chartPower: document.getElementById("chart-power"),
  legendPower: document.getElementById("legend-power"),
  chartWeakest: document.getElementById("chart-weakest"),
  legendWeakest: document.getElementById("legend-weakest"),
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
const weakestPowerHistory = {};
let historyStartTime = null;

const GROUP_COLORS = {
  A: "#4f8cff", // blue
  B: "#f2b84b", // amber/orange
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
  historyStartTime = null;

  for (const key of Object.keys(powerHistory)) {
    delete powerHistory[key];
  }

  for (const key of Object.keys(weakestPowerHistory)) {
    delete weakestPowerHistory[key];
  }

  drawChart(els.chartPower, powerHistory);
  drawChart(els.chartWeakest, weakestPowerHistory);
  renderLegend(els.legendPower, powerHistory);
  renderLegend(els.legendWeakest, weakestPowerHistory);
}

function renderGroups(metrics) {
  if (!metrics || !metrics.groups || Object.keys(metrics.groups).length === 0) {
    els.groupsGrid.innerHTML = '<div class="empty-state">No data yet.</div>';
    els.overallBanner.textContent = "No data yet.";
    return;
  }

  els.overallBanner.innerHTML = `Strongest group right now: <strong>${metrics.strongest_group ?? "—"}</strong>`;

  const cards = [];

  for (const [groupName, group] of Object.entries(metrics.groups)) {
    const radios = Array.isArray(group.radios) ? group.radios : [];

    const rows = radios
      .map((radio) => {
        const rowClass = radio.is_strongest ? "strongest" : radio.is_weakest ? "weakest" : "";
        const badge = radio.is_strongest
          ? '<span class="badge strong">strongest</span>'
          : radio.is_weakest
          ? '<span class="badge weak">weakest</span>'
          : "";

        const power = Number.isFinite(radio.power_db) ? radio.power_db.toFixed(2) : "—";
        const snr = Number.isFinite(radio.snr_db) ? radio.snr_db.toFixed(2) : "—";

        return `<tr class="${rowClass}"><td>${radio.serial || radio.uri}${badge}</td><td>${power}</td><td>${snr}</td></tr>`;
      })
      .join("");

    const meanPower = Number.isFinite(group.mean_power_db) ? group.mean_power_db.toFixed(2) : "—";
    const meanNoise = Number.isFinite(group.mean_noise_db) ? group.mean_noise_db.toFixed(2) : "—";

    cards.push(`
      <div class="group-card">
        <h3>Group ${groupName}</h3>
        <div class="group-summary">Mean power: ${meanPower} dB · Mean noise: ${meanNoise} dB</div>
        <table>
          <thead>
            <tr>
              <th>Radio</th>
              <th>Power (dB)</th>
              <th>SNR (dB)</th>
            </tr>
          </thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
    `);
  }

  els.groupsGrid.innerHTML = cards.join("");
}

function pushHistory(store, groupName, value, timeSeconds) {
  if (!Number.isFinite(value)) return;

  if (!store[groupName]) {
    store[groupName] = [];
  }

  store[groupName].push({
    t: timeSeconds,
    value,
  });

  if (store[groupName].length > MAX_HISTORY_POINTS) {
    store[groupName].shift();
  }
}

function findWeakestRadio(group) {
  const radios = Array.isArray(group.radios) ? group.radios : [];

  const markedWeakest = radios.find(
    (radio) => radio.is_weakest && Number.isFinite(radio.power_db)
  );

  if (markedWeakest) {
    return markedWeakest;
  }

  let weakest = null;

  for (const radio of radios) {
    if (!Number.isFinite(radio.power_db)) continue;

    if (weakest === null || radio.power_db < weakest.power_db) {
      weakest = radio;
    }
  }

  return weakest;
}

function updateHistories(metrics) {
  if (!metrics || !metrics.groups) return;

  if (historyStartTime === null) {
    historyStartTime = performance.now();
  }

  const timeSeconds = (performance.now() - historyStartTime) / 1000;

  for (const [groupName, group] of Object.entries(metrics.groups)) {
    pushHistory(
      powerHistory,
      groupName,
      group.mean_power_db,
      timeSeconds
    );

    const weakestRadio = findWeakestRadio(group);

    if (weakestRadio) {
      pushHistory(
        weakestPowerHistory,
        groupName,
        weakestRadio.power_db,
        timeSeconds
      );
    }
  }
}

function drawChart(canvas, store) {
  if (!canvas) return;

  const ctx = canvas.getContext("2d");
  const width = canvas.width;
  const height = canvas.height;

  ctx.clearRect(0, 0, width, height);

  const groupNames = Object.keys(store).filter(
    (name) => Array.isArray(store[name]) && store[name].length > 0
  );

  if (groupNames.length === 0) {
    return;
  }

  let minVal = Infinity;
  let maxVal = -Infinity;
  let minT = Infinity;
  let maxT = -Infinity;

  for (const name of groupNames) {
    for (const point of store[name]) {
      if (!Number.isFinite(point.value) || !Number.isFinite(point.t)) continue;

      minVal = Math.min(minVal, point.value);
      maxVal = Math.max(maxVal, point.value);
      minT = Math.min(minT, point.t);
      maxT = Math.max(maxT, point.t);
    }
  }

  if (
    !Number.isFinite(minVal) ||
    !Number.isFinite(maxVal) ||
    !Number.isFinite(minT) ||
    !Number.isFinite(maxT)
  ) {
    return;
  }

  if (minVal === maxVal) {
    minVal -= 1;
    maxVal += 1;
  }

  if (minT === maxT) {
    maxT = minT + 1;
  }

  const valueRange = maxVal - minVal;
  minVal -= valueRange * 0.08;
  maxVal += valueRange * 0.08;

  const marginLeft = 72;
  const marginRight = 20;
  const marginTop = 20;
  const marginBottom = 58;

  const plotWidth = width - marginLeft - marginRight;
  const plotHeight = height - marginTop - marginBottom;

  const xScale = (t) =>
    marginLeft + ((t - minT) / (maxT - minT)) * plotWidth;

  const yScale = (value) =>
    marginTop +
    (1 - (value - minVal) / (maxVal - minVal)) * plotHeight;

  const axisText = "rgba(220, 225, 235, 0.82)";
  const axisLine = "rgba(255,255,255,0.25)";
  const gridLine = "rgba(255,255,255,0.07)";
  const verticalGridLine = "rgba(255,255,255,0.05)";

  // Horizontal grid and Y-axis tick labels.
  ctx.font = "12px Arial, sans-serif";
  const yTicks = 5;

  for (let i = 0; i <= yTicks; i++) {
    const ratio = i / yTicks;
    const y = marginTop + ratio * plotHeight;
    const value = maxVal - ratio * (maxVal - minVal);

    ctx.strokeStyle = gridLine;
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(marginLeft, y);
    ctx.lineTo(width - marginRight, y);
    ctx.stroke();

    ctx.fillStyle = axisText;
    ctx.textAlign = "right";
    ctx.textBaseline = "middle";
    ctx.fillText(value.toFixed(1), marginLeft - 8, y);
  }

  // Vertical grid and X-axis tick labels.
  const xTicks = 5;

  for (let i = 0; i <= xTicks; i++) {
    const ratio = i / xTicks;
    const x = marginLeft + ratio * plotWidth;
    const time = minT + ratio * (maxT - minT);

    ctx.strokeStyle = verticalGridLine;
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(x, marginTop);
    ctx.lineTo(x, height - marginBottom);
    ctx.stroke();

    ctx.fillStyle = axisText;
    ctx.textAlign = "center";
    ctx.textBaseline = "top";
    ctx.fillText(time.toFixed(1), x, height - marginBottom + 8);
  }

  // X-axis label.
  ctx.fillStyle = "rgba(230,235,245,0.92)";
  ctx.font = "13px Arial, sans-serif";
  ctx.textAlign = "center";
  ctx.textBaseline = "bottom";
  ctx.fillText("Time (s)", marginLeft + plotWidth / 2, height - 6);

  // Y-axis label.
  ctx.save();
  ctx.translate(17, marginTop + plotHeight / 2);
  ctx.rotate(-Math.PI / 2);
  ctx.textAlign = "center";
  ctx.textBaseline = "top";
  ctx.fillText("Power (dB)", 0, 0);
  ctx.restore();

  // Axis lines.
  ctx.strokeStyle = axisLine;
  ctx.lineWidth = 1;

  ctx.beginPath();
  ctx.moveTo(marginLeft, marginTop);
  ctx.lineTo(marginLeft, height - marginBottom);
  ctx.stroke();

  ctx.beginPath();
  ctx.moveTo(marginLeft, height - marginBottom);
  ctx.lineTo(width - marginRight, height - marginBottom);
  ctx.stroke();

  // Group power traces.
  for (const name of groupNames) {
    const points = store[name].filter(
      (point) => Number.isFinite(point.value) && Number.isFinite(point.t)
    );

    if (points.length === 0) continue;

    ctx.strokeStyle = colorForGroup(name);
    ctx.lineWidth = 2;
    ctx.beginPath();

    points.forEach((point, index) => {
      const x = xScale(point.t);
      const y = yScale(point.value);

      if (index === 0) {
        ctx.moveTo(x, y);
      } else {
        ctx.lineTo(x, y);
      }
    });

    ctx.stroke();
  }
}

function renderLegend(container, store) {
  if (!container) return;

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
    renderGroups(metrics);

    if (status.state === "running") {
      updateHistories(metrics);

      drawChart(
        els.chartPower,
        powerHistory
      );

      renderLegend(
        els.legendPower,
        powerHistory
      );

      drawChart(
        els.chartWeakest,
        weakestPowerHistory
      );

      renderLegend(
        els.legendWeakest,
        weakestPowerHistory
      );
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

// Keep the state consistent on first load in case the service was already
// running before this tab was opened.
fetch("/api/status")
  .then((res) => res.json())
  .then((status) => {
    setStatus(status.state);

    if (status.state === "running") {
      els.btnStart.disabled = true;
      els.btnStop.disabled = false;
    }
  })
  .catch(() => {});
