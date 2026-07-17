"""Scraper fuer die Pokemon-Center-Kategorieseite.

Nutzt patchright (getarnter Chromium), um am Bot-Schutz (DataDome + Imperva
Incapsula) vorbeizukommen. Ein Browser wird einmal gestartet und fuer alle
Pruefungen wiederverwendet, damit die Sitzung "warm" bleibt.
"""
import json
import re

from patchright.sync_api import sync_playwright

import config

HOME = "https://www.pokemoncenter.com/de-de"

# Nur die eindeutigen Merkmale der ECHTEN Sperr-/Captcha-Seite.
# Wichtig: "datadome" NICHT als Merkmal nehmen - das Skript laedt DataDome auf
# jeder normalen Seite, das wuerde funktionierende Seiten faelschlich als
# blockiert melden.
_BLOCK_MARKERS = ("_incapsula_resource", "incident id",
                  "geo.captcha-delivery.com")

# Drop-Erkennung: Bei einem Drop schaltet Pokemon Center eine Warteschlange
# (Queue-it) und/oder ein Captcha (DataDome) vor die Seite. Diese Merkmale
# werden NUR geprueft, wenn keine Produkte gefunden wurden - auf einer
# normalen Produktseite koennen sie nicht falsch anschlagen.
_QUEUE_MARKERS = ("queue-it", "queueit", "waiting room", "warteschlange",
                  "waitingroom", "softblock")
_CAPTCHA_MARKERS = ("geo.captcha-delivery.com", "captcha-delivery")


def _detect_shield(html: str, page_url: str) -> str | None:
    """Warteschlangen- oder Captcha-Seite erkennen (nur bei 0 Produkten rufen).

    Rueckgabe: "queue" | "captcha" | None
    """
    hay = html.lower()
    url = (page_url or "").lower()
    if "queue-it.net" in url or any(m in hay for m in _QUEUE_MARKERS):
        return "queue"
    if any(m in hay for m in _CAPTCHA_MARKERS):
        return "captcha"
    return None


def _looks_blocked(html: str) -> bool:
    """Nur relevant, wenn KEINE Produkte gefunden wurden: echte Sperrseite?"""
    if len(html) < 3000:
        return True
    return any(m in html.lower() for m in _BLOCK_MARKERS)


def extract_products(html: str) -> list:
    """Produkte aus dem HTML lesen: primaer JSON-LD, Preis aus dem DOM."""
    products = {}
    for m in re.finditer(
        r'<script type="application/ld\+json">(.*?)</script>', html, re.S
    ):
        try:
            data = json.loads(m.group(1))
        except Exception:
            continue
        if not isinstance(data, dict) or data.get("@type") != "Product":
            continue
        offers = data.get("offers") or {}
        avail = (offers.get("availability") or "").rsplit("/", 1)[-1]
        url = data.get("url") or offers.get("url") or ""
        pid = data.get("mpn") or data.get("sku") or ""
        if not pid and url:
            mm = re.search(r"/product/([^/]+)/", url)
            pid = mm.group(1) if mm else url
        if not pid:
            continue
        products[pid] = {
            "id": pid,
            "name": (data.get("name") or "").strip(),
            "url": url,
            "available": avail == "InStock",
            "price": None,
        }

    # Sichtbaren EUR-Preis pro Produkt-Kachel ergaenzen (url -> Preis)
    price_map = {}
    for m in re.finditer(
        r'href="(/de-de/product/[^"]+)"[^>]*>.*?product-price--\w+">([^<]+)<',
        html, re.S,
    ):
        full = "https://www.pokemoncenter.com" + m.group(1)
        price_map.setdefault(full, m.group(2).strip())
    for p in products.values():
        if p["url"] in price_map:
            p["price"] = price_map[p["url"]]

    return list(products.values())


class Scraper:
    def __init__(self):
        self._pw = None
        self._ctx = None
        self._page = None
        self._warmed = False

    def _ensure_browser(self):
        if self._ctx is not None:
            return
        launch_args = ["--disable-blink-features=AutomationControlled"]
        if config.BROWSER_OFFSCREEN:
            # Fenster weit ausserhalb des sichtbaren Bereichs positionieren.
            launch_args += ["--window-position=-2400,-2400",
                            "--window-size=1366,900"]
        self._pw = sync_playwright().start()
        self._ctx = self._pw.chromium.launch_persistent_context(
            user_data_dir=str(config.PROFILE_DIR),
            headless=config.HEADLESS,
            channel="chromium",
            locale="de-DE",
            timezone_id="Europe/Berlin",
            viewport={"width": 1366, "height": 900},
            args=launch_args,
        )
        self._page = self._ctx.pages[0] if self._ctx.pages else self._ctx.new_page()
        self._warmed = False

    def _warmup(self):
        """Beim ersten Laden einer neuen Sitzung die Startseite besuchen,
        damit der Bot-Schutz die noetigen Cookies setzt."""
        if self._warmed:
            return
        try:
            self._page.goto(HOME, wait_until="domcontentloaded", timeout=60000)
            self._page.wait_for_timeout(5000)
            # etwas menschliche Aktivitaet
            self._page.mouse.move(400, 300)
            self._page.mouse.wheel(0, 1200)
            self._page.wait_for_timeout(2000)
        except Exception:
            pass
        self._warmed = True

    def close(self):
        try:
            if self._ctx:
                self._ctx.close()
        finally:
            if self._pw:
                self._pw.stop()
        self._pw = self._ctx = self._page = None

    def _load_once(self, url: str, wait_ms: int = 6000) -> str:
        self._page.goto(url, wait_until="domcontentloaded", timeout=60000)
        self._page.wait_for_timeout(wait_ms)
        return self._page.content()

    def fetch(self) -> dict:
        """Eine Pruefung durchfuehren.

        Rueckgabe: {"status": "ok"|"queue"|"blocked"|"error", "products": [...], "note": str}

        "queue" = Warteschlange/Captcha vorgeschaltet - starkes Drop-Signal.
        """
        try:
            self._ensure_browser()
        except Exception as e:  # Browser-Start fehlgeschlagen
            return {"status": "error", "products": [], "note": f"Browser-Start: {e}"}

        try:
            self._warmup()
            html = self._load_once(config.PC_URL)
            products = extract_products(html)

            # Noch keine Produkte? Erst pruefen, ob eine Warteschlange oder
            # ein Captcha vorgeschaltet ist (= Drop laeuft). In dem Fall NICHT
            # neu laden - das koennte eine echte Queue-Position verschlechtern.
            if not products:
                shield = _detect_shield(html, self._page.url)
                if shield == "queue":
                    return {"status": "queue", "products": [],
                            "note": "Warteschlange aktiv - vermutlich laeuft ein Drop!"}
                if shield == "captcha":
                    return {"status": "queue", "products": [],
                            "note": "Captcha-Seite (DataDome) aktiv - moeglicher Drop oder Bot-Verdacht."}

            # Einmal sanft nachladen (Seite evtl. noch am Rendern, oder
            # Imperva loest nach einem Reload auf). Kein Ladesturm.
            if not products:
                self._page.wait_for_timeout(4000)
                self._page.reload(wait_until="domcontentloaded", timeout=60000)
                self._page.wait_for_timeout(6000)
                html = self._page.content()
                products = extract_products(html)

            # Produkte da -> durch Scrollen evtl. weitere Kacheln laden, neu lesen
            if products:
                for _ in range(4):
                    self._page.mouse.wheel(0, 4000)
                    self._page.wait_for_timeout(800)
                products = extract_products(self._page.content())
                return {"status": "ok", "products": products, "note": ""}

            # Keine Produkte: Warteschlange/Captcha, echte Sperrseite oder
            # leere/geaenderte Seite?
            shield = _detect_shield(html, self._page.url)
            if shield == "queue":
                return {"status": "queue", "products": [],
                        "note": "Warteschlange aktiv - vermutlich laeuft ein Drop!"}
            if shield == "captcha":
                return {"status": "queue", "products": [],
                        "note": "Captcha-Seite (DataDome) aktiv - moeglicher Drop oder Bot-Verdacht."}
            if _looks_blocked(html):
                return {"status": "blocked", "products": [],
                        "note": "Bot-Schutz hat den Zugriff blockiert."}
            return {"status": "ok", "products": [],
                    "note": "0 Artikel gefunden (Kategorie leer oder Seite geaendert)."}

        except Exception as e:
            # Browser evtl. abgestuerzt -> beim naechsten Mal neu starten
            try:
                self.close()
            except Exception:
                pass
            return {"status": "error", "products": [], "note": str(e)[:300]}


if __name__ == "__main__":
    # Manueller Einzeltest: python scraper.py
    s = Scraper()
    res = s.fetch()
    print("Status:", res["status"], "| Note:", res["note"])
    for p in res["products"]:
        print(("  [VERFUEGBAR] " if p["available"] else "  [ausverkauft] ")
              + f"{p['price'] or '-':>9}  {p['name']}")
    s.close()
