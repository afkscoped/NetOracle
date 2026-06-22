import React, { useState, useEffect, useContext } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Activity, AlertTriangle, Wifi, TrendingUp, Zap, RefreshCw, Play, Globe } from 'lucide-react';
import { AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, LineChart, Line } from 'recharts';
import { AppContext } from '../context/AppContext';
import GlassPanel from '../components/GlassPanel';
import RingGauge from '../components/RingGauge';
import './Dashboard.css';

export default function Dashboard() {
  const { state, refreshTelemetry, refreshMetrics, triggerTick } = useContext(AppContext);
  const { telemetry, alerts, metrics } = state;

  const [visibleMetrics, setVisibleMetrics] = useState({
    cpu: true,
    memory: true,
    latency: true,
    packetLoss: true,
    throughput: true,
  });

  const [isRefreshing, setIsRefreshing] = useState(false);

  useEffect(() => {
    refreshTelemetry();
    refreshMetrics();
  }, []);

  const handleRefresh = async () => {
    setIsRefreshing(true);
    await Promise.all([refreshTelemetry(), refreshMetrics()]);
    setIsRefreshing(false);
  };

  const handleTriggerTick = async () => {
    try {
      await triggerTick();
    } catch (err) {
      console.error(err);
    }
  };

  const toggleMetric = (metric) => {
    setVisibleMetrics((prev) => ({ ...prev, [metric]: !prev[metric] }));
  };

  // Process data for charts
  const chartData = telemetry.map((t) => ({
    time: t.timestamp ? new Date(t.timestamp).toLocaleTimeString() : '',
    cpu: t.cpu != null ? Math.round(t.cpu * 10) / 10 : 0,
    memory: t.memory != null ? Math.round(t.memory) : 0,
    latency: t.latency_ms || 0,
    packetLoss: t.packet_loss != null ? Math.round(t.packet_loss * 100) : 0,
    throughput: t.throughput_mbps || 0,
  }));

  // Sparkline data for throughput
  const sparklineData = chartData.map((d) => ({ val: d.throughput }));

  // Break down alert severities
  const criticalAlerts = alerts.filter((a) => a.fault_probability > 0.85).length;
  const warningAlerts = alerts.filter((a) => a.fault_probability > 0.5 && a.fault_probability <= 0.85).length;
  const infoAlerts = alerts.filter((a) => a.fault_probability <= 0.5).length;

  return (
    <div className="dashboard-page">
      <header className="page-header flex justify-between items-center mb-6">
        <div>
          <h1 className="text-3xl font-bold flex items-center gap-3" style={{ fontFamily: 'Orbitron, sans-serif' }}>
            <Activity className="text-cyan-400 animate-pulse" /> NetOracle NOC
          </h1>
          <p className="text-sm text-gray-400 mt-1">Causal 5G Network Fault Intelligence System</p>
        </div>
        <div className="flex gap-3">
          <button
            onClick={handleTriggerTick}
            className="flex items-center gap-2 px-4 py-2 bg-gradient-to-r from-cyan-600 to-blue-600 hover:from-cyan-500 hover:to-blue-500 text-white rounded-lg font-medium transition-all shadow-lg shadow-cyan-950/20 active:scale-95"
          >
            <Play size={16} /> Force Tick
          </button>
          <button
            onClick={handleRefresh}
            disabled={isRefreshing}
            className={`flex items-center justify-center p-2.5 rounded-lg border border-cyan-800/30 text-cyan-400 bg-cyan-950/25 hover:bg-cyan-900/40 transition-all ${
              isRefreshing ? 'animate-spin' : ''
            }`}
          >
            <RefreshCw size={18} />
          </button>
        </div>
      </header>

      {/* KPI Row */}
      <section className="kpi-row grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-6 mb-6">
        <GlassPanel className="kpi-card flex items-center justify-between gap-4" delay={0.05}>
          <div className="flex flex-col">
            <span className="kpi-label text-xs uppercase tracking-wider text-gray-400">Fault Probability</span>
            <span className="kpi-value text-2xl font-bold mt-2" style={{ fontFamily: 'Orbitron, sans-serif' }}>
              {metrics.fault_probability > 0.4 ? 'Elevated' : 'Optimal'}
            </span>
            <span className="text-[10px] text-gray-500 mt-1">Live inference rate</span>
          </div>
          <RingGauge
            value={metrics.fault_probability}
            title="Risk"
            size={90}
            strokeWidth={8}
            colorMap={(val) => (val > 0.8 ? '#ef4444' : val > 0.4 ? '#f59e0b' : '#10b981')}
          />
        </GlassPanel>

        <GlassPanel className="kpi-card flex items-center justify-between gap-4" delay={0.1}>
          <div className="flex flex-col">
            <span className="kpi-label text-xs uppercase tracking-wider text-gray-400">Active Alerts</span>
            <span className="kpi-value text-3xl font-extrabold mt-2 text-red-400" style={{ fontFamily: 'Orbitron, sans-serif' }}>
              {alerts.length}
            </span>
            <div className="flex gap-2 mt-2 text-[10px]">
              <span className="px-1.5 py-0.5 rounded bg-red-950/40 text-red-400 border border-red-900/30">{criticalAlerts} Crit</span>
              <span className="px-1.5 py-0.5 rounded bg-amber-950/40 text-amber-400 border border-amber-900/30">{warningAlerts} Warn</span>
              <span className="px-1.5 py-0.5 rounded bg-cyan-950/40 text-cyan-400 border border-cyan-900/30">{infoAlerts} Info</span>
            </div>
          </div>
          <AlertTriangle size={48} className="text-red-500/80 filter drop-shadow-[0_0_8px_rgba(239,68,68,0.3)] animate-pulse" />
        </GlassPanel>

        <GlassPanel className="kpi-card flex items-center justify-between gap-4" delay={0.15}>
          <div className="flex flex-col">
            <span className="kpi-label text-xs uppercase tracking-wider text-gray-400">Prediction Accuracy</span>
            <span className="kpi-value text-2xl font-bold mt-2" style={{ fontFamily: 'Orbitron, sans-serif' }}>
              {metrics.model_type.split(' ')[0]}
            </span>
            <span className="text-[10px] text-cyan-400 mt-1">Conformal coverage: 95%</span>
          </div>
          <RingGauge value={metrics.prediction_auc} title="AUC" size={90} strokeWidth={8} colorMap={() => '#00e5ff'} />
        </GlassPanel>

        <GlassPanel className="kpi-card flex items-center justify-between gap-4" delay={0.2}>
          <div className="flex flex-col w-1/2">
            <span className="kpi-label text-xs uppercase tracking-wider text-gray-400">Live Throughput</span>
            <span className="kpi-value text-2xl font-bold mt-2 text-green-400" style={{ fontFamily: 'Orbitron, sans-serif' }}>
              {telemetry.length > 0 ? `${(telemetry[telemetry.length - 1].throughput_mbps || 0).toFixed(1)} Mbps` : '0.0 Mbps'}
            </span>
            <span className="text-[10px] text-gray-500 mt-1">Total aggregated load</span>
          </div>
          <div className="w-1/2 h-14">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={sparklineData}>
                <Line type="monotone" dataKey="val" stroke="#10b981" strokeWidth={2} dot={false} isAnimationActive={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </GlassPanel>
      </section>

      {/* Main Grid: Telemetry + Alerts */}
      <div className="grid grid-cols-1 xl:grid-cols-3 gap-6">
        {/* Telemetry Chart Panel */}
        <GlassPanel className="chart-container xl:col-span-2 flex flex-col justify-between" delay={0.25}>
          <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4 mb-6">
            <div>
              <h2 className="text-lg font-bold" style={{ fontFamily: 'Orbitron, sans-serif' }}>Telemetry Streaming Analysis</h2>
              <p className="text-xs text-gray-500 mt-0.5">Real-time KPI observations across network slices</p>
            </div>
            {/* Legend controls */}
            <div className="chart-controls flex flex-wrap gap-2">
              <button
                onClick={() => toggleMetric('cpu')}
                className={`chart-toggle ${visibleMetrics.cpu ? 'active-cpu' : ''}`}
              >
                CPU
              </button>
              <button
                onClick={() => toggleMetric('memory')}
                className={`chart-toggle ${visibleMetrics.memory ? 'active-memory' : ''}`}
              >
                RAM
              </button>
              <button
                onClick={() => toggleMetric('latency')}
                className={`chart-toggle ${visibleMetrics.latency ? 'active-latency' : ''}`}
              >
                Latency
              </button>
              <button
                onClick={() => toggleMetric('packetLoss')}
                className={`chart-toggle ${visibleMetrics.packetLoss ? 'active-loss' : ''}`}
              >
                Loss
              </button>
              <button
                onClick={() => toggleMetric('throughput')}
                className={`chart-toggle ${visibleMetrics.throughput ? 'active-throughput' : ''}`}
              >
                TPut
              </button>
            </div>
          </div>

          <div className="h-80 w-full relative">
            {chartData.length === 0 ? (
              <div className="absolute inset-0 flex items-center justify-center text-gray-500 text-sm">
                Waiting for telemetry data stream...
              </div>
            ) : (
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={chartData} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                  <defs>
                    <linearGradient id="colorCpu" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#00e5ff" stopOpacity={0.25}/>
                      <stop offset="95%" stopColor="#00e5ff" stopOpacity={0.0}/>
                    </linearGradient>
                    <linearGradient id="colorMemory" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#a855f7" stopOpacity={0.25}/>
                      <stop offset="95%" stopColor="#a855f7" stopOpacity={0.0}/>
                    </linearGradient>
                    <linearGradient id="colorLatency" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#f59e0b" stopOpacity={0.25}/>
                      <stop offset="95%" stopColor="#f59e0b" stopOpacity={0.0}/>
                    </linearGradient>
                    <linearGradient id="colorLoss" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#ef4444" stopOpacity={0.25}/>
                      <stop offset="95%" stopColor="#ef4444" stopOpacity={0.0}/>
                    </linearGradient>
                    <linearGradient id="colorThroughput" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#10b981" stopOpacity={0.25}/>
                      <stop offset="95%" stopColor="#10b981" stopOpacity={0.0}/>
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.03)" />
                  <XAxis dataKey="time" stroke="rgba(255,255,255,0.3)" tick={{ fontSize: 10 }} />
                  <YAxis stroke="rgba(255,255,255,0.3)" tick={{ fontSize: 10 }} />
                  <Tooltip content={<CustomTooltip />} />
                  
                  {visibleMetrics.cpu && (
                    <Area type="monotone" dataKey="cpu" stroke="#00e5ff" strokeWidth={1.5} fillOpacity={1} fill="url(#colorCpu)" name="CPU (%)" />
                  )}
                  {visibleMetrics.memory && (
                    <Area type="monotone" dataKey="memory" stroke="#a855f7" strokeWidth={1.5} fillOpacity={1} fill="url(#colorMemory)" name="RAM (%)" />
                  )}
                  {visibleMetrics.latency && (
                    <Area type="monotone" dataKey="latency" stroke="#f59e0b" strokeWidth={1.5} fillOpacity={1} fill="url(#colorLatency)" name="Latency (ms)" />
                  )}
                  {visibleMetrics.packetLoss && (
                    <Area type="monotone" dataKey="packetLoss" stroke="#ef4444" strokeWidth={1.5} fillOpacity={1} fill="url(#colorLoss)" name="Loss (%)" />
                  )}
                  {visibleMetrics.throughput && (
                    <Area type="monotone" dataKey="throughput" stroke="#10b981" strokeWidth={1.5} fillOpacity={1} fill="url(#colorThroughput)" name="Throughput" />
                  )}
                </AreaChart>
              </ResponsiveContainer>
            )}
          </div>
        </GlassPanel>

        {/* Alerts Section Panel */}
        <GlassPanel className="alerts-section flex flex-col h-[440px]" delay={0.3}>
          <div className="flex justify-between items-center mb-4">
            <div>
              <h2 className="text-lg font-bold" style={{ fontFamily: 'Orbitron, sans-serif' }}>Fault Alert Stream</h2>
              <p className="text-xs text-gray-500 mt-0.5">Real-time anomaly feeds and model confidence</p>
            </div>
            <span className="text-[10px] uppercase font-semibold text-cyan-400 bg-cyan-950/40 px-2 py-0.5 rounded border border-cyan-800/30">
              Live Feed
            </span>
          </div>

          <div className="flex-grow overflow-y-auto pr-1 flex flex-col gap-3">
            <AnimatePresence initial={false}>
              {alerts.length === 0 ? (
                <div className="h-full flex flex-col items-center justify-center text-gray-500 text-sm gap-2">
                  <Wifi size={24} className="text-gray-600 animate-pulse" />
                  No anomalous behavior detected.
                </div>
              ) : (
                alerts.map((alert, idx) => {
                  const isCrit = alert.fault_probability > 0.85;
                  const isWarn = alert.fault_probability > 0.5 && alert.fault_probability <= 0.85;
                  
                  const severityClass = isCrit
                    ? 'alert-critical'
                    : isWarn
                    ? 'alert-warning'
                    : 'alert-info';

                  return (
                    <motion.div
                      key={alert.timestamp || idx}
                      initial={{ opacity: 0, x: 20 }}
                      animate={{ opacity: 1, x: 0 }}
                      exit={{ opacity: 0, x: -20 }}
                      transition={{ duration: 0.3 }}
                      className={`alert-card flex flex-col gap-1 p-3 rounded-lg bg-slate-900/40 border border-slate-800/30 ${severityClass}`}
                    >
                      <div className="flex justify-between items-center">
                        <span className="font-bold text-sm text-gray-200">
                          {alert.fault_type || 'Unknown Anomaly'}
                        </span>
                        <span className="text-[10px] text-gray-500">
                          {alert.timestamp ? new Date(alert.timestamp).toLocaleTimeString() : ''}
                        </span>
                      </div>
                      <div className="flex justify-between items-center text-xs mt-1">
                        <span className="text-gray-400 font-mono">
                          Node: {alert.node_id || alert.node || 'N/A'}
                        </span>
                        <span className="text-[10px] px-1.5 py-0.25 rounded bg-cyan-950/20 text-cyan-400 font-mono">
                          Slice: {alert.slice_id || alert.slice || 'N/A'}
                        </span>
                      </div>
                      <div className="flex justify-between items-center text-[10px] text-gray-500 mt-1 pt-1 border-t border-white/5">
                        <span>Risk: {(alert.fault_probability * 100).toFixed(0)}%</span>
                        <span className="text-cyan-400 font-mono">
                          H: {alert.prediction_horizon_steps || '1'}s
                        </span>
                      </div>
                    </motion.div>
                  );
                })
              )}
            </AnimatePresence>
          </div>
        </GlassPanel>
      </div>
    </div>
  );
}

// Custom tooltip for chart
function CustomTooltip({ active, payload, label }) {
  if (active && payload && payload.length) {
    return (
      <div className="custom-tooltip p-3 bg-slate-950/80 backdrop-blur-md border border-cyan-500/20 rounded-lg shadow-xl flex flex-col gap-1.5 text-xs">
        <p className="font-semibold text-gray-300 font-mono border-b border-white/5 pb-1 mb-1">{label}</p>
        {payload.map((p, idx) => (
          <div key={idx} className="flex justify-between items-center gap-6">
            <span style={{ color: p.color }} className="font-medium">{p.name}:</span>
            <span className="font-bold text-gray-200 font-mono">{p.value}</span>
          </div>
        ))}
      </div>
    );
  }
  return null;
}
