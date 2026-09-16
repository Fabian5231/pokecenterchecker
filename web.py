"""Flask-Weboberflaeche + Start der Hintergrund-Ueberwachung."""
from datetime import datetime, timezone

from flask import Flask, jsonify, render_template, request, send_from_directory

import config
import db
import notifier
from monitor import Monitor

app = Flask(__name__)
monitor = Monitor()


def _fmt(ts: str) -> str:
    """ISO-UTC -> lesbare lokale Zeit."""
    if not ts:
        return "–"
    try:
        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone().strftime("%d.%m.%Y %H:%M:%S")
    except Exception:
        return ts


def _state() -> dict:
    last = db.last_check()
    return {
        "status": monitor.status,
        "last_error": monitor.last_error,
        "paused": db.paused(),
        "interval": db.check_interval(),
        "interval_min": config.INTERVAL_MIN_SECONDS,
        "interval_max": config.INTERVAL_MAX_SECONDS,
        "url": config.PC_URL,
        # konfiguriert (Token + Chat-ID in der .env) vs. eingeschaltet (Schalter
        # in der Weboberflaeche) - zwei verschiedene Dinge.
        "telegram": config.TELEGRAM_ENABLED,
        "telegram_on": db.telegram_on(),
        "notify_on": sorted(config.NOTIFY_ON),
        "last_check": _fmt(last["ts"]) if last else None,
        "last_check_status": last["status"] if last else None,
        "last_check_note": last["note"] if last else "",
        "products": [
            {**p, "first_seen_fmt": _fmt(p["first_seen"]),
             "last_seen_fmt": _fmt(p["last_seen"])}
            for p in db.current_products()
        ],
        "events": [
            {**e, "ts_fmt": _fmt(e["ts"])} for e in db.recent_events(40)
        ],
    }


PER_PAGE_OPTIONS = (20, 30, 50)


def _checks_page(page: int, per_page: int) -> dict:
    if per_page not in PER_PAGE_OPTIONS:
        per_page = PER_PAGE_OPTIONS[0]
    total = db.count_checks()
    total_pages = max(1, (total + per_page - 1) // per_page)
    page = max(1, min(page, total_pages))
    offset = (page - 1) * per_page
    return {
        "checks": [
            {**c, "ts_fmt": _fmt(c["ts"])}
            for c in db.recent_checks(per_page, offset)
        ],
        "page": page,
        "per_page": per_page,
        "total": total,
        "total_pages": total_pages,
    }


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/favicon.ico")
def favicon():
    return send_from_directory(app.static_folder, "favicon.ico",
                               mimetype="image/x-icon")


@app.route("/api/state")
def api_state():
    return jsonify(_state())


@app.route("/api/checks")
def api_checks():
    try:
        page = int(request.args.get("page", 1))
    except (TypeError, ValueError):
        page = 1
    try:
        per_page = int(request.args.get("per_page", PER_PAGE_OPTIONS[0]))
    except (TypeError, ValueError):
        per_page = PER_PAGE_OPTIONS[0]
    return jsonify(_checks_page(page, per_page))


@app.route("/api/interval", methods=["POST"])
def api_interval():
    """Pruefintervall zur Laufzeit aendern (wird in der DB gespeichert)."""
    data = request.get_json(silent=True) or {}
    try:
        seconds = int(data.get("seconds"))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "Bitte eine Zahl angeben."}), 400
    if not config.INTERVAL_MIN_SECONDS <= seconds <= config.INTERVAL_MAX_SECONDS:
        return jsonify({
            "ok": False,
            "error": f"Erlaubt sind {config.INTERVAL_MIN_SECONDS}–"
                     f"{config.INTERVAL_MAX_SECONDS} Sekunden.",
        }), 400
    seconds = db.set_check_interval(seconds)
    # Laufende Wartezeit neu berechnen, damit die Aenderung sofort greift
    monitor.reschedule()
    return jsonify({"ok": True, "interval": seconds})


@app.route("/api/pause", methods=["POST"])
def api_pause():
    """Ueberwachung komplett pausieren bzw. fortsetzen.

    Pausiert: keine Abfragen der Seite und keine Telegram-Nachrichten. Der
    Zustand steht in der DB und gilt darum auch nach einem Neustart weiter.
    """
    data = request.get_json(silent=True) or {}
    value = data.get("paused")
    if not isinstance(value, bool):
        return jsonify({"ok": False,
                        "error": "Feld 'paused' (true/false) fehlt."}), 400
    paused = db.set_paused(value)
    # Schleife sofort wecken, damit die Pause nicht erst nach Ablauf der
    # laufenden Wartezeit greift.
    monitor.reschedule()
    return jsonify({"ok": True, "paused": paused})


@app.route("/api/telegram", methods=["POST"])
def api_telegram():
    """Nur den Telegram-Bot an-/abschalten - unabhaengig von der Pause.

    Abgeschaltet: der Monitor prueft ganz normal weiter und erfasst auch
    Ereignisse, es geht nur keine Nachricht raus. Der Zustand steht in der DB
    und gilt darum auch nach einem Neustart weiter.
    """
    data = request.get_json(silent=True) or {}
    value = data.get("enabled")
    if not isinstance(value, bool):
        return jsonify({"ok": False,
                        "error": "Feld 'enabled' (true/false) fehlt."}), 400
    if value and not config.TELEGRAM_ENABLED:
        return jsonify({
            "ok": False,
            "error": "Telegram ist nicht konfiguriert "
                     "(TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID in .env).",
        }), 409
    enabled = db.set_telegram_on(value)
    return jsonify({"ok": True, "telegram_on": enabled})


@app.route("/api/telegram-test", methods=["POST"])
def api_telegram_test():
    """Testnachricht senden - unabhaengig von Pause/Bot-Schalter (force=True)."""
    if not config.TELEGRAM_ENABLED:
        return jsonify({
            "ok": False,
            "error": "Telegram ist nicht konfiguriert "
                     "(TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID in .env).",
        }), 409
    sent = notifier.send_test()
    if not sent:
        return jsonify({"ok": False, "error": "Senden fehlgeschlagen - Token/Chat-ID prüfen."}), 502
    return jsonify({"ok": True})


@app.route("/api/check-now", methods=["POST"])
def api_check_now():
    if db.paused():
        return jsonify({"ok": False, "status": "paused",
                        "note": "Pausiert - erst fortsetzen."}), 409
    # WICHTIG: nicht selbst scrapen (anderer Thread!), sondern den
    # Monitor-Thread um eine sofortige Pruefung bitten.
    res = monitor.request_check()
    return jsonify({"ok": True, "status": res["status"], "note": res.get("note", "")})


def main():
    db.init()
    monitor.start()
    print(f"PCAlerts laeuft.  Weboberflaeche: http://{config.WEB_HOST}:{config.WEB_PORT}")
    print(f"Pruefintervall: alle {db.check_interval()} Sekunden")
    print(f"Telegram konfiguriert: {config.TELEGRAM_ENABLED}")
    if config.TELEGRAM_ENABLED and not db.telegram_on():
        print("Hinweis: Telegram-Bot ist ABGESCHALTET (in der Weboberflaeche einschalten).")
    if db.paused():
        print("Achtung: Ueberwachung ist PAUSIERT (in der Weboberflaeche fortsetzen).")
    # use_reloader=False, damit der Monitor-Thread nicht doppelt startet
    app.run(host=config.WEB_HOST, port=config.WEB_PORT,
            debug=False, use_reloader=False, threaded=True)


if __name__ == "__main__":
    main()
