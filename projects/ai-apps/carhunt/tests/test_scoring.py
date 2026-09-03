from datetime import datetime

from app.providers.base import Criteria, Listing
from app.scoring import (
    build_market_model,
    clean_weights,
    evaluate,
    evaluate_all,
    it_num,
    verdict_for,
)

YEAR = datetime.now().year


def make_listing(price, mileage, year, **kwargs):
    defaults = dict(
        provider="test", external_id=f"{price}-{mileage}-{year}", url="https://example.invalid/x",
        title="Volkswagen Golf 1.6 TDI", make="Volkswagen", model="Golf",
    )
    defaults.update(kwargs)
    return Listing(price=price, mileage=mileage, year=year, **defaults)


def market_pool():
    """Prezzi coerenti con un modello lineare: 20000 - 0.06*km - 500*eta'."""
    pool = []
    for index in range(12):
        mileage = 20_000 + index * 12_000
        age = index % 6
        price = 20_000 - 0.06 * mileage - 500 * age
        pool.append(make_listing(price, mileage, YEAR - age))
    return pool


def test_modello_di_mercato_usa_la_regressione_con_dati_sufficienti():
    model = build_market_model(market_pool())
    assert model.method == "regressione"
    assert model.per_km < 0  # piu' km, meno valore
    assert model.per_year < 0

    stima = model.estimate(make_listing(0, 80_000, YEAR - 2))
    assert abs(stima - (20_000 - 0.06 * 80_000 - 500 * 2)) < 300


def test_modello_di_mercato_ripiega_sulla_mediana_con_pochi_annunci():
    model = build_market_model([make_listing(10_000, 100_000, YEAR - 5),
                                make_listing(12_000, 80_000, YEAR - 4)])
    assert model.method == "mediana"
    assert model.estimate(make_listing(0, 90_000, YEAR - 4)) == 11_000


def test_annuncio_sotto_mercato_prende_punteggio_alto_e_commento_esplicito():
    pool = market_pool()
    affare = make_listing(9_000, 80_000, YEAR - 2, external_id="affare")
    caro = make_listing(19_000, 80_000, YEAR - 2, external_id="caro")
    model = build_market_model(pool)
    criteria = Criteria(make="Volkswagen", model="Golf")
    weights = clean_weights({"mercato": 10, "prezzo": 5, "km": 3, "anno": 3})

    buono = evaluate(affare, criteria=criteria, weights=weights, pool=pool + [affare], market=model)
    brutto = evaluate(caro, criteria=criteria, weights=weights, pool=pool + [caro], market=model)

    assert buono.deal_delta > 0.2
    assert brutto.deal_delta < -0.2
    assert buono.score > brutto.score + 20
    assert "sotto la stima di mercato" in buono.comment
    assert "sopra la stima di mercato" in brutto.comment
    assert buono.verdict in {"Ottimo affare", "Buon affare"}


def test_i_pesi_cambiano_la_classifica():
    pool = market_pool()
    economica_ma_scassata = make_listing(7_000, 260_000, YEAR - 10, external_id="a")
    cara_ma_nuova = make_listing(17_000, 15_000, YEAR, external_id="b")
    candidati = [economica_ma_scassata, cara_ma_nuova]
    criteria = Criteria()

    solo_prezzo = {"mercato": 0, "prezzo": 10, "km": 0, "anno": 0, "potenza": 0, "distanza": 0, "dotazioni": 0}
    solo_km_anno = {"mercato": 0, "prezzo": 0, "km": 10, "anno": 10, "potenza": 0, "distanza": 0, "dotazioni": 0}

    per_prezzo = dict((l.external_id, e.score) for l, e in
                      evaluate_all(candidati, criteria=criteria, weights=solo_prezzo, pool=pool + candidati))
    per_stato = dict((l.external_id, e.score) for l, e in
                     evaluate_all(candidati, criteria=criteria, weights=solo_km_anno, pool=pool + candidati))

    assert per_prezzo["a"] > per_prezzo["b"]
    assert per_stato["b"] > per_stato["a"]


def test_limiti_utente_finiscono_nel_commento():
    pool = market_pool()
    listing = make_listing(16_000, 200_000, YEAR - 3)
    criteria = Criteria(price_max=12_000, km_max=150_000,
                        nice_to_have=["navigatore", "gancio traino"])
    listing.description = "Ottima auto con navigatore di serie"
    evaluation = evaluate(listing, criteria=criteria, weights=clean_weights({}),
                          pool=pool, market=build_market_model(pool))

    assert "fuori_budget" in evaluation.flags
    assert "km_oltre_limite" in evaluation.flags
    assert "Fuori budget" in evaluation.comment
    assert "navigatore" in evaluation.comment
    assert evaluation.breakdown["dotazioni"]["utilita"] == 0.5  # 1 su 2


def test_distanza_da_casa_pesa_sul_punteggio():
    pool = [make_listing(10_000, 100_000, YEAR - 5, lat=45.46, lon=9.19)]
    vicina = make_listing(10_000, 100_000, YEAR - 5, external_id="vicina", lat=45.5, lon=9.2)
    lontana = make_listing(10_000, 100_000, YEAR - 5, external_id="lontana", lat=40.85, lon=14.26)
    criteria = Criteria(home_lat=45.46, home_lon=9.19, max_distance_km=200)
    weights = {"mercato": 0, "prezzo": 0, "km": 0, "anno": 0, "potenza": 0, "distanza": 10, "dotazioni": 0}
    model = build_market_model(pool)

    vicino = evaluate(vicina, criteria=criteria, weights=weights, pool=pool, market=model)
    lontano = evaluate(lontana, criteria=criteria, weights=weights, pool=pool, market=model)

    assert vicino.score > 90
    assert lontano.score < 10
    assert "fuori_raggio" in lontano.flags
    assert "km da casa" in vicino.comment


def test_verdetti_e_formattazione():
    assert verdict_for(85, 0.15) == "Ottimo affare"
    assert verdict_for(72, 0.0) == "Buon affare"
    assert verdict_for(30, -0.3) == "Da scartare"
    assert it_num(14200) == "14.200"
    assert it_num(None) == "n.d."


def test_pesi_sporchi_vengono_ripuliti():
    weights = clean_weights({"mercato": 99, "prezzo": "3", "sconosciuto": 5, "km": None})
    assert weights["mercato"] == 10
    assert weights["prezzo"] == 3
    assert "sconosciuto" not in weights
    assert weights["km"] == 5  # valore di default, il None e' ignorato
