"""Scraper fuer die Pokemon-Center-Kategorieseite.

Nutzt patchright (getarnter Chromium), um am Bot-Schutz (DataDome + Imperva
Incapsula) vorbeizukommen. Ein Browser wird einmal gestartet und fuer alle
Pruefungen wiederverwendet, damit die Sitzung "warm" bleibt.
"""
import json
import re
from datetime import datetime

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
_QUEUE_MARKERS = (
    "queue-it", "queueit", "queue.pokemoncenter", "waiting room", "waitingroom",
    "warteschlange", "warteraum", "wartebereich", "softblock",
    "you are now in line", "you are in line", "your turn", "estimated wait",
    "geschaetzte wartezeit", "voraussichtliche wartezeit", "bitte warten",
    "queuepassingdetail", "queue_number", "high traffic", "hoher andrang",
    "vielen dank fuer deine geduld",
)
# Domains/Skripte der Warteschlangen-Anbieter (im HTML oder in der URL)
_QUEUE_HOSTS = ("queue-it.net", "queue.pokemoncenter.com", "waitingroom")

# Achtung: KEINE generischen Vendor-Namen wie "recaptcha" aufnehmen - das
# laedt die normale Seite in ihrem JS-Bundle mit, das gaebe Fehlalarme.
_CAPTCHA_MARKERS = (
    "geo.captcha-delivery.com", "captcha-delivery", "captcha_delivery",
    "hcaptcha.com", "px-captcha", "human verification",
    "verify you are a human", "verify you are human",
    "bestaetige, dass du ein mensch bist", "sicherheitsabfrage",
    "please enable js and disable any ad blocker",
)


def _detect_shield(html: str, page_url: str, http_status: int | None = None) -> str | None:
    """Warteschlangen- oder Captcha-Seite erkennen (nur bei 0 Produkten rufen).

    Rueckgabe: "queue" | "captcha" | None
    """
    hay = html.lower()
    url = (page_url or "").lower()
    if any(h in url for h in _QUEUE_HOSTS) or any(h in hay for h in _QUEUE_HOSTS):
        return "queue"
    if any(m in hay for m in _QUEUE_MARKERS):
        return "queue"
    if any(m in hay for m in _CAPTCHA_MARKERS):
        return "captcha"
    # 429/503 = "zu viele Anfragen" / "Dienst ueberlastet". Auf einer Seite,
    # die sonst 200 liefert, ist das das typische Drop-Ueberlastungssignal.
    if http_status in (429, 503):
        return "queue"
    return None


def _page_title(html: str) -> str:
    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.S | re.I)
    return re.sub(r"\s+", " ", m.group(1)).strip()[:120] if m else ""


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
        self._http_status = None  # HTTP-Code der zuletzt geladenen Seite

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
        resp = self._page.goto(url, wait_until="domcontentloaded", timeout=60000)
        self._http_status = resp.status if resp else None
        self._page.wait_for_timeout(wait_ms)
        return self._page.content()

    # --- Diagnose ---------------------------------------------------------
    def _dump(self, html: str, status: str):
        """HTML + Screenshot der Seite wegschreiben, wenn eine Pruefung nicht
        geklappt hat. Ohne das raten wir beim naechsten Drop wieder, wie die
        Warteschlangen-Seite ueberhaupt aussieht."""
        if not config.SAVE_DIAGNOSTICS:
            return
        try:
            config.DIAG_DIR.mkdir(exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            base = config.DIAG_DIR / f"{stamp}_{status}"
            base.with_suffix(".html").write_text(html, encoding="utf-8",
                                                 errors="replace")
            try:
                self._page.screenshot(path=str(base.with_suffix(".png")),
                                      full_page=False, timeout=15000)
            except Exception:
                pass
            # Nur die neuesten Dumps behalten
            files = sorted(config.DIAG_DIR.glob("*_*.*"))
            for old in files[:-(config.DIAG_KEEP * 2)]:
                try:
                    old.unlink()
                except Exception:
                    pass
        except Exception:
            pass  # Diagnose darf die Ueberwachung nie stoppen

    def _fail(self, status: str, note: str, html: str) -> dict:
        """Fehlschlag protokollieren (inkl. HTTP-Code + Titel) und dumpen."""
        extra = []
        if self._http_status and self._http_status != 200:
            extra.append(f"HTTP {self._http_status}")
        title = _page_title(html)
        if title:
            extra.append(f'"{title}"')
        if extra:
            note = f"{note} ({', '.join(extra)})"
        self._dump(html, status)
        return {"status": status, "products": [], "note": note,
                "http_status": self._http_status}

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
                shield = _detect_shield(html, self._page.url, self._http_status)
                if shield:
                    return self._shield_result(shield, html)

            # Einmal sanft nachladen (Seite evtl. noch am Rendern, oder
            # Imperva loest nach einem Reload auf). Kein Ladesturm.
            if not products:
                self._page.wait_for_timeout(4000)
                resp = self._page.reload(wait_until="domcontentloaded", timeout=60000)
                self._http_status = resp.status if resp else self._http_status
                self._page.wait_for_timeout(6000)
                html = self._page.content()
                products = extract_products(html)

            # Produkte da -> durch Scrollen evtl. weitere Kacheln laden, neu lesen
            if products:
                for _ in range(4):
                    self._page.mouse.wheel(0, 4000)
                    self._page.wait_for_timeout(800)
                products = extract_products(self._page.content())
                return {"status": "ok", "products": products, "note": "",
                        "http_status": self._http_status}

            # Keine Produkte: Warteschlange/Captcha, echte Sperrseite oder
            # leere/geaenderte Seite?
            shield = _detect_shield(html, self._page.url, self._http_status)
            if shield:
                return self._shield_result(shield, html)
            if _looks_blocked(html):
                return self._fail("blocked", "Bot-Schutz hat den Zugriff blockiert.",
                                  html)
            return self._fail("empty",
                              "0 Artikel gefunden (Kategorie leer oder Seite geaendert).",
                              html)

        except Exception as e:
            # Browser evtl. abgestuerzt -> beim naechsten Mal neu starten
            try:
                self.close()
            except Exception:
                pass
            return {"status": "error", "products": [], "note": str(e)[:300],
                    "http_status": None}

    def _shield_result(self, shield: str, html: str) -> dict:
        if shield == "queue":
            return self._fail("queue", "Warteschlange aktiv - vermutlich laeuft ein Drop!",
                              html)
        return self._fail("queue",
                          "Captcha-Seite aktiv - moeglicher Drop oder Bot-Verdacht.",
                          html)


if __name__ == "__main__":
    # Manueller Einzeltest: python scraper.py
    s = Scraper()
    res = s.fetch()
    print("Status:", res["status"], "| Note:", res["note"])
    for p in res["products"]:
        print(("  [VERFUEGBAR] " if p["available"] else "  [ausverkauft] ")
              + f"{p['price'] or '-':>9}  {p['name']}")
    s.close()
