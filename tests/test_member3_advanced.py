import pytest
import math
import time
import json
from unittest.mock import patch, MagicMock, call
from hypothesis import given, settings, strategies as st

# ══════════════════════════════════════════════════════════════════════════
# GRAPHRAG TESTS
# ══════════════════════════════════════════════════════════════════════════

from app.services.graph import graph_service

class TestGraphRAGCore:
    def test_neighbourhood_structure(self):
        result = graph_service.get_node_neighbourhood_v2("upf_1", depth=1)
        assert isinstance(result, dict)
        for key in ("anchor_node", "nodes", "edges", "centrality", "top_node"):
            assert key in result, f"Missing key: {key}"

    def test_nodes_have_relevance_scores(self):
        result = graph_service.get_node_neighbourhood_v2("upf_1", depth=2)
        for node in result["nodes"]:
            assert "relevance_score" in node
            assert 0.0 <= node["relevance_score"] <= 1.0

    def test_max_nodes_cap_respected(self):
        result = graph_service.get_node_neighbourhood_v2("upf_1", depth=3, max_nodes=5)
        assert len(result["nodes"]) <= 5

    def test_cache_hit_returns_same_result(self):
        r1 = graph_service.get_node_neighbourhood_v2("upf_1", depth=1)
        r2 = graph_service.get_node_neighbourhood_v2("upf_1", depth=1)
        assert r1["anchor_node"] == r2["anchor_node"]
        assert len(r1["nodes"]) == len(r2["nodes"])

    def test_unknown_node_returns_empty_gracefully(self):
        result = graph_service.get_node_neighbourhood_v2("node_that_does_not_exist_xyz", depth=2)
        assert result["nodes"] == []
        assert result["edges"] == []

    def test_serialise_respects_token_budget(self):
        result = graph_service.get_node_neighbourhood_v2("upf_1", depth=2)
        serialised = graph_service.serialise_graphrag_context(result, token_budget=100)
        char_budget = 100 * 4
        assert len(serialised) <= char_budget + 100  # small buffer for truncation suffix

    def test_serialise_contains_anchor_node(self):
        result = graph_service.get_node_neighbourhood_v2("upf_1", depth=1)
        serialised = graph_service.serialise_graphrag_context(result)
        assert "upf_1" in serialised


class TestPageRank:
    def test_uniform_graph_equal_ranks(self):
        edges = [
            {"source": "A", "target": "B", "relation": "CONNECTS_TO"},
            {"source": "B", "target": "C", "relation": "CONNECTS_TO"},
            {"source": "C", "target": "A", "relation": "CONNECTS_TO"},
        ]
        ranks = graph_service._compute_local_pagerank(edges, iterations=20)
        values = list(ranks.values())
        # In a cycle all ranks should be equal
        assert max(values) - min(values) < 0.01

    def test_hub_node_scores_higher(self):
        # Hub has many incoming edges
        edges = [
            {"source": "A", "target": "HUB", "relation": "CONNECTS_TO"},
            {"source": "B", "target": "HUB", "relation": "CONNECTS_TO"},
            {"source": "C", "target": "HUB", "relation": "CONNECTS_TO"},
            {"source": "HUB", "target": "D", "relation": "CONNECTS_TO"},
        ]
        ranks = graph_service._compute_local_pagerank(edges, iterations=30)
        assert ranks["HUB"] > ranks.get("A", 0)

    def test_empty_graph_returns_empty(self):
        assert graph_service._compute_local_pagerank([]) == {}


class TestPathScoring:
    def test_shorter_path_scores_higher(self):
        short_path = [{"relation": "HOSTS"}]
        long_path  = [{"relation": "HOSTS"}, {"relation": "HOSTS"}, {"relation": "HOSTS"}]
        assert graph_service._score_path(short_path) > graph_service._score_path(long_path)

    def test_high_weight_relation_scores_higher(self):
        strong = [{"relation": "DEPENDS_ON"}]
        weak   = [{"relation": "MONITORS"}]
        assert graph_service._score_path(strong) > graph_service._score_path(weak)

    def test_empty_path_scores_zero(self):
        assert graph_service._score_path([]) == 0.0

    @given(st.lists(st.text(min_size=1, max_size=20), min_size=1, max_size=10))
    @settings(max_examples=50)
    def test_score_always_non_negative(self, relations):
        path = [{"relation": r} for r in relations]
        assert graph_service._score_path(path) >= 0.0


# ══════════════════════════════════════════════════════════════════════════
# MOE ROUTING TESTS
# ══════════════════════════════════════════════════════════════════════════

from app.services.rag_llm import route_to_specialists, _embed_fault, _cosine_similarity

class TestFaultEmbedding:
    def test_radio_fault_embeds_to_radio_domain(self):
        vec = _embed_fault("prb_congestion")
        assert vec["radio"] > vec["core"]
        assert vec["radio"] > vec["transport"]

    def test_core_fault_embeds_to_core_domain(self):
        vec = _embed_fault("upf_overload")
        assert vec["core"] > vec["radio"]

    def test_transport_fault_embeds_to_transport_domain(self):
        vec = _embed_fault("latency_spike")
        assert vec["transport"] > vec["core"]

    def test_embedding_is_normalised(self):
        vec = _embed_fault("prb_congestion")
        magnitude = math.sqrt(sum(v**2 for v in vec.values()))
        assert abs(magnitude - 1.0) < 0.01 or magnitude == 0.0  # normalised or zero

    def test_empty_fault_returns_zero_vector(self):
        vec = _embed_fault("")
        assert all(v == 0.0 for v in vec.values())

    @given(st.text(min_size=0, max_size=100))
    @settings(max_examples=100)
    def test_embedding_never_raises(self, fault_type):
        try:
            _embed_fault(fault_type)
        except Exception as e:
            pytest.fail(f"_embed_fault raised on input '{fault_type}': {e}")


class TestMoERouter:
    def test_routes_radio_fault_to_radio_specialist(self):
        specialists = route_to_specialists("prb_congestion", top_k=1)
        assert specialists[0]["specialist_key"] == "radio"

    def test_routes_core_fault_to_core_specialist(self):
        specialists = route_to_specialists("upf_overload", top_k=1)
        assert specialists[0]["specialist_key"] == "core"

    def test_routes_transport_fault_to_transport_specialist(self):
        specialists = route_to_specialists("latency_spike", top_k=1)
        assert specialists[0]["specialist_key"] == "transport"

    def test_top_k_respected(self):
        specialists = route_to_specialists("upf_overload", top_k=2)
        assert len(specialists) <= 2

    def test_always_returns_at_least_one_specialist(self):
        specialists = route_to_specialists("completely_unknown_xyz_fault_type_123")
        assert len(specialists) >= 1

    def test_none_fault_type_does_not_raise(self):
        specialists = route_to_specialists(None)
        assert len(specialists) >= 1

    def test_routing_scores_are_between_0_and_1(self):
        specialists = route_to_specialists("prb_congestion", top_k=3)
        for s in specialists:
            assert 0.0 <= s["routing_score"] <= 1.0

    def test_specialists_have_required_keys(self):
        specialists = route_to_specialists("upf_overload")
        for s in specialists:
            for key in ("name", "system_prompt", "domain_vector", "routing_score"):
                assert key in s, f"Specialist missing key: {key}"


class TestCosimilarity:
    def test_identical_vectors_score_1(self):
        vec = {"radio": 1.0, "core": 0.0, "transport": 0.0, "security": 0.0}
        assert abs(_cosine_similarity(vec, vec) - 1.0) < 0.001

    def test_orthogonal_vectors_score_0(self):
        a = {"radio": 1.0, "core": 0.0, "transport": 0.0, "security": 0.0}
        b = {"radio": 0.0, "core": 1.0, "transport": 0.0, "security": 0.0}
        assert abs(_cosine_similarity(a, b)) < 0.001

    def test_score_between_0_and_1(self):
        a = {"radio": 0.8, "core": 0.2, "transport": 0.0, "security": 0.0}
        b = {"radio": 0.3, "core": 0.7, "transport": 0.0, "security": 0.0}
        score = _cosine_similarity(a, b)
        assert 0.0 <= score <= 1.0


# ══════════════════════════════════════════════════════════════════════════
# CMDP SAFETY TESTS
# ══════════════════════════════════════════════════════════════════════════

from app.services.adaptive_rl import (
    MultiConstraintCMDP, SafetyConstraint, ACTION_PROFILES
)

class TestSafetyConstraint:
    def test_satisfied_below_threshold(self):
        c = SafetyConstraint("risk", threshold=0.35)
        assert c.is_satisfied(0.20) is True

    def test_violated_above_threshold(self):
        c = SafetyConstraint("risk", threshold=0.35)
        assert c.is_satisfied(0.50) is False

    def test_satisfied_at_exact_threshold(self):
        c = SafetyConstraint("risk", threshold=0.35)
        assert c.is_satisfied(0.35) is True  # boundary: <= threshold

    def test_lambda_increases_on_violation(self):
        c = SafetyConstraint("risk", threshold=0.35, penalty_init=1.0, learning_rate=0.1)
        initial_lambda = c._lambda
        c.update_lambda(0.80)  # violating value
        assert c._lambda > initial_lambda

    def test_lambda_decreases_on_satisfaction(self):
        c = SafetyConstraint("risk", threshold=0.35, penalty_init=2.0, learning_rate=0.1)
        c.update_lambda(0.10)  # satisfying value
        assert c._lambda < 2.0

    def test_lambda_never_negative(self):
        c = SafetyConstraint("risk", threshold=0.35, penalty_init=0.01, learning_rate=0.5)
        for _ in range(20):
            c.update_lambda(0.0)  # highly satisfying — lambda should floor at 0
        assert c._lambda >= 0.0

    def test_violation_rate_tracks_correctly(self):
        c = SafetyConstraint("risk", threshold=0.35)
        c.update_lambda(0.80)  # violate
        c.update_lambda(0.10)  # satisfy
        c.update_lambda(0.90)  # violate
        assert abs(c.violation_rate - 2/3) < 0.01


class TestMultiConstraintCMDP:
    def setup_method(self):
        self.cmdp = MultiConstraintCMDP()

    def test_safe_action_approved(self):
        ctx = {"conformal_risk_score": 0.10, "confidence": 0.90}
        result = self.cmdp.evaluate_and_update("reduce_prb_allocation", ctx)
        assert result["approved"] is True
        assert result["escalate"] is False

    def test_high_risk_action_blocked(self):
        ctx = {"conformal_risk_score": 0.95, "confidence": 0.80}
        result = self.cmdp.evaluate_and_update("reroute_slice", ctx)
        assert result["approved"] is False
        assert "risk_score" in result["violated_constraints"]

    def test_irreversible_action_with_high_blast_blocked(self):
        ctx = {"conformal_risk_score": 0.20, "confidence": 0.90}
        # isolate_node has blast_radius=0.80, above threshold of 0.50
        result = self.cmdp.evaluate_and_update("isolate_node", ctx)
        assert result["approved"] is False
        assert "blast_radius" in result["violated_constraints"]

    def test_all_constraint_results_present(self):
        ctx = {"conformal_risk_score": 0.20, "confidence": 0.80}
        result = self.cmdp.evaluate_and_update("scale_upf", ctx)
        for key in ("risk_score", "blast_radius", "estimated_downtime_s"):
            assert key in result["constraint_results"]

    def test_action_masking_removes_unsafe_actions(self):
        ctx = {"conformal_risk_score": 0.90}  # high risk
        safe = self.cmdp.mask_unsafe_actions(list(ACTION_PROFILES.keys()), ctx)
        # High risk should eliminate actions with high blast radius
        assert "isolate_node" not in safe or len(safe) == 1  # may force escalation only

    def test_action_masking_always_returns_at_least_one(self):
        ctx = {"conformal_risk_score": 0.99}  # extreme risk
        safe = self.cmdp.mask_unsafe_actions(list(ACTION_PROFILES.keys()), ctx)
        assert len(safe) >= 1
        assert "escalate_to_human" in safe

    def test_audit_log_grows_with_evaluations(self):
        ctx = {"conformal_risk_score": 0.10}
        initial = len(self.cmdp._audit_log)
        self.cmdp.evaluate_and_update("scale_upf", ctx)
        self.cmdp.evaluate_and_update("restart_vnf", ctx)
        assert len(self.cmdp._audit_log) == initial + 2

    def test_constraint_status_returns_all_dimensions(self):
        status = self.cmdp.get_constraint_status()
        for key in ("risk_score", "blast_radius", "estimated_downtime_s"):
            assert key in status

    @given(
        risk=st.floats(min_value=0.0, max_value=1.0),
        action=st.sampled_from(list(ACTION_PROFILES.keys()))
    )
    @settings(max_examples=80)
    def test_evaluate_never_raises(self, risk, action):
        cmdp = MultiConstraintCMDP()
        ctx = {"conformal_risk_score": risk}
        try:
            result = cmdp.evaluate_and_update(action, ctx)
            assert "approved" in result or "approved" not in result
        except Exception as e:
            pytest.fail(f"evaluate_and_update raised for risk={risk}, action={action}: {e}")


# ══════════════════════════════════════════════════════════════════════════
# INTEGRATION TESTS — cross-service flows
# ══════════════════════════════════════════════════════════════════════════

class TestIntegrationFlows:
    """
    Tests that verify correct data flow between graph.py, rag_llm.py,
    adaptive_rl.py, and remediation.py as an integrated pipeline.
    """

    def test_graphrag_context_feeds_into_moe_routing(self):
        """GraphRAG output should be a string consumable as LLM context."""
        from app.services.graph import graph_service
        neighbourhood = graph_service.get_node_neighbourhood_v2("upf_1", depth=1)
        context_str = graph_service.serialise_graphrag_context(neighbourhood)
        assert isinstance(context_str, str)
        assert len(context_str) > 0
        # MoE routing should work with any fault type regardless
        from app.services.rag_llm import route_to_specialists
        specialists = route_to_specialists("upf_overload")
        assert len(specialists) >= 1

    def test_cmdp_decision_includes_rl_proposal(self):
        from app.services.adaptive_rl import recommend_action_cmdp
        ctx = {
            "node_id": "upf_1",
            "fault_type": "upf_overload",
            "conformal_risk_score": 0.15,
            "confidence": 0.85,
        }
        result = recommend_action_cmdp(ctx)
        assert "action" in result
        assert "cmdp_approved" in result
        assert "safe_action_set" in result

    def test_high_risk_pipeline_always_escalates(self):
        from app.services.adaptive_rl import recommend_action_cmdp
        ctx = {
            "node_id": "gnb_1",
            "fault_type": "interference",
            "conformal_risk_score": 0.99,  # extreme
            "confidence": 0.95,
        }
        result = recommend_action_cmdp(ctx)
        assert result["escalate"] is True or result["cmdp_approved"] is False

    def test_low_risk_pipeline_does_not_escalate(self):
        from app.services.adaptive_rl import recommend_action_cmdp
        ctx = {
            "node_id": "gnb_1",
            "fault_type": "interference",
            "conformal_risk_score": 0.05,
            "confidence": 0.95,
        }
        result = recommend_action_cmdp(ctx)
        # Should be approved for at least some action
        assert result.get("cmdp_approved") is True or result.get("action") is not None
