import hashlib
import json
import logging
import math
import os
import re
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Any, List, Optional

import requests
from pydantic import BaseModel, Field

from app.database import db, decode, encode
from app.settings import get_settings

logger = logging.getLogger(__name__)


def groq_model_candidates() -> list[str]:
    configured = os.getenv("GROQ_MODEL", "").strip()
    return [model for model in [configured, "llama-3.1-8b-instant", "llama3-8b-8192"] if model]


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

    def sync_from_telemetry(
        self,
        frames: list[dict[str, Any]],
        origin: str = "adaptive_data_twin",
        replace_existing: bool = False,
    ) -> dict[str, Any]:
        """
        Infer a clean demo topology from telemetry identities so uploaded or generated
        datasets can reshape the whole product without requiring a separate topology file.
        """
        if not frames:
            return {"nodes_upserted": 0, "edges_upserted": 0, "message": "No telemetry frames supplied."}

        if replace_existing:
            db.execute("DELETE FROM topology_edges")
            db.execute("DELETE FROM topology_nodes")
        else:
            db.execute("DELETE FROM topology_edges WHERE properties_json LIKE ?", (f'%"{origin}"%',))
            db.execute("DELETE FROM topology_nodes WHERE properties_json LIKE ?", (f'%"{origin}"%',))

        node_by_id: dict[str, dict[str, Any]] = {}
        slice_nodes: set[str] = set()
        by_slice: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for frame in frames:
            slice_id = str(frame.get("slice_id") or "slice_1")
            node_id = str(frame.get("node_id") or "unknown_node")
            node_type = str(frame.get("node_type") or "Unknown")
            slice_nodes.add(slice_id)
            if node_id not in node_by_id:
                node_by_id[node_id] = {
                    "node_id": node_id,
                    "node_type": node_type,
                    "label": node_id.replace("_", " ").upper(),
                    "properties": {
                        "origin": origin,
                        "slice_id": slice_id,
                        "telemetry_rows": 0,
                    },
                }
            node_by_id[node_id]["properties"]["telemetry_rows"] += 1
            by_slice[slice_id].append(node_by_id[node_id])

        for slice_id in slice_nodes:
            node_by_id.setdefault(slice_id, {
                "node_id": slice_id,
                "node_type": "Slice",
                "label": slice_id.replace("_", " ").upper(),
                "properties": {"origin": origin, "telemetry_rows": 0},
            })

        type_rank = {"Slice": 0, "gNB": 1, "AMF": 2, "SMF": 3, "UPF": 4, "Router": 5, "Service": 6}
        edge_keys: set[tuple[str, str, str]] = set()
        for slice_id, nodes in by_slice.items():
            unique_nodes = {node["node_id"]: node for node in nodes}.values()
            ordered = sorted(unique_nodes, key=lambda n: (type_rank.get(n["node_type"], 50), n["node_id"]))
            previous = slice_id
            for node in ordered:
                relation = "USES" if previous == slice_id else "FEEDS"
                edge_keys.add((previous, node["node_id"], relation))
                previous = node["node_id"]

        for node in node_by_id.values():
            db.execute(
                "INSERT OR REPLACE INTO topology_nodes(node_id, node_type, label, properties_json) VALUES (?, ?, ?, ?)",
                (node["node_id"], node["node_type"], node["label"], encode(node["properties"])),
            )
        for source, target, relation in sorted(edge_keys):
            if source == target:
                continue
            db.execute(
                "INSERT INTO topology_edges(source_id, target_id, relation, properties_json) VALUES (?, ?, ?, ?)",
                (source, target, relation, encode({"origin": origin, "weight": 1.0})),
            )
        summary = {
            "nodes_upserted": len(node_by_id),
            "edges_upserted": len(edge_keys),
            "origin": origin,
            "replace_existing": replace_existing,
        }
        db.audit("adaptive_topology_synced", summary)
        return summary

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

    # ── Advanced GraphRAG Neighbourhood Retrieval ─────────────────────────

    _NEIGHBOURHOOD_CACHE: dict = {}
    _CACHE_TTL_SECONDS = 60

    @staticmethod
    def _cache_key(node_id: str, depth: int) -> str:
        return hashlib.md5(f"{node_id}:{depth}".encode()).hexdigest()

    EDGE_RELATION_WEIGHTS = {
        "HOSTS":           1.0,
        "CONNECTS_TO":     0.9,
        "DEPENDS_ON":      0.95,
        "GOVERNS":         0.85,
        "SERVES":          0.80,
        "MONITORS":        0.70,
        "SHARES_RESOURCE": 0.75,
        "BACKUP_FOR":      0.60,
    }
    DEFAULT_EDGE_WEIGHT = 0.50

    @staticmethod
    def _compute_local_pagerank(edges: list[dict], iterations: int = 10, damping: float = 0.85) -> dict:
        nodes = set()
        adjacency = defaultdict(list)
        for e in edges:
            nodes.add(e["source"])
            nodes.add(e["target"])
            adjacency[e["source"]].append(e["target"])

        n = len(nodes)
        if n == 0:
            return {}

        rank = {node: 1.0 / n for node in nodes}

        for _ in range(iterations):
            new_rank = {}
            for node in nodes:
                incoming = [s for s, targets in adjacency.items() if node in targets]
                score = (1 - damping) / n
                for src in incoming:
                    out_degree = len(adjacency[src]) or 1
                    score += damping * (rank[src] / out_degree)
                new_rank[node] = score
            rank = new_rank

        return rank

    @classmethod
    def _score_path(cls, path_edges: list[dict]) -> float:
        if not path_edges:
            return 0.0
        score = 1.0
        for edge in path_edges:
            relation = edge.get("relation", "")
            weight = cls.EDGE_RELATION_WEIGHTS.get(relation, cls.DEFAULT_EDGE_WEIGHT)
            score *= weight
        length_penalty = 1.0 / math.log(len(path_edges) + math.e)
        return score * length_penalty

    def get_node_neighbourhood_v2(
        self,
        node_id: str,
        depth: int = 2,
        max_nodes: int = 20,
        fault_type: Optional[str] = None,
    ) -> dict:
        self.seed()
        cache_key = self._cache_key(node_id, depth)
        cached = self._NEIGHBOURHOOD_CACHE.get(cache_key)
        if cached and (time.time() - cached["ts"]) < self._CACHE_TTL_SECONDS:
            return cached["data"]

        visited_nodes = set()
        all_edges = []
        all_nodes = {}
        path_scores = {}

        frontier = [(node_id, [], 0)]

        while frontier:
            current, path, current_depth = frontier.pop(0)
            if current in visited_nodes or current_depth > depth:
                continue
            visited_nodes.add(current)

            rows = db.fetch_all(
                "SELECT target_id, relation FROM topology_edges WHERE source_id = ?",
                (current,)
            )

            for row in rows:
                target_id = row["target_id"]
                relation = row["relation"]
                edge = {"source": current, "target": target_id, "relation": relation}
                edge_weight = self.EDGE_RELATION_WEIGHTS.get(relation, self.DEFAULT_EDGE_WEIGHT)
                edge["weight"] = edge_weight
                all_edges.append(edge)

                new_path = path + [edge]
                path_score = self._score_path(new_path)
                if target_id not in path_scores or path_scores[target_id] < path_score:
                    path_scores[target_id] = path_score

                if target_id not in all_nodes:
                    meta = db.fetch_one(
                        "SELECT node_type, label FROM topology_nodes WHERE node_id = ?",
                        (target_id,)
                    )
                    if meta:
                        all_nodes[target_id] = {
                            "node_id": target_id,
                            "node_type": meta["node_type"],
                            "label": meta["label"],
                        }

                frontier.append((target_id, new_path, current_depth + 1))

        if node_id not in all_nodes:
            meta = db.fetch_one(
                "SELECT node_type, label FROM topology_nodes WHERE node_id = ?",
                (node_id,)
            )
            if meta:
                all_nodes[node_id] = {
                    "node_id": node_id,
                    "node_type": meta["node_type"],
                    "label": meta["label"],
                }

        centrality = self._compute_local_pagerank(all_edges)

        for node_id_key in all_nodes:
            c = centrality.get(node_id_key, 0.0)
            p = path_scores.get(node_id_key, 0.0)
            all_nodes[node_id_key]["relevance_score"] = round(0.6 * c + 0.4 * p, 4)

        ranked_nodes = sorted(
            all_nodes.values(),
            key=lambda n: n["relevance_score"],
            reverse=True
        )[:max_nodes]

        ranked_node_ids = {n["node_id"] for n in ranked_nodes}
        filtered_edges = [
            e for e in all_edges
            if e["source"] in ranked_node_ids or e["target"] in ranked_node_ids
        ]

        result = {
            "anchor_node": node_id,
            "depth": depth,
            "nodes": ranked_nodes,
            "edges": filtered_edges,
            "centrality": {k: round(v, 4) for k, v in centrality.items()},
            "top_node": ranked_nodes[0]["node_id"] if ranked_nodes else None,
            "fault_type_context": fault_type,
        }

        self._NEIGHBOURHOOD_CACHE[cache_key] = {"ts": time.time(), "data": result}
        return result

    def get_node_neighbourhood(self, node_id: str, depth: int = 2, max_nodes: int = 20, fault_type: Optional[str] = None) -> dict:
        return self.get_node_neighbourhood_v2(node_id, depth=depth, max_nodes=max_nodes, fault_type=fault_type)

    @staticmethod
    def serialise_graphrag_context(neighbourhood: dict, token_budget: int = 600) -> str:
        lines = []
        lines.append(f"## Graph Context — Anchor: {neighbourhood['anchor_node']} (depth={neighbourhood['depth']})")

        lines.append("\n### Top Relevant Nodes (ranked by centrality + path relevance):")
        for node in neighbourhood["nodes"][:10]:
            lines.append(
                f"  [{node['node_type']}] {node['node_id']} | label={node.get('label','?')} | relevance={node.get('relevance_score', 0)}"
            )

        lines.append("\n### Key Topology Edges:")
        seen_pairs = set()
        for edge in neighbourhood["edges"][:15]:
            pair = (edge["source"], edge["target"])
            if pair not in seen_pairs:
                seen_pairs.add(pair)
                lines.append(f"  {edge['source']} --[{edge['relation']} w={edge.get('weight', 0.5)}]--> {edge['target']}")

        context = "\n".join(lines)

        char_budget = token_budget * 4
        if len(context) > char_budget:
            context = context[:char_budget] + "\n  ... [truncated to token budget]"

        return context

    # -------------------------------------------------------------------
    # GraphRAG: LLM-based entity / relationship extraction
    # -------------------------------------------------------------------

    def _extract_via_groq(self, text: str) -> GraphExtract | None:
        """Attempt extraction using Groq API."""
        settings = get_settings()
        if not settings.groq_api_key:
            return None
        system_prompt = (
            "You are a technical knowledge extraction agent for a 5G network monitoring system. "
            "Extract system components, errors, faults, and agent actions as entities. "
            "Identify strict, logical relationships between them. "
            "Return ONLY valid JSON matching this schema: "
            '{"relationships": [{"source": "...", "target": "...", "relation_type": "...", "context": "..."}]}'
        )
        for model in groq_model_candidates():
            try:
                response = requests.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={"Authorization": f"Bearer {settings.groq_api_key}", "Content-Type": "application/json"},
                    json={
                        "model": model,
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": f"Extract relationships from:\n{text}"}
                        ],
                        "temperature": 0.1,
                        "response_format": {"type": "json_object"}
                    },
                    timeout=30,
                )
                response.raise_for_status()
                raw = response.json()["choices"][0]["message"]["content"]
                return GraphExtract.model_validate_json(raw)
            except Exception as exc:
                logger.debug("Groq extraction failed for %s: %s", model, exc)
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
        # 1. Try Groq
        result = self._extract_via_groq(text)
        if result and result.relationships:
            logger.info("Extraction via Groq: %d relationships", len(result.relationships))
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

    def _regex_query(self, question: str) -> dict[str, Any]:
        self.seed()
        q = question.lower()
        slice_match = re.search(r"slice\s*([123])", q)
        slice_id = f"slice_{slice_match.group(1)}" if slice_match else "slice_1"
        node_match = re.search(r"\b(?:upf|gnb|router|app|slice|policy|amf|smf|pcf|nrf)[_\s-]?(?:latency|throughput|[123])\b", q)
        node_id = node_match.group(0).replace(" ", "_").replace("-", "_") if node_match else "upf_1"
        nodes = self.nodes()
        edges = self.edges()
        if "last fault" in q or "caused" in q or "root cause" in q:
            audits = db.audit_entries(80)
            fault_events = [
                item for item in audits
                if item.get("event_type") in {"fault_predicted", "fault_diagnosed", "remediation_decision"}
            ]
            cypher = "MATCH (a:Audit) WHERE a.event_type IN ['fault_predicted','fault_diagnosed'] RETURN a ORDER BY a.timestamp DESC LIMIT 5"
            result = fault_events[:5]
        elif "how many" in q and "node" in q:
            slice_edges = [edge for edge in edges if edge["source_id"] == slice_id]
            ids = {slice_id, *[edge["target_id"] for edge in slice_edges]}
            cypher = "MATCH (s:Slice {id:$slice_id})--(n) RETURN count(n)"
            result = [{"slice_id": slice_id, "node_count": len(ids), "nodes": sorted(ids)}]
        elif "share" in q and ("infrastructure" in q or "resource" in q or "control" in q):
            shared_edges = [edge for edge in edges if edge["relation"] in {"PEERS_WITH", "SHARES_CONTROL_PLANE"}]
            ids = {node_id for edge in shared_edges for node_id in (edge["source_id"], edge["target_id"])}
            cypher = "MATCH (a)-[:PEERS_WITH|SHARES_CONTROL_PLANE]-(b) RETURN a,b"
            result = [node for node in nodes if node["node_id"] in ids]
        elif "vnf" in q or "upf" in q or "connected" in q:
            cypher = "MATCH (s:Slice {id:$slice_id})-[:USES]->(:gNB)-[:FORWARDS_TO]->(u:UPF) RETURN u"
            target_ids = set()
            frontier = {slice_id}
            for _ in range(3):
                next_frontier = set()
                for edge in edges:
                    if edge["source_id"] in frontier:
                        next_frontier.add(edge["target_id"])
                target_ids.update(next_frontier)
                frontier = next_frontier
            result = [node for node in nodes if node["node_id"] in target_ids and node["node_type"] in {"UPF", "gNB", "Router", "Service"}]
        elif "policy" in q:
            cypher = "MATCH (s:Slice {id:$slice_id})-[:GOVERNED_BY]->(p:Policy) RETURN p"
            policy_edges = [edge for edge in edges if edge["source_id"] == slice_id and edge["relation"] == "GOVERNED_BY"]
            ids = {edge["target_id"] for edge in policy_edges}
            result = [node for node in nodes if node["node_id"] in ids]
        elif "path" in q:
            cypher = "MATCH path = (s:Slice {id:$slice_id})-[*]->(a:Service) RETURN path"
            result = self.localise({"alert_id": "nl_query", "slice_id": slice_id, "node_id": slice_id.replace("slice", "app")}).get("affected_path", [])
        elif "risk" in q:
            cypher = "MATCH (n) WHERE n.fault_risk > 0.5 RETURN n ORDER BY n.fault_risk DESC"
            result = [
                node for node in nodes
                if float(node.get("properties", {}).get("fault_risk", node.get("properties", {}).get("risk_score", 0)) or 0) > 0.5
            ]
        elif "neighbour" in q or "neighbor" in q:
            cypher = "MATCH (n {id:$node_id})--(m) RETURN m"
            adjacency = self._adjacency()
            ids = {target for target, _ in adjacency.get(node_id, [])}
            result = [node for node in nodes if node["node_id"] in ids]
        else:
            cypher = "MATCH (n) WHERE n.id CONTAINS $keyword OR n.label CONTAINS $keyword RETURN n LIMIT 5"
            keywords = [token for token in re.findall(r"[a-z0-9_]+", q) if len(token) > 2]
            scored = []
            for node in nodes:
                haystack = f"{node.get('node_id','')} {node.get('node_type','')} {node.get('label','')}".lower()
                score = sum(1 for keyword in keywords if keyword in haystack)
                if score:
                    scored.append((score, node))
            result = [node for _, node in sorted(scored, key=lambda item: item[0], reverse=True)[:5]] or nodes[:5]
        answer = ""
        if "last fault" in q or "caused" in q or "root cause" in q:
            diagnosis = next((item for item in result if item.get("event_type") == "fault_diagnosed"), None)
            prediction = next((item for item in result if item.get("event_type") == "fault_predicted"), None)
            payload = (diagnosis or prediction or {}).get("payload", {})
            if diagnosis:
                answer = (
                    f"Last diagnosed fault: {payload.get('root_cause', 'root cause unavailable')} "
                    f"with {round(float(payload.get('confidence', 0)) * 100)}% confidence. "
                    f"Recommended action: {payload.get('recommended_action', 'review manually')}."
                )
            elif prediction:
                answer = (
                    f"Last predicted fault: {payload.get('fault_type', 'unknown fault')} on "
                    f"{payload.get('node_id', 'unknown node')} at {round(float(payload.get('fault_probability', 0)) * 100)}% risk."
                )
            else:
                answer = "No fault diagnosis has been recorded yet. Run a closed-loop demo or inject a fault first."
        return {"cypher": cypher, "parameters": {"slice_id": slice_id, "node_id": node_id}, "result": result, "answer": answer}

    @staticmethod
    def _llm_confidence(method: str) -> float:
        return {
            "groq": 0.88,
            "ollama": 0.76,
            "heuristic": 0.65,
            "fallback": 0.65,
            "regex_fallback": 0.65,
        }.get(method, 0.65)

    def nl_to_cypher(self, question: str) -> dict[str, Any]:
        self.seed()
        few_shot = """You translate natural language questions about a 5G network topology into Cypher queries.
Graph node types: Slice, gNB, AMF, SMF, UPF, PCF, NRF, Router, Service, Policy.
Edges: USES, FEEDS, FORWARDS_TO, EXITS_VIA, SERVES, GOVERNED_BY, PEERS_WITH, SHARES_CONTROL_PLANE.
Node IDs may be static demo IDs like slice_1..3, gnb_1..3, upf_1..3, router_1..3, app_1..3, policy_latency, policy_throughput, or uploaded IDs discovered from telemetry.
Properties: node_id, node_type, label, properties.fault_risk, properties.risk_score, properties.sla, properties.priority.

Q: Which VNFs are connected to Slice 1?
Cypher: MATCH (s:Slice {id:'slice_1'})-[:USES]->(:gNB)-[:FORWARDS_TO]->(u:UPF) RETURN u
Q: What policy governs Slice 2?
Cypher: MATCH (s:Slice {id:'slice_2'})-[:GOVERNED_BY]->(p:Policy) RETURN p
Q: What neighbors does upf_1 have?
Cypher: MATCH (n {id:'upf_1'})--(m) RETURN m
Q: Which nodes have high fault risk?
Cypher: MATCH (n) WHERE n.fault_risk > 0.5 RETURN n ORDER BY n.fault_risk DESC
Q: Show the path from slice_1 to app_1
Cypher: MATCH path = (s:Slice {id:'slice_1'})-[*]->(a:Service {id:'app_1'}) RETURN path
Q: Which slices share infrastructure?
Cypher: MATCH (a)-[:PEERS_WITH|SHARES_CONTROL_PLANE]-(b) RETURN a,b
Q: What caused the last fault?
Cypher: MATCH (a:Audit) WHERE a.event_type IN ['fault_predicted','fault_diagnosed'] RETURN a ORDER BY a.timestamp DESC LIMIT 5
Q: How many nodes are in Slice 1?
Cypher: MATCH (s:Slice {id:'slice_1'})--(n) RETURN count(n)
"""
        cypher = None
        method = "regex_fallback"

        prompt = f"{few_shot}\nReturn only one Cypher MATCH query, no markdown.\nQ: {question}\nCypher:"

        from app.services.rag_llm import call_llm
        try:
            result = call_llm(prompt, max_tokens=200)
            cypher_raw = result.get("text", "")
            method = result.get("source", "fallback")
            for line in cypher_raw.split("\n"):
                stripped = line.strip().strip("`").replace("cypher", "").strip()
                if "MATCH" in stripped.upper() or "RETURN" in stripped.upper():
                    cypher = stripped
                    break
        except Exception as e:
            logger.warning(f"LLM nl-to-cypher failed: {e}")
        fallback = self._regex_query(question)
        payload = {
            "question": question,
            "cypher": cypher or fallback["cypher"],
            "method": method,
            "parameters": fallback["parameters"],
            "result": fallback["result"],
            "answer": fallback.get("answer", ""),
            "confidence": self._llm_confidence(method),
        }
        db.audit("nl_to_cypher", payload)
        return payload


    def update_node_risk(self, node_id: str, risk_score: float) -> None:
        row = db.fetch_one("SELECT properties_json FROM topology_nodes WHERE node_id = ?", (node_id,))
        if not row:
            return
        props = decode(row["properties_json"], {})
        props["fault_risk"] = round(float(risk_score), 4)
        props["risk_score"] = round(float(risk_score), 4)
        props["risk_updated_at"] = datetime.now(timezone.utc).isoformat()
        db.execute(
            "UPDATE topology_nodes SET properties_json = ? WHERE node_id = ?",
            (encode(props), node_id),
        )
        logger.debug("Updated risk score for %s: %f", node_id, risk_score)


graph_service = GraphService()
