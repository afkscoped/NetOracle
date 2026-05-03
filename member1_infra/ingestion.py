import time
import json
from datetime import datetime, timezone
from pathlib import Path
import requests

API = "http://127.0.0.1:8000/api/data/upload-telemetry"


def create_sample_telemetry():
    data = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "metrics": {"cpu": 50, "latency": 20}
    }
    Path("sample.json").write_text(json.dumps(data))
    return "sample.json"


def upload(file):
    with open(file, "rb") as f:
        return requests.post(API, files={"file": f})


def upload_file(file):
    return upload(file)


def continuous_ingestion(file_path, interval=5):
    while True:
        try:
            res = upload(file_path)
            print("STATUS:", res.status_code)
        except Exception as e:
            print("ERROR:", e)

        time.sleep(interval)


if __name__ == "__main__":
    file_path = create_sample_telemetry()
    continuous_ingestion(file_path)
