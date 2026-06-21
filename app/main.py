import asyncio
import json
import logging
import os
import uuid
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timezone
from pathlib import Path
import time
from typing import Any
 
logger = logging.getLogger(__name__)

from fastapi import Body, Depends, FastAPI, File, HTTPException, Query, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from prometheus_fastapi_instrumentator import Instrumentator
import mimetypes

mimetypes.add_type("application/javascript", ".js")
mimetypes.add_type("text/css", ".css")

from app.auth import require_write_auth
from app.database import db
from app.schemas import DemoRunRequest, FaultInjectionRequest, NaturalLanguageQuery
from app.settings import get_settings
from app.services.adaptive_rl import adaptive_rl_service
from app.services.benchmarks import benchmark_service
from app.services.cloud_sync import cloud_sync_service
from app.services.data_harmonizer import harmonizer_service
from app.services.data_sources import get_adapter, reset_adapter
from app.services.explainability import explainability_service
from app.services.graph import graph_service
from app.services.ingestion import ingestion_service
from app.services.intelligence import intelligence_service
from app.services.proactive_engine import proactive_engine
from app.services.rag_llm import rag_llm_service
from app.services.realtime_engine import realtime_engine
from app.services.remediation import remediation_service
from app.services.telemetry import telemetry_service
from app.services.training_pipeline import training_pipeline_service
from app.services.visualization import visualization_service
from app.services.wireless import wireless_optimizer_service
from app.services.xai import xai_service
from scripts.generate_realistic_data import generate_realistic_rows, write_csv

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"

# ─── Background Job Registry ────────────────────────────────────────────────
# In-memory job store for long-running tasks (benchmarks, training).
_jobs: dict[str, dict[str, Any]] = {}


def _do_export_retrain(limit: int = 5000, epochs: int = 5) -> dict:
    """
    Stub for the auto-retrain pipeline.
    Exports the latest `limit` telemetry frames to a CSV in exports/
    and logs the retrain trigger.  Full GPU-accelerated retrain runs
    via colab_train.py / training/train_ctgnn_colab.py.
    """
    import csv
    import os

    os.makedirs("exports", exist_ok=True)
    rows = db.fetch_all(
        f"SELECT * FROM telemetry ORDER BY id DESC LIMIT {int(limit)}"
    )
    export_path = f"exports/auto_retrain_export_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.csv"
    if rows:
        with open(export_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)
    logger.info(
        f"[AutoRetrain] Exported {len(rows)} rows → {export_path}  "
        f"(epochs={epochs}, full retrain: run colab_train.py)"
    )
    return {"exported": len(rows), "path": export_path, "epochs_requested": epochs}


def _new_job(label: str) -> str:
    job_id = str(uuid.uuid4())[:8]
    _jobs[job_id] = {
        "job_id": job_id, "label": label, "status": "queued",
        "result": None, "error": None,
        "started_at": datetime.now(timezone.utc).isoformat(), "completed_at": None,
    }
    return job_id


async def _run_job(job_id: str, fn, *args, **kwargs) -> None:
    """Execute sync fn in a thread pool; update job state on finish."""
    _jobs[job_id]["status"] = "running"
    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, lambda: fn(*args, **kwargs))
        _jobs[job_id].update({"status": "done", "result": result})
    except Exception as exc:
        _jobs[job_id].update({"status": "error", "error": str(exc)})
        logger.error(f"[Job {job_id}] failed: {exc}", exc_info=True)
    finally:
        _jobs[job_id]["completed_at"] = datetime.now(timezone.utc).isoformat()


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

    # Initialize telemetry counter for auto-retrain trigger
    try:
        res = db.fetch_one("SELECT COUNT(*) as count FROM telemetry")
        previous_count = res.get("count", 0) if res else 0
    except Exception:
        previous_count = 0

    while True:
        await asyncio.sleep(max(1, settings.open5gs_poll_interval_s))
        try:
            # Get frames from the configured source
            frames = telemetry_service.generate_tick()

            # Auto-retrain trigger: when count crosses a 500-frame threshold
            try:
                res = db.fetch_one("SELECT COUNT(*) as count FROM telemetry")
                current_count = res.get("count", 0) if res else 0
                if previous_count > 0 and (current_count // 500) > (previous_count // 500):
                    logger.info(f"[AutoRetrain] Telemetry count crossed 500-frame threshold ({previous_count} -> {current_count}). Auto-triggering retrain...")
                    job_id = _new_job("auto_export_retrain(limit=5000)")
                    # Pass limit/epochs as keyword args — NOT as a dict positional arg
                    asyncio.create_task(_run_job(job_id, _do_export_retrain, limit=5000, epochs=5))
                previous_count = current_count
            except Exception as e:
                logger.error(f"[AutoRetrain] Error checking trigger: {e}")

            # Run intelligence prediction on latest frames
            alert = intelligence_service.predict_latest()
            proactive = proactive_engine.latest()
            realtime = realtime_engine.analyse_once(generate_tick=False, run_diagnosis=False)

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
                "proactive": proactive,
                "realtime": realtime,
                "metrics": intelligence_service.metrics(),
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

from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="NetOracle", version="1.0.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# ─── CORS ────────────────────────────────────────────────────────────────────
# Must be added BEFORE any route handler.
# Allows the React/Vite dev server and the embedded dashboard to call the API
# from any origin without 405 preflight errors.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,  # must be False when allow_origins=["*"]
    allow_methods=["*"],
    allow_headers=["*"],
)

Instrumentator().instrument(app).expose(app)




@app.get("/")
def index() -> FileResponse:
    react_index = STATIC_DIR / "react-dist" / "index.html"
    if react_index.exists():
        return FileResponse(react_index)
    return FileResponse(STATIC_DIR / "index.html")



@app.get("/twin")
def twin() -> FileResponse:
    return FileResponse(STATIC_DIR / "twin.html")


@app.get("/health", tags=["ops"])
def health() -> dict:
    """Liveness probe — returns 200 if the process is running."""
    return {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}


@app.get("/ready", tags=["ops"])
def ready() -> dict:
    """Readiness probe — checks DB writability, model load, conformal calibration."""
    checks: dict[str, bool] = {}
    # DB check
    try:
        db.audit_entries(1)
        checks["db"] = True
    except Exception:
        checks["db"] = False
    # Model check
    checks["model_loaded"] = bool(intelligence_service._model_loaded)
    # Conformal check
    checks["conformal_calibrated"] = bool(intelligence_service._conformal.is_calibrated)
    all_ready = all(checks.values())
    return {
        "status": "ready" if all_ready else "degraded",
        "checks": checks,
        "model": "CTGNN" if checks["model_loaded"] else "heuristic_fallback",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/api/jobs/{job_id}", tags=["ops"])
def job_status(job_id: str) -> dict:
    """Poll status of a background job (benchmark run, training, export-retrain)."""
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found. It may have expired.")
    return {"ok": True, "data": job}


@app.get("/api/jobs", tags=["ops"])
def list_jobs() -> dict:
    """List all active/recent background jobs."""
    return {"ok": True, "data": list(_jobs.values())}


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
    return {"ok": True, "data": info}


@app.get("/api/open5gs/health")
async def get_open5gs_health():
    """Returns Open5GS NF health for the configured core adapter if DATA_SOURCE_MODE=open5gs."""
    adapter = get_adapter()
    if hasattr(adapter, 'get_nf_health'):
        return {"ok": True, "data": adapter.get_nf_health()}
    return {"ok": True, "data": {
        "mode": adapter.get_source_info().get("mode"),
        "message": "Open5GS adapter not active. Set DATA_SOURCE_MODE=open5gs."
    }}


@app.get("/api/open5gs-demo/health")
def open5gs_demo_health() -> dict:
    from app.services.open5gs_adapter import Open5GSAdapter
    settings = get_settings()
    adapter = Open5GSAdapter(settings.open5gs_prometheus_url, settings.open5gs_mongo_uri)
    return {"ok": True, "data": {"mode": "open5gs_demo_addon", "core_data_source_unchanged": get_adapter().get_source_info(), **adapter.get_nf_health()}}


@app.post("/api/open5gs-demo/analyse")
def open5gs_demo_analyse(payload: dict[str, Any] = Body(default={})) -> dict:
    return {"ok": True, "data": realtime_engine.open5gs_demo_tick(ingest=bool(payload.get("ingest", True)))}


@app.post("/api/data/switch-mode")
async def switch_data_mode(mode: str):
    """
    Switch data source mode at runtime without restarting.
    Valid modes: simulation | csv_stream | prometheus | open5gs | upload
    """
    valid_modes = {"simulation", "csv_stream", "prometheus", "open5gs", "upload"}
    if mode not in valid_modes:
        raise HTTPException(status_code=400, detail=f"Invalid mode '{mode}'. Valid modes: {sorted(valid_modes)}")
    import os
    from app.services.data_sources import reset_adapter
    os.environ["DATA_SOURCE_MODE"] = mode
    # Clear the @lru_cache so get_settings() returns a fresh Settings object
    # reflecting the new DATA_SOURCE_MODE env var on the next call.
    get_settings.cache_clear()
    reset_adapter()
    new_adapter = get_adapter()
    return {"ok": True, "data": {
        "status": "switched",
        "mode": mode,
        "adapter": new_adapter.__class__.__name__,
    }}


@app.websocket("/ws/telemetry")
async def telemetry_websocket(websocket: WebSocket) -> None:
    await manager.connect(websocket)
    try:
        frames = telemetry_service.generate_tick()
        await websocket.send_json({
            "type": "tick",
            "frames": frames,
            "alert": intelligence_service.predict_latest(),
            "proactive": proactive_engine.latest(),
            "realtime": realtime_engine.analyse_once(generate_tick=False, run_diagnosis=False),
            "metrics": intelligence_service.metrics(),
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


@app.post("/api/incidents/add")
def add_incident(payload: dict[str, Any] = Body(...)) -> dict:
    title = str(payload.get("title") or "").strip()
    fault_type = str(payload.get("fault_type") or "unknown").strip()
    body = str(payload.get("body") or "").strip()
    if not title or not body:
        return {"ok": False, "error": "Both title and body are required."}
    incident = rag_llm_service.add_incident(title, fault_type, body)
    return {"ok": True, "data": incident}


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
    proactive = proactive_engine.latest()
    
    return {
        "ok": True, 
        "data": {
            "frames": frames, 
            "alert": alert, 
            "proactive": proactive,
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
    proactive = proactive_engine.latest()
    
    return {"ok": True, "data": {"frames": frames, "alert": alert, "proactive": proactive, "graph_context": graph_context, "diagnosis": diagnosis, "remediation": remediation}}


@app.get("/api/causal-graph")
def causal_graph(slice: str | None = None) -> dict:
    if slice and slice in {"slice_1", "slice_2", "slice_3"}:
        return {"ok": True, "data": intelligence_service.discover_slice_dag(slice)}
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
def nl_query(payload: dict[str, Any] = Body(...)) -> dict:
    question = str(payload.get("question") or payload.get("query") or "").strip()
    if not question:
        return {"ok": False, "error": "Field 'query' or 'question' is required."}
    return {"ok": True, "data": graph_service.nl_to_cypher(question)}


@app.get("/api/proactive/latest")
def proactive_latest() -> dict:
    return {"ok": True, "data": proactive_engine.latest()}


@app.get("/api/conformal/report")
def conformal_report() -> dict:
    """
    ACI (Adaptive Conformal Inference) adaptation report.
    Returns current q̂, empirical coverage, ACI update history.
    Use this to verify the conformal predictor is maintaining coverage
    after switching from simulated to live Open5GS data.
    """
    report = intelligence_service._conformal.aci_report()
    cal_info = {
        "is_calibrated": intelligence_service._conformal.is_calibrated,
        "q_hat": round(intelligence_service._conformal.q_hat, 6)
            if intelligence_service._conformal.q_hat is not None else None,
        "n_calibration": intelligence_service._conformal.n_calibration,
        "alpha": intelligence_service._conformal.alpha,
        "coverage_guarantee": f"{(1 - intelligence_service._conformal.alpha)*100:.0f}%",
    }
    return {"ok": True, "data": {"calibration": cal_info, "aci": report}}


@app.post("/api/conformal/update")
def conformal_aci_update(prediction: float, true_label: float) -> dict:
    """
    ACI feedback loop: provide a resolved fault label to update q̂.

    Call this when you have a ground-truth outcome for a previous prediction.
    Example: after a fault injection resolves and you know whether the alert
    was correct (true_label=1) or a false positive (true_label=0).

    Body params:
        prediction: the fault_probability that was emitted at alert time
        true_label: 0 (false alarm) or 1 (confirmed fault)
    """
    update = intelligence_service._conformal.update(prediction, true_label)
    db.audit("conformal_aci_update", {
        "prediction": prediction,
        "true_label": true_label,
        **update,
    })
    return {"ok": True, "data": update}



@app.get("/api/proactive/forecast")
def proactive_forecast(limit: int = 240) -> dict:
    return {"ok": True, "data": proactive_engine.forecast(limit)}


@app.post("/api/proactive/avoid")
def proactive_avoid() -> dict:
    return {"ok": True, "data": proactive_engine.avoid()}


@app.get("/api/proactive/autopilot")
def proactive_autopilot() -> dict:
    return {"ok": True, "data": proactive_engine.compare_actions()}


@app.get("/api/proactive/explain")
def proactive_explain() -> dict:
    return {"ok": True, "data": explainability_service.latest_prediction_explanation()}


@app.get("/api/realtime/analyse")
def realtime_analyse(generate_tick: bool = True, run_diagnosis: bool = True) -> dict:
    return {"ok": True, "data": realtime_engine.analyse_once(generate_tick=generate_tick, run_diagnosis=run_diagnosis)}


@app.post("/api/realtime/simulate-fix")
def realtime_simulate_fix(payload: dict[str, Any] = Body(default={})) -> dict:
    return {"ok": True, "data": realtime_engine.simulate_fix(payload)}


@app.get("/api/explain/tab/{tab_name}")
def explain_tab(tab_name: str, node_id: str | None = None) -> dict:
    return {"ok": True, "data": explainability_service.explain_tab(tab_name, node_id)}


@app.post("/api/explain/event")
def explain_event(payload: dict[str, Any] = Body(default={})) -> dict:
    return {"ok": True, "data": explainability_service.explain_event(payload)}


@app.get("/api/explain/node/{node_id}")
def explain_node(node_id: str) -> dict:
    return {"ok": True, "data": explainability_service.explain_node(node_id)}


@app.get("/api/explain/prediction/latest")
def explain_prediction_latest() -> dict:
    return {"ok": True, "data": explainability_service.latest_prediction_explanation()}


@app.get("/api/xai/explain/{tab_name}")
def xai_explain(tab_name: str, node_id: str | None = None) -> dict:
    """Generate Groq-powered SHAP-based XAI explanation for a dashboard tab."""
    return {"ok": True, "data": xai_service.generate_explanation(tab_name, node_id)}


@app.post("/api/training/export-retrain")
def training_export_retrain(payload: dict[str, Any] = Body(default={})) -> dict:
    """Export telemetry DB to CSV and trigger retraining pipeline.
    This enables the model to learn from live/real data collected in production."""
    import csv
    from pathlib import Path

    # Step 1: Use a generated/uploaded CSV if supplied; otherwise export current DB telemetry.
    supplied_data = payload.get("data")
    if supplied_data and Path(str(supplied_data)).exists():
        export_path = Path(str(supplied_data))
        export_result = {"rows_exported": "existing_file", "csv_path": str(export_path), "source": "supplied_dataset"}
    else:
        rows = db.latest_telemetry(int(payload.get("limit", 5000)))
        if not rows:
            return {"ok": False, "error": "No telemetry data in database to export."}

        export_path = Path("data/exported_telemetry.csv")
        export_path.parent.mkdir(parents=True, exist_ok=True)

        fieldnames = [
            "timestamp", "slice_id", "node_id", "node_type",
            "cpu", "memory", "latency_ms", "packet_loss",
            "throughput_mbps", "prb_utilization", "fault_label", "fault_type",
        ]
        with open(export_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for row in rows:
                metrics = row.get("metrics", {})
                writer.writerow({
                    "timestamp": row.get("timestamp", ""),
                    "slice_id": row.get("slice_id", ""),
                    "node_id": row.get("node_id", ""),
                    "node_type": row.get("node_type", ""),
                    "cpu": metrics.get("cpu", 0),
                    "memory": metrics.get("memory", 0),
                    "latency_ms": metrics.get("latency_ms", 0),
                    "packet_loss": metrics.get("packet_loss", 0),
                    "throughput_mbps": metrics.get("throughput_mbps", 0),
                    "prb_utilization": metrics.get("prb_utilization", 0),
                    "fault_label": row.get("fault_label", 0),
                    "fault_type": row.get("fault_type", ""),
                })

        export_result = {
            "rows_exported": len(rows),
            "csv_path": str(export_path),
            "source": "database_export",
        }

    # Step 2: Trigger retraining
    train_payload = {
        "data": str(export_path),
        "epochs": int(payload.get("epochs", 8)),
        "batch_size": int(payload.get("batch_size", 256)),
        "hidden_dim": int(payload.get("hidden_dim", 128)),
    }
    if payload.get("cpu"):
        train_payload["cpu"] = True

    train_result = training_pipeline_service.start(train_payload)

    db.audit("export_and_retrain", {**export_result, "training": train_result})
    return {"ok": True, "data": {"export": export_result, "training": train_result}}


@app.get("/api/xai/explain/prediction/latest")
def xai_prediction_latest() -> dict:
    return {"ok": True, "data": explainability_service.latest_prediction_explanation()}


@app.get("/api/datasets/registry")
def datasets_registry() -> dict:
    return {"ok": True, "data": harmonizer_service.registry()}


@app.get("/api/data/templates")
def data_templates() -> dict:
    return {"ok": True, "data": harmonizer_service.templates()}


@app.get("/api/data/quality")
def data_quality(limit: int = 1000) -> dict:
    return {"ok": True, "data": harmonizer_service.quality_report(db.latest_telemetry(limit))}


@app.post("/api/data/generate-synthetic")
def generate_synthetic_data(payload: dict[str, Any] = Body(default={})) -> dict:
    scenario = str(payload.get("scenario", "mixed")).strip() or "mixed"
    duration_hours = max(0.25, min(float(payload.get("duration_hours", 6)), 48.0))
    fault_rate = max(0.0, min(float(payload.get("fault_rate", 0.08)), 0.30))
    node_count = max(5, min(int(payload.get("nodes", payload.get("node_count", 8))), 20))
    slices = payload.get("slices") or ["slice_1", "slice_2", "slice_3"]
    if not isinstance(slices, list):
        slices = ["slice_1", "slice_2", "slice_3"]
    slices = [str(item) for item in slices if str(item) in {"slice_1", "slice_2", "slice_3"}] or ["slice_1"]

    rows, summary = generate_realistic_rows(
        scenario=scenario,
        duration_hours=duration_hours,
        fault_rate=fault_rate,
        slices=slices,
        node_count=node_count,
    )
    output_path = Path("data/scenarios") / f"{scenario}.csv"
    write_csv(output_path, rows)

    frames = []
    for row in rows:
        frames.append({
            "timestamp": row["timestamp"],
            "slice_id": row["slice_id"],
            "node_id": row["node_id"],
            "node_type": row["node_type"],
            "metrics": {key: row[key] for key in ["cpu", "memory", "latency_ms", "packet_loss", "throughput_mbps", "prb_utilization"]},
            "fault_label": row["fault_label"],
            "fault_type": row.get("fault_type") or None,
            "source": row.get("source", "realistic_generator"),
        })
    telemetry_service.ingest_external_frames(frames, audit_event="realistic_synthetic_generated")
    topology = graph_service.sync_from_telemetry(frames, origin="synthetic_data_twin")
    db.audit("synthetic_generation", {**summary, "output": str(output_path), "loaded_rows": len(frames), "topology": topology})
    return {
        "ok": True,
        "data": {
            **summary,
            "output": str(output_path),
            "download_url": f"/api/data/download?path={output_path.as_posix()}",
            "loaded_rows": len(frames),
            "topology": topology,
            "preview": frames[:10],
            "quality": harmonizer_service.quality_report(frames),
        },
    }


@app.get("/api/data/download")
def download_data(path: str = Query(...)) -> FileResponse:
    requested = Path(path)
    allowed_roots = [Path("data").resolve(), Path("reports").resolve(), Path("artifacts").resolve()]
    resolved = requested.resolve()
    if not any(resolved == root or root in resolved.parents for root in allowed_roots):
        raise HTTPException(status_code=400, detail="Download path is outside the allowed project artifact folders.")
    if not resolved.exists() or not resolved.is_file():
        raise HTTPException(status_code=404, detail=str(resolved))
    return FileResponse(resolved, filename=resolved.name)


@app.get("/api/wireless/adaptive-plan")
def wireless_adaptive_plan() -> dict:
    recent = db.latest_telemetry(240)
    users = max(4, min(32, len({row["node_id"] for row in recent}) or 8))
    channels = max(8, min(64, users * 2))
    allocation = wireless_optimizer_service.hopfield_allocate(users=users, channels=channels, iterations=80)
    latest_alert = db.latest_alerts(1)
    alert = latest_alert[0] if latest_alert else intelligence_service.predict_latest()
    rl = adaptive_rl_service.recommend(
        str(alert.get("fault_type", "congestion")) if alert else "congestion",
        risk="low" if allocation.get("fairness_index", 0) >= 0.7 else "medium",
        probability=float(alert.get("fault_probability", 0.55)) if alert else 0.55,
        fairness_index=allocation.get("fairness_index"),
        throughput_mbps=allocation.get("throughput_mbps"),
    )
    plan = {
        "status": "adaptive_plan_ready",
        "network_basis": {
            "telemetry_rows": len(recent),
            "active_nodes": users,
            "channels_planned": channels,
            "latest_fault": alert,
        },
        "allocation": allocation,
        "rl_recommendation": rl,
        "why_it_matters": [
            "Wireless allocation is now tied to live topology and telemetry size instead of a detached toy input.",
            "The CMDP policy receives the current fault context plus fairness and throughput evidence.",
            "This creates a preventive radio-resource action before congestion becomes an SLA incident.",
        ],
    }
    db.audit("wireless_adaptive_plan", plan)
    return {"ok": True, "data": plan}


@app.get("/api/executive/proof")
def executive_proof() -> dict:
    metrics = intelligence_service.metrics()
    accuracy = intelligence_service.prediction_accuracy()
    proactive = proactive_engine.latest()
    autopilot = proactive_engine.compare_actions()
    quality = harmonizer_service.quality_report(db.latest_telemetry(1000))
    audit_entries = db.audit_entries(300)
    audit_types = {entry.get("event_type") for entry in audit_entries}
    benchmark_path = Path("reports/latest_benchmark.json")
    benchmark = {}
    if benchmark_path.exists():
        with suppress(Exception):
            import json
            benchmark = json.loads(benchmark_path.read_text(encoding="utf-8"))
    proof = {
        "headline": "NetOracle is unique because it predicts, explains, safely prevents, adapts to new data, and proves every decision.",
        "novel_feature": {
            "name": "Adaptive Causal Data Twin",
            "claim": "Generated or uploaded telemetry reshapes the graph, risk model inputs, XAI layer, benchmark evidence, and retraining handoff in one loop.",
            "metric": "Topology freshness + data quality + preventive lead time + audit completeness",
        },
        "full_trilogy": [
            {
                "name": "Preventive Autopilot",
                "proof": autopilot.get("executive_summary", "Autopilot is waiting for enough telemetry."),
                "status": autopilot.get("status", "unknown"),
            },
            {
                "name": "Adaptive Data Twin",
                "proof": f"Current data quality score is {quality.get('quality_score', 0)} across {quality.get('rows', 0)} recent rows.",
                "status": "ready" if quality.get("quality_score", 0) >= 0.65 else "needs_more_data",
            },
            {
                "name": "Executive Proof Mode",
                "proof": f"Audit ledger has {len(audit_entries)} recent events across {len(audit_types)} event types.",
                "status": "ready",
            },
        ],
        "comparison": [
            {"capability": "Traditional threshold monitor", "legacy": "Detects after a metric crosses a limit.", "netoracle": "Forecasts T+5/T+10/T+20 risk before SLA damage."},
            {"capability": "Static dashboard", "legacy": "Shows charts but not why they matter.", "netoracle": "Explains metrics, devices, causal paths, and safe next steps."},
            {"capability": "Manual RCA", "legacy": "Operator manually searches logs and topology.", "netoracle": "Uses GraphRAG and MoE specialists grounded in topology and incident memory."},
            {"capability": "Automation", "legacy": "Scripts can be unsafe or unaudited.", "netoracle": "CMDP safety gates block risky actions and log every decision."},
            {"capability": "New network data", "legacy": "Requires custom dashboard/model work.", "netoracle": "Loads canonical telemetry/topology and re-runs prediction, graph, XAI, and training flows."},
        ],
        "hackathon_metrics": [
            {"metric": "Preventive lead time", "why_unique": "Shows minutes gained before an SLA breach instead of post-fault detection."},
            {"metric": "Topology freshness", "why_unique": "Scores whether the digital twin reflects the current uploaded/generated network."},
            {"metric": "Causal support ratio", "why_unique": "Measures how much of each diagnosis is backed by causal edges and graph paths."},
            {"metric": "Safe autonomy rate", "why_unique": "Counts actions that pass CMDP gates rather than blindly executing scripts."},
            {"metric": "Adaptation latency", "why_unique": "Time from new data ingestion to updated topology, forecast, explanation, and training artifact."},
        ],
        "evidence": {
            "model": metrics,
            "prediction_accuracy": accuracy,
            "proactive": proactive,
            "data_quality": quality,
            "benchmark": benchmark,
            "audit_event_types": sorted(str(item) for item in audit_types if item),
        },
        "talk_track": [
            "NetOracle is not a Grafana clone; it is a preventive network fault intelligence loop.",
            "It combines causal discovery, temporal prediction, topology localisation, LLM diagnosis, safe RL remediation, and audit evidence.",
            "The same UI can adapt to generated, uploaded, CSV-streamed, Prometheus, or Open5GS-shaped telemetry.",
        ],
    }
    return {"ok": True, "data": proof}


@app.get("/api/groq/health")
def groq_health() -> dict:
    settings = get_settings()
    configured = bool(settings.groq_api_key)
    if not configured:
        return {"ok": True, "data": {"configured": False, "reachable": False, "message": "GROQ_API_KEY is not configured."}}
    try:
        from app.services.rag_llm import call_llm
        result = call_llm('Return JSON only: {"status":"ok","purpose":"netoracle_health_check"}')
        return {"ok": True, "data": {"configured": True, "reachable": bool(result), "model": result.get("_model") if isinstance(result, dict) else None}}
    except Exception as exc:
        return {"ok": True, "data": {"configured": True, "reachable": False, "error": str(exc)}}


@app.get("/api/metrics/prediction-accuracy")
def prediction_accuracy() -> dict:
    return {"ok": True, "data": intelligence_service.prediction_accuracy()}


@app.post("/api/training/start")
def training_start(payload: dict[str, Any] = Body(default={})) -> dict:
    return {"ok": True, "data": training_pipeline_service.start(payload)}


@app.get("/api/training/status")
def training_status() -> dict:
    return {"ok": True, "data": training_pipeline_service.status()}


@app.post("/api/training/stop")
def training_stop() -> dict:
    return {"ok": True, "data": training_pipeline_service.stop()}


@app.get("/api/training/metrics")
def training_metrics() -> dict:
    return {"ok": True, "data": training_pipeline_service.metrics()}


@app.post("/api/benchmarks/run")
async def run_benchmarks(scenarios: int = 60) -> dict:
    """Queue a benchmark run as a background job. Poll /api/jobs/{job_id} for results."""
    job_id = _new_job(f"benchmark_run(scenarios={scenarios})")
    asyncio.create_task(_run_job(job_id, benchmark_service.run, scenarios))
    return {"ok": True, "data": {"job_id": job_id, "status": "queued", "poll": f"/api/jobs/{job_id}"}}


@app.post("/api/benchmarks/live")
def run_live_benchmarks() -> dict:
    return {"ok": True, "data": benchmark_service.run_live()}


@app.get("/api/evidence/latest")
def get_latest_evidence(limit: int = 10) -> dict:
    rows = db.latest_telemetry(5000)
    by_source = {}
    for r in rows:
        src = str(r.get("source", "unknown"))
        by_source[src] = by_source.get(src, 0) + 1
    
    latest_frames = db.latest_telemetry(limit)
    
    return {
        "ok": True,
        "data": {
            "source_distribution": by_source,
            "claim_boundaries": {
                "open5gs_live": "Values verified against WSL2 Prometheus ports",
                "simulation": "Synthetic metrics from scenario file",
                "open5gs_simulated": "Open5GS stack data under simulation"
            },
            "latest_frames": latest_frames,
            "artifacts": {
                "open5gs_metric_registry": "artifacts/open5gs_metric_registry.json" if Path("artifacts/open5gs_metric_registry.json").exists() else None,
                "benchmarks_live_vs_simulated": "reports/benchmarks_live_vs_simulated.json" if Path("reports/benchmarks_live_vs_simulated.json").exists() else None
            }
        }
    }




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


@app.get("/api/rl/constraints")
def rl_constraints() -> dict:
    """
    CMDP Safety Constraint Status — §6.5 Novel Contribution.
    Returns per-constraint Lagrangian λ, violation rates, lockdown status.
    Use this to verify the safety filter is adapting correctly during live ops.
    """
    from app.services.adaptive_rl import get_cmdp_status
    return {"ok": True, "data": get_cmdp_status()}


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
