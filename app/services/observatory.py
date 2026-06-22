from __future__ import annotations

import csv
import math
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, pstdev
from typing import Any

from app.database import db
from app.services.ctgnn_model import METRICS
from app.services.intelligence import intelligence_service


class ObservatoryService:
    def comparison(self, limit: int = 100) -> dict[str, Any]:
        live_rows = db.latest_telemetry(limit)
        sim_rows = db.latest_shadow_telemetry(limit)
        live_stats = self._stats_by_metric(live_rows)
        sim_stats = self._stats_by_metric(sim_rows)
        divergences = {
            metric: self._kl_divergence(
                [float(row.get("metrics", {}).get(metric, 0.0) or 0.0) for row in live_rows],
                [float(row.get("metrics", {}).get(metric, 0.0) or 0.0) for row in sim_rows],
            )
            for metric in METRICS
        }
        quality = {
            metric: {
                "kl_divergence": value,
                "badge": "green" if value < 0.1 else "yellow" if value < 0.5 else "red",
                "label": "transfers_well" if value < 0.1 else "adapting" if value < 0.5 else "distribution_gap",
            }
            for metric, value in divergences.items()
        }
        aci = intelligence_service._conformal.aci_report()
        return {
            "status": "ready",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "limit": limit,
            "counts": {"live": len(live_rows), "shadow_sim": len(sim_rows)},
            "live": {"source_counts": self._source_counts(live_rows), "stats": live_stats},
            "simulation": {"source_counts": self._source_counts(sim_rows), "stats": sim_stats},
            "transfer_quality": quality,
            "conformal": {
                "calibration": {
                    "is_calibrated": intelligence_service._conformal.is_calibrated,
                    "q_hat": intelligence_service._conformal.q_hat,
                    "n_calibration": intelligence_service._conformal.n_calibration,
                    "target_coverage": round(1 - intelligence_service._conformal.alpha, 4),
                },
                "aci": aci,
            },
            "q_hat_trace": aci.get("recent_history", []),
            "value_statement": self._value_statement(live_rows, sim_rows, quality, aci),
        }

    def incident_match(self) -> dict[str, Any]:
        alert = (db.latest_alerts(1) or [None])[0]
        trace = intelligence_service.last_prediction_trace
        metrics = None
        if trace:
            metrics = trace.get("latest_metrics")
        if not metrics:
            rows = db.latest_telemetry(1)
            metrics = rows[-1].get("metrics", {}) if rows else {}
        scenario = self._closest_scenario(metrics)
        return {
            "status": "ready" if scenario else "no_scenario_data",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "real_incident": {
                "alert": alert,
                "metrics": {metric: metrics.get(metric) for metric in METRICS},
                "risk": trace.get("conformal", {}).get("fault_probability") if trace else None,
            },
            "closest_synthetic": scenario,
        }

    def divergence_log(self, limit: int = 100) -> dict[str, Any]:
        comparison = self.comparison(limit)
        rows = []
        for metric in METRICS:
            live = comparison["live"]["stats"].get(metric, {})
            sim = comparison["simulation"]["stats"].get(metric, {})
            kl = comparison["transfer_quality"][metric]["kl_divergence"]
            rows.append({
                "metric": metric,
                "sim_distribution": self._distribution_label(sim),
                "live_distribution": self._distribution_label(live),
                "kl_divergence": kl,
                "severity": comparison["transfer_quality"][metric]["badge"],
                "why": self._why(metric, live, sim, kl),
            })
        rows.sort(key=lambda item: item["kl_divergence"], reverse=True)
        return {
            "status": "ready",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "rows": rows,
            "value_statement": comparison["value_statement"],
        }

    def _stats_by_metric(self, rows: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
        stats = {}
        for metric in METRICS:
            values = sorted(float(row.get("metrics", {}).get(metric, 0.0) or 0.0) for row in rows)
            if not values:
                stats[metric] = {"mean": 0.0, "std": 0.0, "p10": 0.0, "p50": 0.0, "p90": 0.0}
                continue
            stats[metric] = {
                "mean": round(mean(values), 6),
                "std": round(pstdev(values), 6) if len(values) > 1 else 0.0,
                "p10": round(values[int((len(values) - 1) * 0.10)], 6),
                "p50": round(values[int((len(values) - 1) * 0.50)], 6),
                "p90": round(values[int((len(values) - 1) * 0.90)], 6),
                "min": round(values[0], 6),
                "max": round(values[-1], 6),
            }
        return stats

    def _kl_divergence(self, xs: list[float], ys: list[float], bins: int = 12) -> float:
        if not xs or not ys:
            return 0.0
        lo = min(xs + ys)
        hi = max(xs + ys)
        if hi <= lo:
            return 0.0
        width = (hi - lo) / bins
        eps = 1e-6
        p = [eps] * bins
        q = [eps] * bins
        for value in xs:
            p[min(bins - 1, max(0, int((value - lo) / width)))] += 1
        for value in ys:
            q[min(bins - 1, max(0, int((value - lo) / width)))] += 1
        ps = sum(p)
        qs = sum(q)
        p = [value / ps for value in p]
        q = [value / qs for value in q]
        return round(sum(pi * math.log(pi / qi) for pi, qi in zip(p, q)), 6)

    def _source_counts(self, rows: list[dict[str, Any]]) -> dict[str, int]:
        counts = {}
        for row in rows:
            source = str(row.get("source", "simulation"))
            counts[source] = counts.get(source, 0) + 1
        return counts

    def _closest_scenario(self, metrics: dict[str, Any]) -> dict[str, Any] | None:
        target = [float(metrics.get(metric, 0.0) or 0.0) for metric in METRICS]
        best = None
        for path in Path("data/scenarios").glob("*.csv"):
            try:
                with open(path, newline="", encoding="utf-8") as handle:
                    for row in csv.DictReader(handle):
                        vec = [float(row.get(metric, 0.0) or 0.0) for metric in METRICS]
                        score = self._cosine(target, vec)
                        if best is None or score > best["similarity"]:
                            best = {
                                "scenario": path.name,
                                "similarity": round(score, 4),
                                "metrics": {metric: round(vec[idx], 6) for idx, metric in enumerate(METRICS)},
                                "fault_type": row.get("fault_type") or None,
                                "fault_label": int(float(row.get("fault_label", 0) or 0)),
                            }
            except Exception:
                continue
        return best

    def _cosine(self, a: list[float], b: list[float]) -> float:
        dot = sum(x * y for x, y in zip(a, b))
        na = math.sqrt(sum(x * x for x in a)) or 1.0
        nb = math.sqrt(sum(y * y for y in b)) or 1.0
        return max(0.0, min(1.0, dot / (na * nb)))

    def _distribution_label(self, stats: dict[str, float]) -> str:
        return f"mu={stats.get('mean', 0):.3f}, sigma={stats.get('std', 0):.3f}, p90={stats.get('p90', 0):.3f}"

    def _why(self, metric: str, live: dict[str, float], sim: dict[str, float], kl: float) -> str:
        if kl < 0.1:
            return "Live and simulation distributions overlap closely for this metric."
        if metric == "packet_loss":
            return "Live packet loss often clusters in bursts around forwarding or radio events, while simulation is smoother."
        if metric == "throughput_mbps":
            return "Live throughput is application-shaped and interface-bursty; simulation uses smoother traffic curves."
        if metric == "cpu":
            return "Live CPU includes kernel and Open5GS process scheduling overhead that simulation only approximates."
        if metric == "latency_ms":
            return "Live latency includes registration, queueing, and tunnel overhead that can arrive as short spikes."
        return "The live distribution differs from the synthetic baseline enough for ACI to keep adapting intervals."

    def _value_statement(
        self,
        live_rows: list[dict[str, Any]],
        sim_rows: list[dict[str, Any]],
        quality: dict[str, dict[str, Any]],
        aci: dict[str, Any],
    ) -> str:
        red = sum(1 for item in quality.values() if item["badge"] == "red")
        yellow = sum(1 for item in quality.values() if item["badge"] == "yellow")
        coverage = aci.get("empirical_coverage")
        coverage_text = f"ACI running coverage is {coverage * 100:.1f}%." if isinstance(coverage, (int, float)) else "ACI is waiting for enough online updates."
        return (
            f"NetOracle compared {len(live_rows)} active-source ticks with {len(sim_rows)} shadow simulation ticks. "
            f"{6 - red - yellow} metrics transfer cleanly, {yellow} are adapting, and {red} show a distribution gap. "
            f"{coverage_text}"
        )


observatory_service = ObservatoryService()
