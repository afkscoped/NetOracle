"""
Member 3 test suite:
- GraphRAG neighbourhood retrieval
- MoE LLM routing
- CMDP safety filter
- Remediation escalation logic
"""
import pytest
from unittest.mock import patch, MagicMock

# ── GraphRAG Tests ────────────────────────────────────────────────────────

from app.services.graph import graph_service

def test_neighbourhood_returns_dict():
    alert = {"alert_id": "test_1", "slice_id": "slice_1", "node_id": "upf_1"}
    result = graph_service.localise(alert)
    assert isinstance(result, dict)
    assert "affected_path" in result
    assert "neighbouring_at_risk" in result

def test_neighbourhood_unknown_node():
    alert = {"alert_id": "test_2", "slice_id": "nonexistent_slice", "node_id": "nonexistent_node"}
    result = graph_service.localise(alert)
    assert isinstance(result, dict)


# ── MoE Routing Tests ─────────────────────────────────────────────────────

from app.services.rag_llm import MoERouter

def test_moe_routes_prb_to_radio():
    router = MoERouter()
    decision = router.route("prb_congestion", "high interference on radio")
    assert decision.expert_key == "radio"

def test_moe_routes_upf_to_core():
    router = MoERouter()
    decision = router.route("upf_overload", "core network is overloaded")
    assert decision.expert_key == "core"

def test_moe_routes_latency_to_transport():
    router = MoERouter()
    decision = router.route("latency_spike", "backhaul latency high")
    assert decision.expert_key == "transport"

def test_moe_routes_unknown_to_default():
    router = MoERouter()
    decision = router.route("completely_unknown_fault", "unknown error")
    assert decision.expert_key == "default"

def test_moe_routes_none_gracefully():
    router = MoERouter()
    decision = router.route("", "")
    assert decision.expert_key == "default" or decision.expert_key in ["radio", "core", "transport"]


# ── CMDP Safety Tests ─────────────────────────────────────────────────────

from app.services.adaptive_rl import CMDPSafetyFilter

def test_cmdp_approves_low_risk():
    f = CMDPSafetyFilter(threshold=0.35)
    result = f.evaluate("restart_vnf", risk_score=0.10, confidence=0.90)
    assert result["approved"] is True
    assert result["escalate"] is False if "escalate" in result else True

def test_cmdp_blocks_high_risk():
    f = CMDPSafetyFilter(threshold=0.35)
    result = f.evaluate("reroute_slice", risk_score=0.80, confidence=0.60)
    assert result["approved"] is False

def test_cmdp_blocks_at_exact_threshold():
    f = CMDPSafetyFilter(threshold=0.35)
    result = f.evaluate("scale_upf", risk_score=0.35, confidence=0.70)
    # At threshold exactly — should be approved (<=)
    assert result["approved"] is True

def test_cmdp_blocks_above_threshold():
    f = CMDPSafetyFilter(threshold=0.35)
    result = f.evaluate("scale_upf", risk_score=0.36, confidence=0.70)
    assert result["approved"] is False


# ── Remediation Tests ─────────────────────────────────────────────────────

from app.services.remediation import remediation_service

def test_remediation_returns_status():
    diagnosis = {
        "alert_id": "test_3",
        "recommended_action": "restart_vnf", 
        "evidence": {
            "risk_score": 0.10, 
            "confidence": 0.85,
            "alert": {"alert_id": "test_3", "slice_id": "slice_1", "node_id": "upf_1"}
        }
    }
    result = remediation_service.decide_and_execute(diagnosis)
    assert "status" in result
    assert result["action"] is not None
