from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.database import db
from app.services.ctgnn_model import METRICS
from app.services.intelligence import intelligence_service
from app.services.rag_llm import rag_llm_service


class DeltaExplainerService:
    def explain(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = payload or {}
        slice_id = payload.get("slice_id")
        node_id = payload.get("node_id")
        metric_filter = payload.get("metric")

        if not slice_id or not node_id:
            trace = intelligence_service.last_prediction_trace
            if not trace:
                intelligence_service.predict_latest()
                trace = intelligence_service.last_prediction_trace
            if trace:
                slice_id = slice_id or trace.get("slice_id")
                node_id = node_id or trace.get("node_id")

        rows = db.telemetry_for_node(str(slice_id or "slice_1"), str(node_id or "upf_1"), 2)
        if len(rows) < 2:
            return {
                "status": "insufficient_data",
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "message": "Need at least two ticks for the same node to explain a delta.",
                "attribution": {},
                "changes": [],
            }

        prev, curr = rows[-2], rows[-1]
        prev_metrics = prev.get("metrics", {})
        curr_metrics = curr.get("metrics", {})
        prev_attr = intelligence_service._heuristic_risk_explanation(prev_metrics)
        curr_attr = intelligence_service._heuristic_risk_explanation(curr_metrics)
        norm_stats = intelligence_service._norm_stats

        changes = []
        for metric in METRICS:
            if metric_filter and metric != metric_filter:
                continue
            before = float(prev_metrics.get(metric, 0.0) or 0.0)
            after = float(curr_metrics.get(metric, 0.0) or 0.0)
            std = float(norm_stats.get(metric, {}).get("std", 1.0)) or 1.0
            delta = after - before
            sigma = delta / std
            contribution_delta = curr_attr["contributions"].get(metric, 0.0) - prev_attr["contributions"].get(metric, 0.0)
            material = abs(sigma) >= 1.0
            changes.append({
                "metric": metric,
                "previous": round(before, 6),
                "current": round(after, 6),
                "delta": round(delta, 6),
                "sigma_delta": round(sigma, 4),
                "contribution_delta": round(contribution_delta, 6),
                "material": material,
            })

        changes.sort(key=lambda item: abs(item["sigma_delta"]), reverse=True)
        material_changes = [item for item in changes if item["material"]]
        top_change = material_changes[0] if material_changes else (changes[0] if changes else None)
        risk_delta = curr_attr["probability"] - prev_attr["probability"]
        incident = self._nearest_incident(top_change, curr_attr)
        causal_path = self._causal_path(top_change["metric"] if top_change else None)
        narrative = self._narrative(top_change, risk_delta, incident, causal_path)

        return {
            "status": "ready",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "slice_id": slice_id,
            "node_id": node_id,
            "previous_timestamp": prev.get("timestamp"),
            "current_timestamp": curr.get("timestamp"),
            "risk": {
                "previous": prev_attr["probability"],
                "current": curr_attr["probability"],
                "delta": round(risk_delta, 4),
            },
            "attribution": curr_attr,
            "previous_attribution": prev_attr,
            "changes": changes,
            "top_change": top_change,
            "causal_path": causal_path,
            "nearest_incident": incident,
            "explanation": narrative,
        }

    def _nearest_incident(self, top_change: dict[str, Any] | None, attr: dict[str, Any]) -> dict[str, Any] | None:
        query = " ".join([attr.get("fault_type", ""), top_change.get("metric", "") if top_change else ""])
        hits = rag_llm_service.retrieve(query.strip() or "network fault", limit=1)
        return hits[0] if hits else None

    def _causal_path(self, metric: str | None) -> list[str]:
        if not metric:
            return []
        dag = intelligence_service.federated_dag()
        edges = dag.get("global_edges", [])
        path = [metric]
        current = metric
        seen = {metric}
        for _ in range(4):
            edge = next((item for item in edges if item.get("source") == current and item.get("target") not in seen), None)
            if not edge:
                break
            current = edge["target"]
            seen.add(current)
            path.append(current)
        return path

    def _narrative(
        self,
        top_change: dict[str, Any] | None,
        risk_delta: float,
        incident: dict[str, Any] | None,
        causal_path: list[str],
    ) -> str:
        if not top_change:
            return "No metric changed enough between the last two ticks to materially change risk."
        metric = top_change["metric"]
        direction = "increased" if top_change["delta"] >= 0 else "decreased"
        risk_direction = "increased" if risk_delta >= 0 else "decreased"
        incident_text = f" The closest incident memory is {incident['title']}." if incident else ""
        path_text = f" The causal path currently follows {' -> '.join(causal_path)}." if causal_path else ""
        return (
            f"Between the previous tick and this one, {metric} {direction} from "
            f"{top_change['previous']} to {top_change['current']} ({top_change['sigma_delta']:+.2f} sigma). "
            f"The heuristic attribution moved by {top_change['contribution_delta']:+.4f}, and risk "
            f"{risk_direction} by {risk_delta * 100:+.1f} percentage points."
            f"{path_text}{incident_text}"
        )


delta_explainer_service = DeltaExplainerService()
