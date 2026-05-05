"""
NetOracle Member 2 — Complete Colab Training Script (FIXED)
============================================================
Run this ENTIRE file as a single cell in Google Colab (T4 GPU).
After running, execute in a NEW cell:
    from google.colab import files
    files.download('netoracle_artifacts.zip')
"""
import json, math, os, zipfile
from pathlib import Path
from collections import defaultdict
import numpy as np
import pandas as pd
import torch
from torch import nn
from torch.utils.data import DataLoader, TensorDataset
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import train_test_split

METRICS = ["cpu", "memory", "latency_ms", "packet_loss", "throughput_mbps", "prb_utilization"]
OUT_DIR = Path("artifacts"); OUT_DIR.mkdir(exist_ok=True)
DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")
WINDOW, HORIZON, EPOCHS = 12, 20, 12
print(f"Device: {DEVICE}")

class CausalAttentionGRU(nn.Module):
    def __init__(self, feature_dim=6, hidden_dim=96, dropout=0.15):
        super().__init__()
        self.feature_dim, self.hidden_dim = feature_dim, hidden_dim
        self.gru = nn.GRU(feature_dim, hidden_dim, batch_first=True, num_layers=2, dropout=dropout)
        self.attention = nn.MultiheadAttention(hidden_dim, num_heads=4, dropout=dropout, batch_first=True)
        self.norm = nn.LayerNorm(hidden_dim)
        self.head = nn.Sequential(nn.Linear(hidden_dim, hidden_dim // 2), nn.GELU(), nn.Dropout(dropout), nn.Linear(hidden_dim // 2, 1))
    def forward(self, x):
        h, _ = self.gru(x)
        attended, weights = self.attention(h, h, h, need_weights=True)
        z = self.norm(h + attended)
        return self.head(z[:, -1]).squeeze(-1), weights

def generate_synthetic(days=30, nodes=12, step_seconds=15):
    rows = []; total_steps = min(days * 24 * 60 * 4, 45000); fault_every = max(total_steps // 120, 80)
    for t in range(total_steps):
        for node in range(nodes):
            sid = f"slice_{node%3+1}"; nid = ["gnb","upf","router","app"][node%4]+f"_{node%3+1}"
            w = math.sin(t/67)*4; cpu=48+w+np.random.randn()*4; mem=50+np.random.randn()*3
            lat=22+abs(w)+np.random.randn()*2; loss=max(0,0.004+np.random.rand()*0.006)
            thr=860+np.random.randn()*65; prb=max(0.05,min(0.98,0.48+w/100+np.random.randn()*0.04))
            fl = 1 if (t%fault_every in range(0,8) and node in {1,5,9}) else 0; ft=""
            if fl:
                p=(t//fault_every)%5
                if p==0: lat+=70;loss+=0.08;prb+=0.3;thr*=0.65;ft="congestion"
                elif p==1: cpu+=42;lat+=25;ft="cpu_overload"
                elif p==2: loss+=0.14;thr*=0.7;ft="packet_loss"
                elif p==3: mem+=36;cpu+=18;lat+=35;ft="vnf_degradation"
                else: lat+=92;loss+=0.03;ft="latency_spike"
            rows.append({"timestamp":t*step_seconds,"slice_id":sid,"node_id":nid,"cpu":cpu,"memory":mem,"latency_ms":lat,"packet_loss":loss,"throughput_mbps":thr,"prb_utilization":min(prb,0.99),"fault_label":fl,"fault_type":ft})
    return pd.DataFrame(rows)

def build_windows(df):
    xs, ys = [], []
    for _, g in df.groupby(["slice_id","node_id"]):
        g = g.sort_values("timestamp"); v = g[METRICS].astype("float32").values; l = g["fault_label"].fillna(0).astype("float32").values
        if len(g) <= WINDOW+HORIZON: continue
        m=v.mean(0,keepdims=True); s=v.std(0,keepdims=True)+1e-6; v=(v-m)/s
        for i in range(WINDOW, len(g)-HORIZON): xs.append(v[i-WINDOW:i]); ys.append(l[i:i+HORIZON].max())
    return torch.tensor(np.array(xs),dtype=torch.float32), torch.tensor(np.array(ys),dtype=torch.float32)

# === GENERATE & WINDOW ===
print("Generating synthetic telemetry..."); df = generate_synthetic()
print(f"Dataset: {len(df)} rows, {df['fault_label'].sum():.0f} faults")
print("Building windows..."); x, y = build_windows(df)
print(f"Windows: {x.shape[0]} samples")

# === SPLIT: train 60% / cal 20% / test 20% ===
x_tv, x_test, y_tv, y_test = train_test_split(x, y, test_size=0.2, random_state=42, stratify=y if y.sum()>1 else None)
x_train, x_cal, y_train, y_cal = train_test_split(x_tv, y_tv, test_size=0.25, random_state=42, stratify=y_tv if y_tv.sum()>1 else None)
print(f"Train:{len(x_train)} Cal:{len(x_cal)} Test:{len(x_test)}")

train_ld = DataLoader(TensorDataset(x_train,y_train),batch_size=512,shuffle=True,num_workers=2,pin_memory=DEVICE.type=="cuda")
test_ld = DataLoader(TensorDataset(x_test,y_test),batch_size=1024,shuffle=False)
cal_ld = DataLoader(TensorDataset(x_cal,y_cal),batch_size=1024,shuffle=False)

model = CausalAttentionGRU(len(METRICS),96,0.15).to(DEVICE)
opt = torch.optim.AdamW(model.parameters(),lr=3e-4,weight_decay=1e-3)
pw = ((len(y_train)-y_train.sum())/(y_train.sum()+1)).to(DEVICE)
crit = nn.BCEWithLogitsLoss(pos_weight=pw)
scaler = torch.amp.GradScaler(enabled=DEVICE.type=="cuda")

best_auc = 0.0
print(f"\n{'='*60}\nTraining for {EPOCHS} epochs on {DEVICE}\n{'='*60}")
for ep in range(1, EPOCHS+1):
    model.train(); losses=[]
    for xb,yb in train_ld:
        xb,yb=xb.to(DEVICE,non_blocking=True),yb.to(DEVICE,non_blocking=True)
        opt.zero_grad(set_to_none=True)
        with torch.amp.autocast(device_type=DEVICE.type,enabled=DEVICE.type=="cuda"):
            lo,_=model(xb); loss=crit(lo,yb)
        scaler.scale(loss).backward(); scaler.unscale_(opt)
        nn.utils.clip_grad_norm_(model.parameters(),1.0); scaler.step(opt); scaler.update()
        losses.append(loss.item())
    model.eval(); sc,lb=[],[]
    with torch.no_grad():
        for xb,yb in test_ld:
            lo,_=model(xb.to(DEVICE,non_blocking=True))
            sc.extend(torch.sigmoid(lo).cpu().tolist()); lb.extend(yb.tolist())
    try: auc=roc_auc_score(lb,sc)
    except: auc=0.5
    print(f"  Epoch {ep:2d}/{EPOCHS} | loss={sum(losses)/len(losses):.4f} | AUC={auc:.4f}")
    if auc>=best_auc:
        best_auc=auc
        torch.save({"model_state_dict":model.state_dict(),"feature_dim":len(METRICS),"hidden_dim":96,"dropout":0.15,"metrics":METRICS,"window":WINDOW,"horizon":HORIZON,"auc":auc}, OUT_DIR/"ctgnn_t4_best.pt")
print(f"\n✅ Best AUC: {best_auc:.4f}")

# === CONFORMAL PREDICTION ===
print(f"\n{'='*60}\nConformal Prediction calibration\n{'='*60}")
ckpt = torch.load(OUT_DIR/"ctgnn_t4_best.pt", map_location=DEVICE, weights_only=False)
model.load_state_dict(ckpt["model_state_dict"]); model.eval()

cal_p, cal_l = [], []
with torch.no_grad():
    for xb,yb in cal_ld:
        lo,_=model(xb.to(DEVICE,non_blocking=True))
        cal_p.extend(torch.sigmoid(lo).cpu().tolist()); cal_l.extend(yb.tolist())
cal_p, cal_l = np.array(cal_p), np.array(cal_l)
scores = np.abs(cal_l - cal_p); alpha=0.10; n=len(scores)
ql = min(np.ceil((n+1)*(1-alpha))/n, 1.0); q_hat = float(np.quantile(scores, ql))

test_p, test_l = [], []
with torch.no_grad():
    for xb,yb in test_ld:
        lo,_=model(xb.to(DEVICE,non_blocking=True))
        test_p.extend(torch.sigmoid(lo).cpu().tolist()); test_l.extend(yb.tolist())
test_p, test_l = np.array(test_p), np.array(test_l)
cov = sum(1 for p,y in zip(test_p,test_l) if max(0,p-q_hat)<=y<=min(1,p+q_hat))/len(test_l)

conf_data = {"alpha":alpha,"q_hat":q_hat,"n_calibration":n,"coverage_guarantee":f"{(1-alpha)*100:.0f}%","empirical_test_coverage":round(cov,4),"mean_interval_width":round(2*q_hat,4),"cal_scores_sorted":sorted(scores.tolist())}
(OUT_DIR/"conformal_calibration.json").write_text(json.dumps(conf_data,indent=2))
print(f"  q̂={q_hat:.4f} | coverage={cov:.4f} (target≥0.90) | width={2*q_hat:.4f}")

# === NOTEARS ===
print(f"\n{'='*60}\nNOTEARS causal discovery\n{'='*60}")
def notears_linear(X, lambda1=0.1, max_iter=50, h_tol=1e-8, rho_max=1e+16, w_threshold=0.3):
    d=X.shape[1]; n=X.shape[0]
    def _h(W):
        M=W*W; E=np.linalg.matrix_power(np.eye(d)+M/d, d); return np.trace(E)-d
    def _loss(W): R=X-X@W; return 0.5/n*(R**2).sum()
    def _grad(W): R=X-X@W; return -1.0/n*X.T@R
    W=np.zeros((d,d)); rho,ah,h=1.0,0.0,np.inf
    for it in range(max_iter):
        Wo=W.copy()
        for _ in range(300):
            g=_grad(W)+rho*_h(W)*2*W+ah*2*W+lambda1*np.sign(W); W-=1e-3*g; np.fill_diagonal(W,0)
        hn=_h(W)
        if hn>0.25*h: rho*=10
        else: ah+=rho*hn
        h=hn
        if it%10==0: print(f"    iter {it:3d} h={h:.6f} loss={_loss(W):.6f}")
        if h<=h_tol: print(f"    converged iter {it}"); break
        if rho>=rho_max: print(f"    rho_max iter {it}"); break
    W[np.abs(W)<w_threshold]=0; return W

gt_edges=[("cpu","latency_ms"),("memory","latency_ms"),("prb_utilization","latency_ms"),("latency_ms","packet_loss"),("packet_loss","throughput_mbps"),("cpu","throughput_mbps")]
notears_res={}
for sid in ["slice_1","slice_2","slice_3"]:
    sdf=df[df["slice_id"]==sid].head(5000); X=sdf[METRICS].values.astype(np.float64)
    X=(X-X.mean(0))/(X.std(0)+1e-8)
    print(f"\n  --- {sid} ({len(sdf)} samples) ---"); W=notears_linear(X)
    edges=[{"source":METRICS[i],"target":METRICS[j],"weight":round(float(W[i,j]),4)} for i in range(len(METRICS)) for j in range(len(METRICS)) if abs(W[i,j])>0]
    shd=len(set(gt_edges).symmetric_difference(set((e["source"],e["target"]) for e in edges)))
    notears_res[sid]={"adjacency_matrix":W.tolist(),"edges":edges,"n_edges":len(edges),"shd":shd,"metrics_order":METRICS}
    print(f"  {sid}: {len(edges)} edges, SHD={shd}")

aew=defaultdict(list)
for r in notears_res.values():
    for e in r["edges"]: aew[(e["source"],e["target"])].append(abs(e["weight"]))
gl_edges=[{"source":s,"target":t,"support":len(w),"mean_weight":round(float(np.mean(w)),4)} for (s,t),w in aew.items() if len(w)>=2 or np.mean(w)>0.3]
(OUT_DIR/"notears_dag.json").write_text(json.dumps({"algorithm":"NOTEARS","per_slice":notears_res,"global_federated_edges":gl_edges,"ground_truth":[{"source":s,"target":t} for s,t in gt_edges]},indent=2))
print(f"\n✅ NOTEARS: {len(gl_edges)} global edges")

# === NORM STATS ===
ns={m:{"mean":round(float(df[m].mean()),4),"std":round(float(df[m].std()),4)} for m in METRICS}
(OUT_DIR/"norm_stats.json").write_text(json.dumps(ns,indent=2))

# === SUMMARY ===
summary={"model":"CausalAttentionGRU","best_auc":round(best_auc,4),"device":str(DEVICE),"epochs":EPOCHS,"feature_dim":len(METRICS),"hidden_dim":96,"window":WINDOW,"horizon":HORIZON,"total_samples":len(x),"train":len(x_train),"cal":len(x_cal),"test":len(x_test),"conformal_q_hat":q_hat,"conformal_coverage":round(cov,4),"notears_global_edges":len(gl_edges),"test_auc":round(float(roc_auc_score(test_l,test_p)),4)}
(OUT_DIR/"training_summary.json").write_text(json.dumps(summary,indent=2))

# === ZIP ===
with zipfile.ZipFile("netoracle_artifacts.zip","w",zipfile.ZIP_DEFLATED) as zf:
    for f in OUT_DIR.iterdir(): zf.write(f,f"artifacts/{f.name}"); print(f"  Packed: {f.name} ({f.stat().st_size:,}b)")

print(f"\n{'='*60}\n🎉 DONE — download netoracle_artifacts.zip\n{'='*60}")
print(f"  AUC={best_auc:.4f} q̂={q_hat:.4f} coverage={cov:.4f} edges={len(gl_edges)}")
print(f"\n  from google.colab import files")
print(f"  files.download('netoracle_artifacts.zip')")
