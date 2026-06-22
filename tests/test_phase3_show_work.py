def test_heuristic_explanation_contributions_sum():
    from app.services.intelligence import intelligence_service

    metrics = {
        "cpu": 50,
        "memory": 40,
        "latency_ms": 60,
        "packet_loss": 0.04,
        "throughput_mbps": 700,
        "prb_utilization": 0.6,
    }
    explanation = intelligence_service._heuristic_risk_explanation(metrics)
    assert explanation["method"] == "heuristic_weight_proxy"
    assert abs(sum(explanation["contributions"].values()) - explanation["raw_weighted_score"]) < 1e-5
    assert 0 <= explanation["probability"] <= 1


def test_trace_with_model_gracefully_degrades_without_model():
    from app.services.ctgnn_model import trace_with_model

    assert trace_with_model(None, [], {}, 12) is None


def test_observatory_kl_divergence_edges():
    from app.services.observatory import observatory_service

    assert observatory_service._kl_divergence([], [1, 2]) == 0.0
    assert observatory_service._kl_divergence([1, 1, 1], [1, 1, 1]) == 0.0
    assert observatory_service._kl_divergence([1, 1, 1, 1], [10, 10, 10, 10]) > 0.0


def test_delta_explainer_detects_material_change(client):
    from app.database import db
    from app.services.delta_explainer import delta_explainer_service

    base = {
        "slice_id": "slice_delta",
        "node_id": "node_delta",
        "node_type": "UPF",
        "metrics": {
            "cpu": 20,
            "memory": 40,
            "latency_ms": 20,
            "packet_loss": 0.001,
            "throughput_mbps": 900,
            "prb_utilization": 0.3,
        },
        "fault_label": 0,
        "fault_type": None,
        "source": "simulation",
    }
    db.insert_telemetry({**base, "timestamp": "2026-06-22T00:00:00+00:00"})
    changed = {**base, "timestamp": "2026-06-22T00:00:05+00:00", "metrics": {**base["metrics"], "packet_loss": 0.09}}
    db.insert_telemetry(changed)

    result = delta_explainer_service.explain({"slice_id": "slice_delta", "node_id": "node_delta"})
    assert result["status"] == "ready"
    assert result["top_change"]["metric"] == "packet_loss"
    assert result["top_change"]["material"] is True
    assert "packet_loss" in result["explanation"]


def test_phase3_api_contracts(client):
    for _ in range(2):
        client.post("/api/telemetry/tick")
    client.get("/api/metrics")

    provenance = client.get("/api/provenance/latest")
    assert provenance.status_code == 200
    stages = provenance.json()["data"]["stages"]
    assert {"raw_collection", "normalization", "model_processing", "calibration_decision"}.issubset(stages)

    delta = client.post("/api/explain/delta", json={})
    assert delta.status_code == 200
    assert "attribution" in delta.json()["data"]

    comparison = client.get("/api/observatory/comparison?limit=20")
    assert comparison.status_code == 200
    data = comparison.json()["data"]
    assert "live" in data and "simulation" in data

    recent = client.get("/api/telemetry/recent?limit=50").json()["data"]
    assert all(row.get("source") != "shadow_simulation" for row in recent)
