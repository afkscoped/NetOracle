import React, { useContext, useEffect, useState, useRef } from 'react';
import { AppContext } from '../context/AppContext';
import GlassPanel from '../components/GlassPanel';
import { 
  Database, 
  Terminal, 
  Activity, 
  Play, 
  Pause, 
  Trash2, 
  Cpu, 
  Clock, 
  Server, 
  TrendingUp,
  RefreshCw
} from 'lucide-react';
import { AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts';
import './RealTimeIngestion.css';

export default function RealTimeIngestion() {
  const { state, triggerTick } = useContext(AppContext);
  const { telemetry, isConnected, dataMode } = state;
  
  const [logs, setLogs] = useState([]);
  const [isPaused, setIsPaused] = useState(false);
  const [filterNode, setFilterNode] = useState('all');
  const [isManualTriggering, setIsManualTriggering] = useState(false);
  const terminalEndRef = useRef(null);
  
  const processedRef = useRef(new Set());
  
  useEffect(() => {
    if (isPaused || !telemetry || telemetry.length === 0) return;
    
    const newLogs = [];
    telemetry.forEach(frame => {
      const key = `${frame.timestamp}_${frame.node_id}_${frame.slice_id}`;
      if (!processedRef.current.has(key)) {
        processedRef.current.add(key);
        newLogs.push(frame);
      }
    });
    
    if (newLogs.length > 0) {
      setLogs(prev => {
        const combined = [...prev, ...newLogs];
        return combined.slice(-150);
      });
    }
  }, [telemetry, isPaused]);
  
  useEffect(() => {
    if (terminalEndRef.current) {
      terminalEndRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [logs]);

  const handleClearLogs = () => {
    setLogs([]);
    processedRef.current.clear();
  };

  const handleManualTick = async () => {
    setIsManualTriggering(true);
    try {
      await triggerTick();
    } catch (err) {
      console.error(err);
    } finally {
      setIsManualTriggering(false);
    }
  };

  const uniqueNodes = Array.from(new Set(telemetry.map(f => f.node_id))).filter(Boolean);
  
  const filteredLogs = logs.filter(log => {
    if (filterNode === 'all') return true;
    return log.node_id === filterNode;
  });

  const latestFrames = telemetry.slice(-8); 
  const averageCpu = latestFrames.length > 0 
    ? latestFrames.reduce((acc, curr) => acc + curr.cpu, 0) / latestFrames.length 
    : 0;
  const averageLatency = latestFrames.length > 0 
    ? latestFrames.reduce((acc, curr) => acc + curr.latency_ms, 0) / latestFrames.length 
    : 0;
  const totalLoss = latestFrames.length > 0 
    ? latestFrames.reduce((acc, curr) => acc + curr.packet_loss, 0) 
    : 0;

  const groupedByTime = {};
  telemetry.forEach(f => {
    const timeStr = new Date(f.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    if (!groupedByTime[timeStr]) {
      groupedByTime[timeStr] = { time: timeStr, cpuSum: 0, latencySum: 0, count: 0 };
    }
    groupedByTime[timeStr].cpuSum += f.cpu;
    groupedByTime[timeStr].latencySum += f.latency_ms;
    groupedByTime[timeStr].count += 1;
  });

  const chartData = Object.values(groupedByTime).map(group => ({
    time: group.time,
    'Avg CPU (%)': Math.round(group.cpuSum / group.count),
    'Avg Latency (ms)': Math.round(group.latencySum / group.count),
  })).slice(-15);

  return (
    <div className="ingestion-page">
      <header className="page-header flex justify-between items-center mb-6">
        <div>
          <h1 className="text-3xl font-bold flex items-center gap-3" style={{ fontFamily: 'Orbitron, sans-serif' }}>
            <Database className="text-cyan-400 animate-pulse" /> Live Ingestion Feed
          </h1>
          <p className="text-sm text-gray-400 mt-1">Real-time visualization of raw telemetry streams ingested by NetOracle</p>
        </div>
        
        <div className="flex items-center gap-3">
          {dataMode === 'simulation' && (
            <button 
              onClick={handleManualTick} 
              disabled={isManualTriggering}
              className="flex items-center gap-2 px-4 py-2 bg-cyan-950 border border-cyan-800 hover:bg-cyan-900 rounded-xl text-xs font-semibold text-cyan-300 transition-all disabled:opacity-50"
            >
              <RefreshCw size={14} className={isManualTriggering ? 'spin' : ''} />
              Trigger Sim Tick
            </button>
          )}
          
          <div className={`flex items-center gap-2 px-3 py-1.5 rounded-full text-xs font-mono border ${
            isConnected ? 'bg-green-950/40 border-green-800 text-green-400' : 'bg-red-950/40 border-red-800 text-red-400'
          }`}>
            <span className={`w-2 h-2 rounded-full ${isConnected ? 'bg-green-400 animate-ping' : 'bg-red-400'}`} />
            <span>{isConnected ? 'STREAMING ACTIVE' : 'DISCONNECTED'}</span>
          </div>
        </div>
      </header>

      <div className="grid grid-cols-1 md:grid-cols-4 gap-6 mb-6">
        <GlassPanel className="stat-card" animate={false}>
          <div className="flex items-center justify-between mb-2">
            <span className="text-xs text-gray-400 uppercase font-semibold">Active Mode</span>
            <Server size={16} className="text-cyan-400" />
          </div>
          <div className="text-2xl font-bold font-mono text-white capitalize">{dataMode}</div>
          <div className="text-[10px] text-gray-500 mt-1">Telemetry source adapter</div>
        </GlassPanel>

        <GlassPanel className="stat-card" animate={false}>
          <div className="flex items-center justify-between mb-2">
            <span className="text-xs text-gray-400 uppercase font-semibold">Avg Node CPU</span>
            <Cpu size={16} className="text-cyan-400" />
          </div>
          <div className="text-2xl font-bold font-mono text-white">{averageCpu.toFixed(1)}%</div>
          <div className="text-[10px] text-gray-500 mt-1">Cross-node active tick average</div>
        </GlassPanel>

        <GlassPanel className="stat-card" animate={false}>
          <div className="flex items-center justify-between mb-2">
            <span className="text-xs text-gray-400 uppercase font-semibold">Avg Latency</span>
            <Clock size={16} className="text-cyan-400" />
          </div>
          <div className="text-2xl font-bold font-mono text-white">{averageLatency.toFixed(1)} ms</div>
          <div className="text-[10px] text-gray-500 mt-1">Network transit time</div>
        </GlassPanel>

        <GlassPanel className="stat-card" animate={false}>
          <div className="flex items-center justify-between mb-2">
            <span className="text-xs text-gray-400 uppercase font-semibold">Total Packet Loss</span>
            <Activity size={16} className="text-cyan-400" />
          </div>
          <div className="text-2xl font-bold font-mono text-white">{(totalLoss * 100).toFixed(2)}%</div>
          <div className="text-[10px] text-gray-500 mt-1">Sum of active drop ratios</div>
        </GlassPanel>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 mb-6">
        <GlassPanel className="lg:col-span-2 flex flex-col justify-between" animate={false}>
          <div>
            <h2 className="text-lg font-bold mb-1 flex items-center gap-2" style={{ fontFamily: 'Orbitron, sans-serif' }}>
              <TrendingUp size={18} className="text-cyan-400" /> Live Ingest Metrics Timeline
            </h2>
            <p className="text-xs text-gray-500 mb-6">Scrolling view of average CPU load and latency over the last 15 ingestion ticks</p>
          </div>
          
          <div className="h-64 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={chartData} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                <defs>
                  <linearGradient id="colorCpu" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#06b6d4" stopOpacity={0.4}/>
                    <stop offset="95%" stopColor="#06b6d4" stopOpacity={0.0}/>
                  </linearGradient>
                  <linearGradient id="colorLatency" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#3b82f6" stopOpacity={0.4}/>
                    <stop offset="95%" stopColor="#3b82f6" stopOpacity={0.0}/>
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.04)" />
                <XAxis dataKey="time" stroke="rgba(255,255,255,0.4)" tick={{ fontSize: 9 }} />
                <YAxis stroke="rgba(255,255,255,0.4)" tick={{ fontSize: 9 }} />
                <Tooltip contentStyle={{ backgroundColor: '#0c1220', border: '1px solid rgba(0, 229, 255, 0.15)', borderRadius: '8px' }} />
                <Area type="monotone" dataKey="Avg CPU (%)" stroke="#06b6d4" fillOpacity={1} fill="url(#colorCpu)" />
                <Area type="monotone" dataKey="Avg Latency (ms)" stroke="#3b82f6" fillOpacity={1} fill="url(#colorLatency)" />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </GlassPanel>

        <GlassPanel className="flex flex-col h-full justify-between" animate={false}>
          <div className="flex items-center justify-between mb-4 border-b border-white-5 pb-3">
            <div className="flex items-center gap-2">
              <Terminal size={18} className="text-cyan-400" />
              <h2 className="text-md font-bold" style={{ fontFamily: 'Orbitron, sans-serif' }}>Raw Console Stream</h2>
            </div>
            
            <div className="flex items-center gap-1.5">
              <button 
                onClick={() => setIsPaused(!isPaused)} 
                className="p-1 hover:bg-slate-900 border border-white-5 rounded transition-all text-gray-400 hover:text-white"
                title={isPaused ? 'Resume Feed' : 'Pause Feed'}
              >
                {isPaused ? <Play size={12} /> : <Pause size={12} />}
              </button>
              <button 
                onClick={handleClearLogs} 
                className="p-1 hover:bg-slate-900 border border-white-5 rounded transition-all text-gray-400 hover:text-red-400"
                title="Clear logs"
              >
                <Trash2 size={12} />
              </button>
            </div>
          </div>

          <div className="terminal-container bg-slate-950 border border-white-5 rounded-lg p-3 font-mono text-[10px] overflow-y-auto flex-grow h-60 flex flex-col gap-1 text-emerald-400">
            {filteredLogs.length === 0 ? (
              <div className="text-gray-500 italic text-center my-auto">Waiting for telemetry frames...</div>
            ) : (
              filteredLogs.map((log, index) => (
                <div key={index} className="log-line">
                  <span className="text-cyan-500">[{new Date(log.timestamp).toLocaleTimeString()}]</span>{' '}
                  <span className="text-yellow-500 font-semibold">INGEST</span>{' '}
                  <span>node=</span><span className="text-white font-semibold">{log.node_id}</span>{' '}
                  <span>cpu=</span><span>{log.cpu}%</span>{' '}
                  <span>latency=</span><span>{log.latency_ms}ms</span>{' '}
                  <span>loss=</span><span>{(log.packet_loss * 100).toFixed(1)}%</span>{' '}
                  <span>src=</span><span className="text-blue-400">{log.source || dataMode}</span>
                </div>
              ))
            )}
            <div ref={terminalEndRef} />
          </div>

          <div className="flex items-center gap-2 mt-4 pt-3 border-t border-white-5">
            <span className="text-[10px] text-gray-500 uppercase font-mono">Filter Node:</span>
            <select 
              value={filterNode} 
              onChange={(e) => setFilterNode(e.target.value)}
              className="bg-slate-900 border border-white-5 rounded text-[10px] px-2 py-1 text-gray-300 font-mono flex-grow focus:outline-none focus:border-cyan-500"
            >
              <option value="all">ALL NODES</option>
              {uniqueNodes.map(node => (
                <option key={node} value={node}>{node}</option>
              ))}
            </select>
          </div>
        </GlassPanel>
      </div>

      <GlassPanel animate={false}>
        <div className="flex items-center justify-between mb-4">
          <div>
            <h2 className="text-lg font-bold" style={{ fontFamily: 'Orbitron, sans-serif' }}>Ingested Telemetry Grid</h2>
            <p className="text-xs text-gray-500">Raw fields unpacked from the websocket telemetry frames</p>
          </div>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs text-gray-400">
            <thead className="bg-slate-950 text-gray-300 uppercase font-mono text-[10px] border-b border-white-5">
              <tr>
                <th className="p-3">Timestamp</th>
                <th className="p-3">Node ID</th>
                <th className="p-3">Type</th>
                <th className="p-3">Slice</th>
                <th className="p-3">CPU (%)</th>
                <th className="p-3">Memory (%)</th>
                <th className="p-3">Latency (ms)</th>
                <th className="p-3">Packet Loss</th>
                <th className="p-3">Throughput (Mbps)</th>
                <th className="p-3">Source</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white-5 font-mono">
              {latestFrames.length === 0 ? (
                <tr>
                  <td colSpan="10" className="p-8 text-center text-gray-500 italic">No telemetry data available</td>
                </tr>
              ) : (
                latestFrames.map((frame, index) => (
                  <tr key={index} className="hover:bg-slate-900/30 transition-all">
                    <td className="p-3 text-gray-500">{new Date(frame.timestamp).toLocaleTimeString()}</td>
                    <td className="p-3 text-white font-semibold">{frame.node_id}</td>
                    <td className="p-3 text-cyan-400">{frame.node_type}</td>
                    <td className="p-3 text-purple-400">{frame.slice_id}</td>
                    <td className="p-3">
                      <div className="flex items-center gap-2">
                        <span>{frame.cpu}%</span>
                        <div className="w-16 bg-slate-950 h-1.5 rounded-full overflow-hidden border border-white-5">
                          <div className="bg-cyan-500 h-full" style={{ width: `${frame.cpu}%` }} />
                        </div>
                      </div>
                    </td>
                    <td className="p-3">
                      <div className="flex items-center gap-2">
                        <span>{frame.memory}%</span>
                        <div className="w-16 bg-slate-950 h-1.5 rounded-full overflow-hidden border border-white-5">
                          <div className="bg-blue-500 h-full" style={{ width: `${frame.memory}%` }} />
                        </div>
                      </div>
                    </td>
                    <td className="p-3 text-white">{frame.latency_ms} ms</td>
                    <td className="p-3 text-amber-500">{(frame.packet_loss * 100).toFixed(2)}%</td>
                    <td className="p-3 text-emerald-400">{frame.throughput_mbps} Mbps</td>
                    <td className="p-3 text-gray-500 capitalize">{frame.source || dataMode}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </GlassPanel>
    </div>
  );
}
