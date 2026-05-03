import time
import requests
import random
from datetime import datetime, timezone

API_URL = "http://127.0.0.1:8000/api/telemetry/stream"

def stream_telemetry():
    print("Starting Open5GS/UERANSIM simulated telemetry stream...")
    try:
        while True:
            # Generate simulated metrics representing an Open5GS UPF node
            payload = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "slice_id": "slice_1",
                "node_id": "upf_1",
                "node_type": "UPF",
                "cpu": round(random.uniform(20.0, 85.0), 2),
                "memory": round(random.uniform(40.0, 75.0), 2),
                "latency_ms": round(random.uniform(10.0, 50.0), 2),
                "packet_loss": round(random.uniform(0.001, 0.05), 4),
                "throughput_mbps": round(random.uniform(500.0, 950.0), 2),
                "prb_utilization": round(random.uniform(0.3, 0.9), 2),
            }
            
            try:
                response = requests.post(API_URL, json=payload, timeout=2)
                if response.ok:
                    print(f"[{payload['timestamp']}] Successfully ingested frame.")
                else:
                    print(f"[{payload['timestamp']}] Failed to ingest: HTTP {response.status_code}")
            except requests.RequestException as e:
                print(f"Connection error: {e}. Is NetOracle running?")
                
            time.sleep(2) # Send a frame every 2 seconds
            
    except KeyboardInterrupt:
        print("\nStopping stream.")

if __name__ == "__main__":
    stream_telemetry()
