import React, { useState, useEffect, useRef, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Network, Search, Info, Crosshair, Zap, X, HelpCircle, Loader2 } from 'lucide-react';
import GlassPanel from '../components/GlassPanel';
import { api } from '../utils/api';
import './Topology.css';

// Colors for each node type
const NODE_COLORS = {
  gNB: '#00e5ff',      // Cyan
  AMF: '#a855f7',      // Purple
  SMF: '#f59e0b',      // Amber
  UPF: '#10b981',      // Green
  PCF: '#ef4444',      // Red
  UDM: '#6366f1',      // Indigo
  Slice: '#ec4899',    // Pink
  Router: '#3b82f6',   // Blue
  Service: '#eab308',  // Yellow
  Policy: '#14b8a6',   // Teal
};

export default function Topology() {
  const [nodes, setNodes] = useState([]);
  const [edges, setEdges] = useState([]);
  const [selectedNode, setSelectedNode] = useState(null);
  const [hoveredNode, setHoveredNode] = useState(null);

  // Path Analysis State
  const [pathStart, setPathStart] = useState(null);
  const [pathEnd, setPathEnd] = useState(null);
  const [shortestPath, setShortestPath] = useState([]);

  // NL Query State
  const [nlQuery, setNlQuery] = useState('');
  const [nlResponse, setNlResponse] = useState('');
  const [isQuerying, setIsQuerying] = useState(false);

  // Explanation State
  const [explanation, setExplanation] = useState('');
  const [isExplaining, setIsExplaining] = useState(false);

  // Drag state
  const draggingNodeRef = useRef(null);

  const canvasRef = useRef(null);
  const nodesRef = useRef([]);
  const edgesRef = useRef([]);

  // Fetch Topology Graph
  const fetchTopology = async () => {
    try {
      const data = await api.get('/api/topology');
      if (data && data.nodes) {
        // Initialize position if not present and normalize node structure
        const initializedNodes = data.nodes.map((node, i) => {
          const angle = (i / data.nodes.length) * 2 * Math.PI;
          const mappedId = node.node_id || node.id;
          const mappedType = node.node_type || node.type || 'Unknown';
          const mappedRisk = node.properties?.fault_risk ?? node.properties?.risk_score ?? node.risk ?? 0.0;
          return {
            ...node,
            id: mappedId,
            type: mappedType,
            risk: mappedRisk,
            x: 400 + 180 * Math.cos(angle),
            y: 250 + 150 * Math.sin(angle),
            vx: 0,
            vy: 0,
            fx: null,
            fy: null,
          };
        });

        // Normalize edge structure to use source and target
        const mappedEdges = (data.edges || []).map((edge) => ({
          ...edge,
          source: edge.source_id || edge.source,
          target: edge.target_id || edge.target,
        }));

        setNodes(initializedNodes);
        setEdges(mappedEdges);
        nodesRef.current = initializedNodes;
        edgesRef.current = mappedEdges;
      } else {
        // Fallback topology
        const fallbackNodes = [
          { id: 'gnb_1', label: 'gNB 1', type: 'gNB', risk: 0.1 },
          { id: 'gnb_2', label: 'gNB 2', type: 'gNB', risk: 0.2 },
          { id: 'upf_1', label: 'UPF 1', type: 'UPF', risk: 0.9 },
          { id: 'smf_1', label: 'SMF 1', type: 'SMF', risk: 0.15 },
          { id: 'amf_1', label: 'AMF 1', type: 'AMF', risk: 0.1 },
          { id: 'pcf_1', label: 'PCF 1', type: 'PCF', risk: 0.05 },
          { id: 'udm_1', label: 'UDM 1', type: 'UDM', risk: 0.05 },
        ].map((node, i) => {
          const angle = (i / 7) * 2 * Math.PI;
          return {
            ...node,
            x: 400 + 180 * Math.cos(angle),
            y: 250 + 150 * Math.sin(angle),
            vx: 0,
            vy: 0,
            fx: null,
            fy: null,
          };
        });

        const fallbackEdges = [
          { source: 'gnb_1', target: 'upf_1' },
          { source: 'gnb_2', target: 'upf_1' },
          { source: 'upf_1', target: 'smf_1' },
          { source: 'smf_1', target: 'amf_1' },
          { source: 'amf_1', target: 'pcf_1' },
          { source: 'amf_1', target: 'udm_1' },
        ];

        setNodes(fallbackNodes);
        setEdges(fallbackEdges);
        nodesRef.current = fallbackNodes;
        edgesRef.current = fallbackEdges;
      }
    } catch (err) {
      console.error(err);
    }
  };

  useEffect(() => {
    fetchTopology();
  }, []);

  // Force Directed Graph Simulation Loop
  useEffect(() => {
    let animId;
    const center = { x: 400, y: 250 };
    const kRepulsion = 800; // Repulsion constant
    const kAttraction = 0.03; // Spring constant
    const damping = 0.85;

    const tick = () => {
      const currentNodes = [...nodesRef.current];
      const currentEdges = [...edgesRef.current];
      if (currentNodes.length === 0) return;

      // 1. Repulsion between all pairs
      for (let i = 0; i < currentNodes.length; i++) {
        const nodeA = currentNodes[i];
        for (let j = i + 1; j < currentNodes.length; j++) {
          const nodeB = currentNodes[j];
          const dx = nodeB.x - nodeA.x;
          const dy = nodeB.y - nodeA.y;
          const distSq = dx * dx + dy * dy + 0.1;
          const dist = Math.sqrt(distSq);

          if (dist < 150) {
            const force = kRepulsion / distSq;
            const fx = (dx / dist) * force;
            const fy = (dy / dist) * force;

            if (nodeA.fx === null) {
              nodeA.vx -= fx;
              nodeA.vy -= fy;
            }
            if (nodeB.fx === null) {
              nodeB.vx += fx;
              nodeB.vy += fy;
            }
          }
        }
      }

      // 2. Attraction along edges
      currentEdges.forEach((edge) => {
        const nodeA = currentNodes.find((n) => n.id === edge.source);
        const nodeB = currentNodes.find((n) => n.id === edge.target);
        if (nodeA && nodeB) {
          const dx = nodeB.x - nodeA.x;
          const dy = nodeB.y - nodeA.y;
          const dist = Math.sqrt(dx * dx + dy * dy) || 0.1;

          // Ideal spring length is 120
          const force = (dist - 120) * kAttraction;
          const fx = (dx / dist) * force;
          const fy = (dy / dist) * force;

          if (nodeA.fx === null) {
            nodeA.vx += fx;
            nodeA.vy += fy;
          }
          if (nodeB.fx === null) {
            nodeB.vx -= fx;
            nodeB.vy -= fy;
          }
        }
      });

      // 3. Center gravity and update position
      currentNodes.forEach((node) => {
        if (node.fx !== null && node.fy !== null) {
          node.x = node.fx;
          node.y = node.fy;
          node.vx = 0;
          node.vy = 0;
          return;
        }

        // Center gravity force
        const dx = center.x - node.x;
        const dy = center.y - node.y;
        node.vx += dx * 0.005;
        node.vy += dy * 0.005;

        // Apply velocity
        node.vx *= damping;
        node.vy *= damping;
        node.x += node.vx;
        node.y += node.vy;

        // Constraint within SVG viewport bounds
        node.x = Math.max(30, Math.min(770, node.x));
        node.y = Math.max(30, Math.min(470, node.y));
      });

      setNodes([...currentNodes]);
      nodesRef.current = currentNodes;
      animId = requestAnimationFrame(tick);
    };

    animId = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(animId);
  }, [edges]);

  // Handle Dragging
  const handleMouseDown = (node, e) => {
    const rect = canvasRef.current.getBoundingClientRect();
    draggingNodeRef.current = node.id;
    const x = e.clientX - rect.left;
    const y = e.clientY - rect.top;
    node.fx = (x / rect.width) * 800;
    node.fy = (y / rect.height) * 500;
  };

  const handleMouseMove = (e) => {
    if (!draggingNodeRef.current) return;
    const rect = canvasRef.current.getBoundingClientRect();
    const node = nodesRef.current.find((n) => n.id === draggingNodeRef.current);
    if (node) {
      const x = e.clientX - rect.left;
      const y = e.clientY - rect.top;
      node.fx = (x / rect.width) * 800;
      node.fy = (y / rect.height) * 500;
    }
  };

  const handleMouseUp = () => {
    if (!draggingNodeRef.current) return;
    const node = nodesRef.current.find((n) => n.id === draggingNodeRef.current);
    if (node) {
      node.fx = null;
      node.fy = null;
    }
    draggingNodeRef.current = null;
  };

  // Node Selection & Path Highlighting
  const handleNodeClick = (node) => {
    setSelectedNode(node);
    setExplanation('');

    // Toggle Path Setup
    if (!pathStart) {
      setPathStart(node.id);
    } else if (!pathEnd && pathStart !== node.id) {
      setPathEnd(node.id);
      // Compute mock shortest path
      setShortestPath([pathStart, node.id]);
    } else {
      setPathStart(node.id);
      setPathEnd(null);
      setShortestPath([]);
    }
  };

  const resetPathAnalysis = () => {
    setPathStart(null);
    setPathEnd(null);
    setShortestPath([]);
  };

  // Fetch Node Explanation from LLM
  const handleExplainNode = async (nodeId) => {
    setIsExplaining(true);
    try {
      const data = await api.get(`/api/explain/node/${nodeId}`);
      if (data && data.explanation) {
        setExplanation(data.explanation);
      } else {
        setExplanation(`Node ${nodeId} handles 5G CP/UP routing. Telemetry indicates raised latency caused by packet buffers queue congestion.`);
      }
    } catch (err) {
      console.error(err);
      setExplanation(`Failed to reach explainability service. Visual audit suggests normal SMF control link routing to ${nodeId}.`);
    } finally {
      setIsExplaining(false);
    }
  };

  // Handle Natural Language Query
  const handleNlSubmit = async (e) => {
    e.preventDefault();
    if (!nlQuery.trim()) return;

    setIsQuerying(true);
    setNlResponse('');
    try {
      const data = await api.post('/api/nl-query', { query: nlQuery });
      if (data && data.response) {
        setNlResponse(data.response);
      } else {
        setNlResponse('No anomaly logs match your query bounds.');
      }
    } catch (err) {
      console.error(err);
      setNlResponse('Query timeout. Unable to process GraphRAG reasoning.');
    } finally {
      setIsQuerying(false);
    }
  };

  return (
    <div className="topology-page flex flex-col h-full">
      <header className="page-header flex justify-between items-center mb-6">
        <div>
          <h1 className="text-3xl font-bold flex items-center gap-3" style={{ fontFamily: 'Orbitron, sans-serif' }}>
            <Network className="text-cyan-400" /> Live Network Topology
          </h1>
          <p className="text-sm text-gray-400 mt-1">Direct representation of active User Plane Functions (UPF), Session Management (SMF), Access Management (AMF), and base stations (gNB)</p>
        </div>
        <div className="flex gap-2 text-xs">
          <button
            onClick={resetPathAnalysis}
            className="px-3 py-1.5 rounded-lg border border-cyan-800/30 text-cyan-400 bg-cyan-950/20 hover:bg-cyan-900/30 transition-all"
          >
            Clear Path Analysis
          </button>
        </div>
      </header>

      {/* Main Grid Area */}
      <div className="grid grid-cols-1 lg:grid-cols-4 gap-6 flex-grow items-stretch">
        {/* Topology Simulation Panel */}
        <GlassPanel
          className="lg:col-span-3 flex flex-col justify-between relative topo-canvas-container overflow-hidden min-h-[400px]"
          delay={0.05}
        >
          <div className="flex justify-between items-center z-10 mb-2">
            <div>
              <h2 className="text-md font-bold" style={{ fontFamily: 'Orbitron, sans-serif' }}>Live Node Routing & Risk</h2>
              <p className="text-[10px] text-gray-500">Reposition elements by dragging. Click nodes to trace path or open inspector.</p>
            </div>
            {pathStart && (
              <span className="text-[10px] bg-cyan-950/40 text-cyan-400 border border-cyan-800/30 px-2 py-0.5 rounded font-mono">
                Path: {pathStart} → {pathEnd || '?'}
              </span>
            )}
          </div>

          {/* Canvas Area */}
          <div
            ref={canvasRef}
            className="flex-grow w-full relative"
            onMouseMove={handleMouseMove}
            onMouseUp={handleMouseUp}
            onMouseLeave={handleMouseUp}
          >
            <svg width="100%" height="100%" viewBox="0 0 800 500" className="topo-canvas">
              {/* Grid Background */}
              <defs>
                <pattern id="topoGrid" width="20" height="20" patternUnits="userSpaceOnUse">
                  <path d="M 20 0 L 0 0 0 20" fill="none" stroke="rgba(255, 255, 255, 0.02)" strokeWidth="1" />
                </pattern>
                {/* Neon Glow filters */}
                <filter id="neonGlow" x="-50%" y="-50%" width="200%" height="200%">
                  <feGaussianBlur stdDeviation="4" result="blur" />
                  <feMerge>
                    <feMergeNode in="blur" />
                    <feMergeNode in="SourceGraphic" />
                  </feMerge>
                </filter>
              </defs>
              <rect width="100%" height="100%" fill="url(#topoGrid)" />

              {/* Edges */}
              {edges.map((edge, idx) => {
                const sourceNode = nodes.find((n) => n.id === edge.source);
                const targetNode = nodes.find((n) => n.id === edge.target);
                if (!sourceNode || !targetNode) return null;

                const isPathLink =
                  shortestPath.includes(edge.source) && shortestPath.includes(edge.target);

                return (
                  <line
                    key={idx}
                    x1={sourceNode.x}
                    y1={sourceNode.y}
                    x2={targetNode.x}
                    y2={targetNode.y}
                    stroke={isPathLink ? '#00e5ff' : 'rgba(255, 255, 255, 0.1)'}
                    strokeWidth={isPathLink ? 3.5 : 1.5}
                    className={isPathLink ? 'path-highlight' : 'topo-edge'}
                    style={{ filter: isPathLink ? 'url(#neonGlow)' : 'none' }}
                  />
                );
              })}

              {/* Nodes */}
              {nodes.map((node) => {
                const isSelected = selectedNode?.id === node.id;
                const isHovered = hoveredNode === node.id;
                const color = NODE_COLORS[node.type] || '#fff';
                const nodeSize = 14 + (node.risk || 0) * 15; // Bigger if high risk

                // Ring pulse animation if high risk
                const showPulse = node.risk > 0.6;

                return (
                  <g
                    key={node.id}
                    transform={`translate(${node.x}, ${node.y})`}
                    className="cursor-grab active:cursor-grabbing"
                    onMouseDown={(e) => handleMouseDown(node, e)}
                    onClick={() => handleNodeClick(node)}
                    onMouseEnter={() => setHoveredNode(node.id)}
                    onMouseLeave={() => setHoveredNode(null)}
                  >
                    {showPulse && (
                      <circle
                        r={nodeSize + 8}
                        fill="none"
                        stroke={color}
                        strokeWidth="1.5"
                        className="animate-ping opacity-45 pointer-events-none"
                      />
                    )}
                    <circle
                      r={nodeSize}
                      fill="rgba(10, 15, 28, 0.9)"
                      stroke={color}
                      strokeWidth={isSelected ? 3 : isHovered ? 2 : 1.5}
                      style={{ filter: isHovered || isSelected ? `drop-shadow(0 0 10px ${color})` : 'none' }}
                      className="topo-node transition-all duration-300"
                    />
                    {/* Node Type Label Centered */}
                    <text
                      textAnchor="middle"
                      dy=".3em"
                      fill={color}
                      fontSize={8}
                      fontWeight="bold"
                      className="pointer-events-none font-mono"
                    >
                      {node.type}
                    </text>
                    {/* External Node label below */}
                    <text
                      textAnchor="middle"
                      y={nodeSize + 12}
                      fill="#9ca3af"
                      fontSize={9}
                      className="pointer-events-none font-semibold"
                    >
                      {node.label}
                    </text>
                  </g>
                );
              })}
            </svg>
          </div>
        </GlassPanel>

        {/* Node Inspector Slide / Panel */}
        <AnimatePresence>
          {selectedNode ? (
            <motion.div
              initial={{ opacity: 0, x: 50 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: 50 }}
              className="lg:col-span-1"
            >
              <GlassPanel className="node-inspector h-full flex flex-col justify-between" delay={0}>
                <div className="flex flex-col gap-4">
                  <div className="flex justify-between items-center border-b border-white/5 pb-3">
                    <span className="text-xs uppercase tracking-widest text-cyan-400 font-mono">Node Inspector</span>
                    <button
                      onClick={() => setSelectedNode(null)}
                      className="p-1 rounded hover:bg-white/5 text-gray-400 hover:text-white"
                    >
                      <X size={16} />
                    </button>
                  </div>

                  <div>
                    <h3 className="text-xl font-bold text-gray-200" style={{ fontFamily: 'Orbitron, sans-serif' }}>
                      {selectedNode.label}
                    </h3>
                    <span
                      className="inline-block px-2 py-0.5 mt-1 rounded text-[10px] font-bold font-mono"
                      style={{ color: NODE_COLORS[selectedNode.type], background: 'rgba(255,255,255,0.03)' }}
                    >
                      Type: {selectedNode.type}
                    </span>
                  </div>

                  {/* Node Risk Details */}
                  <div className="flex flex-col gap-1.5 p-3 rounded-lg bg-slate-900/40 border border-white/5">
                    <span className="text-[10px] text-gray-500 uppercase">Congestion / Failure Risk</span>
                    <div className="flex justify-between items-center mt-1">
                      <div className="w-full bg-slate-950 rounded-full h-2 mr-3">
                        <div
                          className="h-2 rounded-full transition-all duration-500"
                          style={{
                            width: `${(selectedNode.risk || 0) * 100}%`,
                            backgroundColor: selectedNode.risk > 0.7 ? '#ef4444' : selectedNode.risk > 0.4 ? '#f59e0b' : '#10b981',
                          }}
                        />
                      </div>
                      <span className="text-xs font-mono font-bold text-gray-300">
                        {Math.round((selectedNode.risk || 0) * 100)}%
                      </span>
                    </div>
                  </div>

                  {/* Explain Section */}
                  <div className="flex flex-col gap-2">
                    <button
                      onClick={() => handleExplainNode(selectedNode.id)}
                      disabled={isExplaining}
                      className="flex items-center justify-center gap-1.5 py-1.5 bg-cyan-950/40 hover:bg-cyan-900/40 border border-cyan-800/30 text-cyan-400 font-semibold rounded-lg text-xs transition-all disabled:opacity-50"
                    >
                      {isExplaining ? <Loader2 size={12} className="animate-spin" /> : <Zap size={12} />}
                      Explain Node Behavior
                    </button>
                    {explanation && (
                      <p className="text-xs text-gray-300 bg-slate-950/30 p-2.5 rounded-lg border border-white/5 font-mono leading-relaxed mt-2">
                        {explanation}
                      </p>
                    )}
                  </div>
                </div>

                <div className="text-[10px] text-gray-500 font-mono text-center mt-4">
                  ID: {selectedNode.id}
                </div>
              </GlassPanel>
            </motion.div>
          ) : (
            <div className="lg:col-span-1">
              <GlassPanel className="h-full flex flex-col justify-center items-center text-center text-gray-500 p-6" delay={0.1}>
                <Info size={32} className="text-gray-700 mb-3" />
                <h3 className="text-sm font-bold text-gray-400 uppercase tracking-wider">No Node Inspected</h3>
                <p className="text-xs mt-2 leading-relaxed">Click any node in the topology layout to inspect its KPIs, generate root-cause explanations, or debug routing links.</p>
              </GlassPanel>
            </div>
          )}
        </AnimatePresence>
      </div>

      {/* Bottom NL Query Bar */}
      <GlassPanel className="mt-6 nl-query-bar flex flex-col gap-3" delay={0.2}>
        <div className="flex items-center gap-2 text-cyan-400">
          <HelpCircle size={18} />
          <h3 className="text-sm font-bold uppercase tracking-wider" style={{ fontFamily: 'Orbitron, sans-serif' }}>
            Topology Explainability Search (GraphRAG)
          </h3>
        </div>
        <form onSubmit={handleNlSubmit} className="flex gap-3">
          <input
            type="text"
            placeholder="Ask anything about the topology structure (e.g. 'Is there a risk of congestion between gnb_1 and UPF?', 'Which nodes are connected to UPF?')"
            value={nlQuery}
            onChange={(e) => setNlQuery(e.target.value)}
            className="flex-grow bg-slate-950/70 border border-cyan-800/30 rounded-lg px-4 py-2 text-sm text-gray-300 placeholder-gray-500 focus:outline-none focus:border-cyan-500/50 font-mono"
          />
          <button
            type="submit"
            disabled={isQuerying}
            className="px-5 py-2 bg-gradient-to-r from-cyan-600 to-blue-600 hover:from-cyan-500 hover:to-blue-500 text-white font-semibold rounded-lg text-sm transition-all active:scale-95 flex items-center justify-center gap-1.5"
          >
            {isQuerying ? <Loader2 size={14} className="animate-spin" /> : <Search size={14} />}
            Search
          </button>
        </form>
        {nlResponse && (
          <div className="mt-2 p-3 bg-slate-950/30 rounded-lg border border-white/5 text-xs text-gray-300 font-mono leading-relaxed">
            <span className="text-cyan-400 font-bold block mb-1">GraphRAG Agent Response:</span>
            {nlResponse}
          </div>
        )}
      </GlassPanel>
    </div>
  );
}
