"""API REST consumata dalla webapp."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, HTTPException
from starlette.concurrency import run_in_threadpool

from . import store
from .config import settings
from .notifier import TelegramError, send_message
from .pipeline import run_all, run_search
from .providers import provider_catalog
from .providers.base import Criteria
from .scheduler import next_run, trigger_now
from .scoring import DEFAULT_WEIGHTS, WEIGHT_KEYS, WEIGHT_LABELS, clean_weights, evaluate_all

router = APIRouter(prefix="/api")


@router.get("/meta")
def meta() -> dict[str, Any]:
    """Tutto cio' che serve alla webapp per costruire il form."""
    return {
        "providers": provider_catalog(),
        "weight_keys": WEIGHT_KEYS,
        "weight_labels": WEIGHT_LABELS,
        "default_weights": DEFAULT_WEIGHTS,
        "interval_minutes": settings.interval_minutes,
        "telegram_configured": settings.telegram_enabled,
        "next_run": next_run(),
        "criteria_fields": list(Criteria().to_dict().keys()),
    }


@router.get("/searches")
def get_searches() -> list[dict[str, Any]]:
    return store.list_searches()


@router.post("/searches", status_code=201)
def post_search(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    if not (payload.get("name") or "").strip():
        raise HTTPException(422, "Il nome della ricerca è obbligatorio")
    return store.create_search(payload)


@router.get("/searches/{search_id}")
def get_one_search(search_id: int) -> dict[str, Any]:
    search = store.get_search(search_id)
    if not search:
        raise HTTPException(404, "Ricerca non trovata")
    return search


@router.put("/searches/{search_id}")
def put_search(search_id: int, payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    updated = store.update_search(search_id, payload)
    if not updated:
        raise HTTPException(404, "Ricerca non trovata")
    return updated


@router.delete("/searches/{search_id}", status_code=204)
def remove_search(search_id: int) -> None:
    if not store.delete_search(search_id):
        raise HTTPException(404, "Ricerca non trovata")


@router.get("/searches/{search_id}/listings")
def get_listings(search_id: int, only_active: bool = True, limit: int = 300) -> list[dict[str, Any]]:
    if not store.get_search(search_id):
        raise HTTPException(404, "Ricerca non trovata")
    return store.listings_for_search(search_id, only_active=only_active, limit=limit)


@router.post("/searches/{search_id}/run")
async def run_one(search_id: int, notify: bool = True) -> dict[str, Any]:
    if not store.get_search(search_id):
        raise HTTPException(404, "Ricerca non trovata")
    return await run_in_threadpool(run_search, search_id, notify=notify)


@router.post("/searches/{search_id}/simulate")
def simulate(search_id: int, payload: dict[str, Any] = Body(default={})) -> list[dict[str, Any]]:
    """Ricalcola i punteggi con pesi diversi senza salvare nulla.

    Serve al cursore dei pesi nella webapp: si vede subito come cambia la classifica.
    """
    search = store.get_search(search_id)
    if not search:
        raise HTTPException(404, "Ricerca non trovata")
    weights = clean_weights(payload.get("weights") or search["weights"])
    criteria = Criteria.from_dict(payload.get("criteria") or search["criteria"])

    rows = store.listings_for_search(search_id, only_active=True)
    listings = [store.row_to_listing(row) for row in rows]
    results = evaluate_all(listings, criteria=criteria, weights=weights, pool=listings)

    out = []
    for row, (_, evaluation) in zip(rows, results):
        merged = dict(row)
        merged.update(evaluation.as_row())
        out.append(merged)
    out.sort(key=lambda item: item.get("score") or 0, reverse=True)
    return out


@router.post("/run-all")
async def run_everything(notify: bool = True) -> list[dict[str, Any]]:
    return await run_in_threadpool(run_all, notify=notify)


@router.post("/scheduler/trigger")
def scheduler_trigger() -> dict[str, Any]:
    trigger_now()
    return {"ok": True, "next_run": next_run()}


@router.get("/runs")
def get_runs(limit: int = 30, search_id: int | None = None) -> list[dict[str, Any]]:
    return store.recent_runs(limit=limit, search_id=search_id)


@router.post("/telegram/test")
def telegram_test(payload: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    try:
        send_message(
            "🚗 <b>Carhunt</b> è collegato correttamente.\nDa qui in poi ricevi qui gli annunci nuovi.",
            (payload.get("chat_id") or "").strip() or None,
        )
    except TelegramError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"ok": True}
