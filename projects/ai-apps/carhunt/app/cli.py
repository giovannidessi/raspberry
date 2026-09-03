"""Comandi da terminale, utili sul Raspberry per diagnosticare i portali.

    python -m app.cli probe subito --make Volkswagen --model Golf --price-max 15000
    python -m app.cli run                # esegue tutte le ricerche attive
    python -m app.cli telegram-test
"""

from __future__ import annotations

import argparse
import json
import logging
import sys

from .db import init_db
from .notifier import TelegramError, send_message
from .pipeline import run_all, run_search
from .providers import PROVIDERS
from .providers.base import Criteria


def cmd_probe(args: argparse.Namespace) -> int:
    """Interroga un solo portale e stampa cosa e' riuscito a estrarre.

    Se un portale cambia struttura, qui si vede subito: 0 annunci o campi vuoti.
    """
    provider = PROVIDERS.get(args.provider)
    if not provider:
        print(f"portale sconosciuto: {args.provider}. Disponibili: {', '.join(PROVIDERS)}")
        return 2

    criteria = Criteria(
        make=args.make or "",
        model=args.model or "",
        keywords=args.keywords or "",
        price_max=args.price_max,
        km_max=args.km_max,
        year_min=args.year_min,
        region=args.region or "",
    )
    listings = provider.search(criteria, limit=args.limit)
    print(f"{provider.label}: {len(listings)} annunci\n")
    for listing in listings[: args.show]:
        if args.json:
            print(json.dumps(listing.to_dict(), ensure_ascii=False, indent=2))
        else:
            print(f"- {listing.title}")
            print(f"  {listing.price} € · {listing.mileage} km · {listing.year} · "
                  f"{listing.fuel} · {listing.location}")
            print(f"  {listing.url}")
    campi_vuoti = [
        campo for campo in ("price", "mileage", "year")
        if listings and all(getattr(l, campo) is None for l in listings)
    ]
    if campi_vuoti:
        print(f"\n⚠️  Campi sempre vuoti ({', '.join(campi_vuoti)}): il portale ha probabilmente "
              f"cambiato struttura, va aggiornato app/providers/{args.provider}.py")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    init_db()
    results = [run_search(args.search_id, notify=not args.no_notify)] if args.search_id else run_all(notify=not args.no_notify)
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0


def cmd_telegram(args: argparse.Namespace) -> int:
    try:
        send_message("🚗 <b>Carhunt</b>: messaggio di prova dal Raspberry.")
    except TelegramError as exc:
        print(f"errore: {exc}")
        return 1
    print("messaggio inviato")
    return 0


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(prog="carhunt", description="Utility a riga di comando di Carhunt")
    sub = parser.add_subparsers(dest="command", required=True)

    probe = sub.add_parser("probe", help="prova un portale e mostra gli annunci estratti")
    probe.add_argument("provider", choices=sorted(PROVIDERS))
    probe.add_argument("--make")
    probe.add_argument("--model")
    probe.add_argument("--keywords")
    probe.add_argument("--price-max", type=int)
    probe.add_argument("--km-max", type=int)
    probe.add_argument("--year-min", type=int)
    probe.add_argument("--region", help="solo Subito, es. lombardia")
    probe.add_argument("--limit", type=int, default=20)
    probe.add_argument("--show", type=int, default=5)
    probe.add_argument("--json", action="store_true")
    probe.set_defaults(func=cmd_probe)

    run = sub.add_parser("run", help="esegue le ricerche adesso")
    run.add_argument("--search-id", type=int)
    run.add_argument("--no-notify", action="store_true", help="non manda nulla su Telegram")
    run.set_defaults(func=cmd_run)

    telegram = sub.add_parser("telegram-test", help="manda un messaggio di prova")
    telegram.set_defaults(func=cmd_telegram)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
