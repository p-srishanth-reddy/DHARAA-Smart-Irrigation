// DHARAA Dashboard Orchestration Logic

let currentFarmId = null;
let currentDeviceId = null;
let telemetryTimer = null;
let moistureChartInstance = null;
let pumpRuntimeSeconds = 0;
let pumpTimer = null;
let farmSelectionVersion = 0;

document.addEventListener("DOMContentLoaded", async () => {
  const hasFarm = await loadFarmsHeader();
  if (!hasFarm) return;

  setupEventListeners();
  await refreshSelectedFarm();

  // Start continuous polling loop every 1.5 seconds for near-real-time updates
  telemetryTimer = setInterval(() => pollTelemetry(), 1500);
});

async function loadFarmsHeader() {
  try {
    const farms = await API.get('/api/farms');
    const select = document.getElementById('farm-select');
    if (select && farms.length > 0) {
      select.disabled = false;
      select.innerHTML = farms.map(f => `<option value="${f.id}">${f.name} (${f.crop})</option>`).join('');
      const requestedFarmId = new URLSearchParams(window.location.search).get('farm_id');
      const activeFarm = FarmSelection.resolve(farms, requestedFarmId);
      select.value = String(activeFarm.id);
      updateFarmDetails(activeFarm);

      const url = new URL(window.location.href);
      if (url.searchParams.has('farm_id')) {
        url.searchParams.delete('farm_id');
        window.history.replaceState(null, '', `${url.pathname}${url.search}${url.hash}`);
      }

      select.addEventListener('change', event => {
        FarmSelection.setId(event.target.value);
      });
      FarmSelection.onChange(farmId => {
        const farm = farms.find(item => item.id === farmId);
        if (!farm || farm.id === currentFarmId) return;
        select.value = String(farm.id);
        updateFarmDetails(farm);

        // Sync active farm selection with backend for telemetry attribution
        API.post('/api/devices/set_active_farm', {
          device_id: currentDeviceId || 1, // Fallback to default device
          farm_id: farmId
        }).catch(err => console.error("Failed to sync active farm:", err));

        void refreshSelectedFarm();
      });
      currentFarmId = activeFarm.id;
      return true;
    }
    if (select) {
      select.innerHTML = '<option value="">No farms available</option>';
      select.disabled = true;
    }
    const subtitle = document.getElementById('farm-details');
    if (subtitle) subtitle.textContent = 'No farms are registered. Add a farm to begin.';
    return false;
  } catch (err) {
    console.error("Failed to load farms:", err);
    return false;
  }
}

function updateFarmDetails(farm) {
  currentFarmId = farm.id;
  const subtitle = document.getElementById('farm-details');
  if (!subtitle) return;

  const location = farm.location_hierarchy || farm.state_district || 'Location not specified';
  const area = farm.area !== null && farm.area !== undefined
    ? ` · ${farm.area} ${farm.area_unit || ''}`.trimEnd()
    : '';
  subtitle.textContent = `Farm #${farm.id} · ${farm.name} · ${location} · ${farm.crop}${area}`;
}

async function refreshSelectedFarm() {
  const version = ++farmSelectionVersion;
  currentDeviceId = null;
  clearFarmData();
  await pollTelemetry(version);
  if (version !== farmSelectionVersion) return;
  await Promise.all([
    loadTelemetryHistory(currentDeviceId, version),
    loadIrrigationEvents(version)
  ]);
}

function clearFarmData() {
  const statusPill = document.getElementById('device-status-pill');
  const statusText = document.getElementById('device-status-text');
  const deviceName = document.getElementById('device-name-text');
  if (statusPill) statusPill.className = 'device-status-pill stale';
  if (statusText) statusText.textContent = 'Loading Farm Data...';
  if (deviceName) deviceName.textContent = '--';

  updateSensorCards({ telemetry: null, is_stale: true });
  const moistureBar = document.getElementById('bar-moisture');
  if (moistureBar) moistureBar.style.width = '0%';
  updatePumpControl({});

  const tableBody = document.getElementById('events-table-body');
  if (tableBody) {
    tableBody.innerHTML = '<tr><td colspan="5" style="text-align: center; color: var(--text-muted);">Loading farm events...</td></tr>';
  }
  if (moistureChartInstance) {
    moistureChartInstance.destroy();
    moistureChartInstance = null;
  }
  moistureChartInstance = createMoistureChart('chart-moisture', []);
}

async function pollTelemetry(version = farmSelectionVersion) {
  const farmId = currentFarmId;
  if (farmId === null) return;

  try {
    const data = await API.get(`/api/telemetry/latest?farm_id=${farmId}`);
    if (version !== farmSelectionVersion || farmId !== currentFarmId) return;
    updateDeviceStatus(data);
    updateSensorCards(data);
    updatePumpControl(data);
  } catch (err) {
    if (version === farmSelectionVersion && farmId === currentFarmId) {
      const pill = document.getElementById('device-status-pill');
      const text = document.getElementById('device-status-text');
      if (pill) pill.className = 'device-status-pill offline';
      if (text) text.textContent = 'Telemetry Unavailable';
    }
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
  } else {
    rainVal.textContent = 'No Data';
    rainBadge.className = 'badge-state badge-error';
    rainBadge.textContent = 'Unavailable';
  }

  // 4. Flow Sensor
  const flowVal = document.getElementById('val-flow');
  if (t) {
    const pulses = t.flow_pulses || 0;
    // YF-S201 calibrated calculation
    const litres = (pulses / 450.0).toFixed(2);
    flowVal.innerHTML = `${pulses} <span class="card-unit">pulses (~${litres} L)</span>`;
  } else {
    flowVal.textContent = 'No Data';
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
  const reqEl     = document.getElementById('state-requested');
  const repEl     = document.getElementById('state-reported');
  const repMirror = document.getElementById('state-reported-mirror');
  const runtimeEl = document.getElementById('pump-runtime');
  const btnOn     = document.getElementById('btn-pump-on');
  const btnOff    = document.getElementById('btn-pump-off');

  const ctrl     = data.pump_control || {};
  const lastCmd  = ctrl.last_command || {};
  const reported = ctrl.reported_state || 'OFF';   // Ground truth: what ESP32 last reported

  // -------------------------------------------------------------------------
  // Determine effective displayed state.
  // "Requested State" = what the backend last commanded.
  // If a command is pending/delivered (ESP32 hasn't ACK'd yet), show it.
  // If the last command is completed/acknowledged, trust the reported state.
  // -------------------------------------------------------------------------
  const cmdType   = (lastCmd.type   || '').toUpperCase();
  const cmdStatus = (lastCmd.status || '').toLowerCase();
  const isPending = cmdStatus === 'pending' || cmdStatus === 'delivered';

  let requested;
  if (isPending && cmdType) {
    // Command in-flight — show what was commanded
    requested = cmdType;   // 'ON', 'OFF', or 'EMERGENCY_STOP'
  } else {
    // No pending command → effective state = what the hardware reports
    requested = reported;
  }

  // The single authoritative pump state to drive all UI from is the REPORTED state.
  // Requested is shown as a secondary hint only.
  const pumpIsOn = (reported === 'ON');

  // Update top metric card ("Pump Operational State")
  if (repEl) {
    repEl.textContent  = reported;
    repEl.style.color  = pumpIsOn ? 'var(--success)' : 'var(--text-muted)';
    repEl.style.fontWeight = '700';
  }

  // Update pump indicator box
  if (reqEl) {
    reqEl.textContent = requested;
    reqEl.className   = `indicator-state ${
      requested === 'ON' ? 'state-on' :
      requested === 'EMERGENCY_STOP' ? 'state-emergency' : 'state-off'
    }`;
  }
  if (repMirror) {
    repMirror.textContent = reported;
    repMirror.className   = `indicator-state ${pumpIsOn ? 'state-on' : 'state-off'}`;
  }

  // -------------------------------------------------------------------------
  // Button state: disable whichever button matches current reported state.
  // This prevents double-commands and gives clear visual feedback.
  // -------------------------------------------------------------------------
  if (btnOn) {
    btnOn.disabled = pumpIsOn;   // Disable START when pump is already ON
    btnOn.style.opacity = pumpIsOn ? '0.5' : '1';
    btnOn.title = pumpIsOn ? 'Pump is already running' : 'Turn Pump ON with pre-flight safety check';
  }
  if (btnOff) {
    btnOff.disabled = !pumpIsOn;   // Disable STOP when pump is already OFF
    btnOff.style.opacity = !pumpIsOn ? '0.5' : '1';
    btnOff.title = !pumpIsOn ? 'Pump is already stopped' : 'Turn Pump OFF';
  }

  // -------------------------------------------------------------------------
  // Runtime timer — driven exclusively by REPORTED state (hardware truth)
  // -------------------------------------------------------------------------
  if (pumpIsOn) {
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

async function loadTelemetryHistory(deviceId = currentDeviceId, version = farmSelectionVersion) {
  if (!deviceId) return;
  try {
    const history = await API.get(`/api/telemetry/history?device_id=${deviceId}&limit=30`);
    if (version !== farmSelectionVersion || deviceId !== currentDeviceId) return;
    if (moistureChartInstance) {
      moistureChartInstance.destroy();
    }
    moistureChartInstance = createMoistureChart('chart-moisture', history);
  } catch (err) {
    console.error("Failed to load history chart:", err);
  }
}

async function loadIrrigationEvents(version = farmSelectionVersion) {
  const farmId = currentFarmId;
  if (farmId === null) return;
  try {
    const events = await API.get(`/api/irrigation/events?farm_id=${farmId}&limit=5`);
    if (version !== farmSelectionVersion || farmId !== currentFarmId) return;
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
      if (btnOn.disabled) return;
      // Optimistic UI: show pending state immediately
      btnOn.disabled  = true;
      btnOn.style.opacity = '0.5';
      const reqEl = document.getElementById('state-requested');
      if (reqEl) { reqEl.textContent = 'ON'; reqEl.className = 'indicator-state state-on'; }
      try {
        await API.post('/api/irrigation/command', {
          device_id: currentDeviceId,
          type: 'ON',
          reason: 'Manual activation from dashboard'
        });
        showToast("Pump ON command queued to ESP32", "success");
        // Poll immediately so UI reflects the new command status
        setTimeout(() => pollTelemetry(), 300);
      } catch (err) {
        showToast(`Failed: ${err.message}`, "error");
        // Revert optimistic state on error
        btnOn.disabled = false;
        btnOn.style.opacity = '1';
        if (reqEl) { reqEl.textContent = 'OFF'; reqEl.className = 'indicator-state state-off'; }
      }
    });
  }

  // Manual OFF
  const btnOff = document.getElementById('btn-pump-off');
  if (btnOff) {
    btnOff.addEventListener('click', async () => {
      if (btnOff.disabled) return;
      // Optimistic UI: show pending state immediately
      btnOff.disabled = true;
      btnOff.style.opacity = '0.5';
      const reqEl = document.getElementById('state-requested');
      if (reqEl) { reqEl.textContent = 'OFF'; reqEl.className = 'indicator-state state-off'; }
      try {
        await API.post('/api/irrigation/command', {
          device_id: currentDeviceId,
          type: 'OFF',
          reason: 'Manual deactivation from dashboard'
        });
        showToast("Pump OFF command queued to ESP32", "info");
        setTimeout(() => pollTelemetry(), 300);
      } catch (err) {
        showToast(`Failed: ${err.message}`, "error");
        btnOff.disabled = false;
        btnOff.style.opacity = '1';
        if (reqEl) { reqEl.textContent = 'ON'; reqEl.className = 'indicator-state state-on'; }
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
          const reqEl = document.getElementById('state-requested');
          if (reqEl) { reqEl.textContent = 'EMERGENCY_STOP'; reqEl.className = 'indicator-state state-emergency'; }
          setTimeout(() => pollTelemetry(), 300);
        } catch (err) {
          showToast(`Emergency stop failed: ${err.message}`, "error");
        }
      }
    });
  }
}
