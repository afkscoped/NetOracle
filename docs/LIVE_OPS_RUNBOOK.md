# LIVE_OPS_RUNBOOK.md
# NetOracle Live Open5GS Operations Runbook
> **Goal**: Cold boot → `source: open5gs_live` on the NetOracle dashboard in under 5 minutes.
> Every command is copy-pasteable. Run steps in order. Do NOT skip.

---

## Pre-requisites (one-time setup — done once, not per-boot)

Follow the **Open5GS Setup Guide** (provided separately) to:
- ✅ WSL2 + Ubuntu 22.04 installed
- ✅ MongoDB installed and `sudo systemctl enable mongod`
- ✅ Open5GS installed via PPA or built from source
- ✅ Prometheus + node_exporter installed
- ✅ UERANSIM cloned, compiled, configs set
- ✅ Test subscriber added via WebUI/start script (IMSI 999700000000001, K, OPc set)
- ✅ Open5GS NF configs have `metrics.server.port` set: AMF=9095, SMF=9096, UPF=9097, PCF=9098
- ✅ (Optional but recommended) `.wslconfig` with `networkingMode=mirrored` for Windows 11 22H2+

If `scripts/wsl_env_sync.sh` has been run at least once, NetOracle's `.env` is already correct.

---

## Daily Startup — 5-Minute Sequence

### STEP 1 — Open a WSL2 terminal (Ubuntu)

```bash
# From Windows: press Win+R, type: ubuntu, press Enter
# OR: open Terminal app, click Ubuntu profile
```

### STEP 2 — Start MongoDB

```bash
sudo systemctl start mongod
# Verify:
sudo systemctl is-active mongod   # must print: active
```

### STEP 3 — Start Open5GS network functions

```bash
sudo systemctl restart \
  open5gs-nrfd open5gs-scpd \
  open5gs-amfd open5gs-smfd open5gs-upfd \
  open5gs-pcfd open5gs-udmd open5gs-udrd \
  open5gs-ausfd open5gs-bsfd open5gs-nssfd

# Quick health check (all must show "active"):
for svc in nrfd scpd amfd smfd upfd pcfd udmd udrd ausfd bsfd nssfd; do
  echo -n "open5gs-${svc}: "; sudo systemctl is-active open5gs-${svc}
done
```

### STEP 4 — Start Prometheus and node_exporter

```bash
sudo systemctl restart prometheus prometheus-node-exporter

# Verify Prometheus is up:
curl -s http://localhost:9090/-/healthy   # must print: Prometheus Server is Healthy.

# Verify NF metrics endpoints are serving:
curl -s http://localhost:9095/metrics | head -5   # AMF
curl -s http://localhost:9096/metrics | head -5   # SMF
curl -s http://localhost:9097/metrics | head -5   # UPF
```

> ⚠️ If any curl returns nothing: that NF's `metrics.server` block in its YAML is wrong,
> or the service didn't restart cleanly. Check: `sudo journalctl -u open5gs-amfd --no-pager -n 20`

### STEP 5 — Start UERANSIM gNB and UE

```bash
cd ~/UERANSIM

# Terminal A: gNB (keep visible — you need to see "NG Setup procedure is successful")
sudo ./build/nr-gnb -c config/open5gs-gnb.yaml
```

Open a **new WSL2 terminal tab/window** and run:

```bash
cd ~/UERANSIM

# Terminal B: UE
sudo ./build/nr-ue -c config/open5gs-ue.yaml
```

**Wait for these exact log lines before proceeding:**
- gNB terminal: `NG Setup procedure is successful`
- UE terminal: `Connection setup for PDU session[1] is successful`

Verify uesimtun0 exists:

```bash
ip addr show uesimtun0   # must show an IP address
ping -I uesimtun0 -c 3 8.8.8.8   # must get replies
```

### STEP 6 — Sync WSL2 IP to NetOracle .env (automated)

```bash
# Run from inside WSL2:
bash /path/to/NetOracle/scripts/wsl_env_sync.sh

# This auto-detects WSL2 IP and updates NetOracle's .env on Windows.
# On mirrored networking (Win 11 22H2+): uses localhost, no portproxy needed.
```

### STEP 7 — (Optional) Start Fault Injection API

```bash
# New WSL2 terminal:
sudo python3 /path/to/NetOracle/scripts/fault_injection_api.py --port 5050

# Test it's reachable from Windows:
curl http://localhost:5050/health
```

### STEP 8 — Start NetOracle on Windows

```powershell
# In Windows PowerShell or Terminal:
cd "C:\Users\Rishab Nayak\Desktop\Om\RVCE\EL\IV Sem\NetOracle"
.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

### STEP 9 — Verify live data is flowing

```powershell
# Run pre-flight check:
.venv\Scripts\python.exe scripts\verify_open5gs_integration.py
# Must exit 0. Any FAIL = stop and fix before demo.
```

Open browser → `http://127.0.0.1:8000`

**What you should see:**
- Green `● LIVE — Open5GS` banner in the top bar
- KPI gauges animating with real values (not zeros)
- Dashboard telemetry chart showing UPF/AMF/SMF data

---

## Shutdown

```bash
# WSL2: stop UERANSIM
sudo pkill nr-ue; sudo pkill nr-gnb

# WSL2: stop Open5GS (optional — MongoDB and Prometheus can stay running)
sudo systemctl stop \
  open5gs-nrfd open5gs-scpd open5gs-amfd open5gs-smfd open5gs-upfd \
  open5gs-pcfd open5gs-udmd open5gs-udrd open5gs-ausfd open5gs-bsfd open5gs-nssfd
```

```powershell
# Windows: stop NetOracle
# Press Ctrl+C in the uvicorn terminal
```

---

## Troubleshooting

### Symptom: `prometheus reachable: FAIL` in pre-flight check

```bash
# From WSL2:
curl http://localhost:9090/-/healthy

# If this fails: Prometheus didn't start
sudo systemctl status prometheus
sudo journalctl -u prometheus --no-pager -n 30

# If curl from Windows (localhost) fails but WSL2 works:
# → portproxy rules are missing. Re-run wsl_env_sync.sh or set manually:
$wslIp = (wsl hostname -I).Trim().Split(" ")[0]
netsh interface portproxy add v4tov4 listenport=9090 listenaddress=127.0.0.1 connectport=9090 connectaddress=$wslIp
```

### Symptom: NF metrics endpoints return nothing (`curl http://localhost:9095/metrics`)

```bash
# Check that AMF has the metrics block:
grep -A5 "metrics:" /etc/open5gs/amf.yaml

# Expected:
#   metrics:
#     server:
#       - address: 0.0.0.0
#         port: 9095

# If missing: add it and restart
sudo systemctl restart open5gs-amfd
```

### Symptom: `NG Setup procedure is successful` never appears in gNB log

Causes and fixes (check in order):
1. AMF not running: `sudo systemctl is-active open5gs-amfd`
2. PLMN mismatch: AMF config `mcc/mnc` must match `open5gs-gnb.yaml` → both should be `001/01`
3. Wrong IP in gNB config: `linkIp`, `ngapIp`, `gtpIp`, `amfConfigs.address` all need the WSL2 IP (run `hostname -I`)
4. Firewall blocking NGAP (SCTP port 38412): `sudo ufw disable` or allow explicitly

### Symptom: `uesimtun0` never appears after UE starts

```bash
# Check UE log for actual error (usually PLMN or DNN mismatch)
# DNN must match AMF config. Default DNN is "internet"
grep -A2 "dnn:" ~/UERANSIM/config/open5gs-ue.yaml

# IMSI must exactly match the subscriber in MongoDB:
mongosh open5gs --eval "db.subscribers.findOne({}, {imsi:1, security:1})"
```

### Symptom: Dashboard shows `○ SIMULATED` even though everything above is working

```bash
# From Windows, test the NetOracle API directly:
curl http://127.0.0.1:8000/api/open5gs/health

# Check .env is in the right place and has the right values:
cat "C:\Users\Rishab Nayak\Desktop\Om\RVCE\EL\IV Sem\NetOracle\.env"
# Must show: DATA_SOURCE_MODE=open5gs and correct URLs

# Check NetOracle logs for [Open5GS] lines:
# Look for "Prometheus not reachable" — means URL in .env is wrong
```

### Symptom: Everything was working, stops after reboot

WSL2 gets a new IP on every restart (unless mirrored networking is enabled).
Fix:
```bash
# Re-run env sync from WSL2:
bash /path/to/NetOracle/scripts/wsl_env_sync.sh
# Then restart NetOracle on Windows.
```

---

## Quick Reference: Port Map

| Service | Port | Protocol |
|---------|------|----------|
| Prometheus | 9090 | HTTP |
| MongoDB | 27017 | TCP |
| Open5GS WebUI | 3000 | HTTP |
| AMF metrics | 9095 | HTTP |
| SMF metrics | 9096 | HTTP |
| UPF metrics | 9097 | HTTP |
| PCF metrics | 9098 | HTTP |
| node_exporter | 9100 | HTTP |
| Fault Injection API | 5050 | HTTP |
| NetOracle | 8000 | HTTP/WS |
