import json
import random
from pathlib import Path
from typing import Any

from app.database import db


ACTIONS = ["scale_vnf", "push_flow_rule", "reallocate_channel", "escalate_to_human"]


class AdaptiveRLService:
    def __init__(self) -> None:
        self.path = Path("data/rl_policy.json")
        self.rng = random.Random(4242)
        self.q = self._load()

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

    def recommend(self, fault_type: str, risk: str = "low", probability: float = 0.7, epsilon: float = 0.08) -> dict[str, Any]:
        state = self.state_key(fault_type, risk, probability)
        self.q.setdefault(state, {action: 0.0 for action in ACTIONS})
        if risk != "low":
            action = "escalate_to_human"
            strategy = "safety_override"
        elif self.rng.random() < epsilon:
            action = self.rng.choice(ACTIONS[:-1])
            strategy = "epsilon_exploration"
        else:
            action = max(self.q[state], key=self.q[state].get)
            if self.q[state][action] == 0.0:
                defaults = {
                    "congestion": "scale_vnf",
                    "cpu_overload": "scale_vnf",
                    "packet_loss": "reallocate_channel",
                    "vnf_degradation": "scale_vnf",
                    "latency_spike": "push_flow_rule",
                }
                action = defaults.get(fault_type, "escalate_to_human")
            strategy = "contextual_bandit_exploitation"
        payload = {"state": state, "action": action, "q_values": self.q[state], "strategy": strategy}
        db.audit("rl_recommendation", payload)
        return payload

    def update(self, state: str, action: str, reward: float, alpha: float = 0.25) -> dict[str, Any]:
        self.q.setdefault(state, {candidate: 0.0 for candidate in ACTIONS})
        old = self.q[state].get(action, 0.0)
        self.q[state][action] = round(old + alpha * (reward - old), 4)
        self._save()
        payload = {"state": state, "action": action, "reward": reward, "old_value": old, "new_value": self.q[state][action]}
        db.audit("rl_policy_updated", payload)
        return payload

    def policy(self) -> dict[str, Any]:
        return {"algorithm": "safety-constrained contextual bandit for adaptive remediation", "actions": ACTIONS, "q_table": self.q}


adaptive_rl_service = AdaptiveRLService()
