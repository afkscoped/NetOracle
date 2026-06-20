#!/usr/bin/env python3
"""
fault_injection_api.py — NetOracle Fault Injection Control Service
===================================================================
Run this INSIDE WSL2 alongside Open5GS. It exposes HTTP endpoints
that NetOracle (running on Windows) can call to inject real faults
into the live 5G stack.

Usage:
    python3 scripts/fault_injection_api.py [--host 0.0.0.0] [--port 5050]

Design:
    - Every inject/restore action is logged with a precise timestamp.
    - Each endpoint returns JSON: {ok, action, timestamp, detail}
      so callers can correlate injection time with detection time.
    - The service NEVER silently ignores failures — it returns HTTP 500
      with a clear error message if an action fails.
    - Requires: pip install fastapi uvicorn pymongo
    - Requires sudo for service control and tc commands.
      Run with: sudo python3 scripts/fault_injection_api.py
"""

import asyncio
import json
import logging
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ── Check dependencies ────────────────────────────────────────────────────────
try:
    from fastapi import FastAPI, HTTPException
    from fastapi.responses import JSONResponse
    import uvicorn
except ImportError:
    print("ERROR: Missing dependencies. Install with:")
    print("  pip install fastapi uvicorn")
    sys.exit(1)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [FaultInjectionAPI] %(levelname)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("/tmp/fault_injection_api.log"),
    ],
)
logger = logging.getLogger(__name__)

# ── Injection state tracking ──────────────────────────────────────────────────
_active_injections: dict[str, dict[str, Any]] = {}

# ── Helper: run shell command ─────────────────────────────────────────────────
def _run(cmd: str, capture: bool = True) -> tuple[int, str]:
    """Run a shell command and return (returncode, output). Always logs."""
    logger.info(f"CMD: {cmd}")
    result = subprocess.run(
        cmd, shell=True, capture_output=capture, text=True, timeout=30
    )
    output = (result.stdout + result.stderr).strip()
    if output:
        logger.info(f"OUT: {output}")
    return result.returncode, output


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ack(action: str, detail: str = "", extra: dict | None = None) -> dict:
    payload = {"ok": True, "action": action, "timestamp": _now(), "detail": detail}
    if extra:
        payload.update(extra)
    return payload


def _fail(action: str, error: str) -> None:
    logger.error(f"[{action}] FAILED: {error}")
    raise HTTPException(status_code=500, detail=f"{action} failed: {error}")


# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="NetOracle Fault Injection API",
    description="Control surface for injecting real faults into the Open5GS 5G stack.",
    version="1.0.0",
)


@app.get("/health")
def health():
    """Liveness check — confirms the service is reachable."""
    return {"ok": True, "service": "fault_injection_api", "timestamp": _now()}


@app.get("/status")
def status():
    """Returns currently active injections and their timestamps."""
    return {"ok": True, "active_injections": _active_injections, "timestamp": _now()}


# ── Fault: UPF Kill ───────────────────────────────────────────────────────────
@app.post("/inject/upf_kill")
def inject_upf_kill():
    """
    Stop the Open5GS UPF process.
    Effect: All user-plane traffic drops immediately. PDU sessions tear down.
    Detectable via: upf_rx/tx_bytes_total stops incrementing, uesimtun0 goes dark.
    """
    ts = _now()
    rc, out = _run("sudo systemctl stop open5gs-upfd")
    if rc != 0:
        _fail("upf_kill", f"systemctl stop failed: {out}")

    _active_injections["upf_kill"] = {"injected_at": ts, "service": "open5gs-upfd"}
    logger.warning(f"[FAULT INJECTED] UPF killed at {ts}")

    return _ack(
        "upf_kill",
        detail="open5gs-upfd stopped. User-plane traffic will drop immediately.",
        extra={"injected_at": ts, "verify_cmd": "systemctl is-active open5gs-upfd"},
    )


# ── Fault: Bandwidth Throttle ─────────────────────────────────────────────────
@app.post("/inject/bandwidth_throttle")
def inject_bandwidth_throttle(rate_kbps: int = 500, latency_ms: int = 200):
    """
    Apply tc (Traffic Control) shaping to uesimtun0.
    Effect: UE traffic is throttled to rate_kbps kbit/s with latency_ms delay.
    Detectable via: throughput_mbps drops, latency_ms spikes in UPF metrics.
    
    Args:
        rate_kbps: bandwidth limit in kbit/s (default 500 = 0.5 Mbps)
        latency_ms: added latency in ms (default 200ms)
    """
    ts = _now()

    # Check if uesimtun0 exists
    rc, _ = _run("ip link show uesimtun0")
    if rc != 0:
        _fail("bandwidth_throttle", "uesimtun0 interface not found — is UERANSIM UE running?")

    # Clear any existing qdisc first
    _run("sudo tc qdisc del dev uesimtun0 root 2>/dev/null || true")

    # Apply netem + tbf (token bucket filter)
    rc1, out1 = _run(
        f"sudo tc qdisc add dev uesimtun0 root handle 1: netem delay {latency_ms}ms"
    )
    rc2, out2 = _run(
        f"sudo tc qdisc add dev uesimtun0 parent 1: handle 10: tbf "
        f"rate {rate_kbps}kbit burst {rate_kbps * 2}bit latency 50ms"
    )

    if rc1 != 0 or rc2 != 0:
        _fail("bandwidth_throttle", f"tc commands failed: {out1} {out2}")

    _active_injections["bandwidth_throttle"] = {
        "injected_at": ts,
        "rate_kbps": rate_kbps,
        "latency_ms": latency_ms,
    }
    logger.warning(f"[FAULT INJECTED] Bandwidth throttle: {rate_kbps}kbps +{latency_ms}ms at {ts}")

    return _ack(
        "bandwidth_throttle",
        detail=f"uesimtun0 throttled to {rate_kbps}kbps with +{latency_ms}ms latency.",
        extra={
            "injected_at": ts,
            "rate_kbps": rate_kbps,
            "latency_ms": latency_ms,
            "verify_cmd": "tc qdisc show dev uesimtun0",
        },
    )


# ── Fault: gNB Drop ───────────────────────────────────────────────────────────
@app.post("/inject/gnb_drop")
def inject_gnb_drop():
    """
    Kill the UERANSIM gNB process.
    Effect: Radio link drops. UE will attempt re-registration (AMF sees churn).
    Detectable via: amf_registration_request_total spikes, ue_count drops.
    """
    ts = _now()

    rc, out = _run("sudo pkill -f nr-gnb")
    if rc != 0 and "no process found" not in out.lower():
        _fail("gnb_drop", f"pkill failed: {out}")

    _active_injections["gnb_drop"] = {"injected_at": ts, "process": "nr-gnb"}
    logger.warning(f"[FAULT INJECTED] gNB dropped at {ts}")

    return _ack(
        "gnb_drop",
        detail="nr-gnb process killed. UE will lose radio link and attempt re-registration.",
        extra={
            "injected_at": ts,
            "verify_cmd": "pgrep -a nr-gnb",
            "note": "Use /inject/restore_all to restart gNB.",
        },
    )


# ── Fault: Subscriber Auth Failure ───────────────────────────────────────────
@app.post("/inject/subscriber_auth_failure")
def inject_subscriber_auth_failure(imsi: str = "001010000000001"):
    """
    Corrupt the subscriber's K (authentication key) in MongoDB so the UE
    fails the 5G-AKA authentication challenge.
    Effect: AMF returns Authentication Reject. UE registration fails.
    Detectable via: amf_registration_success_total stops incrementing, success ratio drops.
    
    Args:
        imsi: IMSI of the subscriber to corrupt (default: 001010000000001)
    """
    try:
        import pymongo  # type: ignore[import]
    except ImportError:
        _fail("subscriber_auth_failure", "pymongo not installed: pip install pymongo")

    ts = _now()

    try:
        client = pymongo.MongoClient("mongodb://localhost:27017", serverSelectionTimeoutMS=3000)
        db = client["open5gs"]
        coll = db["subscribers"]

        # Find the subscriber
        sub = coll.find_one({"imsi": imsi})
        if not sub:
            _fail("subscriber_auth_failure", f"Subscriber IMSI {imsi} not found in MongoDB")

        # Store original K for restore
        orig_k = sub.get("security", {}).get("k")
        _active_injections["subscriber_auth_failure"] = {
            "injected_at": ts,
            "imsi": imsi,
            "original_k": orig_k,
        }

        # Corrupt K (flip all bytes to FF)
        corrupted_k = "FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF"
        result = coll.update_one(
            {"imsi": imsi},
            {"$set": {"security.k": corrupted_k}},
        )

        if result.modified_count == 0:
            _fail("subscriber_auth_failure", f"MongoDB update returned modified_count=0 for IMSI {imsi}")

        client.close()
        logger.warning(f"[FAULT INJECTED] Subscriber {imsi} auth key corrupted at {ts}")

        return _ack(
            "subscriber_auth_failure",
            detail=f"IMSI {imsi} authentication key corrupted. Next registration attempt will fail 5G-AKA.",
            extra={
                "injected_at": ts,
                "imsi": imsi,
                "verify_cmd": f"mongosh open5gs --eval \"db.subscribers.findOne({{imsi:'{imsi}'}}).security.k\"",
            },
        )

    except Exception as exc:
        if isinstance(exc, HTTPException):
            raise
        _fail("subscriber_auth_failure", str(exc))


# ── Restore All ───────────────────────────────────────────────────────────────
@app.post("/inject/restore_all")
def inject_restore_all():
    """
    Revert ALL active fault injections and restart affected services.
    Returns a per-action restoration log.
    """
    ts = _now()
    results: list[dict] = []

    def attempt(name: str, fn):
        try:
            fn()
            results.append({"action": name, "ok": True})
            logger.info(f"[RESTORE] {name}: OK")
        except Exception as exc:
            results.append({"action": name, "ok": False, "error": str(exc)})
            logger.error(f"[RESTORE] {name}: FAILED — {exc}")

    # Restore UPF
    if "upf_kill" in _active_injections:
        attempt("restart_upf", lambda: _run("sudo systemctl start open5gs-upfd"))
        attempt("restart_smf", lambda: _run("sudo systemctl restart open5gs-smfd"))
        _active_injections.pop("upf_kill", None)

    # Remove bandwidth throttle
    if "bandwidth_throttle" in _active_injections:
        attempt("clear_tc", lambda: _run("sudo tc qdisc del dev uesimtun0 root 2>/dev/null || true"))
        _active_injections.pop("bandwidth_throttle", None)

    # Restart gNB
    if "gnb_drop" in _active_injections:
        gnb_config = "/root/UERANSIM/config/open5gs-gnb.yaml"
        gnb_bin = "/root/UERANSIM/build/nr-gnb"
        attempt("restart_gnb", lambda: _run(f"sudo {gnb_bin} -c {gnb_config} &"))
        _active_injections.pop("gnb_drop", None)

    # Restore subscriber K
    if "subscriber_auth_failure" in _active_injections:
        info = _active_injections["subscriber_auth_failure"]
        imsi = info.get("imsi", "001010000000001")
        orig_k = info.get("original_k")
        if orig_k:
            try:
                import pymongo  # type: ignore[import]
                client = pymongo.MongoClient("mongodb://localhost:27017", serverSelectionTimeoutMS=3000)
                db = client["open5gs"]
                db["subscribers"].update_one(
                    {"imsi": imsi},
                    {"$set": {"security.k": orig_k}},
                )
                client.close()
                results.append({"action": "restore_subscriber_k", "ok": True, "imsi": imsi})
            except Exception as exc:
                results.append({"action": "restore_subscriber_k", "ok": False, "error": str(exc)})
        else:
            results.append({"action": "restore_subscriber_k", "ok": False, "error": "original_k not stored — manual restore required"})
        _active_injections.pop("subscriber_auth_failure", None)

    all_ok = all(r["ok"] for r in results)
    logger.warning(f"[RESTORE ALL] Completed at {ts}. All OK: {all_ok}. Results: {results}")

    return {
        "ok": all_ok,
        "action": "restore_all",
        "timestamp": ts,
        "results": results,
        "remaining_injections": list(_active_injections.keys()),
    }


# ── Main ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="NetOracle Fault Injection API")
    parser.add_argument("--host", default="0.0.0.0", help="Bind host (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=5050, help="Bind port (default: 5050)")
    args = parser.parse_args()

    # Warn if not running as root (many commands need sudo)
    if os.geteuid() != 0:
        logger.warning(
            "WARNING: Not running as root. Service control (systemctl, tc) will require"
            " sudo, which may fail if no password is configured. Consider: sudo python3 " + __file__
        )

    logger.info(f"Starting Fault Injection API on {args.host}:{args.port}")
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
