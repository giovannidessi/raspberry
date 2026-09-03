"""Subito.it - usa l'API JSON pubblica che alimenta il sito (hades.subito.it)."""

from __future__ import annotations

from typing import Any

from .base import Criteria, Listing, Provider, dig, normalize, to_float, to_int, year_from
from .http import get

API_URL = "https://hades.subito.it/v1/search/items"
CATEGORY_AUTO = "6"

# uri della feature -> attributo del nostro Listing
FEATURE_MAP = {
    "price": "price",
    "mileage": "mileage",
    "register_year": "year",
    "car_brand": "make",
    "car_model": "model",
    "car_version": "version",
    "fuel": "fuel",
    "gearbox": "gearbox",
    "horse_power": "power_hp",
}


def _feature_values(ad: dict[str, Any]) -> dict[str, str]:
    """Appiattisce la lista `features` in {nome: valore}."""
    out: dict[str, str] = {}
    for feature in ad.get("features") or []:
        uri = str(feature.get("uri") or "").rstrip("/").split("/")[-1]
        values = feature.get("values") or []
        if not uri or not values:
            continue
        first = values[0] if isinstance(values[0], dict) else {"value": values[0]}
        out[uri] = str(first.get("value") or first.get("key") or "").strip()
    return out


def parse(payload: dict[str, Any]) -> list[Listing]:
    """Trasforma la risposta dell'API in annunci normalizzati."""
    listings: list[Listing] = []
    for ad in payload.get("ads") or []:
        item = ad.get("item") if isinstance(ad.get("item"), dict) else ad
        urn = str(item.get("urn") or item.get("id") or "").strip()
        url = dig(item, "urls", "default") or dig(item, "urls", "mobile") or ""
        if not urn and not url:
            continue
        features = _feature_values(item)
        seller = "concessionario" if dig(item, "advertiser", "company") else "privato"
        image = dig(item, "images", 0, "scale", -1, "secureuri") or dig(item, "images", 0, "uri") or ""

        listings.append(
            Listing(
                provider=SubitoProvider.key,
                external_id=urn or url,
                url=url,
                title=str(item.get("subject") or "").strip(),
                description=str(item.get("body") or "").strip(),
                price=to_float(features.get("price")),
                mileage=to_int(features.get("mileage")),
                year=year_from(features.get("register_year")),
                make=(features.get("car_brand") or "").strip(),
                model=(features.get("car_model") or "").strip(),
                version=(features.get("car_version") or "").strip(),
                fuel=(features.get("fuel") or "").strip(),
                gearbox=(features.get("gearbox") or "").strip(),
                power_hp=to_int(features.get("horse_power")),
                seller=seller,
                location=dig(item, "geo", "town", "value") or dig(item, "geo", "city", "value") or "",
                province=dig(item, "geo", "city", "short_name") or dig(item, "geo", "region", "value") or "",
                lat=to_float(dig(item, "geo", "map", "latitude")),
                lon=to_float(dig(item, "geo", "map", "longitude")),
                image=image,
            )
        )
    return listings


class SubitoProvider(Provider):
    key = "subito"
    label = "Subito.it"

    def search(self, criteria: Criteria, limit: int = 60) -> list[Listing]:
        results: list[Listing] = []
        page_size = 50
        start = 0
        while len(results) < limit:
            params: dict[str, Any] = {
                "c": CATEGORY_AUTO,
                "t": "s",  # solo annunci di vendita
                "qso": "false",
                "shp": "true",
                "sort": "datedesc",
                "lim": min(page_size, limit - len(results)),
                "start": start,
            }
            if criteria.query_text:
                params["q"] = criteria.query_text
            if criteria.region:
                params["r"] = criteria.region
            if criteria.price_min is not None:
                params["ps"] = int(criteria.price_min)
            if criteria.price_max is not None:
                params["pe"] = int(criteria.price_max)

            payload = get(API_URL, params=params).json()
            page = parse(payload)
            if not page:
                break
            results.extend(page)
            start += len(page)
            if len(page) < params["lim"]:
                break
        return results[:limit]


def matches_free_text(listing: Listing, criteria: Criteria) -> bool:
    """Subito non ha filtri strutturati affidabili: rifiltriamo noi sul testo."""
    hay = listing.haystack
    for token in normalize(criteria.model).split():
        if token and token not in hay:
            return False
    return True
