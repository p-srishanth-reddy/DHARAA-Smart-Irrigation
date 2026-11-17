// DHARAA AI Irrigation Intelligence — Frontend Logic
// Handles prediction, AI-guided start, history charts, and model status display.

let aiFarmId     = null;
let aiDeviceId   = null;
let lastPrediction = null;
let chartComparison  = null;
let chartTimeline    = null;
let chartBeforeAfter = null;

// Priority badge styling
const PRIORITY_STYLE = {
  HIGH:   { cls: 'badge-error',   emoji: '🔴' },
  MEDIUM: { cls: 'badge-warning', emoji: '🟡' },
  LOW:    { cls: 'badge-neutral', emoji: '🟢' },
};

// -------------------------------------------------------------------------
// Bootstrap
// -------------------------------------------------------------------------
document.addEventListener('DOMContentLoaded', async () => {
  try {
    const farms = await API.get('/api/farms');
    if (!farms.length) {
      setStatus('No farms found. Please add a farm first.', 'error');
      return;
    }
    const farm = FarmSelection.resolve(farms, null);
    aiFarmId   = farm.id;

    // Populate farm selector
    const sel = document.getElementById('ai-farm-select');
    if (sel) {
      sel.innerHTML = farms.map(f =>
        `<option value="${f.id}"${f.id === farm.id ? ' selected' : ''}>${f.name} (${f.crop})</option>`
      ).join('');
      sel.addEventListener('change', () => {
        aiFarmId = parseInt(sel.value);
        aiDeviceId = null;
        FarmSelection.setId(aiFarmId);
        resetPrediction();
        loadModelStatus();
        loadHistory();
      });
    }

    // Resolve device
    const telem = await API.get(`/api/telemetry/latest?farm_id=${aiFarmId}`).catch(() => null);
    if (telem && telem.device) aiDeviceId = telem.device.id;

    // Show live telemetry context
    updateLiveTelemetryDisplay(telem);

    // Load model status and history
    await Promise.all([loadModelStatus(), loadHistory()]);

    // Wire up buttons
    document.getElementById('btn-ai-predict')?.addEventListener('click', runPrediction);
    document.getElementById('btn-ai-start')?.addEventListener('click', startAIIrrigation);
    document.getElementById('btn-train-model')?.addEventListener('click', triggerModelTrain);

    // Live telemetry context: refresh every 1.5s (matches simulator transmit rate)
    setInterval(async () => {
      const t = await API.get(`/api/telemetry/latest?farm_id=${aiFarmId}`).catch(() => null);
      updateLiveTelemetryDisplay(t);
      if (t && t.device) aiDeviceId = t.device.id;
    }, 1500);

    // History & model status: refresh every 10s (less frequent — data changes slowly)
    setInterval(async () => {
      await Promise.all([loadHistory(), loadModelStatus()]);
    }, 10000);

  } catch (err) {
    setStatus(`Initialisation error: ${err.message}`, 'error');
  }
});

// -------------------------------------------------------------------------
// Live Telemetry Context Display
// -------------------------------------------------------------------------
function updateLiveTelemetryDisplay(data) {
  const t = data?.telemetry;
  setText('ctx-moisture',    t?.moisture    != null ? `${t.moisture}%`    : '--');
  setText('ctx-temperature', t?.temperature != null ? `${t.temperature}°C` : '--');
  setText('ctx-humidity',    t?.humidity    != null ? `${t.humidity}%`    : '--');
  setText('ctx-rain',        t?.rain === 1 ? '🌧 Rain' : '☀ Dry');
  setText('ctx-pump',        data?.pump_control?.reported_state || '--');
  const staleBadge = document.getElementById('ctx-stale-badge');
  if (staleBadge) {
    staleBadge.textContent  = data?.is_stale ? 'Stale' : 'Live';
    staleBadge.className    = `badge-state ${data?.is_stale ? 'badge-warning' : 'badge-live'}`;
  }
}

// -------------------------------------------------------------------------
// Run Prediction
// -------------------------------------------------------------------------
async function runPrediction() {
  const btn = document.getElementById('btn-ai-predict');
  if (btn) { btn.disabled = true; btn.textContent = 'Predicting…'; }
  setStatus('Generating AI water requirement prediction…', 'info');
  hidePredictionResult();

  try {
    const result = await API.post('/api/ai-irrigation/predict', {
      farm_id:   aiFarmId,
      device_id: aiDeviceId,
    });
    lastPrediction = result;
    displayPrediction(result);
    setStatus('Prediction complete.', 'success');
  } catch (err) {
    setStatus(`Prediction failed: ${err.message}`, 'error');
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = '🔮 Generate AI Prediction'; }
  }
}

// -------------------------------------------------------------------------
// Display Prediction Result
// -------------------------------------------------------------------------
function displayPrediction(p) {
  const panel = document.getElementById('prediction-result-panel');
  if (!panel) return;
  panel.style.display = 'block';

  // Recommendation header
  const recommend = p.recommended_irrigate;
  const recBox    = document.getElementById('pred-recommend-box');
  if (recBox) {
    recBox.className = `recommendation-box ${recommend ? 'rec-yes' : 'rec-no'}`;
    recBox.innerHTML = recommend
      ? '<span class="rec-icon">💧</span><span class="rec-label">Irrigation Recommended</span>'
      : '<span class="rec-icon">✅</span><span class="rec-label">No Irrigation Needed</span>';
  }

  // Priority badge
  const pstyle = PRIORITY_STYLE[p.priority] || PRIORITY_STYLE.LOW;
  setBadge('pred-priority', p.priority || 'LOW', pstyle.cls);

  // Quantity metrics
  const ml  = p.predicted_water_ml  || 0;
  const dur = p.predicted_duration_s || 0;
  const tp  = p.target_pulses       || 0;

  setText('pred-water-ml',   ml  > 0 ? `${(ml / 1000).toFixed(2)} L (${ml.toFixed(0)} ml)` : '— N/A —');
  setText('pred-duration',   dur > 0 ? formatDuration(dur) : '— N/A —');
  setText('pred-pulses',     tp  > 0 ? `${tp} pulses` : '— N/A —');
  setText('pred-model',      p.estimator_type === 'random_forest' ? '🤖 RandomForest Model' : '📐 FAO-56 Baseline Estimator');
  setText('pred-explanation', p.explanation || '');

  // Weather adjustment note
  const adj = p.weather_adjustment || 'none';
  const adjEl = document.getElementById('pred-weather-adj');
  if (adjEl) {
    if (adj === 'none' || !adj)         { adjEl.style.display = 'none'; }
    else if (adj === 'postponed')        { adjEl.textContent = '⛈ Postponed: strong rain forecast'; adjEl.style.display = ''; adjEl.className = 'badge-state badge-info'; }
    else if (adj.startsWith('reduced')) { adjEl.textContent = `🌦 Quantity reduced (${adj})`; adjEl.style.display = ''; adjEl.className = 'badge-state badge-warning'; }
    else                                 { adjEl.textContent = adj; adjEl.style.display = ''; }
  }

  // Show/hide start button
  const startBtn = document.getElementById('btn-ai-start');
  if (startBtn) {
    startBtn.style.display = recommend ? 'inline-flex' : 'none';
  }

  // Context sub-row
  const ctx = p.context || {};
  setText('pred-ctx-fc',   ctx.field_capacity != null ? `${ctx.field_capacity}%` : '--');
  setText('pred-ctx-crop', ctx.crop || '--');
  setText('pred-ctx-soil', ctx.soil_type || '--');
  setText('pred-ctx-rain-prob', ctx.weather_rain_prob != null ? `${ctx.weather_rain_prob.toFixed(0)}%` : '--');
}

// -------------------------------------------------------------------------
// Start AI Irrigation
// -------------------------------------------------------------------------
async function startAIIrrigation() {
  if (!lastPrediction) { showToast('Run a prediction first.', 'warning'); return; }
  if (!lastPrediction.recommended_irrigate) {
    showToast('AI does not recommend irrigation now.', 'info');
    return;
  }

  const ml  = (lastPrediction.predicted_water_ml  || 0) / 1000;
  const dur = formatDuration(lastPrediction.predicted_duration_s || 0);
  if (!confirm(`⚠️ Confirm AI Irrigation\n\nTarget: ${ml.toFixed(2)} L\nEstimated runtime: ${dur}\nPriority: ${lastPrediction.priority}\n\nThis will queue a pump ON command to the ESP32.`)) return;

  const btn = document.getElementById('btn-ai-start');
  if (btn) { btn.disabled = true; btn.textContent = 'Starting…'; }

  try {
    const result = await API.post('/api/ai-irrigation/start', {
      farm_id:       aiFarmId,
      device_id:     aiDeviceId,
      prediction_id: lastPrediction.prediction_id,
    });
    showToast(`AI irrigation started! Target: ${(result.target_water_ml / 1000).toFixed(2)} L`, 'success');
    setStatus(`✅ AI irrigation running. Command #${result.command_id}. Event #${result.event_id}.`, 'success');
    setText('active-event-id',    result.event_id  || '--');
    setText('active-target-ml',   result.target_water_ml ? `${(result.target_water_ml/1000).toFixed(2)} L` : '--');
    setText('active-target-pulse', result.target_pulses || '--');
    document.getElementById('active-session-panel')?.style.setProperty('display', 'block');
    setTimeout(() => { loadHistory(); loadModelStatus(); }, 3000);
  } catch (err) {
    showToast(`Failed: ${err.message}`, 'error');
    setStatus(`Error starting AI irrigation: ${err.message}`, 'error');
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = '💧 Start AI Irrigation'; }
  }
}

// -------------------------------------------------------------------------
// Load History & Charts
// -------------------------------------------------------------------------
async function loadHistory() {
  if (!aiFarmId) return;
  try {
    const records = await API.get(`/api/ai-irrigation/history?farm_id=${aiFarmId}&limit=15`);
    renderHistoryTable(records);
    renderCharts(records);
  } catch (err) {
    console.warn('History load error:', err);
  }
}

function renderHistoryTable(records) {
  const tbody = document.getElementById('ai-history-tbody');
  if (!tbody) return;
  if (!records.length) {
    tbody.innerHTML = '<tr><td colspan="8" style="text-align:center;color:var(--text-muted);padding:24px">No AI irrigation cycles recorded yet. Run your first AI prediction to get started.</td></tr>';
    return;
  }
  tbody.innerHTML = records.map((r, i) => {
    const pml  = r.predicted_water_ml != null ? (r.predicted_water_ml / 1000).toFixed(2) : '--';
    const aml  = r.actual_water_ml    != null ? (r.actual_water_ml    / 1000).toFixed(2) : '--';
    const diff = (r.predicted_water_ml != null && r.actual_water_ml != null)
      ? ((r.actual_water_ml - r.predicted_water_ml) / 1000).toFixed(2)
      : '--';
    const diffColor = diff !== '--' ? (parseFloat(diff) > 0 ? '#3B82F6' : '#22A447') : 'var(--text-muted)';
    return `
      <tr>
        <td style="font-size:0.76rem;color:var(--text-muted)">${r.started_at ? r.started_at.split(' ')[0] : '--'}</td>
        <td>${r.initial_moisture != null ? r.initial_moisture.toFixed(1) + '%' : '--'}</td>
        <td>${r.final_moisture   != null ? r.final_moisture.toFixed(1)   + '%' : '--'}</td>
        <td style="color:#3B82F6">${pml} L</td>
        <td style="color:#22A447">${aml} L</td>
        <td style="color:${diffColor}">${diff !== '--' ? (parseFloat(diff) >= 0 ? '+' : '') + diff + ' L' : '--'}</td>
        <td>${r.stop_reason ? r.stop_reason.replace(/_/g, ' ') : '--'}</td>
        <td><span class="badge-state ${r.is_valid ? 'badge-live' : 'badge-error'}">${r.is_valid ? 'Valid' : 'Invalid'}</span></td>
      </tr>`;
  }).join('');
}

function renderCharts(records) {
  const valid = records.filter(r => r.is_valid);
  const chartData = valid.slice().reverse().map((r, i) => ({
    label:             r.started_at ? r.started_at.split(' ')[0].slice(5) : `S${i+1}`,
    predicted_ml:      r.predicted_water_ml,
    actual_ml:         r.actual_water_ml,
    initial_moisture:  r.initial_moisture,
    final_moisture:    r.final_moisture,
  }));

  if (chartComparison)  { chartComparison.destroy();  chartComparison  = null; }
  if (chartTimeline)    { chartTimeline.destroy();     chartTimeline    = null; }
  if (chartBeforeAfter) { chartBeforeAfter.destroy();  chartBeforeAfter = null; }

  chartComparison  = createWaterComparisonChart('chart-water-comparison',   chartData);
  chartTimeline    = createWaterTimelineChart('chart-water-timeline',         chartData);
  chartBeforeAfter = createMoistureBeforeAfterChart('chart-moisture-before-after', chartData);
}

// -------------------------------------------------------------------------
// Model Status
// -------------------------------------------------------------------------
async function loadModelStatus() {
  try {
    const status = await API.get('/api/ai-irrigation/model-status');
    renderModelStatus(status);
  } catch (err) {
    console.warn('Model status load error:', err);
  }
}

function renderModelStatus(s) {
  setText('model-estimator',  s.estimator_type === 'random_forest' ? '🤖 RandomForest Regressor' : '📐 FAO-56 Baseline Estimator');
  setText('model-version',    s.model_version || 'baseline_v1');
  setText('model-records',    `${s.valid_records} / ${s.records_needed} needed`);
  setText('model-flow-cal',   `${s.flow_ml_per_pulse?.toFixed(2)} ml/pulse (${s.pulses_per_litre} p/L)`);

  const activeModel = s.active_model_db;
  if (activeModel) {
    setText('model-mae',  activeModel.mae_ml != null ? `${activeModel.mae_ml} ml` : '--');
    setText('model-r2',   activeModel.r2_score != null ? activeModel.r2_score.toFixed(3) : '--');
    setText('model-trained-at', activeModel.trained_at || '--');
  } else {
    setText('model-mae', '--');
    setText('model-r2',  '--');
    setText('model-trained-at', 'Not trained yet');
  }

  const trainBtn  = document.getElementById('btn-train-model');
  const trainInfo = document.getElementById('train-info');
  if (trainBtn) {
    trainBtn.disabled = !s.can_train;
    trainBtn.title    = s.can_train
      ? `Retrain model on ${s.valid_records} records`
      : `Need ${s.records_needed - s.valid_records} more valid records to train`;
  }
  if (trainInfo) {
    if (s.can_train) {
      trainInfo.textContent = `✅ ${s.valid_records} records ready. Click to train the RandomForest model.`;
      trainInfo.style.color = 'var(--success)';
    } else {
      trainInfo.textContent = `📊 Collecting data: ${s.valid_records}/${s.records_needed} valid irrigation records. FAO-56 baseline active.`;
      trainInfo.style.color = 'var(--text-secondary)';
    }
  }
}

async function triggerModelTrain() {
  const btn = document.getElementById('btn-train-model');
  if (btn) { btn.disabled = true; btn.textContent = 'Training…'; }
  setStatus('Training RandomForest model on irrigation data…', 'info');
  try {
    const result = await API.post('/api/ai-irrigation/model-train', {});
    if (result.success) {
      showToast(`Model trained! MAE: ${result.mae_ml}ml, R²: ${result.r2_score}`, 'success');
      setStatus(`✅ ${result.message}`, 'success');
      await loadModelStatus();
    } else {
      showToast(result.message, 'warning');
      setStatus(result.message, 'warning');
    }
  } catch (err) {
    showToast(`Training failed: ${err.message}`, 'error');
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = '🧠 Train Model'; }
  }
}

// -------------------------------------------------------------------------
// Helpers
// -------------------------------------------------------------------------
function setText(id, val) {
  const el = document.getElementById(id);
  if (el) el.textContent = val ?? '--';
}

function setBadge(id, text, cls) {
  const el = document.getElementById(id);
  if (el) { el.textContent = text; el.className = `badge-state ${cls}`; }
}

function setStatus(msg, type = 'info') {
  const el = document.getElementById('ai-status-bar');
  if (!el) return;
  const colors = { info: '#2563EB', success: '#16A34A', error: '#DC2626', warning: '#D97706' };
  el.textContent  = msg;
  el.style.color  = colors[type] || colors.info;
  el.style.display = 'block';
}

function hidePredictionResult() {
  const p = document.getElementById('prediction-result-panel');
  if (p) p.style.display = 'none';
  const s = document.getElementById('btn-ai-start');
  if (s) s.style.display = 'none';
}

function resetPrediction() {
  lastPrediction = null;
  hidePredictionResult();
  setStatus('Select a farm and click "Generate AI Prediction".', 'info');
}

function formatDuration(seconds) {
  if (!seconds || seconds <= 0) return '0s';
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  return m > 0 ? `${m}m ${s}s` : `${s}s`;
}
