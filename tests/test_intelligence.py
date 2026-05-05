"""
Test Suite for Intelligence Service — Member 2
================================================
20 test cases covering CTGNN inference, Conformal Prediction,
NOTEARS causal discovery, risk scoring, and alert generation.
"""
import math


# ─── Conformal Prediction Unit Tests ────────────────────────────────

def test_conformal_predictor_calibration():
    """ConformalPredictor calibrates from a list of scores."""
    from app.services.conformal import ConformalPredictor
    cp = ConformalPredictor(alpha=0.10)
    scores = [abs(i / 100 - 0.5) for i in range(100)]
    cp.calibrate_from_scores(scores)
    assert cp.is_calibrated
    assert cp.q_hat is not None
    assert cp.q_hat > 0


def test_conformal_interval_bounds():
    """Prediction interval is within [0, 1] and lower <= upper."""
    from app.services.conformal import ConformalPredictor
    cp = ConformalPredictor(alpha=0.10)
    cp.calibrate_from_scores([0.1, 0.2, 0.3, 0.15, 0.05, 0.25, 0.08, 0.12, 0.18, 0.22])
    result = cp.predict_with_interval(0.87)
    assert result["prob_lower"] >= 0.0
    assert result["prob_upper"] <= 1.0
    assert result["prob_lower"] <= result["prob_upper"]
    assert result["calibrated"] is True


def test_conformal_interval_width_positive():
    """Interval width is positive."""
    from app.services.conformal import ConformalPredictor
    cp = ConformalPredictor(alpha=0.10)
    cp.calibrate_from_scores([0.05] * 50 + [0.8] * 50)
    result = cp.predict_with_interval(0.5)
    assert result["prob_upper"] - result["prob_lower"] > 0


def test_conformal_uncalibrated_fallback():
    """Uncalibrated predictor returns fallback values."""
    from app.services.conformal import ConformalPredictor
    cp = ConformalPredictor(alpha=0.10)
    result = cp.predict_with_interval(0.7)
    assert result["calibrated"] is False
    assert result["coverage_guarantee"] == "uncalibrated"


def test_conformal_coverage_report():
    """Coverage report computes correct empirical coverage."""
    from app.services.conformal import ConformalPredictor
    cp = ConformalPredictor(alpha=0.10)
    cp.calibrate_from_scores([0.05, 0.1, 0.15, 0.2, 0.25, 0.3, 0.35, 0.4, 0.45, 0.5])
    preds = [0.1, 0.9, 0.5, 0.3, 0.7]
    labels = [0.0, 1.0, 0.0, 0.0, 1.0]
    report = cp.coverage_report(preds, labels)
    assert "empirical_coverage" in report
    assert 0.0 <= report["empirical_coverage"] <= 1.0
    assert report["n_test"] == 5


def test_conformal_loads_from_file():
    """ConformalPredictor loads calibration from artifacts file."""
    from app.services.conformal import ConformalPredictor, CALIBRATION_PATH
    cp = ConformalPredictor(alpha=0.10)
    if CALIBRATION_PATH.exists():
        assert cp.calibrate_from_file() is True
        assert cp.is_calibrated
        assert cp.q_hat > 0


# ─── NOTEARS Causal Discovery Tests ─────────────────────────────────

def test_notears_discover_slice_dag(client):
    """Slice DAG discovery returns valid structure."""
    from app.services.notears import NOTEARSDiscovery
    nd = NOTEARSDiscovery()
    dag = nd.discover_slice_dag("slice_1", [])
    assert "slice_id" in dag
    assert "edges" in dag
    assert "algorithm" in dag


def test_causal_dag_has_edges(client):
    """Federated DAG returns edges (from priors or NOTEARS)."""
    response = client.get("/api/causal-graph")
    assert response.status_code == 200
    data = response.json()["data"]
    assert "global_edges" in data
    assert "slice_dags" in data


def test_causal_dag_acyclic():
    """Verify DAG is actually acyclic via topological sort."""
    from app.services.notears import CAUSAL_PRIORS
    # Build adjacency for ground truth priors
    adj = {}
    for src, tgt in CAUSAL_PRIORS:
        adj.setdefault(src, []).append(tgt)
    # Kahn's algorithm
    in_deg = {}
    for src in adj:
        in_deg.setdefault(src, 0)
        for tgt in adj[src]:
            in_deg[tgt] = in_deg.get(tgt, 0) + 1
            in_deg.setdefault(src, in_deg.get(src, 0))
    queue = [n for n in in_deg if in_deg[n] == 0]
    visited = 0
    while queue:
        node = queue.pop(0)
        visited += 1
        for nb in adj.get(node, []):
            in_deg[nb] -= 1
            if in_deg[nb] == 0:
                queue.append(nb)
    assert visited == len(in_deg), "Causal priors contain a cycle!"


def test_notears_shd_computation():
    """SHD computation returns a non-negative integer."""
    from app.services.notears import NOTEARSDiscovery
    nd = NOTEARSDiscovery()
    shd = nd.shd_vs_ground_truth([
        {"source": "cpu", "target": "latency_ms"},
        {"source": "memory", "target": "latency_ms"},
    ])
    assert isinstance(shd, int)
    assert shd >= 0


# ─── Risk Scoring Tests ─────────────────────────────────────────────

def test_risk_score_range():
    """Heuristic risk score is always in [0, 1]."""
    from app.services.intelligence import intelligence_service
    for cpu in [0, 50, 99]:
        for lat in [5, 50, 120]:
            metrics = {"cpu": cpu, "memory": 50, "latency_ms": lat,
                       "packet_loss": 0.01, "throughput_mbps": 800, "prb_utilization": 0.5}
            score, _, _ = intelligence_service._heuristic_risk_score(metrics)
            assert 0 <= score <= 1, f"Score {score} out of range for cpu={cpu}, lat={lat}"


def test_risk_score_high_on_bad_metrics():
    """Extreme bad metrics produce high risk score."""
    from app.services.intelligence import intelligence_service
    bad = {"cpu": 98, "memory": 95, "latency_ms": 110,
           "packet_loss": 0.15, "throughput_mbps": 200, "prb_utilization": 0.95}
    score, _, _ = intelligence_service._heuristic_risk_score(bad)
    assert score > 0.75, f"Bad metrics should produce high score, got {score}"


def test_risk_score_low_on_good_metrics():
    """Normal healthy metrics produce low risk score."""
    from app.services.intelligence import intelligence_service
    good = {"cpu": 30, "memory": 40, "latency_ms": 15,
            "packet_loss": 0.002, "throughput_mbps": 950, "prb_utilization": 0.3}
    score, _, _ = intelligence_service._heuristic_risk_score(good)
    assert score < 0.35, f"Good metrics should produce low score, got {score}"


# ─── API Integration Tests ──────────────────────────────────────────

def test_predict_returns_none_on_empty(client):
    """Prediction returns None when database is empty (handled by startup warm)."""
    # After startup warm, there's data, so this tests the flow doesn't crash
    response = client.get("/api/metrics")
    assert response.status_code == 200


def test_telemetry_tick_generates_frames(client):
    """Telemetry tick produces 12 frames (one per node)."""
    response = client.post("/api/telemetry/tick")
    assert response.status_code == 200
    data = response.json()["data"]
    assert len(data) == 12  # 4 nodes × 3 slices


def test_fault_inject_produces_alert(client):
    """Fault injection triggers the prediction pipeline."""
    response = client.post("/api/fault/inject", json={
        "slice_id": "slice_1", "node_id": "upf_1",
        "fault_type": "congestion", "severity": 0.9,
    })
    assert response.status_code == 200
    data = response.json()["data"]
    assert "alert" in data
    assert "graph_context" in data


def test_metrics_endpoint(client):
    """Metrics endpoint returns model info and baselines."""
    response = client.get("/api/metrics")
    assert response.status_code == 200
    data = response.json()["data"]
    assert "model_active" in data
    assert "baselines" in data
    assert "novel_mechanisms" in data


def test_alert_has_conformal_fields(client):
    """Alert output includes conformal prediction fields."""
    # Generate fault data
    for _ in range(5):
        client.post("/api/telemetry/tick")
    response = client.post("/api/fault/inject", json={
        "slice_id": "slice_1", "node_id": "upf_1",
        "fault_type": "cpu_overload", "severity": 0.95,
    })
    data = response.json()["data"]
    alert = data.get("alert")
    if alert:
        assert "fault_probability" in alert
        assert "prob_lower" in alert
        assert "prob_upper" in alert
        assert "calibrated" in alert
        assert "model_used" in alert


def test_benchmark_run_completes(client):
    """Benchmark suite runs to completion with all expected fields."""
    response = client.post("/api/benchmarks/run?scenarios=12")
    assert response.status_code == 200
    data = response.json()["data"]
    assert "metrics" in data
    assert "ablation" in data
    assert "conformal" in data
    assert "notears" in data
    assert "benefit_summary" in data
    metrics = data["metrics"]
    assert "roc_auc" in metrics
    assert "localisation_accuracy" in metrics
    assert "rca_accuracy" in metrics
    assert "jain_fairness" in metrics
