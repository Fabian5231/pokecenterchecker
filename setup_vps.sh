#!/usr/bin/env bash
# Einmalige Einrichtung auf einem Linux-VPS (Debian/Ubuntu) OHNE Grafikoberflaeche.
# Installiert alles Noetige inkl. xvfb (virtueller, unsichtbarer Bildschirm).
set -e
cd "$(dirname "$0")"

echo "==> System-Pakete (python venv, xvfb) ..."
sudo apt-get update
sudo apt-get install -y python3-venv python3-pip xvfb

echo "==> Virtuelle Umgebung + Python-Pakete ..."
python3 -m venv .venv
./.venv/bin/python -m pip install --upgrade pip
./.venv/bin/python -m pip install -r requirements.txt

echo "==> Chromium herunterladen ..."
./.venv/bin/python -m patchright install chromium

echo "==> System-Abhaengigkeiten von Chromium ..."
# Braucht i. d. R. sudo; faellt sonst auf den Nicht-sudo-Versuch zurueck.
sudo ./.venv/bin/python -m patchright install-deps chromium \
  || ./.venv/bin/python -m patchright install-deps chromium \
  || echo "   (install-deps uebersprungen - ggf. manuell nachinstallieren)"

if [ ! -f .env ]; then
  cp .env.example .env
  echo "==> .env angelegt. Bitte jetzt bearbeiten:  nano .env"
  echo "    (Telegram-Token/Chat-ID; HEADLESS=false lassen!)"
fi

echo ""
echo "Fertig. Zum Testen im Vordergrund:   ./run.sh"
echo "Fuer Dauerbetrieb als Dienst:        siehe README.md (Abschnitt VPS/systemd)"
