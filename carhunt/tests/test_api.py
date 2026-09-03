import pytest
from fastapi.testclient import TestClient

from app import pipeline
from app.api import router
from fastapi import FastAPI


@pytest.fixture()
def client(temp_db, monkeypatch):
    monkeypatch.setattr(pipeline, "safe_send", lambda text, chat=None: True)
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def payload(**overrides):
    data = {
        "name": "Golf diesel",
        "min_score": 60,
        "criteria": {"make": "Volkswagen", "model": "Golf", "price_max": 15000, "providers": ["demo"]},
        "weights": {"mercato": 9, "prezzo": 5},
    }
    data.update(overrides)
    return data


def test_meta_espone_pesi_e_portali(client):
    body = client.get("/api/meta").json()
    assert "mercato" in body["weight_keys"]
    assert body["weight_labels"]["mercato"]
    assert any(p["key"] == "demo" for p in body["providers"])
    assert body["interval_minutes"] >= 5


def test_ciclo_completo_di_una_ricerca(client):
    created = client.post("/api/searches", json=payload()).json()
    assert created["id"]
    assert created["criteria"]["make"] == "Volkswagen"
    assert created["weights"]["mercato"] == 9

    listed = client.get("/api/searches").json()
    assert len(listed) == 1

    updated = client.put(f"/api/searches/{created['id']}",
                         json=payload(name="Golf o Polo", min_score=75)).json()
    assert updated["name"] == "Golf o Polo"
    assert updated["min_score"] == 75

    run = client.post(f"/api/searches/{created['id']}/run").json()
    assert run["found"] > 0

    listings = client.get(f"/api/searches/{created['id']}/listings").json()
    assert listings and listings[0]["score"] is not None
    assert listings[0]["comment"]

    assert client.delete(f"/api/searches/{created['id']}").status_code == 204
    assert client.get(f"/api/searches/{created['id']}").status_code == 404


def test_nome_obbligatorio(client):
    assert client.post("/api/searches", json=payload(name="  ")).status_code == 422


def test_simulazione_riordina_senza_salvare(client):
    created = client.post("/api/searches", json=payload()).json()
    client.post(f"/api/searches/{created['id']}/run")

    prezzo = client.post(f"/api/searches/{created['id']}/simulate",
                         json={"weights": {"mercato": 0, "prezzo": 10, "km": 0, "anno": 0,
                                           "potenza": 0, "distanza": 0, "dotazioni": 0}}).json()
    km = client.post(f"/api/searches/{created['id']}/simulate",
                     json={"weights": {"mercato": 0, "prezzo": 0, "km": 10, "anno": 0,
                                       "potenza": 0, "distanza": 0, "dotazioni": 0}}).json()

    assert prezzo[0]["price"] == min(item["price"] for item in prezzo)
    assert km[0]["mileage"] == min(item["mileage"] for item in km)

    salvati = client.get(f"/api/searches/{created['id']}/listings").json()
    assert {item["id"] for item in salvati} == {item["id"] for item in prezzo}


def test_storico_dei_giri(client):
    created = client.post("/api/searches", json=payload()).json()
    client.post(f"/api/searches/{created['id']}/run")
    runs = client.get("/api/runs").json()
    assert runs and runs[0]["status"] in {"ok", "parziale"}
    assert runs[0]["search_name"] == "Golf diesel"


def test_telegram_non_configurato_risponde_400(client, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "telegram_bot_token", "")
    assert client.post("/api/telegram/test", json={}).status_code == 400


def test_chat_id_si_puo_svuotare(client):
    created = client.post("/api/searches", json=payload(telegram_chat_id="12345")).json()
    assert created["telegram_chat_id"] == "12345"

    svuotata = client.put(f"/api/searches/{created['id']}", json=payload(telegram_chat_id="")).json()
    assert svuotata["telegram_chat_id"] is None
