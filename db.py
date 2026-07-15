"""SQLite-Speicher: aktueller Produkt-Snapshot, Ereignisse und Pruef-Historie."""
import sqlite3
import threading
from datetime import datetime, timezone

from config import DB_PATH

_lock = threading.Lock()


def _conn():
    c = sqlite3.connect(DB_PATH, timeout=30)
    c.row_factory = sqlite3.Row
    return c


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def init():
    with _lock, _conn() as c:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS products (
                id          TEXT PRIMARY KEY,
                name        TEXT,
                url         TEXT,
                price       TEXT,
                available   INTEGER,
                first_seen  TEXT,
                last_seen   TEXT
            );
            CREATE TABLE IF NOT EXISTS events (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                ts          TEXT,
                type        TEXT,      -- 'new' | 'restock'
                product_id  TEXT,
                name        TEXT,
                url         TEXT,
                price       TEXT
            );
            CREATE TABLE IF NOT EXISTS checks (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                ts            TEXT,
                status        TEXT,    -- 'ok' | 'blocked' | 'error'
                num_products  INTEGER,
                num_available INTEGER,
                note          TEXT
            );
            """
        )


def get_known_products() -> dict:
    with _lock, _conn() as c:
        rows = c.execute("SELECT * FROM products").fetchall()
    return {r["id"]: dict(r) for r in rows}


def upsert_products(products: list, seen_ts: str):
    """Snapshot der aktuell sichtbaren Produkte speichern/aktualisieren."""
    with _lock, _conn() as c:
        for p in products:
            existing = c.execute(
                "SELECT first_seen FROM products WHERE id=?", (p["id"],)
            ).fetchone()
            first_seen = existing["first_seen"] if existing else seen_ts
            c.execute(
                """INSERT INTO products (id, name, url, price, available, first_seen, last_seen)
                   VALUES (?,?,?,?,?,?,?)
                   ON CONFLICT(id) DO UPDATE SET
                       name=excluded.name, url=excluded.url, price=excluded.price,
                       available=excluded.available, last_seen=excluded.last_seen""",
                (p["id"], p["name"], p["url"], p["price"],
                 1 if p["available"] else 0, first_seen, seen_ts),
            )


def add_event(ev_type: str, p: dict, ts: str):
    with _lock, _conn() as c:
        c.execute(
            "INSERT INTO events (ts, type, product_id, name, url, price) VALUES (?,?,?,?,?,?)",
            (ts, ev_type, p["id"], p["name"], p["url"], p.get("price")),
        )


def add_check(status: str, num_products: int, num_available: int, note: str = ""):
    with _lock, _conn() as c:
        c.execute(
            "INSERT INTO checks (ts, status, num_products, num_available, note) VALUES (?,?,?,?,?)",
            (now_iso(), status, num_products, num_available, note),
        )


def recent_events(limit: int = 50) -> list:
    with _lock, _conn() as c:
        rows = c.execute(
            "SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


def recent_checks(limit: int = 30) -> list:
    with _lock, _conn() as c:
        rows = c.execute(
            "SELECT * FROM checks ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


def current_products() -> list:
    with _lock, _conn() as c:
        rows = c.execute(
            "SELECT * FROM products ORDER BY available DESC, name ASC"
        ).fetchall()
    return [dict(r) for r in rows]


def last_check() -> dict | None:
    with _lock, _conn() as c:
        row = c.execute("SELECT * FROM checks ORDER BY id DESC LIMIT 1").fetchone()
    return dict(row) if row else None


def has_baseline() -> bool:
    """Wurde schon mindestens einmal erfolgreich geprueft?"""
    with _lock, _conn() as c:
        row = c.execute("SELECT COUNT(*) AS n FROM checks WHERE status='ok'").fetchone()
    return row["n"] > 0
