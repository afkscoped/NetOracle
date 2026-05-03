import json
from pathlib import Path
from typing import Any

import requests

from app.database import db
from app.settings import get_settings


class CloudSyncService:
    def config_status(self) -> dict[str, Any]:
        settings = get_settings()
        return {
            "provider": settings.cloud_provider,
            "aws_configured": bool(settings.aws_access_key_id and settings.aws_secret_access_key and settings.aws_s3_bucket),
            "supabase_configured": bool(settings.supabase_url and settings.supabase_service_role_key),
            "mode": "optional export-only; local app never depends on cloud",
        }

    def export_audit(self) -> dict[str, Any]:
        payload = {"kind": "audit", "entries": db.audit_entries(500)}
        return self._export_payload("netoracle-audit.json", payload)

    def export_benchmark(self) -> dict[str, Any]:
        path = Path("reports/latest_benchmark.json")
        payload = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"kind": "benchmark", "message": "No benchmark report exists yet."}
        return self._export_payload("netoracle-benchmark.json", payload)

    def _export_payload(self, filename: str, payload: dict[str, Any]) -> dict[str, Any]:
        settings = get_settings()
        exports = Path("exports")
        exports.mkdir(exist_ok=True)
        local_path = exports / filename
        local_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        if settings.cloud_provider.lower() == "supabase" and settings.supabase_url and settings.supabase_service_role_key:
            return self._export_supabase(filename, local_path)
        if settings.cloud_provider.lower() == "aws":
            return self._export_aws(filename, local_path)
        result = {"provider": "local", "status": "saved", "path": str(local_path), "note": "Set CLOUD_PROVIDER=supabase or aws to export to a free-tier cloud account."}
        db.audit("cloud_export", result)
        return result

    def _export_supabase(self, filename: str, local_path: Path) -> dict[str, Any]:
        settings = get_settings()
        bucket = settings.supabase_bucket or "netoracle"
        url = f"{settings.supabase_url.rstrip('/')}/storage/v1/object/{bucket}/{filename}"
        headers = {"Authorization": f"Bearer {settings.supabase_service_role_key}", "Content-Type": "application/json", "x-upsert": "true"}
        response = requests.post(url, headers=headers, data=local_path.read_bytes(), timeout=20)
        result = {"provider": "supabase", "status": "uploaded" if response.ok else "failed", "http_status": response.status_code, "object": filename}
        db.audit("cloud_export", result)
        return result

    def _export_aws(self, filename: str, local_path: Path) -> dict[str, Any]:
        try:
            import boto3
        except Exception:
            result = {"provider": "aws", "status": "missing_dependency", "install": "pip install boto3", "local_path": str(local_path)}
            db.audit("cloud_export", result)
            return result
        settings = get_settings()
        client = boto3.client(
            "s3",
            aws_access_key_id=settings.aws_access_key_id,
            aws_secret_access_key=settings.aws_secret_access_key,
            region_name=settings.aws_region,
        )
        client.upload_file(str(local_path), settings.aws_s3_bucket, filename)
        result = {"provider": "aws", "status": "uploaded", "bucket": settings.aws_s3_bucket, "object": filename}
        db.audit("cloud_export", result)
        return result


cloud_sync_service = CloudSyncService()
