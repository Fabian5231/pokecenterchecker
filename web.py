"""Flask-Weboberflaeche + Start der Hintergrund-Ueberwachung."""
import threading
from datetime import datetime, timezone

from flask import Flask, jsonify, render_template, request

import config
import db
from monitor import Monitor

app = Flask(__name__)
monitor = Monitor()
_check_lock = threading.Lock()


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
        "interval": config.CHECK_INTERVAL_SECONDS,
        "url": config.PC_URL,
        "telegram": config.TELEGRAM_ENABLED,
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
        "checks": [
            {**c, "ts_fmt": _fmt(c["ts"])} for c in db.recent_checks(20)
        ],
    }


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/state")
def api_state():
    return jsonify(_state())


@app.route("/api/check-now", methods=["POST"])
def api_check_now():
    if not _check_lock.acquire(blocking=False):
        return jsonify({"ok": False, "msg": "Es laeuft bereits eine Pruefung."}), 409
    try:
        res = monitor.check_once()
        return jsonify({"ok": True, "status": res["status"], "note": res["note"]})
    finally:
        _check_lock.release()


def main():
    db.init()
    monitor.start()
    print(f"PCAlerts laeuft.  Weboberflaeche: http://{config.WEB_HOST}:{config.WEB_PORT}")
    print(f"Pruefintervall: alle {config.CHECK_INTERVAL_SECONDS} Sekunden")
    print(f"Telegram aktiv: {config.TELEGRAM_ENABLED}")
    # use_reloader=False, damit der Monitor-Thread nicht doppelt startet
    app.run(host=config.WEB_HOST, port=config.WEB_PORT,
            debug=False, use_reloader=False, threaded=True)


if __name__ == "__main__":
    main()
