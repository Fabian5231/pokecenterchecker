#!/usr/bin/env bash
# PCAlerts starten (Linux / macOS)
set -e
cd "$(dirname "$0")"

if [ ! -d ".venv" ]; then
  echo "Erstelle virtuelle Umgebung..."
  python3 -m venv .venv
  ./.venv/bin/python -m pip install --upgrade pip
  ./.venv/bin/python -m pip install -r requirements.txt
  ./.venv/bin/python -m patchright install chromium
fi
if [ ! -f ".env" ]; then
  cp .env.example .env
  echo "Bitte .env bearbeiten (Telegram-Token etc.), dann erneut starten."
  exit 0
fi

# HEADLESS-Wert aus .env lesen
HEADLESS_VAL=$(grep -E '^HEADLESS=' .env | cut -d= -f2 | tr -d '[:space:]' | tr 'A-Z' 'a-z')

# Auf einem Server ohne Bildschirm braucht der sichtbare Browser xvfb.
if [ "$HEADLESS_VAL" != "true" ] && [ -z "$DISPLAY" ]; then
  if command -v xvfb-run >/dev/null 2>&1; then
    echo "Kein Display gefunden -> starte mit xvfb-run (virtueller Bildschirm)."
    exec xvfb-run -a ./.venv/bin/python web.py
  else
    echo "WARNUNG: Kein Display und kein xvfb-run gefunden."
    echo "Installiere xvfb  (z. B.:  sudo apt install xvfb)  oder setze HEADLESS=true."
  fi
fi

exec ./.venv/bin/python web.py
