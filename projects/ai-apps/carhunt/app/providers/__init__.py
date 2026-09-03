"""Registro dei portali supportati."""

from __future__ import annotations

from .autoscout24 import AutoScout24Provider
from .base import Criteria, Listing, Provider, normalize
from .demo import DemoProvider
from .subito import SubitoProvider

PROVIDERS: dict[str, Provider] = {
    provider.key: provider
    for provider in (SubitoProvider(), AutoScout24Provider(), DemoProvider())
}

DEFAULT_PROVIDERS = ["subito", "autoscout24"]


def get_providers(keys: list[str] | None) -> list[Provider]:
    selected = [k for k in (keys or DEFAULT_PROVIDERS) if k in PROVIDERS]
    return [PROVIDERS[k] for k in selected] or [PROVIDERS[k] for k in DEFAULT_PROVIDERS]


def provider_catalog() -> list[dict[str, str | bool]]:
    return [
        {"key": p.key, "label": p.label, "needs_network": p.needs_network}
        for p in PROVIDERS.values()
    ]


__all__ = [
    "Criteria",
    "Listing",
    "Provider",
    "PROVIDERS",
    "DEFAULT_PROVIDERS",
    "get_providers",
    "provider_catalog",
    "normalize",
]
