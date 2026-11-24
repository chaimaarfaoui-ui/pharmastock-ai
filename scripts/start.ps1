# Starts the API (port 8000) and the web app (port 3000), each in its own window, then opens the browser.
# Run from anywhere:   powershell -ExecutionPolicy Bypass -File scripts\start.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$venvPy = Join-Path $root "backend\.venv\Scripts\python.exe"
if (-not (Test-Path $venvPy)) { throw "Run scripts\setup.ps1 first." }

Start-Process powershell -ArgumentList "-NoExit", "-Command", "Set-Location '$root\backend'; & '$venvPy' -m uvicorn app.main:app --reload"
Start-Process powershell -ArgumentList "-NoExit", "-Command", "Set-Location '$root\frontend'; npm run dev"
Write-Host "Starting... the web app needs about 15 seconds the first time."
Start-Sleep -Seconds 12
Start-Process "http://localhost:3000"
Write-Host "API docs: http://localhost:8000/docs   |   Stop the app by closing the two new windows."
