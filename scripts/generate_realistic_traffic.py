#!/usr/bin/env python3
"""
generate_realistic_traffic.py — Sustained Mixed-Load Traffic Generator
=======================================================================
Run INSIDE WSL2 on the uesimtun0 interface after UERANSIM UE is attached.
Produces varied, sustained load for 30+ minutes to give the ML pipeline
realistic signal, including normal and degraded traffic patterns.

Usage:
    sudo python3 scripts/generate_realistic_traffic.py [--duration 3600] [--interface uesimtun0]

Requirements:
    - uesimtun0 interface must exist (UERANSIM UE attached)
    - iperf3 installed: sudo apt install iperf3
    - curl installed: sudo apt install curl
    - python3 standard library only (no extra packages)

Traffic mix:
    - Continuous background ping (ICMP, 1 pps, low bandwidth)
    - iperf3 bursts (TCP, 30s on / 30s off cycle, varied bandwidth)
    - HTTP bulk downloads via curl (periodic, mimics video streaming)
    - Multi-UE simulation via rapid ping floods (if single UE)
"""

import argparse
import asyncio
import logging
import random
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [TrafficGen] %(levelname)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("/tmp/traffic_gen.log"),
    ],
)
logger = logging.getLogger(__name__)

# Global stop event
_stop = asyncio.Event()

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()

def _run_bg(cmd: str) -> subprocess.Popen:
    """Start a command in background, return process handle."""
    logger.info(f"[BG] {cmd}")
    return subprocess.Popen(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def _run(cmd: str, timeout: int = 60) -> tuple[int, str]:
    """Run a command synchronously, return (rc, output)."""
    logger.debug(f"[CMD] {cmd}")
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return result.returncode, (result.stdout + result.stderr).strip()
    except subprocess.TimeoutExpired:
        return -1, "timeout"
    except Exception as exc:
        return -1, str(exc)


async def _background_ping(interface: str) -> None:
    """Continuous low-rate ping to maintain baseline traffic."""
    targets = ["8.8.8.8", "1.1.1.1", "9.9.9.9"]
    idx = 0
    while not _stop.is_set():
        target = targets[idx % len(targets)]
        idx += 1
        proc = _run_bg(f"ping -I {interface} -c 10 -i 0.5 {target}")
        await asyncio.sleep(8)
        if proc.poll() is None:
            proc.terminate()
        await asyncio.sleep(2)


async def _iperf3_bursts(interface: str) -> None:
    """
    Alternating iperf3 TCP bursts through the tunnel.
    Requires an iperf3 server reachable via the tunnel — we use a public iperf3 server.
    Fallback: skip if no server reachable.
    """
    # Public iperf3 servers (may change — update if they stop responding)
    servers = ["iperf.scottlinux.com", "iperf3.moji.fr", "bouygues.iperf.fr"]
    active_server = None

    # Find a working server
    for srv in servers:
        rc, _ = _run(f"timeout 5 iperf3 -c {srv} -t 3 --interface {interface} 2>&1", timeout=10)
        if rc == 0:
            active_server = srv
            logger.info(f"[iperf3] Using server: {srv}")
            break

    if not active_server:
        logger.warning("[iperf3] No reachable iperf3 server found — skipping iperf3 bursts.")
        logger.warning("[iperf3] To enable: run 'iperf3 -s' on another reachable host.")
        return

    burst_cycle = 0
    while not _stop.is_set():
        burst_cycle += 1
        # Vary bandwidth: light / medium / heavy
        bandwidth = random.choice(["1M", "5M", "10M", "20M"])
        duration = random.choice([15, 30, 45])
        direction = "-R" if burst_cycle % 3 == 0 else ""  # reverse direction every 3rd burst

        logger.info(f"[iperf3] Burst #{burst_cycle}: {bandwidth} for {duration}s {direction or '(upload)'}")
        proc = _run_bg(
            f"iperf3 -c {active_server} -t {duration} -b {bandwidth} "
            f"--interface {interface} {direction} -P 2"
        )

        # Wait for burst to complete (or stop event)
        for _ in range(duration + 10):
            if _stop.is_set():
                break
            await asyncio.sleep(1)

        if proc.poll() is None:
            proc.terminate()

        # Pause between bursts
        pause = random.randint(15, 45)
        logger.info(f"[iperf3] Pausing {pause}s before next burst")
        await asyncio.sleep(pause)


async def _bulk_http_downloads(interface: str) -> None:
    """
    Periodic HTTP bulk downloads via curl — mimics video streaming load.
    Uses large public files accessible via plain HTTP.
    """
    # Public test files of varying sizes
    test_urls = [
        "http://speedtest.tele2.net/10MB.zip",
        "http://speedtest.tele2.net/1MB.zip",
        "http://proof.ovh.net/files/1Mb.dat",
        "http://speedtest.tele2.net/5MB.zip",
    ]

    download_count = 0
    while not _stop.is_set():
        download_count += 1
        url = random.choice(test_urls)
        logger.info(f"[HTTP] Download #{download_count}: {url}")

        proc = _run_bg(
            f"curl -s --interface {interface} -o /dev/null --max-time 60 "
            f"--limit-rate {random.choice(['500K', '1M', '2M', '5M'])} '{url}'"
        )

        await asyncio.sleep(60)  # Let download run for up to 60s
        if proc.poll() is None:
            proc.terminate()

        # Gap between downloads (30–120s)
        gap = random.randint(30, 120)
        logger.info(f"[HTTP] Next download in {gap}s")
        await asyncio.sleep(gap)


async def _multi_ue_simulation(interface: str) -> None:
    """
    Simulate multi-UE churn by sending ICMP floods with varied packet sizes.
    This stresses the UPF's packet processing and generates varied throughput signal.
    """
    churn_count = 0
    while not _stop.is_set():
        churn_count += 1
        # Vary packet size to simulate different UE types
        pkt_size = random.choice([64, 512, 1400, 1472])
        count = random.randint(100, 500)
        target = random.choice(["8.8.8.8", "1.1.1.1"])

        logger.info(f"[UE-sim] Churn #{churn_count}: {count} pkts × {pkt_size}B → {target}")
        proc = _run_bg(f"ping -I {interface} -c {count} -s {pkt_size} -i 0.01 {target}")

        await asyncio.sleep(random.randint(5, 20))
        if proc.poll() is None:
            proc.terminate()

        await asyncio.sleep(random.randint(10, 30))


async def _stats_reporter(interface: str) -> None:
    """Print traffic stats every 60s for monitoring."""
    while not _stop.is_set():
        await asyncio.sleep(60)
        rc, out = _run(f"cat /proc/net/dev | grep {interface}", timeout=5)
        if rc == 0 and out:
            logger.info(f"[STATS] {interface}: {out.strip()}")
        else:
            logger.warning(f"[STATS] Could not read stats for {interface}")


async def _main(interface: str, duration: int) -> None:
    """Main coroutine: run all traffic generators concurrently."""
    # Verify interface exists
    rc, _ = _run(f"ip link show {interface}")
    if rc != 0:
        logger.error(
            f"ERROR: Interface '{interface}' not found.\n"
            "Is UERANSIM UE running and attached? Check: ip addr show"
        )
        sys.exit(1)

    logger.info(f"Starting traffic generation on {interface} for {duration}s")
    logger.info(f"Stop time: {datetime.fromtimestamp(time.time() + duration)}")
    logger.info("Traffic mix: ping (continuous) + iperf3 bursts + HTTP downloads + UE churn simulation")

    # Schedule stop after duration
    async def _stop_after():
        await asyncio.sleep(duration)
        logger.info(f"[TrafficGen] Duration {duration}s elapsed — stopping.")
        _stop.set()

    tasks = [
        asyncio.create_task(_background_ping(interface)),
        asyncio.create_task(_iperf3_bursts(interface)),
        asyncio.create_task(_bulk_http_downloads(interface)),
        asyncio.create_task(_multi_ue_simulation(interface)),
        asyncio.create_task(_stats_reporter(interface)),
        asyncio.create_task(_stop_after()),
    ]

    # Handle Ctrl+C
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: _stop.set())

    # Wait until stop
    await _stop.wait()

    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)

    logger.info("[TrafficGen] All generators stopped cleanly.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="NetOracle Traffic Generator")
    parser.add_argument(
        "--interface", default="uesimtun0",
        help="Network interface to send traffic through (default: uesimtun0)"
    )
    parser.add_argument(
        "--duration", type=int, default=3600,
        help="Total run duration in seconds (default: 3600 = 1 hour)"
    )
    args = parser.parse_args()

    if args.duration < 30:
        print("ERROR: Duration must be at least 30 seconds to give the ML pipeline enough signal.")
        sys.exit(1)

    asyncio.run(_main(args.interface, args.duration))
