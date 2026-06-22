from functools import lru_cache
import os
from pathlib import Path


def _load_env_file() -> dict[str, str]:
    env_path = Path(".env")
    values: dict[str, str] = {}
    if not env_path.exists():
        return values
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


class Settings:
    def __init__(self) -> None:
        env_file = _load_env_file()
        self.app_name = os.getenv("APP_NAME", env_file.get("APP_NAME", "NetOracle"))
        self.app_env = os.getenv("APP_ENV", env_file.get("APP_ENV", "development"))
        self.database_path = os.getenv("DATABASE_PATH", env_file.get("DATABASE_PATH", "./data/netoracle.db"))
        self.ollama_base_url = os.getenv("OLLAMA_BASE_URL", env_file.get("OLLAMA_BASE_URL", "http://localhost:11434"))
        self.ollama_models = os.getenv("OLLAMA_MODELS", env_file.get("OLLAMA_MODELS", "phi3:mini,mistral:7b,llama3.1:8b"))
        self.slack_webhook_url = os.getenv("SLACK_WEBHOOK_URL", env_file.get("SLACK_WEBHOOK_URL", ""))
        self.openai_api_key = os.getenv("OPENAI_API_KEY", env_file.get("OPENAI_API_KEY", ""))
        self.groq_api_key = os.getenv("GROQ_API_KEY", env_file.get("GROQ_API_KEY", ""))
        self.confidence_threshold = float(os.getenv("CONFIDENCE_THRESHOLD", env_file.get("CONFIDENCE_THRESHOLD", "0.60")))
        self.remediation_mode = os.getenv("REMEDIATION_MODE", env_file.get("REMEDIATION_MODE", "simulation"))
        self.cloud_provider = os.getenv("CLOUD_PROVIDER", env_file.get("CLOUD_PROVIDER", "local"))
        self.data_source_mode = os.getenv("DATA_SOURCE_MODE", env_file.get("DATA_SOURCE_MODE", "open5gs"))
        self.open5gs_prometheus_url = os.getenv(
            "OPEN5GS_PROMETHEUS_URL",
            env_file.get("OPEN5GS_PROMETHEUS_URL", "http://localhost:9090"),
        )
        self.open5gs_mongo_uri = os.getenv(
            "OPEN5GS_MONGO_URI",
            env_file.get("OPEN5GS_MONGO_URI", "mongodb://localhost:27017"),
        )
        self.open5gs_webui_url = os.getenv(
            "OPEN5GS_WEBUI_URL",
            env_file.get("OPEN5GS_WEBUI_URL", "http://localhost:3000"),
        )
        self.open5gs_poll_interval_s = int(os.getenv("OPEN5GS_POLL_INTERVAL_S", env_file.get("OPEN5GS_POLL_INTERVAL_S", "5")))
        self.prometheus_url = os.getenv("PROMETHEUS_URL", env_file.get("PROMETHEUS_URL", "http://localhost:9090"))

    @property
    def db_path(self) -> Path:
        resolved_path = Path(self.database_path).expanduser().resolve()
        import sys
        if sys.platform.startswith("linux") and str(resolved_path).startswith("/mnt/"):
            return Path("/tmp/netoracle.db")
        return resolved_path

    @property
    def model_names(self) -> list[str]:
        return [item.strip() for item in self.ollama_models.split(",") if item.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
