"""Zentrale Konfiguration, geladen aus der .env-Datei."""
import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


def _bool(name: str, default: bool) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on", "ja")


PC_URL = os.getenv(
    "PC_URL",
    "https://www.pokemoncenter.com/de-de/category/trading-card-game"
    "?category=elite-trainer-box%2Ctins",
)
CHECK_INTERVAL_SECONDS = int(os.getenv("CHECK_INTERVAL_SECONDS", "90"))
HEADLESS = _bool("HEADLESS", False)
# Fenster aus dem sichtbaren Bereich schieben (laeuft weiter, stoert aber nicht).
BROWSER_OFFSCREEN = _bool("BROWSER_OFFSCREEN", False)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()
NOTIFY_ON = {
    x.strip().lower()
    for x in os.getenv("NOTIFY_ON", "new,restock").split(",")
    if x.strip()
}

WEB_HOST = os.getenv("WEB_HOST", "127.0.0.1")
WEB_PORT = int(os.getenv("WEB_PORT", "8080"))

DB_PATH = BASE_DIR / "pcalerts.db"
PROFILE_DIR = BASE_DIR / ".pw-profile"

TELEGRAM_ENABLED = bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID)
