import json
import os
import random
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from collections import deque
from dataclasses import dataclass, field

import numpy as np

from app.database import db

# ---------------------------------------------------------------------------
# CMDP Constraint Definitions
# ---------------------------------------------------------------------------

@dataclass
class SafetyConstraint:
    """A single named safety constraint with adaptive Lagrangian multiplier."""
    name: str
    threshold: float
    penalty_init: float = 1.0
    learning_rate: float = 0.05
    _lambda: float = field(init=False)
    _violations: int = field(default=0, init=False)
    _total_evaluations: int = field(default=0, init=False)

    def __post_init__(self):
        self._lambda = self.penalty_init

    def update_lambda(self, constraint_value: float):
        """
        Lagrangian update: increase λ when violated, decrease when satisfied.
        """
        self._total_evaluations += 1
        violation = constraint_value - self.threshold
        self._lambda = max(0.0, self._lambda + self.learning_rate * violation)
        if violation > 0:
            self._violations += 1

    @property
    def violation_rate(self) -> float:
        if self._total_evaluations == 0:
            return 0.0
        return self._violations / self._total_evaluations

    def is_satisfied(self, value: float) -> bool:
        return value <= self.threshold

    def penalty(self, value: float) -> float:
        """Lagrangian penalty term for cost function."""
        return self._lambda * max(0.0, value - self.threshold)


# ---------------------------------------------------------------------------
# Action Profiles
# ---------------------------------------------------------------------------

ACTION_PROFILES = {
    "restart_vnf": {
        "base_cost": 0.20,
        "estimated_downtime_s": 15,
        "blast_radius": 0.15,
        "reversible": True,
    },
    "scale_upf": {
        "base_cost": 0.30,
        "estimated_downtime_s": 5,
        "blast_radius": 0.10,
        "reversible": True,
    },
    "scale_vnf": {  # Alias for backward compatibility
        "base_cost": 0.30,
        "estimated_downtime_s": 5,
        "blast_radius": 0.10,
        "reversible": True,
    },
    "reroute_slice": {
        "base_cost": 0.50,
        "estimated_downtime_s": 30,
        "blast_radius": 0.40,
        "reversible": True,
    },
    "push_flow_rule": {  # Alias for backward compatibility
        "base_cost": 0.50,
        "estimated_downtime_s": 30,
        "blast_radius": 0.40,
        "reversible": True,
    },
    "reduce_prb_allocation": {
        "base_cost": 0.15,
        "estimated_downtime_s": 0,
        "blast_radius": 0.05,
        "reversible": True,
    },
    "reallocate_channel": {  # Alias for backward compatibility
        "base_cost": 0.15,
        "estimated_downtime_s": 0,
        "blast_radius": 0.05,
        "reversible": True,
    },
    "isolate_node": {
        "base_cost": 0.80,
        "estimated_downtime_s": 120,
        "blast_radius": 0.80,
        "reversible": False,
    },
    "escalate_to_human": {
        "base_cost": 0.0,
        "estimated_downtime_s": 0,
        "blast_radius": 0.0,
        "reversible": True,
    },
}

ACTIONS = list(ACTION_PROFILES.keys())

# ---------------------------------------------------------------------------
# Multi-Constraint CMDP Safety Filter
# ---------------------------------------------------------------------------

class MultiConstraintCMDP:
    """
    Constrained MDP safety layer with:
    - Multiple named constraints with independent Lagrangian multipliers
    - Action masking (removes unsafe actions before bandit selection)
    - Violation budget: allows at most N violations per hour before lockdown
    """

    def __init__(self):
        self.constraints = {
            "risk_score": SafetyConstraint(
                name="risk_score",
                threshold=float(os.getenv("CMDP_RISK_THRESHOLD", "0.35")),
                penalty_init=2.0,
                learning_rate=0.05,
            ),
            "blast_radius": SafetyConstraint(
                name="blast_radius",
                threshold=float(os.getenv("CMDP_BLAST_THRESHOLD", "0.50")),
                penalty_init=1.5,
                learning_rate=0.03,
            ),
            "estimated_downtime_s": SafetyConstraint(
                name="estimated_downtime_s",
                threshold=float(os.getenv("CMDP_DOWNTIME_THRESHOLD", "60")),
                penalty_init=1.0,
                learning_rate=0.02,
            ),
        }

        # Violation budget: max violations allowed per rolling hour
        self._violation_budget = int(os.getenv("CMDP_VIOLATION_BUDGET", "3"))
        self._recent_violations: deque = deque(maxlen=100)
        self._audit_log: list = []
        self._lockdown_until: float = 0.0

    @property
    def in_lockdown(self) -> bool:
        """True if too many violations occurred recently — all actions escalate."""
        now = time.time()
        if now < self._lockdown_until:
            return True
        one_hour_ago = now - 3600
        recent = [v for v in self._recent_violations if v["ts"] > one_hour_ago]
        return len(recent) >= self._violation_budget

    def _get_action_constraint_values(self, action: str, context: dict) -> dict:
        profile = ACTION_PROFILES.get(action, {
            "base_cost": 0.5, "estimated_downtime_s": 60, "blast_radius": 0.5
        })
        return {
            "risk_score": float(context.get("conformal_risk_score", context.get("risk_score", 0.5))),
            "blast_radius": profile["blast_radius"],
            "estimated_downtime_s": profile["estimated_downtime_s"],
        }

    def mask_unsafe_actions(self, available_actions: list, context: dict) -> list:
        if self.in_lockdown:
            return ["escalate_to_human"]

        safe = []
        for action in available_actions:
            values = self._get_action_constraint_values(action, context)
            all_satisfied = all(
                c.is_satisfied(values[name])
                for name, c in self.constraints.items()
            )
            if all_satisfied:
                safe.append(action)

        if not safe:
            return ["escalate_to_human"]

        return safe

    def evaluate_and_update(self, action: str, context: dict) -> dict:
        if self.in_lockdown:
            decision = {
                "action": action,
                "approved": False,
                "reason": "CMDP LOCKDOWN: violation budget exceeded — all actions escalated",
                "lockdown": True,
                "constraints": {},
            }
            self._audit_log.append({**decision, "context": context, "ts": time.time()})
            return decision

        values = self._get_action_constraint_values(action, context)
        constraint_results = {}
        all_satisfied = True
        violated_constraints = []

        for name, constraint in self.constraints.items():
            value = values[name]
            satisfied = constraint.is_satisfied(value)
            constraint.update_lambda(value)  # Always update λ

            constraint_results[name] = {
                "value": round(value, 4),
                "threshold": constraint.threshold,
                "satisfied": satisfied,
                "lambda": round(constraint._lambda, 4),
                "violation_rate": round(constraint.violation_rate, 3),
            }

            if not satisfied:
                all_satisfied = False
                violated_constraints.append(name)
                self._recent_violations.append({
                    "ts": time.time(), "action": action, "constraint": name, "value": value
                })

        if not all_satisfied and self.in_lockdown:
            self._lockdown_until = time.time() + 300  # 5-minute lockdown

        decision = {
            "action": action,
            "approved": all_satisfied,
            "violated_constraints": violated_constraints,
            "constraint_results": constraint_results,
            "escalate": not all_satisfied,
            "reason": (
                "CMDP approved: all constraints satisfied."
                if all_satisfied
                else f"CMDP BLOCKED: violated [{', '.join(violated_constraints)}]"
            ),
            "lockdown": self.in_lockdown,
            "ts": time.time(),
        }

        decision["context"] = context
        self._audit_log.append(decision)
        return decision

    def get_constraint_status(self) -> dict:
        return {
            name: {
                "threshold": c.threshold,
                "lambda": round(c._lambda, 4),
                "violation_rate": round(c.violation_rate, 3),
            }
            for name, c in self.constraints.items()
        }

_cmdp = MultiConstraintCMDP()

def get_cmdp_status() -> dict:
    return {
        "constraint_health": _cmdp.get_constraint_status(),
        "in_lockdown": _cmdp.in_lockdown,
        "violation_budget": _cmdp._violation_budget,
        "recent_violations": len([
            v for v in _cmdp._recent_violations
            if v["ts"] > time.time() - 3600
        ]),
        "audit_log_size": len(_cmdp._audit_log),
    }


# ---------------------------------------------------------------------------
# Adaptive RL Service (upgraded with CMDP)
# ---------------------------------------------------------------------------

class AdaptiveRLService:
    def __init__(self) -> None:
        self.path = Path("data/rl_policy.json")
        self.rng = random.Random(4242)
        self.q = self._load()
        self.cumulative_session_cost = 0.0

    def _load(self) -> dict[str, dict[str, float]]:
        if self.path.exists():
            return json.loads(self.path.read_text(encoding="utf-8"))
        return {}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.q, indent=2), encoding="utf-8")

    def state_key(self, fault_type: str, risk: str, probability: float) -> str:
        band = "high" if probability >= 0.8 else "medium" if probability >= 0.55 else "low"
        return f"{fault_type}:{risk}:{band}"

    def recommend(
        self, 
        fault_type: str, 
        risk: str = "low", 
        probability: float = 0.7, 
        epsilon: float = 0.08,
        conformal_risk_score: float = 0.0,
        traffic_load: float = 0.0,
        **kwargs
    ) -> dict[str, Any]:
        """Backward compatible wrapper around recommend_action_cmdp"""
        context = {
            "fault_type": fault_type,
            "risk_score": conformal_risk_score,
            "conformal_risk_score": conformal_risk_score,
            "probability": probability,
            "risk": risk,
            "epsilon": epsilon,
            **kwargs
        }
        return recommend_action_cmdp(context, self)

    def update(self, state: str, action: str, reward: float, cost: float = 0.0, alpha: float = 0.25) -> dict[str, Any]:
        self.q.setdefault(state, {candidate: 0.0 for candidate in ACTIONS})
        old = self.q[state].get(action, 0.0)

        safe_reward = reward
        self.q[state][action] = round(old + alpha * (safe_reward - old), 4)
        self._save()

        payload = {
            "state": state,
            "action": action,
            "reward": reward,
            "cost": cost,
            "old_value": old,
            "new_value": self.q[state][action],
        }
        db.audit("rl_policy_updated", payload)
        return payload

    def train_episode(self, episodes: int = 1, max_steps: int = 15) -> dict[str, Any]:
        # Legacy stub for backward compatibility
        return {"message": "CMDP active, offline training skipped"}

    def policy(self) -> dict[str, Any]:
        return {
            "algorithm": "safety-constrained CMDP with Lagrangian penalty for adaptive remediation",
            "actions": ACTIONS,
            "q_table": self.q,
            "cmdp": get_cmdp_status(),
        }


adaptive_rl_service = AdaptiveRLService()


def recommend_action_cmdp(context: dict, service: AdaptiveRLService = adaptive_rl_service) -> dict:
    """
    Full Safe RL pipeline:
    1. Action masking — remove unsafe actions before bandit sees them
    2. RL bandit proposes action from SAFE subset only
    3. CMDP full constraint evaluation + Lagrangian update
    4. Return structured decision with audit trail
    """
    fault_type = context.get("fault_type", "unknown")
    risk = context.get("risk", "low")
    probability = context.get("probability", 0.7)
    epsilon = context.get("epsilon", 0.08)

    state = service.state_key(fault_type, risk, probability)
    service.q.setdefault(state, {action: 0.0 for action in ACTIONS})

    # Step 1: mask unsafe actions
    safe_actions = _cmdp.mask_unsafe_actions(ACTIONS, context)

    # Step 2: RL bandit proposes from safe subset
    if risk != "low":
        action = "escalate_to_human"
        strategy = "safety_override"
    elif service.rng.random() < epsilon:
        action = service.rng.choice(safe_actions)
        strategy = "epsilon_exploration"
    else:
        action = max(safe_actions, key=lambda a: service.q[state].get(a, 0.0))
        if service.q[state][action] == 0.0:
            defaults = {
                "congestion": "scale_vnf",
                "cpu_overload": "scale_vnf",
                "packet_loss": "reallocate_channel",
                "vnf_degradation": "scale_vnf",
                "latency_spike": "push_flow_rule",
            }
            action = defaults.get(fault_type, "escalate_to_human")
            if action not in safe_actions:
                action = "escalate_to_human"
        strategy = "contextual_bandit_exploitation"

    # Step 3: final CMDP evaluation + λ update
    safety_result = _cmdp.evaluate_and_update(action, context)
    
    if not safety_result["approved"]:
        action = "escalate_to_human"
        strategy = "cmdp_blocked"

    payload = {
        "state": state,
        "action": action,
        "q_values": service.q[state],
        "strategy": strategy,
        "safe_action_set": safe_actions,
        "cmdp_approved": safety_result["approved"],
        "cmdp_reason": safety_result["reason"],
        "cmdp_constraints": safety_result.get("constraint_results", {}),
        "violated_constraints": safety_result.get("violated_constraints", []),
        "escalate": not safety_result["approved"],
        "lockdown": safety_result.get("lockdown", False),
        "node_id": context.get("node_id", "unknown"),
        "context": context
    }
    
    db.audit("rl_recommendation", payload)
    return payload
