# Deployment Guide

## Overview

The ETL Validator is fully automated for deployment on Windows machines using the `restart.ps1` script. The script auto-detects your Python and Node.js installations and requires **zero configuration**.

## Prerequisites

Before deploying on a new machine, ensure you have:

1. **Python 3.10 or higher**
   - Download: https://www.python.org/downloads/
   - **Important**: Check "Add Python to PATH" during installation
   - Verify: Open PowerShell and run `python --version`

2. **Node.js 18 or higher** (includes npm)
   - Download: https://nodejs.org/ (LTS version recommended)
   - Verify: Open PowerShell and run `node --version` and `npm --version`

3. **Git** (to clone the repository)
   - Download: https://git-scm.com/

## Deployment Steps

### Step 1: Clone the Repository

```powershell
git clone <repository-url> etl_validator
cd etl_validator
```

**Important**: The folder name must be `etl_validator` (not `etl-validator` or any other name) because the Python import system depends on it.

### Step 2: Run the Automated Setup

```powershell
powershell -ExecutionPolicy Bypass -File .\restart.ps1
```

That's it! The script will:

- **Auto-detect** Python and Node.js installations (no matter where they're installed)
- **Create** a Python virtual environment (`.venv`)
- **Install** all Python dependencies from `requirements.txt`
- **Install** all npm packages for the frontend
- **Start** the backend API (FastAPI/Uvicorn) on port 8000
- **Start** the frontend (React/Vite) on port 5173
- **Print** the URLs where you can access the application

### Step 3: Access the Application

Open your browser and navigate to:

- **Frontend UI**: http://localhost:5173
- **Backend API**: http://localhost:8000
- **API Documentation**: http://localhost:8000/docs

## Restarting the Application

To restart without reinstalling dependencies (faster):

```powershell
powershell -ExecutionPolicy Bypass -File .\restart.ps1 -SkipSetup
```

To restart with a full dependency reinstall:

```powershell
powershell -ExecutionPolicy Bypass -File .\restart.ps1
```

## How the Automation Works

### Auto-Detection Logic

The `restart.ps1` script uses intelligent detection to find Python and Node.js:

1. **Checks environment PATH first** - If Python/Node.js are in PATH, uses them immediately
2. **Searches common installation locations**:
   - `C:\Program Files\Python*\`
   - `C:\Program Files\nodejs\`
   - `C:\Users\<username>\AppData\Local\Programs\Python\`
   - And several other common paths

3. **Selects the latest version** if multiple installations exist

### What Gets Installed

#### Python Packages (`requirements.txt`)
- FastAPI & Uvicorn - Web framework and server
- Pandas & DuckDB - Data processing
- pyodbc - Database connectivity
- xlsxwriter - Excel report generation
- pyyaml - Configuration file parsing
- Click - CLI framework

#### NPM Packages (frontend)
- React 19 - UI library
- Vite - Frontend build tool
- Material-UI (MUI) - Component library
- Recharts - Data visualization
- Axios - HTTP client

## Troubleshooting

### "Python not found" error

**Solution**: Ensure Python 3.10+ is installed with "Add to PATH" checked:
1. Reinstall Python from https://www.python.org/downloads/
2. During installation, check the "Add Python to PATH" checkbox
3. Restart your computer or terminal
4. Retry the deployment script

### "Node.js not found" error

**Solution**: Install Node.js from https://nodejs.org/:
1. Download LTS version
2. Run installer with default settings
3. Restart your computer or terminal
4. Retry the deployment script

### Ports 8000 or 5173 already in use

**Solution**: The script automatically kills existing processes on these ports. If this fails:

```powershell
# Kill all processes on port 8000
Get-NetTCPConnection -LocalPort 8000 | ForEach-Object {Stop-Process -Id $_.OwningProcess -Force}

# Kill all processes on port 5173
Get-NetTCPConnection -LocalPort 5173 | ForEach-Object {Stop-Process -Id $_.OwningProcess -Force}
```

Then retry the script.

### PowerShell execution policy error

**Solution**: The script already handles this with `-ExecutionPolicy Bypass`. If you still get an error, ensure you're using the exact command:

```powershell
powershell -ExecutionPolicy Bypass -File .\restart.ps1
```

### npm install fails

**Solution**: Clear npm cache and retry:

```powershell
npm cache clean --force
powershell -ExecutionPolicy Bypass -File .\restart.ps1
```

## Accessing from Other Machines

To access the application from another machine on the same network:

1. Find your machine's IP address:
   ```powershell
   ipconfig
   ```
   Look for "IPv4 Address" (e.g., `192.168.1.100`)

2. Allow firewall access (Windows Defender):
   ```powershell
   New-NetFirewallRule -DisplayName 'ETL Validator' -Direction Inbound -LocalPort 8000,5173 -Protocol TCP -Action Allow
   ```

3. Access from another machine:
   - Frontend: `http://<your-ip>:5173`
   - Backend: `http://<your-ip>:8000`

## Manual Cleanup (if needed)

If you want to reset everything and start fresh:

```powershell
# Remove virtual environment
Remove-Item -Recurse -Force .venv

# Remove npm packages
Remove-Item -Recurse -Force frontend\node_modules

# Remove pip cache
Remove-Item -Recurse -Force $env:LOCALAPPDATA\pip\cache

# Then restart
powershell -ExecutionPolicy Bypass -File .\restart.ps1
```

## Environment Variables

The script respects existing PATH variables. To use specific Python or Node.js installations, add them to your PATH before running:

```powershell
$env:PATH = "C:\Custom\Python\Path;C:\Custom\Node\Path;$env:PATH"
powershell -ExecutionPolicy Bypass -File .\restart.ps1
```

## Script Output Example

```
=== ETL Validator - Windows Setup and Start ===
Project root: C:\Users\YourName\etl_validator

[1/7] Detecting prerequisites...
  Python: Python 3.12.10 at C:\Users\YourName\AppData\Local\Programs\Python\Python312\python.exe
  Node.js: v24.15.0 at C:\Program Files\nodejs\node.exe
  npm: 11.12.1 at C:\Program Files\nodejs\npm.cmd

[2/7] Setting up Python virtual environment...
  .venv already exists
  Virtual environment ready

[3/7] Installing Python dependencies...
  Python packages installed

[4/7] Installing frontend dependencies...
  npm packages installed

[5/7] Killing existing backend on port 8000...
  No process on port 8000

[6/7] Killing existing frontend on port 5173...
  No process on port 5173

[7/7] Starting services...
  Backend starting at http://localhost:8000
  Frontend starting at http://localhost:5173

=== Setup Complete ===

  Backend API:  http://localhost:8000
  API Docs:     http://localhost:8000/docs
  Frontend UI:  http://localhost:5173
```

## Advanced Options

### Custom Port Configuration

To use different ports, modify the `restart.ps1` script:

```powershell
# Find these lines and change the ports:
--port 8000      # Change to desired backend port
npm run dev -- --host 0.0.0.0  # Change port in frontend/vite.config.js
```

### Using a Different Python Version

The script auto-detects the latest Python 3.x. To force a specific version:

```powershell
$env:PATH = "C:\path\to\specific\python;$env:PATH"
powershell -ExecutionPolicy Bypass -File .\restart.ps1
```

## Getting Help

If you encounter issues:

1. Check the error message in the PowerShell output
2. Verify Python and Node.js are installed: `python --version` and `node --version`
3. Check that ports 8000 and 5173 are available
4. Try the "Manual Cleanup" section and restart
5. Review the Troubleshooting section above

## Summary

The automated deployment script (`restart.ps1`) is designed to work on any Windows machine with Python 3.10+ and Node.js installed. It requires **zero configuration** and automatically detects your installations, making it ideal for deploying across multiple machines without any changes.
