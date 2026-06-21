#!/usr/bin/env bash
set -x

# Kill existing UERANSIM processes
sudo pkill -f "nr-ue" || true
sudo pkill -f "nr-gnb" || true
sleep 2

# Start gNodeB
echo "Starting gNodeB..."
sudo nohup nr-gnb -c /etc/ueransim/open5gs-gnb.yaml > /var/log/ueransim/gnb.log 2>&1 &
sleep 5

# Start UE
echo "Starting UE..."
sudo nohup nr-ue -c /etc/ueransim/open5gs-ue.yaml > /var/log/ueransim/ue.log 2>&1 &
sleep 8

# Check if tunnel is up
if ip link show uesimtun0 &>/dev/null; then
    echo "SUCCESS: uesimtun0 is UP"
    ip addr show uesimtun0
else
    echo "ERROR: uesimtun0 is STILL DOWN"
    tail -n 20 /var/log/ueransim/ue.log
fi
