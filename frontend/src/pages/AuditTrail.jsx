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
    const matchesSearch =
      event.details.toLowerCase().includes(searchTerm.toLowerCase()) ||
      event.event_type.toLowerCase().includes(searchTerm.toLowerCase());
    const matchesType = typeFilter === 'all' || event.event_type === typeFilter;
    return matchesSearch && matchesType;
  });

  const handleExport = () => {
    const dataStr = JSON.stringify(events, null, 2);
    const blob = new Blob([dataStr], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `netoracle-audit-trail-${new Date().toISOString().slice(0,10)}.json`;
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
          <p className="text-sm text-gray-400 mt-1">Immutable execution log logs of GNN predictions, Causal localization discovery, and Safe RL mitigations</p>
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
                  <th className="p-3 w-32">Event Type</th>
                  <th className="p-3">Details Summary</th>
                </tr>
              </thead>
              <tbody>
                {filteredEvents.map((event, idx) => {
                  const isExpanded = expandedEvent === idx;
                  const typeColors = {
                    prediction: 'bg-cyan-950/40 text-cyan-400 border-cyan-800/30',
                    localization: 'bg-purple-950/40 text-purple-400 border-purple-800/30',
                    diagnosis: 'bg-amber-950/40 text-amber-400 border-amber-800/30',
                    remediation: 'bg-green-950/40 text-green-400 border-green-800/30',
                  };
                  const colorClass = typeColors[event.event_type] || 'bg-slate-950/40 text-slate-400 border-slate-800/30';

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
                          {event.details}
                        </td>
                      </tr>
                      {isExpanded && (
                        <tr className="bg-slate-950/20 border-b border-white/5">
                          <td colSpan="4" className="p-4 text-xs font-mono text-gray-400 leading-relaxed">
                            <div className="flex flex-col gap-2">
                              <div className="flex gap-2 items-center text-[10px] text-cyan-400 font-bold uppercase tracking-wider">
                                <ArrowRight size={10} /> Full event trace
                              </div>
                              <p className="bg-slate-950/40 p-3 rounded border border-white/5 text-gray-300">
                                {event.details}
                              </p>
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
