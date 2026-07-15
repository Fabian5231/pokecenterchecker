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


def _extract_chat(upd: dict):
    """Chat-Objekt aus verschiedenen Update-Typen holen."""
    for key in ("message", "edited_message", "channel_post",
                "my_chat_member", "chat_member", "callback_query"):
        obj = upd.get(key)
        if not obj:
            continue
        chat = obj.get("chat") or (obj.get("message") or {}).get("chat")
        if chat:
            return chat
    return None


def main():
    token = config.TELEGRAM_BOT_TOKEN
    if not token:
        print("Kein TELEGRAM_BOT_TOKEN in der .env gefunden.")
        print("Erst den Token von @BotFather eintragen, dann erneut starten.")
        sys.exit(1)

    base = f"https://api.telegram.org/bot{token}"

    # Token pruefen
    me = requests.get(f"{base}/getMe", timeout=15).json()
    if not me.get("ok"):
        print("Token ungueltig? Antwort von Telegram:", me)
        sys.exit(1)
    print(f"Bot erkannt: @{me['result'].get('username')}")

    # Evtl. gesetzten Webhook entfernen - sonst liefert getUpdates nichts.
    requests.get(f"{base}/deleteWebhook",
                 params={"drop_pending_updates": "false"}, timeout=15)

    print("\nWarte auf eine Nachricht an deinen Bot ...")
    print("=> Schreibe deinem Bot jetzt in Telegram eine beliebige Nachricht.\n")

    seen = None
    offset = None
    for _ in range(30):  # bis zu ~2,5 Minuten (Long-Polling, 5 s je Runde)
        params = {"timeout": 5}
        if offset is not None:
            params["offset"] = offset
        try:
            r = requests.get(f"{base}/getUpdates", params=params, timeout=20).json()
        except Exception as e:
            print("Netzwerkfehler:", e)
            time.sleep(2)
            continue
        if not r.get("ok"):
            print("Telegram-API-Fehler:", r)
            sys.exit(1)
        for upd in r.get("result", []):
            offset = upd["update_id"] + 1
            chat = _extract_chat(upd)
            if chat:
                seen = chat
        if seen:
            break

    if not seen:
        print("Keine Nachricht empfangen.")
        print("Pruefe: richtiger Bot? Hast du IHM (nicht @BotFather) geschrieben?")
        print("Manuell testen:")
        print(f'  curl -s "{base}/getUpdates"')
        sys.exit(1)

    cid = seen["id"]
    name = seen.get("first_name") or seen.get("title") or seen.get("username") or ""
    print("\n============================================")
    print(f"  Chat gefunden: {name}")
    print(f"  DEINE CHAT-ID: {cid}")
    print("============================================")
    print("\nTrage in die .env ein:")
    print(f"  TELEGRAM_CHAT_ID={cid}")


if __name__ == "__main__":
    main()
