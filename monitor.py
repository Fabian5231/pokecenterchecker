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


class Monitor:
    def __init__(self):
        self._scraper = Scraper()
        self._thread = None
        self._stop = threading.Event()
        self._req_q = queue.Queue()  # Anfragen fuer manuelle Sofort-Pruefungen
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

    # --- Ein Durchlauf (NUR im Monitor-Thread aufrufen!) ------------------
    def check_once(self):
        res = self._scraper.fetch()
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

    def _next_wait(self, blocked_streak: int) -> float:
        if blocked_streak:
            return min(config.CHECK_INTERVAL_SECONDS * (2 ** min(blocked_streak, 4)), 900)
        return config.CHECK_INTERVAL_SECONDS

    # --- Von aussen (Web-Thread): sofortige Pruefung anfragen -------------
    def request_check(self, timeout: float = 150.0) -> dict:
        resp: queue.Queue = queue.Queue(maxsize=1)
        self._req_q.put(resp)
        try:
            return resp.get(timeout=timeout)
        except queue.Empty:
            return {"status": "pending",
                    "note": "Pruefung wurde angestossen und laeuft noch."}

    # --- Schleife (Monitor-Thread) ---------------------------------------
    def _run(self):
        blocked_streak = 0
        # Direkt beim Start einmal pruefen
        res = self._safe_check()
        blocked_streak = blocked_streak + 1 if res["status"] == "blocked" else 0

        while not self._stop.is_set():
            deadline = time.monotonic() + self._next_wait(blocked_streak)

            # Bis zum Deadline auf manuelle Anfragen reagieren
            manual_rescheduled = False
            while not self._stop.is_set():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                try:
                    resp = self._req_q.get(timeout=remaining)
                except queue.Empty:
                    break
                # Manuelle Pruefung im richtigen (diesem) Thread ausfuehren
                r = self._safe_check()
                blocked_streak = blocked_streak + 1 if r["status"] == "blocked" else 0
                try:
                    resp.put_nowait(r)
                except Exception:
                    pass
                deadline = time.monotonic() + self._next_wait(blocked_streak)
                manual_rescheduled = True

            if self._stop.is_set():
                break
            if manual_rescheduled and time.monotonic() < deadline:
                # Nach manueller Pruefung wurde neu geplant -> weiter warten
                continue

            # Planmaessige Pruefung
            res = self._safe_check()
            blocked_streak = blocked_streak + 1 if res["status"] == "blocked" else 0

        self._scraper.close()

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
