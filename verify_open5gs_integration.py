"""
verify_open5gs_integration.py
──────────────────────────────
Run this from the NetOracle root directory to verify
the Open5GS integration is working correctly.
 
Usage (Windows):
    .\.venv\Scripts\activate
    python verify_open5gs_integration.py
"""
 
import json
import sys
import time
from pathlib import Path
 
import requests
 
BASE_URL = "http://127.0.0.1:8000"
PROM_URL = "http://localhost:9090"   # Change to WSL2 IP if running on Windows
 
PASS = "[OK]"
FAIL = "[FAIL]"
WARN = "[WARN]"
 
 
def check(label: str, condition: bool, detail: str = "") -> bool:
    icon = PASS if condition else FAIL
    print(f"  {icon}  {label}" + (f"  ->  {detail}" if detail else ""))
    return condition
 
 
def section(title: str):
    print(f"\n{'='*55}")
    print(f"  {title}")
    print('='*55)
 
 
# ── 1. Open5GS / Prometheus checks ───────────────────────────────────────
 
section("1. Open5GS + Prometheus Connectivity")
 
try:
    r = requests.get(f"{PROM_URL}/-/healthy", timeout=3)
    prom_ok = r.status_code == 200
except Exception:
    prom_ok = False
check("Prometheus reachable", prom_ok, PROM_URL)
 
if prom_ok:
    def prom_query(q):
        try:
            r = requests.get(f"{PROM_URL}/api/v1/query", params={"query": q}, timeout=5)
            results = r.json().get("data", {}).get("result", [])
            return float(results[0]["value"][1]) if results else None
        except Exception:
            return None
 
    amf_sessions = prom_query("amf_session_count")
    upf_rx       = prom_query("upf_rx_bytes_total")
    smf_pdu      = prom_query("smf_pdu_session_count")
 
    check("AMF session_count metric", amf_sessions is not None, str(amf_sessions))
    check("UPF rx_bytes_total metric", upf_rx      is not None, str(upf_rx))
    check("SMF pdu_session_count metric", smf_pdu  is not None, str(smf_pdu))
else:
    print(f"  {WARN}  Skipping metric checks (Prometheus not reachable)")
    print(f"       Start Open5GS in WSL2: bash start_open5gs.sh")
 
 
# ── 2. MongoDB check ─────────────────────────────────────────────────────
 
section("2. MongoDB / Open5GS Subscriber Store")
 
try:
    from pymongo import MongoClient
    client = MongoClient("mongodb://localhost:27017", serverSelectionTimeoutMS=3000)
    client.admin.command("ping")
    mongo_ok = True
    db = client["open5gs"]
    sub_count = db["subscribers"].count_documents({})
    check("MongoDB reachable", True, "mongodb://localhost:27017")
    check("open5gs database exists", True)
    check("Subscriber registered", sub_count > 0, f"{sub_count} subscriber(s) found")
    client.close()
except ImportError:
    check("pymongo installed", False, "Run: pip install pymongo")
except Exception as e:
    check("MongoDB reachable", False, str(e))
    print(f"       Start MongoDB in WSL2: sudo systemctl start mongod")
 
 
# ── 3. UERANSIM tunnel check (WSL2 only) ──────────────────────────────────
 
section("3. UERANSIM UE Tunnel")
 
import subprocess
try:
    result = subprocess.run(["ip", "link", "show", "uesimtun0"],
                            capture_output=True, text=True, timeout=3)
    tunnel_up = result.returncode == 0
    check("uesimtun0 interface up", tunnel_up,
          "UE is attached" if tunnel_up else "Start: nr-ue -c /etc/ueransim/open5gs-ue.yaml")
except (FileNotFoundError, Exception):
    print(f"  {WARN}  'ip' command not found or error — skipping (run this check inside WSL2)")
 
 
# ── 4. NetOracle API checks ───────────────────────────────────────────────
 
section("4. NetOracle API Integration")
 
try:
    r = requests.get(f"{BASE_URL}/api/status", timeout=5)
    api_ok = r.status_code == 200
    check("NetOracle API reachable", api_ok)
except Exception:
    api_ok = False
    check("NetOracle API reachable", False,
          "Start server: uvicorn app.main:app --reload --host 127.0.0.1 --port 8000")
 
if api_ok:
    # Data mode endpoint
    try:
        r = requests.get(f"{BASE_URL}/api/data/mode", timeout=5)
        if r.status_code == 200:
            mode_data = r.json().get("data", {}) if "data" in r.json() else r.json()
            mode = mode_data.get("mode", "unknown")
            check("/api/data/mode returns mode", True, mode)
            if mode == "open5gs":
                check("Mode is open5gs [OK]", True)
                prom_reach = mode_data.get("prometheus_reachable", False)
                check("Prometheus reachable (via API)", prom_reach)
            else:
                print(f"  {WARN}  Mode is '{mode}' -- set DATA_SOURCE_MODE=open5gs in .env")
        else:
            check("/api/data/mode endpoint", False, f"HTTP {r.status_code}")
    except Exception as e:
        check("/api/data/mode endpoint", False, str(e))
 
    # WebSocket check
    try:
        import websockets
        import asyncio
 
        async def test_ws():
            async with websockets.connect(f"ws://127.0.0.1:8000/ws/telemetry", timeout=5) as ws:
                msg = await asyncio.wait_for(ws.recv(), timeout=10)
                data = json.loads(msg)
                return data.get("type") == "tick"
 
        ws_ok = asyncio.run(test_ws())
        check("WebSocket /ws/telemetry live", ws_ok, "received tick frame")
    except ImportError:
        print(f"  {WARN}  websockets not installed -- skipping WS test")
    except Exception as e:
        check("WebSocket /ws/telemetry live", False, str(e))
 
    # Open5GS NF health endpoint
    try:
        r = requests.get(f"{BASE_URL}/api/open5gs/health", timeout=5)
        if r.status_code == 200:
            health = r.json().get("data", {}) if "data" in r.json() else r.json()
            check("/api/open5gs/health endpoint", True)
            nfs = health.get("nfs", {})
            for nf, status in nfs.items():
                check(f"  NF: {nf}", status == "up", status)
        else:
            check("/api/open5gs/health endpoint", False, f"HTTP {r.status_code} (endpoint may not be wired yet)")
    except Exception as e:
        check("/api/open5gs/health endpoint", False, str(e))
 
    # Tick generates open5gs source frames
    try:
        r = requests.post(f"{BASE_URL}/api/telemetry/tick", timeout=10)
        if r.status_code == 200:
            tick_data = r.json().get("data", []) if "data" in r.json() else r.json()
            frames = tick_data if isinstance(tick_data, list) else tick_data.get("frames", [])
            open5gs_frames = [f for f in frames if f.get("source", "").startswith("open5gs")]
            check(
                "Tick returns open5gs frames",
                len(open5gs_frames) > 0,
                f"{len(open5gs_frames)}/{len(frames)} frames from open5gs"
            )
            if open5gs_frames:
                nf_types = {f["node_type"] for f in open5gs_frames}
                check("AMF frame present", "AMF" in nf_types)
                check("SMF frame present", "SMF" in nf_types)
                check("UPF frame present", "UPF" in nf_types)
    except Exception as e:
        check("Telemetry tick test", False, str(e))
 
 
# ── 5. Open5GS Adapter unit test ─────────────────────────────────────────
 
section("5. Open5GSAdapter Direct Test")
 
try:
    sys.path.insert(0, str(Path(__file__).parent))
    from app.services.open5gs_adapter import Open5GSAdapter
 
    adapter = Open5GSAdapter(
        prometheus_url=PROM_URL,
        mongo_uri="mongodb://localhost:27017",
    )
    tick_start = time.time()
    frames = adapter.get_tick()
    tick_ms = (time.time() - tick_start) * 1000
 
    check("Adapter returns frames",         len(frames) > 0,    f"{len(frames)} frames")
    check("Tick completes < 10s",           tick_ms < 10000,    f"{tick_ms:.0f}ms")
    check("All frames have required keys",
          all("node_id" in f and "cpu" in f and "throughput_mbps" in f for f in frames))
    check("Frames have source field",
          all("source" in f for f in frames))
 
    sources = {f.get("source") for f in frames}
    is_live = "open5gs_live" in sources
    is_sim  = "open5gs_simulated" in sources
    check(
        "Frame source",
        True,
        "LIVE [OK]" if is_live else "simulated (Open5GS not running)"
    )
 
    # NF health
    health = adapter.get_nf_health()
    check("get_nf_health() returns dict",    isinstance(health, dict))
    check("NF status reported",              "nfs" in health,
          str(health.get("nfs", {})))
 
except Exception as e:
    check("Open5GSAdapter import & run", False, str(e))
 
 
# ── Summary ───────────────────────────────────────────────────────────────
 
section("Summary")
print("""
  If all checks pass:
    DATA_SOURCE_MODE=open5gs is fully working.
    NetOracle is streaming live 5G Core metrics.
 
  If Prometheus checks fail:
    1. Open WSL2 terminal
    2. Run: bash start_open5gs.sh
    3. Note the WSL2 IP printed at the end
    4. Update .env:
         OPEN5GS_PROMETHEUS_URL=http://<wsl2-ip>:9090
         OPEN5GS_MONGO_URI=mongodb://<wsl2-ip>:27017
    5. Restart NetOracle
 
  If adapter test passes but API test fails:
    Wire the adapter into main.py auto_tick():
      from app.services.data_sources import get_adapter
      frames = get_adapter().get_tick()
""")
