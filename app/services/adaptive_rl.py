import json
import os
import random
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from app.database import db


# ---------------------------------------------------------------------------
# Action Space & Safety Cost Matrix
# ---------------------------------------------------------------------------

ACTIONS = ["scale_vnf", "push_flow_rule", "reallocate_channel", "escalate_to_human"]

# Per-action base safety costs — higher cost = more disruptive action
ACTION_COSTS: dict[str, float] = {
    "scale_vnf": 0.5,            # Low risk: spin up a new replica
    "push_flow_rule": 1.0,       # Medium risk: modify routing tables
    "reallocate_channel": 1.5,   # Medium risk: radio reconfig can cause brief disruption
    "escalate_to_human": 0.0,    # Zero cost: human decides, no automated disruption
}

# Fault-type to numeric state index mapping
FAULT_TYPES = ["congestion", "cpu_overload", "packet_loss", "vnf_degradation", "latency_spike"]
RISK_LEVELS = ["low", "medium", "high"]
PROBABILITY_BANDS = ["low", "medium", "high"]


def _probability_band(probability: float) -> str:
    if probability >= 0.8:
        return "high"
    if probability >= 0.55:
        return "medium"
    return "low"


def _is_peak_hours() -> bool:
    """Check if the current time is within business/peak hours (09:00-18:00 UTC)."""
    hour = datetime.now(timezone.utc).hour
    return 9 <= hour <= 18


# ---------------------------------------------------------------------------
# CMDP Safety Configuration
# ---------------------------------------------------------------------------

SAFETY_THRESHOLD = float(os.getenv("CMDP_SAFETY_THRESHOLD", "0.35"))
SAFETY_CONSTRAINT_LOG = []

class CMDPSafetyFilter:
    """
    Implements the safety constraint layer for Constrained MDP.
    The RL policy proposes an action. This filter checks the conformal
    prediction risk score (from Member 2's intelligence.py output).
    If risk exceeds the threshold, the action is blocked and escalated.
    """
    def __init__(self, threshold: float = SAFETY_THRESHOLD):
        self.threshold = threshold

    def is_safe(self, risk_score: float, action: str) -> bool:
        if action == "escalate_to_human":
            return True
        return risk_score <= self.threshold

    def evaluate(self, action: str, risk_score: float, confidence: float) -> dict[str, Any]:
        safe = self.is_safe(risk_score, action)
        decision = {
            "action": action,
            "risk_score": risk_score,
            "confidence": confidence,
            "safety_threshold": self.threshold,
            "approved": safe,
            "reason": (
                "CMDP approved: risk within safe bounds."
                if safe
                else f"CMDP BLOCKED: risk_score {risk_score:.3f} exceeds threshold {self.threshold}. Escalating to human."
            ),
        }
        SAFETY_CONSTRAINT_LOG.append(decision)
        return decision

cmdp_safety_filter = CMDPSafetyFilter()


# ---------------------------------------------------------------------------
# Safe Remediation Environment (Gymnasium-compatible CMDP)
# ---------------------------------------------------------------------------

try:
    import gymnasium as gym
    from gymnasium import spaces
    _GYM_AVAILABLE = True
except ImportError:
    _GYM_AVAILABLE = False


class SafeRemediationEnv:
    """
    A Gymnasium-compatible environment implementing Constrained MDP (CMDP)
    constraints for safe remediation learning.

    The agent must maximise reward (fault resolution) subject to the constraint
    that cumulative safety cost stays below `cost_limit`. This prevents the
    agent from learning overly aggressive remediation strategies.

    Observation space: (fault_type_idx, risk_idx, probability_band_idx) → Discrete
    Action space: 4 possible remediation actions
    """

    def __init__(self, cost_limit: float = 5.0):
        n_states = len(FAULT_TYPES) * len(RISK_LEVELS) * len(PROBABILITY_BANDS)
        self.n_states = n_states
        self.n_actions = len(ACTIONS)
        self.cost_limit = cost_limit

        if _GYM_AVAILABLE:
            self.observation_space = spaces.Discrete(n_states)
            self.action_space = spaces.Discrete(self.n_actions)
        else:
            self.observation_space = None
            self.action_space = None

        # Internal state
        self._rng = np.random.default_rng(4242)
        self._fault_idx = 0
        self._risk_idx = 0
        self._prob_idx = 0
        self.current_cost = 0.0
        self._step_count = 0
        self._max_steps = 15

    def _state_to_index(self, fault_idx: int, risk_idx: int, prob_idx: int) -> int:
        return fault_idx * len(RISK_LEVELS) * len(PROBABILITY_BANDS) + risk_idx * len(PROBABILITY_BANDS) + prob_idx

    def _index_to_state(self, index: int) -> tuple[int, int, int]:
        prob_idx = index % len(PROBABILITY_BANDS)
        remainder = index // len(PROBABILITY_BANDS)
        risk_idx = remainder % len(RISK_LEVELS)
        fault_idx = remainder // len(RISK_LEVELS)
        return fault_idx, risk_idx, prob_idx

    @property
    def state_index(self) -> int:
        return self._state_to_index(self._fault_idx, self._risk_idx, self._prob_idx)

    def reset(self, seed: int | None = None) -> tuple[int, dict]:
        """Reset the environment to a random initial fault state."""
        if seed is not None:
            self._rng = np.random.default_rng(seed)
        self._fault_idx = int(self._rng.integers(0, len(FAULT_TYPES)))
        self._risk_idx = int(self._rng.integers(0, len(RISK_LEVELS)))
        self._prob_idx = int(self._rng.integers(0, len(PROBABILITY_BANDS)))
        self.current_cost = 0.0
        self._step_count = 0
        info = {
            "fault_type": FAULT_TYPES[self._fault_idx],
            "risk": RISK_LEVELS[self._risk_idx],
            "probability_band": PROBABILITY_BANDS[self._prob_idx],
        }
        return self.state_index, info

    def step(self, action: int) -> tuple[int, float, bool, bool, dict]:
        """
        Execute a remediation action and return (obs, reward, terminated, truncated, info).

        The info dict includes CMDP cost metrics:
        - cost: safety cost of this action
        - cumulative_cost: total cost so far
        - safety_violation: whether cumulative cost exceeds the limit
        """
        self._step_count += 1
        action_name = ACTIONS[action]

        # 1. Calculate safety cost (the CMDP upgrade)
        step_cost = self._calculate_safety_cost(action_name)
        self.current_cost += step_cost

        # 2. Calculate reward for this action
        reward = self._calculate_reward(action_name)

        # 3. Transition to next state
        self._transition(action_name)
        obs = self.state_index

        # 4. Check termination
        terminated = self._is_resolved(action_name)
        truncated = self._step_count >= self._max_steps

        # 5. Build info dict with CMDP cost metrics
        info = {
            "cost": step_cost,
            "cumulative_cost": self.current_cost,
            "safety_violation": self.current_cost > self.cost_limit,
            "action_name": action_name,
            "fault_type": FAULT_TYPES[self._fault_idx],
            "risk": RISK_LEVELS[self._risk_idx],
            "step": self._step_count,
        }

        return obs, reward, terminated, truncated, info

    def _calculate_safety_cost(self, action_name: str) -> float:
        """
        Calculate the safety cost of an action, with context-dependent modifiers.
        Peak hours and high-risk states increase the cost of disruptive actions.
        """
        base_cost = ACTION_COSTS.get(action_name, 1.0)

        # Peak hours multiplier: dangerous actions cost 2x during business hours
        if _is_peak_hours() and action_name != "escalate_to_human":
            base_cost *= 2.0

        # High-risk state modifier: aggressive actions in high-risk states cost more
        if self._risk_idx == 2:  # high risk
            base_cost *= 1.5

        return round(base_cost, 2)

    def _calculate_reward(self, action_name: str) -> float:
        """
        Calculate reward based on how appropriate the action is for the fault type.
        Correct action for the fault → high reward. Wrong action → low/negative reward.
        """
        fault_type = FAULT_TYPES[self._fault_idx]
        optimal_actions = {
            "congestion": "scale_vnf",
            "cpu_overload": "scale_vnf",
            "packet_loss": "reallocate_channel",
            "vnf_degradation": "scale_vnf",
            "latency_spike": "push_flow_rule",
        }
        optimal = optimal_actions.get(fault_type, "escalate_to_human")

        if action_name == optimal:
            return 10.0
        elif action_name == "escalate_to_human":
            return 2.0  # Safe but slow — partial reward
        else:
            return -1.0  # Wrong automated action

    def _transition(self, action_name: str) -> None:
        """Stochastic state transition after an action."""
        # Correct actions tend to reduce risk; wrong actions may increase it
        fault_type = FAULT_TYPES[self._fault_idx]
        optimal_actions = {
            "congestion": "scale_vnf",
            "cpu_overload": "scale_vnf",
            "packet_loss": "reallocate_channel",
            "vnf_degradation": "scale_vnf",
            "latency_spike": "push_flow_rule",
        }

        if action_name == optimal_actions.get(fault_type):
            # Correct action: likely reduce risk
            self._risk_idx = max(0, self._risk_idx - 1)
            if self._rng.random() < 0.3:
                self._prob_idx = max(0, self._prob_idx - 1)
        elif action_name != "escalate_to_human":
            # Wrong automated action: risk may increase
            if self._rng.random() < 0.4:
                self._risk_idx = min(len(RISK_LEVELS) - 1, self._risk_idx + 1)

    def _is_resolved(self, action_name: str) -> bool:
        """Episode ends if risk drops to low AND the correct action was taken."""
        fault_type = FAULT_TYPES[self._fault_idx]
        optimal_actions = {
            "congestion": "scale_vnf",
            "cpu_overload": "scale_vnf",
            "packet_loss": "reallocate_channel",
            "vnf_degradation": "scale_vnf",
            "latency_spike": "push_flow_rule",
        }
        return self._risk_idx == 0 and action_name == optimal_actions.get(fault_type)


# ---------------------------------------------------------------------------
# CMDP Agent: Q-learning with Lagrangian Safety Constraint
# ---------------------------------------------------------------------------

class CMDPAgent:
    """
    Constrained MDP agent using a Lagrangian relaxation approach.

    The agent modifies rewards by subtracting (lambda * cost) from the raw reward,
    teaching it to avoid high-cost actions. The Lagrangian multiplier lambda is
    dynamically adjusted: it increases when safety constraints are violated and
    decreases when the agent operates within budget.
    """

    def __init__(self, n_states: int, n_actions: int, cost_limit: float = 5.0):
        self.n_states = n_states
        self.n_actions = n_actions
        self.cost_limit = cost_limit
        self.lambda_multiplier = 0.1  # Initial Lagrangian penalty weight
        self.lambda_lr = 0.05         # Learning rate for lambda updates
        self.lambda_max = 5.0         # Cap to prevent runaway penalty

        # Q-table initialised to zeros
        self.q_table = np.zeros((n_states, n_actions), dtype=np.float64)

    def select_action(self, state: int, epsilon: float = 0.08) -> int:
        """Epsilon-greedy action selection."""
        if np.random.random() < epsilon:
            return int(np.random.randint(0, self.n_actions))
        return int(np.argmax(self.q_table[state]))

    def safe_reward(self, reward: float, cost: float) -> float:
        """Compute the Lagrangian-penalised reward."""
        return reward - (self.lambda_multiplier * cost)

    def train_step(
        self,
        state: int,
        action: int,
        reward: float,
        cost: float,
        next_state: int,
        alpha: float = 0.25,
        gamma: float = 0.95,
    ) -> dict[str, float]:
        """
        Single Q-learning update with CMDP cost penalty.

        Returns metrics about the update for logging.
        """
        safe_r = self.safe_reward(reward, cost)
        old_q = self.q_table[state, action]
        best_next = float(np.max(self.q_table[next_state]))
        td_target = safe_r + gamma * best_next
        self.q_table[state, action] = old_q + alpha * (td_target - old_q)

        return {
            "old_q": round(float(old_q), 4),
            "new_q": round(float(self.q_table[state, action]), 4),
            "raw_reward": reward,
            "safe_reward": round(safe_r, 4),
            "cost": cost,
            "lambda": round(self.lambda_multiplier, 4),
        }

    def update_lagrangian(self, cumulative_cost: float) -> None:
        """
        Dual variable update for the Lagrangian relaxation.
        If cumulative cost exceeds the budget, increase lambda (penalise more).
        If within budget, decrease lambda (allow more aggressive actions).
        """
        constraint_violation = cumulative_cost - self.cost_limit
        self.lambda_multiplier = max(
            0.0,
            min(self.lambda_max, self.lambda_multiplier + self.lambda_lr * constraint_violation)
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialise agent state for persistence."""
        return {
            "q_table": self.q_table.tolist(),
            "lambda_multiplier": self.lambda_multiplier,
            "cost_limit": self.cost_limit,
            "n_states": self.n_states,
            "n_actions": self.n_actions,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CMDPAgent":
        """Restore agent from a serialised dict."""
        agent = cls(
            n_states=data.get("n_states", 45),
            n_actions=data.get("n_actions", 4),
            cost_limit=data.get("cost_limit", 5.0),
        )
        agent.lambda_multiplier = data.get("lambda_multiplier", 0.1)
        q_table = data.get("q_table")
        if q_table is not None:
            agent.q_table = np.array(q_table, dtype=np.float64)
        return agent


# ---------------------------------------------------------------------------
# Adaptive RL Service (upgraded with CMDP)
# ---------------------------------------------------------------------------

class AdaptiveRLService:
    def __init__(self) -> None:
        self.path = Path("data/rl_policy.json")
        self.rng = random.Random(4242)
        self.q = self._load()

        # CMDP components
        self.env = SafeRemediationEnv(cost_limit=5.0)
        self.cmdp_agent = self._load_cmdp_agent()
        self.cumulative_session_cost = 0.0

    def _load(self) -> dict[str, dict[str, float]]:
        if self.path.exists():
            return json.loads(self.path.read_text(encoding="utf-8"))
        return {}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.q, indent=2), encoding="utf-8")

    def _cmdp_path(self) -> Path:
        return Path("data/cmdp_agent.json")

    def _load_cmdp_agent(self) -> CMDPAgent:
        """Load the CMDP agent from disk, or create a fresh one."""
        path = self._cmdp_path()
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                return CMDPAgent.from_dict(data)
            except Exception:
                pass
        return CMDPAgent(
            n_states=self.env.n_states,
            n_actions=self.env.n_actions,
            cost_limit=self.env.cost_limit,
        )

    def _save_cmdp_agent(self) -> None:
        path = self._cmdp_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.cmdp_agent.to_dict(), indent=2), encoding="utf-8")

    def state_key(self, fault_type: str, risk: str, probability: float) -> str:
        band = "high" if probability >= 0.8 else "medium" if probability >= 0.55 else "low"
        return f"{fault_type}:{risk}:{band}"

    def _compute_action_cost(self, action: str, risk: str) -> float:
        """Compute the safety cost for a specific action in the current context."""
        base_cost = ACTION_COSTS.get(action, 1.0)
        if _is_peak_hours() and action != "escalate_to_human":
            base_cost *= 2.0
        if risk == "high":
            base_cost *= 1.5
        return round(base_cost, 2)

    def recommend(
        self, 
        fault_type: str, 
        risk: str = "low", 
        probability: float = 0.7, 
        epsilon: float = 0.08,
        conformal_risk_score: float = 0.0,
        traffic_load: float = 0.0
    ) -> dict[str, Any]:
        state = self.state_key(fault_type, risk, probability)
        self.q.setdefault(state, {action: 0.0 for action in ACTIONS})
        
        # Action Masking (Safety Shield)
        valid_actions = ACTIONS[:-1]  # Exclude escalate_to_human from automated choice
        if _is_peak_hours() and traffic_load > 80.0:
            # Physically block highly disruptive actions (cost >= 1.5) during peak high-load
            valid_actions = [a for a in valid_actions if ACTION_COSTS.get(a, 0.0) < 1.5]
            if not valid_actions:
                valid_actions = ["escalate_to_human"]

        if risk != "low":
            action = "escalate_to_human"
            strategy = "safety_override"
        elif self.rng.random() < epsilon:
            action = self.rng.choice(valid_actions)
            strategy = "epsilon_exploration"
        else:
            action = max(valid_actions, key=lambda a: self.q[state].get(a, 0.0))
            if self.q[state][action] == 0.0:
                defaults = {
                    "congestion": "scale_vnf",
                    "cpu_overload": "scale_vnf",
                    "packet_loss": "reallocate_channel" if "reallocate_channel" in valid_actions else "escalate_to_human",
                    "vnf_degradation": "scale_vnf",
                    "latency_spike": "push_flow_rule",
                }
                action = defaults.get(fault_type, "escalate_to_human")
                if action not in valid_actions and action != "escalate_to_human":
                    action = "escalate_to_human"
            strategy = "contextual_bandit_exploitation"

        # Apply CMDP Safety Filter
        confidence = 1.0 - conformal_risk_score
        safety_result = cmdp_safety_filter.evaluate(action, conformal_risk_score, confidence)
        
        if not safety_result["approved"]:
            action = "escalate_to_human"
            strategy = "cmdp_safety_filter_blocked"

        # Compute safety cost for the selected action
        safety_cost = self._compute_action_cost(action, risk)
        self.cumulative_session_cost += safety_cost

        payload = {
            "state": state,
            "action": action,
            "q_values": self.q[state],
            "strategy": strategy,
            "safety_cost": safety_cost,
            "cumulative_session_cost": round(self.cumulative_session_cost, 2),
            "cost_limit": self.env.cost_limit,
            "safety_budget_remaining": round(max(0, self.env.cost_limit - self.cumulative_session_cost), 2),
            "lambda_multiplier": round(self.cmdp_agent.lambda_multiplier, 4),
            "cmdp_approved": safety_result["approved"],
            "cmdp_reason": safety_result["reason"],
        }
        db.audit("rl_recommendation", payload)
        return payload

    def update(self, state: str, action: str, reward: float, cost: float = 0.0, alpha: float = 0.25) -> dict[str, Any]:
        self.q.setdefault(state, {candidate: 0.0 for candidate in ACTIONS})
        old = self.q[state].get(action, 0.0)

        # Apply Lagrangian penalty if cost is provided
        if cost > 0:
            safe_reward = reward - (self.cmdp_agent.lambda_multiplier * cost)
        else:
            safe_reward = reward

        self.q[state][action] = round(old + alpha * (safe_reward - old), 4)
        self._save()

        # Update Lagrangian multiplier based on cost feedback
        if cost > 0:
            self.cumulative_session_cost += cost
            self.cmdp_agent.update_lagrangian(self.cumulative_session_cost)
            self._save_cmdp_agent()

        payload = {
            "state": state,
            "action": action,
            "reward": reward,
            "cost": cost,
            "safe_reward": round(safe_reward, 4),
            "old_value": old,
            "new_value": self.q[state][action],
            "lambda_multiplier": round(self.cmdp_agent.lambda_multiplier, 4),
            "cumulative_cost": round(self.cumulative_session_cost, 2),
            "safety_violation": self.cumulative_session_cost > self.env.cost_limit,
        }
        db.audit("rl_policy_updated", payload)
        return payload

    def train_episode(self, episodes: int = 1, max_steps: int = 15) -> dict[str, Any]:
        """
        Run simulated CMDP training episodes to improve the safety-aware policy.
        Uses the SafeRemediationEnv and CMDPAgent with Lagrangian penalty updates.
        """
        episode_results = []

        for ep in range(episodes):
            state, info = self.env.reset(seed=ep)
            episode_reward = 0.0
            episode_cost = 0.0
            steps = []

            for step_num in range(max_steps):
                action = self.cmdp_agent.select_action(state, epsilon=max(0.3 - ep * 0.005, 0.05))
                next_state, reward, terminated, truncated, step_info = self.env.step(action)

                # CMDP training update
                update_metrics = self.cmdp_agent.train_step(
                    state=state,
                    action=action,
                    reward=reward,
                    cost=step_info["cost"],
                    next_state=next_state,
                )

                episode_reward += reward
                episode_cost += step_info["cost"]

                steps.append({
                    "step": step_num + 1,
                    "action": step_info["action_name"],
                    "reward": reward,
                    "cost": step_info["cost"],
                    "safe_reward": update_metrics["safe_reward"],
                    "cumulative_cost": round(step_info["cumulative_cost"], 2),
                    "safety_violation": step_info["safety_violation"],
                })

                state = next_state
                if terminated or truncated:
                    break

            # Update Lagrangian multiplier at end of episode
            self.cmdp_agent.update_lagrangian(episode_cost)

            episode_results.append({
                "episode": ep + 1,
                "total_reward": round(episode_reward, 2),
                "total_cost": round(episode_cost, 2),
                "steps_taken": len(steps),
                "safety_violated": episode_cost > self.env.cost_limit,
                "lambda_after": round(self.cmdp_agent.lambda_multiplier, 4),
                "steps": steps,
            })

        # Persist the trained agent
        self._save_cmdp_agent()

        summary = {
            "episodes_run": episodes,
            "avg_reward": round(np.mean([r["total_reward"] for r in episode_results]), 2),
            "avg_cost": round(np.mean([r["total_cost"] for r in episode_results]), 2),
            "violations": sum(1 for r in episode_results if r["safety_violated"]),
            "final_lambda": round(self.cmdp_agent.lambda_multiplier, 4),
            "cost_limit": self.env.cost_limit,
            "episodes": episode_results,
        }
        db.audit("cmdp_training", {
            "episodes": episodes,
            "avg_reward": summary["avg_reward"],
            "avg_cost": summary["avg_cost"],
            "violations": summary["violations"],
            "final_lambda": summary["final_lambda"],
        })
        return summary

    def policy(self) -> dict[str, Any]:
        return {
            "algorithm": "safety-constrained CMDP with Lagrangian penalty for adaptive remediation",
            "actions": ACTIONS,
            "q_table": self.q,
            "cmdp": {
                "cost_limit": self.env.cost_limit,
                "lambda_multiplier": round(self.cmdp_agent.lambda_multiplier, 4),
                "cumulative_session_cost": round(self.cumulative_session_cost, 2),
                "safety_budget_remaining": round(max(0, self.env.cost_limit - self.cumulative_session_cost), 2),
                "action_costs": ACTION_COSTS,
                "peak_hours_active": _is_peak_hours(),
            },
        }


adaptive_rl_service = AdaptiveRLService()
