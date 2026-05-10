import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
from app.main import app


CHECKS = [
    ("GET", "/api/status", None),
    ("POST", "/api/nl-query", {"query": "Which VNFs are connected to Slice 1?"}),
    ("GET", "/api/proactive/latest", None),
    ("GET", "/api/proactive/forecast", None),
    ("POST", "/api/proactive/avoid", None),
    ("GET", "/api/explain/tab/dashboard", None),
    ("GET", "/api/explain/node/upf_1", None),
    ("GET", "/api/datasets/registry", None),
    ("GET", "/api/training/status", None),
    ("GET", "/api/open5gs/health", None),
    ("GET", "/api/realtime/analyse", None),
    ("POST", "/api/realtime/simulate-fix", {}),
    ("GET", "/api/open5gs-demo/health", None),
    ("POST", "/api/open5gs-demo/analyse", {}),
]


def main() -> None:
    client = TestClient(app)
    for method, path, payload in CHECKS:
        response = client.request(method, path, json=payload) if payload is not None else client.request(method, path)
        data = response.json()
        ok = response.status_code == 200 and data.get("ok", True) is True
        print(method, path, response.status_code, "PASS" if ok else "FAIL")
        if not ok:
            raise SystemExit(1)
    print("NetOracle V2 smoke verification passed.")


if __name__ == "__main__":
    main()
