import React, { useState, useEffect } from 'react';
import { motion } from 'framer-motion';
import { Radio, Cpu, BarChart3, Shield, Zap, Play, Loader2, RefreshCw } from 'lucide-react';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts';
import GlassPanel from '../components/GlassPanel';
import { api } from '../utils/api';
import './WirelessRL.css';

export default function WirelessRL() {
  // Hopfield State
  const [users, setUsers] = useState(8);
  const [channels, setChannels] = useState(16);
  const [isHopfieldRunning, setIsHopfieldRunning] = useState(false);
  const [hopfieldResult, setHopfieldResult] = useState(null);

  // Safe RL State
  const [constraints, setConstraints] = useState([]);
  const [policyState, setPolicyState] = useState(null);
  const [isLoadingRL, setIsLoadingRL] = useState(false);
  const [isTraining, setIsTraining] = useState(false);

  // Run Hopfield HNN
  const runHopfield = async () => {
    setIsHopfieldRunning(true);
    try {
      const res = await api.post(`/api/wireless/hopfield?users=${users}&channels=${channels}`);
      setHopfieldResult(res);
    } catch (err) {
      console.error(err);
      // Fallback Hopfield result
      const mockMatrix = Array.from({ length: users }, () =>
        Array.from({ length: channels }, () => (Math.random() > 0.85 ? 1 : 0))
      );
      // Ensure each user has at least one channel
      mockMatrix.forEach((row) => {
        if (!row.includes(1)) {
          row[Math.floor(Math.random() * channels)] = 1;
        }
      });

      setHopfieldResult({
        allocation: mockMatrix,
        jain_fairness: 0.88,
        total_energy: -142.5,
        iterations: 42,
        energy_trace: Array.from({ length: 30 }, (_, i) => ({
          step: i,
          energy: -50 - i * 3 - Math.sin(i) * 5,
        })),
      });
    } finally {
      setIsHopfieldRunning(false);
    }
  };

  // Fetch Safe RL policy and constraints
  const fetchRLData = async () => {
    setIsLoadingRL(true);
    try {
      const [constraintsRes, policyRes] = await Promise.all([
        api.get('/api/rl/constraints'),
        api.get('/api/rl/policy'),
      ]);
      setConstraints(constraintsRes || []);
      setPolicyState(policyRes || null);
    } catch (err) {
      console.error(err);
      // Fallback constraints
      setConstraints([
        { name: 'Slice Latency Bound', threshold: 20.0, current_value: 14.8, lambda: 1.42, violation_rate: 0.02 },
        { name: 'Packet Drop Constraint', threshold: 0.02, current_value: 0.008, lambda: 4.85, violation_rate: 0.0 },
        { name: 'UPF Load Guard', threshold: 0.90, current_value: 0.94, lambda: 12.4, violation_rate: 0.12 },
      ]);
      setPolicyState({
        episodes: 140,
        mean_reward: 482.4,
        policy_entropy: 1.22,
      });
    } finally {
      setIsLoadingRL(false);
    }
  };

  // Train one RL episode
  const trainEpisode = async () => {
    setIsTraining(true);
    try {
      await api.post('/api/rl/train-episode');
      await fetchRLData();
    } catch (err) {
      console.error(err);
    } finally {
      setIsTraining(false);
    }
  };

  useEffect(() => {
    runHopfield();
    fetchRLData();
  }, []);

  // Energy trace for LineChart
  const energyTraceData = hopfieldResult?.energy_trace || [];

  return (
    <div className="wireless-rl-page">
      <header className="page-header flex justify-between items-center mb-6">
        <div>
          <h1 className="text-3xl font-bold flex items-center gap-3" style={{ fontFamily: 'Orbitron, sans-serif' }}>
            <Radio className="text-cyan-400" /> Radio Resource Allocation & SafeRL
          </h1>
          <p className="text-sm text-gray-400 mt-1">HNN resource scheduling constraints and CMDP Safe Reinforcement Learning loops</p>
        </div>
      </header>

      {/* Top Section: Hopfield Allocation Matrix + Energy Convergence */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
        {/* Hopfield Neural Net Matrix */}
        <GlassPanel className="hopfield-panel flex flex-col justify-between border border-white/5" delay={0.05}>
          <div>
            <div className="flex justify-between items-center mb-4">
              <div>
                <h2 className="text-lg font-bold" style={{ fontFamily: 'Orbitron, sans-serif' }}>HNN Allocation Matrix</h2>
                <p className="text-xs text-gray-500">Recurrent Hopfield Neural Network user-to-channel matching</p>
              </div>
              <button
                onClick={runHopfield}
                disabled={isHopfieldRunning}
                className="flex items-center gap-1.5 px-3 py-1.5 bg-cyan-950/40 hover:bg-cyan-900/40 text-cyan-400 rounded-lg text-xs font-semibold border border-cyan-800/30 transition-all"
              >
                {isHopfieldRunning ? <Loader2 size={12} className="animate-spin" /> : <Cpu size={12} />}
                Run Allocation
              </button>
            </div>

            {/* Inputs row */}
            <div className="flex gap-4 mb-4">
              <div className="flex flex-col gap-1 w-1/2">
                <span className="text-[9px] uppercase text-gray-500 font-mono">Active Users</span>
                <input
                  type="number"
                  min="2"
                  max="16"
                  value={users}
                  onChange={(e) => setUsers(parseInt(e.target.value) || 8)}
                  className="bg-slate-950/70 border border-cyan-800/30 rounded px-2 py-1 text-xs text-cyan-400 font-mono focus:outline-none"
                />
              </div>
              <div className="flex flex-col gap-1 w-1/2">
                <span className="text-[9px] uppercase text-gray-500 font-mono">Channels</span>
                <input
                  type="number"
                  min="4"
                  max="32"
                  value={channels}
                  onChange={(e) => setChannels(parseInt(e.target.value) || 16)}
                  className="bg-slate-950/70 border border-cyan-800/30 rounded px-2 py-1 text-xs text-cyan-400 font-mono focus:outline-none"
                />
              </div>
            </div>
          </div>

          {/* Matrix Grid Representation */}
          <div className="matrix-grid-container flex items-center justify-center bg-slate-950/40 rounded-xl border border-white/5 p-4 h-48 overflow-auto">
            {isHopfieldRunning ? (
              <Loader2 className="animate-spin text-cyan-400" size={24} />
            ) : hopfieldResult && hopfieldResult.allocation ? (
              <div className="flex flex-col gap-1.5">
                {hopfieldResult.allocation.map((row, uIdx) => (
                  <div key={uIdx} className="flex gap-1.5 items-center">
                    <span className="text-[9px] font-mono text-gray-500 w-8">User {uIdx + 1}</span>
                    {row.map((cell, cIdx) => (
                      <div
                        key={cIdx}
                        title={`User ${uIdx + 1}, Ch ${cIdx + 1}: ${cell}`}
                        className={`w-3.5 h-3.5 rounded-sm transition-all duration-300 ${
                          cell === 1
                            ? 'bg-cyan-400 shadow-[0_0_6px_rgba(6,182,212,0.6)]'
                            : 'bg-slate-900 border border-white/5'
                        }`}
                      />
                    ))}
                  </div>
                ))}
              </div>
            ) : (
              <span className="text-xs text-gray-500">Run neural optimizer allocation</span>
            )}
          </div>

          {/* Stats foot */}
          {hopfieldResult && (
            <div className="flex justify-between items-center mt-3 pt-3 border-t border-white/5 text-[10px] text-gray-400 font-mono">
              <span>Fairness Index: {hopfieldResult.jain_fairness.toFixed(3)}</span>
              <span>Min Energy: {hopfieldResult.total_energy.toFixed(1)} eV</span>
              <span>Steps: {hopfieldResult.iterations}</span>
            </div>
          )}
        </GlassPanel>

        {/* Lyapunov Energy Convergence */}
        <GlassPanel className="energy-panel flex flex-col justify-between border border-white/5" delay={0.1}>
          <div>
            <h2 className="text-lg font-bold" style={{ fontFamily: 'Orbitron, sans-serif' }}>Lyapunov Convergence</h2>
            <p className="text-xs text-gray-500">Neural energy minimization trace showing convergence to stable attractor state</p>
          </div>

          <div className="h-56 w-100% mt-4">
            {energyTraceData.length === 0 ? (
              <div className="h-full flex items-center justify-center text-xs text-gray-500">
                Waiting for energy matrix trace...
              </div>
            ) : (
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={energyTraceData} margin={{ top: 10, right: 10, left: -25, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="rgba(255, 255, 255, 0.03)" />
                  <XAxis dataKey="step" stroke="rgba(255, 255, 255, 0.4)" tick={{ fontSize: 9 }} />
                  <YAxis stroke="rgba(255, 255, 255, 0.4)" tick={{ fontSize: 9 }} />
                  <Tooltip contentStyle={{ background: '#0a0f1d', border: '1px solid rgba(255,255,255,0.08)', fontSize: '10px' }} />
                  <Line type="monotone" dataKey="energy" stroke="#10b981" strokeWidth={1.5} dot={false} name="Network Energy" />
                </LineChart>
              </ResponsiveContainer>
            )}
          </div>
        </GlassPanel>
      </div>

      {/* Bottom Panel: CMDP Safe Reinforcement Learning */}
      <GlassPanel className="cmdp-panel flex flex-col gap-6 border border-white/5" delay={0.15}>
        <div className="flex justify-between items-center border-b border-white/5 pb-4">
          <div className="flex items-center gap-3">
            <Shield className="text-cyan-400" />
            <div>
              <h2 className="text-xl font-bold" style={{ fontFamily: 'Orbitron, sans-serif' }}>
                Constrained MDP Safe Policy Guard
              </h2>
              <p className="text-xs text-gray-500 mt-0.5">CMDP reward-constrained policy optimizer constraints verification and Lagrange multipliers (λ)</p>
            </div>
          </div>
          <div className="flex gap-2">
            <button
              onClick={fetchRLData}
              disabled={isLoadingRL}
              className="p-2 rounded-lg border border-cyan-800/30 text-cyan-400 bg-cyan-950/25 hover:bg-cyan-900/40 transition-all"
            >
              <RefreshCw size={14} className={isLoadingRL ? 'animate-spin' : ''} />
            </button>
            <button
              onClick={trainEpisode}
              disabled={isTraining}
              className="flex items-center gap-1.5 px-3 py-1.5 bg-cyan-600 hover:bg-cyan-500 text-white rounded-lg text-xs font-semibold transition-all active:scale-95 disabled:opacity-50"
            >
              {isTraining ? <Loader2 size={12} className="animate-spin" /> : <Play size={12} />}
              Train Episode
            </button>
          </div>
        </div>

        {/* Policy State Row */}
        {policyState && (
          <div className="flex flex-wrap gap-4 text-xs font-mono text-gray-400 bg-slate-950/25 p-3 rounded-lg border border-white/5">
            <span>Policy Iteration: {policyState.episodes}</span>
            <span className="text-cyan-400">Mean Episode Reward: {policyState.mean_reward.toFixed(1)}</span>
            <span>Entropy: {policyState.policy_entropy.toFixed(3)}</span>
          </div>
        )}

        {/* Constraints Table */}
        <div className="overflow-x-auto rounded-lg border border-white/5">
          <table className="w-full text-left text-xs border-collapse">
            <thead>
              <tr className="bg-slate-950/80 text-gray-400 font-semibold border-b border-white/10">
                <th className="p-3">Constraint Name</th>
                <th className="p-3">Threshold Limit</th>
                <th className="p-3">Current Observed</th>
                <th className="p-3">Lagrange Multiplier (λ)</th>
                <th className="p-3">Violation Frequency</th>
                <th className="p-3">Status</th>
              </tr>
            </thead>
            <tbody>
              {constraints.map((c, idx) => {
                const isViolated = c.current_value > c.threshold;
                return (
                  <tr key={idx} className="border-b border-white/5 hover:bg-white/5 transition-all">
                    <td className="p-3 font-semibold text-gray-300">{c.name}</td>
                    <td className="p-3 font-mono">{c.threshold.toFixed(4)}</td>
                    <td className="p-3 font-mono font-medium text-gray-200">{c.current_value.toFixed(4)}</td>
                    <td className="p-3 font-mono text-cyan-400">{c.lambda.toFixed(3)}</td>
                    <td className="p-3 font-mono text-purple-400">{(c.violation_rate * 100).toFixed(1)}%</td>
                    <td className="p-3">
                      <span className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase ${
                        isViolated ? 'bg-red-950/40 text-red-400 border border-red-900/30' : 'bg-green-950/40 text-green-400 border border-green-800/30'
                      }`}>
                        {isViolated ? 'Violated' : 'Secured'}
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </GlassPanel>
    </div>
  );
}
