import json
import logging
import re
from collections import deque
from typing import Any, List

import requests
from pydantic import BaseModel, Field

from app.database import db, decode, encode
from app.settings import get_settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pydantic schemas for structured LLM extraction
# ---------------------------------------------------------------------------

class Relationship(BaseModel):
    """A single directed relationship between two network entities."""
    source: str = Field(description="The starting entity (e.g. node_id or component name)")
    target: str = Field(description="The destination entity")
    relation_type: str = Field(description="How they are connected (e.g. DEPENDS_ON, CAUSES, FIXES)")
    context: str = Field(default="", description="Brief explanation of the relationship")


class GraphExtract(BaseModel):
    """Collection of relationships extracted from unstructured text."""
    relationships: List[Relationship]


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

    def get_node_neighbourhood(self, node_id: str, depth: int = 2) -> dict[str, Any]:
        """
        Returns the k-hop neighbourhood of a node from the SQLite property graph.
        Used by GraphRAG to inject topology context into LLM prompts.
        """
        self.seed()
        node_map = {node["node_id"]: node for node in self.nodes()}
        adjacency = self._adjacency()

        visited: set[str] = set()
        frontier = [node_id]
        neighbourhood_nodes: list[dict[str, Any]] = []
        neighbourhood_edges: list[dict[str, Any]] = []

        # Include root node if it exists
        if node_id in node_map:
            root = node_map[node_id]
            neighbourhood_nodes.append({
                "node_id": root["node_id"],
                "node_type": root["node_type"],
                "label": root["label"],
                "hop": 0,
            })

        for hop in range(1, depth + 1):
            next_frontier: list[str] = []
            for nid in frontier:
                if nid in visited:
                    continue
                visited.add(nid)
                for neighbour_id, relation in adjacency.get(nid, []):
                    neighbourhood_edges.append({
                        "source": nid,
                        "target": neighbour_id,
                        "relation": relation,
                    })
                    if neighbour_id not in visited and neighbour_id not in set(frontier):
                        next_frontier.append(neighbour_id)
                        if neighbour_id in node_map:
                            meta = node_map[neighbour_id]
                            neighbourhood_nodes.append({
                                "node_id": meta["node_id"],
                                "node_type": meta["node_type"],
                                "label": meta["label"],
                                "hop": hop,
                            })
            frontier = next_frontier

        return {
            "root": node_id,
            "depth": depth,
            "nodes": neighbourhood_nodes,
            "edges": neighbourhood_edges,
        }

    # -------------------------------------------------------------------
    # GraphRAG: LLM-based entity / relationship extraction
    # -------------------------------------------------------------------

    def _extract_via_ollama(self, text: str) -> GraphExtract | None:
        """Attempt extraction using a local Ollama model."""
        settings = get_settings()
        system_prompt = (
            "You are a technical knowledge extraction agent for a 5G network monitoring system. "
            "Extract system components, errors, faults, and agent actions as entities. "
            "Identify strict, logical relationships between them. "
            "Return ONLY valid JSON matching this schema: "
            '{"relationships": [{"source": "...", "target": "...", "relation_type": "...", "context": "..."}]}'
        )
        try:
            response = requests.post(
                f"{settings.ollama_base_url.rstrip('/')}/api/generate",
                json={
                    "model": settings.model_names[0] if settings.model_names else "phi3:mini",
                    "prompt": f"{system_prompt}\n\nExtract relationships from:\n{text}",
                    "stream": False,
                    "format": "json",
                },
                timeout=30,
            )
            response.raise_for_status()
            raw = response.json().get("response", "{}")
            return GraphExtract.model_validate_json(raw)
        except Exception as exc:
            logger.debug("Ollama extraction failed: %s", exc)
            return None

    def _extract_via_openai(self, text: str) -> GraphExtract | None:
        """Attempt extraction using OpenAI API (requires OPENAI_API_KEY)."""
        settings = get_settings()
        api_key = settings.openai_api_key
        if not api_key:
            return None
        system_prompt = (
            "You are a technical knowledge extraction agent for a 5G network monitoring system. "
            "Extract system components, errors, faults, and agent actions as entities. "
            "Identify strict, logical relationships between them. "
            "Return ONLY valid JSON matching this schema: "
            '{"relationships": [{"source": "...", "target": "...", "relation_type": "...", "context": "..."}]}'
        )
        try:
            response = requests.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={
                    "model": "gpt-4o",
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": f"Extract relationships from:\n{text}"},
                    ],
                    "response_format": {"type": "json_object"},
                },
                timeout=30,
            )
            response.raise_for_status()
            raw = response.json()["choices"][0]["message"]["content"]
            return GraphExtract.model_validate_json(raw)
        except Exception as exc:
            logger.debug("OpenAI extraction failed: %s", exc)
            return None

    @staticmethod
    def _extract_via_regex(text: str) -> GraphExtract:
        """
        Heuristic fallback: extract simple component relationships using regex.
        Looks for known 5G entity patterns in unstructured text.
        """
        entity_patterns = {
            "UPF": r"\b(upf[_\s]?\d*)\b",
            "gNB": r"\b(gnb[_\s]?\d*)\b",
            "Slice": r"\b(slice[_\s]?\d*)\b",
            "Router": r"\b(router[_\s]?\d*)\b",
            "Service": r"\b((?:service|app)[_\s]?\d*)\b",
        }
        found_entities: list[tuple[str, str]] = []  # (normalised_id, entity_type)
        for etype, pattern in entity_patterns.items():
            for match in re.finditer(pattern, text, re.IGNORECASE):
                normalised = re.sub(r"[\s]+", "_", match.group(1).strip().lower())
                found_entities.append((normalised, etype))

        # Deduplicate while preserving order
        seen: set[str] = set()
        unique: list[tuple[str, str]] = []
        for eid, etype in found_entities:
            if eid not in seen:
                seen.add(eid)
                unique.append((eid, etype))

        # Build pairwise relationships based on fault keywords
        relationships: list[Relationship] = []
        fault_keywords = re.findall(r"\b(congestion|overload|latency|packet.?loss|degradation|spike|failure|timeout)\b", text, re.IGNORECASE)
        relation = "RELATED_TO"
        if fault_keywords:
            keyword = fault_keywords[0].lower().replace(" ", "_")
            relation_map = {
                "congestion": "CAUSES", "overload": "CAUSES", "latency": "AFFECTS",
                "packet_loss": "AFFECTS", "degradation": "DEGRADES", "spike": "AFFECTS",
                "failure": "CAUSES", "timeout": "CAUSES",
            }
            relation = relation_map.get(keyword, "RELATED_TO")

        for i in range(len(unique) - 1):
            relationships.append(Relationship(
                source=unique[i][0],
                target=unique[i + 1][0],
                relation_type=relation,
                context=f"Extracted from: {text[:120]}",
            ))

        return GraphExtract(relationships=relationships)

    def extract_graph_data(self, text: str) -> GraphExtract:
        """
        Extract structured graph data from unstructured text.
        Tries Ollama → OpenAI → regex-heuristic fallback (graceful degradation).
        """
        # 1. Try local Ollama
        result = self._extract_via_ollama(text)
        if result and result.relationships:
            logger.info("Extraction via Ollama: %d relationships", len(result.relationships))
            return result

        # 2. Try OpenAI
        result = self._extract_via_openai(text)
        if result and result.relationships:
            logger.info("Extraction via OpenAI: %d relationships", len(result.relationships))
            return result

        # 3. Regex heuristic fallback
        result = self._extract_via_regex(text)
        logger.info("Extraction via regex fallback: %d relationships", len(result.relationships))
        return result

    def ingest_extracted_relationships(self, graph_data: GraphExtract) -> dict[str, Any]:
        """
        Merge extracted relationships into the SQLite property graph.
        Uses INSERT OR IGNORE to avoid duplicates.
        """
        nodes_added = 0
        edges_added = 0

        for rel in graph_data.relationships:
            # Upsert source node
            existing = db.fetch_one(
                "SELECT node_id FROM topology_nodes WHERE node_id = ?", (rel.source,)
            )
            if not existing:
                db.execute(
                    "INSERT OR IGNORE INTO topology_nodes(node_id, node_type, label, properties_json) VALUES (?, ?, ?, ?)",
                    (rel.source, "Extracted", rel.source, encode({"origin": "graphrag_extraction"})),
                )
                nodes_added += 1

            # Upsert target node
            existing = db.fetch_one(
                "SELECT node_id FROM topology_nodes WHERE node_id = ?", (rel.target,)
            )
            if not existing:
                db.execute(
                    "INSERT OR IGNORE INTO topology_nodes(node_id, node_type, label, properties_json) VALUES (?, ?, ?, ?)",
                    (rel.target, "Extracted", rel.target, encode({"origin": "graphrag_extraction"})),
                )
                nodes_added += 1

            # Insert edge
            db.execute(
                "INSERT INTO topology_edges(source_id, target_id, relation, properties_json) VALUES (?, ?, ?, ?)",
                (rel.source, rel.target, rel.relation_type, encode({"context": rel.context, "origin": "graphrag_extraction"})),
            )
            edges_added += 1

        summary = {
            "nodes_added": nodes_added,
            "edges_added": edges_added,
            "total_relationships": len(graph_data.relationships),
        }
        db.audit("graphrag_ingestion", summary)
        logger.info("GraphRAG ingestion: %s", summary)
        return summary

    # -------------------------------------------------------------------
    # NL-to-Cypher (existing)
    # -------------------------------------------------------------------

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
