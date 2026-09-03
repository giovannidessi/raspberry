"""Configurazione letta dalle variabili d'ambiente (vedi .env.example)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux aarch64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, "") or default)
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(float(os.getenv(name, "") or default))
    except ValueError:
        return default


def _env_bool(name: str, default: bool = False) -> bool:
    raw = (os.getenv(name) or "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "y", "on", "si", "sì"}


@dataclass
class Settings:
    db_path: str = field(default_factory=lambda: os.getenv("CARHUNT_DB", "data/carhunt.sqlite3"))
    telegram_bot_token: str = field(default_factory=lambda: (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip())
    telegram_chat_id: str = field(default_factory=lambda: (os.getenv("TELEGRAM_CHAT_ID") or "").strip())
    interval_minutes: int = field(default_factory=lambda: max(5, _env_int("CARHUNT_INTERVAL_MINUTES", 60)))
    run_on_start: bool = field(default_factory=lambda: _env_bool("CARHUNT_RUN_ON_START", False))
    request_delay: float = field(default_factory=lambda: _env_float("CARHUNT_REQUEST_DELAY", 1.5))
    http_timeout: float = field(default_factory=lambda: _env_float("CARHUNT_HTTP_TIMEOUT", 25.0))
    user_agent: str = field(default_factory=lambda: os.getenv("CARHUNT_USER_AGENT") or DEFAULT_USER_AGENT)
    max_results_per_provider: int = field(default_factory=lambda: _env_int("CARHUNT_MAX_RESULTS", 60))

    @property
    def telegram_enabled(self) -> bool:
        return bool(self.telegram_bot_token and self.telegram_chat_id)


settings = Settings()
