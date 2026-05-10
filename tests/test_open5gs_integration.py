def test_open5gs_adapter_fallback_frames(monkeypatch):
    from app.services.open5gs_adapter import Open5GSAdapter, Open5GSMongoClient, Open5GSPrometheusClient

    monkeypatch.setattr(Open5GSPrometheusClient, "is_available", lambda self: False)
    monkeypatch.setattr(Open5GSMongoClient, "_connect", lambda self: None)
    adapter = Open5GSAdapter(
        prometheus_url="http://127.0.0.1:65530",
        mongo_uri="mongodb://127.0.0.1:65531",
    )
    frames = adapter.get_tick()

    assert len(frames) == 6
    assert {frame["node_id"] for frame in frames} >= {"amf_1", "smf_1", "upf_1", "pcf_1", "nrf_1", "gnb_1"}
    assert all(frame["source"] == "open5gs_simulated" for frame in frames)
    assert all("cpu" in frame and "throughput_mbps" in frame for frame in frames)


def test_data_source_factory_selects_simulation(monkeypatch):
    from app.settings import get_settings
    from app.services.data_sources import SimulationAdapter, get_adapter, reset_adapter

    monkeypatch.setenv("DATA_SOURCE_MODE", "simulation")
    get_settings.cache_clear()
    reset_adapter()
    try:
        assert isinstance(get_adapter(), SimulationAdapter)
    finally:
        reset_adapter()
        get_settings.cache_clear()


def test_telemetry_normalizes_flat_open5gs_metrics():
    from app.services.telemetry import telemetry_service

    frame = telemetry_service._normalise_frame({
        "timestamp": "2026-05-09T00:00:00+00:00",
        "slice_id": "slice_1",
        "node_id": "upf_1",
        "node_type": "UPF",
        "cpu": 42,
        "memory": 55,
        "latency_ms": 12.5,
        "packet_loss": 0.01,
        "throughput_mbps": 123.4,
        "prb_utilization": 0.67,
        "fault_label": 0,
        "fault_type": "",
        "source": "open5gs_live",
    })

    assert frame["metrics"]["cpu"] == 42.0
    assert frame["metrics"]["throughput_mbps"] == 123.4
    assert "cpu" not in {key for key in frame if key != "metrics"}
    assert frame["source"] == "open5gs_live"


def test_data_mode_and_open5gs_health_endpoints(client):
    mode = client.get("/api/data/mode")
    assert mode.status_code == 200
    body = mode.json()
    assert "mode" in body.get("data", body)  # mode is inside data envelope
 
    health = client.get("/api/open5gs/health")
    assert health.status_code == 200
    hbody = health.json()
    health_data = hbody.get("data", hbody)
    assert "nfs" in health_data or "message" in health_data


def test_websocket_telemetry_receives_tick(client):
    with client.websocket_connect("/ws/telemetry") as websocket:
        payload = websocket.receive_json()
    assert payload["type"] == "tick"
    assert payload["frames"]
    assert all("metrics" in frame for frame in payload["frames"])
