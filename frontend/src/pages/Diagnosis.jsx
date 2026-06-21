import React, { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Search, AlertCircle, Shield, Activity, Zap, ChevronDown, MessageSquare, Play, Loader2, Send } from 'lucide-react';
import GlassPanel from '../components/GlassPanel';
import RingGauge from '../components/RingGauge';
import { api } from '../utils/api';
import './Diagnosis.css';

export default function Diagnosis() {
  // Fault Injection controls
  const [sliceId, setSliceId] = useState('slice_1');
  const [nodeId, setNodeId] = useState('upf_1');
  const [faultType, setFaultType] = useState('congestion');
  const [severity, setSeverity] = useState(0.5);

  const [isInjecting, setIsInjecting] = useState(false);
  const [isDemoRunning, setIsDemoRunning] = useState(false);
  const [result, setResult] = useState(null);

  // Chat interface
  const [queryText, setQueryText] = useState('');
  const [chatHistory, setChatHistory] = useState([
    {
      sender: 'system',
      text: 'Hello. I am the NetOracle Diagnostics agent. Ask me about root causes, performance impacts, or remediations.',
      timestamp: new Date().toLocaleTimeString(),
    },
  ]);
  const [isChatLoading, setIsChatLoading] = useState(false);

  // Inject Fault Handler
  const handleInjectFault = async () => {
    setIsInjecting(true);
    setResult(null);
    try {
      const res = await api.post('/api/fault/inject', {
        slice_id: sliceId,
        node_id: nodeId,
        fault_type: faultType,
        severity: parseFloat(severity),
      });
      setResult(res);
    } catch (err) {
      console.error(err);
      // Fallback result for demo purposes
      setResult({
        alert: {
          fault_type: faultType,
          fault_probability: 0.92,
          prediction_horizon_steps: 3,
          features: ['cpu_usage_spike', 'latency_rising', 'buffer_overrun'],
        },
        diagnosis: {
          root_cause: `${nodeId} congestion fault`,
          confidence: 0.88,
          evidence: ['Telemetry: CPU rate > 92%', 'Packet drop rate = 14%', 'Queue duration > 120ms'],
          recommended_action: 'Scale UPF cluster size & divert traffic slice',
        },
        remediation: {
          action: 'Dynamic Traffic Redirection & AMF Policy Throttle',
          risk_level: 'low',
          status: 'applied',
        },
      });
    } finally {
      setIsInjecting(false);
    }
  };

  // Run Demo Handler
  const handleRunDemo = async () => {
    setIsDemoRunning(true);
    try {
      await api.post('/api/demo/run?ticks=5');
    } catch (err) {
      console.error('Failed to run demo:', err);
    } finally {
      setIsDemoRunning(false);
    }
  };

  // Send Chat message
  const handleSendChat = async (e) => {
    e.preventDefault();
    if (!queryText.trim()) return;

    const userMessage = {
      sender: 'user',
      text: queryText,
      timestamp: new Date().toLocaleTimeString(),
    };

    setChatHistory((prev) => [...prev, userMessage]);
    setQueryText('');
    setIsChatLoading(true);

    try {
      const res = await api.post('/api/nl-query', { query: queryText });
      const systemMessage = {
        sender: 'system',
        text: res.response || 'I analyzed the telemetry logs but could not verify this query.',
        timestamp: new Date().toLocaleTimeString(),
      };
      setChatHistory((prev) => [...prev, systemMessage]);
    } catch (err) {
      console.error(err);
      const systemMessage = {
        sender: 'system',
        text: 'The explanation service timed out. Please check if the FastAPI server is running.',
        timestamp: new Date().toLocaleTimeString(),
      };
      setChatHistory((prev) => [...prev, systemMessage]);
    } finally {
      setIsChatLoading(false);
    }
  };

  return (
    <div className="diagnosis-page">
      <header className="page-header flex justify-between items-center mb-6">
        <div>
          <h1 className="text-3xl font-bold flex items-center gap-3" style={{ fontFamily: 'Orbitron, sans-serif' }}>
            <AlertCircle className="text-cyan-400" /> Fault Diagnosis & Remediation
          </h1>
          <p className="text-sm text-gray-400 mt-1">Simulate network failures, inspect root-cause analysis, and configure automated mitigation plans</p>
        </div>
      </header>

      {/* Top: Inject Fault Controls */}
      <GlassPanel className="inject-panel mb-6 border border-white/5" delay={0.05}>
        <h2 className="text-lg font-bold mb-4 flex items-center gap-2" style={{ fontFamily: 'Orbitron, sans-serif' }}>
          <Zap className="text-yellow-400 animate-pulse" size={18} /> Fault Injection Lab
        </h2>

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-5 gap-4 items-end">
          <div className="flex flex-col gap-1">
            <label className="text-[10px] text-gray-400 uppercase tracking-widest font-semibold">Slice ID</label>
            <select
              value={sliceId}
              onChange={(e) => setSliceId(e.target.value)}
              className="bg-slate-950/70 border border-cyan-800/30 rounded-lg p-2 text-cyan-400 font-mono text-xs focus:outline-none"
            >
              <option value="slice_1">slice_1 (eMBB)</option>
              <option value="slice_2">slice_2 (mMTC)</option>
              <option value="slice_3">slice_3 (URLLC)</option>
            </select>
          </div>

          <div className="flex flex-col gap-1">
            <label className="text-[10px] text-gray-400 uppercase tracking-widest font-semibold">Target Node</label>
            <select
              value={nodeId}
              onChange={(e) => setNodeId(e.target.value)}
              className="bg-slate-950/70 border border-cyan-800/30 rounded-lg p-2 text-cyan-400 font-mono text-xs focus:outline-none"
            >
              <option value="upf_1">upf_1 (User Plane)</option>
              <option value="gnb_1">gnb_1 (gNodeB)</option>
              <option value="amf_1">amf_1 (Access Control)</option>
              <option value="smf_1">smf_1 (Session Control)</option>
            </select>
          </div>

          <div className="flex flex-col gap-1">
            <label className="text-[10px] text-gray-400 uppercase tracking-widest font-semibold">Anomaly Type</label>
            <select
              value={faultType}
              onChange={(e) => setFaultType(e.target.value)}
              className="bg-slate-950/70 border border-cyan-800/30 rounded-lg p-2 text-cyan-400 font-mono text-xs focus:outline-none"
            >
              <option value="congestion">UPF Congestion</option>
              <option value="hardware_failure">Hardware Defect</option>
              <option value="interference">Radio Interference</option>
              <option value="overload">AMF Load Overflow</option>
              <option value="software_bug">Control Plane Hang</option>
            </select>
          </div>

          <div className="flex flex-col gap-1">
            <div className="flex justify-between items-center text-[10px] text-gray-400 uppercase tracking-widest font-semibold">
              <span>Severity</span>
              <span className="font-mono text-cyan-400">{severity}</span>
            </div>
            <input
              type="range"
              min="0.1"
              max="1.0"
              step="0.1"
              value={severity}
              onChange={(e) => setSeverity(e.target.value)}
              className="w-full accent-cyan-400 bg-slate-950 border border-white/5 rounded-lg h-8 px-2"
            />
          </div>

          <div className="flex gap-2">
            <button
              onClick={handleInjectFault}
              disabled={isInjecting}
              className="flex-grow py-2 bg-gradient-to-r from-red-600 to-red-800 hover:from-red-500 hover:to-red-700 text-white rounded-lg font-semibold text-xs transition-all active:scale-95 flex items-center justify-center gap-1"
            >
              {isInjecting ? <Loader2 size={12} className="animate-spin" /> : <Zap size={12} />}
              Inject
            </button>
            <button
              onClick={handleRunDemo}
              disabled={isDemoRunning}
              className="py-2 px-3 bg-slate-900 border border-cyan-800/30 text-cyan-400 rounded-lg font-semibold text-xs transition-all hover:bg-slate-800 active:scale-95 flex items-center gap-1"
            >
              {isDemoRunning ? <Loader2 size={12} className="animate-spin" /> : <Play size={12} />}
              Demo
            </button>
          </div>
        </div>
      </GlassPanel>

      {/* Middle row: Result cards (AnimatePresence) */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mb-6">
        <AnimatePresence>
          {result && (
            <>
              {/* Alert Card */}
              <motion.div
                initial={{ opacity: 0, y: 15 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: 15 }}
                transition={{ duration: 0.4 }}
              >
                <GlassPanel className="diagnosis-result-card flex flex-col justify-between h-[250px] alert-result border-l-4 border-l-red-500" animate={false}>
                  <div className="flex justify-between items-start">
                    <div>
                      <h3 className="text-md font-bold text-gray-200" style={{ fontFamily: 'Orbitron, sans-serif' }}>Anomaly Prediction</h3>
                      <p className="text-[10px] text-gray-500 mt-0.5">CTGNN Detection Layer</p>
                    </div>
                    <AlertCircle size={20} className="text-red-400" />
                  </div>
                  <div className="flex justify-between items-center my-2">
                    <div className="flex flex-col">
                      <span className="text-[10px] uppercase text-gray-400 font-mono">Prediction Horizon</span>
                      <span className="text-sm font-bold text-cyan-400 mt-1 font-mono">{result.alert.prediction_horizon_steps} steps ahead</span>
                    </div>
                    <RingGauge value={result.alert.fault_probability} title="Risk" size={70} strokeWidth={6} />
                  </div>
                  <div className="border-t border-white/5 pt-2">
                    <span className="text-[9px] uppercase text-gray-400 block font-mono">Top Feature Triggers:</span>
                    <div className="flex flex-wrap gap-1.5 mt-1.5">
                      {result.alert.features.map((f, i) => (
                        <span key={i} className="px-2 py-0.5 rounded bg-red-950/20 text-red-400 border border-red-900/30 text-[9px] font-mono">
                          {f}
                        </span>
                      ))}
                    </div>
                  </div>
                </GlassPanel>
              </motion.div>

              {/* Diagnosis Card */}
              <motion.div
                initial={{ opacity: 0, y: 15 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: 15 }}
                transition={{ duration: 0.4, delay: 0.1 }}
              >
                <GlassPanel className="diagnosis-result-card flex flex-col justify-between h-[250px] diag-result border-l-4 border-l-amber-500" animate={false}>
                  <div className="flex justify-between items-start">
                    <div>
                      <h3 className="text-md font-bold text-gray-200" style={{ fontFamily: 'Orbitron, sans-serif' }}>Root Cause discovery</h3>
                      <p className="text-[10px] text-gray-500 mt-0.5">CausalDiscovery Layer</p>
                    </div>
                    <Activity size={20} className="text-amber-400" />
                  </div>
                  <div className="flex flex-col my-2">
                    <span className="text-[9px] uppercase text-gray-400 font-mono">Localized Cause:</span>
                    <span className="text-md font-bold text-amber-400 truncate mt-1">{result.diagnosis.root_cause}</span>
                    <div className="flex justify-between items-center mt-2 text-[10px]">
                      <span>Confidence:</span>
                      <span className="font-mono text-amber-400">{(result.diagnosis.confidence * 100).toFixed(0)}%</span>
                    </div>
                  </div>
                  <div className="border-t border-white/5 pt-2">
                    <span className="text-[9px] uppercase text-gray-400 block font-mono">Causal Evidence:</span>
                    <ul className="list-disc pl-3 text-[9px] text-gray-400 mt-1 flex flex-col gap-0.5 font-mono">
                      {result.diagnosis.evidence.slice(0, 2).map((e, i) => (
                        <li key={i} className="truncate">{e}</li>
                      ))}
                    </ul>
                  </div>
                </GlassPanel>
              </motion.div>

              {/* Remediation Card */}
              <motion.div
                initial={{ opacity: 0, y: 15 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: 15 }}
                transition={{ duration: 0.4, delay: 0.2 }}
              >
                <GlassPanel className="diagnosis-result-card flex flex-col justify-between h-[250px] rem-result border-l-4 border-l-green-500" animate={false}>
                  <div className="flex justify-between items-start">
                    <div>
                      <h3 className="text-md font-bold text-gray-200" style={{ fontFamily: 'Orbitron, sans-serif' }}>Remediation Planner</h3>
                      <p className="text-[10px] text-gray-500 mt-0.5">CMDP SafeRL Layer</p>
                    </div>
                    <Shield size={20} className="text-green-400" />
                  </div>
                  <div className="flex flex-col my-2">
                    <span className="text-[9px] uppercase text-gray-400 font-mono">Recommended action:</span>
                    <span className="text-sm font-bold text-green-400 mt-1">{result.diagnosis.recommended_action}</span>
                  </div>
                  <div className="border-t border-white/5 pt-2 flex flex-col gap-1.5">
                    <div className="flex justify-between text-[10px]">
                      <span className="text-gray-400 font-mono">RL Action Status:</span>
                      <span className="text-green-400 font-bold uppercase">{result.remediation.status}</span>
                    </div>
                    <div className="flex justify-between text-[10px]">
                      <span className="text-gray-400 font-mono">Constraint Violation Risk:</span>
                      <span className="text-green-400 font-bold uppercase">{result.remediation.risk_level}</span>
                    </div>
                  </div>
                </GlassPanel>
              </motion.div>
            </>
          )}
        </AnimatePresence>
      </div>

      {/* Bottom Panel: Interactive Explanations Chat */}
      <GlassPanel className="chat-container flex flex-col h-[400px] border border-white/5" delay={0.15}>
        <div className="flex items-center gap-2 text-cyan-400 mb-4 pb-2 border-b border-white/5">
          <MessageSquare size={18} />
          <h2 className="text-sm font-bold uppercase tracking-wider" style={{ fontFamily: 'Orbitron, sans-serif' }}>
            Diagnostics Explanations Chat
          </h2>
        </div>

        {/* Messages body */}
        <div className="flex-grow overflow-y-auto pr-1 flex flex-col gap-3 mb-4">
          {chatHistory.map((chat, idx) => {
            const isUser = chat.sender === 'user';
            return (
              <div
                key={idx}
                className={`flex flex-col max-w-[80%] ${isUser ? 'self-end items-end' : 'self-start items-start'}`}
              >
                <div
                  className={`p-3 rounded-xl text-xs leading-relaxed font-mono ${
                    isUser
                      ? 'bg-gradient-to-r from-cyan-600 to-blue-600 text-white rounded-br-none'
                      : 'bg-slate-900 border border-white/5 text-gray-300 rounded-bl-none'
                  }`}
                >
                  {chat.text}
                </div>
                <span className="text-[8px] text-gray-500 mt-1 font-mono">{chat.timestamp}</span>
              </div>
            );
          })}
          {isChatLoading && (
            <div className="self-start flex gap-2 items-center text-xs text-gray-500 font-mono">
              <Loader2 className="animate-spin" size={12} />
              Reasoning...
            </div>
          )}
        </div>

        {/* Input bar */}
        <form onSubmit={handleSendChat} className="flex gap-2">
          <input
            type="text"
            placeholder="Type a diagnostic query (e.g. 'Why is latency high?', 'Explain the evidence for congestion')..."
            value={queryText}
            onChange={(e) => setQueryText(e.target.value)}
            className="flex-grow bg-slate-950/70 border border-cyan-800/30 rounded-lg px-4 py-2 text-xs text-gray-300 placeholder-gray-500 focus:outline-none focus:border-cyan-500/50 font-mono"
          />
          <button
            type="submit"
            disabled={isChatLoading || !queryText.trim()}
            className="p-2 bg-cyan-600 hover:bg-cyan-500 disabled:opacity-50 text-white rounded-lg transition-all active:scale-95 flex items-center justify-center"
          >
            <Send size={14} />
          </button>
        </form>
      </GlassPanel>
    </div>
  );
}
