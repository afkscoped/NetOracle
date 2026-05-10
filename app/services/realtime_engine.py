from datetime import datetime, timezone
from typing import Any

from app.database import db
from app.services.data_sources import get_adapter
from app.services.graph import graph_service
from app.services.intelligence import intelligence_service
from app.services.proactive_engine import proactive_engine
from app.services.rag_llm import rag_llm_service
from app.services.remediation import remediation_service
from app.services.telemetry import telemetry_service

ACTION_EFFECTS = {
    "scale_upf": {"cpu": 0.74, "memory": 0.84, "latency_ms": 0.78, "packet_loss": 0.72, "throughput_mbps": 1.16, "prb_utilization": 0.82},
    "scale_vnf": {"cpu": 0.72, "memory": 0.82, "latency_ms": 0.80, "packet_loss": 0.76, "throughput_mbps": 1.12, "prb_utilization": 0.86},
    "reroute_slice": {"cpu": 0.92, "memory": 0.96, "latency_ms": 0.62, "packet_loss": 0.48, "throughput_mbps": 1.08, "prb_utilization": 0.80},
    "push_flow_rule": {"cpu": 0.94, "memory": 0.98, "latency_ms": 0.58, "packet_loss": 0.52, "throughput_mbps": 1.10, "prb_utilization": 0.84},
    "reduce_prb_allocation": {"cpu": 0.88, "memory": 0.96, "latency_ms": 0.88, "packet_loss": 0.86, "throughput_mbps": 0.94, "prb_utilization": 0.62},
    "reallocate_channel": {"cpu": 0.96, "memory": 0.98, "latency_ms": 0.74, "packet_loss": 0.42, "throughput_mbps": 1.05, "prb_utilization": 0.70},
    "restart_vnf": {"cpu": 0.68, "memory": 0.62, "latency_ms": 1.10, "packet_loss": 0.90, "throughput_mbps": 0.88, "prb_utilization": 0.90},
    "escalate_to_human": {"cpu": 1.0, "memory": 1.0, "latency_ms": 1.0, "packet_loss": 1.0, "throughput_mbps": 1.0, "prb_utilization": 1.0},
}


def _bounded_metric(metric: str, value: float) -> float:
    if metric in {"cpu", "memory"}:
        return round(max(0.0, min(100.0, value)), 4)
    if metric in {"packet_loss", "prb_utilization"}:
        return round(max(0.0, min(1.0, value)), 6)
    return round(max(0.0, value), 4)


class RealtimeEngine:
    def open5gs_demo_tick(self, prometheus_url: str | None = None, mongo_uri: str | None = None, ingest: bool = True) -> dict[str, Any]:
        from app.services.open5gs_adapter import Open5GSAdapter
        from app.settings import get_settings

        settings = get_settings()
        adapter = Open5GSAdapter(
            prometheus_url=prometheus_url or settings.open5gs_prometheus_url,
            mongo_uri=mongo_uri or settings.open5gs_mongo_uri,
        )
        raw_frames = adapter.get_tick()
        frames = telemetry_service.ingest_external_frames(raw_frames, audit_event="open5gs_demo_tick") if ingest else raw_frames
        health = adapter.get_nf_health()
        alert = intelligence_service.predict_latest()
        proactive = proactive_engine.latest()
        quick = self.quick_fix(alert, proactive)
        simulation = self.simulate_fix({"action": (quick or {}).get("action")})
        result = {
            "mode": "open5gs_demo_addon",
            "core_data_source_unchanged": get_adapter().get_source_info(),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "health": health,
            "frames": frames,
            "alert": alert,
            "proactive": proactive,
            "quick_fix": quick,
            "simulation": simulation,
            "narrative": self._analysis_narrative(alert, proactive, quick, simulation),
        }
        db.audit("open5gs_demo_analysis", {"health": health, "quick_fix": quick, "frame_count": len(frames)})
        return result

    def quick_fix(self, alert: dict[str, Any] | None, proactive: dict[str, Any] | None) -> dict[str, Any] | None:
        top = proactive.get("top_forecast") if proactive else None
        if not alert and not top:
            return None
        node_id = (alert or {}).get("node_id") or (top or {}).get("node_id")
        fault_type = (alert or {}).get("fault_type") or (top or {}).get("fault_type") or "emerging_fault"
        probability = float((alert or {}).get("fault_probability") or (top or {}).get("risk_t_plus_10") or 0.0)
        action = (top or {}).get("recommended_action") or self._default_action(fault_type, (alert or {}).get("top_features", []))
        return {
            "node_id": node_id,
            "fault_type": fault_type,
            "probability": round(probability, 3),
            "action": action,
            "reason": self._reason_for(action, fault_type),
            "urgency": "prevent_now" if probability >= 0.65 else "watch",
        }

    def analyse_once(self, generate_tick: bool = True, run_diagnosis: bool = True) -> dict[str, Any]:
        frames = telemetry_service.generate_tick() if generate_tick else db.latest_telemetry(32)
        alert = intelligence_service.predict_latest()
        proactive = proactive_engine.latest()
        quick = self.quick_fix(alert, proactive)
        graph_context = None
        diagnosis = None
        remediation = None
        if alert and run_diagnosis:
            graph_context = graph_service.localise(alert)
            diagnosis = rag_llm_service.diagnose(alert, graph_context)
            if diagnosis:
                diagnosis["node_id"] = alert.get("node_id")
                remediation = remediation_service.decide_and_execute(diagnosis)
        simulation = self.simulate_fix({"action": (remediation or quick or {}).get("action")})
        source_info = get_adapter().get_source_info()
        result = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "source": source_info,
            "frames": frames[-12:] if isinstance(frames, list) else [],
            "alert": alert,
            "proactive": proactive,
            "quick_fix": quick,
            "graph_context": graph_context,
            "diagnosis": diagnosis,
            "remediation": remediation,
            "simulation": simulation,
            "narrative": self._analysis_narrative(alert, proactive, quick, simulation),
        }
        db.audit("realtime_fault_analysis", {"alert": alert, "quick_fix": quick, "simulation": simulation.get("summary")})
        return result

    def simulate_fix(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = payload or {}
        forecast = proactive_engine.latest().get("top_forecast")
        if not forecast:
            return {"status": "insufficient_data", "message": "No forecast available for fix simulation."}
        rows = db.telemetry_for_node(forecast["slice_id"], forecast["node_id"], 12)
        metrics = rows[-1]["metrics"] if rows else forecast.get("horizon_metrics", {}).get("t_plus_5", {})
        action = str(payload.get("action") or forecast.get("recommended_action") or self._default_action(forecast.get("fault_type"), forecast.get("top_drivers", [])))
        before_risk, before_drivers, _ = intelligence_service._heuristic_risk_score(metrics)
        after_metrics = self._apply_action(metrics, action)
        after_risk, after_drivers, after_fault = intelligence_service._heuristic_risk_score(after_metrics)
        reduction = round(max(0.0, before_risk - after_risk), 3)
        impact = self._impact_rows(metrics, after_metrics)
        result = {
            "status": "simulated",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "node_id": forecast["node_id"],
            "slice_id": forecast["slice_id"],
            "action": action,
            "fault_type_before": forecast.get("fault_type"),
            "fault_type_after": after_fault,
            "risk_before": before_risk,
            "risk_after": after_risk,
            "risk_reduction": reduction,
            "drivers_before": before_drivers,
            "drivers_after": after_drivers,
            "before_metrics": metrics,
            "after_metrics": after_metrics,
            "impact": impact,
            "summary": f"{action.replace('_', ' ')} lowers predicted risk from {round(before_risk * 100)}% to {round(after_risk * 100)}% on {forecast['node_id']}.",
            "visual_model": "Kintsugi recovery map: cracked SLA dimensions are repaired with golden action paths and before/after risk relief lanes.",
        }
        db.audit("fix_simulation", {"node_id": result["node_id"], "action": action, "risk_reduction": reduction})
        return result

    def _apply_action(self, metrics: dict[str, Any], action: str) -> dict[str, float]:
        effect = ACTION_EFFECTS.get(action, ACTION_EFFECTS["escalate_to_human"])
        adjusted = {}
        for metric, value in metrics.items():
            if isinstance(value, (int, float)):
                adjusted[metric] = _bounded_metric(metric, float(value) * float(effect.get(metric, 1.0)))
        for metric in ["cpu", "memory", "latency_ms", "packet_loss", "throughput_mbps", "prb_utilization"]:
            adjusted.setdefault(metric, _bounded_metric(metric, 0.0))
        return adjusted

    def _impact_rows(self, before: dict[str, Any], after: dict[str, Any]) -> list[dict[str, Any]]:
        rows = []
        for metric in ["latency_ms", "packet_loss", "cpu", "memory", "prb_utilization", "throughput_mbps"]:
            b = float(before.get(metric, 0.0) or 0.0)
            a = float(after.get(metric, 0.0) or 0.0)
            better_when_lower = metric != "throughput_mbps"
            improvement = (b - a) if better_when_lower else (a - b)
            denom = max(abs(b), 1e-6)
            rows.append({
                "metric": metric,
                "before": round(b, 4),
                "after": round(a, 4),
                "delta": round(a - b, 4),
                "improvement_pct": round(max(-1.0, min(1.0, improvement / denom)), 4),
                "better": improvement >= 0,
            })
        return rows

    def _default_action(self, fault_type: str | None, drivers: list[str]) -> str:
        fault_type = fault_type or "congestion"
        if fault_type in {"packet_loss", "upf_packet_loss", "latency_spike"}:
            return "reroute_slice"
        if fault_type in {"cpu_overload", "upf_overload", "vnf_degradation", "congestion"}:
            return "scale_upf"
        if "prb_utilization" in drivers:
            return "reduce_prb_allocation"
        return "escalate_to_human"

    def _reason_for(self, action: str, fault_type: str) -> str:
        reasons = {
            "scale_upf": "adds packet-processing headroom before UPF saturation causes SLA breach",
            "scale_vnf": "adds VNF capacity and lowers compute contention",
            "reroute_slice": "moves traffic away from a lossy or latent path",
            "push_flow_rule": "installs a lower-latency route for affected flows",
            "reduce_prb_allocation": "relieves radio congestion by reshaping resource pressure",
            "reallocate_channel": "moves users away from an impaired channel",
            "restart_vnf": "clears degraded VNF state when memory or process health is the root cause",
            "escalate_to_human": "requires operator confirmation because automation safety gates are not satisfied",
        }
        return reasons.get(action, f"best available action for {fault_type}")

    def _analysis_narrative(self, alert: dict[str, Any] | None, proactive: dict[str, Any], quick: dict[str, Any] | None, simulation: dict[str, Any]) -> str:
        if quick:
            return f"Live analysis recommends {quick['action'].replace('_', ' ')} for {quick['node_id']} because {quick['reason']}. {simulation.get('summary', '')}"
        return proactive.get("narrative") or "Live telemetry is nominal; NetOracle is monitoring for emerging faults."


realtime_engine = RealtimeEngine()
