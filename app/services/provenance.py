from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.database import db
from app.services.ctgnn_model import METRICS
from app.services.intelligence import intelligence_service


class ProvenanceService:
    def latest(self) -> dict[str, Any]:
        trace = intelligence_service.last_prediction_trace
        if not trace:
            intelligence_service.predict_latest()
            trace = intelligence_service.last_prediction_trace
        if not trace:
            return {
                "status": "insufficient_data",
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "message": "No prediction trace is available yet.",
                "stages": {},
            }

        rows = db.telemetry_for_node(trace["slice_id"], trace["node_id"], trace.get("window_size", 12))
        model_trace = trace.get("model_trace") or self._fallback_model_trace(rows, trace.get("norm_stats", {}))
        latest = rows[-1] if rows else {"metrics": trace.get("latest_metrics", {})}
        evidence = trace.get("evidence") or latest.get("evidence") or {}
        queries = evidence.get("queries", []) if isinstance(evidence, dict) else []
        raw_values = evidence.get("raw_values", {}) if isinstance(evidence, dict) else {}
        remediation = self._latest_remediation(trace.get("node_id"))

        return {
            "status": "ready",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "node": {
                "slice_id": trace.get("slice_id"),
                "node_id": trace.get("node_id"),
                "node_type": trace.get("node_type"),
                "source": trace.get("source", latest.get("source", "unknown")),
                "source_detail": trace.get("source_detail") or latest.get("source_detail"),
            },
            "stages": {
                "raw_collection": {
                    "queries": queries,
                    "raw_values": raw_values,
                    "derived_metrics": latest.get("metrics", {}),
                    "source": trace.get("source", latest.get("source", "unknown")),
                },
                "normalization": {
                    "metrics": METRICS,
                    "norm_stats": trace.get("norm_stats", {}),
                    "latest": self._normalization_rows(latest.get("metrics", {}), trace.get("norm_stats", {})),
                    "tensor": model_trace.get("normalized_tensor", []),
                },
                "model_processing": {
                    "model": trace.get("model"),
                    "model_loaded": trace.get("model_loaded"),
                    "logit": model_trace.get("logit", trace.get("attribution", {}).get("logit")),
                    "probability": model_trace.get("probability", trace.get("conformal", {}).get("fault_probability")),
                    "attention_weights": model_trace.get("attention_weights"),
                    "hidden_state_magnitude": model_trace.get("hidden_state_magnitude"),
                    "raw_window": model_trace.get("raw_window", []),
                    "attribution": trace.get("attribution", {}),
                    "inference_ms": trace.get("inference_ms", 0.0),
                },
                "calibration_decision": {
                    "conformal": trace.get("conformal", {}),
                    "aci_update": trace.get("aci_update", {}),
                    "causal_edges": trace.get("causal_edges", []),
                    "cmdp_gate": remediation,
                    "top_features": trace.get("top_features", []),
                    "fault_type": trace.get("fault_type"),
                },
            },
        }

    def _fallback_model_trace(self, rows: list[dict[str, Any]], norm_stats: dict[str, dict[str, float]]) -> dict[str, Any]:
        normalized = []
        raw_window = []
        for row in rows[-12:]:
            metrics = row.get("metrics", {})
            raw_window.append({metric: round(float(metrics.get(metric, 0.0) or 0.0), 6) for metric in METRICS})
            normalized.append([
                round((float(metrics.get(metric, 0.0) or 0.0) - float(norm_stats.get(metric, {}).get("mean", 0.0))) /
                      (float(norm_stats.get(metric, {}).get("std", 1.0)) + 1e-6), 6)
                for metric in METRICS
            ])
        attribution = intelligence_service._heuristic_risk_explanation(rows[-1].get("metrics", {}) if rows else {})
        return {
            "metrics": METRICS,
            "raw_window": raw_window,
            "normalized_tensor": normalized,
            "logit": attribution.get("logit"),
            "probability": attribution.get("probability"),
            "attention_weights": None,
            "hidden_state_magnitude": None,
        }

    def _normalization_rows(self, metrics: dict[str, Any], norm_stats: dict[str, dict[str, float]]) -> list[dict[str, Any]]:
        rows = []
        for metric in METRICS:
            value = float(metrics.get(metric, 0.0) or 0.0)
            stats = norm_stats.get(metric, {"mean": 0.0, "std": 1.0})
            mean = float(stats.get("mean", 0.0))
            std = float(stats.get("std", 1.0)) or 1.0
            normalized = (value - mean) / (std + 1e-6)
            rows.append({
                "metric": metric,
                "raw": round(value, 6),
                "mean": round(mean, 6),
                "std": round(std, 6),
                "normalized": round(normalized, 6),
                "formula": f"({value:.4f} - {mean:.4f}) / {std:.4f} = {normalized:.4f}",
            })
        return rows

    def _latest_remediation(self, node_id: str | None) -> dict[str, Any] | None:
        for entry in db.audit_entries(100):
            if entry.get("event_type") != "remediation_decision":
                continue
            payload = entry.get("payload", {})
            rl = payload.get("rl_recommendation", {})
            context = rl.get("context", {})
            if node_id and context.get("node_id") not in (None, "unknown", node_id):
                continue
            return {
                "timestamp": entry.get("timestamp"),
                "action": payload.get("action"),
                "status": payload.get("status"),
                "cmdp_approved": rl.get("cmdp_approved"),
                "cmdp_reason": rl.get("cmdp_reason"),
                "constraints": rl.get("cmdp_constraints", {}),
                "violated_constraints": rl.get("violated_constraints", []),
            }
        return None


provenance_service = ProvenanceService()
