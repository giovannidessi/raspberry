"""Query SQL usate da API e pipeline."""

from __future__ import annotations

import sqlite3
from typing import Any

from .db import dumps, loads, now, session
from .providers.base import Criteria, Listing
from .scoring import DEFAULT_WEIGHTS, clean_weights

LISTING_COLUMNS = (
    "url", "title", "make", "model", "version", "price", "mileage", "year",
    "fuel", "gearbox", "power_hp", "seller", "location", "province", "lat", "lon",
    "image", "description",
)


# ------------------------------------------------------------------- ricerche

def _search_row(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    data["criteria"] = loads(data.get("criteria"), {})
    data["weights"] = clean_weights(loads(data.get("weights"), DEFAULT_WEIGHTS))
    data["enabled"] = bool(data.get("enabled"))
    data["bootstrapped"] = bool(data.get("bootstrapped"))
    return data


def list_searches() -> list[dict[str, Any]]:
    with session() as conn:
        rows = conn.execute("SELECT * FROM searches ORDER BY id").fetchall()
    return [_search_row(row) for row in rows]


def get_search(search_id: int) -> dict[str, Any] | None:
    with session() as conn:
        row = conn.execute("SELECT * FROM searches WHERE id = ?", (search_id,)).fetchone()
    return _search_row(row) if row else None


def create_search(payload: dict[str, Any]) -> dict[str, Any]:
    timestamp = now()
    with session() as conn:
        cursor = conn.execute(
            """
            INSERT INTO searches (name, enabled, criteria, weights, min_score, telegram_chat_id,
                                  created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload.get("name") or "Ricerca senza nome",
                1 if payload.get("enabled", True) else 0,
                dumps(Criteria.from_dict(payload.get("criteria")).to_dict()),
                dumps(clean_weights(payload.get("weights"))),
                float(payload.get("min_score", 60) or 0),
                (payload.get("telegram_chat_id") or "").strip() or None,
                timestamp,
                timestamp,
            ),
        )
        search_id = int(cursor.lastrowid)
    return get_search(search_id)  # type: ignore[return-value]


def update_search(search_id: int, payload: dict[str, Any]) -> dict[str, Any] | None:
    current = get_search(search_id)
    if not current:
        return None
    criteria = payload.get("criteria", current["criteria"])
    weights = payload.get("weights", current["weights"])
    with session() as conn:
        conn.execute(
            """
            UPDATE searches
               SET name = ?, enabled = ?, criteria = ?, weights = ?, min_score = ?,
                   telegram_chat_id = ?, updated_at = ?
             WHERE id = ?
            """,
            (
                payload.get("name", current["name"]),
                1 if payload.get("enabled", current["enabled"]) else 0,
                dumps(Criteria.from_dict(criteria).to_dict()),
                dumps(clean_weights(weights)),
                float(payload.get("min_score", current["min_score"]) or 0),
                ((payload["telegram_chat_id"].strip() or None)
                 if isinstance(payload.get("telegram_chat_id"), str)
                 else current.get("telegram_chat_id")),
                now(),
                search_id,
            ),
        )
    return get_search(search_id)


def delete_search(search_id: int) -> bool:
    with session() as conn:
        cursor = conn.execute("DELETE FROM searches WHERE id = ?", (search_id,))
        return cursor.rowcount > 0


def mark_bootstrapped(search_id: int) -> None:
    with session() as conn:
        conn.execute("UPDATE searches SET bootstrapped = 1 WHERE id = ?", (search_id,))


def set_run_status(search_id: int, status: str, message: str) -> None:
    with session() as conn:
        conn.execute(
            "UPDATE searches SET last_run_at = ?, last_run_status = ?, last_run_message = ? WHERE id = ?",
            (now(), status, message[:500], search_id),
        )


# -------------------------------------------------------------------- annunci

def row_to_listing(row: sqlite3.Row | dict[str, Any]) -> Listing:
    data = dict(row)
    return Listing(
        provider=data.get("provider") or "",
        external_id=data.get("external_id") or "",
        url=data.get("url") or "",
        title=data.get("title") or "",
        price=data.get("price"),
        mileage=data.get("mileage"),
        year=data.get("year"),
        make=data.get("make") or "",
        model=data.get("model") or "",
        version=data.get("version") or "",
        fuel=data.get("fuel") or "",
        gearbox=data.get("gearbox") or "",
        power_hp=data.get("power_hp"),
        seller=data.get("seller") or "",
        location=data.get("location") or "",
        province=data.get("province") or "",
        lat=data.get("lat"),
        lon=data.get("lon"),
        image=data.get("image") or "",
        description=data.get("description") or "",
    )


def upsert_listing(search_id: int, listing: Listing) -> tuple[str, dict[str, Any]]:
    """Inserisce o aggiorna un annuncio.

    Ritorna ("nuovo" | "ribasso" | "invariato", riga) cosi' la pipeline sa cosa notificare.
    """
    timestamp = now()
    values = listing.to_dict()
    with session() as conn:
        existing = conn.execute(
            "SELECT * FROM listings WHERE search_id = ? AND provider = ? AND external_id = ?",
            (search_id, listing.provider, listing.external_id),
        ).fetchone()

        if existing is None:
            columns = ["search_id", "provider", "external_id", *LISTING_COLUMNS,
                       "first_price", "first_seen_at", "last_seen_at"]
            params = [search_id, listing.provider, listing.external_id]
            params += [values.get(col) for col in LISTING_COLUMNS]
            params += [listing.price, timestamp, timestamp]
            placeholders = ",".join("?" * len(columns))
            cursor = conn.execute(
                f"INSERT INTO listings ({','.join(columns)}) VALUES ({placeholders})", params
            )
            row = conn.execute("SELECT * FROM listings WHERE id = ?", (cursor.lastrowid,)).fetchone()
            return "nuovo", dict(row)

        old_price = existing["price"]
        assignments = ", ".join(f"{col} = ?" for col in LISTING_COLUMNS)
        params = [values.get(col) for col in LISTING_COLUMNS]
        params += [old_price, timestamp, existing["id"]]
        conn.execute(
            f"UPDATE listings SET {assignments}, previous_price = ?, last_seen_at = ?, is_active = 1 WHERE id = ?",
            params,
        )
        row = conn.execute("SELECT * FROM listings WHERE id = ?", (existing["id"],)).fetchone()

    status = "invariato"
    if old_price and listing.price and listing.price < old_price * 0.97:
        status = "ribasso"
    return status, dict(row)


def save_evaluation(listing_id: int, evaluation: dict[str, Any]) -> None:
    with session() as conn:
        conn.execute(
            """
            UPDATE listings
               SET score = ?, deal_delta = ?, estimated_price = ?, verdict = ?, comment = ?,
                   breakdown = ?, flags = ?
             WHERE id = ?
            """,
            (
                evaluation["score"],
                evaluation["deal_delta"],
                evaluation["estimated_price"],
                evaluation["verdict"],
                evaluation["comment"],
                dumps(evaluation["breakdown"]),
                dumps(evaluation["flags"]),
                listing_id,
            ),
        )


def mark_notified(listing_id: int) -> None:
    with session() as conn:
        conn.execute("UPDATE listings SET notified_at = ? WHERE id = ?", (now(), listing_id))


def deactivate_missing(search_id: int, seen_ids: list[int]) -> int:
    """Gli annunci non piu' presenti nei risultati vengono archiviati, non cancellati."""
    with session() as conn:
        if seen_ids:
            placeholders = ",".join("?" * len(seen_ids))
            cursor = conn.execute(
                f"UPDATE listings SET is_active = 0 WHERE search_id = ? AND is_active = 1 AND id NOT IN ({placeholders})",
                [search_id, *seen_ids],
            )
        else:
            cursor = conn.execute(
                "UPDATE listings SET is_active = 0 WHERE search_id = ? AND is_active = 1", (search_id,)
            )
        return cursor.rowcount


def listings_for_search(search_id: int, *, only_active: bool = True, limit: int = 500) -> list[dict[str, Any]]:
    query = "SELECT * FROM listings WHERE search_id = ?"
    params: list[Any] = [search_id]
    if only_active:
        query += " AND is_active = 1"
    query += " ORDER BY score DESC NULLS LAST, first_seen_at DESC LIMIT ?"
    params.append(limit)
    with session() as conn:
        rows = conn.execute(query, params).fetchall()
    out = []
    for row in rows:
        data = dict(row)
        data["breakdown"] = loads(data.get("breakdown"), {})
        data["flags"] = loads(data.get("flags"), [])
        data["is_active"] = bool(data.get("is_active"))
        out.append(data)
    return out


# ----------------------------------------------------------------------- run

def start_run(search_id: int) -> int:
    with session() as conn:
        cursor = conn.execute(
            "INSERT INTO runs (search_id, started_at, status) VALUES (?, ?, 'in corso')",
            (search_id, now()),
        )
        return int(cursor.lastrowid)


def finish_run(run_id: int, *, status: str, found: int, new_items: int, price_drops: int,
               notified: int, message: str) -> None:
    with session() as conn:
        conn.execute(
            """
            UPDATE runs SET finished_at = ?, status = ?, found = ?, new_items = ?,
                            price_drops = ?, notified = ?, message = ?
             WHERE id = ?
            """,
            (now(), status, found, new_items, price_drops, notified, message[:500], run_id),
        )


def recent_runs(limit: int = 30, search_id: int | None = None) -> list[dict[str, Any]]:
    query = "SELECT r.*, s.name AS search_name FROM runs r LEFT JOIN searches s ON s.id = r.search_id"
    params: list[Any] = []
    if search_id is not None:
        query += " WHERE r.search_id = ?"
        params.append(search_id)
    query += " ORDER BY r.started_at DESC LIMIT ?"
    params.append(limit)
    with session() as conn:
        rows = conn.execute(query, params).fetchall()
    return [dict(row) for row in rows]
