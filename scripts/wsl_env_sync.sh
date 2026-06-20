#!/usr/bin/env bash
# =============================================================================
# wsl_env_sync.sh — Auto-detect WSL2 IP and update NetOracle's .env on Windows
# Run this from inside WSL2 each time it starts, before launching NetOracle.
#
# Usage:
#   bash scripts/wsl_env_sync.sh [path/to/.env]
#
# What it does:
#   1. Gets the current WSL2 IP via hostname -I
#   2. Optionally sets up Windows netsh portproxy rules (requires PowerShell)
#   3. Rewrites OPEN5GS_* env vars in the target .env file
#   4. Prints a one-line status so you know it worked
# =============================================================================
set -euo pipefail

# ── Config ────────────────────────────────────────────────────────────────────
# Default: .env sits at the repo root, relative to this script's directory.
# Override by passing the path as $1.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
ENV_FILE="${1:-${REPO_ROOT}/.env}"

# Ports that need to be reachable from Windows
PROM_PORT=9090
MONGO_PORT=27017
WEBUI_PORT=3000
FAULT_INJECTION_PORT=5050   # fault_injection_api.py

# ── Detect WSL2 IP ───────────────────────────────────────────────────────────
WSL_IP=$(hostname -I 2>/dev/null | awk '{print $1}')
if [[ -z "$WSL_IP" ]]; then
    echo "[wsl_env_sync] ERROR: Could not determine WSL2 IP. Is WSL2 networking up?" >&2
    exit 1
fi

echo "[wsl_env_sync] WSL2 IP detected: ${WSL_IP}"

# ── Check for mirrored networking (Windows 11 22H2+) ─────────────────────────
# If mirrored mode is active, localhost on Windows reaches WSL2 services directly.
# In that case we use localhost everywhere instead of the WSL2 IP.
USE_LOCALHOST=false
if command -v powershell.exe &>/dev/null; then
    WSLCONFIG_PATH=$(powershell.exe -NoProfile -Command "[System.Environment]::GetFolderPath('UserProfile')" 2>/dev/null | tr -d '\r')/.wslconfig
    if powershell.exe -NoProfile -Command "
        if (Test-Path '$WSLCONFIG_PATH') {
            \$content = Get-Content '$WSLCONFIG_PATH' -Raw
            if (\$content -match 'networkingMode\s*=\s*mirrored') { exit 0 } else { exit 1 }
        } else { exit 1 }
    " 2>/dev/null; then
        USE_LOCALHOST=true
        echo "[wsl_env_sync] Mirrored networking detected — using localhost instead of WSL2 IP."
    fi
fi

if $USE_LOCALHOST; then
    TARGET_HOST="localhost"
else
    TARGET_HOST="${WSL_IP}"
fi

PROM_URL="http://${TARGET_HOST}:${PROM_PORT}"
MONGO_URI="mongodb://${TARGET_HOST}:${MONGO_PORT}"
WEBUI_URL="http://${TARGET_HOST}:${WEBUI_PORT}"
FAULT_URL="http://${TARGET_HOST}:${FAULT_INJECTION_PORT}"

# ── Update or create .env ─────────────────────────────────────────────────────
update_env_var() {
    local key="$1"
    local value="$2"
    local file="$3"

    if grep -qE "^${key}=" "$file" 2>/dev/null; then
        # Replace existing line (cross-platform sed)
        sed -i "s|^${key}=.*|${key}=${value}|" "$file"
    else
        # Append if not present
        echo "${key}=${value}" >> "$file"
    fi
}

# Create .env if it doesn't exist
if [[ ! -f "$ENV_FILE" ]]; then
    echo "[wsl_env_sync] .env not found at ${ENV_FILE} — creating from template."
    touch "$ENV_FILE"
fi

update_env_var "DATA_SOURCE_MODE"          "open5gs"     "$ENV_FILE"
update_env_var "OPEN5GS_PROMETHEUS_URL"   "$PROM_URL"   "$ENV_FILE"
update_env_var "OPEN5GS_MONGO_URI"        "$MONGO_URI"  "$ENV_FILE"
update_env_var "OPEN5GS_WEBUI_URL"        "$WEBUI_URL"  "$ENV_FILE"
update_env_var "OPEN5GS_FAULT_INJECTION_URL" "$FAULT_URL" "$ENV_FILE"
update_env_var "OPEN5GS_POLL_INTERVAL_S"  "5"           "$ENV_FILE"

echo "[wsl_env_sync] .env updated:"
echo "  OPEN5GS_PROMETHEUS_URL=${PROM_URL}"
echo "  OPEN5GS_MONGO_URI=${MONGO_URI}"
echo "  OPEN5GS_WEBUI_URL=${WEBUI_URL}"
echo "  OPEN5GS_FAULT_INJECTION_URL=${FAULT_URL}"

# ── Set up Windows portproxy rules (if NOT mirrored networking) ───────────────
if ! $USE_LOCALHOST && command -v powershell.exe &>/dev/null; then
    echo "[wsl_env_sync] Setting up Windows portproxy rules for IP ${WSL_IP}..."

    PORTPROXY_SCRIPT="
    \$wslIp = '${WSL_IP}'
    \$ports = @(${PROM_PORT}, ${MONGO_PORT}, ${WEBUI_PORT}, ${FAULT_INJECTION_PORT})
    foreach (\$port in \$ports) {
        # Remove existing rule if present (ignore errors)
        netsh interface portproxy delete v4tov4 listenport=\$port listenaddress=127.0.0.1 2>\$null | Out-Null
        # Add new rule
        netsh interface portproxy add v4tov4 listenport=\$port listenaddress=127.0.0.1 connectport=\$port connectaddress=\$wslIp
    }
    Write-Host '[wsl_env_sync] Portproxy rules set for: ' + (\$ports -join ', ')
    "

    # Run PowerShell as elevated if possible, otherwise warn
    if powershell.exe -NoProfile -Command "
        \$id = [System.Security.Principal.WindowsIdentity]::GetCurrent()
        \$p = [System.Security.Principal.WindowsPrincipal]\$id
        \$p.IsInRole([System.Security.Principal.WindowsBuiltInRole]::Administrator)
    " 2>/dev/null | grep -qi "true"; then
        powershell.exe -NoProfile -Command "$PORTPROXY_SCRIPT" 2>&1 | sed 's/^/  /'
    else
        echo "[wsl_env_sync] WARNING: PowerShell is not elevated — portproxy rules NOT set."
        echo "  Run the following from an elevated PowerShell to set them manually:"
        echo "  \$wslIp = '${WSL_IP}'"
        for PORT in $PROM_PORT $MONGO_PORT $WEBUI_PORT $FAULT_INJECTION_PORT; do
            echo "  netsh interface portproxy add v4tov4 listenport=${PORT} listenaddress=127.0.0.1 connectport=${PORT} connectaddress=\$wslIp"
        done
    fi
fi

echo "[wsl_env_sync] Done. WSL2 → Windows networking ready for NetOracle."
echo "[wsl_env_sync] Start NetOracle on Windows: python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000"
