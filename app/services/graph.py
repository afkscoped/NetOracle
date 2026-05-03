import re
from collections import deque
from typing import Any

from app.database import db, decode, encode


TOPOLOGY_NODES = [
    ("slice_1", "Slice", "Ultra Reliable Slice", {"sla": "low-latency", "priority": "gold"}),
    ("slice_2", "Slice", "Enhanced Mobile Broadband Slice", {"sla": "high-throughput", "priority": "silver"}),
    ("slice_3", "Slice", "Massive IoT Slice", {"sla": "high-density", "priority": "bronze"}),
    ("gnb_1", "gNB", "Radio Access Node 1", {"region": "campus-east"}),
    ("gnb_2", "gNB", "Radio Access Node 2", {"region": "campus-west"}),
    ("gnb_3", "gNB", "Radio Access Node 3", {"region": "campus-north"}),
    ("upf_1", "UPF", "User Plane Function 1", {"replicas": 1, "capacity": "medium"}),
    ("upf_2", "UPF", "User Plane Function 2", {"replicas": 1, "capacity": "medium"}),
    ("upf_3", "UPF", "User Plane Function 3", {"replicas": 1, "capacity": "low"}),
    ("router_1", "Router", "Edge Router 1", {"vendor": "simulated"}),
    ("router_2", "Router", "Edge Router 2", {"vendor": "simulated"}),
    ("router_3", "Router", "Edge Router 3", {"vendor": "simulated"}),
    ("app_1", "Service", "AR Surgery Control Service", {"criticality": "high"}),
    ("app_2", "Service", "Video Analytics Service", {"criticality": "medium"}),
    ("app_3", "Service", "IoT Metering Service", {"criticality": "low"}),
    ("policy_latency", "Policy", "Latency Protection Policy", {"max_latency_ms": 45}),
    ("policy_throughput", "Policy", "Throughput Guard Policy", {"min_throughput_mbps": 650}),
]


TOPOLOGY_EDGES = [
    ("slice_1", "gnb_1", "USES"), ("gnb_1", "upf_1", "FORWARDS_TO"), ("upf_1", "router_1", "EXITS_VIA"), ("router_1", "app_1", "SERVES"),
    ("slice_2", "gnb_2", "USES"), ("gnb_2", "upf_2", "FORWARDS_TO"), ("upf_2", "router_2", "EXITS_VIA"), ("router_2", "app_2", "SERVES"),
    ("slice_3", "gnb_3", "USES"), ("gnb_3", "upf_3", "FORWARDS_TO"), ("upf_3", "router_3", "EXITS_VIA"), ("router_3", "app_3", "SERVES"),
    ("slice_1", "policy_latency", "GOVERNED_BY"), ("slice_2", "policy_throughput", "GOVERNED_BY"), ("slice_3", "policy_throughput", "GOVERNED_BY"),
    ("router_1", "router_2", "PEERS_WITH"), ("router_2", "router_3", "PEERS_WITH"), ("upf_1", "upf_2", "SHARES_CONTROL_PLANE"),
]


class GraphService:
    def seed(self) -> None:
        if db.fetch_one("SELECT node_id FROM topology_nodes LIMIT 1"):
            return
        for node_id, node_type, label, props in TOPOLOGY_NODES:
            db.execute(
                "INSERT OR REPLACE INTO topology_nodes(node_id, node_type, label, properties_json) VALUES (?, ?, ?, ?)",
                (node_id, node_type, label, encode(props)),
            )
        for source, target, relation in TOPOLOGY_EDGES:
            db.execute(
                "INSERT INTO topology_edges(source_id, target_id, relation, properties_json) VALUES (?, ?, ?, ?)",
                (source, target, relation, encode({"weight": 1.0})),
            )
        db.audit("topology_seeded", {"nodes": len(TOPOLOGY_NODES), "edges": len(TOPOLOGY_EDGES)})

    def nodes(self) -> list[dict[str, Any]]:
        rows = db.fetch_all("SELECT * FROM topology_nodes ORDER BY node_type, node_id")
        for row in rows:
            row["properties"] = decode(row.pop("properties_json"), {})
        return rows

    def edges(self) -> list[dict[str, Any]]:
        rows = db.fetch_all("SELECT * FROM topology_edges ORDER BY id")
        for row in rows:
            row["properties"] = decode(row.pop("properties_json"), {})
        return rows

    def topology(self) -> dict[str, Any]:
        return {"nodes": self.nodes(), "edges": self.edges()}

    def _adjacency(self) -> dict[str, list[tuple[str, str]]]:
        adjacency: dict[str, list[tuple[str, str]]] = {}
        for edge in self.edges():
            adjacency.setdefault(edge["source_id"], []).append((edge["target_id"], edge["relation"]))
            adjacency.setdefault(edge["target_id"], []).append((edge["source_id"], edge["relation"]))
        return adjacency

    def localise(self, alert: dict[str, Any]) -> dict[str, Any]:
        self.seed()
        node_map = {node["node_id"]: node for node in self.nodes()}
        adjacency = self._adjacency()
        start = alert["slice_id"]
        target = alert["node_id"]
        queue = deque([(start, [start])])
        seen = {start}
        path = [start, target] if start != target else [start]
        while queue:
            current, current_path = queue.popleft()
            if current == target:
                path = current_path
                break
            for nxt, _ in adjacency.get(current, []):
                if nxt not in seen:
                    seen.add(nxt)
                    queue.append((nxt, current_path + [nxt]))
        neighbours = sorted({nxt for node in path for nxt, _ in adjacency.get(node, []) if nxt not in path})
        policies = [node for node in neighbours + path if node_map.get(node, {}).get("node_type") == "Policy"]
        context = {
            "alert_id": alert["alert_id"],
            "affected_path": [{"node_id": item, **node_map.get(item, {})} for item in path],
            "neighbouring_at_risk": [{"node_id": item, **node_map.get(item, {})} for item in neighbours],
            "active_policies": [{"node_id": item, **node_map.get(item, {})} for item in policies],
            "localisation_confidence": 0.91 if target in path else 0.63,
            "query_strategy": "in-memory property graph BFS with Neo4j-compatible schema",
        }
        db.audit("fault_localised", context)
        return context

    def nl_to_cypher(self, question: str) -> dict[str, Any]:
        self.seed()
        q = question.lower()
        slice_match = re.search(r"slice\s*([123])", q)
        slice_id = f"slice_{slice_match.group(1)}" if slice_match else "slice_1"
        if "vnf" in q or "upf" in q or "connected" in q:
            cypher = "MATCH (s:Slice {id:$slice_id})-[:USES]->(:gNB)-[:FORWARDS_TO]->(u:UPF) RETURN u"
            result = [node for node in self.nodes() if node["node_id"] == slice_id.replace("slice", "upf")]
        elif "policy" in q:
            cypher = "MATCH (s:Slice {id:$slice_id})-[:GOVERNED_BY]->(p:Policy) RETURN p"
            edges = [edge for edge in self.edges() if edge["source_id"] == slice_id and edge["relation"] == "GOVERNED_BY"]
            ids = {edge["target_id"] for edge in edges}
            result = [node for node in self.nodes() if node["node_id"] in ids]
        elif "risk" in q or "neighbour" in q or "neighbor" in q:
            cypher = "MATCH (n {id:$node_id})--(m) RETURN m"
            result = self.nodes()[:5]
        else:
            cypher = "MATCH (n) RETURN n LIMIT 10"
            result = self.nodes()[:10]
        payload = {"question": question, "cypher": cypher, "parameters": {"slice_id": slice_id}, "result": result, "confidence": 0.76}
        db.audit("nl_to_cypher", payload)
        return payload


graph_service = GraphService()
