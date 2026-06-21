from pathlib import Path


def test_telemetry_evidence_round_trips_through_db():
    from app.database import db

    frame = {
        "timestamp": "2026-06-21T00:00:00+00:00",
        "slice_id": "slice_9",
        "node_id": "evidence_node",
        "node_type": "UPF",
        "metrics": {
            "cpu": 10,
            "memory": 20,
            "latency_ms": 5,
            "packet_loss": 0.0,
            "throughput_mbps": 100,
            "prb_utilization": 0.2,
        },
        "fault_label": 0,
        "fault_type": None,
        "source": "open5gs_live",
        "source_detail": {"nf": "upf", "classification": "open5gs_live"},
        "evidence": {"queries": [{"name": "rx_bytes", "value": 42.0}]},
        "scenario_id": "scenario_test",
    }
    db.insert_telemetry(frame)
    rows = [row for row in db.latest_telemetry(50) if row["node_id"] == "evidence_node"]

    assert rows
    row = rows[-1]
    assert row["source"] == "open5gs_live"
    assert row["source_detail"]["nf"] == "upf"
    assert row["evidence"]["queries"][0]["name"] == "rx_bytes"
    assert row["scenario_id"] == "scenario_test"
    assert "_evidence" not in row["metrics"]


def test_metric_registry_marks_present_and_missing(monkeypatch):
    from app.services.open5gs_adapter import Open5GSAdapter, Open5GSMongoClient

    monkeypatch.setattr(Open5GSMongoClient, "_connect", lambda self: None)
    adapter = Open5GSAdapter("http://prometheus.local:9090", "mongodb://mongo.local:27017")
    monkeypatch.setattr(adapter.prom, "is_available", lambda: True)
    monkeypatch.setattr(
        adapter.prom,
        "label_values",
        lambda label_name="__name__": (
            ["node_cpu_seconds_total", "node_memory_MemTotal_bytes", "upf_rx_bytes_total"],
            {"ok": True, "endpoint": "/api/v1/label/__name__/values"},
        ),
    )

    class Response:
        status_code = 200
        text = "# HELP dummy\nupf_rx_bytes_total 1\n"

    monkeypatch.setattr("app.services.open5gs_adapter.requests.get", lambda *args, **kwargs: Response())
    registry = adapter.discover_metric_registry(save=False)

    by_name = {item["metric_name"]: item for item in registry["expected_metrics"]}
    assert by_name["upf_rx_bytes_total"]["status"] == "verified_present"
    assert by_name["amf_session_count"]["status"] == "assumed_missing"
    assert registry["nf_exporters"]["upf"]["reachable"] is True


def test_live_benchmark_endpoint_writes_local_artifact(client):
    response = client.post("/api/benchmarks/live")
    assert response.status_code == 200
    data = response.json()["data"]
    assert "inputs" in data
    assert "model_comparison" in data
    assert "claim_policy" in data
    assert Path("reports/benchmarks_live_vs_simulated.json").exists()


def test_evidence_latest_endpoint_has_claim_boundaries(client):
    response = client.get("/api/evidence/latest?limit=3")
    assert response.status_code == 200
    data = response.json()["data"]
    assert "source_distribution" in data
    assert "claim_boundaries" in data
    assert "open5gs_live" in data["claim_boundaries"]


def test_fault_api_defaults_match_startup_subscriber():
    from scripts import fault_injection_api

    assert fault_injection_api.DEFAULT_TEST_IMSI == "999700000000001"
    assert fault_injection_api.GNB_CONFIG == "/etc/ueransim/open5gs-gnb.yaml"
    assert fault_injection_api.UE_CONFIG == "/etc/ueransim/open5gs-ue.yaml"
