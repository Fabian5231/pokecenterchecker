"""Hintergrund-Schleife: prueft regelmaessig, erkennt neue/wieder verfuegbare
Artikel, speichert alles und benachrichtigt via Telegram."""
import threading
import time

import config
import db
import notifier
from scraper import Scraper


class Monitor:
    def __init__(self):
        self._scraper = Scraper()
        self._thread = None
        self._stop = threading.Event()
        self.status = "gestartet"
        self.last_error = ""

    # --- Diff-Logik -------------------------------------------------------
    def _process(self, products: list):
        seen_ts = db.now_iso()
        known = db.get_known_products()
        first_run = not db.has_baseline()

        events = []
        for p in products:
            prev = known.get(p["id"])
            if prev is None:
                # Neuer Artikel in der Liste
                if not first_run:
                    events.append(("new", p))
            else:
                was_available = bool(prev["available"])
                if p["available"] and not was_available:
                    events.append(("restock", p))

        # Snapshot + Ereignisse speichern
        db.upsert_products(products, seen_ts)
        for ev_type, p in events:
            db.add_event(ev_type, p, seen_ts)

        # Benachrichtigen (nur konfigurierte Ereignistypen)
        for ev_type, p in events:
            if ev_type in config.NOTIFY_ON:
                notifier.notify_event(ev_type, p)

        return events, first_run

    # --- Ein Durchlauf ----------------------------------------------------
    def check_once(self):
        res = self._scraper.fetch()
        if res["status"] == "ok":
            events, first_run = self._process(res["products"])
            num_avail = sum(1 for p in res["products"] if p["available"])
            note = ""
            if first_run:
                note = f"Erstlauf: {len(res['products'])} Artikel als Basis gespeichert."
            elif events:
                note = f"{len(events)} Ereignis(se): " + ", ".join(
                    f"{t}:{p['id']}" for t, p in events)
            db.add_check("ok", len(res["products"]), num_avail, note)
            self.status = "ok"
            self.last_error = ""
        else:
            db.add_check(res["status"], 0, 0, res["note"])
            self.status = res["status"]
            self.last_error = res["note"]
        return res

    # --- Schleife ---------------------------------------------------------
    def _run(self):
        blocked_streak = 0
        while not self._stop.is_set():
            try:
                res = self.check_once()
                if res["status"] == "blocked":
                    blocked_streak += 1
                else:
                    blocked_streak = 0
            except Exception as e:  # darf die Schleife nie beenden
                self.status = "error"
                self.last_error = str(e)[:300]
                try:
                    db.add_check("error", 0, 0, self.last_error)
                except Exception:
                    pass
            # Bei anhaltender Blockade langsamer werden (Backoff bis max. 15 Min),
            # damit die blockierte Seite nicht dauernd angefasst wird.
            wait = config.CHECK_INTERVAL_SECONDS
            if blocked_streak:
                wait = min(config.CHECK_INTERVAL_SECONDS * (2 ** min(blocked_streak, 4)), 900)
            self._stop.wait(wait)
        self._scraper.close()

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
