import os
import pytest
from unittest.mock import patch, MagicMock

# Ensure we have some test audit entries by triggering an audit event
def test_export_audit_local(client):
    response = client.post("/api/cloud/export-audit")
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["provider"] == "local"
    assert data["status"] == "saved"

@patch("app.services.cloud_sync.get_settings")
@patch("app.services.cloud_sync.requests.post")
def test_export_audit_supabase(mock_post, mock_get_settings, client):
    mock_settings = MagicMock()
    mock_settings.cloud_provider = "supabase"
    mock_settings.supabase_url = "http://mock"
    mock_settings.supabase_service_role_key = "key"
    mock_settings.supabase_bucket = "netoracle"
    mock_get_settings.return_value = mock_settings

    mock_response = MagicMock()
    mock_response.ok = True
    mock_response.status_code = 200
    mock_post.return_value = mock_response

    response = client.post("/api/cloud/export-audit")
    assert response.status_code == 200
    data = response.json()["data"]
    
    assert data["provider"] == "supabase"
    assert data["status"] == "uploaded"
    mock_post.assert_called_once()

import sys

@patch("app.services.cloud_sync.get_settings")
@patch.dict(sys.modules, {"boto3": MagicMock()})
def test_export_benchmark_aws(mock_get_settings, client):
    import boto3
    mock_settings = MagicMock()
    mock_settings.cloud_provider = "aws"
    mock_settings.aws_access_key_id = "mock"
    mock_settings.aws_secret_access_key = "mock"
    mock_settings.aws_s3_bucket = "mock-bucket"
    mock_settings.aws_region = "ap-south-1"
    mock_get_settings.return_value = mock_settings

    mock_client_instance = MagicMock()
    boto3.client.return_value = mock_client_instance

    response = client.post("/api/cloud/export-benchmark")
    assert response.status_code == 200
    data = response.json()["data"]
    
    assert data["provider"] == "aws"
    assert data["status"] == "uploaded"
    mock_client_instance.upload_file.assert_called_once()
