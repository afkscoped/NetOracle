<div align="center">

# 🔮 NetOracle

**AI-Powered 5G Network Operations Centre · Causal Fault Intelligence · Safe RL Remediation**

[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.111-009688?style=flat-square&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![React](https://img.shields.io/badge/React-18-61DAFB?style=flat-square&logo=react&logoColor=black)](https://react.dev)
[![PyTorch](https://img.shields.io/badge/PyTorch-2.x-EE4C2C?style=flat-square&logo=pytorch&logoColor=white)](https://pytorch.org)
[![Tests](https://img.shields.io/badge/Tests-114%20passed-4CAF50?style=flat-square)](tests/)
[![License](https://img.shields.io/badge/License-MIT-blue?style=flat-square)](LICENSE)

</div>

---

## Overview

**NetOracle** is a research-grade, production-architected **Network Operations Centre (NOC)** platform for 5G core networks. It combines real-time telemetry ingestion, causal AI fault prediction, graph-grounded diagnosis, and constraint-safe automated remediation into a single, no-Docker, locally-runnable system.

Built as a 4-member capstone Engineering Lab project at **RV College of Engineering**, NetOracle demonstrates how modern AI/ML techniques — causal discovery, GNNs, RAG, constrained MDPs — can be applied to the critical problem of autonomous 5G network management.

---

## Key Features

| Category | Capability |
|---|---|
| 🔭 **Telemetry** | Live Open5GS 5G Core ingestion via Prometheus + Simulated multi-NF stream |
| 🧠 **Prediction** | CausalAttentionGRU (CTGNN) — AUC **0.9236**, with Split Conformal uncertainty bounds |
| 🕸️ **Graph AI** | NOTEARS causal DAG discovery with federated edge voting across 5G slices |
| 🔍 **Diagnosis** | Multi-agent RAG/LLM ensemble with confidence-weighted voting |
| 🛡️ **Safety** | CMDP-gated remediation — Lagrangian multipliers enforce risk, blast-radius, and downtime constraints |
| 📡 **RL Policy** | Contextual bandit adaptive remediation that learns from outcomes |
| 📶 **Wireless** | Continuous Hopfield Network for sub-channel resource allocation |
| 📊 **Dashboard** | React + Vite real-time NOC dashboard with 8 specialized panels |
| 🌐 **3D Twin** | Three.js interactive digital twin with fault heatmaps and audit replay |
| ☁️ **Cloud** | Optional AWS S3/DynamoDB or Supabase export |

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                   NetOracle System Architecture                  │
├───────────────────────┬─────────────────────────────────────────┤
│   DATA SOURCES        │   INTELLIGENCE PIPELINE                 │
│                       │                                         │
│  Open5GS (WSL2)  ──►  │  Telemetry Ingestion                   │
│  Prometheus      ──►  │       │                                 │
│  Simulation      ──►  │       ▼                                 │
│  CSV Upload      ──►  │  CTGNN Fault Prediction  (AUC 0.9236)  │
│                       │       │                                 │
│   STORAGE             │       ▼                                 │
│                       │  Causal DAG Discovery (NOTEARS)         │
│  SQLite Telemetry     │       │                                 │
│  SQLite Graph         │       ▼                                 │
│  SQLite RAG           │  Graph Localisation (property graph)    │
│  SQLite Audit         │       │                                 │
│  RL Policy Store      │       ▼                                 │
│                       │  Multi-Agent RAG/LLM Diagnosis          │
│   FRONTEND            │       │                                 │
│                       │       ▼                                 │
│  React + Vite    ◄──  │  CMDP Safety Gate (Lagrangian RL)       │
│  WebSocket feed       │       │                                 │
│  Three.js twin        │       ▼                                 │
│  8 NOC panels         │  Remediation → Audit Log                │
└───────────────────────┴─────────────────────────────────────────┘
```

---

## Quickstart

### Prerequisites

- **Python 3.10 or 3.11** (required)
- **Node.js 18+** (required for the React frontend)
- Git (recommended)
- Ollama (optional — for local LLM inference)

### 1. Clone & Setup

```powershell
git clone <repo-url>
cd NetOracle

# One-command setup and launch
.\run.ps1
```

`run.ps1` will automatically:
1. Create `.venv` and install Python dependencies
2. Copy `.env.example` → `.env` if missing
3. Build the React frontend (`npm run build`)
4. Start the FastAPI server at `http://127.0.0.1:8000`

### 2. Open the Dashboard

Navigate to **http://127.0.0.1:8000** in your browser.

### 3. Manual Setup (Alternative)

```powershell
# Python backend
python -m venv .venv
.\.venv\Scripts\activate
pip install --upgrade pip
pip install -r requirements.txt

# React frontend
cd frontend && npm install && npm run build && cd ..

# Start server
copy .env.example .env
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

---

## Configuration

Copy `.env.example` to `.env` and edit as needed:

```env
# Core
APP_NAME=NetOracle
APP_ENV=development
DATABASE_PATH=./data/netoracle.db

# Telemetry source: simulation | open5gs | csv
DATA_SOURCE_MODE=simulation

# Remediation: simulation | production (use production with EXTREME caution)
REMEDIATION_MODE=simulation

# Optional: Ollama local LLM
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODELS=phi3:mini

# Optional: Slack escalation
SLACK_WEBHOOK_URL=

# Optional: Cloud export (free tier)
CLOUD_PROVIDER=none       # aws | supabase | none
AWS_ACCESS_KEY_ID=
AWS_SECRET_ACCESS_KEY=
AWS_REGION=ap-south-1
AWS_S3_BUCKET=
SUPABASE_URL=
SUPABASE_SERVICE_ROLE_KEY=
```

No API key is required for the basic demo — it runs fully offline in simulation mode.

---

## Project Structure

```
NetOracle/
├── app/                          # FastAPI backend
│   ├── main.py                   # App entry point, routes, WebSocket hub
│   ├── database.py               # SQLite abstraction layer
│   ├── schemas.py                # Pydantic request/response models
│   ├── settings.py               # Pydantic settings with .env loading
│   └── services/
│       ├── telemetry.py          # Telemetry generation and persistence
│       ├── intelligence.py       # CTGNN prediction + conformal calibration
│       ├── graph.py              # Property graph topology (Neo4j-compatible)
│       ├── rag_llm.py            # RAG incident memory + LLM diagnosis
│       ├── remediation.py        # Risk-gated remediation engine
│       ├── adaptive_rl.py        # Contextual bandit RL + CMDP safety gate
│       ├── wireless.py           # Hopfield Network sub-channel allocator
│       ├── benchmarks.py         # Automated evaluation suite
│       ├── visualization.py      # 3D digital twin scene data
│       ├── ingestion.py          # CSV/JSON user data upload pipeline
│       ├── open5gs_adapter.py    # Live Open5GS / Prometheus adapter
│       ├── causal_discovery.py   # NOTEARS DAG discovery + federated voting
│       └── cloud_sync.py         # AWS / Supabase cloud export
│
├── frontend/                     # React + Vite NOC dashboard
│   └── src/pages/
│       ├── Dashboard.jsx         # Live telemetry stream + KPI cards
│       ├── CausalAI.jsx          # Causal DAG viewer + prediction panel
│       ├── Topology.jsx          # Interactive graph topology
│       ├── Diagnosis.jsx         # LLM diagnosis + confidence voting
│       ├── WirelessRL.jsx        # Hopfield allocator + RL policy
│       ├── AuditTrail.jsx        # Full audit log with replay
│       ├── DataSources.jsx       # Data upload + mode switching
│       └── ExecutiveProof.jsx    # Benchmark results + evidence
│
├── app/static/                   # Legacy static frontend + Three.js 3D twin
│   ├── index.html / app.js       # Original NOC dashboard
│   └── twin.html / twin.js       # Three.js 3D digital twin
│
├── training/                     # Model training scripts
│   └── train_ctgnn_colab.py      # CTGNN Colab/T4 GPU training
│
├── data/                         # Seed data and sample uploads
├── tests/                        # 114 automated tests (pytest)
├── scripts/                      # Integration and utility scripts
├── monitoring/                   # Prometheus + Grafana config
├── reports/                      # Benchmark output files
├── exports/                      # Cloud export and auto-retrain CSVs
├── .env.example                  # Configuration template
├── requirements.txt              # Python dependencies
├── run.ps1                       # One-click Windows startup script
├── ARCHITECTURE.md               # Deep architecture notes
├── TRAINING.md                   # Model training guide
└── LIVE_OPS_RUNBOOK.md           # Production runbook
```

---

## API Reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/status` | System health and version |
| `POST` | `/api/telemetry/tick` | Trigger one telemetry tick |
| `GET` | `/api/telemetry/recent` | Recent telemetry frames |
| `POST` | `/api/demo/run` | Run full closed-loop demo |
| `POST` | `/api/fault/inject` | Inject a synthetic fault |
| `GET` | `/api/causal-graph` | Causal DAG with edge weights |
| `GET` | `/api/topology` | Network topology graph |
| `POST` | `/api/nl-query` | Natural language graph query |
| `GET` | `/api/alerts` | Active prediction alerts |
| `GET` | `/api/audit` | Full audit trail |
| `GET` | `/api/metrics` | Aggregated performance metrics |
| `POST` | `/api/benchmarks/run` | Run evaluation benchmarks |
| `POST` | `/api/wireless/hopfield` | Hopfield sub-channel allocation |
| `GET` | `/api/rl/policy` | RL policy current state |
| `POST` | `/api/rl/recommend` | Get RL action recommendation |
| `GET` | `/api/visualization/scene` | Three.js 3D twin scene data |
| `GET` | `/api/data/mode` | Active telemetry source info |
| `POST` | `/api/data/switch-mode` | Switch telemetry source at runtime |
| `GET` | `/api/open5gs/health` | Open5GS NF health check |
| `POST` | `/api/data/upload-telemetry` | Upload CSV/JSON telemetry |
| `POST` | `/api/data/upload-topology` | Upload JSON topology |
| `GET` | `/api/cloud/status` | Cloud export configuration |
| `POST` | `/api/cloud/export-audit` | Export audit log to cloud |
| `WS` | `/ws/telemetry` | Live telemetry WebSocket stream |

Interactive API docs: **http://127.0.0.1:8000/docs**

---

## Recent Integration, Fixes & Refinements (v2.8)

Here is a summary of the senior-level network engineering and software architecture updates implemented to make NetOracle fully production-ready and cross-platform stable:

### 🔭 NOC Live Metrics & Inference Stability
* **Exposed Live Inference Risk:** Resolved the issue where the NOC dashboard KPI was stuck at `0%` risk. Tracked the latest computed GNN fault probability in memory (`self.last_probability`) during tick execution and dynamically exposed it inside `/api/metrics` and the WebSocket tick feed.
* **NOC Chart Sizing:** Resized area and line charts from hardcoded CSS constraints to dynamic container widths (`w-full`), ensuring they stretch and adapt across different viewport resolutions.
* **CMDP Button Layout:** Added Flexbox constraints (`flex-shrink: 0`, `white-space: nowrap`) to active remediation control buttons on the Wireless RL page to prevent text wrapping or cropping on narrow viewports.

### 📡 Real-Time 5G Telemetry & Adapter Mappings
* **Host Interface Proxying:** Configured the Prometheus adapter to read packet rates directly from the host virtual device interface (`ogstun`) since the containerized interface (`uesimtun0`) is isolated within WSL's network namespace and invisible to the host node-exporter.
* **UPF Throughput Fallback:** Integrated a fallback mapping to scrape bytes from `ogstun` when native UPF NF metrics return zero, keeping throughput curves responsive.
* **Rolling Cache Refinements:** Redesigned counter delta timing to track timestamps per-key, preventing rate values from shrinking toward zero over time.
* **Verified Schema Queries:** Replaced assumed core metric names with verified Prometheus schemas (`ran_ue`, `pfcp_sessions_active`, `fivegs_ep_n3_gtp_indatapktn3upf`) in pre-flight checks.

### 🌐 UI Navigation & Topology Sizing
* **3D Digital Twin Navigation:** Integrated a direct **3D Digital Twin** link to the navigation bar using the `Globe` icon. Clicking it opens `/twin` in a new tab.
* **Topology Normalization:** Added mapping support to resolve schema differences between backend SQLite graph entities (`source_id`/`target_id`) and frontend properties (`source`/`target`), restoring lost network node connections.
* **ViewBox & Coordinate Dragging:** Expanded the SVG canvas dimensions from `500x360` to `800x500` to prevent label overlaps, and scaled mouse drag delta inputs dynamically to SVG viewBox ratios to align coordinates correctly on zoom.

### 🧪 Advanced Physics & Algorithm Tuning
* **Continuous Lyapunov Decay:** Modified the Hopfield Network optimizer in `wireless.py` to use a continuous-time damped state transition update ($\eta = 0.15$), allowing the allocator to converge smoothly over 45 steps. This creates a realistic exponential Lyapunov minimization curve instead of snapping in a single step.
* **Audit Trail Payload Formatting:** Added detailed serializers for proactive forecasting, RAG indexing, cypher queries, and conformal predictions inside the Audit Trail page.

### 💻 Windows Console UTF-8 Reconfiguration
* **Pre-Flight Checks Unicode Support:** Added standard output and standard error reconfigurations to enforce `utf-8` on Windows terminals, eliminating shell crashes (`UnicodeEncodeError` under `cp1252`) when printing diagnostic checks, tables, and emojis.

---

## Open5GS / UERANSIM Integration

NetOracle can ingest live, real-time 5G Core telemetry from Open5GS and UERANSIM running inside WSL2 (Ubuntu 22.04). Follow this verified startup guide:

### 1. Start Open5GS Core Services (inside WSL2)
Start the MongoDB subscriber store, Prometheus scraper, and the Open5GS control-plane and user-plane network functions:
```bash
# Start MongoDB database
sudo systemctl start mongod

# Start Prometheus metrics engine
sudo systemctl start prometheus

# Start Open5GS network functions
sudo systemctl restart open5gs-nrfd open5gs-amfd open5gs-smfd open5gs-upfd open5gs-pcfd
```

### 2. Register the 5G Subscriber (inside WSL2)
Run the subscriber registration script to register the simulated SIM card in the core's subscriber database:
```bash
mongosh open5gs "/mnt/c/Users/Rishab Nayak/Desktop/Om/RVCE/EL/IV Sem/NetOracle/scripts/register_subscriber.js"
```

### 3. Configure WSL Kernel Routing & NAT NAT Masquerading (inside WSL2)
Allow the virtual subscriber namespace to forward packets through your computer's virtual network interface to reach the internet:
```bash
sudo sysctl -w net.ipv4.ip_forward=1
sudo iptables -t nat -A POSTROUTING -s 10.45.0.0/16 ! -o ogstun -j MASQUERADE
sudo iptables -I FORWARD 1 -i ogstun -j ACCEPT
sudo iptables -I FORWARD 1 -o ogstun -j ACCEPT
```

### 4. Start the UERANSIM gNodeB & UE Simulators (inside WSL2)
Open separate terminal tabs and launch the 5G Base Station (gNodeB) and 5G Phone Simulator (UE):
```bash
# Tab 1: Start gNodeB base station
sudo /home/rishab_nayak/UERANSIM/build/nr-gnb -c /home/rishab_nayak/UERANSIM/config/open5gs-gnb.yaml

# Tab 2: Start UE phone simulator
sudo /home/rishab_nayak/UERANSIM/build/nr-ue -c /home/rishab_nayak/UERANSIM/config/open5gs-ue.yaml
```
*Verify that the UE outputs: `Connection setup for PDU session[1] is successful, TUN interface[uesimtun0, 10.45.0.3] is up`.*

### 5. Launch the Traffic Generator (inside WSL2)
Generate network traffic (internet downloads, pings, multi-user load) to feed metrics to Prometheus:
```bash
sudo ip netns exec ueransim-999700000000001-internet-psi1 python3 "/mnt/c/Users/Rishab Nayak/Desktop/Om/RVCE/EL/IV Sem/NetOracle/scripts/generate_realistic_traffic.py" --interface uesimtun0 --duration 1800
```

### 6. Connect NetOracle (on Windows)
Configure the `.env` file on Windows to connect to your local WSL environment:
```env
DATA_SOURCE_MODE=open5gs
OPEN5GS_PROMETHEUS_URL=http://localhost:9090
OPEN5GS_MONGO_URI=mongodb://localhost:27017
```
Launch the server using `.\run.ps1` or run the verification pre-flight checklist:
```powershell
.venv\Scripts\python.exe scripts/verify_open5gs_integration.py
```

If Open5GS is unreachable or not running, NetOracle automatically falls back to diurnal simulated telemetry frames.

---

## AI/ML Details

### CTGNN — CausalAttentionGRU

Temporal graph neural network trained on synthetic 5G telemetry. Combines:
- **Causal attention** over the NOTEARS-discovered DAG structure
- **Gated recurrent units** for temporal sequence modeling
- **Split Conformal Prediction** for 90%-coverage uncertainty intervals

**Performance:** ROC-AUC 0.9236, FPR < 0.05, MTTP < 10 min

### NOTEARS Causal Discovery

Gradient-based DAG learning (Zheng et al., NeurIPS 2018). Runs per network slice with federated edge voting — edges appearing consistently across ≥2 slices are promoted to the global causal graph.

### CMDP Safety Gate

Constrained MDP with Lagrangian multipliers. Before any remediation action, the gate checks:
- **Risk score** below threshold
- **Blast radius** (affected nodes) below limit
- **Estimated downtime** below limit

Actions failing any constraint are escalated to human operators.

### Hopfield Wireless Allocator

Continuous Hopfield Network optimizing sub-channel assignment across UEs. Minimizes interference while maximizing throughput fairness (Jain's fairness index).

---

## Testing

```powershell
# Run the full 114-test suite
.\.venv\Scripts\python.exe -m pytest tests/ -v

# With coverage
.\.venv\Scripts\python.exe -m pytest tests/ --cov=app --cov-report=term-missing
```

---

## Team

| Member | Scope |
|---|---|
| **Member 1** | Synthetic 5G telemetry fabric, fault injection, setup automation, persistent stores, Colab training scaffold |
| **Member 2** | CTGNN + causal DAG, federated edge voting, conformal prediction, benchmark evaluation suite (39 unit tests, AUC 0.9236) |
| **Member 3** | Neo4j-compatible property graph (SQLite), topology localisation, NL-to-Cypher querying, Three.js 3D digital twin |
| **Member 4** | RAG incident memory, multi-agent LLM diagnosis, confidence voting, CMDP risk-gated remediation, RL policy, Hopfield allocator, cloud export, React NOC dashboard |

---

## Limitations

This is a robust academic prototype, not a production telecom control plane:

- Causal discovery is a lightweight NOTEARS-inspired implementation; full `causal-learn` integration is planned
- The property graph is Neo4j-compatible in schema but stored in SQLite for no-Docker execution
- RAG uses deterministic local embeddings; FAISS/Qdrant can be swapped in
- Remediation is simulated by default (`REMEDIATION_MODE=simulation`)

---

## Upgrade Roadmap

| Priority | Upgrade |
|---|---|
| 🔴 High | Replace SQLite graph → **KuzuDB** or **Neo4j Desktop** |
| 🔴 High | Replace hash-vector RAG → **FAISS** or **Qdrant** |
| 🟡 Medium | Add **Ray Serve** workers for distributed inference |
| 🟡 Medium | Add **Prometheus/Grafana** metrics export |
| 🟢 Low | Add **Temporal Graph Networks** (TGAT/DySAT) for dynamic prediction |
| 🟢 Low | Add **Mixture-of-Experts** LLM routing by fault type |

---

## License

MIT License — see [LICENSE](LICENSE) for details.

---

<div align="center">
  <sub>Built with ❤️ at RV College of Engineering · Engineering Lab IV Semester · 2025–26</sub>
</div>
