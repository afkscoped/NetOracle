import argparse
import json
from pathlib import Path

import pandas as pd
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler

FEATURES = ["cpu", "memory", "latency_ms", "packet_loss", "throughput_mbps", "prb_utilization"]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default="data/sample_telemetry.csv")
    parser.add_argument("--epochs", type=int, default=8)
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument("--hidden-dim", type=int, default=128)
    parser.add_argument("--lr", type=float, default=3e-4)
    parser.add_argument("--cpu", action="store_true")
    args = parser.parse_args()
    import torch
    from torch import nn
    from torch.utils.data import DataLoader, TensorDataset

    device = torch.device("cuda" if torch.cuda.is_available() and not args.cpu else "cpu")
    df = pd.read_csv(args.data)
    for col in FEATURES:
        if col not in df.columns:
            df[col] = 0.0
    if "fault_label" not in df.columns:
        df["fault_label"] = 0
    X = df[FEATURES].fillna(0).astype(float).values
    y = df["fault_label"].fillna(0).astype(float).values
    scaler = StandardScaler()
    X = scaler.fit_transform(X)
    stratify = y if len(set(y.tolist())) > 1 else None
    X_train, X_val, y_train, y_val = train_test_split(X, y, test_size=0.2, random_state=42, stratify=stratify)
    train_ds = TensorDataset(torch.tensor(X_train, dtype=torch.float32), torch.tensor(y_train, dtype=torch.float32).unsqueeze(1))
    val_x = torch.tensor(X_val, dtype=torch.float32).to(device)
    val_y = torch.tensor(y_val, dtype=torch.float32).unsqueeze(1).to(device)
    loader = DataLoader(train_ds, batch_size=args.batch_size, shuffle=True)

    class ProactiveMLP(nn.Module):
        def __init__(self, in_dim: int, hidden: int):
            super().__init__()
            self.net = nn.Sequential(
                nn.Linear(in_dim, hidden), nn.LayerNorm(hidden), nn.GELU(), nn.Dropout(0.12),
                nn.Linear(hidden, hidden // 2), nn.GELU(), nn.Linear(hidden // 2, 1),
            )
        def forward(self, x):
            return self.net(x)

    model = ProactiveMLP(len(FEATURES), args.hidden_dim).to(device)
    positives = max(1.0, float(y_train.sum()))
    negatives = max(1.0, float(len(y_train) - y_train.sum()))
    criterion = nn.BCEWithLogitsLoss(pos_weight=torch.tensor([negatives / positives], device=device))
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=1e-4)
    scaler_amp = torch.cuda.amp.GradScaler(enabled=device.type == "cuda")
    best_auc = 0.0
    history = []
    artifact_dir = Path("artifacts/models")
    artifact_dir.mkdir(parents=True, exist_ok=True)
    status_path = Path("artifacts/training_status.json")
    for epoch in range(1, args.epochs + 1):
        model.train()
        total = 0.0
        for xb, yb in loader:
            xb = xb.to(device)
            yb = yb.to(device)
            optimizer.zero_grad(set_to_none=True)
            with torch.cuda.amp.autocast(enabled=device.type == "cuda"):
                logits = model(xb)
                loss = criterion(logits, yb)
            scaler_amp.scale(loss).backward()
            scaler_amp.unscale_(optimizer)
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            scaler_amp.step(optimizer)
            scaler_amp.update()
            total += float(loss.detach().cpu())
        model.eval()
        with torch.no_grad():
            probs = torch.sigmoid(model(val_x)).detach().cpu().numpy().reshape(-1)
        try:
            auc = float(roc_auc_score(y_val, probs)) if len(set(y_val.tolist())) > 1 else 0.5
        except Exception:
            auc = 0.5
        record = {"epoch": epoch, "loss": round(total / max(1, len(loader)), 5), "val_auc": round(auc, 4), "device": str(device)}
        history.append(record)
        status_path.write_text(json.dumps({"status": "running", "latest": record, "history": history[-10:]}, indent=2), encoding="utf-8")
        if auc >= best_auc:
            best_auc = auc
            ckpt = {
                "model_state_dict": model.state_dict(),
                "features": FEATURES,
                "auc": best_auc,
                "scaler_mean": scaler.mean_.tolist(),
                "scaler_scale": scaler.scale_.tolist(),
                "architecture": "ProactiveMLP CUDA fallback trainer for NetOracle V2",
            }
            torch.save(ckpt, artifact_dir / "ctgnn_best.pt")
            # Also save to primary inference path so it becomes the active model
            primary = Path("artifacts/ctgnn_t4_best.pt")
            primary.parent.mkdir(parents=True, exist_ok=True)
            torch.save(ckpt, primary)
    summary = {"status": "completed", "best_auc": round(best_auc, 4), "device": str(device), "epochs": args.epochs, "history": history, "artifact": str(artifact_dir / "ctgnn_best.pt")}
    Path("artifacts/training_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    status_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
