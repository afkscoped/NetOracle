from __future__ import annotations

import argparse
import csv
import json
import math
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import mean
from typing import Any


METRICS = ["cpu", "memory", "latency_ms", "packet_loss", "throughput_mbps", "prb_utilization"]

SLICE_PROFILES = {
    "slice_1": {"name": "eMBB", "throughput_scale": 1.35, "latency_scale": 0.85, "prb_scale": 1.05},
    "slice_2": {"name": "mMTC", "throughput_scale": 0.55, "latency_scale": 1.55, "prb_scale": 0.75},
    "slice_3": {"name": "URLLC", "throughput_scale": 0.95, "latency_scale": 0.45, "prb_scale": 0.95},
}

BASE_PROFILE = {
    "cpu": {"mean": 45.0, "std": 15.0, "low": 5.0, "high": 98.0},
    "memory": {"mean": 52.0, "std": 12.0, "low": 20.0, "high": 95.0},
    "latency_ms": {"mean": 18.0, "std": 12.0, "low": 2.0, "high": 500.0},
    "packet_loss": {"mean": 0.002, "std": 0.008, "low": 0.0, "high": 0.4},
    "throughput_mbps": {"mean": 450.0, "std": 280.0, "low": 0.0, "high": 1200.0},
    "prb_utilization": {"mean": 0.42, "std": 0.18, "low": 0.05, "high": 0.98},
}

DIURNAL = {
    0: 0.30,
    3: 0.15,
    6: 0.50,
    9: 0.95,
    12: 0.80,
    15: 0.85,
    18: 1.00,
    21: 0.70,
}

NODE_TYPES = ["gNB", "UPF", "Router", "Service", "AMF", "SMF"]


def clamp(value: float, metric: str) -> float:
    profile = BASE_PROFILE[metric]
    return max(profile["low"], min(profile["high"], value))


def diurnal_multiplier(ts: datetime) -> float:
    hour = ts.hour + ts.minute / 60
    points = sorted(DIURNAL.items())
    for idx, (left_hour, left_value) in enumerate(points):
        right_hour, right_value = points[(idx + 1) % len(points)]
        adjusted_right = right_hour if right_hour > left_hour else right_hour + 24
        adjusted_hour = hour if hour >= left_hour else hour + 24
        if left_hour <= adjusted_hour <= adjusted_right:
            ratio = (adjusted_hour - left_hour) / max(adjusted_right - left_hour, 1e-6)
            return left_value + (right_value - left_value) * ratio
    return 0.5


def node_blueprints(node_count: int, slices: list[str]) -> list[dict[str, str]]:
    nodes: list[dict[str, str]] = []
    for idx in range(max(1, node_count)):
        slice_id = slices[idx % len(slices)]
        node_type = NODE_TYPES[idx % len(NODE_TYPES)]
        node_id = f"{node_type.lower()}_{idx + 1}"
        if node_type == "gNB":
            node_id = f"gnb_{idx + 1}"
        nodes.append({"slice_id": slice_id, "node_id": node_id, "node_type": node_type})
    return nodes


def correlated_metrics(rng: random.Random, ts: datetime, node: dict[str, str], stress: float = 0.0) -> dict[str, float]:
    profile = SLICE_PROFILES.get(node["slice_id"], SLICE_PROFILES["slice_1"])
    load = diurnal_multiplier(ts)
    demand = rng.gauss(load, 0.08)
    cpu = BASE_PROFILE["cpu"]["mean"] + 25 * (demand - 0.5) + rng.gauss(0, 7) + stress * 18
    memory = BASE_PROFILE["memory"]["mean"] + 0.42 * (cpu - 45) + rng.gauss(0, 6) + stress * 10
    prb = BASE_PROFILE["prb_utilization"]["mean"] * profile["prb_scale"] + 0.42 * demand + rng.gauss(0, 0.05) + stress * 0.22
    throughput = BASE_PROFILE["throughput_mbps"]["mean"] * profile["throughput_scale"] * max(demand, 0.1) + rng.gauss(0, 70)
    latency = BASE_PROFILE["latency_ms"]["mean"] * profile["latency_scale"] + max(0, cpu - 65) * 1.4 + max(0, prb - 0.75) * 90 + rng.lognormvariate(1.2, 0.35)
    packet_loss = BASE_PROFILE["packet_loss"]["mean"] + max(0, prb - 0.82) * 0.12 + max(0, latency - 120) * 0.0009 + abs(rng.gauss(0, 0.002))
    return {
        "cpu": round(clamp(cpu, "cpu"), 3),
        "memory": round(clamp(memory, "memory"), 3),
        "latency_ms": round(clamp(latency, "latency_ms"), 3),
        "packet_loss": round(clamp(packet_loss, "packet_loss"), 6),
        "throughput_mbps": round(clamp(throughput, "throughput_mbps"), 3),
        "prb_utilization": round(clamp(prb, "prb_utilization"), 6),
    }


def apply_fault(metrics: dict[str, float], fault_type: str, severity: float, phase: int) -> dict[str, float]:
    out = dict(metrics)
    if fault_type == "cpu_overload":
        out["cpu"] = clamp(out["cpu"] + 38 * severity, "cpu")
        out["latency_ms"] = clamp(out["latency_ms"] + 70 * severity + phase * 8, "latency_ms")
    elif fault_type == "memory_leak":
        out["memory"] = clamp(out["memory"] + (22 + phase * 3) * severity, "memory")
        if phase >= 2:
            out["packet_loss"] = clamp(out["packet_loss"] + 0.035 * severity, "packet_loss")
    elif fault_type == "link_failure":
        out["throughput_mbps"] = clamp(out["throughput_mbps"] * (1 - 0.78 * severity), "throughput_mbps")
        out["packet_loss"] = clamp(out["packet_loss"] + 0.22 * severity, "packet_loss")
        out["latency_ms"] = clamp(out["latency_ms"] + 110 * severity, "latency_ms")
    elif fault_type == "congestion":
        out["prb_utilization"] = clamp(out["prb_utilization"] + 0.34 * severity, "prb_utilization")
        out["latency_ms"] = clamp(out["latency_ms"] + 85 * severity, "latency_ms")
        out["throughput_mbps"] = clamp(out["throughput_mbps"] * (1 - 0.28 * severity), "throughput_mbps")
    elif fault_type == "packet_loss":
        out["packet_loss"] = clamp(out["packet_loss"] + 0.15 * severity, "packet_loss")
        out["latency_ms"] = clamp(out["latency_ms"] + 45 * severity, "latency_ms")
    return {key: round(value, 6) for key, value in out.items()}


def schedule_faults(rng: random.Random, ticks: int, scenario: str, fault_rate: float) -> list[dict[str, Any]]:
    faults: list[dict[str, Any]] = []
    scenario = scenario.lower().replace(" ", "_")
    if scenario in {"normal", "healthy"}:
        return faults
    if scenario in {"cascade", "cascade_failure"}:
        faults.append({"start": max(2, ticks // 3), "duration": min(18, max(6, ticks // 5)), "type": "link_failure", "severity": 0.85})
    elif scenario in {"degradation", "gradual_degradation"}:
        faults.append({"start": max(2, ticks // 5), "duration": min(ticks // 2, 60), "type": "memory_leak", "severity": 0.75})
    elif scenario in {"flash_crowd", "flash"}:
        faults.append({"start": max(2, ticks // 2), "duration": min(24, max(8, ticks // 6)), "type": "congestion", "severity": 0.9})
    else:
        attempts = max(1, int(ticks * max(0.0, min(0.3, fault_rate)) / 8))
        for _ in range(attempts):
            faults.append({
                "start": rng.randint(1, max(2, ticks - 8)),
                "duration": rng.randint(3, 15),
                "type": rng.choice(["cpu_overload", "memory_leak", "link_failure", "congestion", "packet_loss"]),
                "severity": rng.uniform(0.55, 0.92),
            })
    return faults


def generate_realistic_rows(
    scenario: str = "mixed",
    duration_hours: float = 6,
    fault_rate: float = 0.08,
    slices: list[str] | None = None,
    node_count: int = 8,
    step_seconds: int = 60,
    seed: int = 20260510,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rng = random.Random(seed)
    slices = slices or ["slice_1", "slice_2", "slice_3"]
    ticks = max(1, int(duration_hours * 3600 / step_seconds))
    nodes = node_blueprints(node_count, slices)
    start = datetime.now(timezone.utc).replace(microsecond=0)
    fault_windows = schedule_faults(rng, ticks, scenario, fault_rate)
    rows: list[dict[str, Any]] = []
    fault_count = 0

    for tick in range(ticks):
        ts = start + timedelta(seconds=tick * step_seconds)
        active_faults = [fault for fault in fault_windows if fault["start"] <= tick < fault["start"] + fault["duration"]]
        for node_idx, node in enumerate(nodes):
            stress = 0.25 if active_faults and (node_idx % 3 == 0 or scenario in {"flash_crowd", "cascade_failure", "mixed"}) else 0.0
            metrics = correlated_metrics(rng, ts, node, stress=stress)
            fault_label = 0
            fault_type = ""
            for fault in active_faults:
                if node_idx % 3 == 0 or (fault["type"] in {"link_failure", "congestion"} and node["node_type"] in {"Router", "UPF", "gNB"}):
                    phase = tick - fault["start"]
                    metrics = apply_fault(metrics, fault["type"], fault["severity"], phase)
                    fault_label = 1
                    fault_type = fault["type"]
                    fault_count += 1
                    break
            rows.append({
                "timestamp": ts.isoformat(),
                "slice_id": node["slice_id"],
                "node_id": node["node_id"],
                "node_type": node["node_type"],
                **metrics,
                "fault_label": fault_label,
                "fault_type": fault_type,
                "source": f"realistic_{scenario}",
            })

    summary = summarize_rows(rows, scenario, fault_windows)
    return rows, summary


def summarize_rows(rows: list[dict[str, Any]], scenario: str, fault_windows: list[dict[str, Any]]) -> dict[str, Any]:
    stats = {}
    for metric in METRICS:
        values = [float(row[metric]) for row in rows]
        stats[metric] = {
            "mean": round(mean(values), 4) if values else 0.0,
            "min": round(min(values), 4) if values else 0.0,
            "max": round(max(values), 4) if values else 0.0,
        }
    faults = sum(int(row["fault_label"]) for row in rows)
    return {
        "scenario": scenario,
        "rows": len(rows),
        "fault_rows": faults,
        "fault_ratio": round(faults / max(len(rows), 1), 4),
        "fault_windows": fault_windows,
        "statistics": stats,
        "validation": {
            "profile": "5G-NIDD/TeleLogs-inspired statistical ranges with Telecom Italia diurnal curve",
            "kl_divergence_proxy": round(abs((faults / max(len(rows), 1)) - 0.07), 4),
        },
    }


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=[
            "timestamp", "slice_id", "node_id", "node_type",
            *METRICS, "fault_label", "fault_type", "source",
        ])
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate realistic NetOracle telemetry scenarios.")
    parser.add_argument("--scenario", default="mixed", choices=["normal", "cascade_failure", "gradual_degradation", "flash_crowd", "mixed"])
    parser.add_argument("--duration-hours", type=float, default=6)
    parser.add_argument("--fault-rate", type=float, default=0.08)
    parser.add_argument("--nodes", type=int, default=8)
    parser.add_argument("--output", default="")
    args = parser.parse_args()

    rows, summary = generate_realistic_rows(
        scenario=args.scenario,
        duration_hours=args.duration_hours,
        fault_rate=args.fault_rate,
        node_count=args.nodes,
    )
    output = Path(args.output) if args.output else Path("data/scenarios") / f"{args.scenario}.csv"
    write_csv(output, rows)
    print(json.dumps({**summary, "output": str(output)}, indent=2))


if __name__ == "__main__":
    main()
