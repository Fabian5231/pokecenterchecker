@echo off
REM PCAlerts starten - einfach doppelklicken
cd /d "%~dp0"
title PCAlerts - Pokemon Center Monitor

REM --- Erststart: virtuelle Umgebung anlegen + Pakete installieren ---
if not exist ".venv\Scripts\python.exe" (
    echo ============================================
    echo   Erststart: installiere PCAlerts ...
    echo   Das kann ein paar Minuten dauern.
    echo ============================================
    python -m venv .venv
    ".venv\Scripts\python.exe" -m pip install --upgrade pip
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
    ".venv\Scripts\python.exe" -m patchright install chromium
)

REM --- .env anlegen, falls noch nicht vorhanden ---
if not exist ".env" (
    copy ".env.example" ".env" >nul
    echo.
    echo ============================================
    echo   Bitte jetzt die Datei .env bearbeiten
    echo   (Telegram-Token usw.) und danach dieses
    echo   Fenster erneut starten.
    echo ============================================
    notepad ".env"
    echo.
    pause
    exit /b
)

REM --- App starten ---
echo Starte PCAlerts ...  Weboberflaeche: http://127.0.0.1:8080
echo (Dieses Fenster offen lassen. Zum Beenden: dieses Fenster schliessen.)
".venv\Scripts\python.exe" web.py

echo.
echo PCAlerts wurde beendet.
pause
