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
        self.cloud_provider = os.getenv("CLOUD_PROVIDER", env_file.get("CLOUD_PROVIDER", "none"))
        self.aws_access_key_id = os.getenv("AWS_ACCESS_KEY_ID", env_file.get("AWS_ACCESS_KEY_ID", ""))
        self.aws_secret_access_key = os.getenv("AWS_SECRET_ACCESS_KEY", env_file.get("AWS_SECRET_ACCESS_KEY", ""))
        self.aws_region = os.getenv("AWS_REGION", env_file.get("AWS_REGION", "ap-south-1"))
        self.aws_s3_bucket = os.getenv("AWS_S3_BUCKET", env_file.get("AWS_S3_BUCKET", ""))
        self.aws_dynamodb_table = os.getenv("AWS_DYNAMODB_TABLE", env_file.get("AWS_DYNAMODB_TABLE", ""))
        self.supabase_url = os.getenv("SUPABASE_URL", env_file.get("SUPABASE_URL", ""))
        self.supabase_service_role_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", env_file.get("SUPABASE_SERVICE_ROLE_KEY", ""))
        self.supabase_bucket = os.getenv("SUPABASE_BUCKET", env_file.get("SUPABASE_BUCKET", "netoracle"))

    @property
    def db_path(self) -> Path:
        return Path(self.database_path).expanduser().resolve()

    @property
    def model_names(self) -> list[str]:
        return [item.strip() for item in self.ollama_models.split(",") if item.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
