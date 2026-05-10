# NetOracle Real-Time Open5GS Runbook

This runbook connects NetOracle on Windows to a live Open5GS + UERANSIM stack running in WSL2 Ubuntu. NetOracle then ingests real telemetry every few seconds, predicts faults, explains likely causes, and simulates the best fix before an SLA breach.

## 1. Prerequisites

- Windows with WSL2 enabled.
- Ubuntu 22.04 in WSL2.
- Administrator/sudo access inside WSL.
- Python virtual environment already installed for NetOracle on Windows.

## 2. Install Open5GS stack inside WSL2

Open a WSL Ubuntu terminal and run:

```bash
cd /mnt/c/Users/raddo/Documents/EL\ main\ 4th\ sem/netoracle
bash scripts/install_open5gs_wsl.sh
```

The installer configures:

- Open5GS NFs: NRF, AUSF, UDM, UDR, PCF, AMF, SMF, UPF.
- MongoDB subscriber database.
- Prometheus on port `9090`.
- Open5GS NF exporters on ports `9095` to `9098`.
- UERANSIM gNB/UE configs.
- Node exporter on `9100`.

## 3. Start live Open5GS + UERANSIM traffic

In WSL:

```bash
cd /mnt/c/Users/raddo/Documents/EL\ main\ 4th\ sem/netoracle
bash scripts/start_open5gs.sh
```

At the end, copy the printed WSL IP values. They look like:

```env
DATA_SOURCE_MODE=open5gs
OPEN5GS_PROMETHEUS_URL=http://<WSL_IP>:9090
OPEN5GS_MONGO_URI=mongodb://<WSL_IP>:27017
OPEN5GS_WEBUI_URL=http://<WSL_IP>:3000
```

## 4. Configure NetOracle on Windows

Create or edit `netoracle/.env` on Windows:

```env
DATA_SOURCE_MODE=open5gs
OPEN5GS_PROMETHEUS_URL=http://<WSL_IP>:9090
OPEN5GS_MONGO_URI=mongodb://<WSL_IP>:27017
OPEN5GS_WEBUI_URL=http://<WSL_IP>:3000
OPEN5GS_POLL_INTERVAL_S=5
REMEDIATION_MODE=simulation
```

If Windows can resolve WSL localhost forwarding correctly, you can use `http://localhost:9090`; otherwise use the WSL IP printed by `start_open5gs.sh`.

## 5. Start NetOracle

From PowerShell on Windows:

```powershell
& "c:\Users\raddo\Documents\EL main 4th sem\netoracle\.venv\Scripts\python.exe" -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Open:

```text
http://127.0.0.1:8000
```

Use the dashboard buttons:

- **Analyse Live Faults**: pulls the latest live Open5GS tick, predicts faults, diagnoses, and suggests fixes.
- **Simulate Best Fix**: shows before/after risk using the Kintsugi recovery map.
- **Data Sources → Open5GS**: switch runtime adapter mode from the UI.
- **3D Twin**: inspect live risk and preventive action per node.

## 6. Verify integration

Run this while NetOracle is running:

```powershell
& "c:\Users\raddo\Documents\EL main 4th sem\netoracle\.venv\Scripts\python.exe" "c:\Users\raddo\Documents\EL main 4th sem\netoracle\scripts\verify_open5gs_integration.py"
```

Expected checks:

- Prometheus reachable.
- Open5GS AMF/SMF/UPF metrics visible.
- MongoDB reachable and subscriber registered.
- NetOracle `/api/open5gs/health` returns NF health.
- `/api/telemetry/tick` returns Open5GS-shaped frames.
- WebSocket `/ws/telemetry` streams live frames.

## 7. Real-time fault flow

Once running in `open5gs` mode:

1. Open5GS + UERANSIM produce live traffic.
2. Prometheus scrapes Open5GS NF exporters.
3. NetOracle pulls live frames through `Open5GSAdapter`.
4. `IntelligenceService` produces fault probabilities.
5. `ProactiveEngine` forecasts 5/10/20-minute risk.
6. `RealtimeEngine` suggests a fix and simulates before/after SLA impact.
7. Dashboard and 3D twin show interpretable cards instead of raw JSON.

## 8. Troubleshooting

- If `Prometheus not reachable`, check WSL IP and Windows firewall.
- If NF metrics are absent, restart Open5GS after running `install_open5gs_wsl.sh`.
- If `uesimtun0` is missing, inspect `/var/log/ueransim/ue.log` and `/var/log/ueransim/gnb.log`.
- If NetOracle still shows simulated Open5GS frames, confirm `.env` has `DATA_SOURCE_MODE=open5gs` and restart Uvicorn.
