import csv
import math
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

OUTPUT = Path("data") / "sample_telemetry.csv"
NODES = [
    ("slice_1", "gnb_1", "gNB"),
    ("slice_1", "upf_1", "UPF"),
    ("slice_1", "router_1", "Router"),
    ("slice_1", "app_1", "Service"),
    ("slice_2", "gnb_2", "gNB"),
    ("slice_2", "upf_2", "UPF"),
    ("slice_3", "gnb_3", "gNB"),
    ("slice_3", "upf_3", "UPF"),
]
SLICE_PROFILES = {
    "slice_1": {"throughput": 900, "latency": 16, "prb": 0.55},
    "slice_2": {"throughput": 520, "latency": 35, "prb": 0.70},
    "slice_3": {"throughput": 700, "latency": 8, "prb": 0.45},
}
FAULT_TYPES = ["congestion", "cpu_overload", "packet_loss", "vnf_degradation", "latency_spike", "link_failure", "memory_leak"]


def diurnal(hour: float) -> float:
    morning = math.exp(-((hour - 9) ** 2) / 10)
    evening = math.exp(-((hour - 18) ** 2) / 12)
    trough = 0.25 * math.exp(-((hour - 3) ** 2) / 8)
    return max(0.25, min(1.0, 0.45 + 0.55 * max(morning, evening) - trough))


def row_for(ts: datetime, slice_id: str, node_id: str, node_type: str, fault: str | None) -> dict[str, object]:
    profile = SLICE_PROFILES[slice_id]
    load = diurnal(ts.hour + ts.minute / 60)
    cpu = 24 + 48 * load + random.uniform(-6, 6)
    memory = 35 + 28 * load + random.uniform(-5, 5)
    latency = profile["latency"] * (1 + 0.45 * load) + random.uniform(-2, 5)
    packet_loss = max(0, random.uniform(0, 0.006))
    throughput = profile["throughput"] * load + random.uniform(-45, 45)
    prb = profile["prb"] * load + random.uniform(-0.06, 0.06)
    fault_label = 1 if fault else 0
    if fault == "congestion":
        latency += 65
        packet_loss += 0.08
        throughput *= 0.55
        prb += 0.32
    elif fault == "cpu_overload":
        cpu += 38
        latency += 25
    elif fault == "packet_loss":
        packet_loss += 0.16
        throughput *= 0.62
    elif fault == "vnf_degradation":
        memory += 30
        cpu += 18
        latency += 35
    elif fault == "latency_spike":
        latency += 95
    elif fault == "link_failure":
        throughput = 0
        packet_loss = 0.4
    elif fault == "memory_leak":
        memory += random.uniform(20, 35)
        cpu += 12
    return {
        "timestamp": ts.isoformat(),
        "slice_id": slice_id,
        "node_id": node_id,
        "node_type": node_type,
        "cpu": round(min(99, max(1, cpu)), 2),
        "memory": round(min(99, max(1, memory)), 2),
        "latency_ms": round(max(1, latency), 2),
        "packet_loss": round(min(1.0, packet_loss), 6),
        "throughput_mbps": round(max(0, throughput), 2),
        "prb_utilization": round(min(0.99, max(0.03, prb)), 4),
        "fault_label": fault_label,
        "fault_type": fault or "",
    }


def main() -> None:
    random.seed(2704)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    start = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0) - timedelta(hours=24)
    rows = []
    for step in range(75):
        ts = start + timedelta(minutes=20 * step)
        cascade_slice = random.choice(["slice_1", "slice_2", "slice_3"]) if random.random() < 0.15 else None
        cascade_fault = random.choice(FAULT_TYPES) if cascade_slice else None
        for slice_id, node_id, node_type in NODES:
            fault = cascade_fault if slice_id == cascade_slice and random.random() < 0.55 else None
            rows.append(row_for(ts, slice_id, node_id, node_type, fault))
    with OUTPUT.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {len(rows)} rows to {OUTPUT}")


if __name__ == "__main__":
    main()
