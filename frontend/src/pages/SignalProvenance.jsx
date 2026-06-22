import React, { useEffect, useState } from 'react';
import { GitBranch, RefreshCw, Database, Sigma, BrainCircuit, ShieldCheck } from 'lucide-react';
import { api } from '../utils/api';
import GlassPanel from '../components/GlassPanel';
import './SignalProvenance.css';

const fmt = (value, digits = 3) => (value == null || Number.isNaN(Number(value)) ? 'n/a' : Number(value).toFixed(digits));
const colorFor = (value) => {
  const v = Math.max(-4, Math.min(4, Number(value) || 0));
  if (v >= 0) return `rgba(239, 68, 68, ${0.12 + Math.abs(v) * 0.16})`;
  return `rgba(34, 211, 238, ${0.12 + Math.abs(v) * 0.16})`;
};

export default function SignalProvenance() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      setData(await api.get('/api/provenance/latest'));
    } catch (err) {
      console.error(err);
      setData({ status: 'error', message: err.message, stages: {} });
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    const first = setTimeout(load, 0);
    const id = setInterval(load, 5000);
    return () => {
      clearTimeout(first);
      clearInterval(id);
    };
  }, []);

  const stages = data?.stages || {};
  const node = data?.node || {};

  return (
    <div className="provenance-page">
      <header className="page-header flex justify-between items-center mb-6">
        <div>
          <h1 className="text-3xl font-bold flex items-center gap-3" style={{ fontFamily: 'Orbitron, sans-serif' }}>
            <GitBranch className="text-cyan-400" /> Signal Provenance
          </h1>
          <p className="text-sm text-gray-400 mt-1">Live trace from source telemetry to calibrated action gate</p>
        </div>
        <button onClick={load} className={`icon-refresh ${loading ? 'spin' : ''}`} title="Refresh provenance">
          <RefreshCw size={18} />
        </button>
      </header>

      {data?.status !== 'ready' ? (
        <GlassPanel className="p-6 text-gray-400">{data?.message || 'Waiting for a prediction trace.'}</GlassPanel>
      ) : (
        <>
          <GlassPanel className="provenance-node mb-6">
            <div>
              <span className="kpi-label">Active Trace</span>
              <h2>{node.node_id} <small>{node.node_type}</small></h2>
            </div>
            <div className={`source-pill ${String(node.source).includes('live') ? 'live' : ''}`}>{node.source}</div>
          </GlassPanel>

          <div className="signal-flow">
            <Stage icon={<Database />} title="Raw Collection">
              <div className="query-list">
                {(stages.raw_collection?.queries || []).slice(0, 8).map((query, idx) => (
                  <div className="query-row" key={`${query.name}-${idx}`}>
                    <span>{query.name || 'query'}</span>
                    <code>{query.promql || query.endpoint || 'simulation-derived'}</code>
                    <b>{fmt(query.value)}</b>
                    <em>{fmt(query.latency_ms, 1)} ms</em>
                  </div>
                ))}
                {(stages.raw_collection?.queries || []).length === 0 && (
                  <div className="empty-mini">No PromQL evidence on this tick; using generated or fallback telemetry.</div>
                )}
              </div>
              <MetricGrid metrics={stages.raw_collection?.derived_metrics} />
            </Stage>

            <Stage icon={<Sigma />} title="Normalization">
              <div className="norm-grid">
                {(stages.normalization?.latest || []).map((row) => (
                  <div className="norm-card" key={row.metric}>
                    <span>{row.metric}</span>
                    <b>{fmt(row.normalized)}</b>
                    <code>{row.formula}</code>
                  </div>
                ))}
              </div>
              <Heatmap tensor={stages.normalization?.tensor || []} metrics={stages.normalization?.metrics || []} />
            </Stage>

            <Stage icon={<BrainCircuit />} title="Model Processing">
              <div className="model-strip">
                <Metric label="Model" value={stages.model_processing?.model} />
                <Metric label="Logit" value={fmt(stages.model_processing?.logit, 4)} />
                <Metric label="Probability" value={`${fmt((stages.model_processing?.probability || 0) * 100, 1)}%`} />
                <Metric label="Hidden magnitude" value={fmt(stages.model_processing?.hidden_state_magnitude, 3)} />
              </div>
              <AttributionBars data={stages.model_processing?.attribution?.contributions || {}} />
              <AttentionMatrix values={stages.model_processing?.attention_weights} />
            </Stage>

            <Stage icon={<ShieldCheck />} title="Calibration & Decision">
              <div className="model-strip">
                <Metric label="q_hat" value={fmt(stages.calibration_decision?.conformal?.q_hat, 4)} />
                <Metric label="Interval" value={`${fmt(stages.calibration_decision?.conformal?.prob_lower, 3)} - ${fmt(stages.calibration_decision?.conformal?.prob_upper, 3)}`} />
                <Metric label="ACI delta" value={fmt(stages.calibration_decision?.aci_update?.delta, 5)} />
                <Metric label="Fault" value={stages.calibration_decision?.fault_type} />
              </div>
              <div className="cmdp-box">
                <b>{stages.calibration_decision?.cmdp_gate?.action || 'No CMDP action yet'}</b>
                <span>{stages.calibration_decision?.cmdp_gate?.cmdp_reason || 'The safety gate will appear after a remediation decision.'}</span>
              </div>
              <div className="edge-list">
                {(stages.calibration_decision?.causal_edges || []).slice(0, 8).map((edge, idx) => (
                  <span key={idx}>{edge.source || edge[0]} {'->'} {edge.target || edge[1]}</span>
                ))}
              </div>
            </Stage>
          </div>
        </>
      )}
    </div>
  );
}

function Stage({ icon, title, children }) {
  return (
    <GlassPanel className="flow-stage">
      <div className="stage-heading">{React.cloneElement(icon, { size: 18 })}<h2>{title}</h2></div>
      {children}
    </GlassPanel>
  );
}

function Metric({ label, value }) {
  return <div className="mini-metric"><span>{label}</span><b>{value ?? 'n/a'}</b></div>;
}

function MetricGrid({ metrics = {} }) {
  return <div className="metric-grid">{Object.entries(metrics).map(([k, v]) => <Metric key={k} label={k} value={fmt(v)} />)}</div>;
}

function Heatmap({ tensor, metrics }) {
  return (
    <div className="heatmap" style={{ gridTemplateColumns: `repeat(${metrics.length || 6}, 1fr)` }}>
      {tensor.flatMap((row, i) => row.map((value, j) => (
        <div key={`${i}-${j}`} title={`t-${tensor.length - i} ${metrics[j] || j}: ${fmt(value)}`} style={{ background: colorFor(value) }} />
      )))}
    </div>
  );
}

function AttentionMatrix({ values }) {
  if (!values || !Array.isArray(values)) return <div className="empty-mini">Attention weights unavailable in heuristic or MLP mode.</div>;
  const matrix = Array.isArray(values[0]) ? values : [values];
  return (
    <div className="attention" style={{ gridTemplateColumns: `repeat(${matrix[0]?.length || 1}, 1fr)` }}>
      {matrix.flatMap((row, i) => row.map((value, j) => (
        <div key={`${i}-${j}`} title={`${i},${j}: ${fmt(value, 4)}`} style={{ opacity: 0.2 + Math.min(0.8, Number(value) || 0) }} />
      )))}
    </div>
  );
}

function AttributionBars({ data }) {
  const max = Math.max(...Object.values(data).map((v) => Math.abs(Number(v))), 0.001);
  return (
    <div className="attrib-bars">
      {Object.entries(data).map(([metric, value]) => (
        <div className="attrib-row" key={metric}>
          <span>{metric}</span>
          <div><i style={{ width: `${Math.min(100, Math.abs(value) / max * 100)}%` }} /></div>
          <b>{fmt(value, 4)}</b>
        </div>
      ))}
    </div>
  );
}
