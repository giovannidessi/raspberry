"""Il giro completo di una ricerca: scarica -> filtra -> valuta -> notifica."""

from __future__ import annotations

import logging
from typing import Any

from . import store
from .config import settings
from .notifier import format_listing, format_summary, safe_send
from .providers import get_providers
from .providers.base import Criteria, Listing, normalize
from .scoring import Evaluation, evaluate_all

log = logging.getLogger(__name__)

MAX_NOTIFICATIONS_PER_RUN = 8


def passes_hard_filters(listing: Listing, criteria: Criteria) -> bool:
    """Scarta cio' che non ha senso mostrare: parole vietate o requisiti obbligatori mancanti."""
    hay = listing.haystack
    for word in criteria.exclude or []:
        if word.strip() and normalize(word) in hay:
            return False
    for word in criteria.must_have or []:
        if word.strip() and normalize(word) not in hay:
            return False
    if criteria.price_max and listing.price and listing.price > criteria.price_max * 1.15:
        return False  # tolleranza del 15%: a volte il prezzo in lista e' quello "da"
    if criteria.price_min and listing.price and listing.price < criteria.price_min * 0.85:
        return False
    if criteria.year_min and listing.year and listing.year < criteria.year_min:
        return False
    if criteria.year_max and listing.year and listing.year > criteria.year_max:
        return False
    if criteria.km_max and listing.mileage is not None and listing.mileage > criteria.km_max * 1.1:
        return False
    if criteria.fuels and listing.fuel:
        wanted = {normalize(f) for f in criteria.fuels}
        if not any(w in normalize(listing.fuel) or normalize(listing.fuel) in w for w in wanted):
            return False
    if criteria.seller and listing.seller and normalize(criteria.seller) != normalize(listing.seller):
        return False
    return True


def deduplicate(listings: list[Listing]) -> list[Listing]:
    """Lo stesso annuncio compare spesso su piu' portali: teniamo la prima occorrenza."""
    seen: set[tuple] = set()
    unique: list[Listing] = []
    for listing in listings:
        fingerprint = (
            normalize(listing.title)[:60],
            int(listing.price) if listing.price else None,
            listing.mileage,
            listing.year,
        )
        key = (listing.provider, listing.external_id)
        if key in seen or (fingerprint[0] and fingerprint in seen):
            continue
        seen.add(key)
        seen.add(fingerprint)
        unique.append(listing)
    return unique


def fetch(criteria: Criteria, limit_per_provider: int) -> tuple[list[Listing], list[str]]:
    """Interroga i portali scelti. Un portale rotto non deve bloccare gli altri."""
    collected: list[Listing] = []
    errors: list[str] = []
    for provider in get_providers(criteria.providers):
        try:
            found = provider.search(criteria, limit=limit_per_provider)
            log.info("%s: %s annunci", provider.key, len(found))
            collected.extend(found)
        except Exception as exc:  # noqa: BLE001
            log.exception("provider %s fallito", provider.key)
            errors.append(f"{provider.label}: {type(exc).__name__} {exc}"[:200])
    return collected, errors


def run_search(search_id: int, *, notify: bool = True, limit_per_provider: int | None = None) -> dict[str, Any]:
    search = store.get_search(search_id)
    if not search:
        raise ValueError(f"ricerca {search_id} inesistente")

    limit_per_provider = limit_per_provider or settings.max_results_per_provider
    criteria = Criteria.from_dict(search["criteria"])
    weights = search["weights"]
    run_id = store.start_run(search_id)

    raw, errors = fetch(criteria, limit_per_provider)
    candidates = deduplicate([l for l in raw if passes_hard_filters(l, criteria)])

    statuses: dict[int, str] = {}
    old_prices: dict[int, float | None] = {}
    seen_ids: list[int] = []
    for listing in candidates:
        status, row = store.upsert_listing(search_id, listing)
        statuses[row["id"]] = status
        old_prices[row["id"]] = row.get("previous_price")
        seen_ids.append(row["id"])

    store.deactivate_missing(search_id, seen_ids)

    # il confronto di mercato usa tutti gli annunci attivi della ricerca, non solo quelli nuovi
    active_rows = store.listings_for_search(search_id, only_active=True)
    pool = [store.row_to_listing(row) for row in active_rows]
    evaluations = evaluate_all(pool, criteria=criteria, weights=weights, pool=pool)

    by_id: dict[int, tuple[Listing, Evaluation]] = {}
    for row, (listing, evaluation) in zip(active_rows, evaluations):
        store.save_evaluation(row["id"], evaluation.as_row())
        by_id[row["id"]] = (listing, evaluation)

    new_items = sum(1 for s in statuses.values() if s == "nuovo")
    price_drops = sum(1 for s in statuses.values() if s == "ribasso")
    notified = 0

    if notify:
        notified = _notify(search, statuses, old_prices, by_id)

    message = "; ".join(errors) if errors else "ok"
    status = "errore" if errors and not candidates else ("parziale" if errors else "ok")
    store.finish_run(
        run_id,
        status=status,
        found=len(candidates),
        new_items=new_items,
        price_drops=price_drops,
        notified=notified,
        message=message,
    )
    store.set_run_status(search_id, status, message)

    return {
        "search_id": search_id,
        "status": status,
        "found": len(candidates),
        "new": new_items,
        "price_drops": price_drops,
        "notified": notified,
        "errors": errors,
        "active": len(active_rows),
    }


def _notify(search: dict[str, Any], statuses: dict[int, str], old_prices: dict[int, float | None],
            by_id: dict[int, tuple[Listing, Evaluation]]) -> int:
    chat_id = search.get("telegram_chat_id")
    min_score = float(search.get("min_score") or 0)

    if not search.get("bootstrapped"):
        # primo giro: un riepilogo invece di decine di notifiche
        top = sorted(by_id.values(), key=lambda pair: pair[1].score, reverse=True)[:3]
        safe_send(format_summary(search["name"], len(by_id), top), chat_id)
        for listing_id in by_id:
            store.mark_notified(listing_id)
        store.mark_bootstrapped(search["id"])
        return 1

    candidates: list[tuple[float, int, str]] = []
    for listing_id, status in statuses.items():
        if status == "invariato" or listing_id not in by_id:
            continue
        evaluation = by_id[listing_id][1]
        threshold = min_score if status == "nuovo" else max(0.0, min_score - 10)
        if evaluation.score >= threshold:
            candidates.append((evaluation.score, listing_id, status))

    sent = 0
    for _, listing_id, status in sorted(candidates, reverse=True)[:MAX_NOTIFICATIONS_PER_RUN]:
        listing, evaluation = by_id[listing_id]
        text = format_listing(
            listing,
            evaluation,
            search_name=search["name"],
            reason="nuovo" if status == "nuovo" else "ribasso",
            old_price=old_prices.get(listing_id),
        )
        if safe_send(text, chat_id):
            store.mark_notified(listing_id)
            sent += 1

    extra = len(candidates) - MAX_NOTIFICATIONS_PER_RUN
    if extra > 0:
        safe_send(f"… e altri <b>{extra}</b> annunci sopra soglia per <i>{search['name']}</i>. Aprili dalla webapp.", chat_id)
    return sent


def run_all(*, notify: bool = True) -> list[dict[str, Any]]:
    results = []
    for search in store.list_searches():
        if not search["enabled"]:
            continue
        try:
            results.append(run_search(search["id"], notify=notify))
        except Exception as exc:  # noqa: BLE001
            log.exception("giro fallito per la ricerca %s", search["id"])
            store.set_run_status(search["id"], "errore", str(exc))
            results.append({"search_id": search["id"], "status": "errore", "errors": [str(exc)]})
    return results
