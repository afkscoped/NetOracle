from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, File, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.database import db
from app.schemas import DemoRunRequest, FaultInjectionRequest, NaturalLanguageQuery
from app.services.adaptive_rl import adaptive_rl_service
from app.services.benchmarks import benchmark_service
from app.services.cloud_sync import cloud_sync_service
from app.services.graph import graph_service
from app.services.ingestion import ingestion_service
from app.services.intelligence import intelligence_service
from app.services.rag_llm import rag_llm_service
from app.services.remediation import remediation_service
from app.services.telemetry import telemetry_service
from app.services.visualization import visualization_service
from app.services.wireless import wireless_optimizer_service


BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"

app = FastAPI(title="NetOracle", version="1.0.0")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.on_event("startup")
def startup() -> None:
    graph_service.seed()
    rag_llm_service.seed()
    telemetry_service.warm_start(24)


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/twin")
def twin() -> FileResponse:
    return FileResponse(STATIC_DIR / "twin.html")


@app.get("/api/status")
def status() -> dict:
    return {
        "ok": True,
        "name": "NetOracle",
        "mode": "no-docker local-first research prototype",
        "stores": ["SQLite telemetry/event store", "SQLite property graph", "SQLite RAG incident store", "audit log"],
        "architecture": [
            "synthetic 5G telemetry fabric",
            "federated causal edge voting",
            "causal attention risk predictor",
            "Neo4j-compatible property graph localisation",
            "graph-grounded RAG and multi-agent LLM voting",
            "risk-gated remediation",
            "user telemetry ingestion",
            "benchmark evaluation suite",
            "Three.js 3D network digital twin",
            "Hopfield radio allocation",
            "safety-constrained adaptive RL policy",
            "optional free-tier cloud export",
        ],
    }


@app.post("/api/telemetry/tick")
def telemetry_tick() -> dict:
    return {"ok": True, "data": telemetry_service.generate_tick()}


@app.get("/api/telemetry/recent")
def recent_telemetry(limit: int = 180) -> dict:
    return {"ok": True, "data": telemetry_service.recent(limit)}


@app.get("/api/data/schema")
def data_schema() -> dict:
    return {"ok": True, "data": ingestion_service.schema()}


@app.post("/api/data/upload-telemetry")
async def upload_telemetry(file: UploadFile = File(...)) -> dict:
    content = (await file.read()).decode("utf-8")
    return {"ok": True, "data": ingestion_service.ingest_telemetry(content, file.filename or "uploaded")}


@app.post("/api/data/upload-topology")
async def upload_topology(file: UploadFile = File(...)) -> dict:
    content = (await file.read()).decode("utf-8")
    return {"ok": True, "data": ingestion_service.ingest_topology(content, file.filename or "topology.json")}


@app.post("/api/analyse/uploaded-data")
def analyse_uploaded_data() -> dict:
    return {"ok": True, "data": ingestion_service.analyse_uploaded_data()}


@app.post("/api/fault/inject")
def inject_fault(request: FaultInjectionRequest) -> dict:
    fault = request.model_dump()
    frames = telemetry_service.generate_tick(fault)
    alert = intelligence_service.predict_latest()
    graph_context = graph_service.localise(alert) if alert else None
    diagnosis = rag_llm_service.diagnose(alert, graph_context) if alert and graph_context else None
    remediation = remediation_service.decide_and_execute(diagnosis) if diagnosis else None
    return {"ok": True, "data": {"frames": frames, "alert": alert, "graph_context": graph_context, "diagnosis": diagnosis, "remediation": remediation}}


@app.post("/api/demo/run")
def run_demo(request: DemoRunRequest) -> dict:
    for _ in range(max(1, request.ticks - 1)):
        telemetry_service.generate_tick()
    fault = {
        "slice_id": request.slice_id,
        "node_id": request.node_id,
        "fault_type": request.fault_type,
        "severity": request.severity,
    }
    frames = telemetry_service.generate_tick(fault)
    alert = intelligence_service.predict_latest()
    if not alert:
        alert = {
            "alert_id": "manual_low_signal",
            "timestamp": frames[0]["timestamp"],
            "slice_id": request.slice_id,
            "node_id": request.node_id,
            "fault_type": request.fault_type,
            "fault_probability": 0.51,
            "horizon_minutes": 20,
            "top_features": ["latency_ms", "packet_loss", "prb_utilization"],
            "causal_edges_used": [],
            "status": "open",
        }
    graph_context = graph_service.localise(alert)
    diagnosis = rag_llm_service.diagnose(alert, graph_context)
    remediation = remediation_service.decide_and_execute(diagnosis)
    return {"ok": True, "data": {"frames": frames, "alert": alert, "graph_context": graph_context, "diagnosis": diagnosis, "remediation": remediation}}


@app.get("/api/causal-graph")
def causal_graph() -> dict:
    return {"ok": True, "data": intelligence_service.federated_dag()}


@app.get("/api/topology")
def topology() -> dict:
    return {"ok": True, "data": graph_service.topology()}


@app.get("/api/visualization/scene")
def visualization_scene() -> dict:
    return {"ok": True, "data": visualization_service.scene()}


@app.get("/api/visualization/replay")
def visualization_replay(limit: int = 80) -> dict:
    return {"ok": True, "data": visualization_service.replay(limit)}


@app.post("/api/nl-query")
def nl_query(request: NaturalLanguageQuery) -> dict:
    return {"ok": True, "data": graph_service.nl_to_cypher(request.question)}


@app.post("/api/benchmarks/run")
def run_benchmarks(scenarios: int = 60) -> dict:
    return {"ok": True, "data": benchmark_service.run(scenarios)}


@app.post("/api/wireless/hopfield")
def hopfield_allocate(users: int = 8, channels: int = 16, iterations: int = 60) -> dict:
    return {"ok": True, "data": wireless_optimizer_service.hopfield_allocate(users, channels, iterations)}


@app.get("/api/rl/policy")
def rl_policy() -> dict:
    return {"ok": True, "data": adaptive_rl_service.policy()}


@app.post("/api/rl/recommend")
def rl_recommend(payload: dict[str, Any] = Body(default={})) -> dict:
    return {"ok": True, "data": adaptive_rl_service.recommend(
        str(payload.get("fault_type", "congestion")),
        str(payload.get("risk", "low")),
        float(payload.get("probability", 0.7)),
    )}


@app.post("/api/rl/update")
def rl_update(payload: dict[str, Any] = Body(default={})) -> dict:
    return {"ok": True, "data": adaptive_rl_service.update(
        str(payload.get("state", "congestion:low:medium")),
        str(payload.get("action", "scale_vnf")),
        float(payload.get("reward", 0.0)),
    )}


@app.get("/api/cloud/status")
def cloud_status() -> dict:
    return {"ok": True, "data": cloud_sync_service.config_status()}


@app.post("/api/cloud/export-audit")
def cloud_export_audit() -> dict:
    return {"ok": True, "data": cloud_sync_service.export_audit()}


@app.post("/api/cloud/export-benchmark")
def cloud_export_benchmark() -> dict:
    return {"ok": True, "data": cloud_sync_service.export_benchmark()}


@app.get("/api/alerts")
def alerts(limit: int = 20) -> dict:
    return {"ok": True, "data": db.latest_alerts(limit)}


@app.get("/api/audit")
def audit(limit: int = 100) -> dict:
    return {"ok": True, "data": db.audit_entries(limit)}


@app.get("/api/metrics")
def metrics() -> dict:
    return {"ok": True, "data": intelligence_service.metrics()}
