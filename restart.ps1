# restart.ps1 — Full setup + kill existing + restart (Windows PowerShell)
# Run from the etl_validator project root folder:  .\restart.ps1
# First-time run does full setup; subsequent runs just restart.

param(
    [switch]$SkipSetup  # Use -SkipSetup to skip install steps on subsequent runs
)

$ErrorActionPreference = "Stop"
$ProjectRoot = $PSScriptRoot

Write-Host "=== ETL Validator — Windows Setup & Start ===" -ForegroundColor Cyan
Write-Host "Project root: $ProjectRoot"

# ============================================================
# STEP 1: Check prerequisites
# ============================================================
Write-Host "`n[1/7] Checking prerequisites..." -ForegroundColor Yellow

# Check Python
try {
    $pyVersion = python --version 2>&1
    Write-Host "  Python: $pyVersion" -ForegroundColor Green
} catch {
    Write-Host "  ERROR: Python not found. Install from https://www.python.org/downloads/" -ForegroundColor Red
    Write-Host "  Make sure to check 'Add Python to PATH' during install." -ForegroundColor Red
    exit 1
}

# Check Node.js
try {
    $nodeVersion = node --version 2>&1
    Write-Host "  Node.js: $nodeVersion" -ForegroundColor Green
} catch {
    Write-Host "  ERROR: Node.js not found. Install from https://nodejs.org/" -ForegroundColor Red
    exit 1
}

# Check npm
try {
    $npmVersion = npm --version 2>&1
    Write-Host "  npm: $npmVersion" -ForegroundColor Green
} catch {
    Write-Host "  ERROR: npm not found." -ForegroundColor Red
    exit 1
}

# ============================================================
# STEP 2: Create virtual environment (if not exists)
# ============================================================
Write-Host "`n[2/7] Setting up Python virtual environment..." -ForegroundColor Yellow

$venvPath = Join-Path $ProjectRoot ".venv"
if (-Not (Test-Path $venvPath)) {
    Write-Host "  Creating .venv..."
    python -m venv $venvPath
    Write-Host "  Created .venv" -ForegroundColor Green
} else {
    Write-Host "  .venv already exists" -ForegroundColor Gray
}

# Activate venv
$activateScript = Join-Path $venvPath "Scripts\Activate.ps1"
. $activateScript
Write-Host "  Virtual environment activated" -ForegroundColor Green

# ============================================================
# STEP 3: Install Python dependencies
# ============================================================
if (-Not $SkipSetup) {
    Write-Host "`n[3/7] Installing Python dependencies..." -ForegroundColor Yellow
    pip install --upgrade pip 2>&1 | Out-Null
    pip install -r (Join-Path $ProjectRoot "requirements.txt")
    pip install -e $ProjectRoot
    Write-Host "  Python packages installed" -ForegroundColor Green
} else {
    Write-Host "`n[3/7] Skipping Python install (-SkipSetup)" -ForegroundColor Gray
}

# ============================================================
# STEP 4: Install frontend dependencies
# ============================================================
if (-Not $SkipSetup) {
    Write-Host "`n[4/7] Installing frontend dependencies..." -ForegroundColor Yellow
    Push-Location (Join-Path $ProjectRoot "frontend")
    npm install
    Pop-Location
    Write-Host "  npm packages installed" -ForegroundColor Green
} else {
    Write-Host "`n[4/7] Skipping npm install (-SkipSetup)" -ForegroundColor Gray
}

# ============================================================
# STEP 5: Kill existing backend (port 8000)
# ============================================================
Write-Host "`n[5/7] Killing existing backend on port 8000..." -ForegroundColor Yellow
$backendPids = netstat -ano | Select-String "LISTENING" | Select-String ":8000\s" | ForEach-Object {
    ($_ -split '\s+')[-1]
} | Sort-Object -Unique | Where-Object { $_ -and $_ -ne "0" }

if ($backendPids) {
    foreach ($pid in $backendPids) {
        taskkill /PID $pid /F 2>$null | Out-Null
        Write-Host "  Killed PID $pid" -ForegroundColor Green
    }
} else {
    Write-Host "  No process on port 8000" -ForegroundColor Gray
}

# ============================================================
# STEP 6: Kill existing frontend (port 5173)
# ============================================================
Write-Host "`n[6/7] Killing existing frontend on port 5173..." -ForegroundColor Yellow
$frontendPids = netstat -ano | Select-String "LISTENING" | Select-String ":5173\s" | ForEach-Object {
    ($_ -split '\s+')[-1]
} | Sort-Object -Unique | Where-Object { $_ -and $_ -ne "0" }

if ($frontendPids) {
    foreach ($pid in $frontendPids) {
        taskkill /PID $pid /F 2>$null | Out-Null
        Write-Host "  Killed PID $pid" -ForegroundColor Green
    }
} else {
    Write-Host "  No process on port 5173" -ForegroundColor Gray
}

# ============================================================
# STEP 7: Start backend + frontend in new windows
# ============================================================
Write-Host "`n[7/7] Starting services..." -ForegroundColor Yellow

# Backend window
$backendCmd = "cd '$ProjectRoot'; & '$activateScript'; python -m uvicorn etl_validator.api:app --host 0.0.0.0 --port 8000 --reload"
Start-Process powershell -ArgumentList "-NoExit", "-Command", $backendCmd
Write-Host "  Backend starting at http://localhost:8000" -ForegroundColor Green

# Wait a moment for backend to grab the port
Start-Sleep -Seconds 2

# Frontend window
$frontendCmd = "cd '$(Join-Path $ProjectRoot 'frontend')'; npm run dev -- --host 0.0.0.0"
Start-Process powershell -ArgumentList "-NoExit", "-Command", $frontendCmd
Write-Host "  Frontend starting at http://localhost:5173" -ForegroundColor Green

# ============================================================
# Done
# ============================================================
Write-Host "`n=== Setup Complete ===" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Backend:  http://localhost:8000" -ForegroundColor White
Write-Host "  Frontend: http://localhost:5173" -ForegroundColor White
Write-Host ""
Write-Host "Two PowerShell windows opened (backend + frontend)."
Write-Host "Close them to stop the servers."
Write-Host ""
Write-Host "Next time, run with -SkipSetup to skip installs:" -ForegroundColor Gray
Write-Host "  .\restart.ps1 -SkipSetup" -ForegroundColor Gray
Write-Host ""
Write-Host "If accessing from another machine, allow firewall:" -ForegroundColor Gray
Write-Host "  New-NetFirewallRule -DisplayName 'ETL Validator' -Direction Inbound -LocalPort 8000,5173 -Protocol TCP -Action Allow" -ForegroundColor Gray
