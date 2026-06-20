"""
Conformal Prediction — Member 2 Novel Contribution
====================================================
Split Conformal Prediction with finite-sample coverage guarantee.

Based on: Angelopoulos & Bates, "Conformal Prediction: A Gentle Introduction"
          Foundations and Trends in ML, 2023.

Coverage guarantee: P(true ∈ [p̂ - q̂, p̂ + q̂]) ≥ 1 - α

Adaptive Conformal Inference (ACI) — Novel Contribution (§6.3):
    q̂_{t+1} = q̂_t + γ(𝟙(y_t ∉ C_t(X_t)) - α)

    This online update rule adjusts the quantile threshold every time a new
    ground-truth label becomes available, maintaining ~(1-α) empirical coverage
    even when the test distribution drifts from the calibration distribution
    (which is expected when switching from simulated to real Open5GS data).

    Reference: Gibbs & Candès, "Adaptive Conformal Inference Under Distribution
    Shift", NeurIPS 2021. https://arxiv.org/abs/2106.00170
"""
import json
import logging
import math
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

ARTIFACTS_DIR = Path(__file__).resolve().parent.parent.parent / "artifacts"
CALIBRATION_PATH = ARTIFACTS_DIR / "conformal_calibration.json"
CALIBRATION_LIVE_PATH = ARTIFACTS_DIR / "conformal_calibration_live.json"  # separate from sim


class ConformalPredictor:
    """
    Split Conformal Predictor for CTGNN fault probability outputs.

    The key insight: compute non-conformity scores on a held-out calibration set,
    take the (1-α) empirical quantile q̂, then for any new prediction p̂,
    the interval [p̂ - q̂, p̂ + q̂] contains the true value with probability ≥ 1-α.

    Adaptive mode (ACI — §6.3):
        After calibration, call update(prediction, true_label) every time a
        ground-truth label becomes available. The threshold q̂ adapts via:
            q̂_{t+1} = q̂_t + γ(𝟙(y_t ∉ C_t(X_t)) - α)
        This maintains coverage even under distribution shift (simulation → live data).
    """

    def __init__(self, alpha: float = 0.10, gamma: float = 0.005):
        """
        Args:
            alpha: significance level. α=0.10 → 90% coverage guarantee.
            gamma: ACI step size (learning rate for online q̂ update).
                   Gibbs & Candès (2021) suggest γ ∈ [0.001, 0.05].
                   Smaller γ = slower adaptation but more stable.
        """
        assert 0 < alpha < 1, "alpha must be in (0, 1)"
        assert gamma > 0, "gamma must be positive"
        self.alpha = alpha
        self.gamma = gamma
        self.q_hat: float | None = None
        self.n_calibration: int = 0
        self.is_calibrated: bool = False

        # ACI tracking
        self._aci_updates: int = 0
        self._aci_coverage_sum: float = 0.0
        self._aci_history: list[dict] = []  # last 100 updates

    def calibrate_from_scores(self, scores: list[float]) -> None:
        """
        Calibrate from pre-computed non-conformity scores.

        Args:
            scores: sorted list of |true_label - predicted_prob| from calibration set
        """
        n = len(scores)
        if n == 0:
            logger.warning("Empty calibration scores — using fallback q̂")
            self.q_hat = 0.5
            self.n_calibration = 0
            self.is_calibrated = True
            return

        # Finite-sample adjusted quantile level
        quantile_level = min(math.ceil((n + 1) * (1 - self.alpha)) / n, 1.0)

        # Since scores are sorted, find the quantile index
        idx = min(int(quantile_level * n), n - 1)
        sorted_scores = sorted(scores)
        self.q_hat = sorted_scores[idx]
        self.n_calibration = n
        self.is_calibrated = True

        logger.info(
            f"Conformal calibrated: q̂={self.q_hat:.4f}, "
            f"{(1 - self.alpha) * 100:.0f}% coverage, N_cal={n}"
        )

    def calibrate_from_file(self, live: bool = False) -> bool:
        """Load calibration data from the JSON artifact file.

        Args:
            live: if True, load from the live-data calibration file.
                  if False, load from the simulated-data calibration file.
        """
        path = CALIBRATION_LIVE_PATH if live else CALIBRATION_PATH
        if not path.exists():
            logger.warning(f"Calibration file not found: {path}")
            return False

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            self.q_hat = float(data["q_hat"])
            self.n_calibration = int(data["n_calibration"])
            self.alpha = float(data.get("alpha", self.alpha))
            if "gamma" in data:
                self.gamma = float(data["gamma"])
            self.is_calibrated = True

            logger.info(
                f"Conformal loaded from {'live' if live else 'simulated'} file: "
                f"q̂={self.q_hat:.4f}, "
                f"coverage={data.get('empirical_test_coverage', 'N/A')}, "
                f"N_cal={self.n_calibration}"
            )
            return True

        except Exception as e:
            logger.error(f"Failed to load calibration: {e}")
            return False

    def save_calibration(self, live: bool = False, extra: dict | None = None) -> bool:
        """Save current calibration state to a JSON file.

        Args:
            live: if True, save to the live-data calibration file (does NOT overwrite simulated).
            extra: optional dict of extra fields to include (e.g., empirical_coverage, data_source).
        """
        if not self.is_calibrated or self.q_hat is None:
            logger.warning("Cannot save calibration — predictor is not calibrated.")
            return False

        path = CALIBRATION_LIVE_PATH if live else CALIBRATION_PATH
        ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)

        data: dict[str, Any] = {
            "q_hat": self.q_hat,
            "n_calibration": self.n_calibration,
            "alpha": self.alpha,
            "gamma": self.gamma,
            "aci_updates": self._aci_updates,
            "data_source": "live" if live else "simulated",
        }
        if extra:
            data.update(extra)

        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        logger.info(f"Calibration saved to {'live' if live else 'simulated'} artifact: {path}")
        return True

    def predict_with_interval(self, point_estimate: float) -> dict[str, Any]:
        """
        Produce a prediction interval for a single CTGNN output.

        Args:
            point_estimate: raw fault probability from sigmoid(logits)

        Returns:
            dict with prob, prob_lower, prob_upper, q_hat, calibrated, coverage_guarantee
        """
        if not self.is_calibrated or self.q_hat is None:
            # Uncalibrated fallback: return point estimate only
            return {
                "fault_probability": round(point_estimate, 4),
                "prob_lower": round(max(0.0, point_estimate - 0.15), 4),
                "prob_upper": round(min(1.0, point_estimate + 0.15), 4),
                "q_hat": 0.15,
                "calibrated": False,
                "coverage_guarantee": "uncalibrated",
                "aci_active": False,
            }

        lower = max(0.0, point_estimate - self.q_hat)
        upper = min(1.0, point_estimate + self.q_hat)

        return {
            "fault_probability": round(point_estimate, 4),
            "prob_lower": round(lower, 4),
            "prob_upper": round(upper, 4),
            "q_hat": round(self.q_hat, 4),
            "calibrated": True,
            "coverage_guarantee": f"{(1 - self.alpha) * 100:.0f}%",
            "interval_width": round(upper - lower, 4),
            "aci_active": self._aci_updates > 0,
            "aci_updates": self._aci_updates,
        }

    def update(self, prediction: float, true_label: float) -> dict[str, Any]:
        """
        Adaptive Conformal Inference (ACI) online update — §6.3 Novel Contribution.

        Call this each time a ground-truth label becomes available (e.g., after
        a fault injection event resolves and we know whether the alert was correct).

        Update rule (Gibbs & Candès, 2021):
            q̂_{t+1} = q̂_t + γ(𝟙(y_t ∉ C_t(X_t)) - α)

        Intuition:
            - If y_t is NOT covered by C_t, we INCREASE q̂ (widen intervals)
            - If y_t IS covered by C_t, we DECREASE q̂ (tighten intervals)
            - γ controls how quickly the threshold adapts
            - Over time, empirical coverage converges to 1-α

        Args:
            prediction: the point estimate p̂ that was made at time t
            true_label: the observed ground truth y_t (0 or 1)

        Returns:
            dict with old_q_hat, new_q_hat, covered, update_delta
        """
        if not self.is_calibrated or self.q_hat is None:
            logger.warning("ACI update called before calibration — skipping.")
            return {"error": "not calibrated"}

        old_q = self.q_hat

        # Was the true label inside the prediction interval?
        lo = max(0.0, prediction - old_q)
        hi = min(1.0, prediction + old_q)
        covered = lo <= true_label <= hi

        # ACI update: q̂_{t+1} = q̂_t + γ(𝟙(y ∉ C) - α)
        # 𝟙(y ∉ C) = 1 if NOT covered, 0 if covered
        indicator = 0.0 if covered else 1.0
        delta = self.gamma * (indicator - self.alpha)
        self.q_hat = max(0.0, min(1.0, old_q + delta))  # clamp to [0, 1]

        self._aci_updates += 1
        self._aci_coverage_sum += float(covered)

        update_record = {
            "t": self._aci_updates,
            "prediction": round(prediction, 4),
            "true_label": float(true_label),
            "covered": covered,
            "old_q_hat": round(old_q, 6),
            "new_q_hat": round(self.q_hat, 6),
            "delta": round(delta, 6),
            "running_coverage": round(self._aci_coverage_sum / self._aci_updates, 4),
        }

        # Keep rolling history of last 100 updates
        self._aci_history.append(update_record)
        if len(self._aci_history) > 100:
            self._aci_history.pop(0)

        logger.debug(
            f"[ACI] t={self._aci_updates}: covered={covered}, "
            f"q̂: {old_q:.4f} → {self.q_hat:.4f} (Δ={delta:+.4f}), "
            f"running_coverage={update_record['running_coverage']:.3f}"
        )

        return update_record

    def aci_report(self) -> dict[str, Any]:
        """
        Return a summary of the ACI adaptation history.
        Use this to verify empirical coverage on a real-data test set.
        """
        if self._aci_updates == 0:
            return {"aci_updates": 0, "message": "No ACI updates yet."}

        empirical_coverage = self._aci_coverage_sum / self._aci_updates
        target_coverage = 1.0 - self.alpha

        return {
            "aci_updates": self._aci_updates,
            "current_q_hat": round(self.q_hat, 6) if self.q_hat else None,
            "gamma": self.gamma,
            "alpha": self.alpha,
            "target_coverage": round(target_coverage, 4),
            "empirical_coverage": round(empirical_coverage, 4),
            "coverage_met": empirical_coverage >= (target_coverage - 0.02),
            "coverage_drift": round(empirical_coverage - target_coverage, 4),
            "recent_history": self._aci_history[-10:],  # last 10 updates
        }

    def coverage_report(
        self, predictions: list[float], true_labels: list[float]
    ) -> dict[str, Any]:
        """
        Verify empirical coverage on a test set.

        Args:
            predictions: model outputs (probabilities)
            true_labels: ground truth binary labels (0 or 1)

        Returns:
            dict with empirical_coverage, n_test, target_coverage, etc.
        """
        if not self.is_calibrated or self.q_hat is None:
            return {"error": "Not calibrated"}

        n = len(predictions)
        if n == 0:
            return {"error": "Empty test set"}

        covered = 0
        for p, y in zip(predictions, true_labels):
            lo = max(0.0, p - self.q_hat)
            hi = min(1.0, p + self.q_hat)
            if lo <= y <= hi:
                covered += 1

        empirical = covered / n

        return {
            "empirical_coverage": round(empirical, 4),
            "target_coverage": round(1 - self.alpha, 2),
            "coverage_met": empirical >= (1 - self.alpha - 0.02),  # 2% tolerance
            "n_test": n,
            "n_covered": covered,
            "q_hat": round(self.q_hat, 4),
            "mean_interval_width": round(2 * self.q_hat, 4),
        }
