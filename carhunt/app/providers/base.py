"""Modello comune a tutti i portali: un annuncio normalizzato + i criteri di ricerca."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class Criteria:
    """Cosa cerchiamo. Arriva dalla webapp come JSON."""

    make: str = ""
    model: str = ""
    keywords: str = ""
    price_min: float | None = None
    price_max: float | None = None
    year_min: int | None = None
    year_max: int | None = None
    km_max: int | None = None
    power_min: int | None = None
    fuels: list[str] = field(default_factory=list)
    gearbox: str = ""
    seller: str = ""  # "", "privato", "concessionario"
    region: str = ""  # slug regione per Subito, es. "lombardia"
    home_lat: float | None = None
    home_lon: float | None = None
    max_distance_km: int | None = None
    must_have: list[str] = field(default_factory=list)
    nice_to_have: list[str] = field(default_factory=list)
    exclude: list[str] = field(default_factory=list)
    providers: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "Criteria":
        data = data or {}
        known = {f for f in cls.__dataclass_fields__}
        clean: dict[str, Any] = {}
        for key, value in data.items():
            if key not in known:
                continue
            if value in ("", None):
                continue
            clean[key] = value
        for list_field in ("fuels", "must_have", "nice_to_have", "exclude", "providers"):
            value = clean.get(list_field)
            if isinstance(value, str):
                clean[list_field] = [p.strip() for p in value.split(",") if p.strip()]
        for num_field in ("price_min", "price_max", "home_lat", "home_lon"):
            if num_field in clean:
                clean[num_field] = _to_float(clean[num_field])
        for int_field in ("year_min", "year_max", "km_max", "power_min", "max_distance_km"):
            if int_field in clean:
                clean[int_field] = _to_int(clean[int_field])
        return cls(**clean)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def query_text(self) -> str:
        parts = [self.make, self.model, self.keywords]
        return " ".join(p.strip() for p in parts if p and p.strip()).strip()


@dataclass
class Listing:
    """Annuncio normalizzato, indipendente dal portale di origine."""

    provider: str
    external_id: str
    url: str
    title: str
    price: float | None = None
    mileage: int | None = None
    year: int | None = None
    make: str = ""
    model: str = ""
    version: str = ""
    fuel: str = ""
    gearbox: str = ""
    power_hp: int | None = None
    seller: str = ""
    location: str = ""
    province: str = ""
    lat: float | None = None
    lon: float | None = None
    image: str = ""
    description: str = ""

    @property
    def age_years(self) -> float | None:
        if not self.year:
            return None
        return max(0.0, datetime.now().year - self.year)

    @property
    def haystack(self) -> str:
        return normalize(" ".join([self.title, self.version, self.description]))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class Provider:
    """Interfaccia dei portali. `search` puo' fare rete, `parse` mai: cosi' e' testabile."""

    key: str = ""
    label: str = ""
    needs_network: bool = True

    def search(self, criteria: Criteria, limit: int = 60) -> list[Listing]:  # pragma: no cover
        raise NotImplementedError


# --------------------------------------------------------------------------- utils

_WS = re.compile(r"\s+")


def normalize(text: str | None) -> str:
    """Minuscolo, senza accenti: serve per il match delle parole chiave."""
    if not text:
        return ""
    text = unicodedata.normalize("NFKD", str(text))
    text = "".join(c for c in text if not unicodedata.combining(c))
    return _WS.sub(" ", text.lower()).strip()


def _to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    cleaned = re.sub(r"[^\d,.\-]", "", str(value))
    if not cleaned:
        return None
    # 12.500,00 -> 12500.00 ; 12,500 -> 12500
    if "," in cleaned and "." in cleaned:
        cleaned = cleaned.replace(".", "").replace(",", ".")
    elif "," in cleaned:
        cleaned = cleaned.replace(",", ".") if cleaned.count(",") == 1 and len(cleaned.split(",")[-1]) <= 2 else cleaned.replace(",", "")
    try:
        return float(cleaned)
    except ValueError:
        return None


def _to_int(value: Any) -> int | None:
    number = _to_float(value)
    return int(round(number)) if number is not None else None


to_float = _to_float
to_int = _to_int


def year_from(value: Any) -> int | None:
    """Accetta 2018, "2018", "03/2018", "2018-03-01"."""
    if value is None:
        return None
    match = re.search(r"(19|20)\d{2}", str(value))
    if not match:
        return None
    year = int(match.group(0))
    return year if 1950 <= year <= datetime.now().year + 1 else None


def dig(data: Any, *path: str | int, default: Any = None) -> Any:
    """Accesso tollerante a JSON annidati: dig(d, "a", 0, "b")."""
    current = data
    for step in path:
        try:
            if isinstance(step, int):
                current = current[step]
            else:
                current = current.get(step)
        except (AttributeError, KeyError, IndexError, TypeError):
            return default
        if current is None:
            return default
    return current
