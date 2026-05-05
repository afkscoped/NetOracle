"""
Conformal Prediction — Member 2 Novel Contribution
====================================================
Split Conformal Prediction with finite-sample coverage guarantee.

Based on: Angelopoulos & Bates, "Conformal Prediction: A Gentle Introduction"
          Foundations and Trends in ML, 2023.

Coverage guarantee: P(true ∈ [p̂ - q̂, p̂ + q̂]) ≥ 1 - α
"""
import json
import logging
import math
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

ARTIFACTS_DIR = Path(__file__).resolve().parent.parent.parent / "artifacts"
CALIBRATION_PATH = ARTIFACTS_DIR / "conformal_calibration.json"


class ConformalPredictor:
    """
    Split Conformal Predictor for CTGNN fault probability outputs.

    The key insight: compute non-conformity scores on a held-out calibration set,
    take the (1-α) empirical quantile q̂, then for any new prediction p̂,
    the interval [p̂ - q̂, p̂ + q̂] contains the true value with probability ≥ 1-α.
    """

    def __init__(self, alpha: float = 0.10):
        """
        Args:
            alpha: significance level. α=0.10 → 90% coverage guarantee.
        """
        assert 0 < alpha < 1, "alpha must be in (0, 1)"
        self.alpha = alpha
        self.q_hat: float | None = None
        self.n_calibration: int = 0
        self.is_calibrated: bool = False

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

    def calibrate_from_file(self) -> bool:
        """Load calibration data from the Colab-generated JSON file."""
        if not CALIBRATION_PATH.exists():
            logger.warning(f"Calibration file not found: {CALIBRATION_PATH}")
            return False

        try:
            data = json.loads(CALIBRATION_PATH.read_text(encoding="utf-8"))
            self.q_hat = float(data["q_hat"])
            self.n_calibration = int(data["n_calibration"])
            self.alpha = float(data.get("alpha", self.alpha))
            self.is_calibrated = True

            logger.info(
                f"Conformal loaded from file: q̂={self.q_hat:.4f}, "
                f"coverage={data.get('empirical_test_coverage', 'N/A')}, "
                f"N_cal={self.n_calibration}"
            )
            return True

        except Exception as e:
            logger.error(f"Failed to load calibration: {e}")
            return False

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
