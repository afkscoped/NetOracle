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
        rl_recommendation = adaptive_rl_service.recommend(fault_type, risk, confidence)
        if rl_recommendation["action"] != "escalate_to_human":
            diagnosis = {**diagnosis, "recommended_action": rl_recommendation["action"]}
        should_escalate = confidence < settings.confidence_threshold or risk != "low"
        if should_escalate:
            result = self._escalate(diagnosis)
        else:
            result = self._simulate_action(diagnosis)
        result["rl_recommendation"] = rl_recommendation
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

    def _escalate(self, diagnosis: dict[str, Any]) -> dict[str, Any]:
        settings = get_settings()
        payload = {
            "text": f"NetOracle escalation for {diagnosis.get('alert_id')}: {diagnosis.get('root_cause')} confidence={diagnosis.get('confidence')} risk={diagnosis.get('risk')}"
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
            "safety_mechanism": "confidence threshold and risk classification gate",
        }


remediation_service = RemediationService()
