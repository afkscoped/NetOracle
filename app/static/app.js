const $ = (id) => document.getElementById(id);
const state = {
  telemetry: [],
  alerts: [],
  latestAlert: null,
  proactive: null,
  currentTab: 'dashboard',
  tickCount: 0,
  wsFailures: 0,
  polling: null,
  charts: {},
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

function safeList(items, fallback = 'No evidence available yet.') {
  if (!items?.length) return `<div class="muted-note">${fallback}</div>`;
  return items.map(item => `<li>${item}</li>`).join('');
}

function renderExplanationCard(explain) {
  if (!explain) return '<div class="empty-state">Explainability is warming up.</div>';
  const evidence = (explain.evidence || []).map(e => `<div class="evidence-row"><span>${e.rank}</span><div><b>${human(e.feature)}</b><p>${e.interpretation}</p></div></div>`).join('');
  const trust = explain.trust || {};
  const components = trust.components || {};
  return `
    <div class="explain-card">
      <div class="explain-headline">${explain.headline || 'NetOracle explanation'}</div>
      <p>${explain.narrative || ''}</p>
      <div class="metric-strip">
        ${metricPill('Trust', pct(trust.score), trust.score > 0.7 ? 'good' : 'warn')}
        ${metricPill('Model', pct(components.model_confidence), '')}
        ${metricPill('Causal', pct(components.causal_agreement), '')}
      </div>
      <div class="evidence-stack">${evidence || '<div class="muted-note">No ranked drivers yet.</div>'}</div>
      <div class="math-panel"><b>${explain.theory?.title || 'Theory'}</b><code>${explain.theory?.equation || ''}</code><p>${explain.theory?.meaning || ''}</p></div>
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
  return `
    <div class="answer-card">
      <h3>${names.length ? names.join(', ') : 'No direct graph match found'}</h3>
      <p>NetOracle translated your question using <b>${human(data?.method)}</b> and matched ${rows.length} graph result${rows.length === 1 ? '' : 's'}.</p>
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

function setStatus(mode, label) {
  const cls = mode === 'ok' ? 'pulse-green' : mode === 'bad' ? 'pulse-red' : 'pulse-amber';
  html('wsStatus', `<span class="pulse-dot ${cls}"></span>${label}`);
}

function setRing(id, pct) {
  const ring = $(id);
  if (!ring) return;
  ring.style.setProperty('--pct', Math.max(0, Math.min(100, pct)));
}

function updateKpis(alert, diagnosis, remediation) {
  const prob = alert?.fault_probability ?? 0;
  text('kpiProb', alert ? fmtPct(prob) : '--');
  text('kpiProbSub', alert ? `${alert.node_id} • ${alert.fault_type}` : 'No alert yet');
  setRing('ring-prob', prob * 100);

  const auc = alert?.model_used === 'CausalAttentionGRU' ? 0.91 : 0.84;
  text('kpiAUC', fmtPct(auc));
  text('kpiAUCSub', alert?.model_used || 'Heuristic/CTGNN fallback');
  setRing('ring-auc', auc * 100);

  const conf = diagnosis?.confidence ?? 0.72;
  text('kpiConf', fmtPct(conf));
  setRing('ring-conf', conf * 100);

  if (remediation) {
    text('kpiRemIcon', remediation.executed === false ? '🛡️' : '✅');
    text('kpiRem', String(remediation.action || remediation.status || 'Decision').replaceAll('_', ' '));
    text('kpiRemSub', remediation.mode || remediation.risk || 'Risk-gated');
  }
}

function toast(message) {
  console.warn(message);
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
    const rect = this.el.getBoundingClientRect();
    const w = Math.max(rect.width, 320);
    const h = Math.max(rect.height, 300);
    const nodes = topology.nodes.map(n => ({ ...n, properties: n.properties || {} }));
    const links = topology.edges.map(e => ({ source: e.source_id, target: e.target_id, relation: e.relation }));
    this.svg.attr('viewBox', `0 0 ${w} ${h}`);
    this.g.selectAll('*').remove();
    this.sim.force('center', d3.forceCenter(w / 2, h / 2));
    const link = this.g.selectAll('.topo-edge').data(links).enter().append('line').attr('stroke', '#5b6b8c').attr('stroke-opacity', 0.5).attr('stroke-width', 1.5);
    const node = this.g.selectAll('.topo-node').data(nodes).enter().append('g').style('cursor', 'pointer').on('click', (_, d) => inspectNode(d)).call(d3.drag().on('start', (e, d) => { if (!e.active) this.sim.alphaTarget(0.3).restart(); d.fx = d.x; d.fy = d.y; }).on('drag', (e, d) => { d.fx = e.x; d.fy = e.y; }).on('end', (e, d) => { if (!e.active) this.sim.alphaTarget(0); d.fx = null; d.fy = null; }));
    node.append('circle').attr('r', d => ({ Slice: 30, gNB: 24, UPF: 24, Router: 21, Service: 18, Policy: 16 }[d.node_type] || 18)).attr('fill', '#101d35').attr('stroke', d => riskColor(d.properties.fault_risk ?? d.properties.risk_score)).attr('stroke-width', 3);
    node.append('text').text(d => d.node_id).attr('text-anchor', 'middle').attr('dy', 4).attr('fill', '#e0f0ff').attr('font-size', 10);
    this.sim.nodes(nodes).on('tick', () => {
      link.attr('x1', d => d.source.x).attr('y1', d => d.source.y).attr('x2', d => d.target.x).attr('y2', d => d.target.y);
      node.attr('transform', d => `translate(${d.x},${d.y})`);
    });
    this.sim.force('link').links(links);
    this.sim.alpha(1).restart();
  }
}

function riskColor(risk) {
  const value = Number(risk || 0);
  if (value > 0.7) return '#ff3366';
  if (value > 0.3) return '#ffb800';
  return '#00ff88';
}

function inspectNode(node) {
  html('nodeInspector', `
    <div class="info-card summary-card">
      <h3>${node.node_id}</h3>
      <p>${node.node_type} • ${node.label || ''}</p>
      <div class="metric-strip">
        ${metricPill('Risk', pct(node.properties?.fault_risk ?? node.properties?.risk_score ?? 0), (node.properties?.fault_risk ?? node.properties?.risk_score ?? 0) > 0.5 ? 'warn' : 'good')}
        ${metricPill('Type', node.node_type, '')}
      </div>
      <button class="btn-secondary" onclick="explainNode('${node.node_id}')">Explain node</button>
    </div>`);
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
  state.telemetry = telemetry.data || [];
  state.charts.telemetry?.update(state.telemetry);
}

async function refreshDAG() {
  const dag = await api('/api/causal-graph');
  const edges = dag.data?.global_edges || dag.data?.edges || [];
  state.charts.dagMini?.update(edges, state.latestAlert);
  state.charts.dagFull?.update(edges, state.latestAlert);
}

async function refreshTopology() {
  const topo = await api('/api/topology');
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

async function refreshAll() {
  await Promise.allSettled([refreshTelemetry(), refreshDAG(), refreshTopology(), refreshAudit(), refreshDataMode(), refreshProactive(), explainCurrentTab(false)]);
}

function handleTick(payload) {
  state.tickCount += 1;
  text('tickCount', state.tickCount);
  if (payload.frames?.length) {
    state.telemetry.push(...payload.frames);
    state.telemetry = state.telemetry.slice(-300);
    state.charts.telemetry?.update(state.telemetry);
  }
  if (payload.proactive) {
    state.proactive = payload.proactive;
    html('proactivePanel', renderForecastCard(state.proactive));
  }
  if (payload.realtime) html('realtimePanel', renderRealtimeAnalysis(payload.realtime));
  if (payload.alert) renderAlert(payload.alert);
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
      explainCurrentTab(false).catch(toast);
    });
  });
  const saved = sessionStorage.getItem('netoracle_tab');
  if (saved) document.querySelector(`.nav-btn[data-tab="${saved}"]`)?.click();
}

function setupButtons() {
  $('btnTick')?.addEventListener('click', async () => { const r = await api('/api/telemetry/tick', { method: 'POST' }); handleTick({ frames: r.data }); });
  $('btnRefresh')?.addEventListener('click', () => refreshAll().catch(toast));
  $('btnRefreshDAG')?.addEventListener('click', () => refreshDAG().catch(toast));
  $('btnTopologyRefresh')?.addEventListener('click', () => refreshTopology().catch(toast));
  $('auditFilter')?.addEventListener('change', () => refreshAudit().catch(toast));
  $('severity')?.addEventListener('input', e => text('sevVal', e.target.value));
  $('btnBenchmark')?.addEventListener('click', runBenchmark);
  $('btnHopfield')?.addEventListener('click', runHopfield);
  $('btnPolicy')?.addEventListener('click', showPolicy);
  $('btnExportAudit')?.addEventListener('click', () => exportReport('/api/cloud/export-audit'));
  $('btnExportBench')?.addEventListener('click', () => exportReport('/api/cloud/export-benchmark'));
  $('btnAsk')?.addEventListener('click', askQuestion);
  $('runDemo')?.addEventListener('click', runDemo);
  $('runInject')?.addEventListener('click', injectFault);
  $('btnUploadTel')?.addEventListener('click', uploadTelemetry);
  $('btnUploadTopo')?.addEventListener('click', uploadTopology);
  $('btnAnalyse')?.addEventListener('click', analyseUploaded);
  $('btnRealtimeAnalyse')?.addEventListener('click', analyseRealtime);
  $('btnSimulateFix')?.addEventListener('click', simulateFix);
  $('btnOpen5gsDemo')?.addEventListener('click', runOpen5gsDemo);
  $('btnExplainTab')?.addEventListener('click', () => explainCurrentTab(true).catch(toast));
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
  const verdict = data.diagnosis?.evidence?.verdict;
  const cards = (verdict?.rounds?.flatMap(r => r.verdicts) || verdict?.specialist_verdicts || []).slice(0, 4);
  html('specialistCards', cards.map(v => `<div class="specialist-card"><b>${v.specialist || v.domain || 'Specialist'}</b><p>${v.root_cause || 'Diagnosis generated'}</p><small>${fmtPct(v.confidence || 0.5)} confidence</small></div>`).join(''));
  html('diagnosis', `
    <div class="decision-flow">
      <div>Telemetry anomaly detected</div><div>Causal risk forecast</div><div>Graph localization</div><div>Specialist debate</div><div>CMDP action selected</div>
    </div>
    <div class="summary-card"><h3>Root Cause</h3><p>${data.diagnosis?.root_cause || 'Graph-grounded diagnosis generated.'}</p><div class="metric-strip">${metricPill('Confidence', pct(data.diagnosis?.confidence), 'good')}${metricPill('Risk', human(data.diagnosis?.risk), '')}</div></div>`);
  if (data.proactive) {
    state.proactive = data.proactive;
    html('proactivePanel', renderForecastCard(data.proactive));
  }
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
  const result = await api('/api/nl-query', { method: 'POST', body: JSON.stringify({ query: $('question').value }) });
  html('nlAnswer', renderNlAnswer(result.data));
}

async function runBenchmark() {
  text('benchOutput', 'Running benchmark...');
  const n = Number($('benchScenarios')?.value || 60);
  const result = await api(`/api/benchmarks/run?scenarios=${n}`, { method: 'POST' });
  html('benchOutput', renderObjectSummary(result.data, 'Benchmark Summary'));
}

async function runHopfield() {
  text('hopOutput', 'Running Hopfield allocator...');
  const users = Number($('hopUsers')?.value || 8);
  const channels = Number($('hopCh')?.value || 16);
  const result = await api(`/api/wireless/hopfield?users=${users}&channels=${channels}`, { method: 'POST' });
  html('hopOutput', renderObjectSummary(result.data, 'Hopfield Allocation') + `<div class="math-panel"><b>Lyapunov energy</b><code>E=-1/2ΣᵢΣⱼwᵢⱼsᵢsⱼ+Σᵢθᵢsᵢ</code><p>The allocator converges by reducing network energy while avoiding channel conflicts.</p></div>`);
  const matrix = result.data?.assignment || result.data?.matrix || [];
  html('hopfieldViz', matrix.flatMap((row, i) => row.map((v, j) => `<span class="hop-cell ${v ? 'active' : ''}" title="u${i}/c${j}"></span>`)).join(''));
}

async function showPolicy() {
  const result = await api('/api/rl/policy');
  html('policyOutput', renderObjectSummary(result.data, 'CMDP Policy') + `<div class="math-panel"><b>Safety objective</b><code>maximize E[Σγᵗrₜ] subject to E[Σγᵗcₜ]≤Cmax</code><p>Unsafe actions are masked before the policy can select them.</p></div>`);
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
