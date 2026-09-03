"""Client HTTP condiviso dai provider, con rate limit gentile e retry minimo."""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

import httpx

from ..config import settings

log = logging.getLogger(__name__)

_last_call: dict[str, float] = {}
_lock = threading.Lock()


def _throttle(host: str) -> None:
    """Non piu' di una richiesta ogni CARHUNT_REQUEST_DELAY secondi per portale."""
    with _lock:
        last = _last_call.get(host, 0.0)
        wait = settings.request_delay - (time.monotonic() - last)
        if wait > 0:
            time.sleep(wait)
        _last_call[host] = time.monotonic()


def get(url: str, *, params: dict[str, Any] | None = None, headers: dict[str, str] | None = None,
        attempts: int = 3) -> httpx.Response:
    host = httpx.URL(url).host
    base_headers = {
        "User-Agent": settings.user_agent,
        "Accept-Language": "it-IT,it;q=0.9,en;q=0.6",
        "Accept": "text/html,application/json;q=0.9,*/*;q=0.8",
    }
    base_headers.update(headers or {})

    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        _throttle(host)
        try:
            with httpx.Client(timeout=settings.http_timeout, follow_redirects=True) as client:
                response = client.get(url, params=params, headers=base_headers)
            if response.status_code == 429 or response.status_code >= 500:
                raise httpx.HTTPStatusError(
                    f"HTTP {response.status_code}", request=response.request, response=response
                )
            response.raise_for_status()
            return response
        except Exception as exc:  # noqa: BLE001 - vogliamo ritentare su qualunque errore di rete
            last_error = exc
            log.warning("richiesta a %s fallita (tentativo %s/%s): %s", host, attempt, attempts, exc)
            if attempt < attempts:
                time.sleep(2 ** attempt)
    assert last_error is not None
    raise last_error
