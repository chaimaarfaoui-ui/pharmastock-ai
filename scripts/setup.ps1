# One-time setup for Windows (no Docker needed; uses a local SQLite database).
# Run from anywhere:   powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

function Run([string]$exe, [string[]]$argv) {
    & $exe @argv
    if ($LASTEXITCODE -ne 0) { throw "Command failed: $exe $($argv -join ' ')" }
}

if ($root -match "OneDrive") {
    Write-Warning "This folder is inside OneDrive, which can break virtual environments. Moving it to e.g. C:\dev\pharmastock is strongly recommended."
}

# 1. Python 3.12 (newer versions such as 3.14 have no prebuilt numpy/pandas yet and hang while compiling)
$py = $null
try { $py = (& py -3.12 --version) 2>$null } catch { }
if (-not $py) { throw "Python 3.12 was not found. Install it with:  winget install Python.Python.3.12  then close and reopen PowerShell and run this script again." }
Write-Host "Found $py"

# 2. Node 18+
try { $node = (& node --version) } catch { throw "Node.js was not found. Install the LTS version from https://nodejs.org then run this script again." }
Write-Host "Found Node $node"

# 3. Backend
$backend = Join-Path $root "backend"
Push-Location $backend
if (-not (Test-Path ".venv\Scripts\python.exe")) {
    if (Test-Path ".venv") { Remove-Item ".venv" -Recurse -Force }      # a broken environment from an earlier failed attempt
    Run "py" @("-3.12", "-m", "venv", ".venv")
}
$venvPy = Join-Path $backend ".venv\Scripts\python.exe"
Run $venvPy @("-m", "pip", "install", "--upgrade", "pip")
Run $venvPy @("-m", "pip", "install", "-r", "requirements.txt")
if (-not (Test-Path ".env")) { "DATABASE_URL=sqlite:///dev.db" | Set-Content ".env" -Encoding ascii }
Run $venvPy @("-m", "alembic", "upgrade", "head")
Pop-Location

# 4. Frontend
$frontend = Join-Path $root "frontend"
Push-Location $frontend
if (-not (Test-Path ".env.local")) { Copy-Item ".env.example" ".env.local" }
Run "npm" @("install")
Pop-Location

Write-Host ""
Write-Host "Setup finished. Start the app with:   powershell -ExecutionPolicy Bypass -File scripts\start.ps1" -ForegroundColor Green
Write-Host "Optional check of the backend:         cd backend; .\.venv\Scripts\python.exe -m pytest   (expect: all tests pass)"
