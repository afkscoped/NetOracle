$ErrorActionPreference = "Stop"

$wslIp = (wsl hostname -I).Trim().Split(" ")[0]
if (-not $wslIp) {
    throw "Could not determine WSL2 IP. Is Ubuntu-22.04 running?"
}

Write-Host "WSL2 IP: $wslIp"

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

Write-Host ""
Write-Host "Add these values to NetOracle .env:"
Write-Host "DATA_SOURCE_MODE=open5gs"
Write-Host "OPEN5GS_PROMETHEUS_URL=http://wsl.local:9090"
Write-Host "OPEN5GS_MONGO_URI=mongodb://wsl.local:27017"
Write-Host "OPEN5GS_WEBUI_URL=http://wsl.local:3000"
Write-Host "OPEN5GS_POLL_INTERVAL_S=5"
