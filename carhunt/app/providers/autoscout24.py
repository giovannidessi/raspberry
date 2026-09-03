"""AutoScout24.it - legge il blob JSON `__NEXT_DATA__` incorporato nella pagina risultati."""

from __future__ import annotations

import json
import re
from typing import Any

from .base import Criteria, Listing, Provider, dig, normalize, to_float, to_int, year_from
from .http import get

BASE_URL = "https://www.autoscout24.it/lst"
NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json"[^>]*>(.*?)</script>', re.DOTALL
)

FUEL_QUERY = {"benzina": "B", "diesel": "D", "gpl": "L", "metano": "C", "elettrica": "E", "ibrida": "2"}
GEARBOX_QUERY = {"manuale": "M", "automatico": "A"}


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", normalize(value)).strip("-")
    return slug


def build_url(criteria: Criteria) -> str:
    parts = [BASE_URL]
    if criteria.make:
        parts.append(_slug(criteria.make))
        if criteria.model:
            parts.append(_slug(criteria.model))
    return "/".join(parts)


def build_params(criteria: Criteria, page: int = 1, size: int = 20) -> dict[str, Any]:
    params: dict[str, Any] = {
        "atype": "C",
        "cy": "I",
        "damaged_listing": "exclude",
        "desc": "1",
        "sort": "age",
        "powertype": "hp",
        "size": size,
        "page": page,
        "ustate": "N,U",
    }
    if not criteria.make and criteria.query_text:
        params["q"] = criteria.query_text
    if criteria.price_min is not None:
        params["pricefrom"] = int(criteria.price_min)
    if criteria.price_max is not None:
        params["priceto"] = int(criteria.price_max)
    if criteria.year_min:
        params["fregfrom"] = int(criteria.year_min)
    if criteria.year_max:
        params["fregto"] = int(criteria.year_max)
    if criteria.km_max:
        params["kmto"] = int(criteria.km_max)
    if criteria.power_min:
        params["powerfrom"] = int(criteria.power_min)
    fuels = [FUEL_QUERY[f] for f in (normalize(x) for x in criteria.fuels) if f in FUEL_QUERY]
    if fuels:
        params["fuel"] = ",".join(fuels)
    gear = GEARBOX_QUERY.get(normalize(criteria.gearbox))
    if gear:
        params["gear"] = gear
    if normalize(criteria.seller) == "privato":
        params["custtype"] = "P"
    elif normalize(criteria.seller) == "concessionario":
        params["custtype"] = "D"
    return params


def extract_next_data(html: str) -> dict[str, Any]:
    match = NEXT_DATA_RE.search(html)
    if not match:
        raise ValueError("blob __NEXT_DATA__ non trovato: il layout di AutoScout24 è cambiato")
    return json.loads(match.group(1))


def _find_listings(node: Any, depth: int = 0) -> list[dict[str, Any]]:
    """Il percorso esatto cambia con le release del sito: cerchiamo la prima lista di annunci."""
    if depth > 8:
        return []
    if isinstance(node, list):
        looks_like_ads = [
            item for item in node
            if isinstance(item, dict) and "id" in item and ("vehicle" in item or "tracking" in item)
        ]
        if len(looks_like_ads) >= max(1, len(node) // 2) and looks_like_ads:
            return looks_like_ads
        for item in node:
            found = _find_listings(item, depth + 1)
            if found:
                return found
        return []
    if isinstance(node, dict):
        for key in ("listings", "articles", "results"):
            found = _find_listings(node.get(key), depth + 1)
            if found:
                return found
        for value in node.values():
            found = _find_listings(value, depth + 1)
            if found:
                return found
    return []


def _price(item: dict[str, Any]) -> float | None:
    for path in (
        ("prices", "public", "amountInEUR"),
        ("price", "amount"),
        ("tracking", "price"),
        ("prices", "public", "priceFormatted"),
    ):
        value = to_float(dig(item, *path))
        if value:
            return value
    return None


def _url(item: dict[str, Any]) -> str:
    url = item.get("url") or dig(item, "seo", "url") or ""
    if url and url.startswith("/"):
        url = "https://www.autoscout24.it" + url
    return url


def parse(payload: dict[str, Any]) -> list[Listing]:
    listings: list[Listing] = []
    for item in _find_listings(payload):
        external_id = str(item.get("id") or "").strip()
        url = _url(item)
        if not external_id and not url:
            continue
        vehicle = item.get("vehicle") or {}
        tracking = item.get("tracking") or {}
        title = " ".join(
            str(part).strip()
            for part in (vehicle.get("make"), vehicle.get("model"), vehicle.get("modelVersionInput"))
            if part
        ).strip() or str(item.get("title") or "").strip()

        listings.append(
            Listing(
                provider=AutoScout24Provider.key,
                external_id=external_id or url,
                url=url,
                title=title,
                description=str(vehicle.get("modelVersionInput") or item.get("subtitle") or "").strip(),
                price=_price(item),
                mileage=to_int(tracking.get("mileage") or dig(item, "vehicleDetails", 0, "data")),
                year=year_from(
                    tracking.get("firstRegistration")
                    or tracking.get("first_registration")
                    or vehicle.get("firstRegistrationDate")
                ),
                make=str(vehicle.get("make") or tracking.get("make") or "").strip(),
                model=str(vehicle.get("model") or tracking.get("model") or "").strip(),
                version=str(vehicle.get("modelVersionInput") or "").strip(),
                fuel=str(tracking.get("fuelType") or vehicle.get("fuelCategory") or "").strip(),
                gearbox=str(tracking.get("transmissionType") or tracking.get("gearBox") or "").strip(),
                power_hp=to_int(tracking.get("powerHP") or tracking.get("power_hp")),
                seller="concessionario" if normalize(dig(item, "seller", "type")) == "dealer" else "privato",
                location=str(dig(item, "location", "city") or "").strip(),
                province=str(dig(item, "location", "zip") or "").strip(),
                image=dig(item, "images", 0) if isinstance(dig(item, "images", 0), str) else dig(item, "images", 0, "src") or "",
            )
        )
    return listings


class AutoScout24Provider(Provider):
    key = "autoscout24"
    label = "AutoScout24"

    def search(self, criteria: Criteria, limit: int = 60) -> list[Listing]:
        results: list[Listing] = []
        page = 1
        size = 20
        while len(results) < limit and page <= 5:
            response = get(build_url(criteria), params=build_params(criteria, page=page, size=size))
            page_items = parse(extract_next_data(response.text))
            if not page_items:
                break
            results.extend(page_items)
            if len(page_items) < size:
                break
            page += 1
        return results[:limit]
