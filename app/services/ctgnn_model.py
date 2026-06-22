"""
CausalAttentionGRU Model — Member 2 CTGNN Integration
======================================================
Defines the exact same model architecture used in training (colab_train.py)
so that torch.load can reconstruct the state_dict properly.

Gracefully degrades if PyTorch is not installed (falls back to heuristic).
"""
import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

TORCH_AVAILABLE = False
try:
    import torch
    from torch import nn
    TORCH_AVAILABLE = True
except ImportError:
    logger.warning("PyTorch not installed — CTGNN will use heuristic fallback")


ARTIFACTS_DIR = Path(__file__).resolve().parent.parent.parent / "artifacts"
MODEL_PATH = ARTIFACTS_DIR / "ctgnn_t4_best.pt"
MODEL_PATH_MLP = ARTIFACTS_DIR / "models" / "ctgnn_best.pt"
NORM_STATS_PATH = ARTIFACTS_DIR / "norm_stats.json"

# Metric names must match training exactly
METRICS = ["cpu", "memory", "latency_ms", "packet_loss", "throughput_mbps", "prb_utilization"]


if TORCH_AVAILABLE:
    class ProactiveMLP(nn.Module):
        def __init__(self, in_dim: int = 6, hidden: int = 96):
            super().__init__()
            self.net = nn.Sequential(
                nn.Linear(in_dim, hidden), nn.LayerNorm(hidden), nn.GELU(), nn.Dropout(0.12),
                nn.Linear(hidden, hidden // 2), nn.GELU(), nn.Linear(hidden // 2, 1),
            )
        def forward(self, x: "torch.Tensor") -> tuple["torch.Tensor", "torch.Tensor"]:
            if x.dim() == 3:
                x = x[:, -1, :]
            logits = self.net(x).view(-1)
            return logits, torch.zeros(x.size(0), x.size(1) if x.dim() == 2 else 1, device=x.device)

    class CausalAttentionGRU(nn.Module):
        """Exact replica of the training architecture for state_dict loading."""

        def __init__(self, feature_dim: int = 6, hidden_dim: int = 96, dropout: float = 0.15):
            super().__init__()
            self.feature_dim = feature_dim
            self.hidden_dim = hidden_dim
            self.gru = nn.GRU(feature_dim, hidden_dim, batch_first=True, num_layers=2, dropout=dropout)
            self.attention = nn.MultiheadAttention(hidden_dim, num_heads=4, dropout=dropout, batch_first=True)
            self.norm = nn.LayerNorm(hidden_dim)
            self.head = nn.Sequential(
                nn.Linear(hidden_dim, hidden_dim // 2),
                nn.GELU(),
                nn.Dropout(dropout),
                nn.Linear(hidden_dim // 2, 1),
            )

        def forward(self, x: "torch.Tensor") -> tuple["torch.Tensor", "torch.Tensor"]:
            h, _ = self.gru(x)
            attended, weights = self.attention(h, h, h, need_weights=True)
            z = self.norm(h + attended)
            logits = self.head(z[:, -1]).squeeze(-1)
            return logits, weights


def load_norm_stats() -> dict[str, dict[str, float]]:
    """Load per-metric mean/std computed during training for z-score normalization."""
    if NORM_STATS_PATH.exists():
        return json.loads(NORM_STATS_PATH.read_text(encoding="utf-8"))
    # Fallback stats from synthetic training data
    return {
        "cpu": {"mean": 48.065, "std": 5.12},
        "memory": {"mean": 50.041, "std": 3.218},
        "latency_ms": {"mean": 24.783, "std": 4.65},
        "packet_loss": {"mean": 0.0073, "std": 0.0056},
        "throughput_mbps": {"mean": 859.343, "std": 66.242},
        "prb_utilization": {"mean": 0.4803, "std": 0.05},
    }


def load_ctgnn_model() -> tuple[Any, dict[str, Any], bool]:
    """
    Load the trained CTGNN model from artifacts/.

    Returns:
        (model, metadata, is_loaded)
        - model: CausalAttentionGRU instance or None
        - metadata: dict with window, horizon, auc, etc.
        - is_loaded: True if model loaded successfully
    """
    if not TORCH_AVAILABLE:
        logger.info("PyTorch not available — model not loaded")
        return None, {}, False

    paths = [MODEL_PATH, MODEL_PATH_MLP]
    # Prefer most recently trained artifact (by modification time)
    paths = sorted([p for p in paths if p.exists()], key=lambda p: p.stat().st_mtime, reverse=True)
    for p in paths:
        try:
            device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
            checkpoint = torch.load(p, map_location=device, weights_only=False)
            arch = checkpoint.get("architecture", "")
            # Infer hidden_dim from weight shapes if not explicitly saved
            hidden_dim = checkpoint.get("hidden_dim", 96)
            state_dict = checkpoint["model_state_dict"]
            if "net.0.weight" in state_dict:
                # ProactiveMLP: net.0.weight has shape [hidden, in_dim]
                hidden_dim = state_dict["net.0.weight"].shape[0]
            elif "gru.weight_ih_l0" in state_dict:
                # CausalAttentionGRU: gru hidden is weight shape / 3
                hidden_dim = state_dict["gru.weight_ih_l0"].shape[0] // 3

            if "ProactiveMLP" in arch or "net.0.weight" in state_dict:
                model = ProactiveMLP(len(METRICS), hidden_dim)
            else:
                model = CausalAttentionGRU(
                    feature_dim=checkpoint.get("feature_dim", 6),
                    hidden_dim=hidden_dim,
                    dropout=checkpoint.get("dropout", 0.15),
                )
            model.load_state_dict(checkpoint["model_state_dict"])
            model.to(device)
            model.eval()
            metadata = {
                "auc": checkpoint.get("auc", 0.0),
                "window": checkpoint.get("window", 12),
                "horizon": checkpoint.get("horizon", 20),
                "feature_dim": checkpoint.get("feature_dim", 6),
                "hidden_dim": checkpoint.get("hidden_dim", 96),
                "metrics": checkpoint.get("metrics", METRICS),
                "architecture": arch or "CausalAttentionGRU",
                "artifact_path": str(p),
                "artifact_size_bytes": p.stat().st_size,
                "artifact_mtime": p.stat().st_mtime,
            }
            logger.info(f"CTGNN loaded from {p.name}: AUC={metadata['auc']:.4f}, arch={metadata['architecture']}")
            return model, metadata, True
        except Exception as e:
            logger.warning(f"Failed to load from {p}: {e}")
            continue
    logger.error("No compatible model artifact found.")
    return None, {}, False


def predict_with_model(
    model: Any,
    telemetry_window: list[dict[str, float]],
    norm_stats: dict[str, dict[str, float]],
    window_size: int = 12,
) -> float | None:
    """
    Run a single CTGNN forward pass on a telemetry window.

    Args:
        model: loaded CausalAttentionGRU
        telemetry_window: list of metric dicts (length = window_size)
        norm_stats: per-metric mean/std for normalization
        window_size: expected window length

    Returns:
        fault probability in [0, 1], or None on failure
    """
    if not TORCH_AVAILABLE or model is None:
        return None

    if len(telemetry_window) < window_size:
        return None

    try:
        # Build feature tensor [1, window, 6]
        features = []
        for frame in telemetry_window[-window_size:]:
            row = []
            for metric in METRICS:
                val = float(frame.get(metric, 0.0))
                stats = norm_stats.get(metric, {"mean": 0, "std": 1})
                normalized = (val - stats["mean"]) / (stats["std"] + 1e-6)
                row.append(normalized)
            features.append(row)

        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        x = torch.tensor([features], dtype=torch.float32).to(device)  # [1, window, 6]

        with torch.no_grad():
            logits, attention_weights = model(x)
            probability = torch.sigmoid(logits).item()

        return round(probability, 4)

    except Exception as e:
        logger.error(f"CTGNN forward pass failed: {e}")
        return None
