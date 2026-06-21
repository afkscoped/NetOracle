# NetOracle Evidence-First Industry-Grade Implementation Plan

## Summary

Build the next sprint around honest proof: WSL2 Open5GS live telemetry, verified metric mappings, reproducible fault scenarios, live-vs-simulated benchmarks, and a portfolio-ready evidence report. Existing UI/source/ACI/Safe-RL work is partly done, so do not rebuild it; harden and prove it.

## Key Changes

- Standardize Open5GS ports and runtime docs: Prometheus `9090`, AMF `9095`, SMF `9096`, UPF `9097`, PCF `9098`, Mongo `27017`, WebUI `3000`.
- Patch Open5GS NF YAML under each NF's `metrics.server` section instead of appending fragile top-level `metrics.addr/port` blocks.
- Add Prometheus metric discovery using `/api/v1/label/__name__/values` and save `artifacts/open5gs_metric_registry.json`.
- Preserve telemetry provenance through DB/API/WebSocket using optional `source_detail`, `evidence`, and `scenario_id`.
- Add `/api/evidence/latest`, `/api/open5gs/metrics/registry`, and `/api/benchmarks/live`.
- Add `scripts/live_fault_scenarios.py` to run real Open5GS fault scenarios and save `reports/live_fault_scenarios.json`.
- Save local portfolio artifacts: `EVIDENCE_REPORT.md`, `DEMO_SCRIPT.md`, `reports/benchmarks_live_vs_simulated.json`, `artifacts/conformal_calibration_live.json`.
- Keep remediation explicitly simulated unless `REMEDIATION_MODE` is deliberately changed.

## Test Plan

- Restore the local test environment and run `pytest`.
- Add focused tests for metric registry parsing, telemetry evidence preservation, live benchmark schema, and fault API defaults.
- Run `scripts/verify_open5gs_integration.py --strict` when WSL2 Open5GS is available.
- Run `scripts/live_fault_scenarios.py --repeats 3` against the live stack.
- Verify the UI shows live/partial/simulated source state and local evidence artifacts without claim leakage.

## Assumptions

- Priority is evidence-first.
- WSL2 Open5GS + UERANSIM will be available locally.
- Claims must remain explicit: live, partial, simulated, and unverified states are separate.
- All artifacts stay local to this repository under `artifacts/`, `reports/`, root markdown files, or `exports/`.
