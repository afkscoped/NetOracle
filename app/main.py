import asyncio
import os
from contextlib import asynccontextmanager, suppress
from pathlib import Path
import time
from typing import Any

from fastapi import Body, FastAPI, File, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from prometheus_fastapi_instrumentator import Instrumentator
import mimetypes

mimetypes.add_type("application/javascript", ".js")
mimetypes.add_type("text/css", ".css")

from app.database import db
from app.schemas import DemoRunRequest, FaultInjectionRequest, NaturalLanguageQuery
from app.settings import get_settings
from app.services.adaptive_rl import adaptive_rl_service
from app.services.benchmarks import benchmark_service
from app.services.cloud_sync import cloud_sync_service
from app.services.data_sources import get_adapter, reset_adapter
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


class TelemetryConnectionManager:
    def __init__(self) -> None:
        self.active_connections: set[WebSocket] = set()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self.active_connections.add(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        self.active_connections.discard(websocket)

    async def broadcast(self, payload: dict[str, Any]) -> None:
        stale = []
        for websocket in self.active_connections:
            try:
                await websocket.send_json(payload)
            except Exception:
                stale.append(websocket)
        for websocket in stale:
            self.disconnect(websocket)


manager = TelemetryConnectionManager()


async def auto_tick() -> None:
    """
    Background task: generates one telemetry tick every POLL_INTERVAL seconds.
    Uses the configured data source adapter (simulation/csv/prometheus/open5gs).
    Broadcasts live frames to all connected WebSocket clients.
    """
    adapter = get_adapter()
    settings = get_settings()
    logger.info(f"[AutoTick] Starting with adapter: {adapter.__class__.__name__}")

    while True:
        await asyncio.sleep(max(1, settings.open5gs_poll_interval_s))
        try:
            # Get frames from the configured source
            frames = telemetry_service.generate_tick()

            # Run intelligence prediction on latest frames
            alert = intelligence_service.predict_latest()

            # Update graph node risk from predictions
            if alert and hasattr(graph_service, 'update_node_risk'):
                for frame in frames:
                    if frame.get("fault_label"):
                        prob = alert.get("fault_probability", 0.5)
                        graph_service.update_node_risk(frame["node_id"], prob)

            # Broadcast to all connected WS clients
            await manager.broadcast({
                "type": "tick",
                "frames": frames,
                "alert": alert,
                "source": frames[0].get("source", "unknown") if frames else "unknown",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })

        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"[AutoTick] Error: {e}", exc_info=True)
            continue


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup logic
    graph_service.seed()
    rag_llm_service.seed()
    telemetry_service.warm_start(24)
    task = asyncio.create_task(auto_tick())
    try:
        yield
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task

app = FastAPI(title="NetOracle", version="1.0.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

Instrumentator().instrument(app).expose(app)




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


@app.get("/api/data/mode")
async def get_data_mode():
    """Returns current data source mode and status."""
    adapter = get_adapter()
    info = adapter.get_source_info()
    return info


@app.get("/api/open5gs/health")
async def get_open5gs_health():
    """Returns Open5GS NF health status. Only meaningful in open5gs mode."""
    adapter = get_adapter()
    if hasattr(adapter, 'get_nf_health'):
        return adapter.get_nf_health()
    return {
        "mode": adapter.get_source_info().get("mode"),
        "message": "Open5GS adapter not active. Set DATA_SOURCE_MODE=open5gs."
    }


@app.post("/api/data/switch-mode")
async def switch_data_mode(mode: str):
    """
    Switch data source mode at runtime without restarting.
    Valid modes: simulation | csv_stream | prometheus | open5gs | upload
    """
    import os
    from app.services.data_sources import reset_adapter
    os.environ["DATA_SOURCE_MODE"] = mode
    reset_adapter()
    new_adapter = get_adapter()
    return {
        "status": "switched",
        "mode": mode,
        "adapter": new_adapter.__class__.__name__,
    }


@app.websocket("/ws/telemetry")
async def telemetry_websocket(websocket: WebSocket) -> None:
    await manager.connect(websocket)
    try:
        frames = telemetry_service.generate_tick()
        await websocket.send_json({
            "type": "tick",
            "frames": frames,
            "alert": intelligence_service.predict_latest(),
            "source": frames[0].get("source", "unknown") if frames else "unknown",
            "timestamp": frames[-1]["timestamp"] if frames else None,
        })
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)


@app.post("/api/data/upload-telemetry")
async def upload_telemetry(file: UploadFile = File(...)) -> dict:
    content = (await file.read()).decode("utf-8")
    return {"ok": True, "data": ingestion_service.ingest_telemetry(content, file.filename or "uploaded")}


@app.post("/api/telemetry/stream")
def stream_telemetry(payload: dict[str, Any] = Body(...)) -> dict:
    return {"ok": True, "data": ingestion_service.ingest_telemetry_stream(payload)}


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
    if diagnosis:
        diagnosis["node_id"] = alert.get("node_id") if alert else None
        
    remediation = remediation_service.decide_and_execute(diagnosis) if diagnosis else None
    
    return {
        "ok": True, 
        "data": {
            "frames": frames, 
            "alert": alert, 
            "graph_context": graph_context, 
            "diagnosis": diagnosis, 
            "remediation": remediation
        }
    }


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
    if not alert or alert.get("node_id") != request.node_id or alert.get("slice_id") != request.slice_id:
        alert = {
            "alert_id": f"manual_{int(time.time())}",
            "timestamp": frames[-1]["timestamp"],
            "slice_id": request.slice_id,
            "node_id": request.node_id,
            "fault_type": request.fault_type,
            "fault_probability": 0.51,
            "horizon_minutes": 20,
            "top_features": ["latency_ms", "packet_loss", "prb_utilization"],
            "causal_edges_used": [],
            "status": "open",
        }
    # Ensure diagnosis and remediation run for ALL alerts (predicted or manual fallback)
    graph_context = graph_service.localise(alert)
    diagnosis = rag_llm_service.diagnose(alert, graph_context)
    if diagnosis:
        diagnosis["node_id"] = alert.get("node_id") # Explicitly propagate node_id
        
    remediation = remediation_service.decide_and_execute(diagnosis) if diagnosis else None
    
    return {"ok": True, "data": {"frames": frames, "alert": alert, "graph_context": graph_context, "diagnosis": diagnosis, "remediation": remediation}}


@app.get("/api/causal-graph")
def causal_graph() -> dict:
    return {"ok": True, "data": intelligence_service.federated_dag()}


@app.get("/api/topology")
def topology() -> dict:
    return {"ok": True, "data": graph_service.topology()}


@app.get("/api/graph/neighbourhood/{node_id}")
def graph_neighbourhood(node_id: str, depth: int = 2) -> dict:
    """Return the k-hop neighbourhood of a node (GraphRAG debug endpoint)."""
    return {"ok": True, "data": graph_service.get_node_neighbourhood(node_id, depth=min(depth, 4))}


@app.post("/api/graph/extract")
def graph_extract(payload: dict[str, Any] = Body(...)) -> dict:
    """
    Extract entities/relationships from unstructured text and ingest into the graph.
    Accepts: {"text": "...incident description or log..."}
    """
    text = payload.get("text", "")
    if not text:
        return {"ok": False, "error": "Field 'text' is required"}
    extracted = graph_service.extract_graph_data(text)
    ingestion_result = graph_service.ingest_extracted_relationships(extracted)
    return {
        "ok": True,
        "data": {
            "extracted": extracted.model_dump(),
            "ingestion": ingestion_result,
        },
    }


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
    # Pop known keys to avoid duplicate argument errors in service call
    fault_type = str(payload.pop("fault_type", "congestion"))
    risk = str(payload.pop("risk", "low"))
    probability = float(payload.pop("probability", 0.7))
    conformal_risk_score = float(payload.pop("conformal_risk_score", 0.0))
    
    return {"ok": True, "data": adaptive_rl_service.recommend(
        fault_type,
        risk=risk,
        probability=probability,
        conformal_risk_score=conformal_risk_score,
        **payload
    )}


@app.post("/api/rl/update")
def rl_update(payload: dict[str, Any] = Body(default={})) -> dict:
    return {"ok": True, "data": adaptive_rl_service.update(
        str(payload.get("state", "congestion:low:medium")),
        str(payload.get("action", "scale_vnf")),
        float(payload.get("reward", 0.0)),
        cost=float(payload.get("cost", 0.0)),
    )}


@app.post("/api/rl/train-episode")
def rl_train_episode(payload: dict[str, Any] = Body(default={})) -> dict:
    """Run simulated CMDP training episodes to improve the safety-constrained policy."""
    return {"ok": True, "data": adaptive_rl_service.train_episode(
        episodes=int(payload.get("episodes", 5)),
        max_steps=int(payload.get("max_steps", 15)),
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
