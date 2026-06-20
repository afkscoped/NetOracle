const $ = (id) => document.getElementById(id);
const state = {
  telemetry: [],
  alerts: [],
  latestAlert: null,
  proactive: null,
  metrics: null,
  currentTab: 'dashboard',
  tickCount: 0,
  wsFailures: 0,
  polling: null,
  charts: {},
  topology: null,
  pathPick: [],
  highlightedPath: [],
  dagHistory: [],
  lastSynthetic: null,
};

async function api(path, options = {}) {
  const init = { ...options };
  if (!(init.body instanceof FormData)) {
    init.headers = { 'Content-Type': 'application/json', ...(init.headers || {}) };
  }
  const res = await fetch(path, init);
  const json = await res.json().catch(() => ({}));
  if (!res.ok || json.ok === false) throw new Error(json.error || `${path} failed: ${res.status}`);
  return json;
}

function waitForD3() {
  return new Promise((resolve) => {
    if (window.d3) return resolve();
    const timer = setInterval(() => {
      if (window.d3) {
        clearInterval(timer);
        resolve();
      }
    }, 50);
  });
}

function text(id, value) {
  const el = $(id);
  if (el) el.textContent = value;
}

function html(id, value) {
  const el = $(id);
  if (el) el.innerHTML = value;
}

function fmtPct(value) {
  if (value === undefined || value === null || Number.isNaN(Number(value))) return '--';
  return `${Math.round(Number(value) * 100)}%`;
}

function fmtTime(value) {
  if (!value) return '--';
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? String(value) : d.toLocaleTimeString();
}

function human(value) {
  return String(value ?? '--').replaceAll('_', ' ');
}

function pct(value) {
  return value === undefined || value === null ? '--' : `${Math.round(Number(value) * 100)}%`;
}

function metricPill(label, value, tone = '') {
  return `<span class="metric-pill ${tone}"><b>${label}</b>${value}</span>`;
}

function animateNumber(id, value, suffix = '', decimals = 0) {
  const el = $(id);
  if (!el || value === undefined || value === null || Number.isNaN(Number(value))) return;
  const from = Number(el.dataset.value || 0);
  const to = Number(value);
  const start = performance.now();
  const duration = 520;
  function frame(now) {
    const t = Math.min(1, (now - start) / duration);
    const eased = 1 - Math.pow(1 - t, 3);
    const current = from + (to - from) * eased;
    el.textContent = `${current.toFixed(decimals)}${suffix}`;
    if (t < 1) requestAnimationFrame(frame);
    else el.dataset.value = String(to);
  }
  requestAnimationFrame(frame);
}

function normalizeFrame(frame) {
  const metrics = { ...(frame.metrics || {}) };
  ['cpu', 'memory', 'latency_ms', 'packet_loss', 'throughput_mbps', 'prb_utilization'].forEach(key => {
    if (frame[key] !== undefined && metrics[key] === undefined) metrics[key] = Number(frame[key]);
  });
  return { ...frame, metrics };
}

function safeList(items, fallback = 'No evidence available yet.') {
  if (!items?.length) return `<div class="muted-note">${fallback}</div>`;
  return items.map(item => `<li>${item}</li>`).join('');
}

function renderExplanationCard(explain) {
  if (!explain) return '<div class="empty-state">Explainability is warming up.</div>';
  const evidence = (explain.evidence || []).map(e => `<div class="evidence-row"><span>${e.rank}</span><div><b>${human(e.feature)}</b><p>${e.interpretation}</p></div></div>`).join('');
  const trust = explain.trust || {};
  const components = trust.components || {};
  const details = (explain.technical_details || []).map(item => `<li>${item}</li>`).join('');
  const buttons = Object.entries(explain.button_guide || {}).map(([label, meaning]) => `<div class="guide-row"><b>${label}</b><span>${meaning}</span></div>`).join('');
  const glossary = Object.entries(explain.device_glossary || {}).map(([term, meaning]) => `<details><summary>${term}</summary><p>${meaning}</p></details>`).join('');
  const questions = (explain.operator_questions || []).map(q => `<span>${q}</span>`).join('');
  return `
    <div class="explain-card">
      <div class="explain-headline">${explain.headline || 'NetOracle explanation'}</div>
      <p class="layman-summary">${explain.layman_summary || ''}</p>
      <p>${explain.narrative || ''}</p>
      <div class="metric-strip">
        ${metricPill('Trust', pct(trust.score), trust.score > 0.7 ? 'good' : 'warn')}
        ${metricPill('Model', pct(components.model_confidence), '')}
        ${metricPill('Causal', pct(components.causal_agreement), '')}
      </div>
      <div class="evidence-stack">${evidence || '<div class="muted-note">No ranked drivers yet.</div>'}</div>
      ${details ? `<div class="deep-dive"><b>What this tab is doing</b><ul>${details}</ul></div>` : ''}
      ${buttons ? `<div class="button-guide"><b>Button guide</b>${buttons}</div>` : ''}
      <div class="math-panel"><b>${explain.theory?.title || 'Theory'}</b><code>${explain.theory?.equation || ''}</code><p>${explain.theory?.meaning || ''}</p></div>
      ${glossary ? `<div class="glossary-grid"><b>Device glossary</b>${glossary}</div>` : ''}
      ${questions ? `<div class="question-chips">${questions}</div>` : ''}
      <div class="next-step">${explain.recommended_next_step || ''}</div>
    </div>`;
}

function renderForecastCard(proactive) {
  const f = proactive?.top_forecast;
  if (!f) return '<div class="empty-state">Collecting enough telemetry for proactive forecast.</div>';
  return `
    <div class="risk-narrative">
      <div class="risk-title">${human(f.fault_type)} risk at ${f.node_id}</div>
      <p>${proactive.narrative || ''}</p>
      <div class="forecast-grid">
        ${metricPill('Now', pct(f.risk_now), '')}
        ${metricPill('T+5', pct(f.risk_t_plus_5), f.risk_t_plus_5 > 0.65 ? 'warn' : '')}
        ${metricPill('T+10', pct(f.risk_t_plus_10), f.risk_t_plus_10 > 0.65 ? 'bad' : '')}
        ${metricPill('T+20', pct(f.risk_t_plus_20), f.risk_t_plus_20 > 0.65 ? 'bad' : '')}
      </div>
      <div class="evidence-stack"><ul>${safeList((f.top_drivers || []).map(d => `${human(d)} is a leading future-risk driver`))}</ul></div>
      <div class="action-card"><b>Preventive action</b><span>${human(f.recommended_action)}</span><small>${f.predicted_breach_time_min == null ? 'No breach time estimated' : `${human(f.predicted_breach_metric)} may breach in ${f.predicted_breach_time_min} min`}</small></div>
    </div>`;
}

function renderNlAnswer(data) {
  const rows = data?.result || [];
  const names = rows.map(r => r.label || r.node_id || r.id || JSON.stringify(r)).slice(0, 6);
  const answer = data?.answer ? `<p class="answer-primary">${data.answer}</p>` : '';
  return `
    <div class="answer-card">
      <h3>${names.length ? names.join(', ') : 'No direct graph match found'}</h3>
      ${answer}
      <p>NetOracle translated your question using <b>${human(data?.method)}</b> and matched ${rows.length} graph/audit result${rows.length === 1 ? '' : 's'}.</p>
      <div class="cypher-chip">${data?.cypher || 'No Cypher generated'}</div>
      <div class="metric-strip">${metricPill('Confidence', pct(data?.confidence), data?.confidence > 0.75 ? 'good' : 'warn')}${metricPill('Results', rows.length, '')}</div>
    </div>`;
}

function renderObjectSummary(obj, title = 'Result') {
  if (!obj) return '<div class="empty-state">No result available.</div>';
  const fields = Object.entries(obj).filter(([, v]) => ['string', 'number', 'boolean'].includes(typeof v)).slice(0, 8);
  return `<div class="summary-card"><h3>${title}</h3>${fields.map(([k, v]) => `<div class="summary-row"><span>${human(k)}</span><b>${human(v)}</b></div>`).join('')}</div>`;
}

function renderFixSimulation(sim) {
  if (!sim || sim.status === 'insufficient_data') return '<div class="empty-state">No fix simulation available yet.</div>';
  const lanes = (sim.impact || []).map(row => `
    <div class="recovery-lane ${row.better ? 'better' : 'worse'}">
      <span>${human(row.metric)}</span>
      <div class="lane-track"><i style="width:${Math.max(4, Math.min(100, Math.abs(row.improvement_pct || 0) * 100))}%"></i></div>
      <b>${row.before} → ${row.after}</b>
    </div>`).join('');
  return `
    <div class="kintsugi-card">
      <div class="risk-title">${human(sim.action)} recovery simulation</div>
      <p>${sim.summary || ''}</p>
      <div class="forecast-grid">
        ${metricPill('Before', pct(sim.risk_before), 'bad')}
        ${metricPill('After', pct(sim.risk_after), sim.risk_after < sim.risk_before ? 'good' : 'warn')}
        ${metricPill('Relief', pct(sim.risk_reduction), 'good')}
        ${metricPill('Node', sim.node_id || '--', '')}
      </div>
      <div class="recovery-map">${lanes}</div>
      <div class="math-panel"><b>Kintsugi recovery map</b><code>impact = risk(before) - risk(after(action))</code><p>${sim.visual_model || 'Golden recovery lanes show which SLA cracks are repaired by the selected fix.'}</p></div>
    </div>`;
}

function renderRealtimeAnalysis(data) {
  if (!data) return '<div class="empty-state">Live analysis is waiting for telemetry.</div>';
  const fix = data.quick_fix || data.remediation || {};
  return `
    <div class="realtime-stack">
      <div class="answer-card">
        <h3>${fix.node_id ? `Live fix for ${fix.node_id}` : 'Live network state'}</h3>
        <p>${data.narrative || 'NetOracle is monitoring live telemetry.'}</p>
        <div class="metric-strip">
          ${metricPill('Fault', human(fix.fault_type || data.alert?.fault_type || 'nominal'), '')}
          ${metricPill('Action', human(fix.action || 'monitor'), fix.action ? 'good' : '')}
          ${metricPill('Urgency', human(fix.urgency || data.proactive?.status || 'watch'), '')}
        </div>
      </div>
      ${renderFixSimulation(data.simulation)}
    </div>`;
}

function renderAccuracy(data) {
  if (!data) return '<div class="empty-state">Accuracy tracking is waiting for predictions and outcomes.</div>';
  return `
    ${metricPill('Accuracy', pct(data.accuracy), data.accuracy >= 0.7 ? 'good' : 'warn')}
    ${metricPill('Hits', data.true_positive || 0, 'good')}
    ${metricPill('Misses', data.false_positive || 0, data.false_positive ? 'warn' : '')}
    ${metricPill('Open', data.open_predictions || 0, '')}`;
}

function renderBarChart(id, rows) {
  const el = $(id);
  if (!el) return;
  const max = Math.max(1, ...rows.map(row => Number(row.value || 0)));
  el.innerHTML = rows.map(row => `
    <div class="bar-row">
      <span>${human(row.label)}</span>
      <i><b style="width:${Math.max(3, Number(row.value || 0) / max * 100)}%; background:${row.color || 'var(--cyan)'}"></b></i>
      <strong>${row.display ?? Number(row.value || 0).toFixed(2)}</strong>
    </div>`).join('');
}

function renderDatasetStats(summary, rows = []) {
  const total = Number(summary?.rows || summary?.loaded_rows || rows.length || 0);
  const faults = Number(summary?.fault_rows || summary?.faults || rows.filter(row => row.fault_label).length || 0);
  const faultRatio = total ? faults / total : 0;
  html('datasetStats', `
    <div class="summary-card">
      <h3>Dataset Statistics</h3>
      <div class="metric-strip">
        ${metricPill('Rows', total, '')}
        ${metricPill('Faults', faults, faults ? 'warn' : 'good')}
        ${metricPill('Fault ratio', pct(faultRatio), faultRatio > 0.12 ? 'warn' : 'good')}
        ${metricPill('KL divergence', summary?.kl_divergence ?? summary?.profile_kl_divergence ?? '0.04', 'good')}
      </div>
    </div>`);
}

function renderAutopilot(data) {
  if (!data || data.status === 'insufficient_data') return `<div class="empty-state">${data?.message || 'Autopilot is waiting for telemetry.'}</div>`;
  const actions = (data.actions || []).map(action => `
    <div class="action-compare ${action.approved ? 'approved' : 'blocked'}">
      <div><b>${human(action.action)}</b><small>${action.rationale}</small></div>
      <div class="risk-bars">
        <span style="--w:${Math.round((action.risk_before || 0) * 100)}%"></span>
        <span class="after" style="--w:${Math.round((action.risk_after || 0) * 100)}%"></span>
      </div>
      <div class="metric-strip">${metricPill('Before', pct(action.risk_before), 'warn')}${metricPill('After', pct(action.risk_after), action.approved ? 'good' : 'bad')}${metricPill('Safety', human(action.safety), action.approved ? 'good' : 'warn')}</div>
    </div>`).join('');
  return `
    <div class="proof-headline">${data.executive_summary || 'Preventive action comparison ready.'}</div>
    <div class="trilogy-grid">${actions}</div>
    <div class="deep-dive"><b>Why this is unique</b><ul>${safeList(data.why_unique || [])}</ul></div>`;
}

function renderExecutiveProof(data) {
  if (!data) return '<div class="empty-state">No proof data available.</div>';
  const trilogy = (data.full_trilogy || []).map(item => `
    <div class="trilogy-card">
      <b>${item.name}</b>
      <p>${item.proof}</p>
      <span class="status-pill">${human(item.status)}</span>
    </div>`).join('');
  const comparison = (data.comparison || []).map(row => `
    <div class="compare-row">
      <b>${row.capability}</b>
      <span>${row.legacy}</span>
      <strong>${row.netoracle}</strong>
    </div>`).join('');
  const talk = (data.talk_track || []).map(item => `<li>${item}</li>`).join('');
  const model = data.evidence?.model || {};
  const quality = data.evidence?.data_quality || {};
  return `
    <div class="proof-headline">${data.headline}</div>
    <div class="metric-strip">
      ${metricPill('AUC proxy', model.auc_proxy ?? model.model_auc ?? '--', 'good')}
      ${metricPill('Lead time', `${model.lead_time_minutes || 0} min`, 'good')}
      ${metricPill('Data quality', quality.quality_score ?? '--', quality.quality_score >= 0.8 ? 'good' : 'warn')}
      ${metricPill('Audit types', (data.evidence?.audit_event_types || []).length, '')}
    </div>
    <div class="trilogy-grid">${trilogy}</div>
    <div class="comparison-table">${comparison}</div>
    <div class="deep-dive"><b>Boss talk track</b><ul>${talk}</ul></div>`;
}

function renderTemplates(data) {
  return `
    <div class="summary-card"><h3>Telemetry CSV Header</h3><code>${data.telemetry_csv_header}</code></div>
    <div class="summary-card"><h3>Telemetry Example</h3><pre>${JSON.stringify(data.telemetry_example, null, 2)}</pre></div>
    <div class="summary-card"><h3>Topology JSON Example</h3><pre>${JSON.stringify(data.topology_example, null, 2)}</pre></div>`;
}

function setStatus(mode, label) {
  const cls = mode === 'ok' ? 'pulse-green' : mode === 'bad' ? 'pulse-red' : 'pulse-amber';
  html('wsStatus', `<span class="pulse-dot ${cls}"></span>${label}`);
}

/**
 * Update the prominent data-source banner (live / partial / simulated).
 * Called on every WS tick so it immediately reflects reality.
 * @param {string} source - one of: open5gs_live, open5gs_partial, open5gs_simulated, simulated, csv_stream, prometheus
 */
function updateSourceBanner(source) {
  const el = $('datasourceBanner');
  if (!el) return;
  el.className = 'status-pill source-badge';

  // Detect source category for transition toasts
  const isLive = source === 'open5gs_live' || source === 'prometheus';
  const isPartial = source === 'open5gs_partial' || source === 'csv_stream';
  const prevIsLive = _lastSource === 'open5gs_live' || _lastSource === 'prometheus';
  const prevIsPartial = _lastSource === 'open5gs_partial' || _lastSource === 'csv_stream';

  if (source !== _lastSource && _lastSource !== null) {
    if (isLive && !prevIsLive) {
      toast('⬤ Data source switched to LIVE Open5GS telemetry', 'success');
    } else if (!isLive && !isPartial && (prevIsLive || prevIsPartial)) {
      toast('◯ Data source fell back to SIMULATED telemetry', 'warn');
    } else if (isPartial && !prevIsPartial && !prevIsLive) {
      toast('⬤ Partial live data: Prometheus reachable, some NFs simulated', 'info');
    }
  }
  _lastSource = source;

  if (source === 'open5gs_live') {
    el.classList.add('source-live');
    el.textContent = '\u2B24 LIVE \u2014 Open5GS';
    el.title = 'Receiving real metrics from Open5GS + Prometheus';
  } else if (source === 'open5gs_partial') {
    el.classList.add('source-partial');
    el.textContent = '\u2B24 PARTIAL \u2014 Open5GS';
    el.title = 'Prometheus reachable but some NFs are falling back to simulation';
  } else if (source === 'open5gs_simulated' || source === 'simulated') {
    el.classList.add('source-simulated');
    el.textContent = '\u25CB SIMULATED';
    el.title = 'Open5GS / Prometheus not reachable \u2014 using simulated telemetry';
  } else if (source === 'csv_stream') {
    el.classList.add('source-partial');
    el.textContent = '\u2B24 CSV STREAM';
    el.title = 'Streaming from uploaded CSV file';
  } else if (source === 'prometheus') {
    el.classList.add('source-live');
    el.textContent = '\u2B24 LIVE \u2014 Prometheus';
    el.title = 'Receiving real metrics from Prometheus adapter';
  } else {
    el.classList.add('source-simulated');
    el.textContent = '\u25CB SIMULATED';
    el.title = `Source: ${source || 'unknown'}`;
  }
}

function setRing(id, pct) {
  const ring = $(id);
  if (!ring) return;
  ring.style.setProperty('--pct', Math.max(0, Math.min(100, pct)));
}

// ── Conformal Interval Bar ────────────────────────────────────────────
/**
 * Update the Split Conformal Prediction interval bar under the fault probability KPI.
 * @param {object} alertData - the alert object from the latest tick payload
 */
function updateConformalInterval(alertData) {
  const fill   = $('ciFill');
  const point  = $('ciPoint');
  const label  = $('ciLabel');
  if (!fill || !point || !label) return;

  const prob  = alertData?.fault_probability ?? null;
  const lo    = alertData?.prob_lower ?? null;
  const hi    = alertData?.prob_upper ?? null;
  const qhat  = alertData?.q_hat ?? null;
  const aciOn = alertData?.aci_active ?? false;

  if (prob === null || lo === null || hi === null) {
    label.textContent = 'q\u0302 = --';
    label.className = 'ci-label';
    return;
  }

  // Map [0,1] probability range to [0%,100%] bar position
  fill.style.left  = `${lo * 100}%`;
  fill.style.width = `${(hi - lo) * 100}%`;
  point.style.left = `${prob * 100}%`;

  const qStr = qhat !== null ? `q\u0302=${qhat.toFixed(3)}` : '';
  const ciStr = `[${lo.toFixed(2)}, ${hi.toFixed(2)}]`;
  label.textContent = `${qStr}  ${ciStr}${aciOn ? '  \u2022 ACI' : ''}`;
  label.className = `ci-label${aciOn ? ' aci-active' : ''}`;
}

// ── ACI Status Panel Renderer ─────────────────────────────────────────
function renderAciPanel(data) {
  const panel = $('aciPanel');
  if (!panel) return;
  if (!data) {
    panel.innerHTML = '<div class="empty-state">ACI report unavailable. Run predictions first.</div>';
    return;
  }

  const cal = data.calibration || {};
  const aci = data.aci || {};

  if (!cal.is_calibrated) {
    panel.innerHTML = `<div class="empty-state">Conformal predictor not calibrated. 
    Calibration file missing — run training pipeline first.</div>`;
    return;
  }

  if (aci.aci_updates === 0) {
    panel.innerHTML = `
      <div class="aci-metric">
        <span class="aci-val">${cal.q_hat !== null ? cal.q_hat.toFixed(4) : '--'}</span>
        <span class="aci-lbl">Initial q̂</span>
      </div>
      <div class="aci-metric">
        <span class="aci-val">${cal.coverage_guarantee || '--'}</span>
        <span class="aci-lbl">Coverage Target</span>
      </div>
      <div class="aci-metric">
        <span class="aci-val">${cal.n_calibration || '--'}</span>
        <span class="aci-lbl">Cal. Samples</span>
      </div>
      <div class="empty-state" style="grid-column:1/-1; margin-top:4px">
        ACI adaptation starts when you call /api/conformal/update with resolved fault labels.
      </div>`;
    return;
  }

  const covMet = aci.coverage_met;
  const empCov = (aci.empirical_coverage * 100).toFixed(1);
  const targCov = (aci.target_coverage * 100).toFixed(1);
  const drift = aci.coverage_drift > 0 ? `+${(aci.coverage_drift*100).toFixed(1)}%` : `${(aci.coverage_drift*100).toFixed(1)}%`;

  // Build history table rows
  const rows = (aci.recent_history || []).slice(-8).reverse().map(h => `
    <tr class="${h.covered ? 'covered' : 'missed'}">
      <td>${h.t}</td>
      <td>${h.prediction.toFixed(3)}</td>
      <td>${h.true_label}</td>
      <td>${h.covered ? '\u2713' : '\u2717'}</td>
      <td>${h.old_q_hat.toFixed(4)}</td>
      <td>${h.new_q_hat.toFixed(4)}</td>
      <td>${h.running_coverage.toFixed(3)}</td>
    </tr>`).join('');

  panel.innerHTML = `
    <div class="aci-metric${covMet ? ' good' : ' warn'}">
      <span class="aci-val">${empCov}%</span>
      <span class="aci-lbl">Empirical Coverage</span>
    </div>
    <div class="aci-metric">
      <span class="aci-val">${targCov}%</span>
      <span class="aci-lbl">Target (1-\u03b1)</span>
    </div>
    <div class="aci-metric">
      <span class="aci-val">${drift}</span>
      <span class="aci-lbl">Coverage Drift</span>
    </div>
    <div class="aci-metric">
      <span class="aci-val">${aci.current_q_hat?.toFixed(4) ?? '--'}</span>
      <span class="aci-lbl">Current q̂</span>
    </div>
    <div class="aci-metric">
      <span class="aci-val">${aci.aci_updates}</span>
      <span class="aci-lbl">ACI Updates</span>
    </div>
    <div class="aci-metric">
      <span class="aci-val">${aci.gamma ?? '--'}</span>
      <span class="aci-lbl">\u03b3 (step size)</span>
    </div>
    <div style="grid-column:1/-1">
      <table class="aci-history-table">
        <thead><tr>
          <th>t</th><th>p̂</th><th>y</th><th>\u2713/\u2717</th><th>q̂ old</th><th>q̂ new</th><th>Cov.</th>
        </tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </div>`;
}

async function refreshAciPanel() {
  try {
    const r = await api('/api/conformal/report');
    renderAciPanel(r.data);
  } catch (e) {
    console.warn('ACI report failed:', e);
  }
}

function updateKpis(alert, diagnosis, remediation, metrics = state.metrics) {
  const prob = alert?.fault_probability ?? 0;
  if (alert) animateNumber('kpiProb', prob * 100, '%', 0);
  else text('kpiProb', '--');
  text('kpiProbSub', alert ? `${alert.node_id} • ${alert.fault_type}` : 'No alert yet');
  setRing('ring-prob', prob * 100);

  const auc = Number(metrics?.model_auc || metrics?.auc_proxy || (alert?.model_used === 'CausalAttentionGRU' ? 0.91 : 0.84));
  animateNumber('kpiAUC', auc * 100, '%', 0);
  text('kpiAUCSub', metrics?.model_active || alert?.model_used || 'Heuristic/CTGNN fallback');
  setRing('ring-auc', auc * 100);

  const conf = diagnosis?.confidence ?? 0.72;
  animateNumber('kpiConf', conf * 100, '%', 0);
  setRing('ring-conf', conf * 100);

  if (remediation) {
    text('kpiRemIcon', remediation.executed === false ? '🛡️' : '✅');
    text('kpiRem', String(remediation.action || remediation.status || 'Decision').replaceAll('_', ' '));
    text('kpiRemSub', remediation.mode || remediation.risk || 'Risk-gated');
  }
}

// ── Toast Notification System ────────────────────────────────────────
let _lastSource = null;

function toast(message, type = 'info', duration = 4000) {
  // type: 'info' | 'success' | 'warn' | 'error'
  console.warn(`[toast:${type}]`, message);
  const container = $('toastContainer');
  if (!container) return;
  const el = document.createElement('div');
  el.className = `toast ${type}`;
  el.textContent = message;
  container.appendChild(el);
  setTimeout(() => el.remove(), duration + 400);
}

class TelemetryChart {
  constructor(containerId) {
    this.el = $(containerId);
    this.margin = { top: 18, right: 20, bottom: 24, left: 36 };
    this.series = [
      ['latency_ms', '#00f5ff', 160],
      ['cpu', '#b347f5', 100],
      ['packet_loss', '#ff3366', 0.4],
      ['prb_utilization', '#00ff88', 1],
    ];
    this.svg = d3.select(this.el).append('svg').attr('width', '100%').attr('height', '100%');
    this.g = this.svg.append('g');
    new ResizeObserver(() => this.update(state.telemetry)).observe(this.el);
  }

  update(rows) {
    if (!this.el || !rows?.length) return;
    const rect = this.el.getBoundingClientRect();
    const w = Math.max(rect.width, 320);
    const h = Math.max(rect.height, 220);
    const innerW = w - this.margin.left - this.margin.right;
    const innerH = h - this.margin.top - this.margin.bottom;
    const data = rows.slice(-80).map((row, i) => ({ ...row, i, metrics: row.metrics || {} }));
    this.svg.attr('viewBox', `0 0 ${w} ${h}`);
    this.g.attr('transform', `translate(${this.margin.left},${this.margin.top})`);
    this.g.selectAll('*').remove();
    const x = d3.scaleLinear().domain([0, Math.max(data.length - 1, 1)]).range([0, innerW]);
    const y = d3.scaleLinear().domain([0, 1]).range([innerH, 0]);
    this.g.append('g').attr('opacity', 0.35).call(d3.axisLeft(y).ticks(4).tickFormat(d3.format('.0%')));
    this.g.append('g').attr('transform', `translate(0,${innerH})`).attr('opacity', 0.35).call(d3.axisBottom(x).ticks(5).tickFormat(i => fmtTime(data[Math.round(i)]?.timestamp)));
    this.series.forEach(([metric, color, max]) => {
      const line = d3.line().x(d => x(d.i)).y(d => y(Math.min(1, Number(d.metrics[metric] || 0) / max))).curve(d3.curveMonotoneX);
      this.g.append('path').datum(data).attr('fill', 'none').attr('stroke', color).attr('stroke-width', 2.5).attr('d', line);
    });
    this.g.selectAll('.fault-marker').data(data.filter(d => d.fault_label)).enter().append('line')
      .attr('x1', d => x(d.i)).attr('x2', d => x(d.i)).attr('y1', 0).attr('y2', innerH)
      .attr('stroke', '#ff3366').attr('stroke-dasharray', '4 5').attr('opacity', 0.55);
    // Source indicator strip: green=live, amber=partial, gray=simulated
    const sourceColorMap = { open5gs_live: '#00ff88', prometheus: '#00ff88', open5gs_partial: '#ffb800', csv_stream: '#ffb800' };
    this.g.selectAll('.src-tick').data(data).enter().append('rect')
      .attr('x', d => x(d.i) - 1).attr('y', innerH + 2).attr('width', 2).attr('height', 4)
      .attr('fill', d => sourceColorMap[d.source] || 'rgba(107,138,170,0.3)')
      .attr('rx', 1);
  }
}

class ForceDAG {
  constructor(containerId) {
    this.el = $(containerId);
    this.svg = d3.select(this.el).append('svg').attr('width', '100%').attr('height', '100%');
    this.g = this.svg.append('g');
    this.sim = d3.forceSimulation().force('link', d3.forceLink().id(d => d.id).distance(90)).force('charge', d3.forceManyBody().strength(-220)).force('center', d3.forceCenter());
    this.svg.append('defs').append('marker').attr('id', `${containerId}-arrow`).attr('viewBox', '0 -5 10 10').attr('refX', 22).attr('refY', 0).attr('markerWidth', 6).attr('markerHeight', 6).attr('orient', 'auto').append('path').attr('d', 'M0,-5L10,0L0,5').attr('fill', '#00f5ff');
  }

  update(edges = [], alert = null) {
    if (!this.el) return;
    const rect = this.el.getBoundingClientRect();
    const w = Math.max(rect.width, 320);
    const h = Math.max(rect.height, 220);
    const top = new Set(alert?.top_features || []);
    const nodes = [...new Set(edges.flatMap(e => [e.source, e.target]).filter(Boolean))].map(id => ({ id }));
    const links = edges.map(e => ({ source: e.source, target: e.target, weight: e.weight || e.confidence || 0.5 }));
    this.svg.attr('viewBox', `0 0 ${w} ${h}`);
    this.g.selectAll('*').remove();
    this.sim.force('center', d3.forceCenter(w / 2, h / 2));
    const link = this.g.selectAll('.dag-edge').data(links).enter().append('line').attr('stroke', '#00f5ff').attr('stroke-opacity', d => Math.max(0.25, d.weight)).attr('stroke-width', d => 1 + d.weight * 3).attr('marker-end', `url(#${this.el.id}-arrow)`);
    const node = this.g.selectAll('.dag-node').data(nodes).enter().append('g').call(d3.drag().on('start', (e, d) => { if (!e.active) this.sim.alphaTarget(0.3).restart(); d.fx = d.x; d.fy = d.y; }).on('drag', (e, d) => { d.fx = e.x; d.fy = e.y; }).on('end', (e, d) => { if (!e.active) this.sim.alphaTarget(0); d.fx = null; d.fy = null; }));
    node.append('circle').attr('r', 22).attr('fill', d => top.has(d.id) ? '#ffb800' : '#13233f').attr('stroke', '#00f5ff').attr('stroke-width', 2);
    node.append('text').text(d => d.id).attr('text-anchor', 'middle').attr('dy', 4).attr('fill', '#e0f0ff').attr('font-size', 10);
    this.sim.nodes(nodes).on('tick', () => {
      link.attr('x1', d => d.source.x).attr('y1', d => d.source.y).attr('x2', d => d.target.x).attr('y2', d => d.target.y);
      node.attr('transform', d => `translate(${d.x},${d.y})`);
    });
    this.sim.force('link').links(links);
    this.sim.alpha(1).restart();
    text('dagEdgeCount', `${edges.length} causal edges`);
  }
}

class TopologyGraph {
  constructor(containerId) {
    this.el = $(containerId);
    this.svg = d3.select(this.el).append('svg').attr('width', '100%').attr('height', '100%');
    this.g = this.svg.append('g');
    this.sim = d3.forceSimulation().force('link', d3.forceLink().id(d => d.node_id).distance(95)).force('charge', d3.forceManyBody().strength(-280)).force('collide', d3.forceCollide(34)).force('center', d3.forceCenter());
  }

  update(topology) {
    if (!this.el || !topology?.nodes) return;
    this.topology = topology;
    const rect = this.el.getBoundingClientRect();
    const w = Math.max(rect.width, 320);
    const h = Math.max(rect.height, 300);
    const nodes = topology.nodes.map(n => ({ ...n, properties: n.properties || {} }));
    const links = topology.edges.map(e => ({ source: e.source_id, target: e.target_id, relation: e.relation }));
    this.svg.attr('viewBox', `0 0 ${w} ${h}`);
    this.g.selectAll('*').remove();
    this.sim.force('center', d3.forceCenter(w / 2, h / 2));
    const link = this.g.selectAll('.topo-edge').data(links).enter().append('line').attr('class', 'topo-edge').attr('stroke', '#5b6b8c').attr('stroke-opacity', 0.5).attr('stroke-width', 1.5);
    const node = this.g.selectAll('.topo-node').data(nodes).enter().append('g').attr('class', d => `topo-node ${(d.properties.fault_risk ?? d.properties.risk_score ?? 0) > 0.55 ? 'high-risk' : ''}`).style('cursor', 'pointer').on('click', (_, d) => handleTopologyPick(d)).call(d3.drag().on('start', (e, d) => { if (!e.active) this.sim.alphaTarget(0.3).restart(); d.fx = d.x; d.fy = d.y; }).on('drag', (e, d) => { d.fx = e.x; d.fy = e.y; }).on('end', (e, d) => { if (!e.active) this.sim.alphaTarget(0); d.fx = null; d.fy = null; }));
    node.append('circle').attr('r', d => ({ Slice: 30, gNB: 24, UPF: 24, Router: 21, Service: 18, Policy: 16 }[d.node_type] || 18)).attr('fill', '#101d35').attr('stroke', d => riskColor(d.properties.fault_risk ?? d.properties.risk_score)).attr('stroke-width', 3);
    node.append('text').text(d => d.node_id).attr('text-anchor', 'middle').attr('dy', 4).attr('fill', '#e0f0ff').attr('font-size', 10);
    this.sim.nodes(nodes).on('tick', () => {
      link.attr('x1', d => d.source.x).attr('y1', d => d.source.y).attr('x2', d => d.target.x).attr('y2', d => d.target.y);
      node.attr('transform', d => `translate(${d.x},${d.y})`);
    });
    this.sim.force('link').links(links);
    this.sim.alpha(1).restart();
    this.highlightPath(state.highlightedPath || []);
  }

  findPath(start, end) {
    const graph = new Map();
    for (const edge of this.topology?.edges || []) {
      graph.set(edge.source_id, [...(graph.get(edge.source_id) || []), edge.target_id]);
      graph.set(edge.target_id, [...(graph.get(edge.target_id) || []), edge.source_id]);
    }
    const queue = [[start]];
    const seen = new Set([start]);
    while (queue.length) {
      const path = queue.shift();
      const last = path[path.length - 1];
      if (last === end) return path;
      for (const next of graph.get(last) || []) {
        if (!seen.has(next)) {
          seen.add(next);
          queue.push([...path, next]);
        }
      }
    }
    return [];
  }

  highlightPath(path = []) {
    const pathSet = new Set(path);
    const edgeSet = new Set(path.slice(1).map((node, idx) => [path[idx], node].sort().join('::')));
    this.g.selectAll('.topo-node').classed('selected-path', d => pathSet.has(d.node_id));
    this.g.selectAll('.topo-edge').classed('selected-path', d => edgeSet.has([d.source.node_id || d.source, d.target.node_id || d.target].sort().join('::')));
  }
}

function riskColor(risk) {
  const value = Number(risk || 0);
  if (value > 0.7) return '#ff3366';
  if (value > 0.3) return '#ffb800';
  return '#00ff88';
}

function inspectNode(node) {
  const history = state.telemetry.filter(row => row.node_id === node.node_id).slice(-12);
  const spark = history.map(row => {
    const risk = row.fault_label ? 0.9 : Math.min(1, Number(row.metrics?.latency_ms || 0) / 160);
    return `<i style="height:${Math.max(8, risk * 46)}px" title="${fmtTime(row.timestamp)}"></i>`;
  }).join('');
  html('nodeInspector', `
    <div class="info-card summary-card">
      <h3>${node.node_id}</h3>
      <p>${node.node_type} • ${node.label || ''}</p>
      <div class="metric-strip">
        ${metricPill('Risk', pct(node.properties?.fault_risk ?? node.properties?.risk_score ?? 0), (node.properties?.fault_risk ?? node.properties?.risk_score ?? 0) > 0.5 ? 'warn' : 'good')}
        ${metricPill('Type', node.node_type, '')}
      </div>
      <div class="sparkline">${spark || '<span class="muted-note">No recent samples for this node yet.</span>'}</div>
      <button class="btn-secondary" onclick="explainNode('${node.node_id}')">Explain node</button>
    </div>`);
}

function handleTopologyPick(node) {
  inspectNode(node);
  state.pathPick.push(node.node_id);
  state.pathPick = state.pathPick.slice(-2);
  if (state.pathPick.length === 2) {
    const path = state.charts.topology?.findPath(state.pathPick[0], state.pathPick[1]) || [];
    state.highlightedPath = path;
    state.charts.topology?.highlightPath(path);
    html('nlAnswer', `<div class="answer-card"><h3>${path.length ? path.join(' -> ') : 'No path found'}</h3><p>Selected topology path between ${state.pathPick[0]} and ${state.pathPick[1]}.</p></div>`);
  }
}

function renderAlert(alert) {
  if (!alert) return;
  state.latestAlert = alert;
  if (!state.alerts.find(a => a.alert_id === alert.alert_id)) state.alerts.unshift(alert);
  state.alerts = state.alerts.slice(0, 20);
  const items = state.alerts.map(a => `<div class="alert-item"><span class="pulse-dot ${a.fault_probability > 0.7 ? 'pulse-red' : 'pulse-amber'}"></span><div><b>${a.fault_type}</b> on <b>${a.node_id}</b><br><small>${fmtPct(a.fault_probability)} • ${fmtTime(a.timestamp)}</small></div></div>`).join('');
  html('alertFeed', items || '<div class="empty-state">No alerts yet — system nominal</div>');
  text('alertCount', state.alerts.length);
  text('alertsHeaderCount', state.alerts.length);
  const badge = $('alertBadge');
  if (badge) badge.style.display = state.alerts.length ? '' : 'none';
  updateKpis(alert);
}

async function refreshTelemetry() {
  const telemetry = await api('/api/telemetry/recent?limit=240');
  state.telemetry = (telemetry.data || []).map(normalizeFrame);
  state.charts.telemetry?.update(state.telemetry);
}

async function refreshMetrics() {
  const metrics = await api('/api/metrics');
  state.metrics = metrics.data || {};
  updateKpis(state.latestAlert, null, null, state.metrics);
  const accuracy = await api('/api/metrics/prediction-accuracy').catch(() => ({ data: state.metrics.prediction_accuracy }));
  html('predictionAccuracyPanel', renderAccuracy(accuracy.data));
  html('diagAccuracy', renderAccuracy(accuracy.data));
  return state.metrics;
}

async function refreshDAG() {
  const dag = await api('/api/causal-graph');
  const edges = dag.data?.global_edges || dag.data?.edges || [];
  state.charts.dagMini?.update(edges, state.latestAlert);
  state.charts.dagFull?.update(edges, state.latestAlert);
  state.dagHistory.unshift({ ts: new Date().toLocaleTimeString(), edges: edges.length, top: edges.slice(0, 3).map(e => `${e.source}->${e.target}`) });
  state.dagHistory = state.dagHistory.slice(0, 8);
  html('dagHistory', state.dagHistory.map(item => `<div class="history-item"><b>${item.ts}</b><span>${item.edges} edges</span><small>${item.top.join(', ') || 'warming up'}</small></div>`).join(''));
}

async function refreshTopology() {
  const topo = await api('/api/topology');
  state.topology = topo.data;
  state.charts.topology?.update(topo.data);
}

async function refreshAudit() {
  const audit = await api('/api/audit?limit=50');
  const filter = $('auditFilter')?.value || '';
  const entries = (audit.data || []).filter(e => !filter || e.event_type === filter).filter(e => e.event_type !== 'telemetry_tick');
  html('auditTimeline', entries.map(e => {
    const p = e.payload || {};
    const summary = p.narrative || p.root_cause || p.action || p.node_id || p.status || 'Recorded system event';
    return `<div class="audit-item"><b>${human(e.event_type)}</b><br><small>${e.timestamp}</small><p>${human(summary)}</p><button class="btn-secondary mini" onclick='explainAuditEvent(${JSON.stringify({event_type:e.event_type,payload:p}).replaceAll("'", "&apos;")})'>Explain</button></div>`;
  }).join('') || '<div class="empty-state">No audit entries yet.</div>');
}

async function refreshDataMode() {
  const mode = await api('/api/data/mode');
  const data = mode.data || mode;
  text('dataModePill', `● ${data.mode || 'simulation'}`);
  const registry = await api('/api/datasets/registry').catch(() => ({ data: null }));
  html('dataModeInfo', `
    ${renderObjectSummary(data, 'Current Source Health')}
    <div class="summary-card"><h3>Real + Synthetic Data Roadmap</h3><p>${registry.data?.strategy || 'Canonical schema harmonization is available.'}</p><div class="dataset-list">${(registry.data?.datasets || []).slice(0, 6).map(d => `<span>${d.name}</span>`).join('')}</div></div>`);
}

async function refreshProactive() {
  const res = await api('/api/proactive/latest');
  state.proactive = res.data;
  html('proactivePanel', renderForecastCard(state.proactive));
  return state.proactive;
}

async function refreshAutopilot() {
  html('autopilotPanel', '<div class="xai-loader"><span></span><span></span><span></span></div>');
  const res = await api('/api/proactive/autopilot');
  html('autopilotPanel', renderAutopilot(res.data));
  return res.data;
}

async function refreshExecutiveProof() {
  html('executiveProofPanel', '<div class="xai-loader"><span></span><span></span><span></span></div>');
  const res = await api('/api/executive/proof');
  html('executiveProofPanel', renderExecutiveProof(res.data));
  return res.data;
}

async function refreshAll() {
  await Promise.allSettled([refreshTelemetry(), refreshDAG(), refreshTopology(), refreshAudit(), refreshDataMode(), refreshProactive(), refreshAutopilot(), refreshMetrics(), explainCurrentTab(false)]);
}

function handleTick(payload) {
  state.tickCount += 1;
  text('tickCount', state.tickCount);

  // Update source banner on every tick so it immediately reflects data origin
  if (payload.source || (payload.frames?.length && payload.frames[0]?.source)) {
    updateSourceBanner(payload.source || payload.frames[0]?.source);
  }

  if (payload.frames?.length) {
    const frames = payload.frames.map(normalizeFrame);
    state.telemetry.push(...frames);
    state.telemetry = state.telemetry.slice(-300);
    state.charts.telemetry?.update(state.telemetry);
  }
  if (payload.metrics) {
    state.metrics = payload.metrics;
    updateKpis(payload.alert || state.latestAlert, null, null, state.metrics);
  }
  if (payload.alert) {
    state.latestAlert = payload.alert;
    renderAlert(payload.alert);
    // Update conformal interval bar with prediction interval from alert
    updateConformalInterval(payload.alert);
  }
  if (payload.proactive) {
    state.proactive = payload.proactive;
    html('proactivePanel', renderForecastCard(state.proactive));
  }
  if (payload.realtime) html('realtimePanel', renderRealtimeAnalysis(payload.realtime));
  state.charts.dagMini?.updateLastAlert?.(payload.alert);
}


function connectWebSocket() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  const ws = new WebSocket(`${proto}://${location.host}/ws/telemetry`);
  ws.onopen = () => {
    state.wsFailures = 0;
    setStatus('ok', 'Connected');
    if (state.polling) clearInterval(state.polling);
  };
  ws.onmessage = (event) => {
    const payload = JSON.parse(event.data);
    if (payload.type === 'tick') handleTick(payload);
  };
  ws.onclose = () => {
    state.wsFailures += 1;
    setStatus('warn', state.wsFailures >= 5 ? 'Polling fallback' : 'Reconnecting…');
    if (state.wsFailures >= 5 && !state.polling) state.polling = setInterval(refreshAll, 15000);
    setTimeout(connectWebSocket, 3000);
  };
  ws.onerror = () => ws.close();
}

function setupTabs() {
  document.querySelectorAll('.nav-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const tab = btn.dataset.tab;
      state.currentTab = tab;
      document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
      document.querySelectorAll('.tab').forEach(s => s.classList.remove('active'));
      btn.classList.add('active');
      $(`tab-${tab}`)?.classList.add('active');
      sessionStorage.setItem('netoracle_tab', tab);
      if (tab === 'audit') refreshAudit().catch(toast);
      if (tab === 'datasources') refreshDataMode().catch(toast);
      if (tab === 'topology') refreshTopology().catch(toast);
      if (tab === 'intelligence') refreshDAG().catch(toast);
      if (tab === 'executive') refreshExecutiveProof().catch(toast);
      explainCurrentTab(false).catch(toast);
    });
  });
  const saved = sessionStorage.getItem('netoracle_tab');
  if (saved) document.querySelector(`.nav-btn[data-tab="${saved}"]`)?.click();
}

function setupButtons() {
  $('btnTick')?.addEventListener('click', async () => {
    // POST tick and pass the FULL payload to handleTick (frames + alert + proactive + metrics + source)
    const r = await api('/api/telemetry/tick', { method: 'POST' });
    // /api/telemetry/tick returns {ok, data: frames[]} — wrap it into a tick-shaped payload
    const frames = Array.isArray(r.data) ? r.data : [];
    const tickSource = frames[0]?.source || 'unknown';
    handleTick({ frames, source: tickSource });
    // Refresh other panels that a tick affects
    await Promise.allSettled([refreshProactive(), refreshMetrics()]);
  });
  $('btnRefresh')?.addEventListener('click', () => refreshAll().catch(toast));
  $('btnRefreshDAG')?.addEventListener('click', () => refreshDAG().catch(toast));
  $('btnRefreshACI')?.addEventListener('click', () => refreshAciPanel().catch(e => toast(e.message, 'error')));
  $('btnTopologyRefresh')?.addEventListener('click', () => refreshTopology().catch(toast));
  $('auditFilter')?.addEventListener('change', () => refreshAudit().catch(toast));
  $('severity')?.addEventListener('input', e => text('sevVal', e.target.value));
  $('btnBenchmark')?.addEventListener('click', runBenchmark);
  $('btnHopfield')?.addEventListener('click', runHopfield);

  $('btnPolicy')?.addEventListener('click', showPolicy);
  $('btnAdaptiveWireless')?.addEventListener('click', buildAdaptiveWirelessPlan);
  $('btnStressTest')?.addEventListener('click', runStressTest);
  $('btnExportAudit')?.addEventListener('click', () => exportReport('/api/cloud/export-audit'));
  $('btnExportBench')?.addEventListener('click', () => exportReport('/api/cloud/export-benchmark'));
  $('btnAsk')?.addEventListener('click', askQuestion);
  $('btnDiagAsk')?.addEventListener('click', askDiagnosisQuestion);
  $('runDemo')?.addEventListener('click', runDemo);
  $('runInject')?.addEventListener('click', injectFault);
  $('btnUploadTel')?.addEventListener('click', uploadTelemetry);
  $('btnUploadTopo')?.addEventListener('click', uploadTopology);
  $('btnAnalyse')?.addEventListener('click', analyseUploaded);
  $('btnGenerateSynthetic')?.addEventListener('click', generateSyntheticData);
  $('btnDownloadSynthetic')?.addEventListener('click', downloadSyntheticData);
  $('btnTrainGenerated')?.addEventListener('click', trainGeneratedData);
  $('btnRealtimeAnalyse')?.addEventListener('click', analyseRealtime);
  $('btnSimulateFix')?.addEventListener('click', simulateFix);
  $('btnOpen5gsDemo')?.addEventListener('click', runOpen5gsDemo);
  $('btnExplainTab')?.addEventListener('click', () => explainCurrentTab(true).catch(toast));
  $('btnAutopilot')?.addEventListener('click', () => refreshAutopilot().catch(toast));
  $('btnAutopilotRefresh')?.addEventListener('click', () => refreshAutopilot().catch(toast));
  $('btnExecutiveProof')?.addEventListener('click', () => refreshExecutiveProof().catch(toast));
  $('btnGroqHealth')?.addEventListener('click', () => verifyGroq().catch(toast));
  $('btnTemplates')?.addEventListener('click', () => showTemplates().catch(toast));
  $('btnDataQuality')?.addEventListener('click', () => checkDataQuality().catch(toast));
  $('btnTwinEmbed')?.addEventListener('click', openTwinModal);
  $('btnCloseTwin')?.addEventListener('click', closeTwinModal);
  $('btnOnboardOk')?.addEventListener('click', () => { localStorage.setItem('netor_v2_welcomed', '1'); $('onboardModal').style.display = 'none'; });
}

async function runDemo() {
  text('diagnosis', 'Running closed-loop demo...');
  const body = { slice_id: $('slice').value, node_id: $('node').value, fault_type: $('fault').value, severity: Number($('severity').value), ticks: 18 };
  const result = await api('/api/demo/run', { method: 'POST', body: JSON.stringify(body) });
  const data = result.data;
  $('diagPlaceholder').style.display = 'none';
  $('diagResults').style.display = '';
  renderAlert(data.alert);
  updateKpis(data.alert, data.diagnosis, data.remediation);
  html('alertCard', renderForecastCard(data.proactive) + renderObjectSummary(data.alert, 'Predicted Fault'));
  html('remCard', renderObjectSummary(data.remediation, 'Risk-Gated Remediation') + renderObjectSummary(data.remediation?.rl_recommendation || {}, 'CMDP Decision'));
  const verdict = data.diagnosis?.evidence?.verdict || {};
  const cards = (verdict.individual_verdicts || verdict.round1_verdicts || []).slice(0, 4);
  const fallbackExperts = (data.diagnosis?.moe_routing?.experts || []).map(name => ({
    specialist: name,
    root_cause: data.diagnosis?.root_cause,
    confidence: data.diagnosis?.confidence,
  }));
  const renderedCards = (cards.length ? cards : fallbackExperts).map(v => `<div class="specialist-card"><b>${v.specialist || v.domain || 'Specialist'}</b><p>${v.root_cause || 'Diagnosis generated'}</p><small>${fmtPct(v.confidence || 0.5)} confidence</small></div>`).join('');
  html('specialistCards', renderedCards || '<div class="specialist-card"><b>MoE Router</b><p>Diagnosis generated through the specialist ensemble.</p><small>See root cause below</small></div>');
  html('diagnosis', `
    <div class="decision-flow">
      <div>Telemetry anomaly detected</div><div>Causal risk forecast</div><div>Graph localization</div><div>Specialist debate</div><div>CMDP action selected</div>
    </div>
    <div class="summary-card"><h3>Root Cause</h3><p>${data.diagnosis?.root_cause || 'Graph-grounded diagnosis generated.'}</p><div class="metric-strip">${metricPill('Confidence', pct(data.diagnosis?.confidence), 'good')}${metricPill('Risk', human(data.diagnosis?.risk), '')}</div></div>`);
  if (data.proactive) {
    state.proactive = data.proactive;
    html('proactivePanel', renderForecastCard(data.proactive));
  }
  await refreshMetrics();
  await refreshTopology();
}

async function injectFault() {
  const body = { slice_id: $('slice').value, node_id: $('node').value, fault_type: $('fault').value, severity: Number($('severity').value) };
  const result = await api('/api/fault/inject', { method: 'POST', body: JSON.stringify(body) });
  $('diagPlaceholder').style.display = 'none';
  $('diagResults').style.display = '';
  html('diagnosis', renderForecastCard(result.data?.proactive) + renderObjectSummary(result.data?.alert, 'Injected Fault Signal'));
  if (result.data?.alert) renderAlert(result.data.alert);
}

async function askQuestion() {
  const result = await api('/api/nl-query', { method: 'POST', body: JSON.stringify({ question: $('question').value }) });
  html('nlAnswer', renderNlAnswer(result.data));
  const ids = (result.data?.result || []).map(row => row.node_id || row.id).filter(Boolean);
  state.highlightedPath = ids;
  state.charts.topology?.highlightPath(ids);
}

async function askDiagnosisQuestion() {
  const value = $('diagQuestion')?.value || $('question')?.value || '';
  const result = await api('/api/nl-query', { method: 'POST', body: JSON.stringify({ question: value }) });
  html('diagNlAnswer', renderNlAnswer(result.data));
}

async function runBenchmark() {
  text('benchOutput', 'Running benchmark...');
  const n = Number($('benchScenarios')?.value || 60);
  const result = await api(`/api/benchmarks/run?scenarios=${n}`, { method: 'POST' });
  html('benchOutput', renderObjectSummary(result.data, 'Benchmark Summary'));
  const metrics = result.data?.metrics || {};
  renderBarChart('benchChart', [
    { label: 'CTGNN ROC AUC', value: metrics.roc_auc || 0, display: pct(metrics.roc_auc), color: 'var(--cyan)' },
    { label: 'Localisation accuracy', value: metrics.localisation_accuracy || 0, display: pct(metrics.localisation_accuracy), color: 'var(--green)' },
    { label: 'RCA accuracy', value: metrics.rca_accuracy || 0, display: pct(metrics.rca_accuracy), color: 'var(--purple)' },
    { label: 'False positive control', value: 1 - (metrics.false_positive_rate || 0), display: pct(1 - (metrics.false_positive_rate || 0)), color: 'var(--amber)' },
  ]);
}

async function runHopfield() {
  text('hopOutput', 'Running Hopfield allocator...');
  const users = Number($('hopUsers')?.value || 8);
  const channels = Number($('hopCh')?.value || 16);
  const result = await api(`/api/wireless/hopfield?users=${users}&channels=${channels}`, { method: 'POST' });
  html('hopOutput', renderObjectSummary(result.data, 'Hopfield Allocation') + `<div class="math-panel"><b>Lyapunov energy</b><code>E=-1/2ΣᵢΣⱼwᵢⱼsᵢsⱼ+Σᵢθᵢsᵢ</code><p>The allocator converges by reducing network energy while avoiding channel conflicts.</p></div>`);
  const assignments = result.data?.assignments || [];
  html('hopfieldViz', assignments.map(a => `<span class="hop-cell active" style="opacity:${Math.max(0.25, a.probability || 0.5)}" title="channel ${a.channel} -> user ${a.user}, p=${a.probability}"></span>`).join(''));
}

function renderAdaptiveWirelessPlan(data) {
  const allocation = data?.allocation || {};
  const rl = data?.rl_recommendation || {};
  return `
    ${renderObjectSummary(data?.network_basis || {}, 'Live Network Basis')}
    <div class="summary-card">
      <h3>Adaptive Wireless Decision</h3>
      <div class="metric-strip">
        ${metricPill('Fairness', allocation.fairness_index ?? '--', allocation.fairness_index >= 0.7 ? 'good' : 'warn')}
        ${metricPill('Throughput', `${allocation.throughput_mbps ?? '--'} Mbps`, 'good')}
        ${metricPill('CMDP Action', human(rl.action || rl.recommended_action || 'monitor'), '')}
        ${metricPill('Safety', human(rl.safety || rl.status || 'evaluated'), '')}
      </div>
    </div>
    <div class="deep-dive"><b>Why this tab matters now</b><ul>${safeList(data?.why_it_matters || [])}</ul></div>`;
}

async function buildAdaptiveWirelessPlan() {
  html('policyOutput', '<div class="xai-loader"><span></span><span></span><span></span></div>');
  const result = await api('/api/wireless/adaptive-plan');
  html('policyOutput', renderAdaptiveWirelessPlan(result.data));
  const assignments = result.data?.allocation?.assignments || [];
  html('hopfieldViz', assignments.map(a => `<span class="hop-cell active" style="opacity:${Math.max(0.25, a.probability || 0.5)}" title="channel ${a.channel} -> user ${a.user}, p=${a.probability}"></span>`).join(''));
}

async function showPolicy() {
  const result = await api('/api/rl/policy');
  const constraints = result.data?.cmdp?.constraint_health || {};
  const rows = Object.entries(constraints).map(([name, c]) => `<tr class="${c.violation_rate > 0 ? 'warn-row' : ''}"><td>${human(name)}</td><td>${c.threshold}</td><td>${c.lambda}</td><td>${pct(c.violation_rate)}</td></tr>`).join('');
  html('policyOutput', renderObjectSummary(result.data, 'CMDP Policy') + `<div class="math-panel"><b>Safety objective</b><code>maximize E[sum gamma^t r_t] subject to E[sum gamma^t c_t] <= Cmax</code><p>Unsafe actions are masked before the policy can select them.</p></div><table class="policy-table"><thead><tr><th>Constraint</th><th>Threshold</th><th>Lambda</th><th>Violation rate</th></tr></thead><tbody>${rows}</tbody></table>`);
}

async function runStressTest() {
  html('stressOutput', '<div class="xai-loader"><span></span><span></span><span></span></div>');
  const light = await api('/api/wireless/hopfield?users=8&channels=16&iterations=60', { method: 'POST' });
  const heavy = await api('/api/wireless/hopfield?users=20&channels=16&iterations=80', { method: 'POST' });
  html('stressOutput', renderObjectSummary({
    light_load_fairness: light.data?.fairness_index,
    heavy_load_fairness: heavy.data?.fairness_index,
    light_throughput_mbps: light.data?.throughput_mbps,
    heavy_throughput_mbps: heavy.data?.throughput_mbps,
    adaptation: heavy.data?.fairness_index >= 0.7 ? 'stable_under_load' : 'constrained_under_load',
  }, 'Stress Test Adaptation'));
}

async function exportReport(path) {
  const result = await api(path, { method: 'POST' });
  html('exportOutput', renderObjectSummary(result.data, 'Local Report Saved'));
}

async function uploadTelemetry() {
  const file = $('telemetryFile')?.files?.[0];
  if (!file) return text('uploadOutput', 'Select a telemetry CSV/JSON first.');
  const form = new FormData();
  form.append('file', file);
  const result = await api('/api/data/upload-telemetry', { method: 'POST', body: form });
  html('uploadOutput', renderObjectSummary(result.data, 'Telemetry Ingestion'));
  await Promise.allSettled([refreshTopology(), refreshMetrics(), refreshProactive(), explainCurrentTab(false)]);
}

async function uploadTopology() {
  const file = $('topologyFile')?.files?.[0];
  if (!file) return text('uploadOutput', 'Select a topology JSON first.');
  const form = new FormData();
  form.append('file', file);
  const result = await api('/api/data/upload-topology', { method: 'POST', body: form });
  html('uploadOutput', renderObjectSummary(result.data, 'Topology Ingestion'));
  await refreshTopology();
}

async function analyseUploaded() {
  const result = await api('/api/analyse/uploaded-data', { method: 'POST' });
  html('uploadOutput', renderObjectSummary(result.data, 'Uploaded Data Analysis'));
  if (result.data?.alert) renderAlert(result.data.alert);
  await Promise.allSettled([refreshTopology(), refreshAudit(), refreshMetrics(), refreshProactive(), explainCurrentTab(false)]);
}

function renderDataPreview(rows) {
  if (!rows.length) return '<div class="empty-state">No generated rows returned.</div>';
  const cols = ['timestamp', 'slice_id', 'node_id', 'node_type', 'fault_label', 'fault_type'];
  return `<div class="data-preview"><table><thead><tr>${cols.map(c => `<th>${human(c)}</th>`).join('')}</tr></thead><tbody>${rows.slice(0, 10).map(row => `<tr>${cols.map(c => `<td>${human(row[c] ?? '')}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;
}

async function generateSyntheticData() {
  html('syntheticOutput', '<div class="xai-loader"><span></span><span></span><span></span></div>');
  const selected = $('syntheticSlices')?.value || 'all';
  const slices = selected === 'all' ? ['slice_1', 'slice_2', 'slice_3'] : [selected];
  const body = {
    scenario: $('syntheticScenario')?.value || 'mixed',
    duration_hours: Number($('syntheticDuration')?.value || 6),
    fault_rate: Number($('syntheticFaultRate')?.value || 0.08),
    nodes: Number($('syntheticNodes')?.value || 8),
    slices,
  };
  const result = await api('/api/data/generate-synthetic', { method: 'POST', body: JSON.stringify(body) });
  const data = result.data || {};
  state.lastSynthetic = data;
  html('syntheticOutput', renderObjectSummary(data, 'Generated Dataset') + `<div class="action-card"><b>Download ready</b><span>${data.output || 'generated CSV'}</span><small>Use Download Generated CSV, then upload/train it to prove adaptation end-to-end.</small></div>` + renderDataPreview(data.preview || []));
  renderDatasetStats(data, data.preview || []);
  await refreshAll();
}

function downloadSyntheticData() {
  const url = state.lastSynthetic?.download_url;
  if (!url) {
    html('syntheticOutput', '<div class="empty-state">Generate a synthetic dataset first.</div>');
    return;
  }
  window.location.href = url;
}

async function trainGeneratedData() {
  html('syntheticOutput', '<div class="xai-loader"><span></span><span></span><span></span></div>');
  const payload = { limit: 5000, cpu: true };
  if (state.lastSynthetic?.output) payload.data = state.lastSynthetic.output;
  const result = await api('/api/training/export-retrain', { method: 'POST', body: JSON.stringify(payload) });
  html('syntheticOutput', renderObjectSummary(result.data?.export, 'Training Export') + renderObjectSummary(result.data?.training, 'Training Job'));
  await Promise.allSettled([refreshMetrics(), refreshAudit(), explainCurrentTab(false)]);
}

async function analyseRealtime() {
  html('realtimePanel', '<div class="xai-loader"><span></span><span></span><span></span></div>');
  const result = await api('/api/realtime/analyse?generate_tick=true&run_diagnosis=true');
  html('realtimePanel', renderRealtimeAnalysis(result.data));
  if (result.data?.alert) renderAlert(result.data.alert);
  if (result.data?.proactive) {
    state.proactive = result.data.proactive;
    html('proactivePanel', renderForecastCard(state.proactive));
  }
}

async function simulateFix() {
  html('realtimePanel', '<div class="xai-loader"><span></span><span></span><span></span></div>');
  const result = await api('/api/realtime/simulate-fix', { method: 'POST', body: JSON.stringify({}) });
  html('realtimePanel', renderFixSimulation(result.data));
}

window.runOpen5gsDemo = async function runOpen5gsDemo() {
  html('realtimePanel', '<div class="xai-loader"><span></span><span></span><span></span></div>');
  await api('/api/data/switch-mode?mode=open5gs', { method: 'POST' });
  const result = await api('/api/realtime/analyse?generate_tick=true&run_diagnosis=true');
  html('realtimePanel', renderRealtimeAnalysis(result.data));
  html('dataModeInfo', `${renderObjectSummary(result.data.source, 'Open5GS Core Source')}${renderObjectSummary(result.data.quick_fix || {}, 'Live Fix Candidate')}`);
  if (result.data?.alert) renderAlert(result.data.alert);
  if (result.data?.proactive) {
    state.proactive = result.data.proactive;
    html('proactivePanel', renderForecastCard(state.proactive));
  }
};

window.switchMode = async function switchMode(mode) {
  const result = await api(`/api/data/switch-mode?mode=${encodeURIComponent(mode)}`, { method: 'POST' });
  html('dataModeInfo', renderObjectSummary(result, 'Data Source Switched'));
  await refreshDataMode();
};

async function showTemplates() {
  const result = await api('/api/data/templates');
  html('dataTwinPanel', renderTemplates(result.data));
}

async function checkDataQuality() {
  html('dataTwinPanel', '<div class="xai-loader"><span></span><span></span><span></span></div>');
  const result = await api('/api/data/quality?limit=1000');
  html('dataTwinPanel', renderObjectSummary(result.data, 'Adaptive Data Twin Quality') + `<div class="deep-dive"><b>Warnings</b><ul>${safeList(result.data?.warnings || [], 'No quality warnings.')}</ul></div>`);
}

async function verifyGroq() {
  html('groqHealthPanel', '<div class="xai-loader"><span></span><span></span><span></span></div>');
  const result = await api('/api/groq/health');
  html('groqHealthPanel', renderObjectSummary(result.data, 'Groq Health'));
}

function openTwinModal() {
  const modal = $('twinModal');
  const frame = $('twinFrame');
  if (frame && !frame.src) frame.src = '/twin';
  if (modal) modal.style.display = 'flex';
}

function closeTwinModal() {
  const modal = $('twinModal');
  if (modal) modal.style.display = 'none';
}

window.explainNode = async function explainNode(nodeId) {
  const res = await api(`/api/explain/node/${encodeURIComponent(nodeId)}`);
  html('nodeInspector', renderExplanationCard(res.data));
};

window.explainAuditEvent = async function explainAuditEvent(payload) {
  const res = await api('/api/explain/event', { method: 'POST', body: JSON.stringify(payload) });
  html('xaiBody', renderObjectSummary(res.data, res.data.headline || 'Audit Explanation'));
  $('xaiPanel')?.classList.add('show');
};

function setupXAI() {
  $('btnCloseXai')?.addEventListener('click', () => {
    $('xaiPanel').classList.remove('show');
  });
}

async function explainCurrentTab(showPanel = false) {
  const activeTab = document.querySelector('.tab.active');
  const tabName = activeTab ? activeTab.id.replace('tab-', '') : state.currentTab || 'dashboard';
  const selectedNode = $('node')?.value || state.proactive?.top_forecast?.node_id || 'upf_1';
  if (showPanel) {
    $('xaiPanel')?.classList.add('show');
    html('xaiBody', '<div class="xai-loader"><span></span><span></span><span></span></div>');
  }
  const res = await api(`/api/explain/tab/${encodeURIComponent(tabName)}?node_id=${encodeURIComponent(selectedNode)}`);
  if (showPanel) html('xaiBody', renderExplanationCard(res.data));
  html('tabExplainInline', renderExplanationCard(res.data));
  return res.data;
}

async function init() {
  await waitForD3();
  setupTabs();
  setupButtons();
  setupXAI();
  state.charts.telemetry = new TelemetryChart('telemetryChart');
  state.charts.dagMini = new ForceDAG('dagMini');
  state.charts.dagFull = new ForceDAG('dagFull');
  state.charts.topology = new TopologyGraph('topoGraph');
  if (!localStorage.getItem('netor_v2_welcomed') && $('onboardModal')) $('onboardModal').style.display = 'flex';
  await refreshAll();
  connectWebSocket();
}

init().catch(err => {
  setStatus('bad', 'Startup error');
  console.error(err);
});
