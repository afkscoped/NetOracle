import math
import random
from datetime import datetime, timezone
from typing import Any

from app.database import db
from app.services.data_sources import METRIC_KEYS, get_adapter


NODE_BLUEPRINTS = [
    ("slice_1", "gnb_1", "gNB"), ("slice_1", "upf_1", "UPF"), ("slice_1", "router_1", "Router"), ("slice_1", "app_1", "Service"),
    ("slice_2", "gnb_2", "gNB"), ("slice_2", "upf_2", "UPF"), ("slice_2", "router_2", "Router"), ("slice_2", "app_2", "Service"),
    ("slice_3", "gnb_3", "gNB"), ("slice_3", "upf_3", "UPF"), ("slice_3", "router_3", "Router"), ("slice_3", "app_3", "Service"),
]


class TelemetryService:
    def __init__(self) -> None:
        self.tick = 0
        self.rng = random.Random(2704)

    def _base_metrics(self, node_type: str) -> dict[str, float]:
        profile = {
            "gNB": (48, 45, 18, 0.004, 920, 0.48),
            "UPF": (52, 58, 24, 0.006, 860, 0.55),
            "Router": (38, 41, 12, 0.003, 980, 0.34),
            "Service": (42, 50, 28, 0.005, 740, 0.28),
        }[node_type]
        wave = math.sin(self.tick / 7.0) * 4
        return {
            "cpu": profile[0] + wave + self.rng.uniform(-5, 5),
            "memory": profile[1] + self.rng.uniform(-4, 4),
            "latency_ms": profile[2] + abs(wave) + self.rng.uniform(-3, 3),
            "packet_loss": max(0.0, profile[3] + self.rng.uniform(-0.002, 0.004)),
            "throughput_mbps": profile[4] + self.rng.uniform(-80, 80),
            "prb_utilization": max(0.05, min(0.95, profile[5] + wave / 100 + self.rng.uniform(-0.05, 0.05))),
        }

    def _apply_fault(self, metrics: dict[str, float], fault_type: str, severity: float) -> None:
        if fault_type == "congestion":
            metrics["latency_ms"] += 65 * severity
            metrics["packet_loss"] += 0.09 * severity
            metrics["prb_utilization"] = min(0.99, metrics["prb_utilization"] + 0.38 * severity)
            metrics["throughput_mbps"] *= 1 - 0.32 * severity
        elif fault_type == "cpu_overload":
            metrics["cpu"] = min(99, metrics["cpu"] + 47 * severity)
            metrics["latency_ms"] += 30 * severity
            metrics["throughput_mbps"] *= 1 - 0.18 * severity
        elif fault_type == "packet_loss":
            metrics["packet_loss"] += 0.16 * severity
            metrics["latency_ms"] += 26 * severity
            metrics["throughput_mbps"] *= 1 - 0.28 * severity
        elif fault_type == "vnf_degradation":
            metrics["memory"] = min(99, metrics["memory"] + 34 * severity)
            metrics["cpu"] = min(99, metrics["cpu"] + 23 * severity)
            metrics["latency_ms"] += 42 * severity
        elif fault_type == "latency_spike":
            metrics["latency_ms"] += 90 * severity
            metrics["packet_loss"] += 0.035 * severity

    def _normalise_frame(self, frame: dict[str, Any]) -> dict[str, Any]:
        metrics = dict(frame.get("metrics") or {})
        for key in METRIC_KEYS:
            if key in frame and key not in metrics:
                metrics[key] = frame[key]
        clean_metrics = {}
        for key, value in metrics.items():
            try:
                clean_metrics[key] = round(float(value), 6)
            except (TypeError, ValueError):
                continue
        return {
            "timestamp": str(frame.get("timestamp") or datetime.now(timezone.utc).isoformat()),
            "slice_id": str(frame.get("slice_id") or "slice_1"),
            "node_id": str(frame.get("node_id") or "unknown_node"),
            "node_type": str(frame.get("node_type") or "Unknown"),
            "metrics": clean_metrics,
            "fault_label": int(float(frame.get("fault_label") or 0)),
            "fault_type": frame.get("fault_type") or None,
            "source": frame.get("source", "unknown"),
        }

    def generate_tick(self, fault: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        self.tick += 1
        adapter = get_adapter()
        try:
            raw_frames = adapter.get_tick(fault)  # type: ignore[arg-type]
        except TypeError:
            raw_frames = adapter.get_tick()
        frames = [self._normalise_frame(frame) for frame in raw_frames]
        for frame in frames:
            db.insert_telemetry(frame)
        source = frames[0].get("source", "unknown") if frames else "unknown"
        db.audit("telemetry_tick", {"frames": len(frames), "fault": fault, "source": source})
        return frames

    def warm_start(self, ticks: int = 20) -> None:
        if db.fetch_one("SELECT id FROM telemetry LIMIT 1"):
            return
        for _ in range(ticks):
            self.generate_tick()

    def recent(self, limit: int = 180) -> list[dict[str, Any]]:
        return db.latest_telemetry(limit)


telemetry_service = TelemetryService()
