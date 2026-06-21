#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Test WSL2 -> Windows connectivity for NetOracle Open5GS mode.
.DESCRIPTION
    Probes all ports that NetOracle needs to reach Open5GS services
    running inside WSL2. Run this from Windows PowerShell before
    switching DATA_SOURCE_MODE=open5gs to verify the bridge is working.
.EXAMPLE
    .\scripts\test_wsl_connectivity.ps1
#>

$ErrorActionPreference = "SilentlyContinue"

Write-Host ""
Write-Host "=============================================="
Write-Host "  NetOracle - WSL2 Connectivity Test"
Write-Host "=============================================="

# -- Detect WSL2 IP ---------------------------------------------------------
$wslIp = (wsl hostname -I 2>$null).Trim().Split(" ")[0]
if (-not $wslIp) {
    Write-Host "[FAIL] Could not detect WSL2 IP. Is WSL2 (Ubuntu) running?" -ForegroundColor Red
    Write-Host "       Run: wsl --distribution Ubuntu (or Ubuntu-22.04)"
    exit 1
}
Write-Host ""
Write-Host "WSL2 IP: $wslIp" -ForegroundColor Cyan

# -- Read .env for configured URL (if present) -----------------------------
$scriptDir   = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot    = Split-Path -Parent $scriptDir
$envFile     = Join-Path $repoRoot ".env"
$configuredUrl = $null
if (Test-Path $envFile) {
    $envContent = Get-Content $envFile
    foreach ($line in $envContent) {
        if ($line -match "^OPEN5GS_PROMETHEUS_URL=(.+)$") {
            $configuredUrl = $Matches[1].Trim()
            break
        }
    }
}
if ($configuredUrl) {
    Write-Host ".env OPEN5GS_PROMETHEUS_URL: $configuredUrl" -ForegroundColor Cyan
} else {
    Write-Host ".env OPEN5GS_PROMETHEUS_URL: (not set)" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Probing services..."
Write-Host ""

$targets = @(
    @{ Name = "Prometheus";               Url  = "http://${wslIp}:9090/-/healthy";   Port = 9090 },
    @{ Name = "Open5GS WebUI";            Url  = "http://${wslIp}:3000";             Port = 3000 },
    @{ Name = "AMF Prometheus exporter";  Url  = "http://${wslIp}:9095/metrics";     Port = 9095 },
    @{ Name = "SMF Prometheus exporter";  Url  = "http://${wslIp}:9096/metrics";     Port = 9096 },
    @{ Name = "UPF Prometheus exporter";  Url  = "http://${wslIp}:9097/metrics";     Port = 9097 },
    @{ Name = "PCF Prometheus exporter";  Url  = "http://${wslIp}:9098/metrics";     Port = 9098 },
    @{ Name = "Node Exporter";            Url  = "http://${wslIp}:9100/metrics";     Port = 9100 },
    @{ Name = "NetOracle API (Windows)";  Url  = "http://127.0.0.1:8000/health";     Port = 8000 }
)

$allOk = $true
foreach ($t in $targets) {
    $name = $t.Name
    $url  = $t.Url
    try {
        $resp = Invoke-WebRequest -Uri $url -TimeoutSec 3 -UseBasicParsing -ErrorAction Stop
        $code = $resp.StatusCode
        if ($code -eq 200) {
            Write-Host "  [OK]   $name  ($url)" -ForegroundColor Green
        } else {
            Write-Host "  [WARN] $name  -> HTTP $code  ($url)" -ForegroundColor Yellow
        }
    } catch {
        $allOk = $false
        Write-Host "  [FAIL] $name  -> $($_.Exception.Message.Split("`n")[0])  ($url)" -ForegroundColor Red
    }
}

# -- MongoDB TCP check (not HTTP) ---------------------------------------------
Write-Host ""
Write-Host "Probing MongoDB TCP port 27017..."
try {
    $tcp = New-Object System.Net.Sockets.TcpClient
    $conn = $tcp.BeginConnect($wslIp, 27017, $null, $null)
    $wait = $conn.AsyncWaitHandle.WaitOne(3000, $false)
    if ($wait -and $tcp.Connected) {
        Write-Host "  [OK]   MongoDB (TCP ${wslIp}:27017)" -ForegroundColor Green
    } else {
        $allOk = $false
        Write-Host "  [FAIL] MongoDB (TCP ${wslIp}:27017) - connection timed out" -ForegroundColor Red
    }
    $tcp.Close()
} catch {
    $allOk = $false
    Write-Host "  [FAIL] MongoDB (TCP ${wslIp}:27017) - $($_.Exception.Message)" -ForegroundColor Red
}

Write-Host ""
Write-Host "=============================================="
if ($allOk) {
    Write-Host "All services reachable. NetOracle is ready." -ForegroundColor Green
    Write-Host ""
    Write-Host "To switch to live Open5GS data:"
    Write-Host "  1. Ensure .env has DATA_SOURCE_MODE=open5gs"
    Write-Host "  2. (Re)start NetOracle server"
    Write-Host "  3. GET http://127.0.0.1:8000/api/open5gs/health"
} else {
    Write-Host "Some services are unreachable." -ForegroundColor Yellow
    Write-Host ""
    Write-Host "Troubleshooting:"
    Write-Host "  1. Start Open5GS in WSL2:  bash scripts/start_open5gs.sh"
    Write-Host "  2. Set up portproxy:        .\scripts\configure_wsl_bridge.ps1  (run as Admin)"
    Write-Host "  3. Re-run this script"
    Write-Host ""
    Write-Host "For first-time Open5GS installation in WSL2:"
    Write-Host "  bash scripts/install_open5gs_wsl.sh"
}
Write-Host "=============================================="
Write-Host ""
