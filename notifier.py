"""Benachrichtigungen: an die Zentrale (eigene App, app.fabian-social.dev) und
per Telegram-Bot-API (ohne Zusatzbibliothek).

Jede Meldung geht zuerst an die Zentrale (ZENTRALE_TOKEN in .env). Deren
Antwort enthaelt den Telegram-Schalter aus der App: steht er auf aus, bleibt
Telegram still. Ist die Zentrale nicht eingerichtet oder nicht erreichbar,
geht die Meldung wie bisher an Telegram - lieber doppelt als gar nicht.
"""
import html
import os
import re

import requests

import config
import db


def _api(method: str) -> str:
    return f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/{method}"


def _paused() -> bool:
    """Ueberwachung komplett pausiert: dann geht gar nichts raus."""
    try:
        return db.paused()
    except Exception:
        return False


def _telegram_on() -> bool:
    """Der Bot allein kann in der Weboberflaeche abgeschaltet werden."""
    try:
        return db.telegram_on()
    except Exception:
        return True


def _zentrale(message: dict) -> dict | None:
    """Meldung an die Zentrale. Gibt deren Antwort zurueck, None = nicht
    eingerichtet oder nicht erreichbar."""
    token = os.getenv("ZENTRALE_TOKEN", "").strip()
    if not token:
        return None
    url = os.getenv("ZENTRALE_URL", "http://127.0.0.1:8088").rstrip("/")
    try:
        r = requests.post(f"{url}/api/notify", json=message,
                          headers={"Authorization": f"Bearer {token}"}, timeout=10)
        return r.json() if r.ok else None
    except Exception:
        return None


def send_message(text: str, force: bool = False, zentrale: dict | None = None) -> bool:
    """text (HTML) geht an Telegram, zentrale (title/body/url/priority/tag) an
    die App. force=True nur fuer manuell ausgeloeste Testnachrichten - die
    sollen auch bei Pause oder abgeschaltetem Bot ankommen."""
    if not force and _paused():
        # Pausiert: nichts verschicken. Greift auch dann noch, wenn eine
        # Pruefung schon lief, als der Schalter umgelegt wurde.
        return False
    answer = _zentrale(zentrale) if zentrale else None
    sent = answer is not None
    if not force and answer is not None and answer.get("telegram") is False:
        return sent  # Telegram-Schalter in der Zentrale ist aus
    if not config.TELEGRAM_ENABLED or (not force and not _telegram_on()):
        return sent
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
        return r.ok or sent
    except Exception:
        return sent


def _tag(value: str) -> str:
    """Kennung fuer die Zentrale: gleiche Kennung ersetzt die vorige Meldung."""
    return re.sub(r"[^A-Za-z0-9._:-]", "-", value)[:64]


def notify_event(ev_type: str, p: dict) -> bool:
    raw_name = p.get("name") or p["id"]
    name = html.escape(raw_name)
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
    return send_message(text, zentrale={
        "title": title,
        "body": f"{raw_name}\nPreis: {price}\nStatus: {status}",
        "url": url or None,
        "priority": "high" if ev_type in ("new", "restock") else "normal",
        "tag": _tag(f"artikel-{p['id']}"),
    })


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
    body = ("Pokémon Center hat eine Warteschlange/Captcha vorgeschaltet – das passiert "
            "normalerweise nur bei einem Drop.")
    if note:
        body += f"\n\n{note}"
    body += "\n\n⚠️ Der Monitor kommt gerade nicht auf die Seite – am besten sofort selbst einreihen!"
    return send_message(text, zentrale={
        "title": "🚨 Drop-Alarm!", "body": body, "url": config.PC_URL, "priority": "high", "tag": "drop",
    })


def notify_unreachable(minutes: float, checks: int, note: str = "") -> bool:
    """Auffangnetz: Seite laenger am Stueck nicht erreichbar. Bei einem Drop
    macht der Bot-Schutz oft komplett dicht, ohne dass eine Warteschlange
    ueberhaupt sichtbar wird - dann ist das hier das einzige Signal."""
    text = (
        "⚠️ <b>Achtung – Seite nicht erreichbar!</b>\n\n"
        f"Seit <b>{int(minutes)} Minuten</b> ({checks} Prüfungen in Folge) kommt "
        "der Monitor nicht mehr auf die Kategorie-Seite.\n\n"
        "Das ist typisch für einen <b>Drop mit Warteschlange/Captcha</b> – "
        "kann aber auch nur der Bot-Schutz sein.\n"
    )
    if note:
        text += f"\n<i>{html.escape(note)}</i>\n"
    text += (
        f'\n<a href="{html.escape(config.PC_URL)}">Selbst nachsehen »</a>\n'
        "👉 Am besten kurz selbst im Browser prüfen – falls eine Warteschlange "
        "läuft, sofort einreihen!"
    )
    body = (f"Seit {int(minutes)} Minuten ({checks} Prüfungen in Folge) kommt der Monitor nicht mehr "
            "auf die Kategorie-Seite. Das ist typisch für einen Drop mit Warteschlange/Captcha – "
            "kann aber auch nur der Bot-Schutz sein.")
    if note:
        body += f"\n\n{note}"
    body += "\n\n👉 Am besten kurz selbst prüfen – falls eine Warteschlange läuft, sofort einreihen!"
    return send_message(text, zentrale={
        "title": "⚠️ Seite nicht erreichbar", "body": body, "url": config.PC_URL,
        "priority": "high", "tag": "drop",
    })


def notify_maintenance() -> bool:
    """Geplante Wartung erkannt - bewusst KEIN Drop-Alarm."""
    return send_message(
        "🛠 <b>Wartungsarbeiten</b>\n\n"
        "Pokémon Center ist gerade wegen geplanter Wartung offline "
        "(„Scheduled Maintenance“). Das ist <b>kein Drop</b>.\n"
        "Der Monitor prüft weiter und meldet sich, sobald der Shop wieder da ist.",
        zentrale={
            "title": "🛠 Wartungsarbeiten",
            "body": ("Pokémon Center ist wegen geplanter Wartung offline. Das ist kein Drop. Der Monitor "
                     "meldet sich, sobald der Shop wieder da ist."),
            "priority": "low", "tag": "wartung",
        },
    )


def notify_maintenance_over(minutes: float = 0.0) -> bool:
    dauer = f" (Dauer: {int(minutes)} Min.)" if minutes >= 1 else ""
    return send_message(
        f"✅ <b>Wartung beendet{dauer}:</b> Der Shop ist wieder erreichbar. "
        "Der Monitor prüft weiter.",
        zentrale={
            "title": f"✅ Wartung beendet{dauer}",
            "body": "Der Shop ist wieder erreichbar. Der Monitor prüft weiter.",
            "url": config.PC_URL, "priority": "low", "tag": "wartung",
        },
    )


def notify_queue_cleared(minutes: float = 0.0) -> bool:
    dauer = f" (Dauer: {int(minutes)} Min.)" if minutes >= 1 else ""
    return send_message(
        f"✅ <b>Entwarnung{dauer}:</b> Die Seite ist wieder normal erreichbar. "
        "Der Monitor prüft weiter.",
        zentrale={
            "title": f"✅ Entwarnung{dauer}",
            "body": "Die Seite ist wieder normal erreichbar. Der Monitor prüft weiter.",
            "url": config.PC_URL, "tag": "drop",
        },
    )


def send_test() -> bool:
    return send_message(
        "🔔 <b>PCAlerts</b> ist eingerichtet.\n"
        "Du bekommst hier Nachrichten, sobald neue Sammelkarten-Artikel "
        "gelistet oder wieder verfügbar sind.",
        force=True,
        zentrale={
            "title": "🔔 Testnachricht",
            "body": ("PCAlerts ist eingerichtet. Du bekommst hier Nachrichten, sobald neue "
                     "Sammelkarten-Artikel gelistet oder wieder verfügbar sind."),
        },
    )


if __name__ == "__main__":
    # python notifier.py  -> Testnachricht senden
    if not config.TELEGRAM_ENABLED:
        print("Telegram ist nicht konfiguriert (TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID in .env).")
    else:
        print("Testnachricht gesendet:", send_test())
