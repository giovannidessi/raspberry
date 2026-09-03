"""Invio dei messaggi Telegram."""

from __future__ import annotations

import html
import logging

import httpx

from .config import settings
from .providers.base import Listing
from .scoring import Evaluation, it_num

log = logging.getLogger(__name__)

API = "https://api.telegram.org/bot{token}/sendMessage"

VERDICT_ICON = {
    "Ottimo affare": "🟢",
    "Buon affare": "🟢",
    "Da valutare": "🟡",
    "Poco interessante": "🟠",
    "Da scartare": "🔴",
}


class TelegramError(RuntimeError):
    pass


def send_message(text: str, chat_id: str | None = None, *, disable_preview: bool = False) -> dict:
    token = settings.telegram_bot_token
    target = (chat_id or settings.telegram_chat_id or "").strip()
    if not token or not target:
        raise TelegramError(
            "Telegram non configurato: imposta TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID nel file .env"
        )
    payload = {
        "chat_id": target,
        "text": text[:4096],
        "parse_mode": "HTML",
        "disable_web_page_preview": disable_preview,
    }
    with httpx.Client(timeout=settings.http_timeout) as client:
        response = client.post(API.format(token=token), json=payload)
    data = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
    if response.status_code != 200 or not data.get("ok", False):
        raise TelegramError(f"Telegram ha risposto {response.status_code}: {data.get('description') or response.text[:200]}")
    return data


def _esc(value: object) -> str:
    return html.escape(str(value or ""), quote=False)


def format_listing(listing: Listing, evaluation: Evaluation, *, search_name: str, reason: str = "nuovo",
                   old_price: float | None = None) -> str:
    """Messaggio HTML per un singolo annuncio."""
    icon = VERDICT_ICON.get(evaluation.verdict, "🚗")
    header = "🆕 Nuovo annuncio" if reason == "nuovo" else "📉 Ribasso di prezzo"

    lines = [
        f"<b>{header}</b> · <i>{_esc(search_name)}</i>",
        f"{icon} <b>{_esc(listing.title)}</b>",
    ]

    price_line = f"💶 <b>{it_num(listing.price)} €</b>"
    if reason == "ribasso" and old_price:
        drop = old_price - (listing.price or 0)
        price_line += f" (era {it_num(old_price)} €, <b>-{it_num(drop)} €</b>)"
    lines.append(price_line)

    specs = []
    if listing.year:
        specs.append(str(listing.year))
    if listing.mileage is not None:
        specs.append(f"{it_num(listing.mileage)} km")
    if listing.fuel:
        specs.append(_esc(listing.fuel))
    if listing.gearbox:
        specs.append(_esc(listing.gearbox))
    if listing.power_hp:
        specs.append(f"{listing.power_hp} CV")
    if specs:
        lines.append("🔧 " + " · ".join(specs))

    where = " · ".join(p for p in (_esc(listing.location), _esc(listing.province)) if p)
    if where:
        lines.append(f"📍 {where}")

    lines.append(f"⭐ Punteggio <b>{evaluation.score:.0f}/100</b> — {_esc(evaluation.verdict)}")
    if evaluation.comment:
        lines.append("")
        lines.append(_esc(evaluation.comment))
    if listing.url:
        lines.append("")
        lines.append(f'🔗 <a href="{_esc(listing.url)}">Apri l\'annuncio su {_esc(listing.provider)}</a>')
    return "\n".join(lines)


def format_summary(search_name: str, total: int, top: list[tuple[Listing, Evaluation]]) -> str:
    """Riepilogo del primo giro: evita di sommergere di notifiche al primo avvio."""
    lines = [
        f"✅ <b>Ricerca attivata:</b> <i>{_esc(search_name)}</i>",
        f"Ho trovato <b>{total}</b> annunci già online: da adesso ti avviso solo sulle novità.",
    ]
    if top:
        lines.append("")
        lines.append("<b>I migliori di oggi:</b>")
        for listing, evaluation in top:
            link = f'<a href="{_esc(listing.url)}">{_esc(listing.title)}</a>' if listing.url else _esc(listing.title)
            lines.append(f"• {evaluation.score:.0f}/100 — {link} — {it_num(listing.price)} €")
    return "\n".join(lines)


def safe_send(text: str, chat_id: str | None = None) -> bool:
    """Non fa mai fallire il giro di ricerca per colpa di Telegram."""
    try:
        send_message(text, chat_id)
        return True
    except Exception as exc:  # noqa: BLE001
        log.warning("invio Telegram fallito: %s", exc)
        return False
