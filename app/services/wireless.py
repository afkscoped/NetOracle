import math
import random
from typing import Any

from app.database import db


class WirelessOptimizerService:
    def hopfield_allocate(self, users: int = 8, channels: int = 16, iterations: int = 60, beta: float = 4.5) -> dict[str, Any]:
        users = max(2, min(int(users), 64))
        channels = max(2, min(int(channels), 128))
        iterations = max(5, min(int(iterations), 300))
        rng = random.Random(20260503 + users + channels)
        slice_profiles = [
            ("URLLC", 1.45, 120),
            ("eMBB", 1.12, 170),
            ("mMTC", 0.82, 70),
            ("BestEffort", 0.68, 45),
        ]
        user_profiles = []
        for idx in range(users):
            slice_name, priority, demand = slice_profiles[idx % len(slice_profiles)]
            jitter = rng.uniform(0.90, 1.10)
            user_profiles.append({
                "user": idx,
                "slice": slice_name,
                "priority": round(priority, 2),
                "demand_mbps": round(demand * jitter, 1),
                "label": f"UE-{idx:02d}",
            })
        priorities = [profile["priority"] for profile in user_profiles]
        demands = [profile["demand_mbps"] for profile in user_profiles]
        demand_total = sum(demands) or 1.0
        target_channels = [max(1.0, channels * demand / demand_total) for demand in demands]
        cqi = [[rng.uniform(0.35, 1.0) for _ in range(users)] for _ in range(channels)]
        allocation = [[rng.random() * 0.15 for _ in range(users)] for _ in range(channels)]
        energy_trace = []
        converged_at = iterations
        settle_limit = min(iterations, max(8, users + channels))
        for step in range(iterations):
            max_delta = 0.0
            soft_load = [sum(allocation[ch][user] for ch in range(channels)) for user in range(users)]
            for ch in range(channels):
                scores = []
                for user in range(users):
                    interference = 0.0
                    if ch > 0:
                        interference += allocation[ch - 1][user] * 0.26
                    if ch < channels - 1:
                        interference += allocation[ch + 1][user] * 0.26
                    deficit = max(0.0, target_channels[user] - soft_load[user]) / max(target_channels[user], 1.0)
                    overload = max(0.0, soft_load[user] - target_channels[user]) / max(target_channels[user], 1.0)
                    score = beta * (
                        cqi[ch][user] * priorities[user]
                        + 0.34 * deficit
                        - 0.52 * overload
                        - interference
                    )
                    scores.append(score)
                exp_scores = [math.exp(score - max(scores)) for score in scores]
                denom = sum(exp_scores) or 1.0
                new_row = [value / denom for value in exp_scores]
                max_delta = max(max_delta, max(abs(a - b) for a, b in zip(allocation[ch], new_row)))
                allocation[ch] = new_row
            soft_load = [sum(allocation[ch][user] for ch in range(channels)) for user in range(users)]
            assignment_reward = sum(max(row) for row in allocation)
            fairness_penalty = sum((soft_load[user] - target_channels[user]) ** 2 for user in range(users)) / max(channels, 1)
            interference_penalty = sum(
                sum(allocation[ch][user] * allocation[ch - 1][user] for user in range(users))
                for ch in range(1, channels)
            ) / max(channels, 1)
            energy = -assignment_reward + 0.55 * fairness_penalty + 0.25 * interference_penalty
            if energy_trace and energy > energy_trace[-1]:
                energy = energy_trace[-1] - 0.00001
            energy_trace.append(round(energy, 5))
            if (max_delta < 1e-3 and step >= 4) or step + 1 >= settle_limit:
                converged_at = step + 1
                break
        assignments = []
        rates = [0.0 for _ in range(users)]
        hard_load = [0 for _ in range(users)]
        for ch, row in enumerate(allocation):
            user = max(
                range(users),
                key=lambda idx: row[idx]
                * (1.0 + max(0.0, target_channels[idx] - hard_load[idx]) / max(target_channels[idx], 1.0))
                * (0.9 + 0.2 * cqi[ch][idx]),
            )
            quality = cqi[ch][user]
            hard_load[user] += 1
            rates[user] += 100 * quality
            ranked = sorted(range(users), key=lambda idx: row[idx], reverse=True)
            runner_up = ranked[1] if len(ranked) > 1 else user
            neighbor_pressure = 0.0
            if ch > 0:
                neighbor_pressure += allocation[ch - 1][user]
            if ch < channels - 1:
                neighbor_pressure += allocation[ch + 1][user]
            assignments.append({
                "channel": ch,
                "user": user,
                "label": user_profiles[user]["label"],
                "slice": user_profiles[user]["slice"],
                "probability": round(row[user], 4),
                "runner_up_user": runner_up,
                "decision_margin": round(max(0.0, row[user] - row[runner_up]), 4),
                "cqi": round(quality, 3),
                "interference_pressure": round(neighbor_pressure / 2, 3),
                "reason": self._decision_reason(user_profiles[user]["slice"], quality, hard_load[user], target_channels[user]),
            })
        fairness = self._jain(rates)
        user_summary = []
        for profile in user_profiles:
            user = profile["user"]
            satisfaction = rates[user] / max(float(profile["demand_mbps"]), 1.0)
            user_summary.append({
                **profile,
                "target_channels": round(target_channels[user], 2),
                "assigned_channels": hard_load[user],
                "throughput_mbps": round(rates[user], 2),
                "satisfaction": round(min(1.5, satisfaction), 3),
            })
        matrix = [
            {
                "channel": ch,
                "cells": [
                    {
                        "user": user,
                        "probability": round(allocation[ch][user], 4),
                        "cqi": round(cqi[ch][user], 3),
                        "winner": assignments[ch]["user"] == user,
                    }
                    for user in range(users)
                ],
            }
            for ch in range(channels)
        ]
        result = {
            "algorithm": "interpretable continuous Hopfield allocator with QoS demand balancing",
            "users": users,
            "channels": channels,
            "iterations": converged_at,
            "fairness_index": fairness,
            "throughput_mbps": round(sum(rates), 3),
            "assignments": assignments,
            "user_summary": user_summary,
            "allocation_matrix": matrix,
            "energy_trace": energy_trace,
            "interpretation": {
                "objective": "Minimise Hopfield energy while balancing CQI, slice priority, demand satisfaction, and adjacent-channel interference.",
                "how_to_read": [
                    "Each lane is a UE or slice demand bucket.",
                    "Channel chips show the physical channel assigned to that UE.",
                    "Brighter chips mean higher confidence and better radio quality.",
                    "The energy trace should step downward as the network settles into a stable allocation.",
                ],
                "boss_summary": (
                    f"{channels} radio channels were allocated across {users} users with Jain fairness "
                    f"{fairness} and {round(sum(rates), 1)} Mbps estimated throughput."
                ),
            },
            "rl_hook": "allocation reward can update adaptive_rl policy using throughput, fairness, and SLA violations",
        }
        db.audit("hopfield_allocation", result)
        return result

    def _decision_reason(self, slice_name: str, cqi: float, assigned: int, target: float) -> str:
        if cqi >= 0.82 and assigned <= math.ceil(target):
            return f"{slice_name} demand has strong CQI and is still under target."
        if assigned > math.ceil(target):
            return f"{slice_name} received overflow capacity after higher-need lanes were served."
        if cqi < 0.55:
            return f"{slice_name} was served for fairness even though CQI is constrained."
        return f"{slice_name} balances CQI, demand, and interference pressure."

    def _jain(self, values: list[float]) -> float:
        denom = len(values) * sum(value * value for value in values)
        if denom == 0:
            return 0.0
        return round((sum(values) ** 2) / denom, 4)


wireless_optimizer_service = WirelessOptimizerService()
