# Open5GS Real-Time Integration Guide for NetOracle

## Overview

This document details the step-by-step process to integrate Open5GS (a real 5G Core Network) running in WSL2 with the NetOracle platform for real-time telemetry ingestion, fault detection, and proactive avoidance.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  WSL2 (Ubuntu)                                                  │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐           │
│  │   AMF    │ │   SMF    │ │   UPF    │ │   PCF    │           │
│  │  :9095   │ │  :9096   │ │  :9097   │ │  :9098   │           │
│  └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘           │
│       │             │            │             │                │
│  ┌────┴─────────────┴────────────┴─────────────┴──────┐        │
│  │              Prometheus :9090                       │        │
│  └─────────────────────┬──────────────────────────────┘        │
│                        │                                        │
│  ┌─────────────────────┴──────────────────────────────┐        │
│  │              MongoDB :27017 (open5gs DB)            │        │
│  └────────────────────────────────────────────────────┘        │
│                                                                  │
│  ┌──────────────────────┐                                       │
│  │     UERANSIM          │  (gNB + UE simulator)                │
│  │   uesimtun0 iface    │                                       │
│  └──────────────────────┘                                       │
└─────────────────────────────────────────────────────────────────┘
         │ (WSL2 bridge / port forward)
         ▼
┌─────────────────────────────────────────────────────────────────┐
│  Windows Host                                                    │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  NetOracle (FastAPI + PyTorch + CTGNN)                   │   │
│  │  ┌─────────────┐  ┌─────────────┐  ┌──────────────────┐ │   │
│  │  │ Open5GS     │  │ Intelligence│  │ Proactive Engine │ │   │
│  │  │ Adapter     │──│ Service     │──│ + CMDP RL        │ │   │
│  │  └─────────────┘  └─────────────┘  └──────────────────┘ │   │
│  │  ┌─────────────┐  ┌─────────────┐  ┌──────────────────┐ │   │
│  │  │ SHAP XAI    │  │ GraphRAG    │  │ Hopfield Radio   │ │   │
│  │  │ Service     │  │ Diagnosis   │  │ Allocator        │ │   │
│  │  └─────────────┘  └─────────────┘  └──────────────────┘ │   │
│  └──────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

---

## Prerequisites

### WSL2 Setup
1. **Windows 11 or Windows 10 (build 19041+)** with WSL2 enabled
2. **Ubuntu 22.04 LTS** installed in WSL2
3. **Docker Desktop** (optional, for containerized Open5GS)

### Software Requirements (in WSL2)
- Open5GS v2.7+ (5G Core Network)
- UERANSIM v3.2+ (gNB + UE simulator)
- MongoDB 6.0+
- Prometheus + node_exporter
- Build tools: `cmake`, `gcc`, `make`, `meson`, `ninja`

---

## Step 1: Install Open5GS in WSL2

```bash
# Run the provided installation script
bash scripts/install_open5gs_wsl.sh
```

Or manually:

```bash
# Add Open5GS PPA
sudo add-apt-repository ppa:open5gs/latest
sudo apt update

# Install Open5GS components
sudo apt install -y open5gs

# Install MongoDB
sudo apt install -y mongodb-org

# Start MongoDB
sudo systemctl start mongod
sudo systemctl enable mongod
```

### Configure Open5GS NF Prometheus exporters

Each NF needs prometheus metrics enabled. Edit the NF config files:

```bash
# AMF: /etc/open5gs/amf.yaml
# Add under 'metrics':
metrics:
  server:
    - address: 0.0.0.0
      port: 9095

# SMF: /etc/open5gs/smf.yaml
metrics:
  server:
    - address: 0.0.0.0
      port: 9096

# UPF: /etc/open5gs/upf.yaml  
metrics:
  server:
    - address: 0.0.0.0
      port: 9097

# PCF: /etc/open5gs/pcf.yaml
metrics:
  server:
    - address: 0.0.0.0
      port: 9098
```

---

## Step 2: Install and Configure Prometheus

```bash
# Install Prometheus
sudo apt install -y prometheus

# Configure scrape targets
sudo tee /etc/prometheus/prometheus.yml > /dev/null <<EOF
global:
  scrape_interval: 5s

scrape_configs:
  - job_name: 'node'
    static_configs:
      - targets: ['localhost:9100']

  - job_name: 'open5gs-amf'
    static_configs:
      - targets: ['localhost:9095']

  - job_name: 'open5gs-smf'
    static_configs:
      - targets: ['localhost:9096']

  - job_name: 'open5gs-upf'
    static_configs:
      - targets: ['localhost:9097']

  - job_name: 'open5gs-pcf'
    static_configs:
      - targets: ['localhost:9098']
EOF

# Restart Prometheus
sudo systemctl restart prometheus
```

Install node_exporter for system metrics:

```bash
sudo apt install -y prometheus-node-exporter
sudo systemctl start prometheus-node-exporter
```

---

## Step 3: Install UERANSIM (gNB + UE Simulator)

```bash
# Clone and build
cd ~
git clone https://github.com/aligungr/UERANSIM.git
cd UERANSIM
sudo apt install -y cmake gcc g++ libsctp-dev
make

# Configure gNB
# Edit config/open5gs-gnb.yaml:
#   linkIp, ngapIp, gtpIp → set to WSL2 IP
#   amfConfigs → point to AMF address

# Configure UE  
# Edit config/open5gs-ue.yaml:
#   gnbSearchList → point to gNB address
#   IMSI, key, OPc → must match Open5GS subscriber
```

---

## Step 4: Add Test Subscribers

```bash
# Use Open5GS WebUI (default: http://localhost:3000)
# Default credentials: admin / 1423

# Or use MongoDB directly:
mongo open5gs --eval '
db.subscribers.insertOne({
  "imsi": "901700000000001",
  "security": {
    "k": "465B5CE8B199B49FAA5F0A2EE238A6BC",
    "opc": "E8ED289DEBA952E4283B54E88E6183CA"
  },
  "slice": [{"sst": 1, "sd": "010203"}],
  "ambr": {"uplink": {"value": 1, "unit": 3}, "downlink": {"value": 1, "unit": 3}}
})'
```

---

## Step 5: Start the 5G Core

```bash
# Start all Open5GS NFs (use the provided script)
bash scripts/start_open5gs.sh

# Or start individually:
sudo systemctl start open5gs-nrfd
sudo systemctl start open5gs-scpd
sudo systemctl start open5gs-amfd
sudo systemctl start open5gs-smfd
sudo systemctl start open5gs-upfd
sudo systemctl start open5gs-pcfd
sudo systemctl start open5gs-udmd
sudo systemctl start open5gs-udrd
sudo systemctl start open5gs-ausfd
sudo systemctl start open5gs-bsfd

# Start UERANSIM gNB
cd ~/UERANSIM
./build/nr-gnb -c config/open5gs-gnb.yaml &

# Start UERANSIM UE
./build/nr-ue -c config/open5gs-ue.yaml &
```

---

## Step 6: Configure WSL2 Network Bridge (Windows ↔ WSL2)

```powershell
# Run the provided PowerShell script on Windows host
.\scripts\configure_wsl_bridge.ps1

# Or manually get WSL2 IP:
wsl hostname -I
# Note the IP (e.g., 172.28.xxx.xxx)
```

---

## Step 7: Configure NetOracle for Open5GS

Edit the `.env` file in the NetOracle root:

```bash
# Switch data source to Open5GS
DATA_SOURCE_MODE=open5gs

# Point to WSL2 addresses (replace with your WSL2 IP)
OPEN5GS_PROMETHEUS_URL=http://172.28.xxx.xxx:9090
OPEN5GS_MONGO_URI=mongodb://172.28.xxx.xxx:27017
OPEN5GS_WEBUI_URL=http://172.28.xxx.xxx:3000
OPEN5GS_POLL_INTERVAL_S=5
```

Alternative: Use `localhost` with port forwarding:

```powershell
# Forward WSL2 ports to Windows localhost
netsh interface portproxy add v4tov4 listenport=9090 listenaddress=127.0.0.1 connectport=9090 connectaddress=$(wsl hostname -I)
netsh interface portproxy add v4tov4 listenport=27017 listenaddress=127.0.0.1 connectport=27017 connectaddress=$(wsl hostname -I)
```

---

## Step 8: Start NetOracle

```powershell
# From the NetOracle root directory
.\run.ps1

# Or manually:
.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

### Verify Integration

1. **Open dashboard**: http://127.0.0.1:8000
2. **Check data source**: The status bar should show "open5gs" mode
3. **Check NF health**: Navigate to http://127.0.0.1:8000/api/open5gs/health
4. **Verify live metrics**: WebSocket telemetry should show `source: "open5gs_live"`

---

## Step 9: Generate Live Traffic for Testing

```bash
# In WSL2, generate traffic through the UE tunnel
# ping through the uesimtun0 interface
ping -I uesimtun0 8.8.8.8

# Use iperf3 for throughput testing
iperf3 -c 8.8.8.8 -B $(ip addr show uesimtun0 | grep inet | awk '{print $2}' | cut -d/ -f1) -t 60

# Bulk HTTP traffic
for i in $(seq 1 100); do
  curl -s --interface uesimtun0 -o /dev/null http://speedtest.tele2.net/10MB.zip &
done
```

---

## Step 10: Automatic DB Export + Retrain from Live Data

Once NetOracle has collected sufficient live data, use the new endpoint:

```bash
# Export collected telemetry to CSV and trigger retraining
curl -X POST http://127.0.0.1:8000/api/training/export-retrain \
  -H "Content-Type: application/json" \
  -d '{"limit": 5000, "epochs": 12, "cpu": true}'
```

Or via the dashboard:
1. Let the system collect data for at least 30 minutes
2. Navigate to the **Training** tab
3. Click "Export & Retrain" to create a CSV from live data and start training

---

## Metric Mapping Reference

| Open5GS Metric | NetOracle Field | NF | Description |
|---|---|---|---|
| `amf_session_count` | `cpu` (proxy) | AMF | Session load indicator |
| `amf_ue_context_count` | `memory` (proxy) | AMF | Connected UE count |
| `smf_pdu_session_count` | `throughput_mbps` | SMF | Active PDU sessions |
| `upf_rx_bytes_total` / `upf_tx_bytes_total` | `throughput_mbps` | UPF | Real data plane throughput |
| `upf_dropped_packets_total` | `packet_loss` | UPF | Packet drop ratio |
| `pcf_policy_rule_count` | `prb_utilization` | PCF | Active policy rules |
| `node_cpu_seconds_total` | `cpu` | Host | System CPU utilization |
| `node_memory_MemAvailable_bytes` | `memory` | Host | System memory usage |

---

## Troubleshooting

### Prometheus Not Reachable
```bash
# Check Prometheus is running in WSL2
curl http://localhost:9090/-/healthy

# Check NF metrics exporters
curl http://localhost:9095/metrics  # AMF
curl http://localhost:9096/metrics  # SMF
curl http://localhost:9097/metrics  # UPF
```

### MongoDB Connection Fails
```bash
# Check MongoDB is running
sudo systemctl status mongod

# Test connection
mongosh --eval "db.adminCommand('ping')"
```

### WSL2 Network Issues
```powershell
# Check WSL2 IP
wsl hostname -I

# Test connectivity from Windows
Test-NetConnection -ComputerName <WSL2_IP> -Port 9090
```

### NetOracle Fallback Mode
If Open5GS is unreachable, NetOracle gracefully falls back to simulated metrics
with `source: "open5gs_simulated"`. Check the logs for warnings:
```
[Open5GS] Prometheus not reachable at http://...
```

---

## Advanced: Scheduled Auto-Retrain

Add this to your system scheduler (Windows Task Scheduler or cron):

```powershell
# PowerShell script to run every 6 hours
$response = Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/training/export-retrain" `
  -Method POST -ContentType "application/json" `
  -Body '{"limit": 5000, "epochs": 8, "cpu": true}'
Write-Output "Retrain result: $($response | ConvertTo-Json)"
```

This ensures the CTGNN model continuously improves from actual network behaviour.
