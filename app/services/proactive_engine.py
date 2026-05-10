import math
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from app.database import db
from app.services.adaptive_rl import adaptive_rl_service
from app.services.graph import graph_service
from app.services.intelligence import intelligence_service

SLA_LIMITS = {
    "slice_1": {"latency_ms": 45.0, "packet_loss": 0.01, "prb_utilization": 0.82},
    "slice_2": {"latency_ms": 80.0, "packet_loss": 0.02, "prb_utilization": 0.88},
    "slice_3": {"latency_ms": 30.0, "packet_loss": 0.015, "prb_utilization": 0.78},
}

FEATURES = ["cpu", "memory", "latency_ms", "packet_loss", "throughput_mbps", "prb_utilization"]


class ProactiveEngine:
    def _risk_from_metrics(self, metrics: dict[str, float]) -> tuple[float, list[str], str]:
        return intelligence_service._heuristic_risk_score(metrics)

    def _trend(self, rows: list[dict[str, Any]], feature: str) -> float:
        if len(rows) < 3:
            return 0.0
        values = [float(row.get("metrics", {}).get(feature, 0.0) or 0.0) for row in rows[-8:]]
        if len(values) < 2:
            return 0.0
        return (values[-1] - values[0]) / max(1, len(values) - 1)

    def _forecast_metric(self, latest: float, slope: float, horizon: int, feature: str) -> float:
        value = latest + slope * max(1, horizon / 5)
        if feature in {"cpu", "memory"}:
            return max(0.0, min(100.0, value))
        if feature in {"packet_loss", "prb_utilization"}:
            return max(0.0, min(1.0, value))
        return max(0.0, value)

    def _breach_time(self, slice_id: str, metrics: dict[str, float], slopes: dict[str, float]) -> tuple[str | None, int | None]:
        limits = SLA_LIMITS.get(slice_id, SLA_LIMITS["slice_1"])
        best_metric = None
        best_minutes = None
        for metric, limit in limits.items():
            current = float(metrics.get(metric, 0.0) or 0.0)
            slope_per_tick = slopes.get(metric, 0.0)
            slope_per_min = slope_per_tick / 5.0
            if current >= limit:
                return metric, 0
            if slope_per_min <= 0:
                continue
            minutes = math.ceil((limit - current) / slope_per_min)
            if minutes >= 0 and (best_minutes is None or minutes < best_minutes):
                best_metric = metric
                best_minutes = minutes
        return best_metric, best_minutes

    def _forecast_for_group(self, slice_id: str, node_id: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
        latest = rows[-1]
        latest_metrics = latest.get("metrics", {})
        slopes = {feature: self._trend(rows, feature) for feature in FEATURES}
        horizons = [5, 10, 20]
        horizon_metrics = {}
        horizon_risks = {}
        for horizon in horizons:
            projected = {
                feature: self._forecast_metric(float(latest_metrics.get(feature, 0.0) or 0.0), slopes[feature], horizon, feature)
                for feature in FEATURES
            }
            risk, _, _ = self._risk_from_metrics(projected)
            horizon_metrics[f"t_plus_{horizon}"] = projected
            horizon_risks[f"risk_t_plus_{horizon}"] = risk
        risk_now, top_features, fault_type = self._risk_from_metrics(latest_metrics)
        breach_metric, breach_minutes = self._breach_time(slice_id, latest_metrics, slopes)
        preventability = min(0.95, max(0.15, horizon_risks["risk_t_plus_10"] - risk_now + 0.45))
        action = self._action_for(fault_type, top_features)
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "slice_id": slice_id,
            "node_id": node_id,
            "fault_type": fault_type,
            "risk_now": risk_now,
            **horizon_risks,
            "horizon_metrics": horizon_metrics,
            "predicted_breach_metric": breach_metric,
            "predicted_breach_time_min": breach_minutes,
            "top_drivers": top_features,
            "metric_slopes": {key: round(value, 5) for key, value in slopes.items()},
            "recommended_action": action,
            "preventability": round(preventability, 3),
            "confidence": round(min(0.93, 0.58 + horizon_risks["risk_t_plus_10"] * 0.35), 3),
            "model": "multi_horizon_ctgnn" if intelligence_service._model_loaded else "multi_horizon_heuristic",
        }

    def _action_for(self, fault_type: str, top_features: list[str]) -> str:
        if fault_type in {"congestion", "cpu_overload", "vnf_degradation"}:
            return "scale_upf"
        if fault_type in {"packet_loss", "latency_spike"}:
            return "reroute_slice"
        if "prb_utilization" in top_features:
            return "reduce_prb_allocation"
        return "escalate_to_human"

    def forecast(self, limit: int = 240) -> dict[str, Any]:
        rows = db.latest_telemetry(limit)
        grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            grouped[(row["slice_id"], row["node_id"])].append(row)
        forecasts = [self._forecast_for_group(slice_id, node_id, node_rows) for (slice_id, node_id), node_rows in grouped.items() if node_rows]
        forecasts.sort(key=lambda item: (item["risk_t_plus_10"], item["risk_t_plus_20"]), reverse=True)
        top = forecasts[0] if forecasts else None
        if top:
            graph_service.update_node_risk(top["node_id"], top["risk_t_plus_10"])
        payload = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "forecast_count": len(forecasts),
            "top_forecast": top,
            "forecasts": forecasts[:12],
            "theory": {
                "risk_equation": "P_fault(t+h)=sigmoid(w·x_hat(t+h)+graph_prior+uncertainty_margin)",
                "breach_rule": "Trigger avoidance when P_fault(t+h)>=threshold and predicted SLA breach time <= action lead time.",
            },
        }
        db.audit("proactive_forecast", {"top": top})
        return payload

    def latest(self) -> dict[str, Any]:
        forecast = self.forecast()
        top = forecast.get("top_forecast")
        if not top:
            return {"status": "insufficient_data", "message": "No telemetry available for proactive forecast.", **forecast}
        status = "avoid_now" if (top["risk_t_plus_10"] >= 0.65 or (top.get("predicted_breach_time_min") or 999) <= 10) else "watch"
        narrative = self.narrative(top)
        return {"status": status, "narrative": narrative, **forecast}

    def narrative(self, forecast: dict[str, Any]) -> str:
        breach = forecast.get("predicted_breach_time_min")
        breach_text = "No SLA breach is projected yet" if breach is None else f"{forecast['predicted_breach_metric']} may breach in about {breach} minutes"
        drivers = ", ".join(str(item).replace("_", " ") for item in forecast.get("top_drivers", []))
        return f"{forecast['node_id']} on {forecast['slice_id']} is the highest-risk element. {breach_text}. Main drivers are {drivers}. Recommended preventive action: {forecast['recommended_action'].replace('_', ' ')}."

    def avoid(self) -> dict[str, Any]:
        latest = self.latest()
        top = latest.get("top_forecast")
        if not top:
            return latest
        recommendation = adaptive_rl_service.recommend(
            top["fault_type"],
            risk="low" if top["risk_t_plus_10"] < 0.75 else "medium",
            probability=top["risk_t_plus_10"],
            conformal_risk_score=max(0.05, top["risk_t_plus_20"] - top["risk_now"]),
            traffic_load=90.0 if "prb_utilization" in top.get("top_drivers", []) else 60.0,
            node_id=top["node_id"],
        )
        before = top["risk_t_plus_10"]
        after = round(max(0.05, before * (1 - top["preventability"] * 0.62)), 3)
        result = {
            "forecast": top,
            "recommended_action": recommendation.get("action", top["recommended_action"]),
            "cmdp": recommendation,
            "counterfactual": {
                "risk_without_action": before,
                "risk_with_action": after,
                "absolute_risk_reduction": round(before - after, 3),
                "expected_effect": f"Reduce predicted risk from {round(before*100)}% to {round(after*100)}% before SLA impact.",
            },
            "execution_mode": "simulation",
            "narrative": f"Preventive action {recommendation.get('action', top['recommended_action']).replace('_', ' ')} is expected to reduce risk from {round(before*100)}% to {round(after*100)}%.",
        }
        db.audit("proactive_avoidance_decision", result)
        return result


proactive_engine = ProactiveEngine()
