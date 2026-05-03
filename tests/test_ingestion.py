def test_upload_telemetry_csv(client):
    csv_content = "timestamp,slice_id,node_id,node_type,cpu,latency_ms\n2026-05-03T10:00:00Z,slice_1,upf_1,UPF,50,20\n"
    response = client.post(
        "/api/data/upload-telemetry",
        files={"file": ("test.csv", csv_content, "text/csv")}
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["frames_ingested"] == 1
    assert data["sample"][0]["metrics"]["cpu"] == 50.0

def test_upload_telemetry_json(client):
    json_content = '[{"timestamp": "2026-05-03T10:00:00Z", "slice_id": "slice_1", "node_id": "upf_1", "metrics": {"cpu": 60}}]'
    response = client.post(
        "/api/data/upload-telemetry",
        files={"file": ("test.json", json_content, "application/json")}
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["frames_ingested"] == 1
    assert data["sample"][0]["metrics"]["cpu"] == 60.0

def test_stream_telemetry(client):
    payload = {
        "timestamp": "2026-05-03T10:00:00Z",
        "slice_id": "slice_1",
        "node_id": "upf_1",
        "node_type": "UPF",
        "cpu": 75,
        "latency_ms": 15
    }
    response = client.post("/api/telemetry/stream", json=payload)
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "ingested"
    assert data["frame"]["metrics"]["cpu"] == 75.0
