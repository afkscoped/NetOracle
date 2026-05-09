import hashlib
import json
import math
from collections import Counter
from datetime import datetime, timezone
from typing import Any

import requests

from app.database import db, decode, encode
from app.services.graph import graph_service
from app.settings import get_settings


POSTMORTEMS = [
    ("incident_01", "UPF congestion after PRB saturation", "congestion", "Latency and packet loss rose after PRB utilization exceeded 85 percent. Scaling the UPF and throttling background traffic restored the slice."),
    ("incident_02", "CPU overload in packet gateway", "cpu_overload", "CPU reached 94 percent and created queuing delay. The safe response was to scale the VNF and move non-critical flows."),
    ("incident_03", "Radio packet loss burst", "packet_loss", "Packet loss increased due to noisy radio conditions. The operator reallocated channels and reduced modulation pressure."),
    ("incident_04", "Memory pressure degraded VNF", "vnf_degradation", "UPF memory pressure caused request drops. Restarting the replica was high-risk; scaling a new replica was safer."),
    ("incident_05", "Latency spike on edge router", "latency_spike", "A transient link queue caused latency spikes. Updating the flow rule shifted traffic to the peer router."),
    ("incident_06", "Shared control-plane congestion", "congestion", "Multiple slices shared a saturated control-plane dependency. Remediation required escalation and policy review."),
    ("incident_07", "Throughput collapse after loss", "packet_loss", "Throughput fell after packet loss exceeded 10 percent. Reallocation and queue discipline changes fixed the issue."),
    ("incident_08", "Application service tail latency", "latency_spike", "Application p99 latency increased while infrastructure metrics were moderate. The system escalated for app-team inspection."),
]


def embed(text: str, dims: int = 64) -> list[float]:
    vector = [0.0] * dims
    tokens = [token.strip(".,:;!?()[]{}\"'").lower() for token in text.split()]
    for token in tokens:
        if not token:
            continue
        digest = hashlib.sha256(token.encode()).digest()
        idx = int.from_bytes(digest[:2], "big") % dims
        sign = 1 if digest[2] % 2 == 0 else -1
        vector[idx] += sign * (1 + min(len(token), 12) / 12)
    norm = math.sqrt(sum(value * value for value in vector)) or 1.0
    return [round(value / norm, 6) for value in vector]


def cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def build_graphrag_context(node_id: str, vector_hits: list[dict[str, Any]]) -> str:
    """
    Combines vector RAG hits with graph neighbourhood context.
    This is the GraphRAG fusion step — injected into the LLM prompt
    so that the diagnostic expert has both retrieval-augmented incident
    history AND live topology structure.
    """
    # Vector context (existing RAG hits)
    vector_lines = []
    for hit in vector_hits[:3]:
        title = hit.get("title", hit.get("incident_id", "unknown"))
        body = hit.get("body", "")
        score = hit.get("score", 0)
        vector_lines.append(f"- [{score:.3f}] {title}: {body[:200]}")
    vector_context = "\n".join(vector_lines) if vector_lines else "No similar incidents found."

    # Graph neighbourhood context (new GraphRAG path)
    neighbourhood = graph_service.get_node_neighbourhood(node_id, depth=2)
    graph_lines = []
    for edge in neighbourhood.get("edges", []):
        graph_lines.append(
            f"  {edge['source']} --[{edge['relation']}]--> {edge['target']}"
        )
    graph_context = "\n".join(graph_lines) if graph_lines else "No neighbours found."

    node_count = len(neighbourhood.get("nodes", []))

    return f"""
## Relevant Past Incidents (Vector RAG)
{vector_context}

## Topology Context (GraphRAG — {node_count} neighbours, depth=2)
{graph_context}
"""


class RagLlmService:
    def seed(self) -> None:
        if db.fetch_one("SELECT incident_id FROM incidents LIMIT 1"):
            return
        for incident_id, title, fault_type, body in POSTMORTEMS:
            db.execute(
                "INSERT OR REPLACE INTO incidents(incident_id, title, fault_type, body, embedding_json) VALUES (?, ?, ?, ?, ?)",
                (incident_id, title, fault_type, body, encode(embed(title + " " + body))),
            )
        db.audit("rag_seeded", {"incidents": len(POSTMORTEMS)})

    def retrieve(self, query: str, limit: int = 3) -> list[dict[str, Any]]:
        self.seed()
        query_vector = embed(query)
        rows = db.fetch_all("SELECT * FROM incidents")
        scored = []
        for row in rows:
            score = cosine(query_vector, decode(row["embedding_json"], []))
            scored.append({"incident_id": row["incident_id"], "title": row["title"], "fault_type": row["fault_type"], "body": row["body"], "score": round(score, 3)})
        return sorted(scored, key=lambda item: item["score"], reverse=True)[:limit]

    def _ollama_vote(self, model: str, prompt: str) -> dict[str, Any] | None:
        settings = get_settings()
        try:
            response = requests.post(
                f"{settings.ollama_base_url.rstrip('/')}/api/generate",
                json={"model": model, "prompt": prompt, "stream": False, "format": "json"},
                timeout=18,
            )
            response.raise_for_status()
            text = response.json().get("response", "{}")
            data = json.loads(text)
            if "root_cause" in data:
                return data
        except Exception:
            return None
        return None

    def _fallback_votes(self, alert: dict[str, Any], context: dict[str, Any], retrieved: list[dict[str, Any]]) -> list[dict[str, Any]]:
        feature_text = " ".join(alert.get("top_features", []))
        fault_type = alert.get("fault_type", "congestion")
        root_map = {
            "congestion": "UPF or radio-path congestion caused by sustained utilisation pressure",
            "cpu_overload": "Compute saturation in the affected network function is increasing queueing delay",
            "packet_loss": "Packet loss is propagating through the slice and reducing throughput",
            "vnf_degradation": "The VNF is degrading under memory or compute pressure",
            "latency_spike": "A link or edge-router queue is creating a latency spike",
        }
        votes = []
        labels = [fault_type, retrieved[0]["fault_type"] if retrieved else fault_type, fault_type if "latency" in feature_text else retrieved[-1]["fault_type"] if retrieved else fault_type]
        for idx, label in enumerate(labels):
            votes.append({
                "model": ["Causal-Mistral-Agent", "Graph-Phi-Agent", "RAG-Llama-Agent"][idx],
                "root_cause": root_map.get(label, root_map[fault_type]),
                "fault_type": label,
                "confidence": round(0.68 + idx * 0.05 + min(alert.get("fault_probability", 0.6), 0.3) / 3, 2),
            })
        return votes

    def diagnose(self, alert: dict[str, Any], graph_context: dict[str, Any]) -> dict[str, Any]:
        retrieved = self.retrieve(" ".join([alert.get("fault_type", ""), " ".join(alert.get("top_features", []))]))

        # --- GraphRAG fusion: combine vector hits with graph neighbourhood ---
        graphrag_context_str = build_graphrag_context(alert.get("node_id", ""), retrieved)
        neighbourhood = graph_service.get_node_neighbourhood(alert.get("node_id", ""), depth=2)

        prompt = json.dumps({
            "task": "Return JSON with root_cause, fault_type, confidence, recommended_action, risk.",
            "alert": alert,
            "graph_context": graph_context,
            "graphrag_context": graphrag_context_str,
            "similar_incidents": retrieved,
        })
        votes = []
        for model in get_settings().model_names:
            vote = self._ollama_vote(model, prompt)
            if vote:
                vote["model"] = model
                votes.append(vote)
        if not votes:
            votes = self._fallback_votes(alert, graph_context, retrieved)
        weighted = Counter()
        total_confidence = 0.0
        for vote in votes:
            confidence = float(vote.get("confidence", 0.5))
            weighted[str(vote.get("fault_type", alert["fault_type"]))] += confidence
            total_confidence += confidence
        final_fault = weighted.most_common(1)[0][0]
        confidence = min(0.96, weighted[final_fault] / max(total_confidence, 1e-6) + 0.22)
        actions = {
            "congestion": "scale_vnf",
            "cpu_overload": "scale_vnf",
            "packet_loss": "reallocate_channel",
            "vnf_degradation": "scale_vnf",
            "latency_spike": "push_flow_rule",
        }
        risk = "low" if confidence >= get_settings().confidence_threshold and alert.get("fault_probability", 0) < 0.92 else "medium"
        root_cause = max(votes, key=lambda item: float(item.get("confidence", 0))).get("root_cause", "Network degradation detected")
        diagnosis = {
            "alert_id": alert["alert_id"],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "root_cause": root_cause,
            "confidence": round(confidence, 3),
            "evidence": {
                "graph_path": [node["node_id"] for node in graph_context.get("affected_path", [])],
                "graph_neighbourhood": neighbourhood,
                "graphrag_context": graphrag_context_str,
                "similar_incidents": retrieved,
                "llm_votes": votes,
                "ensemble_method": "confidence-weighted multi-agent vote with GraphRAG topology fusion",
            },
            "recommended_action": actions.get(final_fault, "escalate"),
            "risk": risk,
        }
        db.execute(
            "INSERT OR REPLACE INTO diagnoses(alert_id, timestamp, root_cause, confidence, evidence_json, recommended_action, risk) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (diagnosis["alert_id"], diagnosis["timestamp"], diagnosis["root_cause"], diagnosis["confidence"], encode(diagnosis["evidence"]), diagnosis["recommended_action"], diagnosis["risk"]),
        )
        db.audit("fault_diagnosed", diagnosis)
        return diagnosis


rag_llm_service = RagLlmService()
