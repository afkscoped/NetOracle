import argparse
import csv
import json
import math
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

NUMERIC_COLUMNS = ["cpu", "memory", "latency_ms", "packet_loss", "throughput_mbps", "prb_utilization", "jitter_ms", "sessions_active", "handover_failures", "retransmission_rate"]
CATEGORICAL_COLUMNS = ["slice_id", "node_id", "node_type", "fault_type", "source"]


def read_csv(path: Path) -> list[dict[str, Any]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0].keys())
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def coerce_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def fit_stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    stats: dict[str, Any] = {"numeric": {}, "categorical": {}, "rows": len(rows)}
    for col in NUMERIC_COLUMNS:
        values = [coerce_float(row.get(col)) for row in rows if row.get(col) not in {None, ""}]
        if values:
            mean = sum(values) / len(values)
            var = sum((v - mean) ** 2 for v in values) / max(1, len(values) - 1)
            stats["numeric"][col] = {"mean": mean, "std": math.sqrt(var), "min": min(values), "max": max(values)}
    for col in CATEGORICAL_COLUMNS:
        counts: dict[str, int] = {}
        for row in rows:
            value = str(row.get(col) or "")
            counts[value] = counts.get(value, 0) + 1
        stats["categorical"][col] = counts
    return stats


def sample_categorical(counts: dict[str, int]) -> str:
    values = list(counts.keys()) or [""]
    weights = list(counts.values()) or [1]
    return random.choices(values, weights=weights, k=1)[0]


def gaussian_fallback(stats: dict[str, Any], count: int, stress: bool = False) -> list[dict[str, Any]]:
    start = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    rows = []
    for idx in range(count):
        row: dict[str, Any] = {"timestamp": (start + timedelta(minutes=idx)).isoformat()}
        for col, counts in stats.get("categorical", {}).items():
            row[col] = sample_categorical(counts)
        if not row.get("slice_id"):
            row["slice_id"] = random.choice(["slice_1", "slice_2", "slice_3"])
        if not row.get("node_id"):
            row["node_id"] = random.choice(["gnb_1", "upf_1", "router_1", "app_1"])
        if not row.get("node_type"):
            row["node_type"] = "UPF" if "upf" in row["node_id"] else "Router"
        fault = stress and random.random() < 0.22
        for col, col_stats in stats.get("numeric", {}).items():
            value = random.gauss(col_stats["mean"], max(col_stats["std"], 1e-6))
            value = max(col_stats["min"], min(col_stats["max"], value))
            if fault:
                if col in {"cpu", "memory", "latency_ms"}:
                    value *= random.uniform(1.25, 1.9)
                elif col in {"packet_loss", "prb_utilization", "jitter_ms", "retransmission_rate"}:
                    value *= random.uniform(2.0, 5.0)
                elif col == "throughput_mbps":
                    value *= random.uniform(0.25, 0.65)
            if col in {"cpu", "memory"}:
                value = max(0, min(99, value))
            if col in {"packet_loss", "prb_utilization", "retransmission_rate"}:
                value = max(0, min(1, value))
            row[col] = round(value, 5)
        row["fault_label"] = 1 if fault else int(coerce_float(row.get("fault_label", 0)))
        row["fault_type"] = random.choice(["congestion", "packet_loss", "latency_spike", "vnf_degradation"]) if fault else row.get("fault_type", "")
        row["source"] = "copulagan_fallback_stress" if stress else "copulagan_fallback"
        rows.append(row)
    return rows


def sdv_generate(input_path: Path, count: int) -> list[dict[str, Any]] | None:
    try:
        import pandas as pd
        from sdv.metadata import SingleTableMetadata
        try:
            from sdv.single_table import CTGANSynthesizer
        except Exception:
            from sdv.tabular import CTGAN as CTGANSynthesizer
        df = pd.read_csv(input_path)
        metadata = SingleTableMetadata()
        metadata.detect_from_dataframe(df)
        synth = CTGANSynthesizer(metadata, epochs=80)
        synth.fit(df)
        return synth.sample(num_rows=count).to_dict(orient="records")
    except Exception:
        return None


def validate(real_rows: list[dict[str, Any]], synthetic_rows: list[dict[str, Any]]) -> dict[str, Any]:
    real_stats = fit_stats(real_rows)
    syn_stats = fit_stats(synthetic_rows)
    drift = {}
    for col, real_col in real_stats.get("numeric", {}).items():
        syn_col = syn_stats.get("numeric", {}).get(col)
        if not syn_col:
            continue
        denom = abs(real_col["mean"]) + 1e-6
        drift[col] = round(abs(real_col["mean"] - syn_col["mean"]) / denom, 4)
    return {
        "real_rows": len(real_rows),
        "synthetic_rows": len(synthetic_rows),
        "mean_relative_drift": drift,
        "quality_score": round(max(0.0, 1.0 - (sum(drift.values()) / max(1, len(drift)))), 3),
        "method": "SDV CTGAN if installed, otherwise Gaussian copula-style fallback with stress injection",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="data/sample_telemetry.csv")
    parser.add_argument("--output", default="data/synthetic/netoracle_copulagan_100k.csv")
    parser.add_argument("--rows", type=int, default=5000)
    parser.add_argument("--mode", choices=["fit", "generate", "stress", "validate"], default="stress")
    parser.add_argument("--seed", type=int, default=2704)
    args = parser.parse_args()
    random.seed(args.seed)
    input_path = Path(args.input)
    real_rows = read_csv(input_path)
    stats = fit_stats(real_rows)
    rows = None if args.mode == "stress" else sdv_generate(input_path, args.rows)
    if rows is None:
        rows = gaussian_fallback(stats, args.rows, stress=args.mode in {"stress", "generate"})
    output_path = Path(args.output)
    write_csv(output_path, rows)
    report = validate(real_rows, rows)
    report.update({"output": str(output_path), "mode": args.mode})
    report_path = Path("reports/data_quality_report.json")
    report_path.parent.mkdir(exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
