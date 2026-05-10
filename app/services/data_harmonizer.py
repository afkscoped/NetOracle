import csv
import json
from pathlib import Path
from typing import Any

CANONICAL_COLUMNS = [
    "timestamp", "slice_id", "node_id", "node_type", "cpu", "memory", "latency_ms", "packet_loss",
    "throughput_mbps", "prb_utilization", "jitter_ms", "sessions_active", "handover_failures",
    "retransmission_rate", "fault_label", "fault_type", "source",
]

ALIASES = {
    "latency": "latency_ms",
    "delay": "latency_ms",
    "loss": "packet_loss",
    "throughput": "throughput_mbps",
    "prb": "prb_utilization",
    "label": "fault_label",
    "attack_cat": "fault_type",
    "class": "fault_label",
}

DATASET_REGISTRY = [
    {"name": "5G Traffic Datasets", "type": "traffic", "use": "Traffic-load priors and throughput distributions", "source": "Kaggle/IEEE DataPort"},
    {"name": "Wireless Network Slicing Dataset", "type": "slicing", "use": "Latency, packet-loss, SLA and slice class priors", "source": "Kaggle"},
    {"name": "DeepSlice / Secure5G", "type": "slicing-security", "use": "Slice classification and abnormal service classes", "source": "Kaggle"},
    {"name": "UNSW-NB15", "type": "network-flow", "use": "Abnormal traffic and attack-like anomaly priors", "source": "UNSW/UNB CIC"},
    {"name": "CIC-IDS2018 / CSE-CIC", "type": "network-flow", "use": "High-volume traffic anomalies and flow bursts", "source": "Canadian Institute for Cybersecurity"},
    {"name": "ToN-IoT / BoT-IoT", "type": "iot", "use": "IoT slice anomaly behavior", "source": "UNSW"},
]


class DataHarmonizer:
    def registry(self) -> dict[str, Any]:
        return {
            "canonical_schema": CANONICAL_COLUMNS,
            "datasets": DATASET_REGISTRY,
            "strategy": "Import real public datasets into canonical telemetry, then train CTGAN/GaussianCopula generators and inject causal cascade scenarios.",
            "optional_realtime": "Open5GS remains an optional source via DATA_SOURCE_MODE=open5gs after WSL/Prometheus/Mongo are configured.",
        }

    def templates(self) -> dict[str, Any]:
        return {
            "telemetry_csv_header": ",".join(CANONICAL_COLUMNS),
            "telemetry_example": {
                "timestamp": "2026-05-10T10:00:00Z",
                "slice_id": "slice_1",
                "node_id": "upf_1",
                "node_type": "UPF",
                "cpu": 52,
                "memory": 58,
                "latency_ms": 24,
                "packet_loss": 0.006,
                "throughput_mbps": 860,
                "prb_utilization": 0.55,
                "jitter_ms": 3,
                "sessions_active": 1200,
                "handover_failures": 0,
                "retransmission_rate": 0.01,
                "fault_label": 0,
                "fault_type": "",
                "source": "user_dataset",
            },
            "topology_example": {
                "nodes": [
                    {"node_id": "slice_1", "node_type": "Slice", "label": "eMBB Slice", "properties": {"sla_latency_ms": 45}},
                    {"node_id": "gnb_1", "node_type": "gNB", "label": "gNB-1", "properties": {"site": "cell-a"}},
                    {"node_id": "upf_1", "node_type": "UPF", "label": "UPF-1", "properties": {"region": "edge"}},
                    {"node_id": "pcf_1", "node_type": "PCF", "label": "PCF-1", "properties": {"policy": "gold"}},
                ],
                "edges": [
                    {"source_id": "slice_1", "target_id": "gnb_1", "relation": "USES_RAN", "properties": {}},
                    {"source_id": "gnb_1", "target_id": "upf_1", "relation": "FORWARDS_TO", "properties": {}},
                    {"source_id": "pcf_1", "target_id": "slice_1", "relation": "GOVERNS", "properties": {}},
                ],
            },
        }

    def quality_report(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        if not rows:
            return {
                "rows": 0,
                "schema_validity": 0.0,
                "completeness": 0.0,
                "fault_ratio": 0.0,
                "distribution_similarity": 0.0,
                "quality_score": 0.0,
                "warnings": ["No telemetry rows are available."],
            }
        warnings = []
        required = {"timestamp", "slice_id", "node_id", "node_type"}
        metric_cols = ["cpu", "memory", "latency_ms", "packet_loss", "throughput_mbps", "prb_utilization"]
        valid_required = sum(1 for row in rows if all(row.get(col) not in (None, "") for col in required)) / len(rows)
        present_values = 0
        total_values = len(rows) * len(metric_cols)
        for row in rows:
            metrics = row.get("metrics", row)
            for col in metric_cols:
                if metrics.get(col) not in (None, ""):
                    present_values += 1
        completeness = present_values / max(total_values, 1)
        faults = sum(1 for row in rows if int(row.get("fault_label") or 0) == 1)
        fault_ratio = faults / max(len(rows), 1)
        distribution_similarity = max(0.0, 1.0 - abs(fault_ratio - 0.07) * 3.0)
        if fault_ratio == 0:
            warnings.append("No labelled faults found; training can still run but RCA validation will be weak.")
        if valid_required < 1:
            warnings.append("Some rows are missing timestamp/slice/node identity fields.")
        if completeness < 0.85:
            warnings.append("Metric completeness is below 85%; fill missing canonical metrics before training.")
        score = round(valid_required * 0.35 + completeness * 0.35 + distribution_similarity * 0.30, 3)
        return {
            "rows": len(rows),
            "schema_validity": round(valid_required, 3),
            "completeness": round(completeness, 3),
            "fault_ratio": round(fault_ratio, 4),
            "distribution_similarity": round(distribution_similarity, 3),
            "quality_score": score,
            "warnings": warnings,
            "interpretation": "A score above 0.80 means the data is suitable for demo retraining; below 0.65 needs cleanup or more labelled faults.",
        }

    def harmonize_rows(self, rows: list[dict[str, Any]], source: str = "uploaded") -> list[dict[str, Any]]:
        output = []
        for idx, row in enumerate(rows):
            normalized = {ALIASES.get(str(k).strip().lower(), str(k).strip().lower()): v for k, v in row.items()}
            item = {column: normalized.get(column, "") for column in CANONICAL_COLUMNS}
            item["timestamp"] = item["timestamp"] or f"synthetic_index_{idx}"
            item["slice_id"] = item["slice_id"] or "slice_1"
            item["node_id"] = item["node_id"] or "upf_1"
            item["node_type"] = item["node_type"] or "UPF"
            item["source"] = item["source"] or source
            item["fault_label"] = int(float(item["fault_label"] or 0))
            item["fault_type"] = item["fault_type"] or ("unknown_fault" if item["fault_label"] else "")
            for col in CANONICAL_COLUMNS:
                if col not in {"timestamp", "slice_id", "node_id", "node_type", "fault_type", "source"}:
                    try:
                        item[col] = float(item[col] or 0)
                    except Exception:
                        item[col] = 0.0
            output.append(item)
        return output

    def harmonize_file(self, input_path: str, output_path: str | None = None, source: str = "public_dataset") -> dict[str, Any]:
        path = Path(input_path)
        if not path.exists():
            return {"ok": False, "error": f"File not found: {input_path}"}
        if path.suffix.lower() == ".json":
            raw = json.loads(path.read_text(encoding="utf-8"))
            rows = raw if isinstance(raw, list) else raw.get("rows", [])
        else:
            with path.open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
        harmonized = self.harmonize_rows(rows, source=source)
        out = Path(output_path) if output_path else Path("data/real") / f"{path.stem}_canonical.csv"
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=CANONICAL_COLUMNS)
            writer.writeheader()
            writer.writerows(harmonized)
        return {"ok": True, "rows": len(harmonized), "output": str(out), "schema": CANONICAL_COLUMNS}


harmonizer_service = DataHarmonizer()
