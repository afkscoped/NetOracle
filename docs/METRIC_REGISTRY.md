# NetOracle — Open5GS Prometheus Metric Registry

This document maps every PromQL query in `open5gs_adapter.py` to its verification status.
Populated from static analysis. Requires live Open5GS + Prometheus instance to mark VERIFIED.

## Legend
- 🔴 `ASSUMED` — metric name inferred from Open5GS documentation/source; not tested against live Prometheus
- 🟡 `PARTIAL` — metric exists in Prometheus but value mapping/label uncertain
- 🟢 `VERIFIED` — confirmed against live Open5GS Prometheus instance

---

## AMF (Access and Mobility Management Function)

| PromQL Metric | Purpose | Status | Notes |
|---|---|---|---|
| `open5gs_amf_session_count` | Active session count → maps to `active_sessions` KPI | 🔴 ASSUMED | Also try `amf_session_active_total` |
| `open5gs_amf_ue_count` | Connected UE count | 🔴 ASSUMED | |
| `open5gs_amf_pdu_session_count` | PDU sessions | 🔴 ASSUMED | |

## UPF (User Plane Function)

| PromQL Metric | Purpose | Status | Notes |
|---|---|---|---|
| `open5gs_upf_session_count` | UPF sessions | 🔴 ASSUMED | |
| `rate(open5gs_upf_dl_bytes_total[30s]) * 8 / 1e6` | Downlink throughput Mbps | 🔴 ASSUMED | May be `upf_bytes_total` with direction label |
| `rate(open5gs_upf_ul_bytes_total[30s]) * 8 / 1e6` | Uplink throughput Mbps | 🔴 ASSUMED | |
| `rate(open5gs_upf_dl_drop_total[30s])` | Downlink packet drops | 🔴 ASSUMED | |
| `rate(open5gs_upf_ul_drop_total[30s])` | Uplink packet drops | 🔴 ASSUMED | |

## SMF (Session Management Function)

| PromQL Metric | Purpose | Status | Notes |
|---|---|---|---|
| `open5gs_smf_session_count` | SMF active sessions | 🔴 ASSUMED | |
| `open5gs_smf_pdu_session_count` | PDU sessions at SMF | 🔴 ASSUMED | |

## PCF (Policy Control Function)

| PromQL Metric | Purpose | Status | Notes |
|---|---|---|---|
| `open5gs_pcf_session_count` | PCF sessions | 🔴 ASSUMED | |

## AUSF / UDM / NRF / NSSF / BSF

| NF | PromQL | Status |
|---|---|---|
| AUSF | `open5gs_ausf_auth_count` | 🔴 ASSUMED |
| UDM | `open5gs_udm_ue_count` | 🔴 ASSUMED |
| NRF | `open5gs_nrf_nf_count` | 🔴 ASSUMED |
| NSSF | `open5gs_nssf_session_count` | 🔴 ASSUMED |
| BSF | `open5gs_bsf_session_count` | 🔴 ASSUMED |

---

## Verification Procedure

### Prerequisites
- WSL2 running with Open5GS stack deployed
- Prometheus scraping Open5GS (`localhost:9090`)

### Steps

```bash
# 1. List ALL available Open5GS metrics
curl -s http://localhost:9090/api/v1/label/__name__/values | python -m json.tool | grep open5gs

# 2. Test specific metric
curl -s "http://localhost:9090/api/v1/query?query=open5gs_amf_session_count" | python -m json.tool

# 3. Run NetOracle metric registry endpoint
curl http://localhost:8000/api/open5gs/metrics/registry

# 4. For each metric found, update this document: 🔴 → 🟢
# 5. Fix wrong names in app/services/open5gs_adapter.py _METRIC_REGISTRY dict
```

### What to check in the adapter

```python
# File: app/services/open5gs_adapter.py
# Dict: _METRIC_REGISTRY (maps NF name → list of PromQL expressions)
# Method: _query_prometheus() — retries 3x with exponential backoff
# Method: _collect_nf_metrics() — per-NF metric collection with partial fallback
```

---

## MongoDB Subscriber Data

| Collection | Expected Schema | Status |
|---|---|---|
| `subscribers` | `{ imsi, supi, msisdn, slice, active }` | 🔴 ASSUMED |
| `sessions` | `{ imsi, apn, ip, state }` | 🔴 ASSUMED |

### Verification
```bash
# In WSL2
mongosh open5gs --eval "db.subscribers.findOne()"
```

---

## Known Issues & Workarounds

1. **Metric names may differ by Open5GS version** — v2.6 vs v2.7 renamed several counters
2. **Label keys are inconsistent** — some NFs use `nf_type`, others use `instance`
3. **Rate calculations** — `[30s]` window may need tuning based on scrape interval (default: 15s)

---

*Last updated: 2026-06-21 | Branch: feature/open5gs-live-integration*
*Status: PRE-VERIFICATION (all metrics ASSUMED — no live Open5GS instance available for testing)*
