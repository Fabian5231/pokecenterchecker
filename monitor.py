"""Hintergrund-Schleife: prueft regelmaessig, erkennt neue/wieder verfuegbare
Artikel, speichert alles und benachrichtigt via Telegram.

WICHTIG: Der Playwright-Browser (Sync-API) darf nur aus EINEM Thread benutzt
werden. Deshalb laeuft der Scraper ausschliesslich im Monitor-Thread. Manuelle
Pruefungen aus dem Webserver werden ueber eine Warteschlange angefragt und im
Monitor-Thread ausgefuehrt (nie direkt aus dem Web-Thread heraus).
"""
import queue
import threading
import time

import config
import db
import notifier
from scraper import Scraper

# Statuswerte, nach denen langsamer weitergeprueft wird (Backoff).
TROUBLE_STATUSES = ("blocked", "queue", "empty")

# Weckruf fuer die Schleife: nur neu planen, keine Pruefung ausloesen.
_RESCHEDULE = object()


class Monitor:
    def __init__(self):
        self._scraper = Scraper()
        self._thread = None
        self._stop = threading.Event()
        self._req_q = queue.Queue()  # Anfragen fuer manuelle Sofort-Pruefungen
        self.status = "gestartet"
        self.last_error = ""
        # Alarm-Zustand einer Stoerungsphase (Queue/Captcha/blockiert/leer):
        # seit wann laeuft sie, wie viele Checks, wurde schon alarmiert?
        self._trouble_since = 0.0
        self._trouble_checks = 0
        self._alerted = False
        self._last_alert = 0.0
        # Zeitpunkt der letzten Pruefung (monotonic) - Basis fuer die naechste
        self._last_check_at = time.monotonic()

    # --- Diff-Logik -------------------------------------------------------
    def _process(self, products: list):
        seen_ts = db.now_iso()
        known = db.get_known_products()
        first_run = not db.has_baseline()

        events = []
        for p in products:
            prev = known.get(p["id"])
            if prev is None:
                if not first_run:
                    events.append(("new", p))
            else:
                if p["available"] and not bool(prev["available"]):
                    events.append(("restock", p))

        db.upsert_products(products, seen_ts)
        for ev_type, p in events:
            db.add_event(ev_type, p, seen_ts)
        for ev_type, p in events:
            if ev_type in config.NOTIFY_ON:
                notifier.notify_event(ev_type, p)
        return events, first_run

    # --- Drop-/Stoerungs-Alarm -------------------------------------------
    def _handle_trouble_alert(self, status: str, note: str):
        """Alarmieren, wenn der Monitor nicht mehr normal an die Seite kommt.

        Zwei Ausloeser:
          1. "queue" - Warteschlange/Captcha sicher erkannt -> sofort melden.
          2. Alles andere ausser "ok" (blockiert, Fehler, leere Seite), wenn es
             UNREACHABLE_ALERT_AFTER_MINUTES am Stueck anhaelt. Genau dieser
             Fall trat beim Drop auf: der Bot-Schutz machte komplett dicht,
             die Queue war gar nicht erst sichtbar - und der Monitor blieb
             stumm. Lieber ein Fehlalarm zu viel als einen Drop verpassen.

        Wiederholte Meldungen fruehestens alle QUEUE_ALERT_COOLDOWN_MINUTES.
        Nach dem ersten erfolgreichen Check gibt es eine Entwarnung.
        """
        now = time.time()

        if status == "ok":
            if self._alerted and config.QUEUE_ALERT:
                minutes = (now - self._trouble_since) / 60
                notifier.notify_queue_cleared(minutes)
            self._trouble_since = 0.0
            self._trouble_checks = 0
            self._alerted = False
            self._last_alert = 0.0
            return

        # Stoerung: Phase starten oder fortfuehren
        if not self._trouble_checks:
            self._trouble_since = now
        self._trouble_checks += 1
        if not config.QUEUE_ALERT:
            return

        minutes = (now - self._trouble_since) / 60
        cooldown = config.QUEUE_ALERT_COOLDOWN_MINUTES * 60
        due = not self._alerted or now - self._last_alert >= cooldown
        if not due:
            return

        if status == "queue":
            sent = notifier.notify_queue(note)
        elif minutes >= config.UNREACHABLE_ALERT_AFTER_MINUTES:
            sent = notifier.notify_unreachable(minutes, self._trouble_checks, note)
        else:
            return  # kurze Stoerung - erst mal abwarten
        if sent:
            self._alerted = True
            self._last_alert = now

    # --- Ein Durchlauf (NUR im Monitor-Thread aufrufen!) ------------------
    def check_once(self):
        res = self._scraper.fetch()
        self._handle_trouble_alert(res["status"], res.get("note", ""))
        if res["status"] == "ok":
            events, first_run = self._process(res["products"])
            num_avail = sum(1 for p in res["products"] if p["available"])
            if first_run:
                note = f"Erstlauf: {len(res['products'])} Artikel als Basis gespeichert."
            elif events:
                note = f"{len(events)} Ereignis(se): " + ", ".join(
                    f"{t}:{p['id']}" for t, p in events)
            else:
                note = res.get("note", "")
            db.add_check("ok", len(res["products"]), num_avail, note)
            self.status = "ok"
            self.last_error = ""
        else:
            db.add_check(res["status"], 0, 0, res["note"])
            self.status = res["status"]
            self.last_error = res["note"]
        return res

    def _safe_check(self):
        self._last_check_at = time.monotonic()
        try:
            return self.check_once()
        except Exception as e:
            self.status = "error"
            self.last_error = str(e)[:300]
            try:
                db.add_check("error", 0, 0, self.last_error)
            except Exception:
                pass
            return {"status": "error", "products": [], "note": self.last_error}

    def _next_wait(self, blocked_streak: int, status: str = "") -> float:
        interval = db.check_interval()
        if blocked_streak:
            # Waehrend einer Queue-Phase kuerzer deckeln, damit die
            # Entwarnung (Seite wieder frei) schnell kommt.
            cap = 300 if status == "queue" else 900
            return min(interval * (2 ** min(blocked_streak, 4)), cap)
        return interval

    # --- Von aussen (Web-Thread): sofortige Pruefung anfragen -------------
    def request_check(self, timeout: float = 150.0) -> dict:
        resp: queue.Queue = queue.Queue(maxsize=1)
        self._req_q.put(resp)
        try:
            return resp.get(timeout=timeout)
        except queue.Empty:
            return {"status": "pending",
                    "note": "Pruefung wurde angestossen und laeuft noch."}

    def reschedule(self):
        """Nach einer Intervall-Aenderung: laufende Wartezeit neu berechnen,
        damit ein kuerzeres Intervall sofort greift (statt erst nach Ablauf
        der alten, evtl. stundenlangen Wartezeit)."""
        self._req_q.put(_RESCHEDULE)

    # --- Schleife (Monitor-Thread) ---------------------------------------
    def _run(self):
        # Direkt beim Start einmal pruefen
        res = self._safe_check()
        last_status = res["status"]
        blocked_streak = 1 if last_status in TROUBLE_STATUSES else 0

        while not self._stop.is_set():
            # Deadline immer aus dem Zeitpunkt der letzten Pruefung ableiten,
            # damit ein geaendertes Intervall sofort richtig wirkt.
            remaining = (self._last_check_at
                         + self._next_wait(blocked_streak, last_status)
                         - time.monotonic())
            if remaining > 0:
                try:
                    item = self._req_q.get(timeout=remaining)
                except queue.Empty:
                    item = None
                if self._stop.is_set():
                    break
                if item is _RESCHEDULE:
                    continue  # nur neu planen, keine Pruefung
                if item is not None:
                    # Manuelle Pruefung im richtigen (diesem) Thread ausfuehren
                    r = self._safe_check()
                    last_status = r["status"]
                    blocked_streak = blocked_streak + 1 if last_status in TROUBLE_STATUSES else 0
                    try:
                        item.put_nowait(r)
                    except Exception:
                        pass
                    continue

            # Planmaessige Pruefung
            res = self._safe_check()
            last_status = res["status"]
            blocked_streak = blocked_streak + 1 if last_status in TROUBLE_STATUSES else 0

        self._scraper.close()

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        # Schleife aus dem Warten holen, damit sie nicht bis zum Ende des
        # Intervalls (u. U. Stunden) haengen bleibt.
        self._req_q.put(_RESCHEDULE)
