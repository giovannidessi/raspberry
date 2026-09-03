import pytest

from app import pipeline, store
from app.providers.base import Criteria, Listing


def make_listing(external_id, price=10_000, **kwargs):
    return Listing(provider="demo", external_id=external_id,
                   url=f"https://example.invalid/{external_id}",
                   title=kwargs.pop("title", "Volkswagen Golf 1.6 TDI Business"),
                   price=price, **kwargs)


@pytest.fixture()
def sent(monkeypatch):
    """Cattura i messaggi Telegram invece di spedirli davvero."""
    messages = []
    monkeypatch.setattr(pipeline, "safe_send", lambda text, chat=None: messages.append(text) or True)
    return messages


def make_search(**overrides):
    payload = {
        "name": "Golf per mio fratello",
        "min_score": 0,
        "criteria": {"make": "Volkswagen", "model": "Golf", "providers": ["demo"], "price_max": 15000},
        "weights": {"mercato": 8, "prezzo": 6, "km": 5, "anno": 4},
    }
    payload.update(overrides)
    return store.create_search(payload)


def test_filtri_rigidi(temp_db):
    criteria = Criteria(price_max=15_000, km_max=150_000, year_min=2015,
                        exclude=["incidentata"], must_have=["tagliandi"], fuels=["Diesel"])

    ok = make_listing("ok", 12_000, mileage=100_000, year=2018, fuel="Diesel",
                      description="tagliandi certificati")
    assert pipeline.passes_hard_filters(ok, criteria)

    assert not pipeline.passes_hard_filters(
        make_listing("no1", 12_000, mileage=100_000, year=2018, fuel="Diesel",
                     description="tagliandi ok ma incidentata"), criteria)
    assert not pipeline.passes_hard_filters(
        make_listing("no2", 12_000, mileage=100_000, year=2018, fuel="Diesel"), criteria)
    assert not pipeline.passes_hard_filters(
        make_listing("no3", 30_000, mileage=100_000, year=2018, fuel="Diesel",
                     description="tagliandi"), criteria)
    assert not pipeline.passes_hard_filters(
        make_listing("no4", 12_000, mileage=100_000, year=2010, fuel="Diesel",
                     description="tagliandi"), criteria)
    assert not pipeline.passes_hard_filters(
        make_listing("no5", 12_000, mileage=100_000, year=2018, fuel="Benzina",
                     description="tagliandi"), criteria)


def test_deduplica_lo_stesso_annuncio_su_portali_diversi(temp_db):
    a = make_listing("1", 11_000, mileage=90_000, year=2018)
    b = Listing(provider="subito", external_id="9", url="https://x", title=a.title,
                price=11_000, mileage=90_000, year=2018)
    c = make_listing("2", 12_500, mileage=70_000, year=2019)

    assert len(pipeline.deduplicate([a, b, c])) == 2


def test_primo_giro_manda_solo_il_riepilogo(temp_db, sent):
    search = make_search()
    result = pipeline.run_search(search["id"])

    assert result["found"] > 0
    assert result["new"] == result["found"]
    assert len(sent) == 1
    assert "Ricerca attivata" in sent[0]

    listings = store.listings_for_search(search["id"])
    assert all(row["score"] is not None for row in listings)
    assert all(row["comment"] for row in listings)
    assert all(row["notified_at"] for row in listings)


def test_secondo_giro_notifica_solo_le_novita(temp_db, sent, monkeypatch):
    search = make_search()
    pipeline.run_search(search["id"])
    sent.clear()

    base = [make_listing(f"vecchio-{i}", 10_000 + i * 500, mileage=100_000, year=2017)
            for i in range(3)]
    monkeypatch.setattr(pipeline, "fetch", lambda criteria, limit: (list(base), []))
    pipeline.run_search(search["id"])
    sent.clear()

    nuovo = make_listing("nuovo", 7_000, mileage=60_000, year=2020)
    monkeypatch.setattr(pipeline, "fetch", lambda criteria, limit: (base + [nuovo], []))
    result = pipeline.run_search(search["id"])

    assert result["new"] == 1
    assert len(sent) == 1
    assert "Nuovo annuncio" in sent[0]
    assert "nuovo" in sent[0]


def test_ribasso_di_prezzo_genera_una_notifica(temp_db, sent, monkeypatch):
    search = make_search()
    listing = make_listing("uno", 12_000, mileage=90_000, year=2018)
    monkeypatch.setattr(pipeline, "fetch", lambda criteria, limit: ([listing], []))
    pipeline.run_search(search["id"])  # bootstrap
    sent.clear()

    ribassato = make_listing("uno", 9_900, mileage=90_000, year=2018)
    monkeypatch.setattr(pipeline, "fetch", lambda criteria, limit: ([ribassato], []))
    result = pipeline.run_search(search["id"])

    assert result["price_drops"] == 1
    assert len(sent) == 1
    assert "Ribasso di prezzo" in sent[0]
    assert "era 12.000" in sent[0]


def test_soglia_punteggio_blocca_le_notifiche(temp_db, sent, monkeypatch):
    search = make_search(min_score=99)
    monkeypatch.setattr(pipeline, "fetch",
                        lambda criteria, limit: ([make_listing("a", 12_000, mileage=90_000, year=2018)], []))
    pipeline.run_search(search["id"])
    sent.clear()

    monkeypatch.setattr(pipeline, "fetch", lambda criteria, limit: (
        [make_listing("a", 12_000, mileage=90_000, year=2018),
         make_listing("b", 12_100, mileage=91_000, year=2018)], []))
    result = pipeline.run_search(search["id"])

    assert result["new"] == 1
    assert result["notified"] == 0
    assert sent == []


def test_un_portale_rotto_non_ferma_il_giro(temp_db, sent, monkeypatch):
    search = make_search()
    monkeypatch.setattr(pipeline, "fetch",
                        lambda criteria, limit: ([make_listing("a", 11_000, mileage=90_000, year=2018)],
                                                 ["AutoScout24: TimeoutError"]))
    result = pipeline.run_search(search["id"])

    assert result["status"] == "parziale"
    assert result["found"] == 1
    assert "AutoScout24" in result["errors"][0]


def test_annunci_spariti_vengono_archiviati(temp_db, sent, monkeypatch):
    search = make_search()
    due = [make_listing("a", 11_000, mileage=90_000, year=2018),
           make_listing("b", 12_000, mileage=80_000, year=2019)]
    monkeypatch.setattr(pipeline, "fetch", lambda criteria, limit: (due, []))
    pipeline.run_search(search["id"])

    monkeypatch.setattr(pipeline, "fetch", lambda criteria, limit: (due[:1], []))
    pipeline.run_search(search["id"])

    assert len(store.listings_for_search(search["id"], only_active=True)) == 1
    assert len(store.listings_for_search(search["id"], only_active=False)) == 2


def test_run_all_salta_le_ricerche_in_pausa(temp_db, sent):
    make_search(name="attiva")
    in_pausa = make_search(name="in pausa")
    store.update_search(in_pausa["id"], {"enabled": False})

    results = pipeline.run_all()
    assert len(results) == 1
