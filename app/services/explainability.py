from datetime import datetime, timezone
from typing import Any

from app.database import db
from app.services.graph import graph_service
from app.services.proactive_engine import proactive_engine

THEORY_BY_TAB = {
    "dashboard": {
        "title": "Predictive risk scoring",
        "equation": "P_fault = σ(w₁·latency + w₂·loss + w₃·PRB + w₄·CPU + graph_prior)",
        "meaning": "The dashboard ranks nodes by future SLA breach probability, not just current threshold violations.",
    },
    "intelligence": {
        "title": "NOTEARS causal discovery",
        "equation": "min_W L(X,W)+λ||W||₁ subject to h(W)=tr(e^{W⊙W})-d=0",
        "meaning": "Edges represent candidate cause-effect relations that remain acyclic and stable across slices.",
    },
    "topology": {
        "title": "Graph risk propagation",
        "equation": "R(v)=σ(αP(v)+βΣᵤR(u)w_uv+γC(v))",
        "meaning": "A node is risky when its local metrics are bad and its upstream/downstream dependencies amplify blast radius.",
    },
    "diagnosis": {
        "title": "Graph-grounded multi-agent diagnosis",
        "equation": "RootCause = argmax_c Σᵢ voteᵢ(c)·confidenceᵢ·graph_support(c)",
        "meaning": "Specialist agents vote, but topology and telemetry evidence constrain the final root cause.",
    },
    "wireless": {
        "title": "CMDP + Hopfield resource control",
        "equation": "maximize E[Σγᵗr_t] subject to E[Σγᵗc_t]≤Cmax; E_H=-1/2ΣᵢΣⱼwᵢⱼsᵢsⱼ+Σᵢθᵢsᵢ",
        "meaning": "The allocator searches for low-energy channel assignments while the CMDP blocks unsafe actions.",
    },
    "audit": {
        "title": "Causal confidence ledger",
        "equation": "Trust = calibration × data_quality × causal_agreement × model_confidence",
        "meaning": "Every event is explainable as a chain of evidence, decision, and safety gate.",
    },
    "datasources": {
        "title": "Data reliability and drift",
        "equation": "Quality = completeness × freshness × schema_validity × distribution_similarity",
        "meaning": "The system checks whether incoming data is fresh, complete, and compatible with the training schema.",
    },
}


class ExplainabilityService:
    def _feature_evidence(self, forecast: dict[str, Any] | None) -> list[dict[str, Any]]:
        if not forecast:
            return []
        labels = {
            "latency_ms": "Latency is rising toward the slice SLA limit.",
            "packet_loss": "Packet loss is increasing, often preceding retransmissions and latency spikes.",
            "prb_utilization": "Radio resource pressure is high and can trigger congestion.",
            "throughput_mbps": "Throughput is dropping relative to expected demand.",
            "cpu": "Compute load is elevated on a network function.",
            "memory": "Memory pressure suggests VNF degradation or leak risk.",
        }
        slopes = forecast.get("metric_slopes", {})
        evidence = []
        for idx, feature in enumerate(forecast.get("top_drivers", []), start=1):
            evidence.append({
                "rank": idx,
                "feature": feature,
                "interpretation": labels.get(feature, "This metric is contributing materially to predicted risk."),
                "trend_per_tick": slopes.get(feature),
            })
        return evidence

    def _trust_score(self, forecast: dict[str, Any] | None) -> dict[str, Any]:
        if not forecast:
            return {"score": 0.0, "components": {}}
        model_confidence = float(forecast.get("confidence", 0.6))
        data_quality = 0.92 if forecast.get("top_drivers") else 0.7
        causal_agreement = 0.78 if forecast.get("top_drivers") else 0.55
        calibration = 0.82 if forecast.get("model") != "multi_horizon_heuristic" else 0.68
        score = round(model_confidence * data_quality * causal_agreement * calibration, 3)
        return {
            "score": score,
            "components": {
                "model_confidence": round(model_confidence, 3),
                "data_quality": data_quality,
                "causal_agreement": causal_agreement,
                "calibration": calibration,
            },
        }

    def explain_tab(self, tab_name: str, node_id: str | None = None) -> dict[str, Any]:
        tab = tab_name.lower().replace("tab-", "")
        theory = THEORY_BY_TAB.get(tab, THEORY_BY_TAB["dashboard"])
        latest = proactive_engine.latest()
        forecast = latest.get("top_forecast")
        if node_id and latest.get("forecasts"):
            forecast = next((item for item in latest["forecasts"] if item.get("node_id") == node_id), forecast)
        narrative = latest.get("narrative") or "NetOracle is waiting for enough telemetry to generate a proactive explanation."
        if tab == "intelligence":
            narrative = "The causal graph shows which metrics tend to move before others. Strong edges are used as causal priors for proactive prediction."
        elif tab == "topology" and forecast:
            path = graph_service.localise({"slice_id": forecast["slice_id"], "node_id": forecast["node_id"], "alert_id": "explain"}).get("affected_path", [])
            path_ids = [
                item.get("node_id", str(item)) if isinstance(item, dict) else str(item)
                for item in path
            ]
            narrative = f"Topology analysis localizes risk around {forecast['node_id']}. Affected path: {' -> '.join(path_ids) if path_ids else forecast['node_id']}."
        elif tab == "diagnosis" and forecast:
            narrative = f"Diagnosis should focus on {forecast['fault_type']} at {forecast['node_id']} because {', '.join(forecast.get('top_drivers', []))} are leading risk drivers."
        elif tab == "wireless" and forecast:
            narrative = f"The policy should prefer {forecast['recommended_action'].replace('_', ' ')} if CMDP safety constraints remain satisfied."
        elif tab == "audit":
            narrative = "The audit trail records each forecast, diagnosis, remediation decision, and export as a causal confidence ledger."
        elif tab == "datasources":
            narrative = "Data source health is judged by schema validity, freshness, completeness, and drift from training distributions."
        result = {
            "tab": tab,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "headline": self._headline(tab, forecast),
            "narrative": narrative,
            "evidence": self._feature_evidence(forecast),
            "theory": theory,
            "trust": self._trust_score(forecast),
            "recommended_next_step": self._next_step(forecast),
            "forecast": forecast,
        }
        db.audit("explain_tab", {"tab": tab, "node_id": node_id, "headline": result["headline"]})
        return result

    def explain_event(self, payload: dict[str, Any]) -> dict[str, Any]:
        event_type = payload.get("event_type", "event")
        data = payload.get("payload", payload)
        return {
            "headline": f"Explanation for {event_type}",
            "narrative": f"NetOracle recorded {event_type}. The important decision fields are action, confidence, risk, node, and safety status.",
            "key_fields": {key: data.get(key) for key in ["node_id", "slice_id", "fault_type", "action", "confidence", "risk", "status"] if key in data},
            "theory": THEORY_BY_TAB["audit"],
        }

    def explain_node(self, node_id: str) -> dict[str, Any]:
        latest = proactive_engine.latest()
        forecast = next((item for item in latest.get("forecasts", []) if item.get("node_id") == node_id), None)
        topology = graph_service.get_node_neighbourhood(node_id, depth=2)
        return {
            "node_id": node_id,
            "headline": self._headline("topology", forecast),
            "forecast": forecast,
            "neighbourhood": topology,
            "evidence": self._feature_evidence(forecast),
            "theory": THEORY_BY_TAB["topology"],
            "trust": self._trust_score(forecast),
        }

    def latest_prediction_explanation(self) -> dict[str, Any]:
        return self.explain_tab("dashboard")

    def _headline(self, tab: str, forecast: dict[str, Any] | None) -> str:
        if not forecast:
            return "System collecting telemetry baseline"
        breach = forecast.get("predicted_breach_time_min")
        if breach is not None and breach <= 10:
            return f"Prevent {forecast['fault_type'].replace('_', ' ')} on {forecast['node_id']} within {breach} min"
        return f"Watch {forecast['node_id']}: future risk {round(forecast.get('risk_t_plus_10', 0)*100)}%"

    def _next_step(self, forecast: dict[str, Any] | None) -> str:
        if not forecast:
            return "Allow telemetry to warm up, then run a demo or ingest CSV/Open5GS data."
        if forecast.get("risk_t_plus_10", 0) >= 0.65:
            return f"Review and simulate {forecast['recommended_action'].replace('_', ' ')} before SLA breach."
        return "Continue monitoring; no immediate preventive action is required."


explainability_service = ExplainabilityService()
