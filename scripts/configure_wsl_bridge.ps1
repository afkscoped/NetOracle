$ErrorActionPreference = "Stop"

$wslIp = (wsl hostname -I).Trim().Split(" ")[0]
if (-not $wslIp) {
    throw "Could not determine WSL2 IP. Is Ubuntu-22.04 running?"
}

Write-Host "WSL2 IP: $wslIp"

# ── 1. Update Windows hosts file ─────────────────────────────────────────────
$hostsPath = "C:\Windows\System32\drivers\etc\hosts"
$hostsLine = "$wslIp wsl.local"
$hostsText = Get-Content -Path $hostsPath -ErrorAction Stop

if ($hostsText -match "\s+wsl\.local$") {
    $updated = $hostsText | ForEach-Object {
        if ($_ -match "\s+wsl\.local$") { $hostsLine } else { $_ }
    }
    Set-Content -Path $hostsPath -Value $updated
    Write-Host "Updated existing wsl.local hosts entry."
} else {
    Add-Content -Path $hostsPath -Value $hostsLine
    Write-Host "Added wsl.local hosts entry."
}

# ── 2. Auto-update .env ───────────────────────────────────────────────────────
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot  = Split-Path -Parent $scriptDir
$envFile   = Join-Path $repoRoot ".env"

$envVars = @{
    "DATA_SOURCE_MODE"        = "open5gs"
    "OPEN5GS_PROMETHEUS_URL"  = "http://$wslIp:9090"
    "OPEN5GS_MONGO_URI"       = "mongodb://$wslIp:27017"
    "OPEN5GS_WEBUI_URL"       = "http://$wslIp:3000"
    "OPEN5GS_POLL_INTERVAL_S" = "5"
}

if (-not (Test-Path $envFile)) {
    Write-Host ".env not found — creating from template."
    New-Item -Path $envFile -ItemType File | Out-Null
}

$lines = [System.Collections.Generic.List[string]](Get-Content $envFile)
foreach ($key in $envVars.Keys) {
    $val  = $envVars[$key]
    $idx  = -1
    for ($i = 0; $i -lt $lines.Count; $i++) {
        if ($lines[$i] -match "^$key\s*=") { $idx = $i; break }
    }
    if ($idx -ge 0) {
        $lines[$idx] = "$key=$val"
    } else {
        $lines.Add("$key=$val")
    }
}
$lines | Set-Content $envFile

Write-Host ""
Write-Host ".env updated with Open5GS settings:"
foreach ($key in $envVars.Keys) {
    Write-Host "  $key=$($envVars[$key])"
}
Write-Host ""
Write-Host "NetOracle is ready for Open5GS mode."
Write-Host "Start or restart the server: python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload"

