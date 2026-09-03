import json
import pathlib

from app.providers.autoscout24 import AutoScout24Provider, build_params, extract_next_data
from app.providers.autoscout24 import parse as parse_as24
from app.providers.base import Criteria
from app.providers.demo import DemoProvider
from app.providers.subito import parse as parse_subito

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


def test_subito_parse_normalizza_i_campi():
    payload = json.loads((FIXTURES / "subito_search.json").read_text(encoding="utf-8"))
    listings = parse_subito(payload)

    assert len(listings) == 5
    first = listings[0]
    assert first.provider == "subito"
    assert first.external_id == "urn:subito:1000"
    assert first.price == 11500
    assert first.mileage == 95000
    assert first.year == 2017
    assert first.make == "Volkswagen"
    assert first.fuel == "Diesel"
    assert first.power_hp == 115
    assert first.seller == "concessionario"
    assert first.location == "Milano"
    assert (first.lat, first.lon) == (45.46, 9.19)
    assert first.url.startswith("https://www.subito.it/")


def test_subito_parse_tollera_annunci_incompleti():
    listings = parse_subito({"ads": [{"item": {"urn": "urn:x:1", "subject": "Auto", "urls": {}}}, {}]})
    assert len(listings) == 1
    assert listings[0].price is None


def test_autoscout24_parse_da_next_data():
    html = (FIXTURES / "autoscout24_search.html").read_text(encoding="utf-8")
    listings = parse_as24(extract_next_data(html))

    assert len(listings) == 3
    first = listings[0]
    assert first.provider == "autoscout24"
    assert first.price == 13900
    assert first.mileage == 72000
    assert first.year == 2018
    assert first.power_hp == 150
    assert first.seller == "privato"
    assert first.url == "https://www.autoscout24.it/annunci/volkswagen-golf-0-abc.html"
    assert listings[1].seller == "concessionario"


def test_autoscout24_parametri_di_ricerca():
    criteria = Criteria(make="Volkswagen", model="Golf", price_max=15000, km_max=120000,
                        fuels=["Diesel"], gearbox="Manuale", year_min=2016, seller="privato")
    params = build_params(criteria)
    assert params["priceto"] == 15000
    assert params["kmto"] == 120000
    assert params["fregfrom"] == 2016
    assert params["fuel"] == "D"
    assert params["gear"] == "M"
    assert params["custtype"] == "P"
    assert AutoScout24Provider.key == "autoscout24"


def test_demo_provider_rispetta_i_criteri():
    criteria = Criteria(make="Fiat", model="Panda", price_max=9000, year_min=2015, km_max=120000)
    listings = DemoProvider().search(criteria, limit=10)

    assert listings
    for listing in listings:
        assert listing.make == "Fiat"
        assert listing.price <= 9000
        assert 2015 <= listing.year
        assert listing.mileage <= 120000
