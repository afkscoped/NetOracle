# NetOracle: Project Status & Future Roadmap

## 1. What Has Been Implemented Properly So Far
NetOracle is a no-Docker, local-first research prototype for federated causal network fault intelligence. The following components have been fully implemented:
- **No-Docker Architecture:** FastAPI backend with multiple local SQLite stores for telemetry, events, topology, RAG incidents, and audit logs.
- **Frontend Visualization:** Custom web interface featuring a 2D dashboard and a Three.js-based 3D digital twin.
- **Data Ingestion & Simulation:** Synthetic 5G telemetry fabric, fault injection, and support for user data uploads (CSV telemetry, JSON topology).
- **Causal Discovery & Prediction:** Federated causal edge voting (PCMCI-lite + PC-prior) and causal-prior temporal risk scoring.
- **Graph Localisation:** Neo4j-compatible property graph schema implemented locally in SQLite for topology tracking and NL-to-Cypher querying.
- **Multi-Agent Diagnostics:** Graph-grounded RAG incident memory and multi-agent LLM diagnosis wrapper using confidence-weighted voting.
- **Automated Remediation:** Risk-gated simulated remediation with an adaptive Reinforcement Learning (RL) policy (safety-constrained contextual bandit).
- **Wireless Allocation:** Continuous Hopfield network for wireless sub-channel allocation focusing on fairness metrics.
- **Evaluation & Benchmarking:** Automated pass/fail testing suite calculating ROC-AUC, FPR, and MTTP thresholds.
- **Cloud Export:** Optional free-tier cloud export integration for AWS (S3) and Supabase.

## 2. Work Needed From Your End (Training / Cloud / API Keys)
To get the system running with full capabilities, the following manual setup is required:

### API Keys & Environment Variables
Create an `.env` file (copy from `.env.example`) and configure the following:
- **Ollama (Local LLMs):** If using local models, install Ollama and run `ollama pull phi3:mini mistral:7b llama3.1:8b`. Set `OLLAMA_MODELS` accordingly.
- **Cloud LLM Fallbacks:** Set `OPENAI_API_KEY` and/or `GROQ_API_KEY` if you want to use cloud LLMs instead of local ones.
- **Alerts:** Set `SLACK_WEBHOOK_URL` to enable human escalation notifications.
- **Cloud Export (Optional):** To enable cloud exports, set `CLOUD_PROVIDER` to `aws` or `supabase` and provide the respective credentials (e.g., `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`).

### Training the CTGNN Model
Currently, the prediction service uses a heuristic causal attention risk model. To use the deep learning model:
1. Upload and run `training/train_ctgnn_colab.py` on Google Colab (with a free T4 GPU) or run it locally using CUDA.
2. Download the resulting `ctgnn_t4_best.pt` model file.
3. Create an `artifacts/` folder in the project root and place the model inside (`netoracle/artifacts/ctgnn_t4_best.pt`).
4. *Development task:* Update the inference pipeline in `intelligence.py` to load and use this trained model for predictions.

## 3. Future Enhancements based on Novel Research Frameworks
To elevate this project to a state-of-the-art research grade, consider implementing the following novel architectures:
- **Dynamic Graph Representation (TGAT / DySAT):** Replace standard GRUs with Temporal Graph Attention Networks (TGAT) to better capture dynamic topology changes over time.
- **Advanced Causal Discovery (NOTEARS / DAG-GNN):** Move beyond PCMCI-lite to differentiable causal discovery algorithms (like NOTEARS) or DAG-GNN for more rigorous causal structure learning.
- **GraphRAG:** Enhance the current local vector RAG by integrating GraphRAG, which combines property-graph neighbourhood retrieval with vector retrieval, improving root-cause analysis context.
- **Mixture-of-Experts (MoE) LLM Routing:** Instead of a simple fallback, use an MoE router to dynamically route incident logs to specialized agent personas (e.g., Radio Specialist, Core Network Specialist) based on the fault type.
- **Conformal Prediction:** Implement conformal prediction bounds on the risk score to provide statistically rigorous uncertainty calibration before autonomous remediation is triggered.
- **Safe Reinforcement Learning (Constrained MDPs):** Upgrade the contextual bandit RL to Safe RL using Constrained Markov Decision Processes (CMDPs) to guarantee zero-downtime during autonomous actions.

## 4. Work Division & Roadmap for 3 Members
The further work, encompassing testing, running, and incorporating the new functionalities, is split into three independent workflows to be eventually merged into the GitHub repository.

### Member 1: Infrastructure, Data pipelines & Cloud Operations
- **Responsibilities:**
  - Setup and test the Cloud Export functionality (AWS/Supabase) ensuring all audits and benchmarks sync correctly.
  - Implement and test continuous data ingestion streams (e.g., integrating Open5GS/UERANSIM for real telemetry instead of synthetic).
  - Add Prometheus/Grafana integration for live metric tracking.
  - Create comprehensive tests for the `ingestion.py` and `cloud_sync.py` services.
  - Setup CI/CD pipeline (e.g., GitHub Actions) for automated testing.

### Member 2: Advanced AI/ML & Core Analytics
- **Responsibilities:**
  - Integrate the trained CTGNN model from `artifacts/` into the live inference pipeline (`intelligence.py`).
  - Implement Conformal Prediction for uncertainty calibration on the model's outputs.
  - Upgrade the causal discovery module to use NOTEARS or DAG-GNN.
  - Run rigorous testing and tuning of the `benchmarks.py` suite against new model changes.
  - Write test cases for the `intelligence.py` and `wireless.py` (Hopfield) services.

### Member 3: Agentic Systems, Remediation & Frontend UI
- **Responsibilities:**
  - Develop and integrate GraphRAG to improve the context provided to the LLMs.
  - Implement the Mixture-of-Experts (MoE) LLM routing mechanism in `rag_llm.py`.
  - Upgrade the remediation RL policy in `adaptive_rl.py` to use Safe RL / CMDP constraints.
  - Perform end-to-end testing of the Three.js 3D digital twin UI, ensuring visual fidelity during complex multi-agent diagnoses.
  - Write test cases for the `rag_llm.py`, `remediation.py`, and `graph.py` services.
