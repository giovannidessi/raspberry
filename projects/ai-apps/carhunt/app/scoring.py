"""Punteggio di convenienza.

Due cose distinte, che poi finiscono nel commento dell'annuncio:

1. la *stima di mercato*: quanto dovrebbe costare quell'auto viste km ed eta',
   ricavata dagli altri annunci comparabili raccolti dalla stessa ricerca;
2. il *punteggio pesato*: quanto l'annuncio si avvicina a cio' che conta per
   chi cerca, secondo i pesi impostati dalla webapp.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Iterable, Sequence

from .providers.base import Criteria, Listing, normalize

WEIGHT_KEYS = ["mercato", "prezzo", "km", "anno", "potenza", "distanza", "dotazioni"]

WEIGHT_LABELS = {
    "mercato": "Affare rispetto al mercato",
    "prezzo": "Prezzo assoluto",
    "km": "Chilometraggio",
    "anno": "Anno di immatricolazione",
    "potenza": "Potenza",
    "distanza": "Vicinanza a casa",
    "dotazioni": "Dotazioni ricercate",
}

DEFAULT_WEIGHTS = {
    "mercato": 8,
    "prezzo": 6,
    "km": 5,
    "anno": 4,
    "potenza": 2,
    "distanza": 2,
    "dotazioni": 3,
}

MIN_SAMPLES_FOR_REGRESSION = 8


def clean_weights(raw: dict[str, Any] | None) -> dict[str, float]:
    """Tiene solo i pesi noti, li limita a 0..10 e scarta i valori non numerici."""
    weights = dict(DEFAULT_WEIGHTS)
    for key, value in (raw or {}).items():
        if key not in WEIGHT_KEYS:
            continue
        try:
            weights[key] = max(0.0, min(10.0, float(value)))
        except (TypeError, ValueError):
            continue
    if sum(weights.values()) <= 0:
        weights = dict(DEFAULT_WEIGHTS)
    return weights


# --------------------------------------------------------------------- statistica

def it_num(value: float | int | None) -> str:
    """Numeri con il separatore delle migliaia all'italiana: 14200 -> 14.200."""
    if value is None:
        return "n.d."
    return f"{value:,.0f}".replace(",", ".")


def median(values: Sequence[float]) -> float | None:
    data = sorted(v for v in values if v is not None)
    if not data:
        return None
    middle = len(data) // 2
    if len(data) % 2:
        return float(data[middle])
    return (data[middle - 1] + data[middle]) / 2.0


def _rank(value: float | None, pool: Sequence[float], higher_is_better: bool) -> float:
    """Posizione percentile del valore nel gruppo (0..1). Ignoto -> 0.5."""
    data = sorted(v for v in pool if v is not None)
    if value is None or len(data) < 2:
        return 0.5
    below = sum(1 for v in data if v < value)
    equal = sum(1 for v in data if v == value)
    percentile = (below + equal / 2.0) / len(data)
    return percentile if higher_is_better else 1.0 - percentile


def _solve3(matrix: list[list[float]], vector: list[float]) -> list[float] | None:
    """Eliminazione di Gauss su un sistema 3x3 (nessuna dipendenza da numpy)."""
    size = 3
    augmented = [row[:] + [vector[i]] for i, row in enumerate(matrix)]
    for col in range(size):
        pivot_row = max(range(col, size), key=lambda r: abs(augmented[r][col]))
        if abs(augmented[pivot_row][col]) < 1e-9:
            return None
        augmented[col], augmented[pivot_row] = augmented[pivot_row], augmented[col]
        pivot = augmented[col][col]
        for row in range(col + 1, size):
            factor = augmented[row][col] / pivot
            for k in range(col, size + 1):
                augmented[row][k] -= factor * augmented[col][k]
    solution = [0.0] * size
    for row in reversed(range(size)):
        total = augmented[row][size] - sum(augmented[row][k] * solution[k] for k in range(row + 1, size))
        solution[row] = total / augmented[row][row]
    return solution


def _drop_price_outliers(samples: list[tuple[float, float, float]]) -> list[tuple[float, float, float]]:
    """Toglie gli annunci con prezzo fuori scala (spesso ricambi o errori di battitura)."""
    prices = sorted(s[0] for s in samples)
    if len(prices) < 8:
        return samples
    q1 = prices[len(prices) // 4]
    q3 = prices[(3 * len(prices)) // 4]
    iqr = q3 - q1
    low, high = q1 - 1.5 * iqr, q3 + 1.5 * iqr
    kept = [s for s in samples if low <= s[0] <= high]
    return kept or samples


@dataclass
class MarketModel:
    """Stima del prezzo giusto per km/eta'. Ricade sulla mediana se i dati sono pochi."""

    intercept: float = 0.0
    per_km: float = 0.0
    per_year: float = 0.0
    median_price: float | None = None
    median_mileage: float | None = None
    median_year: float | None = None
    samples: int = 0
    method: str = "insufficiente"

    def estimate(self, listing: Listing) -> float | None:
        if self.method == "regressione" and listing.mileage is not None and listing.year:
            age = max(0.0, datetime.now().year - listing.year)
            value = self.intercept + self.per_km * listing.mileage + self.per_year * age
            if self.median_price:
                value = max(0.35 * self.median_price, min(2.5 * self.median_price, value))
            return value if value > 0 else self.median_price
        return self.median_price


def build_market_model(pool: Iterable[Listing]) -> MarketModel:
    listings = [l for l in pool if l.price and l.price > 0]
    model = MarketModel(
        median_price=median([l.price for l in listings if l.price]),
        median_mileage=median([float(l.mileage) for l in listings if l.mileage is not None]),
        median_year=median([float(l.year) for l in listings if l.year]),
        samples=len(listings),
    )
    if not listings:
        return model
    model.method = "mediana"

    current_year = datetime.now().year
    samples = [
        (float(l.price), float(l.mileage), float(max(0, current_year - l.year)))
        for l in listings
        if l.price and l.mileage is not None and l.year
    ]
    samples = _drop_price_outliers(samples)
    if len(samples) < MIN_SAMPLES_FOR_REGRESSION:
        return model

    n = float(len(samples))
    sum_km = sum(s[1] for s in samples)
    sum_age = sum(s[2] for s in samples)
    matrix = [
        [n, sum_km, sum_age],
        [sum_km, sum(s[1] * s[1] for s in samples), sum(s[1] * s[2] for s in samples)],
        [sum_age, sum(s[1] * s[2] for s in samples), sum(s[2] * s[2] for s in samples)],
    ]
    vector = [
        sum(s[0] for s in samples),
        sum(s[0] * s[1] for s in samples),
        sum(s[0] * s[2] for s in samples),
    ]
    solution = _solve3(matrix, vector)
    if solution is None:
        return model
    intercept, per_km, per_year = solution
    # una regressione sensata non fa aumentare il prezzo con km ed eta'
    if per_km > 0 or per_year > 0 or intercept <= 0:
        return model
    model.intercept, model.per_km, model.per_year = intercept, per_km, per_year
    model.method = "regressione"
    return model


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6371.0
    d_lat = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)
    a = (
        math.sin(d_lat / 2) ** 2
        + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(d_lon / 2) ** 2
    )
    return 2 * radius * math.asin(math.sqrt(a))


# ------------------------------------------------------------------- valutazione

@dataclass
class Evaluation:
    score: float
    verdict: str
    comment: str
    deal_delta: float | None
    estimated_price: float | None
    distance_km: float | None
    breakdown: dict[str, dict[str, float]] = field(default_factory=dict)
    flags: list[str] = field(default_factory=list)

    def as_row(self) -> dict[str, Any]:
        return {
            "score": round(self.score, 1),
            "verdict": self.verdict,
            "comment": self.comment,
            "deal_delta": self.deal_delta,
            "estimated_price": self.estimated_price,
            "breakdown": self.breakdown,
            "flags": self.flags,
        }


def _matched_keywords(listing: Listing, keywords: Sequence[str]) -> list[str]:
    hay = listing.haystack
    return [k for k in keywords if k.strip() and normalize(k) in hay]


def evaluate(
    listing: Listing,
    *,
    criteria: Criteria,
    weights: dict[str, float],
    pool: Sequence[Listing],
    market: MarketModel,
) -> Evaluation:
    """Calcola punteggio, indice di affare e commento in italiano per un annuncio."""

    weights = clean_weights(weights)
    prices = [l.price for l in pool if l.price]
    mileages = [float(l.mileage) for l in pool if l.mileage is not None]
    years = [float(l.year) for l in pool if l.year]
    powers = [float(l.power_hp) for l in pool if l.power_hp]

    flags: list[str] = []
    utilities: dict[str, float] = {}
    notes: list[str] = []

    # --- 1. affare rispetto alla stima di mercato
    estimated = market.estimate(listing)
    deal_delta: float | None = None
    if estimated and listing.price:
        deal_delta = (estimated - listing.price) / estimated
        utilities["mercato"] = max(0.0, min(1.0, 0.5 + deal_delta * 2.0))
    else:
        utilities["mercato"] = 0.5
        flags.append("stima_mercato_assente")

    # --- 2. prezzo in assoluto (rispetto al budget e agli altri annunci)
    if listing.price:
        rank = _rank(listing.price, prices, higher_is_better=False)
        if criteria.price_max:
            budget = max(0.0, min(1.0, (criteria.price_max - listing.price) / criteria.price_max))
            utilities["prezzo"] = 0.5 * rank + 0.5 * budget
        else:
            utilities["prezzo"] = rank
    else:
        utilities["prezzo"] = 0.4
        flags.append("prezzo_assente")

    # --- 3. chilometraggio
    if listing.mileage is not None:
        utilities["km"] = _rank(float(listing.mileage), mileages, higher_is_better=False)
    else:
        utilities["km"] = 0.4
        flags.append("km_assenti")

    # --- 4. anno
    if listing.year:
        utilities["anno"] = _rank(float(listing.year), years, higher_is_better=True)
    else:
        utilities["anno"] = 0.4
        flags.append("anno_assente")

    # --- 5. potenza
    if listing.power_hp:
        utilities["potenza"] = _rank(float(listing.power_hp), powers, higher_is_better=True)
        if criteria.power_min and listing.power_hp < criteria.power_min:
            utilities["potenza"] *= 0.4
    else:
        utilities["potenza"] = 0.5

    # --- 6. distanza da casa
    distance_km: float | None = None
    if criteria.home_lat is not None and criteria.home_lon is not None and listing.lat and listing.lon:
        distance_km = haversine_km(criteria.home_lat, criteria.home_lon, listing.lat, listing.lon)
        limit = float(criteria.max_distance_km or 300)
        utilities["distanza"] = max(0.0, min(1.0, 1.0 - distance_km / max(limit, 1.0)))
        if criteria.max_distance_km and distance_km > criteria.max_distance_km:
            flags.append("fuori_raggio")
    else:
        utilities["distanza"] = 0.5

    # --- 7. dotazioni desiderate
    nice = list(criteria.nice_to_have or [])
    matched = _matched_keywords(listing, nice)
    utilities["dotazioni"] = (len(matched) / len(nice)) if nice else 0.5

    total_weight = sum(weights[k] for k in WEIGHT_KEYS) or 1.0
    score = 100.0 * sum(weights[k] * utilities[k] for k in WEIGHT_KEYS) / total_weight

    # dati mancanti: non ci fidiamo fino in fondo di un punteggio incompleto
    if "prezzo_assente" in flags:
        score *= 0.6
    elif len(flags) >= 2:
        score *= 0.9

    breakdown = {
        key: {
            "peso": round(weights[key], 1),
            "utilita": round(utilities[key], 3),
            "contributo": round(100.0 * weights[key] * utilities[key] / total_weight, 1),
        }
        for key in WEIGHT_KEYS
    }

    # --- commento in italiano
    if deal_delta is not None and estimated:
        pct = abs(deal_delta) * 100
        if deal_delta >= 0.12:
            notes.append(f"💰 Prezzo {pct:.0f}% sotto la stima di mercato ({it_num(estimated)} €) per km ed età simili.")
        elif deal_delta >= 0.04:
            notes.append(f"👍 Leggermente sotto la stima di mercato ({it_num(estimated)} €), circa {pct:.0f}% in meno.")
        elif deal_delta <= -0.12:
            notes.append(f"🚩 Prezzo {pct:.0f}% sopra la stima di mercato ({it_num(estimated)} €): c'e' margine di trattativa.")
        elif deal_delta <= -0.04:
            notes.append(f"⚠️ Un po' sopra la stima di mercato ({it_num(estimated)} €), circa {pct:.0f}% in più.")
        else:
            notes.append(f"➖ Prezzo in linea con il mercato (stima {it_num(estimated)} €).")
        if market.method == "mediana":
            notes.append("ℹ️ Stima basata sulla mediana degli annunci simili: pochi dati per un confronto più fine.")
    else:
        notes.append("ℹ️ Non ci sono abbastanza annunci comparabili per stimare il prezzo di mercato.")

    median_km = median(mileages)
    if listing.mileage is not None and median_km:
        delta_km = (listing.mileage - median_km) / median_km
        if delta_km <= -0.2:
            notes.append(f"✅ Chilometraggio basso: {it_num(listing.mileage)} km, {abs(delta_km)*100:.0f}% sotto la media degli annunci simili.")
        elif delta_km >= 0.25:
            notes.append(f"⚠️ Chilometraggio alto: {it_num(listing.mileage)} km, {delta_km*100:.0f}% sopra la media.")

    median_year = median(years)
    if listing.year and median_year:
        if listing.year >= median_year + 2:
            notes.append(f"✅ Immatricolazione recente ({listing.year}) rispetto agli altri annunci.")
        elif listing.year <= median_year - 3:
            notes.append(f"⚠️ Auto più vecchia della media ({listing.year}).")

    if criteria.km_max and listing.mileage is not None and listing.mileage > criteria.km_max:
        flags.append("km_oltre_limite")
        notes.append(f"⛔ Supera il limite di km che hai impostato ({it_num(criteria.km_max)} km).")
    if criteria.price_max and listing.price and listing.price > criteria.price_max:
        flags.append("fuori_budget")
        notes.append(f"⛔ Fuori budget: {it_num(listing.price)} € contro un massimo di {it_num(criteria.price_max)} €.")

    if matched:
        notes.append("✨ Include: " + ", ".join(matched) + ".")
    missing_nice = [k for k in nice if k not in matched]
    if nice and missing_nice and len(missing_nice) <= 4:
        notes.append("➖ Non risulta: " + ", ".join(missing_nice) + " (spesso non è scritto nell'annuncio).")

    if distance_km is not None:
        notes.append(f"📍 {listing.location or 'venditore'} a circa {distance_km:.0f} km da casa.")
    if listing.seller:
        notes.append(f"🧾 Venditore: {listing.seller}.")

    verdict = verdict_for(score, deal_delta)
    comment = "\n".join(notes)

    return Evaluation(
        score=round(score, 1),
        verdict=verdict,
        comment=comment,
        deal_delta=round(deal_delta, 4) if deal_delta is not None else None,
        estimated_price=round(estimated, 0) if estimated else None,
        distance_km=round(distance_km, 1) if distance_km is not None else None,
        breakdown=breakdown,
        flags=flags,
    )


def verdict_for(score: float, deal_delta: float | None) -> str:
    if score >= 80 and (deal_delta or 0) >= 0.08:
        return "Ottimo affare"
    if score >= 70:
        return "Buon affare"
    if score >= 55:
        return "Da valutare"
    if score >= 40:
        return "Poco interessante"
    return "Da scartare"


def evaluate_all(
    listings: Sequence[Listing],
    *,
    criteria: Criteria,
    weights: dict[str, float],
    pool: Sequence[Listing] | None = None,
) -> list[tuple[Listing, Evaluation]]:
    """Valuta un gruppo di annunci usando `pool` come riferimento di mercato."""
    reference = list(pool if pool is not None else listings)
    market = build_market_model(reference)
    return [
        (listing, evaluate(listing, criteria=criteria, weights=weights, pool=reference, market=market))
        for listing in listings
    ]
