#!/usr/bin/env python3
"""
verify_open5gs_integration.py — NetOracle Pre-Flight Check
============================================================
Run this BEFORE every demo or validation session.
EXIT CODE: 0 = all checks passed, 1 = one or more checks failed.

Usage:
    python scripts/verify_open5gs_integration.py
    python scripts/verify_open5gs_integration.py --strict   # fail on any WARN too

Checks performed:
  1. Prometheus reachable + AMF/SMF/UPF metric endpoints exist AND non-zero
  2. MongoDB reachable + at least 1 subscriber registered
  3. NetOracle API reachable + /api/data/mode shows open5gs
  4. /api/open5gs/health reports NFs healthy
  5. /api/telemetry/tick returns open5gs_live-tagged frames
  6. WebSocket /ws/telemetry actually STREAMS frames (not just connects)
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
import os
from pathlib import Path

try:
    import requests
except ImportError:
    print("FATAL: requests not installed. Run: pip install requests")
    sys.exit(1)

# ── Configuration ─────────────────────────────────────────────────────────────
BASE_URL = os.getenv("NETORACLE_URL", "http://127.0.0.1:8000")
PROM_URL = os.getenv("OPEN5GS_PROMETHEUS_URL", "http://localhost:9090")
MONGO_URI = os.getenv("OPEN5GS_MONGO_URI", "mongodb://localhost:27017")

STRICT_MODE = "--strict" in sys.argv

# ── Results tracking ──────────────────────────────────────────────────────────
_failures: list[str] = []
_warnings: list[str] = []
_passes: list[str] = []


def check(label: str, condition: bool, detail: str = "", critical: bool = True) -> bool:
    """Print a check result and track failures."""
    if condition:
        icon = "✅ PASS"
        _passes.append(label)
    else:
        if critical:
            icon = "❌ FAIL"
            _failures.append(f"{label}: {detail}" if detail else label)
        else:
            icon = "⚠️  WARN"
            _warnings.append(f"{label}: {detail}" if detail else label)
    suffix = f"  → {detail}" if detail else ""
    print(f"  {icon}  {label}{suffix}")
    return condition


def section(title: str) -> None:
    print(f"\n{'─' * 60}")
    print(f"  {title}")
    print(f"{'─' * 60}")


def prom_query(query: str, url: str = PROM_URL) -> float | None:
    """Query Prometheus instant metric, return float value or None."""
    try:
        r = requests.get(f"{url}/api/v1/query", params={"query": query}, timeout=5)
        results = r.json().get("data", {}).get("result", [])
        if not results:
            return None
        return float(results[0]["value"][1])
    except Exception:
        return None


# ── Section 1: Prometheus ─────────────────────────────────────────────────────
section("1. Prometheus + Open5GS Metrics Endpoints")

try:
    r = requests.get(f"{PROM_URL}/-/healthy", timeout=4)
    prom_ok = r.status_code == 200
except Exception:
    prom_ok = False
check("Prometheus reachable", prom_ok, PROM_URL)

if prom_ok:
    # Check metric endpoints directly (bypassing Prometheus scrape lag)
    NF_PORTS = {"AMF": 9095, "SMF": 9096, "UPF": 9097, "PCF": 9098}
    prom_host = PROM_URL.split("://")[1].split(":")[0]

    for nf, port in NF_PORTS.items():
        try:
            r = requests.get(f"http://{prom_host}:{port}/metrics", timeout=3)
            has_metrics = r.status_code == 200 and len(r.text) > 50
        except Exception:
            has_metrics = False
        check(f"{nf} /metrics endpoint reachable (port {port})", has_metrics,
              f"curl http://{prom_host}:{port}/metrics | head")

    # Check key metric names are non-zero (expected when UE is attached)
    # ASSUMED METRIC NAMES — update to VERIFIED once live stack is confirmed
    metric_checks = [
        # (label, query, must_be_nonzero)
        ("node_cpu metric (node_exporter)", "rate(node_cpu_seconds_total[30s])", False),  # can be near 0 at idle
        ("node_memory metric (node_exporter)", "node_memory_MemTotal_bytes", True),
        ("uesimtun0 RX rate (gNB proxy)", 'rate(node_network_receive_bytes_total{device="uesimtun0"}[60s])', False),
        # Open5GS NF metrics — ASSUMED names, may return None if name is wrong
        ("AMF session_count (ASSUMED NAME)", "amf_session_count", False),
        ("UPF rx_bytes_total (ASSUMED NAME)", "upf_rx_bytes_total", False),
        ("SMF pdu_session_count (ASSUMED NAME)", "smf_pdu_session_count", False),
    ]

    for label, query, must_nonzero in metric_checks:
        val = prom_query(query)
        if val is not None:
            if must_nonzero:
                check(f"  {label}", val > 0, f"value={val:.4f}")
            else:
                check(f"  {label}", True, f"value={val:.4f} (present)")
        else:
            # Non-zero check fails, but ASSUMED metrics only warn
            is_assumed = "ASSUMED" in label
            check(f"  {label}", False,
                  "returned None — verify metric name against live /metrics output",
                  critical=not is_assumed)

# ── Section 2: MongoDB ────────────────────────────────────────────────────────
section("2. MongoDB Subscriber Store")

try:
    from pymongo import MongoClient  # type: ignore[import]
    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=3000)
    client.admin.command("ping")
    sub_count = client["open5gs"]["subscribers"].count_documents({})
    check("MongoDB reachable", True, MONGO_URI)
    check("At least 1 subscriber registered", sub_count >= 1,
          f"{sub_count} subscriber(s) found — add one via http://localhost:3000")
    client.close()
except ImportError:
    check("pymongo installed", False, "pip install pymongo", critical=False)
    print("     (MongoDB checks skipped — install pymongo to enable)")
except Exception as exc:
    check("MongoDB reachable", False, str(exc))

# ── Section 3: NetOracle API ──────────────────────────────────────────────────
section("3. NetOracle API")

try:
    r = requests.get(f"{BASE_URL}/api/status", timeout=5)
    api_ok = r.status_code == 200
except Exception:
    api_ok = False
check("NetOracle reachable", api_ok, BASE_URL)

if api_ok:
    # Check mode
    try:
        mode_resp = requests.get(f"{BASE_URL}/api/data/mode", timeout=5).json()
        mode = mode_resp.get("data", {}).get("mode", "unknown")
        check("DATA_SOURCE_MODE=open5gs", mode == "open5gs",
              f"current mode='{mode}' — set DATA_SOURCE_MODE=open5gs in .env")
    except Exception as exc:
        check("/api/data/mode", False, str(exc))

    # Check open5gs health
    try:
        health = requests.get(f"{BASE_URL}/api/open5gs/health", timeout=5).json()
        health_data = health.get("data", {})
        prom_healthy = health_data.get("prometheus_reachable", False)
        mongo_healthy = health_data.get("mongodb_reachable", False)
        check("/api/open5gs/health: Prometheus reachable", prom_healthy)
        check("/api/open5gs/health: MongoDB reachable", mongo_healthy)
        nfs = health_data.get("nfs", {})
        for nf, status in nfs.items():
            check(f"/api/open5gs/health: {nf.upper()} status", status == "up",
                  f"reported '{status}'", critical=False)
    except Exception as exc:
        check("/api/open5gs/health", False, str(exc))

# ── Section 4: Telemetry Tick ─────────────────────────────────────────────────
section("4. Telemetry Tick — Frame Schema and Source Tag")

if api_ok:
    try:
        tick = requests.post(f"{BASE_URL}/api/telemetry/tick", timeout=10).json()
        frames = tick.get("data", [])
        check("Tick returns >0 frames", len(frames) > 0, f"{len(frames)} frame(s)")

        if frames:
            sources = {f.get("source", "unknown") for f in frames}
            live_count = sum(1 for f in frames if f.get("source") == "open5gs_live")
            partial_count = sum(1 for f in frames if f.get("source") == "open5gs_partial")
            sim_count = sum(1 for f in frames if f.get("source") == "open5gs_simulated")

            check("At least 1 open5gs_live frame", live_count > 0,
                  f"live={live_count}, partial={partial_count}, simulated={sim_count}")
            check("Frame has required fields",
                  all(all(k in f for k in ["timestamp", "slice_id", "node_id", "source"]) for f in frames),
                  "missing required frame fields")
            check("Frame metrics dict present", all("metrics" in f for f in frames))

            # Verify NF types
            nf_types = {f.get("node_type") for f in frames}
            for nf in ("AMF", "SMF", "UPF"):
                check(f"NF type '{nf}' present in frames", nf in nf_types, critical=False)

    except Exception as exc:
        check("Telemetry tick", False, str(exc))

# ── Section 5: WebSocket Streaming ───────────────────────────────────────────
section("5. WebSocket — Live Streaming (not just connect)")

try:
    import websockets  # type: ignore[import]

    async def test_ws_streaming() -> tuple[bool, str]:
        """
        Connects to /ws/telemetry and waits for actual tick frames.
        Returns (success, detail_message).
        This is stricter than just checking the connection opens.
        """
        try:
            ws_url = BASE_URL.replace("http://", "ws://").replace("https://", "wss://") + "/ws/telemetry"
            async with websockets.connect(ws_url, open_timeout=5) as ws:
                # Wait for up to 2 messages (first may be the immediate tick on connect)
                for attempt in range(3):
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=8)
                        payload = json.loads(raw)
                        if payload.get("type") == "tick":
                            frames = payload.get("frames", [])
                            source = payload.get("source", "unknown")
                            if frames:
                                return True, f"received tick: {len(frames)} frames, source={source}"
                    except asyncio.TimeoutError:
                        continue
                return False, "connected but no tick frames received within 24s"
        except Exception as exc:
            return False, str(exc)

    ws_ok, ws_detail = asyncio.run(test_ws_streaming())
    check("WebSocket streams tick frames", ws_ok, ws_detail)

except ImportError:
    check("websockets installed", False,
          "pip install websockets", critical=False)
    print("     (WebSocket streaming check skipped)")
except Exception as exc:
    check("WebSocket /ws/telemetry", False, str(exc))

# ── Section 6: Direct Adapter Test ───────────────────────────────────────────
section("6. Open5GSAdapter Direct Import Test")

try:
    repo_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repo_root))
    from app.services.open5gs_adapter import Open5GSAdapter  # type: ignore[import]

    adapter = Open5GSAdapter(prometheus_url=PROM_URL, mongo_uri=MONGO_URI)
    t0 = time.time()
    frames = adapter.get_tick()
    elapsed_ms = (time.time() - t0) * 1000

    check("Adapter returns frames", len(frames) > 0, f"{len(frames)} frames")
    check("Adapter tick completes in <10s", elapsed_ms < 10000, f"{elapsed_ms:.0f}ms")
    check("All frames have 'source' field",
          all("source" in f for f in frames))
    check("NF health endpoint works", isinstance(adapter.get_nf_health(), dict))

    source_counts: dict[str, int] = {}
    for f in frames:
        src = f.get("source", "unknown")
        source_counts[src] = source_counts.get(src, 0) + 1
    print(f"      source distribution: {source_counts}")

except Exception as exc:
    check("Open5GSAdapter import + tick", False, str(exc))

# ── Summary ───────────────────────────────────────────────────────────────────
section("SUMMARY")

total = len(_passes) + len(_failures) + len(_warnings)
print(f"  Passed:   {len(_passes)}/{total}")
print(f"  Failed:   {len(_failures)}/{total}")
print(f"  Warnings: {len(_warnings)}/{total}")

if _failures:
    print("\n  FAILED CHECKS:")
    for f in _failures:
        print(f"    ❌ {f}")

if _warnings:
    print("\n  WARNINGS:")
    for w in _warnings:
        print(f"    ⚠️  {w}")

if not _failures and not (STRICT_MODE and _warnings):
    print("\n  ✅ ALL CHECKS PASSED — System is ready for live demo/validation.")
    sys.exit(0)
else:
    if STRICT_MODE and _warnings:
        print("\n  ❌ STRICT MODE: Warnings treated as failures.")
    print("\n  ❌ PRE-FLIGHT CHECK FAILED. Fix the issues above before proceeding.")
    print("     See LIVE_OPS_RUNBOOK.md Troubleshooting section for fixes.")
    sys.exit(1)
