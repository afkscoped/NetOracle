# NetOracle Demo Script

## Preflight

1. Start WSL2 Ubuntu.
2. Run `bash scripts/start_open5gs.sh`.
3. Start the WSL fault API: `sudo python3 scripts/fault_injection_api.py --host 0.0.0.0 --port 5050`.
4. Start NetOracle on Windows:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

5. Run the strict preflight:

```powershell
.\.venv\Scripts\python.exe scripts\verify_open5gs_integration.py --strict
```

6. Open `http://127.0.0.1:8000` and confirm the source banner shows `LIVE - Open5GS`.

## Evidence Refresh

1. Open `/api/open5gs/metrics/registry` or click the evidence refresh in the UI.
2. Confirm `artifacts/open5gs_metric_registry.json` exists.
3. Run:

```powershell
.\.venv\Scripts\python.exe scripts\live_fault_scenarios.py --repeats 1
```

4. Confirm `reports/live_fault_scenarios.json`, `EVIDENCE_REPORT.md`, and `DEMO_SCRIPT.md` are local.

## Live Walkthrough

1. Show the dashboard source banner and Evidence Trail panel.
2. Trigger one live fault through the WSL fault API.
3. Watch telemetry, alert, diagnosis, CMDP remediation decision, and ACI state update.
4. Open `reports/live_fault_scenarios.json` to show ground truth timestamps and MTTD.
5. Run `/api/benchmarks/live` to refresh `reports/benchmarks_live_vs_simulated.json`.

## Honest Scope Boundary

- Open5GS/UERANSIM traffic is live software-defined 5G core telemetry.
- Frames marked simulated or partial are not presented as live evidence.
- Remediation is safety-gated and simulated unless deliberately configured otherwise.
- Any missing metric in the registry remains an assumption until observed in Prometheus.

## Fallback

If WSL networking fails during a demo, switch to simulation mode and explicitly state that the live stack is unavailable. Use previously saved local artifacts for evidence review.
