#!/usr/bin/env python3
"""
Run reproducible live Open5GS fault scenarios and save local evidence artifacts.

Outputs:
  - reports/live_fault_scenarios.json
  - EVIDENCE_REPORT.md
  - DEMO_SCRIPT.md

The harness is intentionally conservative: it records missing detections instead
of inventing success, and it restores the stack after every scenario attempt.
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests


DEFAULT_NETORACLE_URL = os.getenv("NETORACLE_URL", "http://127.0.0.1:8000").rstrip("/")
DEFAULT_FAULT_API_URL = os.getenv("FAULT_API_URL", "http://127.0.0.1:5050").rstrip("/")
DEFAULT_IMSI = os.getenv("OPEN5GS_TEST_IMSI", "999700000000001")

SCENARIOS = {
    "upf_kill": {
        "endpoint": "/inject/upf_kill",
        "params": {},
        "expected_signal": "UPF service stops; user-plane traffic should drop.",
    },
    "bandwidth_throttle": {
        "endpoint": "/inject/bandwidth_throttle",
        "params": {"rate_kbps": 500, "latency_ms": 200},
        "expected_signal": "Latency rises and throughput drops on uesimtun0/UPF path.",
    },
    "gnb_drop": {
        "endpoint": "/inject/gnb_drop",
        "params": {},
        "expected_signal": "UERANSIM gNB process exits; AMF/gNB telemetry should degrade.",
    },
    "subscriber_auth_failure": {
        "endpoint": "/inject/subscriber_auth_failure",
        "params": {"imsi": DEFAULT_IMSI},
        "expected_signal": "Subscriber authentication fails on next registration.",
    },
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def request_json(method: str, url: str, **kwargs) -> dict[str, Any]:
    response = requests.request(method, url, timeout=kwargs.pop("timeout", 15), **kwargs)
    response.raise_for_status()
    return response.json()


def source_distribution(frames: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for frame in frames:
        source = str(frame.get("source", "unknown"))
        counts[source] = counts.get(source, 0) + 1
    return counts


def poll_detection(
    netoracle_url: str,
    fault_type: str,
    started_epoch: float,
    timeout_s: int,
    poll_interval_s: float,
) -> dict[str, Any]:
    attempts = []
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        attempt_started = time.time()
        try:
            analysis = request_json(
                "GET",
                f"{netoracle_url}/api/realtime/analyse",
                params={"generate_tick": "true", "run_diagnosis": "true"},
                timeout=30,
            ).get("data", {})
            frames = analysis.get("frames", [])
            alert = analysis.get("alert")
            diagnosis = analysis.get("diagnosis")
            remediation = analysis.get("remediation")
            detected = bool(alert)
            attempts.append({
                "timestamp": utc_now(),
                "latency_ms": round((time.time() - attempt_started) * 1000, 2),
                "detected": detected,
                "source_distribution": source_distribution(frames),
                "alert": alert,
            })
            if detected:
                return {
                    "detected": True,
                    "detected_at": utc_now(),
                    "time_to_detection_s": round(time.time() - started_epoch, 3),
                    "alert": alert,
                    "diagnosis": diagnosis,
                    "remediation": remediation,
                    "source_distribution": source_distribution(frames),
                    "poll_attempts": attempts,
                }
        except Exception as exc:
            attempts.append({
                "timestamp": utc_now(),
                "detected": False,
                "error": str(exc),
            })
        time.sleep(poll_interval_s)

    return {
        "detected": False,
        "detected_at": None,
        "time_to_detection_s": None,
        "alert": None,
        "diagnosis": None,
        "remediation": None,
        "source_distribution": {},
        "poll_attempts": attempts,
    }


def call_aci_update(netoracle_url: str, alert: dict[str, Any] | None, true_label: float) -> dict[str, Any] | None:
    if not alert or alert.get("fault_probability") is None:
        return None
    try:
        return request_json(
            "POST",
            f"{netoracle_url}/api/conformal/update",
            params={"prediction": float(alert["fault_probability"]), "true_label": true_label},
            timeout=10,
        ).get("data")
    except Exception as exc:
        return {"error": str(exc)}


def restore_all(fault_api_url: str) -> dict[str, Any]:
    try:
        return request_json("POST", f"{fault_api_url}/inject/restore_all", timeout=45)
    except Exception as exc:
        return {"ok": False, "error": str(exc), "timestamp": utc_now()}


def run_one(
    name: str,
    repeat: int,
    netoracle_url: str,
    fault_api_url: str,
    timeout_s: int,
    poll_interval_s: float,
) -> dict[str, Any]:
    spec = SCENARIOS[name]
    scenario_id = f"{name}_{repeat}_{int(time.time())}"
    restore_before = restore_all(fault_api_url)
    injected_at = utc_now()
    started_epoch = time.time()
    injection = request_json(
        "POST",
        f"{fault_api_url}{spec['endpoint']}",
        params=spec.get("params", {}),
        timeout=45,
    )
    detection = poll_detection(netoracle_url, name, started_epoch, timeout_s, poll_interval_s)
    aci_update = call_aci_update(netoracle_url, detection.get("alert"), 1.0 if detection.get("detected") else 0.0)
    restore_after = restore_all(fault_api_url)
    return {
        "scenario_id": scenario_id,
        "fault_type": name,
        "repeat": repeat,
        "expected_signal": spec["expected_signal"],
        "injected_at": injected_at,
        "injection": injection,
        "detected": detection["detected"],
        "detected_at": detection["detected_at"],
        "time_to_detection_s": detection["time_to_detection_s"],
        "alert": detection["alert"],
        "diagnosis": detection["diagnosis"],
        "remediation": detection["remediation"],
        "cmdp_decision": (detection.get("remediation") or {}).get("rl_recommendation"),
        "source_distribution": detection["source_distribution"],
        "poll_attempts": detection["poll_attempts"],
        "aci_update": aci_update,
        "restore_before": restore_before,
        "restore_after": restore_after,
        "completed_at": utc_now(),
    }


def summarize(scenarios: list[dict[str, Any]]) -> dict[str, Any]:
    detected = [s for s in scenarios if s.get("detected")]
    mttd = [float(s["time_to_detection_s"]) for s in detected if s.get("time_to_detection_s") is not None]
    by_fault: dict[str, list[float]] = {}
    for scenario in detected:
        if scenario.get("time_to_detection_s") is None:
            continue
        by_fault.setdefault(str(scenario["fault_type"]), []).append(float(scenario["time_to_detection_s"]))
    return {
        "total": len(scenarios),
        "detected": len(detected),
        "detection_rate": round(len(detected) / max(len(scenarios), 1), 4),
        "mean_time_to_detection_s": round(statistics.mean(mttd), 3) if mttd else None,
        "mttd_by_fault_s": {
            fault: round(statistics.mean(values), 3)
            for fault, values in by_fault.items()
        },
    }


def write_json_report(output: Path, payload: dict[str, Any]) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def write_markdown_artifacts(payload: dict[str, Any]) -> None:
    summary = payload.get("summary", {})
    scenario_rows = "\n".join(
        f"| {s.get('fault_type')} | {s.get('repeat')} | {s.get('detected')} | {s.get('time_to_detection_s')} | {s.get('source_distribution')} |"
        for s in payload.get("scenarios", [])
    )
    Path("EVIDENCE_REPORT.md").write_text(
        "\n".join([
            "# NetOracle Evidence Report",
            "",
            f"Generated: {payload.get('generated_at')}",
            "",
            "## Live Fault Scenario Summary",
            "",
            f"- Total scenarios: {summary.get('total', 0)}",
            f"- Detected: {summary.get('detected', 0)}",
            f"- Detection rate: {summary.get('detection_rate')}",
            f"- Mean time to detection: {summary.get('mean_time_to_detection_s')} seconds",
            "",
            "| Fault | Repeat | Detected | MTTD (s) | Source distribution |",
            "|---|---:|---|---:|---|",
            scenario_rows or "| none | 0 | false |  |  |",
            "",
            "## What Is Real vs Simulated",
            "",
            "- `open5gs_live`: Prometheus was reachable and the NF query path succeeded for that frame.",
            "- `open5gs_partial`: Prometheus was reachable but an NF fetch path used fallback values.",
            "- `open5gs_simulated`: Open5GS/Prometheus was unreachable and fallback telemetry was used.",
            "- Remediation is simulated unless `REMEDIATION_MODE` is changed deliberately.",
            "",
            "## Local Artifacts",
            "",
            "- `reports/live_fault_scenarios.json`",
            "- `reports/benchmarks_live_vs_simulated.json`",
            "- `artifacts/open5gs_metric_registry.json`",
            "- `artifacts/conformal_calibration_live.json`",
        ]) + "\n",
        encoding="utf-8",
    )
    Path("DEMO_SCRIPT.md").write_text(
        "\n".join([
            "# NetOracle Demo Script",
            "",
            "## Preflight",
            "",
            "1. Start Open5GS, UERANSIM, Prometheus, MongoDB, and NetOracle.",
            "2. Run `python scripts/verify_open5gs_integration.py --strict`.",
            "3. Open `http://127.0.0.1:8000` and confirm the source banner is `LIVE - Open5GS`.",
            "4. Run `python scripts/live_fault_scenarios.py --repeats 1` for a short evidence refresh.",
            "",
            "## Live Demo",
            "",
            "1. Show `/api/open5gs/metrics/registry` and the local metric registry artifact.",
            "2. Inject a fault through the WSL fault API.",
            "3. Watch the dashboard alert, diagnosis, CMDP decision, and evidence panel update.",
            "4. Show `reports/live_fault_scenarios.json` and `EVIDENCE_REPORT.md`.",
            "",
            "## Fallback",
            "",
            "If WSL networking fails, switch to simulated mode and clearly state the source banner is simulated.",
        ]) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Run NetOracle live Open5GS fault scenarios.")
    parser.add_argument("--netoracle-url", default=DEFAULT_NETORACLE_URL)
    parser.add_argument("--fault-api-url", default=DEFAULT_FAULT_API_URL)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--timeout-s", type=int, default=90)
    parser.add_argument("--poll-interval-s", type=float, default=5.0)
    parser.add_argument("--output", default="reports/live_fault_scenarios.json")
    parser.add_argument("--fault", action="append", choices=sorted(SCENARIOS), help="Run only selected fault(s).")
    args = parser.parse_args()

    selected = args.fault or list(SCENARIOS)
    results: list[dict[str, Any]] = []
    output = Path(args.output)

    for repeat in range(1, args.repeats + 1):
        for name in selected:
            print(f"[{utc_now()}] Running {name} repeat {repeat}/{args.repeats}")
            try:
                result = run_one(name, repeat, args.netoracle_url.rstrip("/"), args.fault_api_url.rstrip("/"), args.timeout_s, args.poll_interval_s)
            except Exception as exc:
                result = {
                    "scenario_id": f"{name}_{repeat}_{int(time.time())}",
                    "fault_type": name,
                    "repeat": repeat,
                    "detected": False,
                    "error": str(exc),
                    "restore_after": restore_all(args.fault_api_url.rstrip("/")),
                    "completed_at": utc_now(),
                }
            results.append(result)
            payload = {
                "generated_at": utc_now(),
                "netoracle_url": args.netoracle_url,
                "fault_api_url": args.fault_api_url,
                "summary": summarize(results),
                "scenarios": results,
            }
            write_json_report(output, payload)
            write_markdown_artifacts(payload)
            print(f"  detected={result.get('detected')} mttd={result.get('time_to_detection_s')}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
