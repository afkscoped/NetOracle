# Phase 1 Audit Notes — NetOracle Telemetry Pipeline

> Written as part of Phase 1 (Audit & Schema Lock) of the Open5GS live integration.
> Every claim here is backed by reading the actual source files, not assumptions.

---

## 1. Telemetry Frame Schema: Full Lifecycle

### 1a. At the Adapter (output of `get_tick()`)

Both `SimulationAdapter` (data_sources.py) and `Open5GSAdapter` (open5gs_adapter.py) emit a **list of dicts** with this schema:

```
{
  "timestamp":       str   — ISO-8601 UTC (e.g. "2026-06-20T15:30:00.123456+00:00")
  "slice_id":        str   — e.g. "slice_1", "slice_2", "slice_3"
  "node_id":         str   — e.g. "upf_1", "amf_1", "gnb_1"
  "node_type":       str   — "UPF" | "AMF" | "SMF" | "PCF" | "NRF" | "gNB" | "Router"
  "cpu":             float — 0–100
  "memory":          float — 0–100
  "latency_ms":      float — milliseconds
  "packet_loss":     float — 0.0–1.0
  "throughput_mbps": float — megabits/second
  "prb_utilization": float — 0.0–1.0
  "fault_label":     int   — 0 or 1
  "fault_type":      str   — e.g. "upf_packet_loss", "" if no fault
  "source":          str   — "open5gs_live" | "open5gs_simulated" | "simulated" | "csv_stream" | "prometheus"
}
```

**Open5GSAdapter only also includes** (prefixed with `_`, not stored to DB):
```
  "_raw_ue_count", "_raw_session_count",    # AMF frame
  "_raw_pdu_count",                          # SMF frame
  "_raw_throughput_bps", "_raw_drop_rate",  # UPF frame
  "_raw_rule_count",                         # PCF frame
  "_active_sessions"                         # if MongoDB available
```

### 1b. Database Insert (`db.insert_telemetry`)

In `database.py` L134–144, `insert_telemetry` stores:
- `timestamp`, `slice_id`, `node_id`, `node_type` → direct columns
- `metrics_json` → JSON-encoded dict containing ONLY the metric fields:
  `{cpu, memory, latency_ms, packet_loss, throughput_mbps, prb_utilization}`
- `fault_label`, `fault_type` → direct columns

**CRITICAL GAP FOUND**: The `source` field is NOT stored to the telemetry table.
The `metrics` column in DB only holds the 6 numeric metrics.
When rows are read back via `db.latest_telemetry()`, `source` is absent.

**Fix required**: Store `source` in `metrics_json` so it round-trips correctly,
OR add a `source` column to the telemetry table.
→ Decision: store `source` inside `metrics_json` since it is contextual metadata
  (adding a column requires a schema migration).

### 1c. After `telemetry_service.generate_tick()`

In `app/services/telemetry.py`, `generate_tick()` calls the adapter, then calls
`db.insert_telemetry()` for each frame. The frame returned to the caller is the
raw adapter output — `source` IS present at this point.

The frame returned to `/api/telemetry/tick` and `auto_tick()` still has `source`.

### 1d. WebSocket Broadcast (`auto_tick()`)

In `main.py` L103–112, the broadcast payload is:
```json
{
  "type": "tick",
  "frames": [<list of raw adapter frames>],
  "alert": <intelligence_service.predict_latest()>,
  "proactive": <proactive_engine.latest()>,
  "realtime": <realtime_engine.analyse_once()>,
  "metrics": <intelligence_service.metrics()>,
  "source": frames[0].get("source", "unknown"),
  "timestamp": "ISO-8601"
}
```

✅ The `source` field DOES propagate to the WebSocket payload.
The frontend JS at app.js L610–650 receives this correctly.

---

## 2. DATA_SOURCE_MODE Branch Points

| Location | What It Does |
|----------|-------------|
| `data_sources.py` `get_adapter()` | Main router — reads `os.environ["DATA_SOURCE_MODE"]` or `settings.data_source_mode` |
| `main.py` `auto_tick()` L88 | Calls `telemetry_service.generate_tick()` — mode-agnostic |
| `main.py` `/api/data/switch-mode` L225 | Runtime switch: writes env var, calls `reset_adapter()` |
| `open5gs_adapter.py` `get_tick()` L512 | Internal: checks `prom.is_available()` → sets source tag |
| `verify_open5gs_integration.py` L14 | Reads `OPEN5GS_PROMETHEUS_URL` from env for direct checks |

There is NO branch on `DATA_SOURCE_MODE` inside `intelligence.py`, `conformal.py`,
or `benchmarks.py` — the ML pipeline is source-agnostic. ✅ Good design.

---

## 3. Prometheus Metric Names — Open5GS Adapter

All metric names below are from `open5gs_adapter.py` L51–79 and usage in `_fetch_*` methods.
**Status: ASSUMED — not yet verified against a live Open5GS /metrics endpoint.**

### AMF (port 9095) — `_fetch_amf_metrics()`
| PromQL Used | Expected Metric | Status |
|------------|-----------------|--------|
| `amf_session_count` | Active session count | ⚠️ ASSUMED — may be `amf_session` or absent in older builds |
| `amf_ue_context_count` | Connected UE count | ⚠️ ASSUMED |
| `amf_registration_request_total` | Registration attempts | ⚠️ ASSUMED |
| `amf_registration_success_total` | Successful registrations | ⚠️ ASSUMED |
| `avg(rate(node_cpu_seconds_total{mode="idle"}[30s])) * 100` | CPU idle | ✅ Standard node_exporter |
| `node_memory_MemAvailable_bytes` | Memory available | ✅ Standard node_exporter |
| `node_memory_MemTotal_bytes` | Memory total | ✅ Standard node_exporter |

### SMF (port 9096) — `_fetch_smf_metrics()`
| PromQL Used | Expected Metric | Status |
|------------|-----------------|--------|
| `smf_pdu_session_count` | Active PDU sessions | ⚠️ ASSUMED |
| `smf_pdu_session_created_total` | PDU sessions created | ⚠️ ASSUMED |
| `smf_pdu_session_released_total` | PDU sessions released | ⚠️ ASSUMED |

### UPF (port 9097) — `_fetch_upf_metrics()`
| PromQL Used | Expected Metric | Status |
|------------|-----------------|--------|
| `upf_rx_bytes_total` | Received bytes counter | ⚠️ ASSUMED |
| `upf_tx_bytes_total` | Transmitted bytes counter | ⚠️ ASSUMED |
| `upf_rx_packets_total` | Received packets counter | ⚠️ ASSUMED |
| `upf_tx_packets_total` | Transmitted packets counter | ⚠️ ASSUMED |
| `upf_dropped_packets_total` | Dropped packets counter | ⚠️ ASSUMED |

### PCF (port 9098) — `_fetch_pcf_metrics()`
| PromQL Used | Expected Metric | Status |
|------------|-----------------|--------|
| `pcf_policy_rule_count` | Active policy rules | ⚠️ ASSUMED |

### gNB / UERANSIM — via node_exporter `_fetch_gnb_metrics()`
| PromQL Used | Expected Metric | Status |
|------------|-----------------|--------|
| `rate(node_network_receive_bytes_total{device="uesimtun0"}[30s])` | gNB RX rate via tunnel | ✅ Standard; depends on uesimtun0 existing |
| `rate(node_network_transmit_bytes_total{device="uesimtun0"}[30s])` | gNB TX rate via tunnel | ✅ Standard; depends on uesimtun0 existing |

### Verification procedure (run once Open5GS is up):
```bash
curl -s http://localhost:9095/metrics | grep -E "^amf_" | head -30
curl -s http://localhost:9096/metrics | grep -E "^smf_" | head -30
curl -s http://localhost:9097/metrics | grep -E "^upf_" | head -30
curl -s http://localhost:9098/metrics | grep -E "^pcf_" | head -30
```
Update this file and add `# VERIFIED AGAINST Open5GS vX.X.X on DATE` comments
in `open5gs_adapter.py` for each confirmed metric.

---

## 4. Source Tag Propagation — Status

| Stage | source field present? | Value when live | Value when fallback |
|-------|----------------------|-----------------|---------------------|
| `Open5GSAdapter.get_tick()` | ✅ Yes (L559) | `"open5gs_live"` | `"open5gs_simulated"` |
| `SimulationAdapter.get_tick()` | ✅ Yes | N/A | `"simulated"` |
| `db.insert_telemetry()` | ❌ NOT STORED | — | — |
| `db.latest_telemetry()` return | ❌ NOT PRESENT | — | — |
| `main.py` WS broadcast `.frames` | ✅ Yes (in raw frame) | `"open5gs_live"` | `"open5gs_simulated"` |
| `main.py` WS broadcast `.source` | ✅ Yes (L110) | `"open5gs_live"` | `"open5gs_simulated"` |
| Frontend `handleTick()` L613 | ✅ Received | — reads `payload.source` | — |
| Frontend status banner | ❌ NOT IMPLEMENTED | banner missing | banner missing |

**Fix list for Phase 1:**
1. Add `source` to the metrics_json stored in DB (so it's available for benchmarks)
2. Add `source` to the `metrics` dict schema in `insert_telemetry`
3. Implement live/simulated status banner in frontend

---

## 5. Known Bugs Found in Phase 1 Audit

| # | File | Line | Bug | Fix |
|---|------|------|-----|-----|
| B1 | `explainability.py` | ~100 | `' → '.join(path)` crashes if path contains dicts | `str(p.get('node_id', p) if isinstance(p, dict) else p)` |
| B2 | `app.js` | 675 | `btnTick` calls `handleTick({frames: r.data})` — missing alert/proactive/realtime/metrics | Extend to full tick payload or call `/api/demo/run` |
| B3 | `app.js` | 687–688 | Export buttons call `/api/cloud/export-audit` and `/api/cloud/export-benchmark` — endpoints are `/api/cloud/export` | Fix URL paths |
| B4 | `app.js` | 756 | `askQuestion` sends `{question: ...}` ✅ — already correct, no bug |
| B5 | `app.js` | N/A | No live/simulated status banner reacting to WS payload source | Add banner element + JS update on every tick |
| B6 | `app.js` | 620–621 | KPI gauges not initialized on page load — `updateKpis` only called in `handleTick` | Call `refreshMetrics()` on init and wire KPIs |
| B7 | `database.py` | 134 | `source` field not persisted — benchmarks can't reconstruct data origin | Store source in metrics_json |

---

## 6. Fallback Behavior Audit

In `open5gs_adapter.py`:
- L514–520: logs `logger.warning("[Open5GS] Prometheus not reachable ...")` ONLY ONCE (first time).
  Subsequent fallback ticks are SILENT. Fix: re-log every N ticks or use a rate-limited logger.
- L559: `"open5gs_live" if prom_available else "open5gs_simulated"` — correct, deterministic.
- Per-NF fetch failure (L540–542): falls back to `_sim_fallback_metrics()` but the frame is
  still tagged `"open5gs_live"` if Prometheus server is reachable! A partial live + partial sim
  frame gets tagged `"open5gs_live"` even if, say, the AMF metrics endpoint was down.

**Fix required**: Per-NF source tracking — if a specific NF's fetch fails, tag that frame
  `"open5gs_partial"` or add `"nf_data_source"` field to the frame.

---

## 7. WebSocket Reconnect Assessment

`connectWebSocket()` in `app.js` L632–651:
- `onclose` → sets status to "Reconnecting…", calls `setTimeout(connectWebSocket, 3000)` ✅
- After 5 failures → falls back to 15s polling ✅
- `onerror` → calls `ws.close()` which triggers `onclose` ✅

**Already functional.** Enhancement: add visual toast on reconnect + timestamp of last successful tick.

---

## 8. Action Items Before Phase 2

- [x] Write this PHASE2_NOTES.md
- [ ] Fix B7: store `source` in metrics_json in `database.py`
- [ ] Fix B2: `btnTick` handler — full tick payload  
- [ ] Fix B3: export URL paths
- [ ] Fix B5: add live/simulated banner to frontend
- [ ] Add ASSUMED comments to all metric names in `open5gs_adapter.py`
- [ ] Fix per-NF fallback source tagging (partial live frame)
- [ ] Add rate-limited fallback warning log (not just first-time)
