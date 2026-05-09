#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════
# start_open5gs.sh — Run this INSIDE WSL2 to start the full Open5GS stack
# Usage: bash start_open5gs.sh
# ═══════════════════════════════════════════════════════════════════════════
 
set -e
 
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  NetOracle — Open5GS Stack Startup"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
 
# ── 1. MongoDB ────────────────────────────────────────────────────────────
echo "[1/6] Starting MongoDB..."
if ! systemctl is-active --quiet mongod; then
    sudo systemctl start mongod
fi
sleep 2
mongosh --eval "db.runCommand({ping:1})" --quiet > /dev/null && echo "  ✓ MongoDB OK" || echo "  ✗ MongoDB FAILED"
 
# ── 2. Open5GS Core NFs ──────────────────────────────────────────────────
echo "[2/6] Starting Open5GS NFs..."
NFS=(nrf ausf udm udr pcf amf smf upf)
for svc in "${NFS[@]}"; do
    if ! systemctl is-active --quiet open5gs-${svc}d; then
        sudo systemctl start open5gs-${svc}d
        sleep 0.5
    fi
done
sleep 3
 
# Check status
echo "  NF Status:"
for svc in "${NFS[@]}"; do
    status=$(systemctl is-active open5gs-${svc}d 2>/dev/null || echo "not-installed")
    icon="✓" && [[ "$status" != "active" ]] && icon="✗"
    printf "    %s open5gs-%sd: %s\n" "$icon" "$svc" "$status"
done
 
# ── 3. Prometheus ─────────────────────────────────────────────────────────
echo "[3/6] Starting Prometheus..."
if ! systemctl is-active --quiet prometheus; then
    sudo systemctl start prometheus
fi
sleep 2
curl -sf http://localhost:9090/-/healthy > /dev/null && echo "  ✓ Prometheus OK" || echo "  ✗ Prometheus FAILED"
 
# ── 4. Register test subscriber (idempotent) ──────────────────────────────
echo "[4/6] Checking test subscriber..."
SUB_EXISTS=$(mongosh open5gs --quiet --eval "db.subscribers.countDocuments({imsi:'999700000000001'})")
if [ "$SUB_EXISTS" -eq "0" ]; then
    echo "  Registering test subscriber..."
    mongosh open5gs --quiet << 'MONGO'
db.subscribers.insertOne({
    "imsi": "999700000000001",
    "security": {
        "k": "465B5CE8B199B49FAA5F0A2EE238A6BC",
        "opc": "E8ED289DEBA952E4283B54E88E6183CA",
        "amf": "8000"
    },
    "ambr": {
        "downlink": {"value": 1, "unit": 3},
        "uplink":   {"value": 1, "unit": 3}
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
    echo "  ✓ Subscriber registered"
else
    echo "  ✓ Subscriber already exists"
fi
 
# ── 5. UERANSIM gNB ──────────────────────────────────────────────────────
echo "[5/6] Starting UERANSIM gNB..."
if command -v nr-gnb &> /dev/null; then
    pkill -f "nr-gnb" 2>/dev/null || true
    sleep 1
    mkdir -p /var/log/ueransim
    nohup nr-gnb -c /etc/ueransim/open5gs-gnb.yaml > /var/log/ueransim/gnb.log 2>&1 &
    GNB_PID=$!
    sleep 5
    if kill -0 $GNB_PID 2>/dev/null; then
        echo "  ✓ gNB running (PID=$GNB_PID)"
    else
        echo "  ✗ gNB failed to start — check /var/log/ueransim/gnb.log"
    fi
else
    echo "  ⚠ nr-gnb not found — skipping UERANSIM (metrics will be partial)"
fi
 
# ── 6. UERANSIM UE ───────────────────────────────────────────────────────
echo "[6/6] Starting UERANSIM UE..."
if command -v nr-ue &> /dev/null; then
    pkill -f "nr-ue" 2>/dev/null || true
    sleep 2
    nohup nr-ue -c /etc/ueransim/open5gs-ue.yaml > /var/log/ueransim/ue.log 2>&1 &
    UE_PID=$!
    sleep 6
 
    if ip link show uesimtun0 &>/dev/null; then
        UE_IP=$(ip addr show uesimtun0 | grep 'inet ' | awk '{print $2}')
        echo "  ✓ UE attached — tunnel: uesimtun0 ($UE_IP)"
        # Start background traffic
        nohup ping -I uesimtun0 8.8.8.8 -i 1 > /dev/null 2>&1 &
        echo "  ✓ Background traffic started (ping via uesimtun0)"
    else
        echo "  ✗ UE tunnel not up — check /var/log/ueransim/ue.log"
    fi
else
    echo "  ⚠ nr-ue not found — skipping UE simulation"
fi
 
# ── Summary ───────────────────────────────────────────────────────────────
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Stack Ready. Service URLs:"
echo "  Prometheus:      http://localhost:9090"
echo "  Open5GS WebUI:   http://localhost:3000  (admin/1423)"
echo "  MongoDB:         mongodb://localhost:27017"
echo ""
echo "  From Windows (WSL2 bridge):"
WSL_IP=$(hostname -I | awk '{print $1}')
echo "  Prometheus:      http://$WSL_IP:9090"
echo "  MongoDB:         mongodb://$WSL_IP:27017"
echo ""
echo "  Set in NetOracle .env:"
echo "  DATA_SOURCE_MODE=open5gs"
echo "  OPEN5GS_PROMETHEUS_URL=http://$WSL_IP:9090"
echo "  OPEN5GS_MONGO_URI=mongodb://$WSL_IP:27017"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
