#!/usr/bin/env bash
set -euo pipefail

if ! grep -qi "ubuntu" /etc/os-release; then
  echo "This script is intended for WSL2 Ubuntu 22.04."
fi

echo "================================================"
echo "  NetOracle - Open5GS WSL2 Installer"
echo "================================================"

echo "[1/10] Installing system prerequisites..."
sudo apt-get update
sudo apt-get upgrade -y
sudo apt-get install -y \
  software-properties-common \
  curl wget git build-essential \
  python3-pip python3-venv \
  cmake ninja-build libsctp-dev \
  libyaml-dev libgnutls28-dev \
  libgcrypt-dev libssl-dev \
  libidn11-dev libmongoc-dev \
  libbson-dev liblz4-dev \
  libnghttp2-dev \
  iproute2 iputils-ping net-tools \
  prometheus prometheus-node-exporter

echo "[2/10] Installing Node.js 18 for Open5GS WebUI..."
curl -fsSL https://deb.nodesource.com/setup_18.x | sudo -E bash -
sudo apt-get install -y nodejs

echo "[3/10] Installing MongoDB packages when available..."
if ! command -v mongosh >/dev/null 2>&1; then
  wget -qO- https://www.mongodb.org/static/pgp/server-7.0.asc | sudo gpg --dearmor -o /usr/share/keyrings/mongodb-server-7.0.gpg
  echo "deb [ arch=amd64,arm64 signed-by=/usr/share/keyrings/mongodb-server-7.0.gpg ] https://repo.mongodb.org/apt/ubuntu jammy/mongodb-org/7.0 multiverse" | sudo tee /etc/apt/sources.list.d/mongodb-org-7.0.list >/dev/null
  sudo apt-get update
  sudo apt-get install -y mongodb-org mongodb-mongosh
fi

echo "[4/10] Installing Open5GS from PPA..."
sudo add-apt-repository ppa:open5gs/latest -y
sudo apt-get update
sudo apt-get install -y open5gs
ls /usr/bin/open5gs-* >/dev/null

echo "[5/10] Installing Open5GS WebUI..."
curl -fsSL https://open5gs.org/open5gs/assets/webui/install | sudo -E bash -

patch_metrics_block() {
  local file="$1"
  local nf="$2"
  local port="$3"
  sudo python3 - "$file" "$nf" "$port" <<'PY'
from pathlib import Path
import re
import sys

path = Path(sys.argv[1])
nf = sys.argv[2]
port = sys.argv[3]
lines = path.read_text(encoding="utf-8").splitlines()

# Remove legacy top-level blocks written by older NetOracle scripts.
cleaned = []
i = 0
while i < len(lines):
    indent = len(lines[i]) - len(lines[i].lstrip(" "))
    if indent == 0 and lines[i].strip() == "metrics:":
        j = i + 1
        block = []
        while j < len(lines) and (not lines[j].strip() or lines[j].startswith((" ", "\t"))):
            block.append(lines[j])
            j += 1
        text = "\n".join(block)
        if "addr:" in text and "port:" in text and "server:" not in text:
            i = j
            continue
    cleaned.append(lines[i])
    i += 1
lines = cleaned

start = None
for idx, line in enumerate(lines):
    if re.match(rf"^{re.escape(nf)}:\s*$", line):
        start = idx
        break
if start is None:
    raise SystemExit(f"{path}: top-level '{nf}:' block not found")

end = len(lines)
for idx in range(start + 1, len(lines)):
    if lines[idx] and not lines[idx].startswith((" ", "\t")) and re.match(r"^[A-Za-z0-9_-]+:", lines[idx]):
        end = idx
        break

inside = []
i = start + 1
while i < end:
    if re.match(r"^  metrics:\s*$", lines[i]):
        j = i + 1
        while j < end and (not lines[j].strip() or lines[j].startswith("    ")):
            j += 1
        i = j
        continue
    inside.append(lines[i])
    i += 1

metrics_block = [
    "  metrics:",
    "    server:",
    "      - address: 0.0.0.0",
    f"        port: {port}",
]
patched = lines[: start + 1] + metrics_block + inside + lines[end:]
path.write_text("\n".join(patched) + "\n", encoding="utf-8")
print(f"patched {path}: {nf}.metrics.server port {port}")
PY
}

echo "[6/10] Enabling Open5GS Prometheus exporters..."
patch_metrics_block /etc/open5gs/amf.yaml amf 9095
patch_metrics_block /etc/open5gs/smf.yaml smf 9096
patch_metrics_block /etc/open5gs/upf.yaml upf 9097
patch_metrics_block /etc/open5gs/pcf.yaml pcf 9098

echo "[7/10] Configuring Prometheus scrape jobs..."
sudo tee /etc/prometheus/prometheus.yml >/dev/null <<'EOF'
global:
  scrape_interval: 5s
  evaluation_interval: 5s

scrape_configs:
  - job_name: 'open5gs-amf'
    static_configs:
      - targets: ['localhost:9095']
    metrics_path: /metrics

  - job_name: 'open5gs-smf'
    static_configs:
      - targets: ['localhost:9096']

  - job_name: 'open5gs-upf'
    static_configs:
      - targets: ['localhost:9097']

  - job_name: 'open5gs-pcf'
    static_configs:
      - targets: ['localhost:9098']

  - job_name: 'node'
    static_configs:
      - targets: ['localhost:9100']
EOF

echo "[8/10] Building and installing UERANSIM..."
if ! command -v nr-gnb >/dev/null 2>&1 || ! command -v nr-ue >/dev/null 2>&1; then
  if [ ! -d "$HOME/UERANSIM" ]; then
    git clone https://github.com/aligungr/UERANSIM "$HOME/UERANSIM"
  fi
  cmake -S "$HOME/UERANSIM" -B "$HOME/UERANSIM/build" -GNinja
  ninja -C "$HOME/UERANSIM/build" -j"$(nproc)"
  sudo cp "$HOME/UERANSIM/build/nr-gnb" "$HOME/UERANSIM/build/nr-ue" /usr/local/bin/
fi

echo "[9/10] Writing UERANSIM configs..."
sudo mkdir -p /etc/ueransim
sudo tee /etc/ueransim/open5gs-gnb.yaml >/dev/null <<'EOF'
mcc: '999'
mnc: '70'
nci: '0x000000010'
idLength: 32
tac: 1

linkIp: 127.0.0.1
ngapIp: 127.0.0.1
gtpIp: 127.0.0.4

amfConfigs:
  - address: 127.0.0.5
    port: 38412

slices:
  - sst: 1
    sd: 0x000001
  - sst: 1
    sd: 0x000002
  - sst: 1
    sd: 0x000003

ignoreStreamIds: true
EOF

sudo tee /etc/ueransim/open5gs-ue.yaml >/dev/null <<'EOF'
supi: 'imsi-999700000000001'
mcc: '999'
mnc: '70'
key: '465B5CE8B199B49FAA5F0A2EE238A6BC'
op: 'E8ED289DEBA952E4283B54E88E6183CA'
opType: 'OPC'
amf: '8000'
imei: '356938035643803'
imeiSv: '4370816125816151'

gnbSearchList:
  - 127.0.0.1

uacAic:
  mps: false
  mcs: false

uacAcc:
  normalClass: 0
  class11: false
  class12: false
  class13: false
  class14: false
  class15: false

sessions:
  - type: 'IPv4'
    apn: 'internet'
    slice:
      sst: 1
      sd: 0x000001

configured-nssai:
  - sst: 1
    sd: 0x000001

default-nssai:
  - sst: 1
    sd: 0x000001

integrity:
  IA1: true
  IA2: true
  IA3: true

ciphering:
  EA0: true
  EA1: true
  EA2: true
  EA3: true

integrityMaxRate:
  uplink: 'full'
  downlink: 'full'
EOF

echo "[10/10] Enabling services..."
sudo systemctl enable mongod
sudo systemctl enable prometheus
sudo systemctl enable prometheus-node-exporter
for svc in nrf ausf udm udr pcf amf smf upf; do
  sudo systemctl enable "open5gs-${svc}d"
done

echo ""
echo "Installation and configuration complete."
echo "Next: bash scripts/start_open5gs.sh"
