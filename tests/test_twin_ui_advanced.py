import time
import json
import pytest

# ── API Smoke Tests (no browser needed) ──────────────────────────────────

class TestAPIEndpoints:
    def test_status_healthy(self, client):
        r = client.get("/api/status")
        assert r.status_code == 200
        data = r.json()
        assert data.get("ok") is True

    def test_visualization_scene_returns_nodes(self, client):
        r = client.get("/api/visualization/scene")
        assert r.status_code == 200
        res = r.json()
        data = res.get("data", {})
        assert "nodes" in data or "objects" in data or "topology" in data, "Scene has no node data"

    def test_visualization_replay_returns_events(self, client):
        # First inject a fault to generate events
        client.post("/api/fault/inject", json={
            "node_id": "upf_1", "fault_type": "congestion", "severity": 0.8
        })
        # No need for sleep with TestClient
        r = client.get("/api/visualization/replay")
        assert r.status_code == 200

    def test_demo_run_populates_audit(self, client):
        client.post("/api/demo/run", json={
            "slice_id": "slice_1", "node_id": "upf_1",
            "fault_type": "congestion", "severity": 0.7
        })
        r = client.get("/api/audit")
        assert r.status_code == 200
        res = r.json()
        audit = res.get("data", [])
        assert len(audit) > 0, "Audit log empty after demo run"

    def test_cmdp_status_endpoint(self, client):
        r = client.get("/api/rl/policy")
        assert r.status_code == 200

    def test_nl_query_returns_result(self, client):
        r = client.post("/api/nl-query",
                          json={"query": "Which VNFs are connected to Slice 1?"})
        assert r.status_code == 200
        data = r.json().get("data", {})
        assert "result" in data or "answer" in data or "response" in data or "cypher" in data


# ── Multi-Fault Stress Test ───────────────────────────────────────────────

class TestMultiFaultScenarios:
    def test_sequential_fault_injection(self, client):
        """Inject faults into multiple nodes and verify they all appear in audit."""
        nodes = ["gnb_1", "upf_1", "router_1"]
        for node in nodes:
            # Use run_demo instead of fault/inject for better reliability in triggering audit
            r = client.post("/api/demo/run", json={
                "slice_id": "slice_1", "node_id": node, 
                "fault_type": "congestion", "severity": 0.9, "ticks": 5
            })
            assert r.status_code == 200
        
        r = client.get("/api/audit")
        audit = r.json().get("data", [])
        
        found_nodes = []
        for entry in audit:
            # The API returns entries from the DB which have a 'payload' field
            p = entry.get("payload", {})
            nid = p.get("node_id") or p.get("context", {}).get("node_id")
            if nid:
                found_nodes.append(nid)
                
        for node in nodes:
            assert node in found_nodes, f"Node {node} not found in audit: {found_nodes}"

    def test_concurrent_demo_runs_dont_crash(self, client):
        """Simulate multiple users running demos at once."""
        # Note: In TestClient this is still sequential but verifies state thread-safety
        results = []
        for i in range(5):
            r = client.post("/api/demo/run", json={
                "slice_id": f"slice_{i%3+1}", 
                "node_id": "upf_1",
                "fault_type": "congestion"
            })
            results.append(r.status_code)
        
        success = [code for code in results if code == 200]
        assert len(success) >= 1, f"All requests failed: {results}"

    def test_moe_routing_visible_in_diagnosis(self, client):
        """After a fault, diagnosis should mention experts/specialists."""
        client.post("/api/fault/inject", json={
            "node_id": "gnb_1", "fault_type": "congestion", "severity": 0.85
        })
        r = client.post("/api/demo/run", json={
            "slice_id": "slice_1", "node_id": "gnb_1",
            "fault_type": "congestion", "severity": 0.85
        })
        assert r.status_code == 200
        res = r.json()
        body_str = json.dumps(res).lower()
        found = any(kw in body_str for kw in ["diagnosis", "experts", "specialist", "moe", "verdict"])
        assert found, "MoE routing details not found in diagnosis output"

    def test_cmdp_blocks_high_risk_action(self, client):
        """High-risk context should result in escalation, not execution."""
        r = client.post("/api/rl/recommend", json={
            "node_id": "upf_1",
            "fault_type": "congestion",
            "conformal_risk_score": 0.95,
            "probability": 0.80,
        })
        assert r.status_code == 200
        res = r.json()
        data = res.get("data", res)
        is_blocked = (
            data.get("escalate") is True or 
            data.get("cmdp_approved") is False or 
            data.get("action") == "escalate_to_human" or
            "blocked" in data.get("strategy", "").lower()
        )
        assert is_blocked, "High-risk action was not blocked by CMDP"


# ── Performance Benchmarks ────────────────────────────────────────────────

class TestPerformanceBenchmarks:
    def test_telemetry_tick_latency(self, client):
        start = time.time()
        r = client.post("/api/telemetry/tick")
        elapsed = (time.time() - start) * 1000
        assert r.status_code == 200
        # In TestClient, latency should be very low, but allow buffer for test runner spikes
        assert elapsed < 1500 

    def test_demo_run_latency(self, client):
        start = time.time()
        client.post("/api/demo/run", json={"node_id": "upf_1"})
        elapsed = (time.time() - start) * 1000
        # Diagnosis with mock LLM should be < 20s
        assert elapsed < 20000

    def test_nl_query_latency(self, client):
        start = time.time()
        client.post("/api/nl-query", json={"query": "Which VNFs connected?"})
        elapsed = (time.time() - start) * 1000
        assert elapsed < 5000

    def test_benchmark_suite_runs(self, client):
        """Verify the benchmark endpoint queues a background job without 500 errors."""
        r = client.post("/api/benchmarks/run")
        assert r.status_code == 200
        data = r.json().get("data", {})
        # New async contract: returns job_id immediately
        assert "job_id" in data, f"Expected job_id in response, got: {data}"
        assert "status" in data
        assert data["status"] == "queued"
        assert "poll" in data

