import React, { useState, useEffect } from 'react';
import { motion } from 'framer-motion';
import { FileText, Search, Filter, Download, Clock, ChevronDown, RefreshCw, Loader2, ArrowRight } from 'lucide-react';
import GlassPanel from '../components/GlassPanel';
import { api } from '../utils/api';
import './AuditTrail.css';

export default function AuditTrail() {
  const [events, setEvents] = useState([]);
  const [searchTerm, setSearchTerm] = useState('');
  const [typeFilter, setTypeFilter] = useState('all');
  const [isLoading, setIsLoading] = useState(false);
  const [expandedEvent, setExpandedEvent] = useState(null);

  // Maps backend specific event_type strings to general UI filter categories
  const getUiEventType = (backendType) => {
    const type = backendType || '';
    if (type.includes('predict') || type.includes('forecast') || type.includes('conformal')) {
      return 'prediction';
    }
    if (type.includes('localis') || type.includes('topology') || type.includes('graphrag') || type.includes('cypher')) {
      return 'localization';
    }
    if (type.includes('diagnos') || type.includes('explain') || type.includes('analysis')) {
      return 'diagnosis';
    }
    if (type.includes('remediat') || type.includes('rl_') || type.includes('hopfield') || type.includes('avoidance') || type.includes('decision') || type.includes('fix')) {
      return 'remediation';
    }
    return 'other';
  };

  // Safe details formatter helper to extract user-friendly descriptions from database payloads
  const getEventDetails = (event) => {
    if (event.details) return event.details;
    if (!event.payload) return 'System audit log entry.';
    
    const p = event.payload;
    if (typeof p === 'string') return p;
    if (p.details) return p.details;
    if (p.message) return p.message;
    if (p.reason) return p.reason;
    if (p.description) return p.description;

    const type = event.event_type || '';
    if (type === 'hopfield_allocation') {
      return `HNN allocated ${p.channels} channels to ${p.users} users. Fairness: ${p.fairness_index ?? 'N/A'}`;
    }
    if (type === 'rl_recommendation') {
      return `CMDP recommendation: selected "${p.action}" under state "${p.state}" (strategy: ${p.strategy || 'N/A'})`;
    }
    if (type === 'rl_policy_updated') {
      return `SafeRL updated Q-value for state "${p.state}", action "${p.action}". New Q: ${p.new_value}`;
    }
    if (type === 'fault_predicted') {
      return `CTGNN Alert: Predicted ${p.fault_type} on node ${p.node_id} (Risk: ${((p.fault_probability || 0) * 100).toFixed(0)}%)`;
    }
    if (type === 'fault_diagnosed') {
      return `RAG root cause: "${p.root_cause}" (Confidence: ${((p.confidence || 0) * 100).toFixed(0)}%)`;
    }
    if (type === 'fault_localised') {
      return `CausalDiscovery path trace for node ${p.node_id} (Alert ID: ${p.alert_id || 'N/A'})`;
    }
    if (type === 'conformal_aci_update') {
      return `Conformal prediction recalibrated: q_hat = ${p.new_q_hat ?? p.q_hat ?? 'N/A'} (coverage: ${p.running_coverage ? `${(p.running_coverage * 100).toFixed(0)}%` : 'N/A'})`;
    }
    if (type === 'telemetry_tick') {
      return `Telemetry ingestion: processed ${p.frames ?? 0} frames from source "${p.source || 'N/A'}"`;
    }
    if (type === 'topology_seeded') {
      return `Topology database seeded: ${p.nodes} nodes, ${p.edges} edges`;
    }
    if (type === 'remediation_decision') {
      return `Remediation executed: "${p.action}" on node ${p.node_id || 'N/A'}. Status: ${p.status || 'applied'}`;
    }
    if (type === 'realtime_fault_analysis') {
      if (p.alert) {
        return `Real-time anomaly detected on ${p.alert.node_id} (${p.alert.fault_type}, Risk: ${((p.alert.fault_probability || 0) * 100).toFixed(0)}%). Quick fix: "${p.quick_fix?.action || 'None'}".`;
      }
      if (p.quick_fix) {
        return `Proactive alert on ${p.quick_fix.node_id}. Quick fix recommended: "${p.quick_fix.action}".`;
      }
      return `Real-time network state analyzed. No active faults or alerts.`;
    }
    if (type === 'fix_simulation') {
      return `Simulated remediation "${p.action}" on node ${p.node_id} reduced fault risk by ${((p.risk_reduction || 0) * 100).toFixed(0)}%.`;
    }
    if (type === 'proactive_forecast') {
      if (p.top) {
        return `Proactive forecast for ${p.top.node_id} on ${p.top.slice_id}: SLA anomaly projected in ${p.top.predicted_breach_time_min ?? 'N/A'} mins (Risk: ${((p.top.risk_t_plus_10 || 0) * 100).toFixed(0)}%). Recommended action: "${p.top.recommended_action}".`;
      }
      return `Proactive forecast generated. No high-risk SLA anomalies detected across slices.`;
    }
    if (type === 'open5gs_demo_analysis') {
      return `Open5GS analysis: processed ${p.frame_count ?? 0} frames. Quick fix action: "${p.quick_fix?.action || 'None'}".`;
    }
    if (type === 'graphrag_ingestion') {
      return `GraphRAG Ingestion: added ${p.nodes_added} nodes, ${p.edges_added} edges from LLM relationships extraction.`;
    }
    if (type === 'explain_tab') {
      return `Explainability request for tab "${p.tab}" (Node: ${p.node_id || 'N/A'}). Summary: "${p.headline}".`;
    }
    if (type === 'nl_to_cypher') {
      return `GraphRAG chatbot query: "${p.question}" (method: ${p.method}, confidence: ${p.confidence}).`;
    }
    if (type === 'telemetry_uploaded') {
      return `Telemetry uploaded: file "${p.filename}" containing ${p.frames} telemetry ticks.`;
    }
    if (type === 'topology_uploaded') {
      return `Topology uploaded: file "${p.filename}" containing ${p.nodes} nodes, ${p.edges} edges.`;
    }
    if (type === 'synthetic_generation') {
      return `Synthetic telemetry generation: created ${p.loaded_rows} ticks. Output: "${p.output}".`;
    }

    try {
      const keys = Object.keys(p).slice(0, 3).join(', ');
      return `Payload contains keys: [${keys}]`;
    } catch (e) {
      return 'Audited event payload.';
    }
  };

  const fetchAuditEvents = async () => {
    setIsLoading(true);
    try {
      const data = await api.get('/api/audit?limit=100');
      if (Array.isArray(data)) {
        setEvents(data);
      } else {
        // Fallback demo events
        setEvents([
          { timestamp: '2026-06-21T15:20:10.000Z', event_type: 'prediction', details: 'GNN predicted fault probability of 0.92' },
          { timestamp: '2026-06-21T15:20:12.000Z', event_type: 'localization', details: 'Root cause discovered at upf_1' },
          { timestamp: '2026-06-21T15:20:14.000Z', event_type: 'diagnosis', details: 'Cause: hardware packet buffer overload. Recommend traffic routing AMF throttling' },
          { timestamp: '2026-06-21T15:20:16.000Z', event_type: 'remediation', details: 'Safe RL selected AMF Throttle. Applied control rule successfully.' },
          { timestamp: '2026-06-21T15:25:00.000Z', event_type: 'prediction', details: 'Conformal bounds validated. Risk under threshold (0.12)' },
        ]);
      }
    } catch (err) {
      console.error(err);
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchAuditEvents();
  }, []);

  // Filter events based on search term and dropdown filter
  const filteredEvents = events.filter((event) => {
    const details = getEventDetails(event);
    const eventType = event.event_type || '';
    const uiType = getUiEventType(eventType);

    const matchesSearch =
      details.toLowerCase().includes(searchTerm.toLowerCase()) ||
      eventType.toLowerCase().includes(searchTerm.toLowerCase()) ||
      uiType.toLowerCase().includes(searchTerm.toLowerCase());

    const matchesType = typeFilter === 'all' || uiType === typeFilter;
    return matchesSearch && matchesType;
  });

  const handleExport = () => {
    const dataStr = JSON.stringify(events, null, 2);
    const blob = new Blob([dataStr], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `netoracle-audit-trail-${new Date().toISOString().slice(0, 10)}.json`;
    link.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="audit-trail-page">
      <header className="page-header flex justify-between items-center mb-6">
        <div>
          <h1 className="text-3xl font-bold flex items-center gap-3" style={{ fontFamily: 'Orbitron, sans-serif' }}>
            <FileText className="text-cyan-400" /> Immutable Audit Trail
          </h1>
          <p className="text-sm text-gray-400 mt-1">Immutable execution logs of GNN predictions, Causal localization discovery, and Safe RL mitigations</p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={fetchAuditEvents}
            disabled={isLoading}
            className="p-2 bg-slate-900 border border-cyan-800/30 text-cyan-400 rounded-lg hover:bg-slate-800 transition-all"
          >
            {isLoading ? <Loader2 size={16} className="animate-spin" /> : <RefreshCw size={16} />}
          </button>
          <button
            onClick={handleExport}
            className="flex items-center gap-1.5 px-3 py-1.5 bg-cyan-600 hover:bg-cyan-500 text-white rounded-lg text-xs font-semibold transition-all active:scale-95"
          >
            <Download size={14} /> Export Logs
          </button>
        </div>
      </header>

      {/* Filter panel */}
      <GlassPanel className="filter-panel mb-6 flex flex-col md:flex-row gap-4 border border-white/5" delay={0.05}>
        <div className="flex-grow flex items-center gap-2 bg-slate-950/70 border border-cyan-800/30 rounded-lg px-3 py-1.5 focus-within:border-cyan-500/50">
          <Search size={16} className="text-gray-500" />
          <input
            type="text"
            placeholder="Search details, event type..."
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            className="bg-transparent border-none text-xs text-gray-300 placeholder-gray-500 focus:outline-none w-full font-mono"
          />
        </div>

        <div className="flex items-center gap-3">
          <Filter size={16} className="text-gray-400" />
          <select
            value={typeFilter}
            onChange={(e) => setTypeFilter(e.target.value)}
            className="bg-slate-950/70 border border-cyan-800/30 rounded-lg px-3 py-1.5 text-cyan-400 font-mono text-xs focus:outline-none"
          >
            <option value="all">All Event Types</option>
            <option value="prediction">Predictions</option>
            <option value="localization">Localizations</option>
            <option value="diagnosis">Diagnoses</option>
            <option value="remediation">Remediations</option>
            <option value="other">Other Operations</option>
          </select>
        </div>
      </GlassPanel>

      {/* Log events list */}
      <GlassPanel className="flex-grow border border-white/5" delay={0.1}>
        <div className="overflow-x-auto rounded-lg border border-white/5">
          {filteredEvents.length === 0 ? (
            <div className="p-8 text-center text-gray-500 text-xs flex flex-col items-center gap-2">
              <Clock size={24} className="text-gray-600 animate-pulse" />
              No audit logs match current filters.
            </div>
          ) : (
            <table className="w-full text-left text-xs border-collapse">
              <thead>
                <tr className="bg-slate-950/80 text-gray-400 font-semibold border-b border-white/10">
                  <th className="p-3 w-10"></th>
                  <th className="p-3 w-48">Timestamp</th>
                  <th className="p-3 w-48">Event Type</th>
                  <th className="p-3">Details Summary</th>
                </tr>
              </thead>
              <tbody>
                {filteredEvents.map((event, idx) => {
                  const isExpanded = expandedEvent === idx;
                  const uiType = getUiEventType(event.event_type);
                  const typeColors = {
                    prediction: 'bg-cyan-950/40 text-cyan-400 border-cyan-800/30',
                    localization: 'bg-purple-950/40 text-purple-400 border-purple-800/30',
                    diagnosis: 'bg-amber-950/40 text-amber-400 border-amber-800/30',
                    remediation: 'bg-green-950/40 text-green-400 border-green-800/30',
                  };
                  const colorClass = typeColors[uiType] || 'bg-slate-950/40 text-slate-400 border-slate-800/30';

                  return (
                    <React.Fragment key={idx}>
                      <tr
                        onClick={() => setExpandedEvent(isExpanded ? null : idx)}
                        className="border-b border-white/5 hover:bg-white/5 transition-all cursor-pointer"
                      >
                        <td className="p-3">
                          <ChevronDown size={14} className={`text-gray-500 transition-transform ${isExpanded ? 'rotate-180' : ''}`} />
                        </td>
                        <td className="p-3 font-mono text-gray-400">
                          {new Date(event.timestamp).toLocaleString()}
                        </td>
                        <td className="p-3">
                          <span className={`px-2 py-0.5 rounded text-[9px] font-bold border uppercase font-mono ${colorClass}`}>
                            {event.event_type}
                          </span>
                        </td>
                        <td className="p-3 text-gray-300 font-mono truncate max-w-xs md:max-w-md">
                          {getEventDetails(event)}
                        </td>
                      </tr>
                      {isExpanded && (
                        <tr className="bg-slate-950/20 border-b border-white/5">
                          <td colSpan="4" className="p-4 text-xs font-mono text-gray-400 leading-relaxed">
                            <div className="flex flex-col gap-2">
                              <div className="flex gap-2 items-center text-[10px] text-cyan-400 font-bold uppercase tracking-wider">
                                <ArrowRight size={10} /> Full event trace
                              </div>
                              <pre className="bg-slate-950/60 p-4 rounded border border-white/5 text-gray-300 overflow-x-auto max-h-96 whitespace-pre-wrap">
                                {event.payload ? JSON.stringify(event.payload, null, 2) : getEventDetails(event)}
                              </pre>
                            </div>
                          </td>
                        </tr>
                      )}
                    </React.Fragment>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>
      </GlassPanel>
    </div>
  );
}
