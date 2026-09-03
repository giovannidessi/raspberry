"""Strato dati: SQLite senza ORM, leggero abbastanza per un Raspberry Pi."""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator

from .config import settings

_lock = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS searches (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    name              TEXT    NOT NULL,
    enabled           INTEGER NOT NULL DEFAULT 1,
    criteria          TEXT    NOT NULL,
    weights           TEXT    NOT NULL,
    min_score         REAL    NOT NULL DEFAULT 60,
    telegram_chat_id  TEXT,
    bootstrapped      INTEGER NOT NULL DEFAULT 0,
    created_at        TEXT    NOT NULL,
    updated_at        TEXT    NOT NULL,
    last_run_at       TEXT,
    last_run_status   TEXT,
    last_run_message  TEXT
);

CREATE TABLE IF NOT EXISTS listings (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    search_id        INTEGER NOT NULL REFERENCES searches(id) ON DELETE CASCADE,
    provider         TEXT    NOT NULL,
    external_id      TEXT    NOT NULL,
    url              TEXT,
    title            TEXT,
    make             TEXT,
    model            TEXT,
    version          TEXT,
    price            REAL,
    first_price      REAL,
    previous_price   REAL,
    mileage          INTEGER,
    year             INTEGER,
    fuel             TEXT,
    gearbox          TEXT,
    power_hp         INTEGER,
    seller           TEXT,
    location         TEXT,
    province         TEXT,
    lat              REAL,
    lon              REAL,
    image            TEXT,
    description      TEXT,
    score            REAL,
    deal_delta       REAL,
    estimated_price  REAL,
    verdict          TEXT,
    comment          TEXT,
    breakdown        TEXT,
    flags            TEXT,
    is_active        INTEGER NOT NULL DEFAULT 1,
    first_seen_at    TEXT    NOT NULL,
    last_seen_at     TEXT    NOT NULL,
    notified_at      TEXT,
    UNIQUE (search_id, provider, external_id)
);

CREATE INDEX IF NOT EXISTS idx_listings_search ON listings (search_id, is_active, score DESC);

CREATE TABLE IF NOT EXISTS runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    search_id   INTEGER REFERENCES searches(id) ON DELETE CASCADE,
    started_at  TEXT NOT NULL,
    finished_at TEXT,
    status      TEXT,
    found       INTEGER DEFAULT 0,
    new_items   INTEGER DEFAULT 0,
    price_drops INTEGER DEFAULT 0,
    notified    INTEGER DEFAULT 0,
    message     TEXT
);

CREATE INDEX IF NOT EXISTS idx_runs_search ON runs (search_id, started_at DESC);
"""


def now() -> str:
    """Timestamp ISO 8601 in UTC, usato per tutte le colonne temporali."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect() -> sqlite3.Connection:
    path = settings.db_path
    parent = os.path.dirname(os.path.abspath(path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def session() -> Iterator[sqlite3.Connection]:
    """Una connessione per operazione: SQLite su Pi regge senza pool."""
    conn = connect()
    try:
        with _lock:
            yield conn
            conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with session() as conn:
        conn.executescript(SCHEMA)


def loads(value: Any, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None
