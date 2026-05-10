import csv
import io
import json
from datetime import datetime, timezone
from typing import Any

from app.database import db
from app.services.graph import graph_service
from app.services.intelligence import intelligence_service
from app.services.rag_llm import rag_llm_service
from app.services.remediation import remediation_service


METRIC_COLUMNS = [
    "cpu",
    "memory",
    "latency_ms",
    "packet_loss",
    "throughput_mbps",
    "prb_utilization",
    "queue_depth",
    "sinr",
    "cqi",
    "bgp_updates",
    "tcp_retransmits",
]


class IngestionService:
    def schema(self) -> dict[str, Any]:
        return {
            "required": ["timestamp", "slice_id", "node_id", "node_type"],
            "metrics": METRIC_COLUMNS,
            "optional": ["fault_label", "fault_type"],
            "csv_example": "timestamp,slice_id,node_id,node_type,cpu,memory,latency_ms,packet_loss,throughput_mbps,prb_utilization,fault_label,fault_type",
            "json_shape": [{
                "timestamp": "2026-05-03T10:00:00Z",
                "slice_id": "slice_1",
                "node_id": "upf_1",
                "node_type": "UPF",
                "metrics": {"cpu": 70, "latency_ms": 44, "packet_loss": 0.02},
                "fault_label": 0,
                "fault_type": None,
            }],
        }

    def parse_telemetry_text(self, content: str, filename: str = "uploaded") -> list[dict[str, Any]]:
        content = content.strip("\ufeff\n\r ")
        if not content:
            return []
        if filename.lower().endswith(".json") or content[0] in "[{":
            payload = json.loads(content)
            records = payload if isinstance(payload, list) else payload.get("records", payload.get("telemetry", []))
            return [self._normalise_json_record(record) for record in records]
        reader = csv.DictReader(io.StringIO(content))
        return [self._normalise_csv_record(row) for row in reader]

    def _normalise_json_record(self, record: dict[str, Any]) -> dict[str, Any]:
        metrics = dict(record.get("metrics") or {})
        for column in METRIC_COLUMNS:
            if column in record and column not in metrics:
                metrics[column] = record[column]
        return self._frame(record, metrics)

    def _normalise_csv_record(self, row: dict[str, Any]) -> dict[str, Any]:
        metrics = {column: row.get(column) for column in METRIC_COLUMNS if row.get(column) not in (None, "")}
        return self._frame(row, metrics)

    def _frame(self, record: dict[str, Any], raw_metrics: dict[str, Any]) -> dict[str, Any]:
        metrics = {}
        for key, value in raw_metrics.items():
            try:
                metrics[key] = float(value)
            except (TypeError, ValueError):
                continue
        timestamp = str(record.get("timestamp") or datetime.now(timezone.utc).isoformat())
        return {
            "timestamp": timestamp,
            "slice_id": str(record.get("slice_id") or "slice_1"),
            "node_id": str(record.get("node_id") or "unknown_node"),
            "node_type": str(record.get("node_type") or "Unknown"),
            "metrics": metrics,
            "fault_label": int(float(record.get("fault_label") or 0)),
            "fault_type": record.get("fault_type") or None,
        }

    def ingest_telemetry(self, content: str, filename: str = "uploaded") -> dict[str, Any]:
        frames = self.parse_telemetry_text(content, filename)
        for frame in frames:
            db.insert_telemetry(frame)
        topology = graph_service.sync_from_telemetry(frames, origin="uploaded_data_twin")
        db.audit("telemetry_uploaded", {"filename": filename, "frames": len(frames), "topology": topology})
        return {"filename": filename, "frames_ingested": len(frames), "sample": frames[:3], "topology": topology}

    def ingest_telemetry_stream(self, payload: dict[str, Any]) -> dict[str, Any]:
        frame = self._normalise_json_record(payload)
        db.insert_telemetry(frame)
        return {"status": "ingested", "frame": frame}

    def ingest_topology(self, content: str, filename: str = "topology.json") -> dict[str, Any]:
        payload = json.loads(content)
        nodes = payload.get("nodes", [])
        edges = payload.get("edges", [])
        db.execute("DELETE FROM topology_edges WHERE properties_json LIKE ?", ('%"uploaded_topology"%',))
        db.execute("DELETE FROM topology_nodes WHERE properties_json LIKE ?", ('%"uploaded_topology"%',))
        for node in nodes:
            props = dict(node.get("properties", {}))
            props["origin"] = "uploaded_topology"
            db.execute(
                "INSERT OR REPLACE INTO topology_nodes(node_id, node_type, label, properties_json) VALUES (?, ?, ?, ?)",
                (
                    str(node.get("node_id") or node.get("id")),
                    str(node.get("node_type") or node.get("type") or "Unknown"),
                    str(node.get("label") or node.get("node_id") or node.get("id")),
                    json.dumps(props),
                ),
            )
        for edge in edges:
            props = dict(edge.get("properties", {}))
            props["origin"] = "uploaded_topology"
            db.execute(
                "INSERT INTO topology_edges(source_id, target_id, relation, properties_json) VALUES (?, ?, ?, ?)",
                (
                    str(edge.get("source_id") or edge.get("source")),
                    str(edge.get("target_id") or edge.get("target")),
                    str(edge.get("relation") or edge.get("type") or "CONNECTED_TO"),
                    json.dumps(props),
                ),
            )
        db.audit("topology_uploaded", {"filename": filename, "nodes": len(nodes), "edges": len(edges)})
        return {"filename": filename, "nodes_ingested": len(nodes), "edges_ingested": len(edges)}

    def analyse_uploaded_data(self) -> dict[str, Any]:
        alert = intelligence_service.predict_latest()
        if not alert:
            return {"alert": None, "message": "No fault probability crossed the alert threshold."}
        graph_context = graph_service.localise(alert)
        diagnosis = rag_llm_service.diagnose(alert, graph_context)
        remediation = remediation_service.decide_and_execute(diagnosis)
        return {"alert": alert, "graph_context": graph_context, "diagnosis": diagnosis, "remediation": remediation}


ingestion_service = IngestionService()
