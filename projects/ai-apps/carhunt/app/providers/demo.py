"""Provider finto: genera annunci verosimili senza rete.

Serve per provare l'app (e le notifiche Telegram) prima ancora di puntare
i portali veri, e per i test automatici.
"""

from __future__ import annotations

import random
from datetime import datetime

from .base import Criteria, Listing, Provider

VERSIONS = ["1.6 TDI Business", "2.0 TDI Sport", "1.0 TSI Style", "1.5 dCi Intens", "Hybrid Lounge"]
CITIES = [
    ("Milano", "MI", 45.4642, 9.1900),
    ("Bologna", "BO", 44.4949, 11.3426),
    ("Roma", "RM", 41.9028, 12.4964),
    ("Torino", "TO", 45.0703, 7.6869),
    ("Napoli", "NA", 40.8518, 14.2681),
]
FUELS = ["Diesel", "Benzina", "GPL", "Ibrida"]
GEARBOXES = ["Manuale", "Automatico"]


class DemoProvider(Provider):
    key = "demo"
    label = "Demo (annunci finti, senza rete)"
    needs_network = False

    def search(self, criteria: Criteria, limit: int = 60) -> list[Listing]:
        # seed legato all'ora: ogni giro orario introduce qualche annuncio nuovo
        bucket = int(datetime.now().timestamp() // 3600)
        rng = random.Random(f"{criteria.query_text}|{bucket}")
        make = criteria.make or "Volkswagen"
        model = criteria.model or "Golf"
        price_max = criteria.price_max or 18000
        price_min = criteria.price_min or max(2000, price_max * 0.45)

        listings: list[Listing] = []
        for index in range(min(limit, 12)):
            city, province, lat, lon = rng.choice(CITIES)
            year_min = criteria.year_min or 2013
            year_max = max(year_min, criteria.year_max or 2022)
            year = rng.randint(year_min, year_max)
            km_max = criteria.km_max or 190_000
            mileage = rng.randint(min(20_000, km_max), km_max)
            price = round(rng.uniform(price_min, price_max) / 100) * 100
            version = rng.choice(VERSIONS)
            listings.append(
                Listing(
                    provider=self.key,
                    external_id=f"demo-{bucket}-{index}",
                    url=f"https://example.invalid/annuncio/demo-{bucket}-{index}",
                    title=f"{make} {model} {version}",
                    description=f"{make} {model} {version}, tagliandi certificati, gomme nuove.",
                    price=float(price),
                    mileage=mileage,
                    year=year,
                    make=make,
                    model=model,
                    version=version,
                    fuel=rng.choice(criteria.fuels or FUELS),
                    gearbox=criteria.gearbox or rng.choice(GEARBOXES),
                    power_hp=rng.choice([90, 105, 115, 150, 190]),
                    seller=rng.choice(["privato", "concessionario"]),
                    location=city,
                    province=province,
                    lat=lat,
                    lon=lon,
                )
            )
        return listings
