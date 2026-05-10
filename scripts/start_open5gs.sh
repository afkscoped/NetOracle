#!/usr/bin/env bash
set -euo pipefail

echo "================================================"
echo "  NetOracle - Open5GS Stack Startup"
echo "================================================"

echo "[1/6] Starting MongoDB..."
sudo systemctl enable mongod >/dev/null 2>&1 || true
if ! systemctl is-active --quiet mongod; then
  sudo systemctl start mongod
fi
sleep 2
mongosh --eval "db.runCommand({ping:1})" --quiet >/dev/null
echo "  MongoDB OK"

echo "[2/6] Starting Open5GS NFs..."
NFS=(nrf ausf udm udr pcf amf smf upf)
for svc in "${NFS[@]}"; do
  sudo systemctl enable "open5gs-${svc}d" >/dev/null 2>&1 || true
  if ! systemctl is-active --quiet "open5gs-${svc}d"; then
    sudo systemctl start "open5gs-${svc}d"
    sleep 0.5
  fi
done
sleep 3

for svc in "${NFS[@]}"; do
  status=$(systemctl is-active "open5gs-${svc}d" 2>/dev/null || echo "not-installed")
  printf "  open5gs-%sd: %s\n" "$svc" "$status"
done

echo "[3/6] Starting Prometheus..."
sudo systemctl enable prometheus >/dev/null 2>&1 || true
sudo systemctl enable prometheus-node-exporter >/dev/null 2>&1 || true
if ! systemctl is-active --quiet prometheus-node-exporter; then
  sudo systemctl start prometheus-node-exporter
fi
if ! systemctl is-active --quiet prometheus; then
  sudo systemctl start prometheus
fi
sleep 2
curl -sf http://localhost:9090/-/healthy >/dev/null && echo "  Prometheus OK" || echo "  Prometheus not healthy"

echo "[4/6] Checking test subscriber..."
SUB_EXISTS=$(mongosh open5gs --quiet --eval "db.subscribers.countDocuments({imsi:'999700000000001'})")
if [ "$SUB_EXISTS" -eq "0" ]; then
  mongosh open5gs --quiet <<'MONGO'
db.subscribers.insertOne({
  "imsi": "999700000000001",
  "security": {
    "k": "465B5CE8B199B49FAA5F0A2EE238A6BC",
    "opc": "E8ED289DEBA952E4283B54E88E6183CA",
    "amf": "8000"
  },
  "ambr": {
    "downlink": {"value": 1, "unit": 3},
    "uplink": {"value": 1, "unit": 3}
  },
  "slice": [{
    "sst": 1,
    "default_indicator": true,
    "session": [{
      "name": "internet",
      "type": 3,
      "qos": {"index": 9, "arp": {"priority_level": 8, "pre_emption_capability": 1, "pre_emption_vulnerability": 1}},
      "ambr": {"downlink": {"value": 1, "unit": 3}, "uplink": {"value": 1, "unit": 3}},
      "ue": {"addr": "10.45.0.0/16"}
    }]
  }]
})
MONGO
  echo "  Subscriber registered"
else
  echo "  Subscriber already exists"
fi

echo "[5/6] Starting UERANSIM gNB..."
if command -v nr-gnb >/dev/null 2>&1; then
  sudo mkdir -p /var/log/ueransim
  pkill -f "nr-gnb" 2>/dev/null || true
  nohup nr-gnb -c /etc/ueransim/open5gs-gnb.yaml >/var/log/ueransim/gnb.log 2>&1 &
  sleep 5
  pgrep -f "nr-gnb" >/dev/null && echo "  gNB running" || echo "  gNB failed; check /var/log/ueransim/gnb.log"
else
  echo "  nr-gnb not found; skipping"
fi

echo "[6/6] Starting UERANSIM UE..."
if command -v nr-ue >/dev/null 2>&1; then
  sudo mkdir -p /var/log/ueransim
  pkill -f "nr-ue" 2>/dev/null || true
  nohup nr-ue -c /etc/ueransim/open5gs-ue.yaml >/var/log/ueransim/ue.log 2>&1 &
  sleep 6
  if ip link show uesimtun0 >/dev/null 2>&1; then
    UE_IP=$(ip addr show uesimtun0 | awk '/inet / {print $2}')
    echo "  UE attached on uesimtun0 ($UE_IP)"
    nohup ping -I uesimtun0 8.8.8.8 -i 0.5 >/dev/null 2>&1 &
    echo "  Background UE traffic started"
  else
    echo "  UE tunnel not up; check /var/log/ueransim/ue.log"
  fi
else
  echo "  nr-ue not found; skipping"
fi

WSL_IP=$(hostname -I | awk '{print $1}')
echo ""
echo "================================================"
echo "Open5GS stack startup completed"
echo "Prometheus: http://localhost:9090"
echo "Open5GS WebUI: http://localhost:3000"
echo "MongoDB: mongodb://localhost:27017"
echo ""
echo "Use these values from Windows NetOracle:"
echo "DATA_SOURCE_MODE=open5gs"
echo "OPEN5GS_PROMETHEUS_URL=http://$WSL_IP:9090"
echo "OPEN5GS_MONGO_URI=mongodb://$WSL_IP:27017"
echo "OPEN5GS_WEBUI_URL=http://$WSL_IP:3000"
echo "================================================"
