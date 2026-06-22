import React, { useEffect, useState } from 'react';
import { Telescope, RefreshCw, GitCompare, ShieldCheck, SearchCheck, AlertTriangle } from 'lucide-react';
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { api } from '../utils/api';
import GlassPanel from '../components/GlassPanel';
import './Observatory.css';

const fmt = (value, digits = 3) => (value == null || Number.isNaN(Number(value)) ? 'n/a' : Number(value).toFixed(digits));

export default function Observatory() {
  const [comparison, setComparison] = useState(null);
  const [divergence, setDivergence] = useState(null);
  const [match, setMatch] = useState(null);
  const [loading, setLoading] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const [c, d, m] = await Promise.all([
        api.get('/api/observatory/comparison?limit=100'),
        api.get('/api/observatory/divergence-log?limit=100'),
        api.get('/api/observatory/incident-match'),
      ]);
      setComparison(c);
      setDivergence(d);
      setMatch(m);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    const first = setTimeout(load, 0);
    const id = setInterval(load, 10000);
    return () => {
      clearTimeout(first);
      clearInterval(id);
    };
  }, []);

  const transfer = comparison?.transfer_quality || {};
  const chartData = Object.entries(transfer).map(([metric, item]) => ({
    metric: metric.replace('_mbps', '').replace('_ms', ''),
    kl: item.kl_divergence,
    badge: item.badge,
  }));
  const aci = comparison?.conformal?.aci || {};
  const calibration = comparison?.conformal?.calibration || {};

  return (
    <div className="observatory-page">
      <header className="page-header flex justify-between items-center mb-6">
        <div>
          <h1 className="text-3xl font-bold flex items-center gap-3" style={{ fontFamily: 'Orbitron, sans-serif' }}>
            <Telescope className="text-cyan-400" /> Sim vs Live Observatory
          </h1>
          <p className="text-sm text-gray-400 mt-1">What live Open5GS teaches beyond the synthetic baseline</p>
        </div>
        <button onClick={load} className={`icon-refresh ${loading ? 'spin' : ''}`} title="Refresh observatory">
          <RefreshCw size={18} />
        </button>
      </header>

      <div className="observatory-grid">
        <GlassPanel className="observatory-panel wide">
          <PanelTitle icon={<GitCompare />} title="Live Distribution Comparison" />
          <div className="comparison-summary">
            <span>Live ticks: <b>{comparison?.counts?.live || 0}</b></span>
            <span>Shadow sim ticks: <b>{comparison?.counts?.shadow_sim || 0}</b></span>
          </div>
          <div className="chart-box">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={chartData}>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.04)" />
                <XAxis dataKey="metric" stroke="rgba(255,255,255,0.35)" tick={{ fontSize: 10 }} />
                <YAxis stroke="rgba(255,255,255,0.35)" tick={{ fontSize: 10 }} />
                <Tooltip contentStyle={{ background: '#0f172a', border: '1px solid rgba(255,255,255,.08)' }} />
                <Bar dataKey="kl" fill="#22d3ee" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
          <div className="quality-badges">
            {Object.entries(transfer).map(([metric, item]) => (
              <span key={metric} className={`quality ${item.badge}`}>{metric}: {fmt(item.kl_divergence)}</span>
            ))}
          </div>
        </GlassPanel>

        <GlassPanel className="observatory-panel">
          <PanelTitle icon={<ShieldCheck />} title="Model Calibration Proof" />
          <div className="calibration-grid">
            <Metric label="Target coverage" value={`${fmt((calibration.target_coverage || 0) * 100, 1)}%`} />
            <Metric label="Running coverage" value={aci.empirical_coverage == null ? 'waiting' : `${fmt(aci.empirical_coverage * 100, 1)}%`} />
            <Metric label="q_hat" value={fmt(calibration.q_hat, 4)} />
            <Metric label="ACI updates" value={aci.aci_updates || 0} />
          </div>
          <p className="observatory-copy">{comparison?.value_statement || 'Waiting for comparison data.'}</p>
        </GlassPanel>

        <GlassPanel className="observatory-panel">
          <PanelTitle icon={<SearchCheck />} title="Real vs Synthetic Incident" />
          <IncidentMatch match={match} />
        </GlassPanel>

        <GlassPanel className="observatory-panel wide">
          <PanelTitle icon={<AlertTriangle />} title="What Simulation Gets Wrong" />
          <div className="divergence-table">
            {(divergence?.rows || []).map((row) => (
              <div className="divergence-row" key={row.metric}>
                <b>{row.metric}</b>
                <span>{row.sim_distribution}</span>
                <span>{row.live_distribution}</span>
                <em className={row.severity}>{row.why}</em>
              </div>
            ))}
          </div>
        </GlassPanel>

        <GlassPanel className="observatory-panel statement">
          <h2>Practical Value Statement</h2>
          <p>{divergence?.value_statement || comparison?.value_statement || 'The observatory will summarize transfer quality after telemetry arrives.'}</p>
        </GlassPanel>
      </div>
    </div>
  );
}

function PanelTitle({ icon, title }) {
  return <div className="panel-title">{React.cloneElement(icon, { size: 18 })}<h2>{title}</h2></div>;
}

function Metric({ label, value }) {
  return <div className="obs-metric"><span>{label}</span><b>{value}</b></div>;
}

function IncidentMatch({ match }) {
  const real = match?.real_incident || {};
  const synthetic = match?.closest_synthetic;
  if (!synthetic) return <p className="observatory-copy">No synthetic scenario rows are available to match yet.</p>;
  return (
    <div className="incident-match">
      <div>
        <h3>Real Incident</h3>
        {Object.entries(real.metrics || {}).map(([metric, value]) => <span key={metric}>{metric}: <b>{fmt(value)}</b></span>)}
      </div>
      <div>
        <h3>{synthetic.scenario}</h3>
        {Object.entries(synthetic.metrics || {}).map(([metric, value]) => <span key={metric}>{metric}: <b>{fmt(value)}</b></span>)}
        <strong>Similarity {fmt(synthetic.similarity, 2)} / 1.0</strong>
      </div>
    </div>
  );
}
