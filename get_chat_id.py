"""Helfer zum Ermitteln der Telegram-Chat-ID.

So gehst du vor:
  1. Erstelle in Telegram einen Bot ueber @BotFather (/newbot) und kopiere den Token.
  2. Trage den Token in die .env-Datei ein (TELEGRAM_BOT_TOKEN=...).
  3. Schreibe deinem neuen Bot in Telegram irgendeine Nachricht (z. B. "hallo").
  4. Starte dieses Skript:  python get_chat_id.py
  5. Trage die angezeigte Chat-ID in die .env ein (TELEGRAM_CHAT_ID=...).
"""
import sys
import time

import requests

import config


def main():
    token = config.TELEGRAM_BOT_TOKEN
    if not token:
        print("Kein TELEGRAM_BOT_TOKEN in der .env gefunden.")
        print("Erst den Token von @BotFather eintragen, dann dieses Skript erneut starten.")
        sys.exit(1)

    base = f"https://api.telegram.org/bot{token}"
    print("Warte auf eine Nachricht an deinen Bot ...")
    print("=> Schreibe deinem Bot jetzt in Telegram eine beliebige Nachricht.\n")

    seen = None
    for _ in range(60):  # bis zu ~2 Minuten warten
        try:
            r = requests.get(f"{base}/getUpdates", timeout=15).json()
        except Exception as e:
            print("Netzwerkfehler:", e)
            time.sleep(2)
            continue
        if not r.get("ok"):
            print("Telegram-API-Fehler:", r)
            sys.exit(1)
        for upd in r.get("result", []):
            msg = upd.get("message") or upd.get("channel_post") or {}
            chat = msg.get("chat")
            if chat:
                seen = chat
        if seen:
            break
        time.sleep(2)

    if not seen:
        print("Keine Nachricht empfangen. Hast du dem Bot geschrieben?")
        sys.exit(1)

    cid = seen["id"]
    name = seen.get("first_name") or seen.get("title") or ""
    print("\n============================================")
    print(f"  Chat gefunden: {name}")
    print(f"  DEINE CHAT-ID: {cid}")
    print("============================================")
    print("\nTrage in die .env ein:")
    print(f"  TELEGRAM_CHAT_ID={cid}")


if __name__ == "__main__":
    main()
