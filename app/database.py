import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from app.settings import get_settings


SCHEMA = """
CREATE TABLE IF NOT EXISTS telemetry (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    slice_id TEXT NOT NULL,
    node_id TEXT NOT NULL,
    node_type TEXT NOT NULL,
    metrics_json TEXT NOT NULL,
    fault_label INTEGER NOT NULL DEFAULT 0,
    fault_type TEXT
);
CREATE INDEX IF NOT EXISTS idx_telemetry_time ON telemetry(timestamp);
CREATE INDEX IF NOT EXISTS idx_telemetry_node ON telemetry(slice_id, node_id);

CREATE TABLE IF NOT EXISTS alerts (
    alert_id TEXT PRIMARY KEY,
    timestamp TEXT NOT NULL,
    slice_id TEXT NOT NULL,
    node_id TEXT NOT NULL,
    fault_type TEXT NOT NULL,
    fault_probability REAL NOT NULL,
    horizon_minutes INTEGER NOT NULL,
    top_features_json TEXT NOT NULL,
    causal_edges_json TEXT NOT NULL,
    status TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS topology_nodes (
    node_id TEXT PRIMARY KEY,
    node_type TEXT NOT NULL,
    label TEXT NOT NULL,
    properties_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS topology_edges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id TEXT NOT NULL,
    target_id TEXT NOT NULL,
    relation TEXT NOT NULL,
    properties_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_topology_edges_source ON topology_edges(source_id);
CREATE INDEX IF NOT EXISTS idx_topology_edges_target ON topology_edges(target_id);

CREATE TABLE IF NOT EXISTS incidents (
    incident_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    fault_type TEXT NOT NULL,
    body TEXT NOT NULL,
    embedding_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS diagnoses (
    alert_id TEXT PRIMARY KEY,
    timestamp TEXT NOT NULL,
    root_cause TEXT NOT NULL,
    confidence REAL NOT NULL,
    evidence_json TEXT NOT NULL,
    recommended_action TEXT NOT NULL,
    risk TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    event_type TEXT NOT NULL,
    payload_json TEXT NOT NULL
);
"""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def encode(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


def decode(value: str | None, fallback: Any = None) -> Any:
    if not value:
        return fallback
    return json.loads(value)


def dict_from_row(row: sqlite3.Row) -> dict[str, Any]:
    return {key: row[key] for key in row.keys()}


class Database:
    def __init__(self) -> None:
        self.path = get_settings().db_path
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.init()

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def init(self) -> None:
        with self.connect() as conn:
            conn.executescript(SCHEMA)

    def execute(self, sql: str, params: Iterable[Any] = ()) -> None:
        with self.connect() as conn:
            conn.execute(sql, tuple(params))

    def fetch_all(self, sql: str, params: Iterable[Any] = ()) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()
            return [dict_from_row(row) for row in rows]

    def fetch_one(self, sql: str, params: Iterable[Any] = ()) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(sql, tuple(params)).fetchone()
            return dict_from_row(row) if row else None

    def insert_telemetry(self, frame: dict[str, Any]) -> None:
        # Build the metrics dict — include source so it round-trips through DB
        # (source is NOT a separate column — stored in metrics_json for schema compat)
        metrics = dict(frame.get("metrics") or {})
        for key in ("cpu", "memory", "latency_ms", "packet_loss", "throughput_mbps", "prb_utilization"):
            if key in frame and key not in metrics:
                metrics[key] = frame[key]
        if "source" in frame:
            metrics["_source"] = frame["source"]  # prefixed to avoid collision
        self.execute(
            """
            INSERT INTO telemetry(timestamp, slice_id, node_id, node_type, metrics_json, fault_label, fault_type)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                frame["timestamp"], frame["slice_id"], frame["node_id"], frame["node_type"],
                encode(metrics), int(frame.get("fault_label", 0)), frame.get("fault_type")
            ),
        )

    def latest_telemetry(self, limit: int = 300) -> list[dict[str, Any]]:
        rows = self.fetch_all("SELECT * FROM telemetry ORDER BY id DESC LIMIT ?", (limit,))
        rows.reverse()
        for row in rows:
            metrics = decode(row.pop("metrics_json"), {})
            # Promote _source back to top-level field for downstream consumers
            if "_source" in metrics:
                row["source"] = metrics.pop("_source")
            row["metrics"] = metrics
        return rows

    def telemetry_for_node(self, slice_id: str, node_id: str, limit: int = 60) -> list[dict[str, Any]]:
        rows = self.fetch_all(
            "SELECT * FROM telemetry WHERE slice_id=? AND node_id=? ORDER BY id DESC LIMIT ?",
            (slice_id, node_id, limit),
        )
        rows.reverse()
        for row in rows:
            metrics = decode(row.pop("metrics_json"), {})
            if "_source" in metrics:
                row["source"] = metrics.pop("_source")
            row["metrics"] = metrics
        return rows

    def upsert_alert(self, alert: dict[str, Any]) -> None:
        self.execute(
            """
            INSERT OR REPLACE INTO alerts(alert_id, timestamp, slice_id, node_id, fault_type, fault_probability,
            horizon_minutes, top_features_json, causal_edges_json, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                alert["alert_id"], alert["timestamp"], alert["slice_id"], alert["node_id"], alert["fault_type"],
                float(alert["fault_probability"]), int(alert["horizon_minutes"]), encode(alert["top_features"]),
                encode(alert["causal_edges_used"]), alert.get("status", "open")
            ),
        )

    def latest_alerts(self, limit: int = 20) -> list[dict[str, Any]]:
        rows = self.fetch_all("SELECT * FROM alerts ORDER BY timestamp DESC LIMIT ?", (limit,))
        for row in rows:
            row["top_features"] = decode(row.pop("top_features_json"), [])
            row["causal_edges_used"] = decode(row.pop("causal_edges_json"), [])
        return rows

    def audit(self, event_type: str, payload: dict[str, Any]) -> None:
        self.execute(
            "INSERT INTO audit_log(timestamp, event_type, payload_json) VALUES (?, ?, ?)",
            (utc_now(), event_type, encode(payload)),
        )

    def audit_entries(self, limit: int = 100) -> list[dict[str, Any]]:
        rows = self.fetch_all("SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,))
        for row in rows:
            row["payload"] = decode(row.pop("payload_json"), {})
        return rows


db = Database()
