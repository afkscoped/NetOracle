import math
import random
from typing import Any

from app.database import db


class WirelessOptimizerService:
    def hopfield_allocate(self, users: int = 8, channels: int = 16, iterations: int = 60, beta: float = 4.5) -> dict[str, Any]:
        rng = random.Random(20260503 + users + channels)
        priorities = [1.4 if idx % 3 == 0 else 1.0 if idx % 3 == 1 else 0.75 for idx in range(users)]
        cqi = [[rng.uniform(0.35, 1.0) for _ in range(users)] for _ in range(channels)]
        allocation = [[rng.random() * 0.15 for _ in range(users)] for _ in range(channels)]
        energy_trace = []
        converged_at = iterations
        for step in range(iterations):
            max_delta = 0.0
            for ch in range(channels):
                scores = []
                for user in range(users):
                    interference = 0.0
                    if ch > 0:
                        interference += max(allocation[ch - 1]) * 0.25
                    if ch < channels - 1:
                        interference += max(allocation[ch + 1]) * 0.25
                    score = beta * (cqi[ch][user] * priorities[user] - interference)
                    scores.append(score)
                exp_scores = [math.exp(score - max(scores)) for score in scores]
                denom = sum(exp_scores) or 1.0
                new_row = [value / denom for value in exp_scores]
                max_delta = max(max_delta, max(abs(a - b) for a, b in zip(allocation[ch], new_row)))
                allocation[ch] = new_row
            energy = -sum(max(row) for row in allocation) + 0.05 * sum(abs(max(allocation[i]) - max(allocation[i - 1])) for i in range(1, channels))
            energy_trace.append(round(energy, 5))
            if max_delta < 1e-4:
                converged_at = step + 1
                break
        assignments = []
        rates = [0.0 for _ in range(users)]
        for ch, row in enumerate(allocation):
            user = max(range(users), key=lambda idx: row[idx])
            quality = cqi[ch][user]
            rates[user] += 100 * quality
            assignments.append({"channel": ch, "user": user, "probability": round(row[user], 4), "cqi": round(quality, 3)})
        fairness = self._jain(rates)
        result = {
            "algorithm": "continuous Hopfield softmax allocator with QoS priorities",
            "users": users,
            "channels": channels,
            "iterations": converged_at,
            "fairness_index": fairness,
            "throughput_mbps": round(sum(rates), 3),
            "assignments": assignments,
            "energy_trace": energy_trace,
            "rl_hook": "allocation reward can update adaptive_rl policy using throughput, fairness, and SLA violations",
        }
        db.audit("hopfield_allocation", result)
        return result

    def _jain(self, values: list[float]) -> float:
        denom = len(values) * sum(value * value for value in values)
        if denom == 0:
            return 0.0
        return round((sum(values) ** 2) / denom, 4)


wireless_optimizer_service = WirelessOptimizerService()
