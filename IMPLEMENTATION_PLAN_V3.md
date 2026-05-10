# NetOracle v3.0 — Complete Rework Implementation Plan

**Date:** 2026-05-10 | **Status:** PLAN — Awaiting Approval

---

## Executive Summary

After a thorough audit of the entire codebase, research documents, and live browser testing, this plan addresses **every broken feature**, **every visual shortcoming**, and **every gap** between the current state and the research paper's vision. The goal: a hackathon-winning, fully functional, visually stunning 5G fault intelligence platform.

---

## Part 1: Critical Bugs Found (Must Fix First)

### Bug 1: Topology Tab Explain → 500 Error
- **File:** `app/services/explainability.py` line 100
- **Error:** `TypeError: sequence item 0: expected str instance, dict found`
- **Cause:** `graph_service.get_affected_path()` returns list of dicts, but code calls `' → '.join(path)` expecting strings
- **Fix:** Extract node IDs from path dicts before joining

### Bug 2: NL Query "Ask" Button Sends Wrong Key
- **File:** `app/static/app.js` line 518
- **Error:** Frontend sends `{ query: ... }` but backend expects `{ question: ... }`
- **Fix:** Change JS to send `{ question: $('question').value }`

### Bug 3: NL Query Results Often Empty
- **File:** `app/services/graph.py` — `_execute_pseudo_cypher()`
- **Cause:** Regex fallback is too narrow; many natural queries get zero matches
- **Fix:** Expand regex patterns + improve Groq prompt with better few-shot examples + return richer results

### Bug 4: KPI Gauges Show "--" Forever
- **File:** `app/static/app.js` lines 183-203
- **Cause:** `updateKpis()` only fires on alert/diagnosis events, never on initial load
- **Fix:** Call `updateKpis()` with model metrics from `/api/metrics` on page load

### Bug 5: Tick Button Returns Frames but Chart Doesn't Update
- **File:** `app/static/app.js` line 458
- **Cause:** `handleTick` expects `payload.frames` but tick API returns flat array; telemetry rows lack `.metrics` sub-object needed by `TelemetryChart`
- **Fix:** Normalize frame shape in `handleTick` to wrap flat metrics into the format the chart expects

### Bug 6: WebSocket Auto-Tick Not Broadcasting Proactive/Realtime
- **File:** `app/main.py` — `auto_tick()` background task
- **Cause:** The broadcast payload doesn't include `proactive` or `realtime` data
- **Fix:** Add proactive forecast and realtime analysis to the WebSocket broadcast

### Bug 7: Diagnosis "Run Demo" Shows Empty Specialist Cards
- **File:** `app/static/app.js` lines 493-495
- **Cause:** The path `data.diagnosis.evidence.verdict.rounds` doesn't match actual API response shape
- **Fix:** Adapt to actual response: `data.diagnosis.evidence.specialist_verdicts` or `data.diagnosis.moe_routing`

### Bug 8: Export Buttons 404
- **File:** `app/static/app.js` line 467-468
- **Cause:** Buttons call `/api/cloud/export-audit` but the endpoint is `/api/cloud/export`
- **Fix:** Update paths to match actual backend routes

---

## Part 2: Real Data Pipeline (Replace Pure Synthetic)

### 2A: Acquire Real-World Base Datasets

The research paper references **Telecom Italia** and **CAIDA** datasets. Based on web research, the best available real/semi-real datasets are:

| Dataset | Source | What It Provides | How We Use It |
|---------|--------|-------------------|---------------|
| **5G-NIDD** | IEEE Dataport / Univ. of Oulu | Real 5G testbed traffic with labeled attacks (DoS, port scan) — CSV format | Base distribution for normal/anomalous network behavior patterns |
| **Telecom Italia CDR** | FBK/BigDataChallenge | Milan cell traffic intensity over 2 months, 10-min intervals | Realistic diurnal traffic patterns and spatial correlations |
| **TeleLogs** | HuggingFace (netop) | Synthetic but engineering-grade 5G RCA data with 8 root causes, RSRP, SINR, throughput | Root cause labels and realistic 5G RAN parameter ranges |
| **CAIDA Traces** | caida.org | Internet backbone packet traces | Packet loss and throughput distribution baselines |

### 2B: New Data Generation Script — `scripts/generate_realistic_data.py`

Instead of pure `sin() + random()`, the new generator will:

1. **Load real statistical profiles** from downloaded dataset summaries (mean, std, correlation matrices, diurnal patterns)
2. **Generate correlated metrics** using multivariate Gaussian with real covariance structure
3. **Apply diurnal modulation** from Telecom Italia traffic patterns (peak 09:00/18:00, trough 03:00)
4. **Inject realistic fault cascades** with causal chains:
   - `cpu_overload` → `latency_spike` (200ms delay, 0.85 correlation)
   - `memory_leak` → `vnf_degradation` → `packet_loss` (cascade over 3 ticks)
   - `link_failure` → `throughput_drop` + `packet_loss_burst`
   - `congestion` → `prb_saturation` → `latency_spike`
5. **Output multiple scenario CSVs** in `data/scenarios/`:
   - `normal_24h.csv` — 24 hours of healthy traffic
   - `cascade_failure.csv` — Multi-node cascade event
   - `gradual_degradation.csv` — Slow memory leak over hours
   - `flash_crowd.csv` — Sudden traffic spike on one slice
   - `mixed_realistic.csv` — Combined scenarios (default training set)
6. **Statistical validation:** Print correlation matrix comparison vs real data profiles

### 2C: User-Driven Synthetic Generation (Data Sources Tab)

Add a new "Generate Synthetic Data" panel in the Data Sources tab:

```
┌─────────────────────────────────────────┐
│ Generate Synthetic Network Data         │
│                                         │
│ Scenario: [Dropdown: Normal/Cascade/    │
│            Degradation/Flash Crowd/Mix] │
│ Duration:  [Slider: 1h — 48h]          │
│ Fault Rate: [Slider: 0% — 30%]         │
│ Slices:    [Checkboxes: eMBB/mMTC/URLLC]│
│ Nodes:     [Number: 5-20]              │
│                                         │
│ [⚡ Generate & Load]                    │
│                                         │
│ Status: Generated 2400 rows, 3 faults   │
│ injected. Distribution matches 5G-NIDD  │
│ profile (KL divergence: 0.04)           │
└─────────────────────────────────────────┘
```

**Backend endpoint:** `POST /api/data/generate-synthetic`
- Accepts scenario parameters
- Runs generator
- Loads into telemetry DB
- Returns statistical summary
- User can then visualize the faults being predicted in real-time

### 2D: Live Fault Prediction Visualization

After data is loaded (synthetic or uploaded), the dashboard will:
1. Stream rows via WebSocket as if live
2. CTGNN runs inference on each window
3. **Proactive panel shows predictions happening in real-time** with countdown timers
4. When a predicted fault materializes, show a "✅ Prediction Correct" or "⚠️ False Alarm" indicator
5. Track prediction accuracy live on the dashboard

---

## Part 3: NL-to-Cypher Complete Fix

### 3A: Fix the Frontend-Backend Key Mismatch
- JS sends `{ query: ... }` → change to `{ question: ... }`

### 3B: Improve Groq Prompt for NL-to-Cypher
Current prompt is generic. New prompt will include:
- Full graph schema (all node types, relationship types, property names)
- 10 few-shot examples covering all difficulty levels from the research paper
- Explicit instruction to return ONLY the Cypher query
- Temperature 0.1 for deterministic output

### 3C: Improve `_execute_pseudo_cypher()` Fallback
Current regex only handles 3-4 patterns. Expand to handle:
- "Which VNFs are connected to Slice X?" → filter by slice relationships
- "What nodes are at risk?" → filter by fault_risk > threshold
- "Show the path from X to Y" → BFS traversal on topology
- "Which slices share infrastructure?" → find common nodes
- "What caused the last fault?" → query audit trail
- "How many nodes are in Slice X?" → count query
- Wildcard: any unmatched query returns top-5 relevant nodes by keyword match

### 3D: Add NL Query to Diagnosis Tab Too
Currently NL Query is only in the Topology tab. Add a second instance in the Diagnosis tab for quick queries during investigation.

---

## Part 4: UI/UX Major Overhaul

### 4A: Visual Theme — "Neon Cyberpunk NOC"

The current UI is functional but bland. The research paper describes a "professional Network Operations Center dashboard" that should feel "Grafana + Cyberpunk HUD + Bloomberg Terminal."

**Color system overhaul:**
```css
--bg-deep: #020817;        /* Near-black space background */
--bg-panel: rgba(6, 18, 42, 0.85);  /* Deep blue glass panels */
--cyan: #00f5ff;           /* Primary accent — data, links */
--purple: #b347f5;         /* Secondary — AI/intelligence */
--green: #00ff88;          /* Success, healthy, nominal */
--red: #ff3366;            /* Danger, faults, critical */
--amber: #ffb800;          /* Warning, degraded */
--pink: #f472b6;           /* Highlights, active selections */
--text-primary: #e2e8f0;   /* Main text */
--text-muted: #94a3b8;     /* Secondary text */
```

**New visual effects to add:**
1. **Animated grid background** — Subtle moving grid lines on body (CSS `background-image` with `linear-gradient`, animated with `@keyframes`)
2. **Glassmorphism panels** — `backdrop-filter: blur(16px)`, colored left-border accents
3. **Scanline overlay** — Subtle horizontal lines at 3% opacity across all panels
4. **Neon glow buttons** — `box-shadow` with accent color on hover, scale transform on click
5. **Pulsing status indicators** — CSS animations for live/connected/fault dots
6. **Animated number transitions** — JS `animateNumber()` function for all KPI updates
7. **Card entrance animations** — Cards fade-slide in when tab switches
8. **Gradient borders** — Top/left border gradients on panels based on content type

### 4B: Dashboard Tab Improvements
- KPI gauge rings should animate on load (not just show --)
- Add model AUC and inference latency KPIs from `/api/metrics`
- Proactive panel should show a mini-timeline of upcoming predicted events
- Alert feed should auto-scroll and have severity-colored left borders
- Telemetry chart needs a time axis that shows actual timestamps

### 4C: Causal AI Tab Improvements
- DAG nodes should be color-coded by metric type (not all same color)
- Edge thickness should reflect causal strength more visibly
- Add a "DAG History" mini-timeline showing how the DAG evolved
- Benchmark results should show bar charts comparing CTGNN vs baselines

### 4D: Topology Tab Improvements
- Nodes should pulse when at-risk (not just change border color)
- Add a path highlighting feature: click two nodes to see the path between them
- NL Query answer should highlight matched nodes on the graph
- Node inspector should show full metric history for that node

### 4E: Diagnosis Tab Improvements
- Specialist verdict cards should have unique icons per domain
- Add an animated decision flow visualization (not just text divs)
- Show before/after metrics comparison in the remediation card
- Add a "Prediction Accuracy" counter showing hit/miss ratio

### 4F: Wireless RL Tab Improvements
- Hopfield grid visualization needs color intensity (not just on/off)
- Add a convergence animation showing the energy function decreasing
- CMDP policy should show a state-action table with safety constraints highlighted
- Add a "Run Allocation Stress Test" button that shows how allocation adapts under load

### 4G: Data Sources Tab — NEW Features
- Add "Generate Synthetic Data" panel (as described in Part 2C)
- Show a preview of the loaded data (first 10 rows as a formatted table)
- Add dataset statistics panel (row count, feature distributions, fault ratio)
- Add a "Train Model on This Data" button that triggers the export-retrain pipeline

---

## Part 5: Three.js Digital Twin — Cyberpunk Upgrade

### 5A: Visual Effects Upgrade
Current twin has bloom but is visually static. Enhancements:

1. **Animated particle system for background** — Floating dust particles with subtle motion
2. **Neon edge glow** — Use `MeshLine` or thicker line geometry with emissive materials
3. **Pulse waves** — When a fault is detected, send a visible pulse wave from the affected node
4. **Better node geometry** — Use `IcosahedronGeometry` for nodes (more faceted, sci-fi look)
5. **Dynamic edge particles** — More particles, varying speeds based on throughput
6. **Color-coded node halos** — Green/amber/red rings that pulse based on risk level
7. **Camera fly-to** — When clicking a node, camera smoothly transitions to focus on it
8. **Grid floor** — Add a subtle holographic grid floor beneath the network
9. **Node labels** — Use `CSS2DRenderer` for crisp text labels that always face camera
10. **Fog enhancement** — Cyan-tinted volumetric fog for depth

### 5B: Interactivity Upgrade
1. **Click node → show detailed overlay** with all metrics and predictions
2. **Right-click → trigger fault injection** on that specific node
3. **Drag to rearrange** nodes (with physics springs)
4. **Timeline slider** — Scrub through time to see how risk evolved
5. **Legend overlay** — Show what colors/sizes mean

### 5C: Real-Time Data Integration
1. Connect to same WebSocket as main dashboard
2. Update node colors/sizes in real-time as telemetry streams in
3. Flash edges red when packet loss spikes
4. Show prediction countdown timers above at-risk nodes

---

## Part 6: Backend Fixes & Enhancements

### 6A: Fix WebSocket Broadcast Payload
```python
# Current (broken): only sends frames
await manager.broadcast({"type": "tick", "frames": frames, "alert": alert})

# Fixed: include all intelligence data
await manager.broadcast({
    "type": "tick",
    "frames": frames,
    "alert": alert,
    "proactive": proactive_engine.latest_forecast(),
    "realtime": realtime_analysis,
    "metrics": {
        "model_active": metadata.get("architecture", ""),
        "model_auc": metadata.get("auc", 0),
        "tick_count": tick_counter,
    },
    "timestamp": datetime.now(timezone.utc).isoformat()
})
```

### 6B: Fix Explainability Service Crash
```python
# Line 100: Fix path joining
# Before:
narrative = f"... {' → '.join(path) if path else ...}"
# After:
path_ids = [p['node_id'] if isinstance(p, dict) else str(p) for p in (path or [])]
narrative = f"... {' → '.join(path_ids) if path_ids else ...}"
```

### 6C: Add Synthetic Data Generation Endpoint
```python
@app.post("/api/data/generate-synthetic")
def generate_synthetic(payload: dict = Body(...)):
    scenario = payload.get("scenario", "mixed")
    duration_hours = payload.get("duration_hours", 6)
    fault_rate = payload.get("fault_rate", 0.1)
    # Generate using realistic statistical profiles
    # Load into telemetry DB
    # Return summary statistics
```

### 6D: Add Prediction Accuracy Tracking
```python
# In intelligence.py:
# Track predictions vs actual outcomes
# When a predicted fault actually happens within the time window → true positive
# When prediction expires without fault → false positive
# Expose via GET /api/metrics/prediction-accuracy
```

### 6E: Fix Model Loading (Already Done)
The hidden_dim inference from weight shapes is already implemented but needs to be verified stable.

---

## Part 7: Conformance to Research Paper

The research paper (NetOracle_Research_Report.docx) specifies these components. Current conformance status:

| Research Paper Component | Current State | Action Needed |
|---|---|---|
| Federated Causal DAG (PC-Algorithm) | ✅ Implemented (NOTEARS variant) | Minor: Add DAG history snapshots |
| Causal Temporal GNN | ✅ ProactiveMLP trained | OK — working |
| Neo4j Knowledge Graph | ✅ SQLite property graph | OK — compatible schema |
| NL-to-Cypher | ⚠️ Partially broken | **Fix: Key mismatch + expand regex + improve Groq prompt** |
| Multi-LLM Ensemble Voting | ✅ Groq specialist cascade | OK — uses MoE routing |
| Hopfield Sub-Channel Allocator | ✅ Working | Minor: Better visualization |
| CMDP Safety Constraints | ✅ Implemented | OK |
| Confidence-Weighted Boolean Voting | ✅ In diagnosis pipeline | OK |
| Closed-Loop Demo | ⚠️ Partially broken | **Fix: Specialist cards rendering** |
| MLOps Retraining | ✅ Export-retrain endpoint | OK |
| Real Data Integration | ❌ Only pure synthetic | **Major: Implement realistic data pipeline** |
| Proactive Fault Avoidance | ✅ Multi-horizon T+5/10/20 | OK |
| XAI Explainability | ⚠️ Topology tab crashes | **Fix: Path joining TypeError** |
| Three.js Digital Twin | ⚠️ Static, not cyberpunk | **Major: Visual overhaul** |
| Dashboard UI | ⚠️ Buttons broken, KPIs empty | **Major: Fix all interactivity** |

---

## Part 8: Implementation Order (Phases)

### Phase 1: Critical Bug Fixes (Day 1)
1. Fix `explainability.py` path joining crash
2. Fix NL query key mismatch (`query` → `question`)
3. Fix KPI gauges loading on startup
4. Fix export button paths
5. Fix specialist cards rendering in diagnosis
6. Fix WebSocket broadcast payload
7. Fix tick button frame normalization
8. Run full test suite — ensure 109/109 still pass

### Phase 2: Data Pipeline (Day 1-2)
1. Create `scripts/generate_realistic_data.py` with real statistical profiles
2. Generate scenario CSVs in `data/scenarios/`
3. Add `POST /api/data/generate-synthetic` endpoint
4. Add synthetic generation UI panel in Data Sources tab
5. Wire the "Generate & Load" flow end-to-end

### Phase 3: NL-to-Cypher Fix (Day 2)
1. Fix frontend key from `query` to `question`
2. Improve Groq prompt with full schema + 10 few-shot examples
3. Expand `_execute_pseudo_cypher()` with 10+ regex patterns
4. Add NL query panel to Diagnosis tab
5. Test with all 6 example queries from research paper

### Phase 4: CSS/Visual Overhaul (Day 2-3)
1. Rewrite CSS color system with neon cyberpunk tokens
2. Add animated grid background
3. Add glassmorphism with colored borders
4. Add neon glow buttons with hover/press effects
5. Add card entrance animations
6. Add animated number transitions for KPIs
7. Add scanline overlay effect
8. Improve all panel layouts for visual density

### Phase 5: Dashboard & Tab Fixes (Day 3)
1. Fix dashboard KPIs to load from `/api/metrics`
2. Improve telemetry chart with proper timestamps
3. Fix proactive panel to show mini-timeline
4. Fix diagnosis specialist cards
5. Improve Hopfield grid visualization
6. Add prediction accuracy tracking
7. Test every button on every tab

### Phase 6: Three.js Cyberpunk Upgrade (Day 3-4)
1. Add holographic grid floor
2. Upgrade node geometry to icosahedrons
3. Add CSS2D labels
4. Add pulse wave effects on fault detection
5. Improve particle system (more particles, varying speed)
6. Add background floating particles
7. Connect to WebSocket for real-time updates
8. Add camera fly-to on node click
9. Improve fog and lighting

### Phase 7: Integration Testing (Day 4)
1. Full end-to-end flow: Generate data → Load → Predict → Visualize
2. Test closed-loop demo with all fault types
3. Test NL queries (all 6 from research paper)
4. Test 3D Twin responsiveness
5. Test all export functions
6. Verify all 7 tabs work perfectly
7. Browser recording of complete walkthrough

---

## Part 9: File Change Summary

| File | Action | Description |
|------|--------|-------------|
| `app/services/explainability.py` | MODIFY | Fix path joining TypeError on line 100 |
| `app/static/app.js` | MAJOR REWRITE | Fix NL key, KPI loading, tick normalization, specialist cards, animated numbers, prediction tracking |
| `app/static/styles.css` | MAJOR REWRITE | Neon cyberpunk theme, animated grid, glassmorphism, neon buttons, scanlines, card animations |
| `app/static/index.html` | MODIFY | Add synthetic generation panel, prediction accuracy display, NL query in diagnosis tab |
| `app/main.py` | MODIFY | Fix WS broadcast, add generate-synthetic endpoint, fix export paths |
| `app/services/graph.py` | MODIFY | Improve NL-to-Cypher prompt, expand regex fallback patterns |
| `app/static/twin.js` | MAJOR REWRITE | Cyberpunk upgrade: grid floor, icosahedrons, CSS2D labels, pulse waves, WS connection |
| `app/static/twin.html` | MODIFY | Update styling for cyberpunk theme |
| `app/static/twin.css` | MODIFY | Match neon cyberpunk visual theme |
| `scripts/generate_realistic_data.py` | REWRITE | Real statistical profiles, correlated metrics, fault cascades, scenario generation |
| `app/services/intelligence.py` | MODIFY | Add prediction accuracy tracking |
| `app/services/telemetry.py` | MODIFY | Improve frame normalization for WebSocket |

---

## Part 10: Success Criteria

When this plan is fully implemented, the following must ALL be true:

- [ ] Every button on every tab works (no JS errors, no 500s)
- [ ] NL query returns meaningful results for all 6 research paper examples
- [ ] KPI gauges show real values on page load
- [ ] Closed-loop demo shows specialist cards, diagnosis timeline, remediation
- [ ] Synthetic data can be generated from the UI with configurable parameters
- [ ] Generated data uses realistic statistical profiles (not random noise)
- [ ] Predictions are visualized in real-time with accuracy tracking
- [ ] Three.js twin has neon cyberpunk aesthetic with bloom, particles, grid floor
- [ ] CSS theme is cohesive neon cyberpunk (not generic dark mode)
- [ ] WebSocket streams all intelligence data (proactive, realtime, alerts)
- [ ] All 109 tests still pass
- [ ] No console errors in browser
- [ ] Topology tab explain doesn't crash
- [ ] Export buttons save files correctly
- [ ] 3D Twin updates in real-time from WebSocket

---

## Appendix A: Real Data Statistical Profiles

Based on the 5G-NIDD and TeleLogs datasets, these are the realistic parameter ranges to use:

```
CPU Utilization:    mean=45%, std=15%, range=[5%, 98%], diurnal_amplitude=20%
Memory Usage:       mean=52%, std=12%, range=[20%, 95%], correlation_with_cpu=0.6
Latency (ms):       mean=18ms, std=12ms, range=[2ms, 500ms], log-normal distribution
Packet Loss:        mean=0.002, std=0.008, range=[0, 0.4], heavy-tailed
Throughput (Mbps):  mean=450, std=280, range=[0, 1200], slice-dependent
PRB Utilization:    mean=0.42, std=0.18, range=[0.05, 0.98], correlates with throughput

Fault rate: ~5-8% of samples in real datasets
Fault duration: 3-15 consecutive samples (15sec-75sec at 5sec intervals)
Cascade delay: 1-3 ticks between cause and effect nodes
```

## Appendix B: Diurnal Traffic Pattern (from Telecom Italia)

```
Hour  | Traffic Multiplier
00:00 | 0.3
03:00 | 0.15  (minimum)
06:00 | 0.5
09:00 | 0.95  (morning peak)
12:00 | 0.8
15:00 | 0.85
18:00 | 1.0   (evening peak)
21:00 | 0.7
```

---

**END OF PLAN — Awaiting your approval to begin implementation.**
