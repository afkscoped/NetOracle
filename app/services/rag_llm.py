import hashlib
import json
import logging
import math
import asyncio
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any, Optional

import requests
from pydantic import BaseModel, Field

from app.database import db, decode, encode
from app.services.graph import graph_service
from app.settings import get_settings

logger = logging.getLogger(__name__)


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


def build_graphrag_context(node_id: str, vector_hits: list, fault_type: str = None) -> str:
    """
    Upgraded GraphRAG fusion:
    - Vector hits are re-ranked by recency + similarity
    - Graph context is ranked by centrality + path relevance
    - Both are compressed to a token budget before injection
    """
    # Vector context — re-rank by similarity score if available, take top 5
    sorted_hits = sorted(vector_hits, key=lambda h: h.get("score", 0), reverse=True)
    vector_lines = []
    for hit in sorted_hits[:5]:
        score_label = f"(sim={hit['score']:.2f})" if "score" in hit else ""
        vector_lines.append(f"  - {hit.get('summary', hit.get('title', 'Unknown'))} {score_label}")
    vector_context = "\n".join(vector_lines) or "  No past incidents found."

    # Graph context — full ranked neighbourhood
    neighbourhood = graph_service.get_node_neighbourhood_v2(
        node_id=node_id,
        depth=2,
        max_nodes=20,
        fault_type=fault_type,
    )
    graph_context = graph_service.serialise_graphrag_context(neighbourhood, token_budget=500)

    return f"""
## Past Incident Memory (Vector RAG — top {len(sorted_hits[:5])} hits)
{vector_context}

{graph_context}

## Structural Summary
  Top central node in subgraph: {neighbourhood.get('top_node', 'N/A')}
  Total neighbours retrieved: {len(neighbourhood['nodes'])}
  Total edges in subgraph: {len(neighbourhood['edges'])}
"""


# ── Fault Embedding (lightweight, no external model needed) ───────────────

FAULT_EMBEDDING_VOCABULARY = {
    # Radio domain
    "prb": "radio", "interference": "radio", "handover": "radio",
    "rsrp": "radio", "sinr": "radio", "coverage": "radio", "gnodeb": "radio",
    "beam": "radio", "rrh": "radio", "du": "radio", "ru": "radio",
    # Core domain
    "upf": "core", "smf": "core", "amf": "core", "ausf": "core",
    "slice": "core", "qos": "core", "session": "core", "pdu": "core",
    "nrf": "core", "udm": "core", "nssf": "core",
    # Transport domain
    "latency": "transport", "packet_loss": "transport", "link": "transport",
    "routing": "transport", "backhaul": "transport", "fronthaul": "transport",
    "jitter": "transport", "throughput": "transport", "bandwidth": "transport",
    # Security domain
    "intrusion": "security", "anomaly": "security", "auth": "security",
    "dos": "security", "flood": "security", "breach": "security",
}

def _embed_fault(fault_type: str, telemetry_keys: list = None) -> dict:
    """
    Creates a domain score vector from fault text tokens.
    Returns {domain: score} — no external model required.
    """
    tokens = (fault_type or "").lower().replace("_", " ").split()
    if telemetry_keys:
        tokens += [k.lower() for k in telemetry_keys]

    domain_scores = {"radio": 0.0, "core": 0.0, "transport": 0.0, "security": 0.0}
    for token in tokens:
        domain = FAULT_EMBEDDING_VOCABULARY.get(token)
        if domain:
            domain_scores[domain] += 1.0

    # L2 normalise
    magnitude = math.sqrt(sum(v**2 for v in domain_scores.values())) or 1.0
    return {k: round(v / magnitude, 4) for k, v in domain_scores.items()}

def _cosine_similarity(vec_a: dict, vec_b: dict) -> float:
    dot = sum(vec_a.get(k, 0) * vec_b.get(k, 0) for k in vec_a)
    mag_a = math.sqrt(sum(v**2 for v in vec_a.values())) or 1.0
    mag_b = math.sqrt(sum(v**2 for v in vec_b.values())) or 1.0
    return dot / (mag_a * mag_b)


# ── Specialist Persona Registry ───────────────────────────────────────────

SPECIALIST_REGISTRY = {
    "radio": {
        "name": "Radio Access Network Specialist",
        "domain_vector": {"radio": 1.0, "core": 0.0, "transport": 0.1, "security": 0.0},
        "system_prompt": (
            "You are a senior Radio Access Network (RAN) specialist with expertise in "
            "5G NR, gNodeBs, PRB utilisation, beamforming, SINR, interference mitigation, "
            "and handover optimisation. Diagnose faults rigorously. "
            "Output JSON: {root_cause, confidence, affected_components, action, domain}."
        ),
        "weight": 1.0,
    },
    "core": {
        "name": "5G Core Network Specialist",
        "domain_vector": {"radio": 0.0, "core": 1.0, "transport": 0.1, "security": 0.0},
        "system_prompt": (
            "You are a senior 5G Core Network specialist with expertise in UPF, SMF, AMF, "
            "AUSF, NRF, network slicing, QoS enforcement, and PDU session management. "
            "Diagnose faults rigorously. "
            "Output JSON: {root_cause, confidence, affected_components, action, domain}."
        ),
        "weight": 1.0,
    },
    "transport": {
        "name": "Transport & Backhaul Specialist",
        "domain_vector": {"radio": 0.1, "core": 0.0, "transport": 1.0, "security": 0.0},
        "system_prompt": (
            "You are a senior Transport and Backhaul specialist with expertise in "
            "fronthaul/midhaul/backhaul latency, packet loss, link failures, and routing. "
            "Output JSON: {root_cause, confidence, affected_components, action, domain}."
        ),
        "weight": 1.0,
    },
    "security": {
        "name": "Network Security Specialist",
        "domain_vector": {"radio": 0.0, "core": 0.1, "transport": 0.0, "security": 1.0},
        "system_prompt": (
            "You are a senior Network Security specialist. Diagnose DDoS, intrusion, "
            "authentication anomalies, and abnormal traffic patterns in 5G networks. "
            "Output JSON: {root_cause, confidence, affected_components, action, domain}."
        ),
        "weight": 1.0,
    },
}


# ── Embedding-Based MoE Router ────────────────────────────────────────────

def route_to_specialists(
    fault_type: str,
    telemetry: dict = None,
    top_k: int = 2,
    min_similarity: float = 0.15,
) -> list[dict]:
    """
    Upgraded router: uses cosine similarity between fault embedding
    and specialist domain vectors to select top_k specialists.
    Always returns at least 1 specialist.
    """
    telemetry_keys = list(telemetry.keys()) if telemetry else []
    fault_vec = _embed_fault(fault_type, telemetry_keys)

    scored = []
    for key, persona in SPECIALIST_REGISTRY.items():
        sim = _cosine_similarity(fault_vec, persona["domain_vector"])
        scored.append((sim, key, persona))

    scored.sort(key=lambda x: x[0], reverse=True)

    # Take top_k above minimum similarity threshold
    selected = [
        {**persona, "routing_score": round(sim, 4), "specialist_key": key}
        for sim, key, persona in scored[:top_k]
        if sim >= min_similarity
    ]

    # Always guarantee at least one specialist
    if not selected:
        sim, key, persona = scored[0]
        selected = [{**persona, "routing_score": round(sim, 4), "specialist_key": key}]

    logger.info(f"[MoE Router] Fault='{fault_type}' → {[s['name'] for s in selected]}")
    return selected


# ── Multi-Specialist Debate Protocol ─────────────────────────────────────

def call_llm(prompt: str) -> dict:
    """Calls the local Ollama model (or configured model)."""
    settings = get_settings()
    model = settings.model_names[0] if settings.model_names else "phi3:mini"
    try:
        response = requests.post(
            f"{settings.ollama_base_url.rstrip('/')}/api/generate",
            json={"model": model, "prompt": prompt, "stream": False, "format": "json"},
            timeout=30,
        )
        response.raise_for_status()
        text = response.json().get("response", "{}")
        return json.loads(text)
    except Exception as e:
        logger.error(f"call_llm error: {e}")
        return {}


def _call_specialist_llm(specialist: dict, prompt: str) -> dict:
    """
    Calls the LLM with a specialist's system prompt and parses the JSON response.
    Falls back to a structured heuristic if the LLM is unavailable.
    """
    full_prompt = f"{specialist['system_prompt']}\n\n{prompt}"
    try:
        raw = call_llm(full_prompt)
        text = raw.get("text", raw) if isinstance(raw, dict) else str(raw)
        if isinstance(text, str):
            text = text.strip().lstrip("```json").rstrip("```").strip()
            if text:
                parsed = json.loads(text)
            else:
                parsed = raw if isinstance(raw, dict) else {}
        else:
            parsed = text
            
        parsed["specialist"] = specialist["name"]
        parsed["routing_score"] = specialist.get("routing_score", 0.0)
        return parsed
    except Exception as e:
        # Structured fallback
        return {
            "specialist": specialist["name"],
            "root_cause": f"LLM unavailable — heuristic: possible {specialist.get('specialist_key', 'unknown')} domain fault",
            "confidence": 0.40,
            "affected_components": [],
            "action": "escalate_to_human",
            "domain": specialist.get("specialist_key", "unknown"),
            "routing_score": specialist.get("routing_score", 0.0),
            "error": str(e),
        }


def multi_specialist_debate(
    specialists: list[dict],
    prompt: str,
    debate_rounds: int = 1,
) -> dict:
    """
    Multi-round debate protocol:
    Round 1: Each specialist independently diagnoses.
    Round 2: Each specialist sees others' conclusions and can revise.
    Final:    Confidence-weighted ensemble verdict.
    """
    # Round 1 — independent diagnosis
    round1_results = []
    with ThreadPoolExecutor(max_workers=len(specialists)) as executor:
        futures = {executor.submit(_call_specialist_llm, s, prompt): s for s in specialists}
        for future in futures:
            try:
                round1_results.append(future.result(timeout=45))
            except Exception as e:
                round1_results.append({"specialist": futures[future]["name"], "confidence": 0.0, "error": str(e)})

    if debate_rounds < 2 or len(specialists) < 2:
        return _ensemble_verdict(round1_results)

    # Round 2 — each specialist sees others' Round 1 verdicts
    peer_summary = "\n".join([
        f"  [{r.get('specialist', 'Unknown')}]: root_cause='{r.get('root_cause','?')}', "
        f"confidence={r.get('confidence', 0):.2f}, action='{r.get('action','?')}'"
        for r in round1_results
    ])

    debate_prompt = (
        f"{prompt}\n\n"
        f"## Peer Specialist Round 1 Verdicts:\n{peer_summary}\n\n"
        "Review the above peer assessments. Do you agree, partially agree, or disagree? "
        "Provide your revised diagnosis. Output JSON as before."
    )

    round2_results = []
    with ThreadPoolExecutor(max_workers=len(specialists)) as executor:
        futures = {executor.submit(_call_specialist_llm, s, debate_prompt): s for s in specialists}
        for future in futures:
            try:
                round2_results.append(future.result(timeout=45))
            except Exception:
                round2_results.append(round1_results[0])  # fallback to round 1

    return _ensemble_verdict(round2_results, round1_results)


def _ensemble_verdict(
    results: list[dict],
    round1: list[dict] = None,
) -> dict:
    """
    Confidence-weighted ensemble: routing_score * confidence determines each specialist's weight.
    Aggregates root cause by majority-weighted vote.
    """
    if not results:
        return {"error": "No specialist results", "confidence": 0.0}

    total_weight = 0.0
    weighted_confidence = 0.0
    root_cause_votes = {}
    action_votes = {}
    all_components = []

    for r in results:
        conf = float(r.get("confidence", 0.5))
        routing = float(r.get("routing_score", 0.5))
        weight = conf * routing
        total_weight += weight
        weighted_confidence += weight * conf

        cause = r.get("root_cause", "unknown")
        root_cause_votes[cause] = root_cause_votes.get(cause, 0) + weight

        action = r.get("action", "escalate_to_human")
        action_votes[action] = action_votes.get(action, 0) + weight

        comp = r.get("affected_components", [])
        if isinstance(comp, list):
            all_components.extend(comp)

    if total_weight == 0:
        total_weight = 1.0

    top_cause = max(root_cause_votes, key=root_cause_votes.get) if root_cause_votes else "unknown"
    top_action = max(action_votes, key=action_votes.get) if action_votes else "escalate_to_human"
    ensemble_confidence = weighted_confidence / total_weight

    # Consensus score: how strongly do specialists agree?
    consensus = max(root_cause_votes.values()) / total_weight if root_cause_votes else 0.0

    return {
        "root_cause": top_cause,
        "confidence": round(ensemble_confidence, 3),
        "consensus_score": round(consensus, 3),
        "action": top_action,
        "affected_components": list(set(all_components)),
        "specialists_consulted": [r.get("specialist") for r in results],
        "individual_verdicts": results,
        "round1_verdicts": round1,
        "ensemble_method": "confidence_routing_weighted_vote",
    }


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

    def diagnose(self, alert: dict[str, Any], graph_context: dict[str, Any], debate_rounds: int = 2) -> dict[str, Any]:
        """
        Full pipeline:
        1. GraphRAG context fusion
        2. Embedding-based MoE routing (top-2 specialists)
        3. Multi-round specialist debate
        4. Confidence-weighted ensemble verdict
        """
        node_id = alert.get("node_id", "")
        fault_type = alert.get("fault_type", "unknown")
        
        # We can extract telemetry from the alert's features if not explicitly present
        telemetry = alert.get("telemetry", {})
        if not telemetry and "top_features" in alert:
            telemetry = {f: 1.0 for f in alert["top_features"]}

        retrieved = self.retrieve(f"{fault_type} {' '.join(alert.get('top_features', []))}")

        # 1. GraphRAG context
        context_str = build_graphrag_context(node_id, retrieved, fault_type)

        # Build diagnostic prompt
        prompt = f"""
Node Under Diagnosis: {node_id}
Fault Type: {fault_type}
Telemetry: {json.dumps(telemetry, indent=2)}

{context_str}

Provide a rigorous diagnosis. Be specific about root cause and required action.
Output ONLY valid JSON: {{"root_cause": "...", "confidence": 0.0, "affected_components": [], "action": "...", "domain": "..."}}
"""

        # 2. Route to top-2 specialists
        specialists = route_to_specialists(fault_type, telemetry, top_k=2)

        # 3 & 4. Multi-round debate & ensemble verdict
        verdict = multi_specialist_debate(specialists, prompt, debate_rounds=debate_rounds)
        
        confidence = verdict.get("confidence", 0.5)
        root_cause = verdict.get("root_cause", "Network degradation detected")
        action = verdict.get("action", "escalate")

        risk = "low" if confidence >= get_settings().confidence_threshold and alert.get("fault_probability", 0) < 0.92 else "medium"

        diagnosis = {
            "alert_id": alert.get("alert_id", "unknown"),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "root_cause": root_cause,
            "confidence": round(confidence, 3),
            "moe_routing": {
                "experts": [s.get("name") for s in specialists],
                "verdict_consensus": verdict.get("consensus_score", 0.0),
            },
            "evidence": {
                "alert": alert,
                "graphrag_context": context_str,
                "similar_incidents": retrieved,
                "ensemble_method": "multi_specialist_debate",
                "verdict": verdict,
            },
            "recommended_action": action,
            "risk": risk,
        }
        
        db.execute(
            "INSERT OR REPLACE INTO diagnoses(alert_id, timestamp, root_cause, confidence, evidence_json, recommended_action, risk) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (diagnosis["alert_id"], diagnosis["timestamp"], diagnosis["root_cause"], diagnosis["confidence"], encode(diagnosis["evidence"]), diagnosis["recommended_action"], diagnosis["risk"]),
        )
        db.audit("fault_diagnosed", diagnosis)
        return diagnosis


rag_llm_service = RagLlmService()
