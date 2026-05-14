# restart.ps1 - Full setup + kill existing + restart (Windows PowerShell)
# IMPORTANT: The folder MUST be named "etl_validator" for Python imports to work.
#   git clone https://github.com/anilmannem/etl-automation.git etl_validator
#   cd etl_validator
#   powershell -ExecutionPolicy Bypass -File .\restart.ps1
# First-time run does full setup; subsequent runs just restart.

param(
    [switch]$SkipSetup  # Use -SkipSetup to skip install steps on subsequent runs
)

$ErrorActionPreference = "Stop"
$ProjectRoot = $PSScriptRoot

# ============================================================
# HELPER: Find Python executable in common locations
# ============================================================
function Get-PythonExe {
    # Try Python in PATH first (but skip Windows Store alias)
    try {
        $pythonCmd = Get-Command python -ErrorAction SilentlyContinue
        if ($pythonCmd -and $pythonCmd.Path -notlike "*WindowsApps*" -and (Test-Path $pythonCmd.Path)) {
            # Verify it actually works
            & $pythonCmd.Path --version 2>&1 | Out-Null
            return $pythonCmd.Path
        }
    } catch {}

    # Common installation locations to check
    $searchPaths = @(
        "$env:ProgramFiles\Python*\python.exe",
        "$env:ProgramFiles(x86)\Python*\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python*\python.exe",
        "$env:APPDATA\Python\*\python.exe",
        "C:\Python*\python.exe"
    )

    foreach ($pattern in $searchPaths) {
        $matches = @(Get-Item $pattern -ErrorAction SilentlyContinue | Sort-Object Name -Descending)
        if ($matches.Count -gt 0) {
            foreach ($pythonPath in $matches) {
                try {
                    # Verify it actually works
                    & $pythonPath.FullName --version 2>&1 | Out-Null
                    return $pythonPath.FullName
                } catch {}
            }
        }
    }

    return $null
}

# ============================================================
# HELPER: Find Node.js executable in common locations
# ============================================================
function Get-NodeExe {
    # Try node in PATH first (but skip Windows Store alias)
    try {
        $nodeCmd = Get-Command node -ErrorAction SilentlyContinue
        if ($nodeCmd -and $nodeCmd.Path -notlike "*WindowsApps*" -and (Test-Path $nodeCmd.Path)) {
            # Verify it actually works
            & $nodeCmd.Path --version 2>&1 | Out-Null
            return $nodeCmd.Path
        }
    } catch {}

    # Common installation locations
    $searchPaths = @(
        "$env:ProgramFiles\nodejs\node.exe",
        "$env:ProgramFiles(x86)\nodejs\node.exe",
        "$env:LOCALAPPDATA\Programs\nodejs\node.exe",
        "C:\nodejs\node.exe"
    )

    foreach ($path in $searchPaths) {
        if (Test-Path $path) {
            try {
                & $path --version 2>&1 | Out-Null
                return $path
            } catch {}
        }
    }

    return $null
}

# ============================================================
# HELPER: Find npm command/script in common locations
# ============================================================
function Get-NpmCmd {
    # Try npm.cmd first (batch file - more reliable)
    try {
        $npmCmd = Get-Command npm.cmd -ErrorAction SilentlyContinue
        if ($npmCmd) {
            return $npmCmd.Path
        }
    } catch {}

    # Try npm as fallback
    try {
        $npmCmd = Get-Command npm -ErrorAction SilentlyContinue
        if ($npmCmd -and $npmCmd.Path -notlike "*.ps1") {
            return $npmCmd.Path
        }
    } catch {}

    # Common installation locations for npm.cmd
    $searchPaths = @(
        "$env:ProgramFiles\nodejs\npm.cmd",
        "$env:ProgramFiles(x86)\nodejs\npm.cmd",
        "$env:LOCALAPPDATA\Programs\nodejs\npm.cmd",
        "$env:ProgramFiles\nodejs\npm",
        "$env:ProgramFiles(x86)\nodejs\npm"
    )

    foreach ($path in $searchPaths) {
        if (Test-Path $path) {
            return $path
        }
    }

    return $null
}

# ============================================================
# STEP 1: Detect and validate prerequisites
# ============================================================
Write-Host "=== ETL Validator - Windows Setup and Start ===" -ForegroundColor Cyan
Write-Host "Project root: $ProjectRoot"
Write-Host "`n[1/7] Detecting prerequisites..." -ForegroundColor Yellow

# Detect Python
$pythonExe = Get-PythonExe
if (-not $pythonExe) {
    Write-Host "  ERROR: Python not found in PATH or common locations." -ForegroundColor Red
    Write-Host "  Please install Python from https://www.python.org/downloads/" -ForegroundColor Red
    Write-Host "  Check 'Add Python to PATH' during installation." -ForegroundColor Red
    exit 1
}

$pyVersion = & $pythonExe --version 2>&1
Write-Host "  Python: $pyVersion at $pythonExe" -ForegroundColor Green

# Detect Node.js
$nodeExe = Get-NodeExe
if (-not $nodeExe) {
    Write-Host "  ERROR: Node.js not found in PATH or common locations." -ForegroundColor Red
    Write-Host "  Please install Node.js from https://nodejs.org/" -ForegroundColor Red
    exit 1
}

$nodeVersion = & $nodeExe --version 2>&1
Write-Host "  Node.js: $nodeVersion at $nodeExe" -ForegroundColor Green

# Detect npm
$npmCmd = Get-NpmCmd
if (-not $npmCmd) {
    Write-Host "  ERROR: npm not found in PATH or common locations." -ForegroundColor Red
    exit 1
}

$npmVersion = & $npmCmd --version 2>&1
Write-Host "  npm: $npmVersion at $npmCmd" -ForegroundColor Green

# Setup PATH with detected executables
$pythonDir = Split-Path $pythonExe
$npmDir = Split-Path $npmCmd
if ($env:PATH -notlike "*$pythonDir*") {
    $env:PATH = "$pythonDir;$npmDir;" + $env:PATH
}

# ============================================================
# STEP 2: Create virtual environment (if not exists)
# ============================================================
Write-Host "`n[2/7] Setting up Python virtual environment..." -ForegroundColor Yellow

$venvPath = Join-Path $ProjectRoot ".venv"
$venvPythonExe = Join-Path $venvPath "Scripts\python.exe"

if (-Not (Test-Path $venvPath)) {
    Write-Host "  Creating .venv..."
    & $pythonExe -m venv $venvPath
    Write-Host "  Created .venv" -ForegroundColor Green
} else {
    Write-Host "  .venv already exists" -ForegroundColor Gray
}

Write-Host "  Virtual environment ready" -ForegroundColor Green

# ============================================================
# STEP 3: Install Python dependencies
# ============================================================
if (-Not $SkipSetup) {
    Write-Host "`n[3/7] Installing Python dependencies..." -ForegroundColor Yellow
    & $venvPythonExe -m pip install --upgrade pip --quiet
    & $venvPythonExe -m pip install -r (Join-Path $ProjectRoot "requirements.txt")
    & $venvPythonExe -m pip install -e $ProjectRoot
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
    
    # Use npm.cmd directly to avoid PowerShell execution policy issues
    $npmPath = Split-Path $npmCmd
    $env:PATH = "$npmPath;" + $env:PATH
    
    & $npmCmd install
    Pop-Location
    Write-Host "  npm packages installed" -ForegroundColor Green
} else {
    Write-Host "`n[4/7] Skipping npm install (-SkipSetup)" -ForegroundColor Gray
}

# ============================================================
# STEP 5: Kill existing backend (port 8000)
# ============================================================
Write-Host "`n[5/7] Killing existing backend on port 8000..." -ForegroundColor Yellow
try {
    $backendPids = netstat -ano | Select-String "LISTENING" | Select-String ":8000\s" | ForEach-Object {
        ($_ -split '\s+')[-1]
    } | Sort-Object -Unique | Where-Object { $_ -and $_ -ne "0" }

    if ($backendPids) {
        foreach ($processId in $backendPids) {
            Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
            Write-Host "  Killed PID $processId" -ForegroundColor Green
        }
    } else {
        Write-Host "  No process on port 8000" -ForegroundColor Gray
    }
} catch {
    Write-Host "  No process on port 8000" -ForegroundColor Gray
}

# ============================================================
# STEP 6: Kill existing frontend (port 5173)
# ============================================================
Write-Host "`n[6/7] Killing existing frontend on port 5173..." -ForegroundColor Yellow
try {
    $frontendPids = netstat -ano | Select-String "LISTENING" | Select-String ":5173\s" | ForEach-Object {
        ($_ -split '\s+')[-1]
    } | Sort-Object -Unique | Where-Object { $_ -and $_ -ne "0" }

    if ($frontendPids) {
        foreach ($processId in $frontendPids) {
            Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
            Write-Host "  Killed PID $processId" -ForegroundColor Green
        }
    } else {
        Write-Host "  No process on port 5173" -ForegroundColor Gray
    }
} catch {
    Write-Host "  No process on port 5173" -ForegroundColor Gray
}

# ============================================================
# STEP 7: Start backend + frontend as background jobs
# ============================================================
Write-Host "`n[7/7] Starting services..." -ForegroundColor Yellow

# Prepare PATH for child processes
$pythonDir = Split-Path $pythonExe
$nodeDir = Split-Path $nodeExe
$npmDir = Split-Path $npmCmd
$env:PATH = "$pythonDir;$nodeDir;$npmDir;" + $env:PATH

# Backend — must run from PARENT directory so Python finds etl_validator package
$parentDir = Split-Path $ProjectRoot -Parent
Start-Process -FilePath $venvPythonExe -ArgumentList "-m uvicorn etl_validator.api:app --host 0.0.0.0 --port 8000 --reload --reload-dir `"$ProjectRoot`"" -WorkingDirectory $parentDir -WindowStyle Hidden
Write-Host "  Backend starting at http://localhost:8000" -ForegroundColor Green

# Wait a moment for backend to grab the port
Start-Sleep -Seconds 3

# Frontend — use npx.cmd to run vite dev server
$frontendDir = Join-Path $ProjectRoot "frontend"
$npxCmd = Join-Path (Split-Path $npmCmd) "npx.cmd"
Start-Process -FilePath $npxCmd -ArgumentList "vite --host 0.0.0.0 --port 5173" -WorkingDirectory $frontendDir -WindowStyle Hidden
Write-Host "  Frontend starting at http://localhost:5173" -ForegroundColor Green

# ============================================================
# Done
# ============================================================
Write-Host "`n=== Setup Complete ===" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Backend API:  http://localhost:8000" -ForegroundColor White
Write-Host "  API Docs:     http://localhost:8000/docs" -ForegroundColor White
Write-Host "  Frontend UI:  http://localhost:5173" -ForegroundColor White
Write-Host ""
Write-Host "Services running as hidden background processes." -ForegroundColor Gray
Write-Host ""
Write-Host "Useful commands:" -ForegroundColor Cyan
Write-Host "  netstat -ano | findstr ':8000'   # Check backend process" -ForegroundColor Gray
Write-Host "  netstat -ano | findstr ':5173'   # Check frontend process" -ForegroundColor Gray
Write-Host "  taskkill /F /PID <pid>           # Kill a specific process" -ForegroundColor Gray
Write-Host ""
Write-Host "Auto-detection Summary:" -ForegroundColor Cyan
Write-Host "  Python:   $pythonExe"
Write-Host "  Node.js:  $nodeExe"
Write-Host "  npm:      $npmCmd"
Write-Host ""
Write-Host "Next time, run with -SkipSetup to skip dependency installs:" -ForegroundColor Gray
Write-Host "  powershell -ExecutionPolicy Bypass -File .\restart.ps1 -SkipSetup" -ForegroundColor Gray
Write-Host ""
Write-Host "To use on another machine:" -ForegroundColor Cyan
Write-Host "  1. Clone repo: git clone <repo-url> etl_validator" -ForegroundColor Gray
Write-Host "  2. Install Python 3.10+: https://www.python.org/downloads/" -ForegroundColor Gray
Write-Host "  3. Install Node.js: https://nodejs.org/" -ForegroundColor Gray
Write-Host "  4. Run: powershell -ExecutionPolicy Bypass -File .\restart.ps1" -ForegroundColor Gray
Write-Host ""
Write-Host "For firewall access from other machines:" -ForegroundColor Cyan
Write-Host "  New-NetFirewallRule -DisplayName 'ETL Validator' -Direction Inbound -LocalPort 8000,5173 -Protocol TCP -Action Allow" -ForegroundColor Gray
