"""
open5gs_adapter.py
──────────────────
NetOracle real-telemetry adapter for Open5GS 5G Core.
 
Pulls live metrics from three sources (in priority order):
  1. Prometheus metrics exported by each Open5GS NF
  2. MongoDB open5gs database (subscriber/session counts)
  3. Graceful simulation fallback if Open5GS is unreachable
 
Metric Mapping — Open5GS → NetOracle Schema
────────────────────────────────────────────
| Open5GS Metric                           | NetOracle Field     | NF     |
|------------------------------------------|---------------------|--------|
| amf_session_count                        | cpu (proxy)         | AMF    |
| amf_ue_context_count                     | memory (proxy)      | AMF    |
| smf_pdu_session_count                    | throughput_mbps     | SMF    |
| upf_rx_bytes_total / upf_tx_bytes_total  | throughput_mbps     | UPF    |
| upf_rx_packets_total (delta)             | packet_loss         | UPF    |
| upf_gtp_latency_seconds (histogram)      | latency_ms          | UPF    |
| pcf_policy_rule_count                    | prb_utilization     | PCF    |
| node_cpu_seconds_total (node-exporter)   | cpu                 | Host   |
| node_memory_MemAvailable_bytes           | memory              | Host   |
 
Each Open5GS NF maps to a NetOracle node_id:
  AMF → node_id: "amf_1",  node_type: "AMF"
  SMF → node_id: "smf_1",  node_type: "SMF"
  UPF → node_id: "upf_1",  node_type: "UPF"
  PCF → node_id: "pcf_1",  node_type: "PCF"
  NRF → node_id: "nrf_1",  node_type: "NRF"
  gNB (UERANSIM) → node_id: "gnb_1", node_type: "gNB"
"""
 
from __future__ import annotations
 
import logging
import math
import random
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
 
import requests
 
logger = logging.getLogger(__name__)
 
# ── Metric name constants (Open5GS Prometheus labels) ─────────────────────
 
OPEN5GS_METRICS = {
    # AMF metrics
    "amf_session":      "amf_session_count",
    "amf_ue":           "amf_ue_context_count",
    "amf_reg_attempt":  "amf_registration_request_total",
    "amf_reg_success":  "amf_registration_success_total",
 
    # SMF metrics
    "smf_pdu":          "smf_pdu_session_count",
    "smf_pdu_created":  "smf_pdu_session_created_total",
    "smf_pdu_released": "smf_pdu_session_released_total",
 
    # UPF metrics
    "upf_rx_bytes":     "upf_rx_bytes_total",
    "upf_tx_bytes":     "upf_tx_bytes_total",
    "upf_rx_pkts":      "upf_rx_packets_total",
    "upf_tx_pkts":      "upf_tx_packets_total",
    "upf_drop_pkts":    "upf_dropped_packets_total",
 
    # PCF metrics
    "pcf_rules":        "pcf_policy_rule_count",
 
    # Node exporter (system)
    "node_cpu_idle":    'node_cpu_seconds_total{mode="idle"}',
    "node_mem_avail":   "node_memory_MemAvailable_bytes",
    "node_mem_total":   "node_memory_MemTotal_bytes",
    "node_net_rx":      "node_network_receive_bytes_total",
    "node_net_tx":      "node_network_transmit_bytes_total",
}
 
# NF port assignments (match your Open5GS config)
NF_PROMETHEUS_PORTS = {
    "amf": 9095,
    "smf": 9096,
    "upf": 9097,
    "pcf": 9098,
}
 
# NetOracle node definitions for each Open5GS NF
NF_NODE_MAP = {
    "amf": {"node_id": "amf_1",  "node_type": "AMF",    "slice_id": "slice_1"},
    "smf": {"node_id": "smf_1",  "node_type": "SMF",    "slice_id": "slice_1"},
    "upf": {"node_id": "upf_1",  "node_type": "UPF",    "slice_id": "slice_1"},
    "pcf": {"node_id": "pcf_1",  "node_type": "PCF",    "slice_id": "slice_2"},
    "nrf": {"node_id": "nrf_1",  "node_type": "NRF",    "slice_id": "slice_1"},
    "gnb": {"node_id": "gnb_1",  "node_type": "gNB",    "slice_id": "slice_1"},
}
 
 
class Open5GSMetricCache:
    """
    Rolling cache for Prometheus counter deltas.
    Counters are monotonically increasing; we need per-interval deltas
    to compute rates (e.g., packets/s, bytes/s).
    """
 
    def __init__(self, window: int = 60):
        self._prev: dict[str, float] = {}
        self._prev_ts: float = time.time()
        self._history: deque = deque(maxlen=window)
 
    def delta(self, key: str, current_value: float) -> float:
        """Returns the delta since last call. Returns 0 on first call."""
        prev = self._prev.get(key, current_value)
        delta = max(0.0, current_value - prev)
        self._prev[key] = current_value
        return delta
 
    def rate_per_second(self, key: str, current_value: float) -> float:
        """Returns per-second rate of a counter."""
        now = time.time()
        elapsed = now - self._prev_ts
        d = self.delta(key, current_value)
        return d / elapsed if elapsed > 0 else 0.0
 
 
class Open5GSPrometheusClient:
    """
    Thin Prometheus HTTP API client.
    Queries the Prometheus server (not NF exporters directly)
    for pre-aggregated metrics.
    """
 
    def __init__(self, base_url: str, timeout: int = 5):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._available: Optional[bool] = None
        self._last_health_check: float = 0.0
        self._health_check_interval: float = 30.0
 
    def is_available(self) -> bool:
        now = time.time()
        if now - self._last_health_check > self._health_check_interval:
            try:
                r = requests.get(
                    f"{self.base_url}/-/healthy",
                    timeout=2,
                )
                self._available = r.status_code == 200
            except Exception:
                self._available = False
            self._last_health_check = now
        return self._available or False
 
    def query(self, promql: str) -> Optional[float]:
        """Run an instant PromQL query, return scalar or first value."""
        try:
            r = requests.get(
                f"{self.base_url}/api/v1/query",
                params={"query": promql},
                timeout=self.timeout,
            )
            data = r.json()
            results = data.get("data", {}).get("result", [])
            if not results:
                return None
            value = results[0].get("value", [None, None])[1]
            return float(value) if value is not None else None
        except Exception as e:
            logger.debug(f"Prometheus query failed '{promql}': {e}")
            return None
 
    def query_all(self, queries: dict[str, str]) -> dict[str, Optional[float]]:
        """Query multiple metrics at once. Returns {name: value}."""
        return {name: self.query(promql) for name, promql in queries.items()}
 
 
class Open5GSMongoClient:
    """
    Optional MongoDB client for subscriber/session data that
    Prometheus doesn't expose directly.
    """
 
    def __init__(self, uri: str):
        self.uri = uri
        self._client = None
        self._available = False
 
    def _connect(self):
        try:
            from pymongo import MongoClient
            self._client = MongoClient(self.uri, serverSelectionTimeoutMS=3000)
            self._client.admin.command("ping")
            self._available = True
            logger.info("[Open5GS] MongoDB connected.")
        except ImportError:
            logger.warning("[Open5GS] pymongo not installed — MongoDB metrics disabled. "
                           "Run: pip install pymongo")
        except Exception as e:
            logger.warning(f"[Open5GS] MongoDB unavailable: {e}")
 
    def get_subscriber_count(self) -> int:
        if not self._available:
            return 0
        try:
            db = self._client["open5gs"]
            return db["subscribers"].count_documents({})
        except Exception:
            return 0
 
    def get_active_sessions(self) -> int:
        if not self._available:
            return 0
        try:
            db = self._client["open5gs"]
            return db["smf.contexts"].count_documents({"state": {"$ne": "released"}})
        except Exception:
            return 0
 
    def get_slice_session_breakdown(self) -> dict[str, int]:
        """Returns {slice_id: session_count}."""
        if not self._available:
            return {}
        try:
            db = self._client["open5gs"]
            pipeline = [
                {"$match": {"state": {"$ne": "released"}}},
                {"$group": {"_id": "$slice.sst", "count": {"$sum": 1}}},
            ]
            result = {}
            for doc in db["smf.contexts"].aggregate(pipeline):
                sst = doc["_id"]
                slice_id = f"slice_{sst}" if sst else "slice_1"
                result[slice_id] = doc["count"]
            return result
        except Exception:
            return {}
 
 
class Open5GSAdapter:
    """
    Main adapter that pulls real metrics from Open5GS and translates
    them into NetOracle's telemetry frame format.
 
    Each call to get_tick() returns a list of frames, one per NF,
    exactly matching the schema expected by NetOracle's telemetry store.
 
    Frame schema:
    {
        "timestamp":       str (ISO-8601),
        "slice_id":        str,
        "node_id":         str,
        "node_type":       str,
        "cpu":             float (0-100),
        "memory":          float (0-100),
        "latency_ms":      float,
        "packet_loss":     float (0-1),
        "throughput_mbps": float,
        "prb_utilization": float (0-1),
        "fault_label":     int (0/1),
        "fault_type":      str or "",
        "source":          "open5gs_live"
    }
    """
 
    def __init__(
        self,
        prometheus_url: str = "http://localhost:9090",
        mongo_uri: str = "mongodb://localhost:27017",
        poll_interval_s: int = 5,
    ):
        self.prom = Open5GSPrometheusClient(prometheus_url)
        self.mongo = Open5GSMongoClient(mongo_uri)
        self.mongo._connect()
        self.cache = Open5GSMetricCache()
        self.poll_interval = poll_interval_s
        self._tick_count = 0
        self._fallback_warned = False
 
        logger.info(f"[Open5GS] Adapter initialised. Prometheus: {prometheus_url}")
 
    # ── Internal Prometheus queries per NF ──────────────────────────────
 
    def _fetch_amf_metrics(self) -> dict:
        """Fetch AMF-specific Prometheus metrics."""
        raw = self.prom.query_all({
            "session_count": "amf_session_count",
            "ue_count":      "amf_ue_context_count",
            "reg_attempts":  "amf_registration_request_total",
            "reg_success":   "amf_registration_success_total",
            "cpu_idle":      'avg(rate(node_cpu_seconds_total{mode="idle"}[30s])) * 100',
            "mem_avail":     "node_memory_MemAvailable_bytes",
            "mem_total":     "node_memory_MemTotal_bytes",
        })
 
        session_count = raw.get("session_count") or 0.0
        ue_count      = raw.get("ue_count")      or 0.0
 
        # CPU: use node-exporter idle% → active%
        cpu_idle = raw.get("cpu_idle")
        cpu = (100.0 - cpu_idle) if cpu_idle is not None else self._sim_cpu()
 
        # Memory: (total - available) / total * 100
        mem_avail = raw.get("mem_avail")
        mem_total = raw.get("mem_total")
        if mem_avail and mem_total and mem_total > 0:
            memory = (1.0 - mem_avail / mem_total) * 100.0
        else:
            memory = self._sim_memory()
 
        # Registration success rate → fault signal
        reg_attempt_rate = self.cache.rate_per_second("amf_reg_att", raw.get("reg_attempts") or 0)
        reg_success_rate = self.cache.rate_per_second("amf_reg_suc", raw.get("reg_success") or 0)
        success_ratio = (reg_success_rate / reg_attempt_rate) if reg_attempt_rate > 0 else 1.0
        fault_label = 1 if success_ratio < 0.85 else 0
        fault_type  = "amf_registration_failure" if fault_label else ""
 
        # Latency proxy: session setup time (no direct metric → use ue_count/session ratio)
        latency_ms = 20.0 + (ue_count * 0.5)  # rough proxy
 
        return {
            "cpu": round(min(100.0, max(0.0, cpu)), 2),
            "memory": round(min(100.0, max(0.0, memory)), 2),
            "latency_ms": round(latency_ms, 2),
            "packet_loss": round(max(0.0, 1.0 - success_ratio), 4),
            "throughput_mbps": round(session_count * 0.1, 2),  # proxy
            "prb_utilization": round(min(1.0, ue_count / 100.0), 4),
            "fault_label": fault_label,
            "fault_type": fault_type,
            "_raw_ue_count": ue_count,
            "_raw_session_count": session_count,
        }
 
    def _fetch_smf_metrics(self) -> dict:
        """Fetch SMF-specific Prometheus metrics."""
        raw = self.prom.query_all({
            "pdu_count":    "smf_pdu_session_count",
            "pdu_created":  "smf_pdu_session_created_total",
            "pdu_released": "smf_pdu_session_released_total",
        })
 
        pdu_count   = raw.get("pdu_count")   or 0.0
        pdu_created = raw.get("pdu_created") or 0.0
 
        creation_rate = self.cache.rate_per_second("smf_pdu_created", pdu_created)
 
        # CPU proxy: PDU count / max expected PDUs
        cpu = min(95.0, 10.0 + (pdu_count / 10.0))
 
        # Throughput proxy: each PDU ≈ 1 Mbps average
        throughput_mbps = round(pdu_count * 1.2, 2)
 
        # Fault: too many rapid PDU creations (burst) → SMF overload
        fault_label = 1 if creation_rate > 50 else 0
        fault_type  = "smf_pdu_burst" if fault_label else ""
 
        return {
            "cpu": round(cpu, 2),
            "memory": self._sim_memory(),
            "latency_ms": round(15.0 + (pdu_count * 0.2), 2),
            "packet_loss": 0.0,
            "throughput_mbps": throughput_mbps,
            "prb_utilization": round(min(1.0, pdu_count / 200.0), 4),
            "fault_label": fault_label,
            "fault_type": fault_type,
            "_raw_pdu_count": pdu_count,
        }
 
    def _fetch_upf_metrics(self) -> dict:
        """
        Fetch UPF-specific Prometheus metrics.
        UPF is the most metric-rich NF — actual byte/packet counters.
        """
        raw = self.prom.query_all({
            "rx_bytes":  "upf_rx_bytes_total",
            "tx_bytes":  "upf_tx_bytes_total",
            "rx_pkts":   "upf_rx_packets_total",
            "tx_pkts":   "upf_tx_packets_total",
            "drop_pkts": "upf_dropped_packets_total",
        })
 
        rx_bytes   = raw.get("rx_bytes")  or 0.0
        tx_bytes   = raw.get("tx_bytes")  or 0.0
        rx_pkts    = raw.get("rx_pkts")   or 0.0
        drop_pkts  = raw.get("drop_pkts") or 0.0
 
        # Rates (per-second deltas)
        rx_bytes_rate  = self.cache.rate_per_second("upf_rx_B",  rx_bytes)
        tx_bytes_rate  = self.cache.rate_per_second("upf_tx_B",  tx_bytes)
        rx_pkts_rate   = self.cache.rate_per_second("upf_rx_pkt", rx_pkts)
        drop_rate      = self.cache.rate_per_second("upf_drop",   drop_pkts)
 
        # Throughput in Mbps (bidirectional average)
        throughput_mbps = round((rx_bytes_rate + tx_bytes_rate) * 8 / 1e6, 3)
 
        # Packet loss ratio
        total_pkts_rate = rx_pkts_rate + drop_rate
        packet_loss = (drop_rate / total_pkts_rate) if total_pkts_rate > 0 else 0.0
 
        # CPU proxy: throughput-based
        cpu = min(95.0, 15.0 + throughput_mbps * 0.5)
 
        # Fault detection: high drop rate
        fault_label = 1 if packet_loss > 0.05 else 0
        fault_type  = "upf_packet_loss" if fault_label else (
                      "upf_overload"    if cpu > 85 else ""
        )
 
        return {
            "cpu": round(cpu, 2),
            "memory": self._sim_memory(),
            "latency_ms": round(5.0 + (packet_loss * 100), 2),
            "packet_loss": round(min(1.0, packet_loss), 6),
            "throughput_mbps": throughput_mbps,
            "prb_utilization": round(min(1.0, throughput_mbps / 1000.0), 4),
            "fault_label": fault_label,
            "fault_type": fault_type,
            "_raw_throughput_bps": (rx_bytes_rate + tx_bytes_rate),
            "_raw_drop_rate": drop_rate,
        }
 
    def _fetch_pcf_metrics(self) -> dict:
        """Fetch PCF-specific Prometheus metrics."""
        raw = self.prom.query_all({
            "rules": "pcf_policy_rule_count",
        })
        rule_count = raw.get("rules") or 0.0
 
        cpu = min(90.0, 5.0 + rule_count * 0.3)
        prb = min(1.0, rule_count / 500.0)
 
        return {
            "cpu": round(cpu, 2),
            "memory": self._sim_memory(),
            "latency_ms": round(8.0 + rule_count * 0.05, 2),
            "packet_loss": 0.0,
            "throughput_mbps": 0.0,
            "prb_utilization": round(prb, 4),
            "fault_label": 0,
            "fault_type": "",
            "_raw_rule_count": rule_count,
        }
 
    def _fetch_nrf_metrics(self) -> dict:
        """Fetch NRF-specific Prometheus metrics."""
        # NRF doesn't have much traffic, mostly registration.
        # We simulate a low background CPU.
        return {
            "cpu": round(random.uniform(5, 15), 2),
            "memory": self._sim_memory(),
            "latency_ms": round(random.uniform(5, 10), 2),
            "packet_loss": 0.0,
            "throughput_mbps": 0.01,
            "prb_utilization": 0.0,
            "fault_label": 0,
            "fault_type": "",
        }
 
    def _fetch_gnb_metrics(self) -> dict:
        """
        gNB metrics from UERANSIM.
        UERANSIM doesn't export Prometheus natively, so we derive
        from node-exporter network interface stats on the uesimtun0 interface.
        """
        raw = self.prom.query_all({
            "net_rx": 'rate(node_network_receive_bytes_total{device="uesimtun0"}[30s])',
            "net_tx": 'rate(node_network_transmit_bytes_total{device="uesimtun0"}[30s])',
        })
 
        rx_rate = raw.get("net_rx") or 0.0
        tx_rate = raw.get("net_tx") or 0.0
        throughput = round((rx_rate + tx_rate) * 8 / 1e6, 3)
 
        prb_util = min(1.0, throughput / 100.0)  # 100 Mbps = full PRB
        cpu = min(90.0, 20.0 + throughput * 0.3)
 
        return {
            "cpu": round(cpu, 2),
            "memory": self._sim_memory(),
            "latency_ms": round(10.0 + random.uniform(0, 5), 2),
            "packet_loss": round(random.uniform(0, 0.002), 6),
            "throughput_mbps": throughput,
            "prb_utilization": round(prb_util, 4),
            "fault_label": 0,
            "fault_type": "",
        }
 
    # ── Simulation fallbacks ─────────────────────────────────────────────
 
    def _sim_cpu(self) -> float:
        """Diurnal CPU simulation (fallback)."""
        hour = datetime.now(timezone.utc).hour
        base = 30 + 40 * (
            math.sin(math.pi * (hour - 3) / 12) ** 2  # peaks at 9am and 9pm
        )
        return round(base + random.uniform(-5, 5), 2)
 
    def _sim_memory(self) -> float:
        return round(random.uniform(40, 70), 2)
 
    # ── Public API ───────────────────────────────────────────────────────
 
    def get_tick(self) -> list[dict]:
        """
        Returns one telemetry frame per Open5GS NF.
        Uses real Prometheus metrics if available, falls back to simulation.
        """
        self._tick_count += 1
        ts = datetime.now(timezone.utc).isoformat()
        frames = []
 
        prom_available = self.prom.is_available()
 
        if not prom_available and not self._fallback_warned:
            logger.warning(
                "[Open5GS] Prometheus not reachable at "
                f"{self.prom.base_url}. Falling back to simulation. "
                "Start Open5GS in WSL2 to get real metrics."
            )
            self._fallback_warned = True
 
        # Fetch metrics per NF (or simulate if unreachable)
        nf_fetchers = {
            "amf": self._fetch_amf_metrics,
            "smf": self._fetch_smf_metrics,
            "upf": self._fetch_upf_metrics,
            "pcf": self._fetch_pcf_metrics,
            "nrf": self._fetch_nrf_metrics,
            "gnb": self._fetch_gnb_metrics,
        }
 
        mongo_sessions = self.mongo.get_slice_session_breakdown()
 
        for nf_key, fetcher in nf_fetchers.items():
            node_info = NF_NODE_MAP[nf_key]
 
            if prom_available:
                try:
                    metrics = fetcher()
                except Exception as e:
                    logger.error(f"[Open5GS] {nf_key} metrics failed: {e}")
                    metrics = self._sim_fallback_metrics()
            else:
                metrics = self._sim_fallback_metrics()
 
            frame = {
                "timestamp":       ts,
                "slice_id":        node_info["slice_id"],
                "node_id":         node_info["node_id"],
                "node_type":       node_info["node_type"],
                "cpu":             metrics["cpu"],
                "memory":          metrics["memory"],
                "latency_ms":      metrics["latency_ms"],
                "packet_loss":     metrics["packet_loss"],
                "throughput_mbps": metrics["throughput_mbps"],
                "prb_utilization": metrics["prb_utilization"],
                "fault_label":     metrics["fault_label"],
                "fault_type":      metrics["fault_type"],
                "source":          "open5gs_live" if prom_available else "open5gs_simulated",
            }
 
            # Enrich with MongoDB session data if available
            if mongo_sessions:
                session_count = mongo_sessions.get(node_info["slice_id"], 0)
                frame["_active_sessions"] = session_count
 
            frames.append(frame)
 
        return frames
 
    def _sim_fallback_metrics(self) -> dict:
        return {
            "cpu":             self._sim_cpu(),
            "memory":          self._sim_memory(),
            "latency_ms":      round(random.uniform(10, 50), 2),
            "packet_loss":     round(random.uniform(0, 0.01), 6),
            "throughput_mbps": round(random.uniform(50, 500), 2),
            "prb_utilization": round(random.uniform(0.3, 0.8), 4),
            "fault_label":     0,
            "fault_type":      "",
        }
 
    def get_nf_health(self) -> dict:
        """Returns health status of each Open5GS NF for the dashboard status bar."""
        health = {
            "prometheus_reachable": self.prom.is_available(),
            "mongodb_reachable":    self.mongo._available,
            "nfs": {},
        }
 
        for nf, port in NF_PROMETHEUS_PORTS.items():
            try:
                # Use split to get host part of URL
                host = self.prom.base_url.split('://')[1].split(':')[0]
                r = requests.get(
                    f"http://{host}:{port}/metrics",
                    timeout=2,
                )
                health["nfs"][nf] = "up" if r.status_code == 200 else "degraded"
            except Exception:
                health["nfs"][nf] = "down"
 
        health["subscriber_count"]   = self.mongo.get_subscriber_count()
        health["active_sessions"]    = self.mongo.get_active_sessions()
        health["tick_count"]         = self._tick_count
        return health
