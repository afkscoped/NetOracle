const $ = (id) => document.getElementById(id);
let lastDemo = null;
let demoActive = false;

async function api(path, options = {}) {
  const res = await fetch(path, { headers: { 'Content-Type': 'application/json' }, ...options });
  if (!res.ok) throw new Error(`${path} failed: ${res.status}`);
  return res.json();
}

function fmtPct(value) {
  if (value === undefined || value === null || Number.isNaN(value)) return '--';
  return `${Math.round(value * 100)}%`;
}

function drawTelemetry(rows) {
  const canvas = $('telemetryChart');
  const ctx = canvas.getContext('2d');
  const w = canvas.width;
  const h = canvas.height;
  ctx.clearRect(0, 0, w, h);
  ctx.fillStyle = 'rgba(2,6,23,.45)';
  ctx.fillRect(0, 0, w, h);
  const lines = [
    ['latency_ms', '#67e8f9', 120],
    ['cpu', '#a78bfa', 100],
    ['packet_loss', '#fb7185', .18],
    ['prb_utilization', '#86efac', 1],
  ];
  const data = rows.slice(-90).filter(r => r.node_id.includes('upf') || r.node_type === 'UPF');
  ctx.strokeStyle = 'rgba(255,255,255,.08)';
  for (let i = 0; i < 6; i++) {
    const y = (h / 6) * i;
    ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(w, y); ctx.stroke();
  }
  lines.forEach(([metric, color, max]) => {
    ctx.strokeStyle = color;
    ctx.lineWidth = 3;
    ctx.beginPath();
    data.forEach((row, i) => {
      const x = (i / Math.max(data.length - 1, 1)) * w;
      const y = h - Math.min(1, (row.metrics[metric] || 0) / max) * (h - 30) - 15;
      if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    });
    ctx.stroke();
  });
  ctx.fillStyle = '#91a8c6';
  ctx.font = '14px system-ui';
  ctx.fillText('cyan latency | violet cpu | red packet loss | green PRB', 18, 24);
}

function network(container, items, edges = []) {
  container.innerHTML = '';
  const rect = container.getBoundingClientRect();
  const w = Math.max(rect.width, 320);
  const h = Math.max(rect.height, 250);
  const positions = new Map();
  items.forEach((item, i) => {
    const angle = (Math.PI * 2 * i) / Math.max(items.length, 1) - Math.PI / 2;
    const x = w / 2 + Math.cos(angle) * Math.min(w, h) * .31;
    const y = h / 2 + Math.sin(angle) * Math.min(w, h) * .31;
    positions.set(item.id, { x, y });
  });
  edges.forEach(edge => {
    const a = positions.get(edge[0]);
    const b = positions.get(edge[1]);
    if (!a || !b) return;
    const el = document.createElement('div');
    const dx = b.x - a.x;
    const dy = b.y - a.y;
    el.className = 'edge';
    el.style.left = `${a.x}px`;
    el.style.top = `${a.y}px`;
    el.style.width = `${Math.hypot(dx, dy)}px`;
    el.style.transform = `rotate(${Math.atan2(dy, dx)}rad)`;
    container.appendChild(el);
  });
  items.forEach(item => {
    const pos = positions.get(item.id);
    const el = document.createElement('div');
    el.className = 'node';
    el.style.left = `${pos.x - 38}px`;
    el.style.top = `${pos.y - 38}px`;
    el.textContent = item.label || item.id;
    container.appendChild(el);
  });
}

async function refresh() {
  const [telemetry, dag, topo, audit, metrics, alerts] = await Promise.all([
    api('/api/telemetry/recent?limit=240'),
    api('/api/causal-graph'),
    api('/api/topology'),
    api('/api/audit?limit=20'),
    api('/api/metrics'),
    api('/api/alerts?limit=1'),
  ]);
  drawTelemetry(telemetry.data);
  const dagNodes = [...new Set(dag.data.global_edges.flatMap(e => [e.source, e.target]))].map(id => ({ id }));
  network($('dag'), dagNodes, dag.data.global_edges.map(e => [e.source, e.target]));
  const nodes = topo.data.nodes.filter(n => ['Slice', 'gNB', 'UPF', 'Router', 'Service'].includes(n.node_type)).slice(0, 12).map(n => ({ id: n.node_id, label: n.node_id }));
  network($('topology'), nodes, topo.data.edges.map(e => [e.source_id, e.target_id]));
  const modelName = metrics.data.model_active || 'heuristic';
  $('auc').textContent = fmtPct(metrics.data.auc_proxy);
  $('aucLabel').textContent = modelName === 'CausalAttentionGRU' ? 'Causal attention GRU' : 'Heuristic sigmoid';
  if (!demoActive) {
    const alert = alerts.data[0];
    if (alert) {
      $('probability').textContent = fmtPct(alert.fault_probability);
      const bounds = alert.prob_lower != null ? ` [${fmtPct(alert.prob_lower)}–${fmtPct(alert.prob_upper)}]` : '';
      $('horizon').textContent = `${alert.horizon_minutes} min horizon • ${alert.node_id}${bounds}`;
    }
  }
  $('audit').innerHTML = audit.data.map(item => `<div class="audit-item"><b>${item.event_type}</b><br><small>${item.timestamp}</small></div>`).join('');
}

async function runDemo() {
  $('diagnosis').textContent = 'Running closed loop...';
  demoActive = true;
  const body = {
    slice_id: $('slice').value,
    node_id: $('node').value,
    fault_type: $('fault').value,
    severity: Number($('severity').value),
    ticks: 18,
  };
  const result = await api('/api/demo/run', { method: 'POST', body: JSON.stringify(body) });
  lastDemo = result.data;
  const alert = lastDemo.alert;
  const prob = alert.fault_probability;
  $('probability').textContent = fmtPct(prob);
  const bounds = alert.prob_lower != null ? ` [${fmtPct(alert.prob_lower)}–${fmtPct(alert.prob_upper)}]` : '';
  $('horizon').textContent = `${alert.horizon_minutes || 10} min • ${alert.node_id} • ${alert.fault_type || body.fault_type}${bounds}`;
  $('confidence').textContent = fmtPct(lastDemo.diagnosis.confidence);
  const modelLabel = alert.model_used || 'heuristic';
  $('aucLabel').textContent = modelLabel === 'CausalAttentionGRU' ? 'CTGNN live inference' : modelLabel;
  $('remediation').textContent = lastDemo.remediation.action.replaceAll('_', ' ');
  $('remLabel').textContent = alert.calibrated ? `Conformal calibrated • q̂=${alert.prob_upper - prob > 0 ? (alert.prob_upper - prob).toFixed(2) : '?'}` : 'Risk-gated action';
  $('diagnosis').textContent = JSON.stringify({ alert, graph_context: lastDemo.graph_context, diagnosis: lastDemo.diagnosis, remediation: lastDemo.remediation }, null, 2);
  await refresh();
  demoActive = false;
}

async function ask() {
  const result = await api('/api/nl-query', { method: 'POST', body: JSON.stringify({ question: $('question').value }) });
  $('answer').textContent = JSON.stringify(result.data, null, 2);
}

$('runDemo').addEventListener('click', () => runDemo().catch(err => $('diagnosis').textContent = err.message));
$('tick').addEventListener('click', async () => { await api('/api/telemetry/tick', { method: 'POST' }); await refresh(); });
$('refresh').addEventListener('click', () => refresh());
$('ask').addEventListener('click', () => ask());

async function uploadTelemetry() {
  const file = $('telemetryFile').files[0];
  if (!file) { $('opsOutput').textContent = 'Select a telemetry file first'; return; }
  const text = await file.text();
  const form = new FormData();
  form.append('file', new Blob([text], { type: 'text/csv' }), file.name);
  const res = await fetch('/api/data/upload-telemetry', { method: 'POST', body: form });
  const json = await res.json();
  $('opsOutput').textContent = JSON.stringify(json.data, null, 2);
}

async function uploadTopology() {
  const file = $('topologyFile').files[0];
  if (!file) { $('opsOutput').textContent = 'Select a topology file first'; return; }
  const text = await file.text();
  const form = new FormData();
  form.append('file', new Blob([text], { type: 'application/json' }), file.name);
  const res = await fetch('/api/data/upload-topology', { method: 'POST', body: form });
  const json = await res.json();
  $('opsOutput').textContent = JSON.stringify(json.data, null, 2);
}

async function analyseUploaded() {
  const json = await api('/api/analyse/uploaded-data', { method: 'POST' });
  $('diagnosis').textContent = JSON.stringify(json.data, null, 2);
}

async function runBenchmark() {
  const scenarios = Math.max(10, Math.min(300, parseInt($('benchmarkScenarios').value || '60', 10)));
  $('opsOutput').textContent = 'Running benchmark...';
  const json = await api(`/api/benchmarks/run?scenarios=${scenarios}`, { method: 'POST' });
  $('opsOutput').textContent = JSON.stringify(json.data, null, 2);
}

async function runHopfield() {
  $('opsOutput').textContent = 'Running Hopfield allocator...';
  const json = await api('/api/wireless/hopfield', { method: 'POST' });
  $('opsOutput').textContent = JSON.stringify(json.data, null, 2);
}

async function exportCloud() {
  $('opsOutput').textContent = 'Exporting to cloud...';
  const json = await api('/api/cloud/export-benchmark', { method: 'POST' });
  $('opsOutput').textContent = JSON.stringify(json.data, null, 2);
}

async function showPolicy() {
  const json = await api('/api/rl/policy');
  $('opsOutput').textContent = JSON.stringify(json.data, null, 2);
}

$('uploadTelemetry').addEventListener('click', () => uploadTelemetry().catch(err => $('opsOutput').textContent = err.message));
$('uploadTopology').addEventListener('click', () => uploadTopology().catch(err => $('opsOutput').textContent = err.message));
$('analyseUploaded').addEventListener('click', () => analyseUploaded().catch(err => $('opsOutput').textContent = err.message));
$('runBenchmark').addEventListener('click', () => runBenchmark().catch(err => $('opsOutput').textContent = err.message));
$('runHopfield').addEventListener('click', () => runHopfield().catch(err => $('opsOutput').textContent = err.message));
$('exportCloud').addEventListener('click', () => exportCloud().catch(err => $('opsOutput').textContent = err.message));
$('showPolicy').addEventListener('click', () => showPolicy().catch(err => $('opsOutput').textContent = err.message));

refresh().catch(console.error);
