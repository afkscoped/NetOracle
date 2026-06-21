# NetOracle Evidence Report

Generated status: pending live Open5GS scenario run.

## Current Evidence Contract

NetOracle separates telemetry source states explicitly:

- `open5gs_live`: Prometheus is reachable and the NF query path succeeded for that frame.
- `open5gs_partial`: Prometheus is reachable, but at least one NF path used fallback values.
- `open5gs_simulated`: Open5GS or Prometheus is unreachable, so fallback telemetry was used.
- `simulation`: synthetic-only mode.

Remediation remains simulated unless `REMEDIATION_MODE` is deliberately changed.

## Local Artifacts

- `NETORACLE_EVIDENCE_IMPLEMENTATION_PLAN.md`
- `artifacts/open5gs_metric_registry.json` after `/api/open5gs/metrics/registry`
- `reports/live_fault_scenarios.json` after `scripts/live_fault_scenarios.py`
- `reports/benchmarks_live_vs_simulated.json` after `/api/benchmarks/live`
- `artifacts/conformal_calibration_live.json` after ACI live updates

## Live Fault Scenario Summary

Run:

```powershell
.\.venv\Scripts\python.exe scripts\live_fault_scenarios.py --repeats 3
```

Then this report can be regenerated from the scenario harness output.

| Fault | Repeats | Detection Rate | Mean MTTD |
|---|---:|---:|---:|
| pending | 0 | pending | pending |

## What Remains Unverified

- Open5GS metric names remain assumptions until `artifacts/open5gs_metric_registry.json` marks them present.
- Live CTGNN vs heuristic performance remains unreported until fault scenario labels exist.
- NOTEARS live validation remains pending until enough live-only rows are collected.
