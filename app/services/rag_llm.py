import hashlib
import json
import logging
import math
from collections import Counter
from datetime import datetime, timezone
from typing import Any

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


# ---------------------------------------------------------------------------
# Mixture-of-Experts: Specialist Personas & Router
# ---------------------------------------------------------------------------

SPECIALIST_PERSONAS = {
    "radio": {
        "name": "Radio Access Network Specialist",
        "trigger_fault_types": [
            "prb_congestion", "interference", "handover_failure", "coverage",
            "congestion",  # radio-path congestion maps here
        ],
        "system_prompt": (
            "You are a Radio Access Network (RAN) specialist. "
            "You diagnose faults in gNodeBs, PRB utilisation, interference patterns, "
            "and handover failures. Focus on physical layer and air interface metrics."
        ),
    },
    "core": {
        "name": "Core Network Specialist",
        "trigger_fault_types": [
            "upf_overload", "smf_failure", "slice_qos", "amf_timeout",
            "cpu_overload", "vnf_degradation",  # VNF / control-plane faults map here
        ],
        "system_prompt": (
            "You are a 5G Core Network specialist. "
            "You diagnose faults in UPF, SMF, AMF, and network slicing. "
            "Focus on session management, QoS policies, and user plane traffic."
        ),
    },
    "transport": {
        "name": "Transport & Backhaul Specialist",
        "trigger_fault_types": [
            "latency_spike", "packet_loss", "link_down", "routing",
        ],
        "system_prompt": (
            "You are a transport and backhaul network specialist. "
            "You diagnose latency spikes, packet loss, link failures, and routing anomalies. "
            "Focus on fronthaul/backhaul paths and midhaul transport metrics."
        ),
    },
    "default": {
        "name": "General Network Operations Specialist",
        "trigger_fault_types": [],
        "system_prompt": (
            "You are a general 5G network operations specialist. "
            "Diagnose faults across RAN, Core, and Transport domains."
        ),
    },
}


class RoutingDecision(BaseModel):
    """Structured record of which MoE specialist was selected and why."""
    expert_key: str = Field(description="Key into SPECIALIST_PERSONAS (radio/core/transport/default)")
    expert_name: str = Field(description="Human-readable specialist name")
    confidence_score: float = Field(description="Routing confidence 0.0-1.0")
    reasoning: str = Field(description="Brief reason for this routing decision")
    routing_method: str = Field(
        default="keyword",
        description="Which routing path was used: 'llm_openai', 'llm_groq', 'llm_ollama', 'keyword', 'fallback'"
    )


def _route_via_keyword(fault_type: str) -> RoutingDecision:
    """
    Legacy MoE Router: maps a fault type to the appropriate specialist persona
    using keyword matching against trigger_fault_types for each persona.
    Preserved as a fast fallback when no LLM is available.
    """
    fault_lower = fault_type.lower().strip() if fault_type else ""

    for persona_key, persona in SPECIALIST_PERSONAS.items():
        if persona_key == "default":
            continue
        for trigger in persona["trigger_fault_types"]:
            if trigger in fault_lower or fault_lower in trigger:
                logger.info(
                    "[MoE Router] Keyword routing fault '%s' → %s", fault_type, persona["name"]
                )
                return RoutingDecision(
                    expert_key=persona_key,
                    expert_name=persona["name"],
                    confidence_score=0.92,
                    reasoning=f"Fault type '{fault_type}' matched trigger '{trigger}' for {persona['name']}",
                    routing_method="keyword",
                )

    logger.info("[MoE Router] No specialist matched for '%s', using default.", fault_type)
    default = SPECIALIST_PERSONAS["default"]
    return RoutingDecision(
        expert_key="default",
        expert_name=default["name"],
        confidence_score=0.50,
        reasoning=f"No specialist trigger matched fault type '{fault_type}'; routing to general expert",
        routing_method="keyword",
    )


# Keep the old function name as an alias for backward compatibility
route_to_specialist = _route_via_keyword


class MoERouter:
    """
    Intelligent Mixture-of-Experts Gatekeeper Router.

    Routes incoming diagnostic queries to the most appropriate specialist
    using a lightweight LLM call with structured JSON output. Falls back
    through a chain: OpenAI → Groq → Ollama → keyword matching.
    """

    # The structured schema we require from the LLM router
    ROUTING_SCHEMA = {
        "type": "object",
        "properties": {
            "expert_key": {
                "type": "string",
                "enum": ["radio", "core", "transport", "default"],
                "description": "Key of the selected specialist persona"
            },
            "confidence_score": {
                "type": "number",
                "minimum": 0.0,
                "maximum": 1.0,
                "description": "Routing confidence from 0.0 to 1.0"
            },
            "reasoning": {
                "type": "string",
                "description": "Brief reason for this routing decision"
            }
        },
        "required": ["expert_key", "confidence_score", "reasoning"]
    }

    def _build_router_prompt(self, user_query: str, graph_context: str = "") -> list[dict[str, str]]:
        """Build the gatekeeper prompt for the routing LLM call."""
        expert_descriptions = "\n".join(
            f"  - {key}: {persona['name']} — {persona['system_prompt']}"
            for key, persona in SPECIALIST_PERSONAS.items()
        )

        system_prompt = f"""You are a routing gatekeeper for a 5G network diagnostic system.
Your job is to analyse the incoming query and assign it to the most relevant specialist expert.

Available Experts:
{expert_descriptions}

You MUST respond with a JSON object containing exactly these fields:
- "expert_key": one of ["radio", "core", "transport", "default"]
- "confidence_score": a float between 0.0 and 1.0 reflecting your confidence
- "reasoning": a brief explanation of why you chose this expert

Consider the fault type, symptoms, affected components, and any topology context provided.
If the query clearly involves radio/PRB/interference → radio
If the query involves UPF/SMF/AMF/VNF/CPU/memory → core
If the query involves latency/packet_loss/routing/links → transport
If ambiguous or multi-domain → default"""

        user_content = f"Query: {user_query}"
        if graph_context:
            user_content += f"\n\nTopology Context:\n{graph_context[:500]}"

        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]

    def _parse_routing_response(self, raw_json: str, method: str) -> RoutingDecision | None:
        """Parse and validate a JSON routing response from any LLM provider."""
        try:
            data = json.loads(raw_json)
            expert_key = data.get("expert_key", "default")
            if expert_key not in SPECIALIST_PERSONAS:
                expert_key = "default"
            confidence = float(data.get("confidence_score", 0.5))
            confidence = max(0.0, min(1.0, confidence))
            reasoning = str(data.get("reasoning", "LLM routing decision"))
            persona = SPECIALIST_PERSONAS[expert_key]
            return RoutingDecision(
                expert_key=expert_key,
                expert_name=persona["name"],
                confidence_score=round(confidence, 3),
                reasoning=reasoning,
                routing_method=method,
            )
        except (json.JSONDecodeError, KeyError, ValueError) as exc:
            logger.debug("[MoE Router] Failed to parse LLM response (%s): %s", method, exc)
            return None

    def _route_via_openai(self, messages: list[dict[str, str]]) -> RoutingDecision | None:
        """Route using OpenAI API with structured JSON output (gpt-4o-mini for speed)."""
        settings = get_settings()
        api_key = settings.openai_api_key
        if not api_key:
            return None

        try:
            response = requests.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={
                    "model": "gpt-4o-mini",
                    "messages": messages,
                    "response_format": {"type": "json_object"},
                    "temperature": 0.1,
                    "max_tokens": 200,
                },
                timeout=8,
            )
            response.raise_for_status()
            raw = response.json()["choices"][0]["message"]["content"]
            return self._parse_routing_response(raw, "llm_openai")
        except Exception as exc:
            logger.debug("[MoE Router] OpenAI routing failed: %s", exc)
            return None

    def _route_via_groq(self, messages: list[dict[str, str]]) -> RoutingDecision | None:
        """Route using Groq API for ultra-low-latency inference."""
        settings = get_settings()
        api_key = settings.groq_api_key
        if not api_key:
            return None

        try:
            response = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={
                    "model": "llama-3.1-8b-instant",
                    "messages": messages,
                    "response_format": {"type": "json_object"},
                    "temperature": 0.1,
                    "max_tokens": 200,
                },
                timeout=6,
            )
            response.raise_for_status()
            raw = response.json()["choices"][0]["message"]["content"]
            return self._parse_routing_response(raw, "llm_groq")
        except Exception as exc:
            logger.debug("[MoE Router] Groq routing failed: %s", exc)
            return None

    def _route_via_ollama(self, messages: list[dict[str, str]]) -> RoutingDecision | None:
        """Route using a local Ollama model."""
        settings = get_settings()
        model = settings.model_names[0] if settings.model_names else "phi3:mini"
        # Flatten messages into a single prompt for the generate API
        prompt = "\n".join(f"{m['role'].upper()}: {m['content']}" for m in messages)

        try:
            response = requests.post(
                f"{settings.ollama_base_url.rstrip('/')}/api/generate",
                json={
                    "model": model,
                    "prompt": prompt,
                    "stream": False,
                    "format": "json",
                },
                timeout=10,
            )
            response.raise_for_status()
            raw = response.json().get("response", "{}")
            return self._parse_routing_response(raw, "llm_ollama")
        except Exception as exc:
            logger.debug("[MoE Router] Ollama routing failed: %s", exc)
            return None

    def route(self, fault_type: str, user_query: str = "", graph_context: str = "") -> RoutingDecision:
        """
        Main routing entry point. Attempts LLM-based routing through
        a fallback chain (Groq → OpenAI → Ollama), then falls back to
        keyword matching if all LLM providers are unavailable.

        Groq is tried first due to its ultra-low latency, making it
        ideal for a fast gatekeeper decision.
        """
        # Build query from fault_type if no explicit user query provided
        query = user_query or f"Diagnose fault: {fault_type}"
        messages = self._build_router_prompt(query, graph_context)

        # Try LLM providers in order: Groq (fastest) → OpenAI → Ollama (local)
        for route_fn, label in [
            (self._route_via_groq, "Groq"),
            (self._route_via_openai, "OpenAI"),
            (self._route_via_ollama, "Ollama"),
        ]:
            decision = route_fn(messages)
            if decision is not None:
                logger.info(
                    "[MoE Router] LLM routing via %s → %s (confidence=%.2f)",
                    label, decision.expert_name, decision.confidence_score,
                )
                db.audit("moe_routing", {
                    "method": decision.routing_method,
                    "expert": decision.expert_key,
                    "confidence": decision.confidence_score,
                    "reasoning": decision.reasoning,
                })
                return decision

        # Fallback to keyword matching
        logger.info("[MoE Router] All LLM providers unavailable, falling back to keyword routing")
        return _route_via_keyword(fault_type)


# Module-level singleton
moe_router = MoERouter()


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

    def _ollama_vote(self, model: str, prompt: str, system_prompt: str = "") -> dict[str, Any] | None:
        """Call an Ollama model with an optional specialist system prompt."""
        settings = get_settings()
        full_prompt = f"{system_prompt}\n\n{prompt}" if system_prompt else prompt
        try:
            response = requests.post(
                f"{settings.ollama_base_url.rstrip('/')}/api/generate",
                json={"model": model, "prompt": full_prompt, "stream": False, "format": "json"},
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

    def _fallback_votes(
        self,
        alert: dict[str, Any],
        context: dict[str, Any],
        retrieved: list[dict[str, Any]],
        routing: RoutingDecision | None = None,
    ) -> list[dict[str, Any]]:
        """Generate deterministic fallback votes when Ollama is unavailable."""
        feature_text = " ".join(alert.get("top_features", []))
        fault_type = alert.get("fault_type", "congestion")
        specialist_name = routing.expert_name if routing else "General Network Operations Specialist"
        root_map = {
            "congestion": "UPF or radio-path congestion caused by sustained utilisation pressure",
            "cpu_overload": "Compute saturation in the affected network function is increasing queueing delay",
            "packet_loss": "Packet loss is propagating through the slice and reducing throughput",
            "vnf_degradation": "The VNF is degrading under memory or compute pressure",
            "latency_spike": "A link or edge-router queue is creating a latency spike",
        }
        votes = []
        labels = [
            fault_type,
            retrieved[0]["fault_type"] if retrieved else fault_type,
            fault_type if "latency" in feature_text else retrieved[-1]["fault_type"] if retrieved else fault_type,
        ]
        # Tag each fallback agent with the specialist persona
        agent_names = [
            f"Causal-{specialist_name.split()[0]}-Agent",
            f"Graph-{specialist_name.split()[0]}-Agent",
            f"RAG-{specialist_name.split()[0]}-Agent",
        ]
        for idx, label in enumerate(labels):
            votes.append({
                "model": agent_names[idx],
                "specialist": specialist_name,
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

        # --- MoE routing: LLM-based gatekeeper with fallback chain ---
        fault_type = alert.get("fault_type", "")
        user_query = f"Diagnose {fault_type} fault on node {alert.get('node_id', '')} in slice {alert.get('slice_id', '')}"
        routing = moe_router.route(
            fault_type=fault_type,
            user_query=user_query,
            graph_context=graphrag_context_str,
        )
        specialist_persona = SPECIALIST_PERSONAS.get(routing.expert_key, SPECIALIST_PERSONAS["default"])
        specialist_system_prompt = specialist_persona["system_prompt"]

        # --- Build the specialist-aware prompt ---
        prompt = json.dumps({
            "task": "Return JSON with root_cause, fault_type, confidence, recommended_action, risk.",
            "specialist": routing.expert_name,
            "alert": alert,
            "graph_context": graph_context,
            "graphrag_context": graphrag_context_str,
            "similar_incidents": retrieved,
        })

        # --- Multi-agent voting with specialist system prompt ---
        votes = []
        for model in get_settings().model_names:
            vote = self._ollama_vote(model, prompt, system_prompt=specialist_system_prompt)
            if vote:
                vote["model"] = model
                vote["specialist"] = routing.expert_name
                votes.append(vote)
        if not votes:
            votes = self._fallback_votes(alert, graph_context, retrieved, routing=routing)

        # --- Confidence-weighted ensemble ---
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
            "moe_routing": routing.model_dump(),
            "evidence": {
                "alert": alert,
                "graph_path": [node["node_id"] for node in graph_context.get("affected_path", [])],
                "graph_neighbourhood": neighbourhood,
                "graphrag_context": graphrag_context_str,
                "similar_incidents": retrieved,
                "llm_votes": votes,
                "ensemble_method": "MoE-routed specialist vote with GraphRAG topology fusion",
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
