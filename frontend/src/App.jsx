import React, { useContext } from 'react';
import { HashRouter as Router, Routes, Route, NavLink } from 'react-router-dom';
import { AppContext, AppProvider } from './context/AppContext';
import Dashboard from './pages/Dashboard';
import CausalAI from './pages/CausalAI';
import Topology from './pages/Topology';
import Diagnosis from './pages/Diagnosis';
import WirelessRL from './pages/WirelessRL';
import AuditTrail from './pages/AuditTrail';
import DataSources from './pages/DataSources';
import ExecutiveProof from './pages/ExecutiveProof';
import {
  LayoutDashboard,
  Brain,
  Network,
  AlertTriangle,
  Radio,
  FileText,
  Database,
  Award,
  Wifi,
  WifiOff,
  Bell,
  Cpu,
  Globe,
} from 'lucide-react';
import './App.css';

function AppContent() {
  const { state } = useContext(AppContext);
  const { isConnected, dataMode, latestAlert } = state;

  // Check if there is an active high-probability alert to show in the global banner
  const hasCriticalAlert = latestAlert && latestAlert.fault_probability > 0.85;

  return (
    <Router>
      <div className="netoracle-app flex h-screen text-slate-100 bg-main-dark font-sans overflow-hidden">
        {/* Global Critical Alert Banner */}
        <AnimatePresence>
          {hasCriticalAlert && (
            <motion.div
              initial={{ y: -60, opacity: 0 }}
              animate={{ y: 0, opacity: 1 }}
              exit={{ y: -60, opacity: 0 }}
              className="absolute top-0 inset-x-0 bg-alert-banner backdrop-blur-md border-b border-red-30 text-red-200 px-6 py-sm z-50 flex items-center justify-between text-xs font-semibold"
            >
              <div className="flex items-center gap-2">
                <AlertTriangle className="text-red-500 animate-bounce" size={16} />
                <span>
                  CRITICAL FAULT DETECTED: {latestAlert.fault_type} on Node{' '}
                  <span className="font-mono text-white">{latestAlert.node_id || latestAlert.node}</span> (Slice{' '}
                  <span className="font-mono text-white">{latestAlert.slice_id || latestAlert.slice}</span>)
                </span>
              </div>
              <div className="flex items-center gap-3">
                <span className="bg-slate-950 border border-white-5 px-2 py-0.5 rounded font-mono">
                  Risk: {(latestAlert.fault_probability * 100).toFixed(0)}%
                </span>
                <span className="text-[10px] text-gray-400">Horizon: {latestAlert.prediction_horizon_steps}s</span>
              </div>
            </motion.div>
          )}
        </AnimatePresence>

        {/* Sidebar Navigation */}
        <aside className="w-sidebar bg-sidebar-dark border-r border-white-5 flex flex-col justify-between p-5 z-10">
          <div className="flex flex-col gap-8">
            {/* Logo */}
            <div className="logo flex items-center gap-3">
              <div className="p-2 bg-slate-950-50 border border-white-5 rounded-xl text-cyan-400">
                <Cpu size={24} className="animate-spin-slow" />
              </div>
              <div>
                <h1 className="text-md font-bold tracking-widest text-white uppercase" style={{ fontFamily: 'Orbitron, sans-serif' }}>
                  NetOracle
                </h1>
                <span className="text-[9px] text-cyan-400 font-mono tracking-wider">5G AIOPS NOC v2.8</span>
              </div>
            </div>

            {/* Menu Link List */}
            <nav className="flex flex-col gap-1.5">
              <NavLink to="/" className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
                <LayoutDashboard size={16} /> Dashboard
              </NavLink>
              <NavLink to="/causal" className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
                <Brain size={16} /> Causal AI
              </NavLink>
              <NavLink to="/topology" className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
                <Network size={16} /> Topology
              </NavLink>
              <a href="/twin" target="_blank" rel="noopener noreferrer" className="nav-item">
                <Globe size={16} className="text-cyan-400" /> 3D Digital Twin
              </a>
              <NavLink to="/diagnosis" className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
                <AlertTriangle size={16} /> Diagnostics
              </NavLink>
              <NavLink to="/wireless" className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
                <Radio size={16} /> Wireless RL
              </NavLink>
              <NavLink to="/audit" className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
                <FileText size={16} /> Audit Trail
              </NavLink>
              <NavLink to="/datasources" className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
                <Database size={16} /> Data Sources
              </NavLink>
              <NavLink to="/proof" className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
                <Award size={16} /> validation
              </NavLink>
            </nav>
          </div>

          {/* Connected state foot */}
          <div className="flex items-center justify-between p-3 rounded-xl bg-slate-950-50 border border-white-5 text-[10px] font-mono">
            <div className="flex items-center gap-1.5">
              {isConnected ? (
                <>
                  <Wifi className="text-green-400" size={12} />
                  <span className="text-green-400">WS Live</span>
                </>
              ) : (
                <>
                  <WifiOff className="text-red-400" size={12} />
                  <span className="text-red-400">Offline</span>
                </>
              )}
            </div>
            <span className="text-gray-500 uppercase tracking-widest">{dataMode}</span>
          </div>
        </aside>

        {/* Main Content Area */}
        <main className="flex-grow p-6 overflow-y-auto relative bg-main-dark flex flex-col justify-start">
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/causal" element={<CausalAI />} />
            <Route path="/topology" element={<Topology />} />
            <Route path="/diagnosis" element={<Diagnosis />} />
            <Route path="/wireless" element={<WirelessRL />} />
            <Route path="/audit" element={<AuditTrail />} />
            <Route path="/datasources" element={<DataSources />} />
            <Route path="/proof" element={<ExecutiveProof />} />
          </Routes>
        </main>
      </div>
    </Router>
  );
}

// Framer motion support helpers
import { AnimatePresence, motion } from 'framer-motion';

export default function App() {
  return (
    <AppProvider>
      <AppContent />
    </AppProvider>
  );
}
