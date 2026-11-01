// DHARAA Dashboard Orchestration Logic

let currentFarmId = 1;
let currentDeviceId = 1;
let telemetryTimer = null;
let moistureChartInstance = null;
let pumpRuntimeSeconds = 0;
let pumpTimer = null;

document.addEventListener("DOMContentLoaded", async () => {
  await loadFarmsHeader();
  await initDashboard();
  setupEventListeners();

  // Start continuous polling loop every 3 seconds
  telemetryTimer = setInterval(pollTelemetry, 3000);
});

async function loadFarmsHeader() {
  try {
    const farms = await API.get('/api/farms');
    const select = document.getElementById('farm-select');
    if (select && farms.length > 0) {
      select.innerHTML = farms.map(f => `<option value="${f.id}">${f.name} (${f.crop})</option>`).join('');
      currentFarmId = farms[0].id;
      select.addEventListener('change', (e) => {
        currentFarmId = parseInt(e.target.value);
        pollTelemetry();
        loadTelemetryHistory();
        loadIrrigationEvents();
      });
    }
  } catch (err) {
    console.error("Failed to load farms:", err);
  }
}

async function initDashboard() {
  await pollTelemetry();
  await loadTelemetryHistory();
  await loadIrrigationEvents();
}

async function pollTelemetry() {
  try {
    const data = await API.get(`/api/telemetry/latest?farm_id=${currentFarmId}`);
    updateDeviceStatus(data);
    updateSensorCards(data);
    updatePumpControl(data);
  } catch (err) {
    console.warn("Telemetry poll error:", err);
  }
}

function updateDeviceStatus(data) {
  const pill = document.getElementById('device-status-pill');
  const text = document.getElementById('device-status-text');
  const devName = document.getElementById('device-name-text');

  if (!pill) return;

  if (data.status === 'NO_DATA') {
    pill.className = 'device-status-pill offline';
    text.textContent = 'No Telemetry Recorded';
  } else if (data.is_stale) {
    pill.className = 'device-status-pill stale';
    text.textContent = `Stale Reading (${data.age_seconds}s ago)`;
  } else {
    pill.className = 'device-status-pill online';
    text.textContent = `Live Telemetry (Updated ${data.age_seconds}s ago)`;
  }

  if (data.device && devName) {
    devName.textContent = data.device.name;
    currentDeviceId = data.device.id;
  }
}

function updateSensorCards(data) {
  const t = data.telemetry;
  const isStale = data.is_stale;

  // 1. Soil Moisture
  const mVal = document.getElementById('val-moisture');
  const mBadge = document.getElementById('badge-moisture');
  const mBar = document.getElementById('bar-moisture');

  if (t && t.moisture !== null) {
    mVal.innerHTML = `${t.moisture}<span class="card-unit">%</span>`;
    if (mBar) mBar.style.width = `${Math.min(100, Math.max(0, t.moisture))}%`;
    
    if (isStale) {
      mBadge.className = 'badge-state badge-stale';
      mBadge.textContent = 'Stale';
    } else {
      mBadge.className = 'badge-state badge-live';
      mBadge.textContent = 'Live Calibrated';
    }
  } else {
    mVal.innerHTML = `--<span class="card-unit">%</span>`;
    mBadge.className = 'badge-state badge-error';
    mBadge.textContent = t ? (t.sensor_status || 'Error') : 'No Data';
  }

  // 2. Temperature & Humidity
  const tempVal = document.getElementById('val-temperature');
  const humVal = document.getElementById('val-humidity');
  if (t && t.temperature !== null) {
    tempVal.innerHTML = `${t.temperature}<span class="card-unit">°C</span>`;
  } else {
    tempVal.innerHTML = `--<span class="card-unit">°C</span>`;
  }
  if (t && t.humidity !== null) {
    humVal.innerHTML = `${t.humidity}<span class="card-unit">%</span>`;
  } else {
    humVal.innerHTML = `--<span class="card-unit">%</span>`;
  }

  // 3. Rain Sensor
  const rainVal = document.getElementById('val-rain');
  const rainBadge = document.getElementById('badge-rain');
  if (t) {
    if (t.rain === 1) {
      rainVal.textContent = 'Rain Detected';
      rainVal.style.color = '#38bdf8';
      rainBadge.className = 'badge-state badge-live';
      rainBadge.textContent = 'Wet Surface';
    } else {
      rainVal.textContent = 'Dry Field';
      rainVal.style.color = '#94a3b8';
      rainBadge.className = 'badge-state badge-live';
      rainBadge.textContent = 'No Rain';
    }
  }

  // 4. Flow Sensor
  const flowVal = document.getElementById('val-flow');
  if (t) {
    const pulses = t.flow_pulses || 0;
    // YF-S201 calibrated calculation
    const litres = (pulses / 450.0).toFixed(2);
    flowVal.innerHTML = `${pulses} <span class="card-unit">pulses (~${litres} L)</span>`;
  }

  // 5. Update Rule Engine explanation
  updateRuleSummary(t);
}

function updateRuleSummary(t) {
  const summaryBox = document.getElementById('rule-summary-text');
  if (!summaryBox) return;

  if (!t) {
    summaryBox.textContent = "Awaiting hardware telemetry to evaluate irrigation rules.";
    return;
  }

  let explanation = "";
  if (t.rain === 1) {
    explanation = "⚠️ Pump locked OFF: Surface rain detected on field. Irrigation inhibited to prevent waterlogging.";
  } else if (t.moisture !== null && t.moisture < 35.0) {
    explanation = `💧 Soil moisture (${t.moisture}%) is BELOW trigger threshold (35.0%). Automated irrigation requested ON.`;
  } else if (t.moisture !== null && t.moisture >= 45.0) {
    explanation = `✅ Soil moisture (${t.moisture}%) has reached recovery target (45.0%). Automated irrigation switched OFF.`;
  } else {
    explanation = `⚖️ Soil moisture (${t.moisture}%) is within safe nominal hysteresis band (35% - 45%). System idle.`;
  }
  summaryBox.textContent = explanation;
}

function updatePumpControl(data) {
  const reqEl = document.getElementById('state-requested');
  const repEl = document.getElementById('state-reported');
  const runtimeEl = document.getElementById('pump-runtime');

  const ctrl = data.pump_control || {};
  const requested = ctrl.requested_state || 'OFF';
  const reported = ctrl.reported_state || 'OFF';

  if (reqEl) {
    reqEl.textContent = requested;
    reqEl.className = `indicator-state ${requested === 'ON' ? 'state-on' : (requested === 'EMERGENCY_STOP' ? 'state-emergency' : 'state-off')}`;
  }

  if (repEl) {
    repEl.textContent = reported;
    repEl.style.color = reported === 'ON' ? 'var(--success)' : 'var(--text-muted)';
  }

  const repMirror = document.getElementById('state-reported-mirror');
  if (repMirror) {
    repMirror.textContent = reported;
    repMirror.className = `indicator-state ${reported === 'ON' ? 'state-on' : 'state-off'}`;
  }

  // Manage runtime timer
  if (reported === 'ON') {
    if (!pumpTimer) {
      pumpTimer = setInterval(() => {
        pumpRuntimeSeconds++;
        const mins = Math.floor(pumpRuntimeSeconds / 60);
        const secs = pumpRuntimeSeconds % 60;
        if (runtimeEl) runtimeEl.textContent = `${mins}m ${secs < 10 ? '0' : ''}${secs}s`;
      }, 1000);
    }
  } else {
    if (pumpTimer) {
      clearInterval(pumpTimer);
      pumpTimer = null;
      pumpRuntimeSeconds = 0;
    }
    if (runtimeEl) runtimeEl.textContent = '0m 00s';
  }
}

async function loadTelemetryHistory() {
  try {
    const history = await API.get(`/api/telemetry/history?device_id=${currentDeviceId}&limit=30`);
    if (moistureChartInstance) {
      moistureChartInstance.destroy();
    }
    moistureChartInstance = createMoistureChart('chart-moisture', history);
  } catch (err) {
    console.error("Failed to load history chart:", err);
  }
}

async function loadIrrigationEvents() {
  try {
    const events = await API.get(`/api/irrigation/events?farm_id=${currentFarmId}&limit=5`);
    const tableBody = document.getElementById('events-table-body');
    if (!tableBody) return;

    if (events.length === 0) {
      tableBody.innerHTML = `<tr><td colspan="5" style="text-align: center; color: var(--text-muted);">No irrigation events recorded yet.</td></tr>`;
      return;
    }

    tableBody.innerHTML = events.map(e => `
      <tr>
        <td><strong>${e.started_at ? e.started_at.split(' ')[1] : '--'}</strong> <span style="font-size:0.75rem; color:var(--text-muted)">${e.started_at ? e.started_at.split(' ')[0] : ''}</span></td>
        <td><span class="badge-state ${e.status === 'running' ? 'badge-live' : 'badge-stale'}">${e.status}</span></td>
        <td>${e.trigger_source || 'auto'}</td>
        <td>${e.estimated_litres ? e.estimated_litres + ' L' : '<span style="color:var(--text-muted)">Uncalibrated</span>'}</td>
        <td>${e.stop_reason || '--'}</td>
      </tr>
    `).join('');
  } catch (err) {
    console.error("Failed to load events:", err);
  }
}

function setupEventListeners() {
  // Manual ON
  const btnOn = document.getElementById('btn-pump-on');
  if (btnOn) {
    btnOn.addEventListener('click', async () => {
      try {
        await API.post('/api/irrigation/command', {
          device_id: currentDeviceId,
          type: 'ON',
          reason: 'Manual activation from dashboard'
        });
        showToast("Pump ON command queued to ESP32", "success");
        pollTelemetry();
      } catch (err) {
        showToast(`Failed: ${err.message}`, "error");
      }
    });
  }

  // Manual OFF
  const btnOff = document.getElementById('btn-pump-off');
  if (btnOff) {
    btnOff.addEventListener('click', async () => {
      try {
        await API.post('/api/irrigation/command', {
          device_id: currentDeviceId,
          type: 'OFF',
          reason: 'Manual deactivation from dashboard'
        });
        showToast("Pump OFF command queued to ESP32", "info");
        pollTelemetry();
      } catch (err) {
        showToast(`Failed: ${err.message}`, "error");
      }
    });
  }

  // Emergency Stop
  const btnEmergency = document.getElementById('btn-emergency-stop');
  if (btnEmergency) {
    btnEmergency.addEventListener('click', async () => {
      if (confirm("⚠️ CRITICAL ACTION: Are you sure you want to trigger EMERGENCY STOP? All pump operation will be halted immediately!")) {
        try {
          await API.post('/api/irrigation/command', {
            device_id: currentDeviceId,
            type: 'EMERGENCY_STOP',
            reason: 'EMERGENCY STOP BUTTON CLICKED BY USER'
          });
          showToast("EMERGENCY STOP EXECUTED!", "error");
          pollTelemetry();
        } catch (err) {
          showToast(`Emergency stop failed: ${err.message}`, "error");
        }
      }
    });
  }
}
