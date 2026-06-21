# NetOracle

NetOracle is a no-Docker, local-first research prototype for federated causal network fault intelligence with telemetry simulation, causal fault prediction, graph localisation, RAG/LLM diagnosis, risk-gated remediation, SQLite-backed stores, user data uploads, benchmark evaluation, Three.js 3D digital twin, adaptive RL policy, Hopfield wireless allocation, optional cloud export, and a custom web interface.

## What Was Implemented

This implementation combines all four team workstreams into one runnable application:

- **Member 1 scope:** synthetic 5G telemetry fabric, fault injection, local setup script, persistent telemetry store, user data upload/ingestion, Colab/T4 training scaffold.
- **Member 2 scope:** causal DAG discovery, federated causal edge voting, causal attention risk prediction, benchmark evaluation suite, pass/fail thresholds.
- **Member 3 scope:** Neo4j-compatible property graph schema implemented locally in SQLite, topology localisation, NL-to-Cypher style querying, Three.js 3D digital twin visualization.
- **Member 4 scope:** RAG incident memory, multi-agent LLM diagnosis wrapper, confidence-weighted voting, risk-gated remediation with RL policy integration, audit log, Hopfield wireless allocation, optional cloud export, polished frontend.

## No-Docker Architecture

The project intentionally avoids Docker. It runs as a single FastAPI server with local managed stores:

```text
Browser UI (2D dashboard + Three.js 3D twin)
   |
FastAPI managed backend
   |
   |-- SQLite telemetry/event store (user upload support)
   |-- SQLite property-graph topology store (user upload support)
   |-- SQLite RAG incident store
   |-- SQLite diagnosis + audit store
   |-- RL policy store (adaptive remediation)
   |-- Optional Ollama local LLM runtime
   |-- Optional Slack webhook escalation
   |-- Optional AWS/Supabase cloud export
```

This keeps the prototype easy to run on Windows while preserving scalable adapter boundaries. Later, each local store can be swapped as follows:

- **SQLite telemetry store -> TimescaleDB, ClickHouse, Kafka, Redpanda, or NATS JetStream**
- **SQLite graph store -> Neo4j, Memgraph, or KuzuDB**
- **Local hash-vector RAG -> FAISS, Qdrant, LanceDB, or Chroma**
- **Local FastAPI workers -> Celery, Dramatiq, Ray Serve, or Temporal workflows**
- **Simulated remediation -> Ryu/ONOS/Kubernetes/Open5GS control hooks**

## Novel Research-Inspired Mechanisms

This prototype includes practical versions of advanced mechanisms inspired by recent network-AI research:

- **Federated causal edge voting:** slices produce causal edges locally; the global graph promotes stable high-confidence edges.
- **Causal-prior temporal risk scoring:** prediction uses causality-inspired feature pathways instead of only physical topology.
- **Graph-grounded diagnosis:** LLM/RAG outputs are grounded in affected infrastructure paths and policies.
- **Multi-agent confidence voting:** diagnosis uses multiple model personas or Ollama models with a confidence-weighted ensemble.
- **Risk-gated remediation:** low-risk/high-confidence actions are simulated automatically; uncertain or high-risk cases escalate.
- **Adaptive RL policy:** contextual bandit learns optimal remediation actions from outcomes.
- **Hopfield wireless allocation:** continuous Hopfield network for sub-channel assignment with fairness metrics.
- **Benchmark evaluation suite:** automated pass/fail testing with ROC-AUC, FPR, and MTTP thresholds.
- **Three.js 3D digital twin:** interactive visualization with fault heatmaps and audit replay.
- **Optional free-tier cloud export:** AWS S3/DynamoDB or Supabase integration.
- **No-Docker scalable local architecture:** the same APIs can scale to proper brokers, graph DBs, vector DBs, and distributed workers later.

Implemented advanced AI/ML features (Member 2):

- **CausalAttentionGRU (CTGNN):** live fault prediction from trained PyTorch model (AUC 0.9236).
- **Split Conformal Prediction:** 90% coverage-guaranteed uncertainty intervals on fault probabilities (Angelopoulos & Bates, 2023).
- **NOTEARS causal discovery:** gradient-based DAG learning (Zheng et al., NeurIPS 2018) with federated edge voting.
- **Live benchmark suite:** ablation study comparing CTGNN vs heuristic vs random baselines.
- **39 unit tests** covering intelligence pipeline and Hopfield wireless allocator.

Recommended future upgrade directions:

- **Temporal Graph Networks / TGAT / DySAT:** for dynamic graph-time prediction.
- **GraphRAG:** combine property-graph neighbourhood retrieval with vector retrieval for root cause analysis.
- **Mixture-of-Experts LLM routing:** route network diagnosis to specialist agents by fault type.
- **Safe RL / constrained MDPs:** use formal safety constraints before executing network actions.
- **Ray Serve or Temporal:** scale prediction/diagnosis/remediation as independent services without Docker dependency.

## Requirements

Install these manually:

- Python 3.10 or 3.11
- Git, optional but recommended
- Ollama, optional for local LLMs

No Node.js and no Docker are required.

## Setup

Open PowerShell in this folder:

```powershell
C:\Users\raddo\Documents\EL main 4th sem\netoracle
```

Run:

```powershell
.\run.ps1
```

The script will:

1. Create `.venv` if missing.
2. Install Python dependencies from `requirements.txt`.
3. Copy `.env.example` to `.env` if missing.
4. Start FastAPI at `http://127.0.0.1:8000`.

Then open:

```text
http://127.0.0.1:8000
```

## Manual Setup Alternative

```powershell
python -m venv .venv
.\.venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
copy .env.example .env
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

## Where To Put API Keys

Create or edit:

```text
netoracle\.env
```

Use this format:

```env
APP_NAME=NetOracle
APP_ENV=development
DATABASE_PATH=./data/netoracle.db

OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODELS=phi3:mini,mistral:7b,llama3.1:8b

SLACK_WEBHOOK_URL=
OPENAI_API_KEY=
GROQ_API_KEY=

CONFIDENCE_THRESHOLD=0.60
REMEDIATION_MODE=simulation

# Optional cloud export (free tier)
CLOUD_PROVIDER=none
AWS_ACCESS_KEY_ID=
AWS_SECRET_ACCESS_KEY=
AWS_REGION=ap-south-1
AWS_S3_BUCKET=
SUPABASE_URL=
SUPABASE_SERVICE_ROLE_KEY=
SUPABASE_BUCKET=netoracle
```

### Required Keys

No API key is required for the basic demo.

### Optional Keys

- **`SLACK_WEBHOOK_URL`:** add this if you want human escalation notifications.
- **`OPENAI_API_KEY`:** reserved for future cloud LLM fallback.
- **`GROQ_API_KEY`:** reserved for future fast cloud LLM fallback.

### Cloud Export Keys (Optional Free Tier)

Set `CLOUD_PROVIDER=aws` or `CLOUD_PROVIDER=supabase` to enable export:

**AWS Free Tier (12 months):**
- `AWS_ACCESS_KEY_ID` + `AWS_SECRET_ACCESS_KEY`: from IAM user
- `AWS_S3_BUCKET`: create in AWS Console (5GB free)
- `AWS_REGION`: e.g., `ap-south-1`, `us-east-1`

**Supabase Free Tier (Unlimited projects):**
- `SUPABASE_URL`: from Project Settings > API
- `SUPABASE_SERVICE_ROLE_KEY`: from Project Settings > API > service_role key
- `SUPABASE_BUCKET`: create in Storage section

### Ollama Models

If you want real local LLM calls instead of the built-in fallback agents, install Ollama and run:

```powershell
ollama pull phi3:mini
ollama pull mistral:7b
ollama pull llama3.1:8b
```

If your laptop has limited RAM, use:

```powershell
ollama pull phi3:mini
```

Then set:

```env
OLLAMA_MODELS=phi3:mini
```

## How To Use The Interface

1. Start the app.
2. Open `http://127.0.0.1:8000`.
3. Choose slice, node, fault type, and severity.
4. Click **Run closed-loop demo**.
5. Watch:
   - telemetry pulse
   - causal DAG
   - topology localisation
   - RAG/LLM diagnosis
   - remediation decision
   - audit trail
6. Ask a graph question such as:
   - `Which VNFs are connected to Slice 1?`
   - `Which policy governs Slice 2?`
   - `Which neighbours are at risk?`

## Useful API Endpoints

- `GET /api/status`
- `POST /api/telemetry/tick`
- `GET /api/telemetry/recent`
- `POST /api/demo/run`
- `POST /api/fault/inject`
- `GET /api/causal-graph`
- `GET /api/topology`
- `POST /api/nl-query`
- `GET /api/alerts`
- `GET /api/audit`
- `GET /api/metrics`
- `GET /api/data/schema` - View telemetry upload schema
- `GET /api/data/mode` - View the active telemetry source and health hints
- `POST /api/data/switch-mode?mode=open5gs` - Switch telemetry source at runtime
- `GET /api/open5gs/health` - View Open5GS Prometheus/MongoDB/NF health
- `WS /ws/telemetry` - Live telemetry tick stream
- `POST /api/data/upload-telemetry` - Upload CSV/JSON telemetry
- `POST /api/data/upload-topology` - Upload JSON topology
- `POST /api/analyse/uploaded-data` - Run analysis on uploaded data
- `POST /api/benchmarks/run` - Run evaluation benchmarks
- `POST /api/wireless/hopfield` - Run Hopfield allocator
- `GET /api/visualization/scene` - Get 3D twin scene data
- `GET /api/visualization/replay` - Get audit replay events
- `GET /api/rl/policy` - View RL policy state
- `POST /api/rl/recommend` - Get RL action recommendation
- `GET /api/cloud/status` - Check cloud export configuration
- `POST /api/cloud/export-audit` - Export audit to cloud
- `POST /api/cloud/export-benchmark` - Export benchmark to cloud

## Open5GS / UERANSIM Integration

NetOracle can stream live Open5GS 5G Core telemetry from WSL2 while the FastAPI app continues to run natively on Windows.

### 1. Install and Start Open5GS in WSL2

Use Ubuntu 22.04 under WSL2. From the repo root mounted in WSL2, run:

```bash
bash scripts/install_open5gs_wsl.sh
```

The installer covers system packages, MongoDB, Open5GS PPA install, Open5GS WebUI, Prometheus/node-exporter, NF metrics config, UERANSIM build, UERANSIM gNB/UE YAML, and service enablement. It configures Open5GS NF Prometheus metrics on:

```text
AMF 9095
SMF 9096
UPF 9097
PCF 9098
Prometheus server 9090
MongoDB 27017
Open5GS WebUI 3000
```

Then start the stack inside WSL2:

```bash
bash scripts/start_open5gs.sh
```

The script starts MongoDB, Open5GS NFs, Prometheus, UERANSIM gNB/UE, registers the test IMSI if missing, and prints the WSL2 IP to use from Windows.

### 2. Configure NetOracle on Windows

Edit `.env`:

```env
DATA_SOURCE_MODE=open5gs
OPEN5GS_PROMETHEUS_URL=http://<wsl2-ip>:9090
OPEN5GS_MONGO_URI=mongodb://<wsl2-ip>:27017
OPEN5GS_WEBUI_URL=http://<wsl2-ip>:3000
OPEN5GS_POLL_INTERVAL_S=5
```

To create or refresh the `wsl.local` hosts entry from an Administrator PowerShell:

```powershell
.\scripts\configure_wsl_bridge.ps1
```

If Open5GS is not reachable, NetOracle still runs and emits `open5gs_simulated` fallback frames with AMF, SMF, UPF, PCF, NRF, and gNB node ids.

### 3. Verify

Start NetOracle, then run:

```powershell
.\.venv\Scripts\python.exe scripts\verify_open5gs_integration.py
```

Useful live checks:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/data/mode
Invoke-RestMethod http://127.0.0.1:8000/api/open5gs/health
Invoke-RestMethod -Method Post http://127.0.0.1:8000/api/telemetry/tick
```

## Data and Datasets

### Built-in Data

No external dataset is required. The app generates its own telemetry and seeds its own incidents/topology.

### User Data Upload

Upload your own network data via the dashboard or API:

**Telemetry CSV/JSON Format:**
```csv
timestamp,slice_id,node_id,node_type,cpu,memory,latency_ms,packet_loss,throughput_mbps,prb_utilization,fault_label,fault_type
2026-05-03T10:00:00Z,slice_1,upf_1,UPF,52,58,24,0.006,860,0.55,0,
```

**Topology JSON Format:**
```json
{
  "nodes": [{"node_id": "upf_1", "node_type": "UPF", "label": "UPF-1"}],
  "edges": [{"source_id": "upf_1", "target_id": "router_1", "relation": "CONNECTS_TO"}]
}
```

Sample files are provided in `data/sample_telemetry.csv` and `data/sample_topology.json`.

Generated locally:

- telemetry frames
- fault labels
- prediction alerts
- topology graph
- historical incident memory
- diagnoses
- remediation decisions
- audit events

Stored in:

```text
netoracle\data\netoracle.db
```

You can delete this file to reset the demo database.

## Project Structure

```text
netoracle/
  app/
    main.py
    database.py
    schemas.py
    settings.py
    services/
      telemetry.py
      intelligence.py
      graph.py
      rag_llm.py
      remediation.py
      ingestion.py          # User data upload
      benchmarks.py         # Evaluation suite
      visualization.py      # 3D twin data
      wireless.py           # Hopfield allocation
      adaptive_rl.py       # RL policy
      cloud_sync.py        # Cloud export
    static/
      index.html
      styles.css
      app.js
      twin.html            # Three.js 3D view
      twin.js
      twin.css
      favicon.svg
  data/
    sample_telemetry.csv
    sample_topology.json
  training/
    train_ctgnn_colab.py  # Colab/T4 training
  reports/               # Benchmark outputs
  exports/               # Cloud export files
  .env.example
  requirements.txt
  requirements-training.txt
  requirements-cloud.txt
  TRAINING.md
  run.ps1
  README.md
```

## Training and Model Development

See [TRAINING.md](TRAINING.md) for detailed Colab/T4 and local CUDA training instructions.

Quick Colab training:
```bash
# In Google Colab with T4 GPU
!pip install torch pandas scikit-learn tqdm
!python train_ctgnn_colab.py --epochs 12 --batch-size 512
```

## Current Limitations

This is a robust academic prototype, not a production telecom control plane.

- Causal discovery is a lightweight PC/PCMCI-inspired implementation; full `causal-learn` integration planned.
- Prediction uses causal attention risk model; trained CTGNN available via separate training script.
- The graph is Neo4j-compatible in schema but stored locally in SQLite for no-Docker execution.
- RAG uses local deterministic embeddings; FAISS/Qdrant can be plugged in later.
- Remediation is intentionally simulated for safety (set `REMEDIATION_MODE=production` with extreme caution).

## Best Next Upgrades

For further research-grade extensions:

1. Replace local graph store with KuzuDB or Neo4j Desktop.
2. Replace hash-vector RAG with FAISS or Qdrant.
3. ~~Integrate trained CTGNN model into live inference pipeline.~~ ✅ Done (Member 2).
4. ~~Add conformal uncertainty calibration before remediation.~~ ✅ Done (Member 2).
5. Add Ray Serve workers for scalable no-Docker distributed inference.
6. Add Open5GS/UERANSIM telemetry as an optional real source.
7. Add Prometheus/Grafana integration for metrics export.
8. Add WebSocket real-time telemetry streaming.
