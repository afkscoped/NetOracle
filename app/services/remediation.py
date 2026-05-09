from datetime import datetime, timezone
from typing import Any

import requests

from app.database import db
from app.services.adaptive_rl import adaptive_rl_service
from app.settings import get_settings


class RemediationService:
    def decide_and_execute(self, diagnosis: dict[str, Any]) -> dict[str, Any]:
        settings = get_settings()
        confidence = float(diagnosis.get("confidence", 0))
        risk = diagnosis.get("risk", "high")
        fault_type = self._fault_type(diagnosis)
        
        # Extract CMDP variables from Member 2's intelligence output
        alert = diagnosis.get("evidence", {}).get("alert", {})
        
        # Conformal risk score: width of the uncertainty interval, or 1 - confidence as fallback
        if "prob_upper" in alert and "prob_lower" in alert:
            conformal_risk_score = alert["prob_upper"] - alert["prob_lower"]
        else:
            conformal_risk_score = 1.0 - confidence
            
        top_features = alert.get("top_features", [])
        traffic_load = 90.0 if "prb_utilization" in top_features or "cpu" in top_features else 50.0

        rl_recommendation = adaptive_rl_service.recommend(
            fault_type=fault_type, 
            risk=risk, 
            probability=alert.get("fault_probability", 0.7),
            conformal_risk_score=conformal_risk_score,
            traffic_load=traffic_load
        )
        
        if rl_recommendation["action"] != "escalate_to_human":
            diagnosis = {**diagnosis, "recommended_action": rl_recommendation["action"]}
            
        cmdp_approved = rl_recommendation.get("cmdp_approved", True)
        should_escalate = not cmdp_approved or confidence < settings.confidence_threshold or risk != "low"
        
        if should_escalate:
            reason = rl_recommendation.get("cmdp_reason", "Confidence or risk thresholds not met.")
            result = self._escalate(diagnosis, reason=reason)
        else:
            result = self._simulate_action(diagnosis)
            
        result["rl_recommendation"] = rl_recommendation
        # Surface CMDP safety metrics in remediation response
        result["safety_cost"] = rl_recommendation.get("safety_cost", 0.0)
        result["cmdp_status"] = {
            "lambda_multiplier": rl_recommendation.get("lambda_multiplier", 0.0),
            "cumulative_session_cost": rl_recommendation.get("cumulative_session_cost", 0.0),
            "cost_limit": rl_recommendation.get("cost_limit", 5.0),
            "safety_budget_remaining": rl_recommendation.get("safety_budget_remaining", 5.0),
        }
        db.audit("remediation_decision", result)
        return result

    def _fault_type(self, diagnosis: dict[str, Any]) -> str:
        votes = diagnosis.get("evidence", {}).get("llm_votes", [])
        if votes and isinstance(votes[0], dict):
            return str(votes[0].get("fault_type", "congestion"))
        action = str(diagnosis.get("recommended_action", "scale_vnf"))
        if action == "reallocate_channel":
            return "packet_loss"
        if action == "push_flow_rule":
            return "latency_spike"
        return "congestion"

    def _simulate_action(self, diagnosis: dict[str, Any]) -> dict[str, Any]:
        action = diagnosis.get("recommended_action", "escalate")
        before_after = {
            "scale_vnf": ({"replicas": 1}, {"replicas": 2}),
            "push_flow_rule": ({"route": "primary"}, {"route": "peer_router_failover"}),
            "reallocate_channel": ({"channel": "n78-a"}, {"channel": "n78-b"}),
        }
        before, after = before_after.get(action, ({"state": "unknown"}, {"state": "manual_review"}))
        return {
            "alert_id": diagnosis["alert_id"],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "action": action,
            "mode": get_settings().remediation_mode,
            "status": "success",
            "before_state": before,
            "after_state": after,
            "operator_required": False,
            "safety_mechanism": "risk-gated simulated actuation with full audit trail",
        }

    def _escalate(self, diagnosis: dict[str, Any], reason: str = "Confidence threshold and risk classification gate") -> dict[str, Any]:
        settings = get_settings()
        payload = {
            "text": f"NetOracle escalation for {diagnosis.get('alert_id')}: {diagnosis.get('root_cause')} confidence={diagnosis.get('confidence')} risk={diagnosis.get('risk')}\nReason: {reason}"
        }
        delivered = False
        if settings.slack_webhook_url:
            try:
                requests.post(settings.slack_webhook_url, json=payload, timeout=8).raise_for_status()
                delivered = True
            except Exception:
                delivered = False
        return {
            "alert_id": diagnosis["alert_id"],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "action": "escalate_to_human",
            "mode": "human_in_loop",
            "status": "queued" if not delivered else "notified",
            "before_state": {"automation": "blocked"},
            "after_state": {"operator_ticket": "created", "slack_delivered": delivered},
            "operator_required": True,
            "safety_mechanism": reason,
        }


remediation_service = RemediationService()
