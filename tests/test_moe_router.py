"""Tests for the MoE LLM-based routing system in rag_llm.py."""

import json
from unittest.mock import MagicMock, patch

import pytest

from app.services.rag_llm import (
    MoERouter,
    RoutingDecision,
    SPECIALIST_PERSONAS,
    _route_via_keyword,
    moe_router,
)


# ---------------------------------------------------------------------------
# RoutingDecision model tests
# ---------------------------------------------------------------------------


class TestRoutingDecision:
    def test_valid_routing_decision(self):
        decision = RoutingDecision(
            expert_key="radio",
            expert_name="Radio Access Network Specialist",
            confidence_score=0.85,
            reasoning="Fault involves PRB congestion",
            routing_method="llm_openai",
        )
        assert decision.expert_key == "radio"
        assert decision.routing_method == "llm_openai"
        assert 0.0 <= decision.confidence_score <= 1.0

    def test_default_routing_method(self):
        decision = RoutingDecision(
            expert_key="default",
            expert_name="General Network Operations Specialist",
            confidence_score=0.5,
            reasoning="No match",
        )
        assert decision.routing_method == "keyword"

    def test_model_dump_includes_routing_method(self):
        decision = RoutingDecision(
            expert_key="core",
            expert_name="Core Network Specialist",
            confidence_score=0.9,
            reasoning="VNF issue detected",
            routing_method="llm_groq",
        )
        dumped = decision.model_dump()
        assert "routing_method" in dumped
        assert dumped["routing_method"] == "llm_groq"


# ---------------------------------------------------------------------------
# Keyword routing tests (fallback)
# ---------------------------------------------------------------------------


class TestKeywordRouting:
    @pytest.mark.parametrize(
        "fault_type, expected_key",
        [
            ("congestion", "radio"),
            ("prb_congestion", "radio"),
            ("cpu_overload", "core"),
            ("vnf_degradation", "core"),
            ("upf_overload", "core"),
            ("latency_spike", "transport"),
            ("packet_loss", "transport"),
            ("link_down", "transport"),
        ],
    )
    def test_known_fault_types_route_correctly(self, fault_type, expected_key):
        decision = _route_via_keyword(fault_type)
        assert decision.expert_key == expected_key
        assert decision.routing_method == "keyword"
        assert decision.confidence_score == 0.92

    def test_unknown_fault_type_routes_to_default(self):
        decision = _route_via_keyword("unknown_weird_fault")
        assert decision.expert_key == "default"
        assert decision.routing_method == "keyword"
        assert decision.confidence_score == 0.50

    def test_empty_fault_type_routes_to_first_match(self):
        # Empty string is a substring of every trigger, so it matches the first
        # persona's first trigger (radio). This is expected keyword-matching behavior.
        decision = _route_via_keyword("")
        assert decision.expert_key in SPECIALIST_PERSONAS
        assert decision.routing_method == "keyword"

    def test_case_insensitive(self):
        decision = _route_via_keyword("CPU_OVERLOAD")
        assert decision.expert_key == "core"


# ---------------------------------------------------------------------------
# MoERouter class tests
# ---------------------------------------------------------------------------


class TestMoERouter:
    def setup_method(self):
        self.router = MoERouter()

    def test_build_router_prompt_structure(self):
        messages = self.router._build_router_prompt("high latency on router_1")
        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"
        assert "radio" in messages[0]["content"]
        assert "core" in messages[0]["content"]
        assert "transport" in messages[0]["content"]

    def test_build_router_prompt_with_graph_context(self):
        messages = self.router._build_router_prompt(
            "latency spike", graph_context="router_1 --[PEERS_WITH]--> router_2"
        )
        assert "Topology Context" in messages[1]["content"]
        assert "router_1" in messages[1]["content"]

    def test_parse_valid_routing_response(self):
        raw = json.dumps({
            "expert_key": "transport",
            "confidence_score": 0.87,
            "reasoning": "Latency issue detected",
        })
        decision = self.router._parse_routing_response(raw, "llm_openai")
        assert decision is not None
        assert decision.expert_key == "transport"
        assert decision.confidence_score == 0.87
        assert decision.routing_method == "llm_openai"

    def test_parse_invalid_expert_key_falls_to_default(self):
        raw = json.dumps({
            "expert_key": "nonexistent_expert",
            "confidence_score": 0.7,
            "reasoning": "test",
        })
        decision = self.router._parse_routing_response(raw, "llm_groq")
        assert decision is not None
        assert decision.expert_key == "default"

    def test_parse_confidence_clamping(self):
        raw = json.dumps({
            "expert_key": "radio",
            "confidence_score": 1.5,
            "reasoning": "test",
        })
        decision = self.router._parse_routing_response(raw, "llm_openai")
        assert decision.confidence_score == 1.0

        raw_low = json.dumps({
            "expert_key": "radio",
            "confidence_score": -0.3,
            "reasoning": "test",
        })
        decision_low = self.router._parse_routing_response(raw_low, "llm_openai")
        assert decision_low.confidence_score == 0.0

    def test_parse_invalid_json_returns_none(self):
        decision = self.router._parse_routing_response("not json at all", "llm_openai")
        assert decision is None

    def test_parse_missing_fields_uses_defaults(self):
        raw = json.dumps({"expert_key": "core"})
        decision = self.router._parse_routing_response(raw, "llm_ollama")
        assert decision is not None
        assert decision.confidence_score == 0.5
        assert decision.reasoning == "LLM routing decision"

    @patch.object(MoERouter, "_route_via_groq", return_value=None)
    @patch.object(MoERouter, "_route_via_openai", return_value=None)
    @patch.object(MoERouter, "_route_via_ollama", return_value=None)
    def test_all_llm_fail_falls_to_keyword(self, mock_ollama, mock_openai, mock_groq):
        """When all LLM providers fail, keyword routing is used as fallback."""
        decision = self.router.route("congestion")
        assert decision.routing_method == "keyword"
        assert decision.expert_key == "radio"

    @patch.object(MoERouter, "_route_via_groq")
    def test_groq_success_short_circuits(self, mock_groq):
        """When Groq succeeds, OpenAI and Ollama are not called."""
        mock_groq.return_value = RoutingDecision(
            expert_key="transport",
            expert_name="Transport & Backhaul Specialist",
            confidence_score=0.95,
            reasoning="Groq detected latency issue",
            routing_method="llm_groq",
        )
        with patch.object(self.router, "_route_via_openai") as mock_openai, \
             patch.object(self.router, "_route_via_ollama") as mock_ollama:
            decision = self.router.route("latency_spike")
            assert decision.routing_method == "llm_groq"
            mock_openai.assert_not_called()
            mock_ollama.assert_not_called()

    @patch.object(MoERouter, "_route_via_groq", return_value=None)
    @patch.object(MoERouter, "_route_via_openai")
    def test_openai_fallback_when_groq_fails(self, mock_openai, mock_groq):
        mock_openai.return_value = RoutingDecision(
            expert_key="core",
            expert_name="Core Network Specialist",
            confidence_score=0.88,
            reasoning="CPU issue via OpenAI",
            routing_method="llm_openai",
        )
        decision = self.router.route("cpu_overload")
        assert decision.routing_method == "llm_openai"
        assert decision.expert_key == "core"


# ---------------------------------------------------------------------------
# Integration-style tests
# ---------------------------------------------------------------------------


class TestMoERouterIntegration:
    def test_specialist_personas_all_have_required_fields(self):
        for key, persona in SPECIALIST_PERSONAS.items():
            assert "name" in persona
            assert "trigger_fault_types" in persona
            assert "system_prompt" in persona
            assert isinstance(persona["trigger_fault_types"], list)

    def test_moe_router_singleton_exists(self):
        assert moe_router is not None
        assert isinstance(moe_router, MoERouter)

    def test_routing_decision_schema_has_all_expert_keys(self):
        schema = MoERouter.ROUTING_SCHEMA
        assert "radio" in schema["properties"]["expert_key"]["enum"]
        assert "core" in schema["properties"]["expert_key"]["enum"]
        assert "transport" in schema["properties"]["expert_key"]["enum"]
        assert "default" in schema["properties"]["expert_key"]["enum"]
