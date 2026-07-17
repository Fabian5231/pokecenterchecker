"""Telegram-Benachrichtigungen ueber die Bot-API (ohne Zusatzbibliothek)."""
import html

import requests

import config


def _api(method: str) -> str:
    return f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/{method}"


def send_message(text: str) -> bool:
    if not config.TELEGRAM_ENABLED:
        return False
    try:
        r = requests.post(
            _api("sendMessage"),
            json={
                "chat_id": config.TELEGRAM_CHAT_ID,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": False,
            },
            timeout=15,
        )
        return r.ok
    except Exception:
        return False


def notify_event(ev_type: str, p: dict) -> bool:
    name = html.escape(p.get("name") or p["id"])
    url = p.get("url") or ""
    price = p.get("price") or "?"
    if ev_type == "new":
        title = "🆕 Neuer Artikel gelistet!"
    elif ev_type == "restock":
        title = "✅ Wieder verfügbar!"
    else:
        title = "🔔 Aenderung"
    status = "✅ verfügbar" if p.get("available") else "❌ ausverkauft"
    text = (
        f"<b>{title}</b>\n\n"
        f"{name}\n"
        f"Preis: {html.escape(str(price))}\n"
        f"Status: {status}\n\n"
        f'<a href="{html.escape(url)}">Zum Artikel »</a>'
    )
    return send_message(text)


def notify_queue(note: str = "") -> bool:
    """Drop-Alarm: Warteschlange/Captcha ist der Pruefseite vorgeschaltet."""
    text = (
        "🚨 <b>Drop-Alarm!</b>\n\n"
        "Pokémon Center hat eine Warteschlange/Captcha vorgeschaltet - "
        "das passiert normalerweise nur bei einem Drop.\n"
    )
    if note:
        text += f"\n<i>{html.escape(note)}</i>\n"
    text += (
        f'\n<a href="{html.escape(config.PC_URL)}">Jetzt selbst in die Warteschlange »</a>\n'
        "⚠️ Der Monitor kommt gerade nicht auf die Seite - am besten sofort "
        "selbst im Browser einreihen!"
    )
    return send_message(text)


def notify_queue_cleared() -> bool:
    return send_message(
        "✅ <b>Entwarnung:</b> Die Warteschlange/Captcha ist weg, "
        "die Seite ist wieder normal erreichbar. Der Monitor prüft weiter."
    )


def send_test() -> bool:
    return send_message(
        "🔔 <b>PCAlerts</b> ist eingerichtet.\n"
        "Du bekommst hier Nachrichten, sobald neue Sammelkarten-Artikel "
        "gelistet oder wieder verfügbar sind."
    )


if __name__ == "__main__":
    # python notifier.py  -> Testnachricht senden
    if not config.TELEGRAM_ENABLED:
        print("Telegram ist nicht konfiguriert (TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID in .env).")
    else:
        print("Testnachricht gesendet:", send_test())
