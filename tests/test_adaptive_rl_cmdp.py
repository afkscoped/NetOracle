"""Tests for the Safe RL / CMDP system in adaptive_rl.py."""

import json
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest

from app.services.adaptive_rl import (
    ACTIONS,
    ACTION_COSTS,
    FAULT_TYPES,
    RISK_LEVELS,
    PROBABILITY_BANDS,
    CMDPAgent,
    SafeRemediationEnv,
    AdaptiveRLService,
    _probability_band,
)


# ---------------------------------------------------------------------------
# SafeRemediationEnv tests
# ---------------------------------------------------------------------------


class TestSafeRemediationEnv:
    def setup_method(self):
        self.env = SafeRemediationEnv(cost_limit=5.0)

    def test_reset_returns_valid_state(self):
        obs, info = self.env.reset(seed=42)
        assert 0 <= obs < self.env.n_states
        assert "fault_type" in info
        assert "risk" in info
        assert "probability_band" in info
        assert info["fault_type"] in FAULT_TYPES
        assert info["risk"] in RISK_LEVELS

    def test_reset_clears_cost(self):
        self.env.current_cost = 10.0
        obs, info = self.env.reset(seed=0)
        assert self.env.current_cost == 0.0

    def test_step_returns_correct_tuple_shape(self):
        self.env.reset(seed=42)
        obs, reward, terminated, truncated, info = self.env.step(0)
        assert isinstance(obs, int)
        assert isinstance(reward, float)
        assert isinstance(terminated, bool)
        assert isinstance(truncated, bool)
        assert isinstance(info, dict)

    def test_step_info_contains_cmdp_fields(self):
        self.env.reset(seed=42)
        _, _, _, _, info = self.env.step(0)
        assert "cost" in info
        assert "cumulative_cost" in info
        assert "safety_violation" in info
        assert "action_name" in info
        assert info["action_name"] in ACTIONS

    def test_cumulative_cost_increases(self):
        self.env.reset(seed=42)
        _, _, _, _, info1 = self.env.step(0)  # scale_vnf
        cost1 = info1["cumulative_cost"]
        _, _, _, _, info2 = self.env.step(2)  # reallocate_channel
        cost2 = info2["cumulative_cost"]
        assert cost2 >= cost1

    def test_safety_violation_detected(self):
        self.env = SafeRemediationEnv(cost_limit=1.0)  # Very low limit
        self.env.reset(seed=42)
        # Take enough expensive actions to exceed the limit
        violated = False
        for _ in range(10):
            _, _, _, _, info = self.env.step(2)  # reallocate_channel is expensive
            if info["safety_violation"]:
                violated = True
                break
        assert violated, "Safety violation should have been triggered"

    def test_escalate_has_zero_cost(self):
        self.env.reset(seed=42)
        # Ensure we're not in peak hours for this test
        with patch("app.services.adaptive_rl._is_peak_hours", return_value=False):
            env = SafeRemediationEnv(cost_limit=5.0)
            env.reset(seed=42)
            _, _, _, _, info = env.step(3)  # escalate_to_human
            assert info["cost"] == 0.0

    def test_truncation_after_max_steps(self):
        self.env._max_steps = 3
        self.env.reset(seed=42)
        for i in range(3):
            _, _, terminated, truncated, _ = self.env.step(3)  # escalate (won't terminate)
        assert truncated, "Should truncate after max steps"

    def test_state_index_roundtrip(self):
        for idx in range(self.env.n_states):
            fault_idx, risk_idx, prob_idx = self.env._index_to_state(idx)
            reconstructed = self.env._state_to_index(fault_idx, risk_idx, prob_idx)
            assert reconstructed == idx

    @patch("app.services.adaptive_rl._is_peak_hours", return_value=True)
    def test_peak_hours_doubles_cost(self, mock_peak):
        env = SafeRemediationEnv(cost_limit=50.0)
        env.reset(seed=42)
        # Force low risk state for predictable cost
        env._risk_idx = 0
        _, _, _, _, info = env.step(0)  # scale_vnf: base 0.5 * 2.0 peak = 1.0
        assert info["cost"] == 1.0

    @patch("app.services.adaptive_rl._is_peak_hours", return_value=False)
    def test_high_risk_increases_cost(self, mock_peak):
        env = SafeRemediationEnv(cost_limit=50.0)
        env.reset(seed=42)
        env._risk_idx = 2  # high risk
        _, _, _, _, info = env.step(0)  # scale_vnf: base 0.5 * 1.5 risk = 0.75
        assert info["cost"] == 0.75


# ---------------------------------------------------------------------------
# CMDPAgent tests
# ---------------------------------------------------------------------------


class TestCMDPAgent:
    def setup_method(self):
        self.agent = CMDPAgent(n_states=45, n_actions=4, cost_limit=5.0)

    def test_initial_q_table_is_zeros(self):
        assert np.all(self.agent.q_table == 0.0)

    def test_select_action_returns_valid_action(self):
        action = self.agent.select_action(0)
        assert 0 <= action < self.agent.n_actions

    def test_epsilon_greedy_exploration(self):
        """With epsilon=1.0, all actions should be explored (statistically)."""
        actions_seen = set()
        for _ in range(200):
            action = self.agent.select_action(0, epsilon=1.0)
            actions_seen.add(action)
        assert len(actions_seen) == 4, "All actions should be explored with epsilon=1.0"

    def test_safe_reward_penalises_cost(self):
        self.agent.lambda_multiplier = 1.0
        safe_r = self.agent.safe_reward(reward=10.0, cost=3.0)
        assert safe_r == 7.0

    def test_safe_reward_with_zero_cost(self):
        safe_r = self.agent.safe_reward(reward=10.0, cost=0.0)
        assert safe_r == 10.0

    def test_train_step_updates_q_value(self):
        old_q = self.agent.q_table[0, 0]
        metrics = self.agent.train_step(
            state=0, action=0, reward=10.0, cost=0.0, next_state=1
        )
        new_q = self.agent.q_table[0, 0]
        assert new_q != old_q
        assert metrics["new_q"] != metrics["old_q"]

    def test_train_step_with_cost_reduces_effective_reward(self):
        self.agent.lambda_multiplier = 2.0
        metrics = self.agent.train_step(
            state=0, action=0, reward=10.0, cost=3.0, next_state=1
        )
        # safe_reward = 10.0 - 2.0 * 3.0 = 4.0
        assert metrics["safe_reward"] == 4.0

    def test_lagrangian_increases_on_violation(self):
        initial_lambda = self.agent.lambda_multiplier
        self.agent.update_lagrangian(cumulative_cost=10.0)  # Well above cost_limit of 5.0
        assert self.agent.lambda_multiplier > initial_lambda

    def test_lagrangian_decreases_within_budget(self):
        self.agent.lambda_multiplier = 1.0
        self.agent.update_lagrangian(cumulative_cost=2.0)  # Below cost_limit of 5.0
        assert self.agent.lambda_multiplier < 1.0

    def test_lagrangian_capped_at_max(self):
        self.agent.lambda_multiplier = self.agent.lambda_max
        self.agent.update_lagrangian(cumulative_cost=100.0)
        assert self.agent.lambda_multiplier <= self.agent.lambda_max

    def test_lagrangian_floor_at_zero(self):
        self.agent.lambda_multiplier = 0.0
        self.agent.update_lagrangian(cumulative_cost=0.0)  # Below limit
        assert self.agent.lambda_multiplier >= 0.0

    def test_serialise_and_restore(self):
        # Train a bit
        self.agent.train_step(0, 0, 10.0, 0.0, 1)
        self.agent.lambda_multiplier = 0.42

        # Serialise
        data = self.agent.to_dict()
        assert "q_table" in data
        assert "lambda_multiplier" in data

        # Restore
        restored = CMDPAgent.from_dict(data)
        assert restored.lambda_multiplier == 0.42
        assert np.allclose(restored.q_table, self.agent.q_table)


# ---------------------------------------------------------------------------
# AdaptiveRLService tests (CMDP-upgraded)
# ---------------------------------------------------------------------------


class TestAdaptiveRLService:
    def setup_method(self):
        self.service = AdaptiveRLService()

    def test_recommend_includes_safety_cost(self):
        result = self.service.recommend("congestion", "low", 0.7)
        assert "safety_cost" in result
        assert "cumulative_session_cost" in result
        assert "cost_limit" in result
        assert "safety_budget_remaining" in result
        assert "lambda_multiplier" in result

    def test_recommend_escalate_on_non_low_risk(self):
        result = self.service.recommend("congestion", "medium", 0.7)
        assert result["action"] == "escalate_to_human"
        assert result["strategy"] == "safety_override"

    def test_recommend_escalate_has_zero_cost(self):
        with patch("app.services.adaptive_rl._is_peak_hours", return_value=False):
            svc = AdaptiveRLService()
            result = svc.recommend("congestion", "medium", 0.7)
            assert result["safety_cost"] == 0.0

    def test_update_with_cost_adjusts_lagrangian(self):
        initial_lambda = self.service.cmdp_agent.lambda_multiplier
        # Send a large cost to trigger Lagrangian update
        self.service.update("congestion:low:medium", "scale_vnf", reward=5.0, cost=10.0)
        # Lambda should have increased since cumulative cost > limit
        assert self.service.cmdp_agent.lambda_multiplier != initial_lambda

    def test_update_without_cost_is_backward_compatible(self):
        result = self.service.update("congestion:low:medium", "scale_vnf", reward=5.0)
        assert "cost" in result
        assert result["cost"] == 0.0
        assert "safe_reward" in result

    def test_policy_includes_cmdp_metadata(self):
        policy = self.service.policy()
        assert "cmdp" in policy
        assert "cost_limit" in policy["cmdp"]
        assert "lambda_multiplier" in policy["cmdp"]
        assert "action_costs" in policy["cmdp"]
        assert "peak_hours_active" in policy["cmdp"]
        assert policy["algorithm"] == "safety-constrained CMDP with Lagrangian penalty for adaptive remediation"

    def test_train_episode_basic(self):
        result = self.service.train_episode(episodes=2, max_steps=5)
        assert "episodes_run" in result
        assert result["episodes_run"] == 2
        assert "avg_reward" in result
        assert "avg_cost" in result
        assert "violations" in result
        assert "final_lambda" in result
        assert len(result["episodes"]) == 2

    def test_train_episode_steps_have_cmdp_fields(self):
        result = self.service.train_episode(episodes=1, max_steps=3)
        episode = result["episodes"][0]
        assert "steps" in episode
        for step in episode["steps"]:
            assert "cost" in step
            assert "safe_reward" in step
            assert "cumulative_cost" in step
            assert "safety_violation" in step

    def test_train_episode_lambda_evolves(self):
        """Over multiple episodes, the Lagrangian multiplier should change."""
        result = self.service.train_episode(episodes=10, max_steps=10)
        # Lambda should have been updated during training
        assert result["final_lambda"] != 0.1  # Should differ from initial


# ---------------------------------------------------------------------------
# Utility function tests
# ---------------------------------------------------------------------------


class TestUtilities:
    def test_probability_band_low(self):
        assert _probability_band(0.3) == "low"
        assert _probability_band(0.54) == "low"

    def test_probability_band_medium(self):
        assert _probability_band(0.55) == "medium"
        assert _probability_band(0.79) == "medium"

    def test_probability_band_high(self):
        assert _probability_band(0.8) == "high"
        assert _probability_band(1.0) == "high"

    def test_action_costs_all_actions_covered(self):
        for action in ACTIONS:
            assert action in ACTION_COSTS

    def test_escalate_always_zero_cost(self):
        assert ACTION_COSTS["escalate_to_human"] == 0.0
