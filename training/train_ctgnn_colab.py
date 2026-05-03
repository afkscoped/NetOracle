import argparse
import json
import math
from pathlib import Path

import pandas as pd
import torch
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import train_test_split
from torch import nn
from torch.cuda.amp import GradScaler, autocast
from torch.utils.data import DataLoader, TensorDataset
from tqdm import tqdm


METRICS = ["cpu", "memory", "latency_ms", "packet_loss", "throughput_mbps", "prb_utilization"]


class CausalAttentionGRU(nn.Module):
    def __init__(self, feature_dim: int, hidden_dim: int = 96, dropout: float = 0.15):
        super().__init__()
        self.gru = nn.GRU(feature_dim, hidden_dim, batch_first=True, num_layers=2, dropout=dropout)
        self.attention = nn.MultiheadAttention(hidden_dim, num_heads=4, dropout=dropout, batch_first=True)
        self.norm = nn.LayerNorm(hidden_dim)
        self.head = nn.Sequential(
            nn.Linear(hidden_dim, hidden_dim // 2),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_dim // 2, 1),
        )

    def forward(self, x):
        h, _ = self.gru(x)
        attended, weights = self.attention(h, h, h, need_weights=True)
        z = self.norm(h + attended)
        logits = self.head(z[:, -1]).squeeze(-1)
        return logits, weights


def generate_synthetic(days: int = 30, nodes: int = 12, step_seconds: int = 15) -> pd.DataFrame:
    rows = []
    total_steps = min(days * 24 * 60 * 4, 45000)
    fault_every = max(total_steps // 120, 80)
    for t in range(total_steps):
        for node in range(nodes):
            slice_id = f"slice_{node % 3 + 1}"
            node_id = ["gnb", "upf", "router", "app"][node % 4] + f"_{node % 3 + 1}"
            wave = math.sin(t / 67) * 4
            cpu = 48 + wave + torch.randn(1).item() * 4
            memory = 50 + torch.randn(1).item() * 3
            latency = 22 + abs(wave) + torch.randn(1).item() * 2
            loss = max(0, 0.004 + torch.rand(1).item() * 0.006)
            throughput = 860 + torch.randn(1).item() * 65
            prb = max(0.05, min(0.98, 0.48 + wave / 100 + torch.randn(1).item() * 0.04))
            fault_label = 1 if (t % fault_every in range(0, 8) and node in {1, 5, 9}) else 0
            fault_type = ""
            if fault_label:
                pattern = (t // fault_every) % 5
                if pattern == 0:
                    latency += 70; loss += 0.08; prb += 0.3; throughput *= 0.65; fault_type = "congestion"
                elif pattern == 1:
                    cpu += 42; latency += 25; fault_type = "cpu_overload"
                elif pattern == 2:
                    loss += 0.14; throughput *= 0.7; fault_type = "packet_loss"
                elif pattern == 3:
                    memory += 36; cpu += 18; latency += 35; fault_type = "vnf_degradation"
                else:
                    latency += 92; loss += 0.03; fault_type = "latency_spike"
            rows.append({
                "timestamp": t * step_seconds,
                "slice_id": slice_id,
                "node_id": node_id,
                "cpu": cpu,
                "memory": memory,
                "latency_ms": latency,
                "packet_loss": loss,
                "throughput_mbps": throughput,
                "prb_utilization": min(prb, 0.99),
                "fault_label": fault_label,
                "fault_type": fault_type,
            })
    return pd.DataFrame(rows)


def load_data(path: str | None) -> pd.DataFrame:
    if path and Path(path).exists():
        if path.endswith(".json"):
            return pd.read_json(path)
        return pd.read_csv(path)
    return generate_synthetic()


def build_windows(df: pd.DataFrame, window: int, horizon: int):
    df = df.copy()
    for metric in METRICS:
        if metric not in df:
            df[metric] = 0.0
    xs, ys = [], []
    for _, group in df.groupby(["slice_id", "node_id"]):
        group = group.sort_values("timestamp")
        values = group[METRICS].astype("float32").values
        labels = group["fault_label"].fillna(0).astype("float32").values
        if len(group) <= window + horizon:
            continue
        mean = values.mean(axis=0, keepdims=True)
        std = values.std(axis=0, keepdims=True) + 1e-6
        values = (values - mean) / std
        for idx in range(window, len(group) - horizon):
            xs.append(values[idx - window:idx])
            ys.append(labels[idx:idx + horizon].max())
    return torch.tensor(xs, dtype=torch.float32), torch.tensor(ys, dtype=torch.float32)


def train(args):
    device = torch.device("cuda" if torch.cuda.is_available() and not args.cpu else "cpu")
    torch.backends.cudnn.benchmark = True
    df = load_data(args.data)
    x, y = build_windows(df, args.window, args.horizon)
    x_train, x_test, y_train, y_test = train_test_split(x, y, test_size=0.2, random_state=42, stratify=y if y.sum() > 1 else None)
    train_loader = DataLoader(TensorDataset(x_train, y_train), batch_size=args.batch_size, shuffle=True, num_workers=2, pin_memory=device.type == "cuda")
    test_loader = DataLoader(TensorDataset(x_test, y_test), batch_size=args.batch_size * 2, shuffle=False, num_workers=2, pin_memory=device.type == "cuda")
    model = CausalAttentionGRU(feature_dim=len(METRICS), hidden_dim=args.hidden_dim, dropout=args.dropout).to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=1e-3)
    pos_weight = ((len(y_train) - y_train.sum()) / (y_train.sum() + 1)).to(device)
    criterion = nn.BCEWithLogitsLoss(pos_weight=pos_weight)
    scaler = GradScaler(enabled=device.type == "cuda")
    best_auc = 0.0
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for epoch in range(1, args.epochs + 1):
        model.train()
        losses = []
        for xb, yb in tqdm(train_loader, desc=f"epoch {epoch}"):
            xb = xb.to(device, non_blocking=True)
            yb = yb.to(device, non_blocking=True)
            optimizer.zero_grad(set_to_none=True)
            with autocast(enabled=device.type == "cuda"):
                logits, _ = model(xb)
                loss = criterion(logits, yb)
            scaler.scale(loss).backward()
            scaler.unscale_(optimizer)
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            scaler.step(optimizer)
            scaler.update()
            losses.append(loss.item())
        auc, val_loss = evaluate(model, test_loader, criterion, device)
        print(json.dumps({"epoch": epoch, "train_loss": sum(losses) / len(losses), "val_loss": val_loss, "auc": auc, "device": str(device)}))
        if auc >= best_auc:
            best_auc = auc
            torch.save({"model_state_dict": model.state_dict(), "metrics": METRICS, "window": args.window, "horizon": args.horizon, "auc": auc}, out_dir / "ctgnn_t4_best.pt")
    (out_dir / "training_summary.json").write_text(json.dumps({"best_auc": best_auc, "device": str(device), "samples": len(x)}, indent=2), encoding="utf-8")


def evaluate(model, loader, criterion, device):
    model.eval()
    scores, labels, losses = [], [], []
    with torch.no_grad():
        for xb, yb in loader:
            xb = xb.to(device, non_blocking=True)
            yb = yb.to(device, non_blocking=True)
            logits, _ = model(xb)
            losses.append(criterion(logits, yb).item())
            scores.extend(torch.sigmoid(logits).detach().cpu().tolist())
            labels.extend(yb.detach().cpu().tolist())
    try:
        auc = float(roc_auc_score(labels, scores))
    except ValueError:
        auc = 0.5
    return round(auc, 4), round(sum(losses) / max(len(losses), 1), 4)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default=None)
    parser.add_argument("--out-dir", default="artifacts")
    parser.add_argument("--window", type=int, default=12)
    parser.add_argument("--horizon", type=int, default=20)
    parser.add_argument("--epochs", type=int, default=8)
    parser.add_argument("--batch-size", type=int, default=512)
    parser.add_argument("--hidden-dim", type=int, default=96)
    parser.add_argument("--dropout", type=float, default=0.15)
    parser.add_argument("--lr", type=float, default=3e-4)
    parser.add_argument("--cpu", action="store_true")
    train(parser.parse_args())
