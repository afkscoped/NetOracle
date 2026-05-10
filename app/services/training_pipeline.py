import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.database import db


class TrainingPipelineService:
    def __init__(self) -> None:
        self.process: subprocess.Popen | None = None
        self.started_at: str | None = None
        self.command: list[str] | None = None
        self.artifacts_dir = Path("artifacts/models")
        self.status_file = Path("artifacts/training_status.json")

    def cuda_status(self) -> dict[str, Any]:
        try:
            import torch
            available = bool(torch.cuda.is_available())
            return {
                "torch_installed": True,
                "cuda_available": available,
                "device_count": torch.cuda.device_count() if available else 0,
                "device_name": torch.cuda.get_device_name(0) if available else None,
                "torch_version": torch.__version__,
            }
        except Exception as exc:
            return {"torch_installed": False, "cuda_available": False, "error": str(exc)}

    def start(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self.process and self.process.poll() is None:
            return {"status": "already_running", **self.status()}
        script = Path("training/train_ctgnn_cuda.py")
        data = payload.get("data", "data/sample_telemetry.csv")
        epochs = int(payload.get("epochs", 8))
        batch_size = int(payload.get("batch_size", 256))
        hidden_dim = int(payload.get("hidden_dim", 128))
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        command = [sys.executable, str(script), "--data", str(data), "--epochs", str(epochs), "--batch-size", str(batch_size), "--hidden-dim", str(hidden_dim)]
        if payload.get("cpu"):
            command.append("--cpu")
        self.command = command
        self.started_at = datetime.now(timezone.utc).isoformat()
        if not script.exists():
            result = {"status": "not_started", "error": f"Training script missing: {script}", "cuda": self.cuda_status()}
            self._write_status(result)
            return result
        log_path = Path("artifacts/training.log")
        log_path.parent.mkdir(exist_ok=True)
        log_handle = log_path.open("a", encoding="utf-8")
        self.process = subprocess.Popen(command, stdout=log_handle, stderr=subprocess.STDOUT)
        result = {"status": "running", "pid": self.process.pid, "started_at": self.started_at, "command": command, "log": str(log_path), "cuda": self.cuda_status()}
        self._write_status(result)
        db.audit("training_started", result)
        return result

    def status(self) -> dict[str, Any]:
        running = bool(self.process and self.process.poll() is None)
        status = {
            "status": "running" if running else "idle",
            "pid": self.process.pid if self.process else None,
            "returncode": None if running or not self.process else self.process.returncode,
            "started_at": self.started_at,
            "command": self.command,
            "cuda": self.cuda_status(),
            "artifacts": self._artifacts(),
        }
        if self.status_file.exists():
            try:
                status["last_checkpoint"] = json.loads(self.status_file.read_text(encoding="utf-8"))
            except Exception:
                pass
        return status

    def stop(self) -> dict[str, Any]:
        if self.process and self.process.poll() is None:
            self.process.terminate()
            time.sleep(0.5)
            if self.process.poll() is None:
                self.process.kill()
            result = {"status": "stopped", "pid": self.process.pid}
            db.audit("training_stopped", result)
            return result
        return {"status": "not_running"}

    def metrics(self) -> dict[str, Any]:
        summary = Path("artifacts/training_summary.json")
        if summary.exists():
            try:
                return json.loads(summary.read_text(encoding="utf-8"))
            except Exception as exc:
                return {"status": "unreadable", "error": str(exc)}
        return {"status": "no_metrics", "message": "Run training first or place training_summary.json in artifacts/."}

    def _artifacts(self) -> list[str]:
        if not self.artifacts_dir.exists():
            return []
        return [str(path) for path in self.artifacts_dir.glob("*.pt")]

    def _write_status(self, payload: dict[str, Any]) -> None:
        self.status_file.parent.mkdir(exist_ok=True)
        self.status_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")


training_pipeline_service = TrainingPipelineService()
