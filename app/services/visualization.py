from typing import Any

from app.services.graph import graph_service
from app.database import db


TYPE_COLORS = {
    "Slice": "#67e8f9",
    "gNB": "#34d399",
    "UPF": "#a78bfa",
    "Router": "#fbbf24",
    "Service": "#f472b6",
    "Policy": "#94a3b8",
    "Unknown": "#e5e7eb",
}


class VisualizationService:
    def scene(self) -> dict[str, Any]:
        graph_service.seed()
        topology = graph_service.topology()
        alerts = db.latest_alerts(20)
        alert_by_node = {alert["node_id"]: alert for alert in alerts}
        nodes = []
        rings = {"Slice": 0, "gNB": 1, "UPF": 2, "Router": 3, "Service": 4, "Policy": 5}
        counts: dict[int, int] = {}
        for node in topology["nodes"]:
            node_type = node.get("node_type", "Unknown")
            ring = rings.get(node_type, 6)
            idx = counts.get(ring, 0)
            counts[ring] = idx + 1
            probability = float(alert_by_node.get(node["node_id"], {}).get("fault_probability", 0.0))
            nodes.append({
                "id": node["node_id"],
                "label": node.get("label", node["node_id"]),
                "type": node_type,
                "color": TYPE_COLORS.get(node_type, TYPE_COLORS["Unknown"]),
                "fault_probability": probability,
                "ring": ring,
                "index": idx,
                "properties": node.get("properties", {}),
            })
        links = [{
            "source": edge["source_id"],
            "target": edge["target_id"],
            "relation": edge["relation"],
            "risk": max(
                float(alert_by_node.get(edge["source_id"], {}).get("fault_probability", 0.0)),
                float(alert_by_node.get(edge["target_id"], {}).get("fault_probability", 0.0)),
            ),
        } for edge in topology["edges"]]
        return {
            "nodes": nodes,
            "links": links,
            "alerts": alerts,
            "legend": TYPE_COLORS,
            "interaction_model": "Three.js digital twin with orbit/fly controls, raycast node picking, fault heatmaps, and audit replay",
        }

    def replay(self, limit: int = 80) -> dict[str, Any]:
        entries = db.audit_entries(limit)
        return {"events": list(reversed(entries)), "count": len(entries)}


visualization_service = VisualizationService()
