# PCAlerts starten (Windows / PowerShell)
$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

if (-not (Test-Path ".venv")) {
    Write-Host "Erstelle virtuelle Umgebung..." -ForegroundColor Cyan
    python -m venv .venv
    .\.venv\Scripts\python.exe -m pip install --upgrade pip
    .\.venv\Scripts\python.exe -m pip install -r requirements.txt
    .\.venv\Scripts\python.exe -m patchright install chromium
}
if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "Bitte .env bearbeiten (Telegram-Token etc.), dann erneut starten." -ForegroundColor Yellow
    exit
}

Write-Host "Starte PCAlerts..." -ForegroundColor Green
.\.venv\Scripts\python.exe web.py
