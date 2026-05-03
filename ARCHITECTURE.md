# NetOracle No-Docker Architecture

NetOracle is implemented as a local-first modular monolith: one managed FastAPI backend serves the UI and coordinates independent backend modules through explicit JSON contracts.

## Runtime

```text
FastAPI app
  |-- Telemetry service
  |-- Intelligence service
  |-- Graph service
  |-- RAG/LLM service
  |-- Remediation service
  |-- SQLite persistence layer
  |-- Static frontend
```

## Why This Replaces Docker

Instead of running Kafka, Neo4j, vector DB, workers, and frontend containers, the project uses embedded local equivalents:

- **Kafka replacement:** direct event persistence and API-triggered ticks.
- **Neo4j replacement:** SQLite property-graph tables with Neo4j-compatible node/edge concepts.
- **Vector DB replacement:** deterministic local embeddings stored in SQLite.
- **Worker replacement:** managed FastAPI orchestration functions.
- **Frontend server replacement:** FastAPI serves static HTML/CSS/JS.

## Scaling Path Without Docker

If the team wants to scale while still avoiding Docker:

- Use **KuzuDB** or **Memgraph installed locally** for graph queries.
- Use **NATS JetStream** or **Redis Streams** installed natively for event streaming.
- Use **Ray** or **Dramatiq** for background workers.
- Use **DuckDB/Parquet** for telemetry analytics.
- Use **LanceDB/Qdrant local binary** for vector retrieval.
- Use **Supervisor/NSSM/Windows Task Scheduler** to run services as managed processes.

## Closed-Loop Flow

```text
Fault injection
  -> telemetry frames
  -> causal DAG and risk prediction
  -> alert JSON
  -> topology localisation
  -> RAG retrieval
  -> multi-agent diagnosis
  -> remediation/escalation
  -> audit log
```

## Safety Model

The remediation layer uses two gates:

1. **Confidence gate:** diagnosis confidence must exceed `CONFIDENCE_THRESHOLD`.
2. **Risk gate:** action must be classified as low-risk.

If either gate fails, the system escalates to a human operator instead of executing the action.
