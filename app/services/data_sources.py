"""
data_sources.py
───────────────
Multi-source telemetry adapter for NetOracle.
Controlled by DATA_SOURCE_MODE environment variable:
 
  simulation  — Diurnal synthetic 5G simulation (default, always works)
  csv_stream  — Stream rows from data/*.csv, loop at EOF
  prometheus  — Scrape a generic Prometheus endpoint
  upload      — Use only user-uploaded rows from SQLite
  open5gs     — Live metrics from Open5GS 5G Core via Prometheus + MongoDB ← NEW
 
Usage:
    from app.services.data_sources import get_adapter
    adapter = get_adapter()
    frames = adapter.get_tick()   # returns list[dict] per tick
"""
 
from __future__ import annotations
 
import csv
import logging
import math
import random
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
 
import requests
 
from app.settings import get_settings
 
logger = logging.getLogger(__name__)
 
 
# ══════════════════════════════════════════════════════════════════════════
# Base adapter interface
# ══════════════════════════════════════════════════════════════════════════
 
class BaseAdapter:
    """All adapters implement get_tick() → list[dict]."""
 
    def get_tick(self) -> list[dict]:
        raise NotImplementedError
 
    def get_source_info(self) -> dict:
        return {"mode": "unknown"}
 
 
# ══════════════════════════════════════════════════════════════════════════
# Simulation Adapter (improved — diurnal + correlated faults)
# ══════════════════════════════════════════════════════════════════════════
 
SLICE_PROFILES = {
    "slice_1": {"name": "eMBB",  "throughput_scale": 3.0,  "latency_base": 15,  "prb_scale": 0.8},
    "slice_2": {"name": "mMTC",  "throughput_scale": 0.5,  "latency_base": 40,  "prb_scale": 0.9},
    "slice_3": {"name": "URLLC", "throughput_scale": 1.5,  "latency_base": 5,   "prb_scale": 0.6},
}
 
NODE_TEMPLATES = [
    {"node_id": "upf_1",    "node_type": "UPF",    "slice_id": "slice_1"},
    {"node_id": "upf_2",    "node_type": "UPF",    "slice_id": "slice_2"},
    {"node_id": "gnb_1",    "node_type": "gNB",    "slice_id": "slice_1"},
    {"node_id": "gnb_2",    "node_type": "gNB",    "slice_id": "slice_3"},
    {"node_id": "router_1", "node_type": "Router", "slice_id": "slice_1"},
    {"node_id": "amf_1",    "node_type": "AMF",    "slice_id": "slice_1"},
    {"node_id": "smf_1",    "node_type": "SMF",    "slice_id": "slice_1"},
    {"node_id": "pcf_1",    "node_type": "PCF",    "slice_id": "slice_2"},
]
 
 
class SimulationAdapter(BaseAdapter):
    """
    Realistic synthetic 5G simulation:
    - Diurnal traffic (peaks 09:00 + 18:00 UTC)
    - Slice-specific profiles
    - Correlated fault cascades
    - Auto fault injection every 200 ticks
    - 7 fault types including link_failure and memory_leak
    """
 
    FAULT_TYPES = [
        "congestion", "cpu_overload", "packet_loss",
        "vnf_degradation", "latency_spike", "link_failure", "memory_leak",
    ]
 
    def __init__(self):
        self._tick = 0
        self._active_faults: dict[str, dict] = {}   # node_id → fault state
        self._memory_leak_progress: dict[str, float] = {}
 
    def _diurnal_factor(self) -> float:
        """Returns 0.4 (off-peak) to 1.0 (peak) based on UTC hour."""
        hour = datetime.now(timezone.utc).hour
        # Two peaks: 9am and 6pm
        morning = math.sin(math.pi * max(0, hour - 6) / 6) ** 2
        evening = math.sin(math.pi * max(0, hour - 15) / 6) ** 2
        return 0.4 + 0.6 * max(morning, evening)
 
    def _maybe_auto_inject(self):
        """Auto-inject random fault every 200 ticks."""
        if self._tick > 0 and self._tick % 200 == 0:
            target = random.choice(NODE_TEMPLATES)
            fault  = random.choice(self.FAULT_TYPES)
            self._active_faults[target["node_id"]] = {
                "fault_type": fault,
                "severity": random.uniform(0.5, 0.9),
                "ttl": random.randint(10, 30),
            }
            logger.info(f"[Sim] Auto-injected {fault} on {target['node_id']}")
 
    def _cascade_faults(self, frames: list[dict]) -> list[dict]:
        """
        Apply correlated fault cascades:
        - UPF fault → router latency +30%, packet_loss +2%
        - gNB fault → all same-slice nodes get PRB spike
        """
        upf_faulted  = any(f["node_type"] == "UPF"  and f["fault_label"] for f in frames)
        gnb_faulted_slices = {
            f["slice_id"] for f in frames
            if f["node_type"] == "gNB" and f["fault_label"]
        }
 
        for frame in frames:
            if upf_faulted and frame["node_type"] == "Router":
                frame["latency_ms"] = round(frame["latency_ms"] * 1.30, 2)
                frame["packet_loss"] = round(min(1.0, frame["packet_loss"] + 0.02), 6)
 
            if frame["slice_id"] in gnb_faulted_slices and frame["node_type"] != "gNB":
                frame["prb_utilization"] = round(min(1.0, frame["prb_utilization"] * 1.20), 4)
 
        return frames
 
    def get_tick(self, fault_override: Optional[dict] = None) -> list[dict]:
        self._tick += 1
        self._maybe_auto_inject()
 
        diurnal = self._diurnal_factor()
        ts = datetime.now(timezone.utc).isoformat()
        frames = []
 
        # Decay active faults TTL
        to_clear = []
        for nid, fs in self._active_faults.items():
            fs["ttl"] -= 1
            if fs["ttl"] <= 0:
                to_clear.append(nid)
        for nid in to_clear:
            del self._active_faults[nid]
 
        # Apply fault override (from API)
        if fault_override:
            self._active_faults[fault_override["node_id"]] = {
                "fault_type": fault_override.get("fault_type", "congestion"),
                "severity":   fault_override.get("severity", 0.7),
                "ttl":        15,
            }
 
        for tmpl in NODE_TEMPLATES:
            profile = SLICE_PROFILES[tmpl["slice_id"]]
            active_fault = self._active_faults.get(tmpl["node_id"])
 
            base_cpu = 20 + 50 * diurnal + random.uniform(-5, 5)
            base_lat = profile["latency_base"] * (1 + 0.3 * diurnal) + random.uniform(-2, 5)
            base_pkt = random.uniform(0, 0.005)
            base_thr = profile["throughput_scale"] * 100 * diurnal + random.uniform(-10, 10)
            base_prb = profile["prb_scale"] * diurnal + random.uniform(-0.05, 0.05)
 
            fault_label = 0
            fault_type  = ""
 
            if active_fault:
                sev = active_fault["severity"]
                ft  = active_fault["fault_type"]
                fault_label = 1
                fault_type  = ft
 
                if ft == "congestion":
                    base_cpu = min(98, base_cpu + sev * 40)
                    base_thr = max(0, base_thr * (1 - sev * 0.6))
                elif ft == "cpu_overload":
                    base_cpu = min(99, base_cpu + sev * 50)
                    base_lat = base_lat * (1 + sev * 0.5)
                elif ft == "packet_loss":
                    base_pkt = min(0.4, base_pkt + sev * 0.3)
                elif ft == "vnf_degradation":
                    base_cpu = min(95, base_cpu + sev * 30)
                    base_thr = max(0, base_thr * (1 - sev * 0.4))
                elif ft == "latency_spike":
                    base_lat = base_lat * (1 + sev * 3)
                elif ft == "link_failure":
                    base_thr = 0.0
                    base_pkt = 0.4
                elif ft == "memory_leak":
                    leak = self._memory_leak_progress.get(tmpl["node_id"], 0)
                    leak = min(95, leak + 2.0)  # grows 2% per tick
                    self._memory_leak_progress[tmpl["node_id"]] = leak
                    base_cpu = min(99, base_cpu + leak * 0.5)
            else:
                self._memory_leak_progress.pop(tmpl["node_id"], None)
 
            frame = {
                "timestamp":       ts,
                "slice_id":        tmpl["slice_id"],
                "node_id":         tmpl["node_id"],
                "node_type":       tmpl["node_type"],
                "cpu":             round(min(100, max(0, base_cpu)), 2),
                "memory":          round(random.uniform(30, 70) + (30 if active_fault else 0), 2),
                "latency_ms":      round(max(1, base_lat), 2),
                "packet_loss":     round(min(1.0, max(0, base_pkt)), 6),
                "throughput_mbps": round(max(0, base_thr), 2),
                "prb_utilization": round(min(1.0, max(0, base_prb)), 4),
                "fault_label":     fault_label,
                "fault_type":      fault_type,
                "source":          "simulation",
            }
            frames.append(frame)
 
        return self._cascade_faults(frames)
 
    def get_source_info(self) -> dict:
        return {
            "mode": "simulation",
            "tick": self._tick,
            "active_faults": len(self._active_faults),
            "recommendation": "Running in simulation mode. Upload a CSV or configure Open5GS for real data.",
        }
 
 
# ══════════════════════════════════════════════════════════════════════════
# CSV Stream Adapter
# ══════════════════════════════════════════════════════════════════════════
 
REQUIRED_COLUMNS = {
    "timestamp", "slice_id", "node_id", "node_type",
    "cpu", "memory", "latency_ms", "packet_loss",
    "throughput_mbps", "prb_utilization", "fault_label", "fault_type",
}
 
 
class CSVStreamAdapter(BaseAdapter):
    def __init__(self):
        self._rows: list[dict] = []
        self._index = 0
        self._sim = SimulationAdapter()
        self._load_csv()
 
    def _load_csv(self):
        data_dir = Path("data")
        csvs = list(data_dir.glob("*.csv")) if data_dir.exists() else []
        if not csvs:
            logger.warning("[CSV] No CSV found in data/. Falling back to simulation.")
            return
 
        for csv_path in csvs:
            try:
                with open(csv_path, newline="", encoding="utf-8") as f:
                    reader = csv.DictReader(f)
                    cols = {c.strip().lower() for c in (reader.fieldnames or [])}
                    if not REQUIRED_COLUMNS.issubset(cols):
                        missing = REQUIRED_COLUMNS - cols
                        logger.warning(f"[CSV] {csv_path.name} missing columns: {missing}")
                        continue
                    self._rows.extend([
                        {k.strip().lower(): v for k, v in row.items()}
                        for row in reader
                    ])
            except Exception as e:
                logger.error(f"[CSV] Failed reading {csv_path}: {e}")
 
        logger.info(f"[CSV] Loaded {len(self._rows)} rows from {len(csvs)} file(s).")
 
    def get_tick(self) -> list[dict]:
        if not self._rows:
            return self._sim.get_tick()
 
        row = self._rows[self._index % len(self._rows)]
        self._index += 1
 
        return [{
            "timestamp":       datetime.now(timezone.utc).isoformat(),
            "slice_id":        row.get("slice_id", "slice_1"),
            "node_id":         row.get("node_id", "upf_1"),
            "node_type":       row.get("node_type", "UPF"),
            "cpu":             float(row.get("cpu", 50)),
            "memory":          float(row.get("memory", 50)),
            "latency_ms":      float(row.get("latency_ms", 20)),
            "packet_loss":     float(row.get("packet_loss", 0)),
            "throughput_mbps": float(row.get("throughput_mbps", 100)),
            "prb_utilization": float(row.get("prb_utilization", 0.5)),
            "fault_label":     int(row.get("fault_label", 0)),
            "fault_type":      row.get("fault_type", ""),
            "source":          "csv_stream",
        }]
 
    def get_source_info(self) -> dict:
        return {
            "mode": "csv_stream",
            "total_rows": len(self._rows),
            "current_index": self._index,
            "available_csv_files": [f.name for f in Path("data").glob("*.csv")] if Path("data").exists() else [],
        }
 
 
# ══════════════════════════════════════════════════════════════════════════
# Prometheus Generic Adapter
# ══════════════════════════════════════════════════════════════════════════
 
class PrometheusAdapter(BaseAdapter):
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self._sim = SimulationAdapter()
 
    def _query(self, metric: str) -> Optional[float]:
        try:
            r = requests.get(
                f"{self.base_url}/api/v1/query",
                params={"query": metric},
                timeout=5,
            )
            results = r.json().get("data", {}).get("result", [])
            if results:
                return float(results[0]["value"][1])
        except Exception:
            pass
        return None
 
    def get_tick(self) -> list[dict]:
        cpu_idle = self._query('avg(rate(node_cpu_seconds_total{mode="idle"}[30s]))')
        mem_avail = self._query("node_memory_MemAvailable_bytes")
        mem_total = self._query("node_memory_MemTotal_bytes")
        net_rx    = self._query("rate(node_network_receive_bytes_total[30s])")
 
        if cpu_idle is None:
            logger.warning("[Prometheus] Unreachable, falling back to simulation.")
            return self._sim.get_tick()
 
        cpu    = round((1 - cpu_idle) * 100, 2)
        memory = round((1 - mem_avail / mem_total) * 100, 2) if mem_avail and mem_total else 50.0
        thr    = round((net_rx or 0) * 8 / 1e6, 3)
 
        return [{
            "timestamp":       datetime.now(timezone.utc).isoformat(),
            "slice_id":        "slice_1",
            "node_id":         "host_node",
            "node_type":       "Host",
            "cpu":             cpu,
            "memory":          memory,
            "latency_ms":      random.uniform(10, 30),
            "packet_loss":     0.0,
            "throughput_mbps": thr,
            "prb_utilization": min(1.0, thr / 1000),
            "fault_label":     1 if cpu > 85 else 0,
            "fault_type":      "cpu_overload" if cpu > 85 else "",
            "source":          "prometheus",
        }]
 
    def get_source_info(self) -> dict:
        reachable = self._query("up") is not None
        return {"mode": "prometheus", "prometheus_reachable": reachable, "url": self.base_url}
 
 
# ══════════════════════════════════════════════════════════════════════════
# Upload Adapter
# ══════════════════════════════════════════════════════════════════════════
 
class UploadAdapter(BaseAdapter):
    def __init__(self):
        from app.database import db
        self._db = db
        self._sim = SimulationAdapter()
        self._index = 0
 
    def get_tick(self) -> list[dict]:
        try:
            rows = self._db.latest_telemetry(8)
            if not rows:
                return self._sim.get_tick()
            row = rows[self._index % len(rows)]
            self._index += 1
            return [{**row, "source": "upload"}]
        except Exception:
            return self._sim.get_tick()
 
    def get_source_info(self) -> dict:
        return {"mode": "upload"}
 
 
# ══════════════════════════════════════════════════════════════════════════
# Open5GS Adapter (imported from open5gs_adapter.py)
# ══════════════════════════════════════════════════════════════════════════
 
class Open5GSAdapterWrapper(BaseAdapter):
    """
    Wraps Open5GSAdapter and exposes the standard BaseAdapter interface.
    Falls back to SimulationAdapter if Open5GS is unavailable.
    """
 
    def __init__(self, prometheus_url: str, mongo_uri: str):
        from app.services.open5gs_adapter import Open5GSAdapter
        self._adapter = Open5GSAdapter(
            prometheus_url=prometheus_url,
            mongo_uri=mongo_uri,
        )
 
    def get_tick(self) -> list[dict]:
        return self._adapter.get_tick()
 
    def get_nf_health(self) -> dict:
        return self._adapter.get_nf_health()
 
    def get_source_info(self) -> dict:
        health = self._adapter.get_nf_health()
        return {
            "mode": "open5gs",
            "prometheus_reachable": health.get("prometheus_reachable"),
            "mongodb_reachable":    health.get("mongodb_reachable"),
            "nf_status":            health.get("nfs", {}),
            "subscriber_count":     health.get("subscriber_count", 0),
            "active_sessions":      health.get("active_sessions", 0),
            "tick_count":           health.get("tick_count", 0),
            "recommendation": (
                "Live Open5GS data streaming."
                if health.get("prometheus_reachable")
                else "Open5GS not reachable — streaming simulated data. Start Open5GS in WSL2."
            ),
        }
 
 
# ══════════════════════════════════════════════════════════════════════════
# Factory
# ══════════════════════════════════════════════════════════════════════════
 
_adapter_instance: Optional[BaseAdapter] = None
 
 
def get_adapter() -> BaseAdapter:
    """
    Returns the singleton adapter based on DATA_SOURCE_MODE.
    Lazily initialised on first call.
    """
    global _adapter_instance
    if _adapter_instance is not None:
        return _adapter_instance
 
    settings = get_settings()
    mode = settings.data_source_mode.lower()
 
    logger.info(f"[DataSources] Initialising adapter: mode={mode}")
 
    if mode == "open5gs":
        prometheus_url = settings.open5gs_prometheus_url
        mongo_uri      = settings.open5gs_mongo_uri
        _adapter_instance = Open5GSAdapterWrapper(prometheus_url, mongo_uri)
 
    elif mode == "csv_stream":
        _adapter_instance = CSVStreamAdapter()
 
    elif mode == "prometheus":
        prom_url = settings.prometheus_url
        _adapter_instance = PrometheusAdapter(prom_url)
 
    elif mode == "upload":
        _adapter_instance = UploadAdapter()
 
    else:
        if mode != "simulation":
            logger.warning(f"[DataSources] Unknown mode '{mode}', defaulting to simulation.")
        _adapter_instance = SimulationAdapter()
 
    return _adapter_instance
 
 
def reset_adapter():
    """Force re-initialisation (useful for mode switching at runtime)."""
    global _adapter_instance
    _adapter_instance = None
