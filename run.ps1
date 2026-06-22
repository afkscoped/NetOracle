# ============================================================
# run.ps1  -  NetOracle one-click launcher
# Usage:  powershell -ExecutionPolicy Bypass -File run.ps1
# ============================================================
$ErrorActionPreference = "Stop"
$ProjectRoot = $PSScriptRoot

Write-Host ""
Write-Host "  NetOracle - 5G Network Intelligence Platform" -ForegroundColor Cyan
Write-Host "  ================================================" -ForegroundColor Cyan
Write-Host ""

# -- 1. Create / activate venv ----------------------------------------------
if (-not (Test-Path "$ProjectRoot\.venv\Scripts\python.exe")) {
    Write-Host "[1/4] Creating Python virtual environment..." -ForegroundColor Yellow
    python -m venv "$ProjectRoot\.venv"
}
$python = "$ProjectRoot\.venv\Scripts\python.exe"

# -- 2. Install dependencies (fast - pip skips already-installed) -----------
Write-Host "[2/4] Checking dependencies..." -ForegroundColor Yellow
& $python -m pip install --quiet --upgrade pip
& $python -m pip install --quiet -r "$ProjectRoot\requirements.txt"

# -- 3. Ensure .env exists -------------------------------------------------
if (-not (Test-Path "$ProjectRoot\.env")) {
    Write-Host "[3/4] Creating .env from example..." -ForegroundColor Yellow
    Copy-Item "$ProjectRoot\.env.example" "$ProjectRoot\.env"
} else {
    Write-Host "[3/4] .env found" -ForegroundColor Green
}

# -- 4. (Optional) Start Open5GS in WSL2 ----------------------------------
$wslStatus = wsl -l -v 2>$null | Out-String
if ($wslStatus -match "Running") {
    Write-Host "[4/4] Checking WSL2 / Open5GS..." -ForegroundColor Yellow
    Write-Host "      WSL2 is running. To start Open5GS services inside WSL run:" -ForegroundColor Green
    Write-Host "        wsl -d Ubuntu -u root bash scripts/start_open5gs.sh" -ForegroundColor DarkGray
} else {
    Write-Host "[4/4] WSL2 not running - data source will use simulation fallback." -ForegroundColor DarkYellow
}

# -- 5. Launch backend -----------------------------------------------------
Write-Host ""
Write-Host "  Starting NetOracle backend on http://127.0.0.1:8000" -ForegroundColor Cyan
Write-Host "  Dashboard: http://127.0.0.1:8000" -ForegroundColor Green
Write-Host "  Press Ctrl+C to stop" -ForegroundColor DarkGray
Write-Host ""

Set-Location $ProjectRoot
& $python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --log-level info
