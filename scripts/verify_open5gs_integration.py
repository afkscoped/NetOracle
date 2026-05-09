from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import time
import os
from pathlib import Path

import requests

BASE_URL = "http://127.0.0.1:8000"
PROM_URL = os.getenv("OPEN5GS_PROMETHEUS_URL", "http://localhost:9090")
MONGO_URI = os.getenv("OPEN5GS_MONGO_URI", "mongodb://localhost:27017")


def check(label: str, condition: bool, detail: str = "") -> bool:
    icon = "PASS" if condition else "FAIL"
    suffix = f" - {detail}" if detail else ""
    print(f"  [{icon}] {label}{suffix}")
    return condition


def section(title: str) -> None:
    print("\n" + "=" * 60)
    print(title)
    print("=" * 60)


def prom_query(query: str):
    try:
        response = requests.get(f"{PROM_URL}/api/v1/query", params={"query": query}, timeout=5)
        results = response.json().get("data", {}).get("result", [])
        return float(results[0]["value"][1]) if results else None
    except Exception:
        return None


section("1. Open5GS + Prometheus")
try:
    response = requests.get(f"{PROM_URL}/-/healthy", timeout=3)
    prom_ok = response.status_code == 200
except Exception:
    prom_ok = False
check("Prometheus reachable", prom_ok, PROM_URL)
if prom_ok:
    check("AMF session metric", prom_query("amf_session_count") is not None)
    check("SMF PDU metric", prom_query("smf_pdu_session_count") is not None)
    check("UPF RX metric", prom_query("upf_rx_bytes_total") is not None)

section("2. MongoDB Subscriber Store")
try:
    from pymongo import MongoClient

    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=3000)
    client.admin.command("ping")
    subscriber_count = client["open5gs"]["subscribers"].count_documents({})
    check("MongoDB reachable", True, MONGO_URI)
    check("Subscriber registered", subscriber_count > 0, f"{subscriber_count} subscriber(s)")
    client.close()
except ImportError:
    check("pymongo installed", False, "Run: python -m pip install pymongo")
except Exception as exc:
    check("MongoDB reachable", False, str(exc))

section("3. UERANSIM Tunnel")
try:
    result = subprocess.run(["ip", "link", "show", "uesimtun0"], capture_output=True, text=True, timeout=3)
    check("uesimtun0 interface up", result.returncode == 0)
except FileNotFoundError:
    print("  [WARN] ip command not found; tunnel check is only available inside WSL2/Linux")

section("4. NetOracle API")
try:
    response = requests.get(f"{BASE_URL}/api/status", timeout=5)
    api_ok = response.status_code == 200
except Exception:
    api_ok = False
check("NetOracle API reachable", api_ok, BASE_URL)

if api_ok:
    mode = requests.get(f"{BASE_URL}/api/data/mode", timeout=5).json()
    check("/api/data/mode", mode.get("ok") is True, json.dumps(mode.get("data", {})))

    health = requests.get(f"{BASE_URL}/api/open5gs/health", timeout=5).json()
    check("/api/open5gs/health", health.get("ok") is True, json.dumps(health.get("data", {})))

    tick = requests.post(f"{BASE_URL}/api/telemetry/tick", timeout=10).json()
    frames = tick.get("data", [])
    open5gs_frames = [frame for frame in frames if str(frame.get("source", "")).startswith("open5gs")]
    check("Telemetry tick returns frames", len(frames) > 0, f"{len(frames)} frame(s)")
    check("Telemetry frame schema is nested", all("metrics" in frame for frame in frames))
    if open5gs_frames:
        nf_types = {frame.get("node_type") for frame in open5gs_frames}
        check("Open5GS AMF frame present", "AMF" in nf_types)
        check("Open5GS SMF frame present", "SMF" in nf_types)
        check("Open5GS UPF frame present", "UPF" in nf_types)

    try:
        import websockets

        async def test_ws() -> bool:
            async with websockets.connect("ws://127.0.0.1:8000/ws/telemetry", open_timeout=5) as ws:
                message = await asyncio.wait_for(ws.recv(), timeout=10)
                payload = json.loads(message)
                return payload.get("type") == "tick" and bool(payload.get("frames"))

        check("WebSocket /ws/telemetry", asyncio.run(test_ws()))
    except ImportError:
        print("  [WARN] websockets not installed; skipping WebSocket check")
    except Exception as exc:
        check("WebSocket /ws/telemetry", False, str(exc))

section("5. Adapter Direct Test")
try:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from app.services.open5gs_adapter import Open5GSAdapter

    adapter = Open5GSAdapter(prometheus_url=PROM_URL, mongo_uri=MONGO_URI)
    started = time.time()
    frames = adapter.get_tick()
    elapsed_ms = (time.time() - started) * 1000
    check("Adapter returns frames", len(frames) > 0, f"{len(frames)} frame(s)")
    check("Adapter tick under 10s", elapsed_ms < 10000, f"{elapsed_ms:.0f}ms")
    check("Required flat fields present", all("node_id" in frame and "cpu" in frame for frame in frames))
    check("NF health returns dict", isinstance(adapter.get_nf_health(), dict))
except Exception as exc:
    check("Open5GSAdapter direct test", False, str(exc))

section("Summary")
print("Use DATA_SOURCE_MODE=open5gs after WSL2 Open5GS is running. Offline fallback should still emit Open5GS-shaped simulated frames.")
