import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.database import db


class CloudSyncService:
    def config_status(self) -> dict[str, Any]:
        return {
            "provider": "local",
            "mode": "local_json_export",
            "cloud": "disabled",
            "exports_dir": str(Path("exports").resolve()),
        }

    def export_audit(self) -> dict[str, Any]:
        payload = {"kind": "audit", "entries": db.audit_entries(500)}
        filename = f"netoracle-audit-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}.json"
        return self._export_payload(filename, payload)

    def export_benchmark(self) -> dict[str, Any]:
        path = Path("reports/latest_benchmark.json")
        payload = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"kind": "benchmark", "message": "No benchmark report exists yet."}
        filename = f"netoracle-benchmark-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}.json"
        return self._export_payload(filename, payload)

    def _export_payload(self, filename: str, payload: dict[str, Any]) -> dict[str, Any]:
        exports = Path("exports")
        exports.mkdir(exist_ok=True)
        local_path = exports / filename
        local_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        result = {"provider": "local", "status": "saved", "path": str(local_path), "method": "local_json"}
        db.audit("cloud_export", result)
        return result


cloud_sync_service = CloudSyncService()
