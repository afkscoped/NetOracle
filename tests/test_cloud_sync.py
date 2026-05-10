"""
Test Suite for CloudSyncService — Local JSON Export
====================================================
Tests the simplified cloud sync which only supports local JSON export.
"""
import os


def test_export_audit_local(client):
    """Export audit produces a local JSON file."""
    response = client.post("/api/cloud/export-audit")
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["provider"] == "local"
    assert data["status"] == "saved"
    assert "path" in data


def test_export_benchmark_local(client):
    """Export benchmark produces a local JSON file."""
    response = client.post("/api/cloud/export-benchmark")
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["provider"] == "local"
    assert data["status"] == "saved"
    assert "path" in data


def test_cloud_status_shows_local(client):
    """Cloud status reflects local-only mode."""
    response = client.get("/api/cloud/status")
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["provider"] == "local"
    assert data["cloud"] == "disabled"
