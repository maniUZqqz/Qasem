"""Discovery providers: ``registry.get("osm")`` -> a ``SearchProvider``."""
from __future__ import annotations

from .base import Candidate, ProviderContext, ProviderError, SearchProvider, SearchQuery
from .osm import OsmProvider
from .search_api import BraveProvider, GoogleCseProvider

_REGISTRY: dict[str, SearchProvider] = {}


def register(provider: SearchProvider) -> None:
    _REGISTRY[provider.key] = provider


def get(key: str) -> SearchProvider | None:
    return _REGISTRY.get(key)


def all_providers() -> list[SearchProvider]:
    return list(_REGISTRY.values())


for _p in (OsmProvider(), BraveProvider(), GoogleCseProvider()):
    register(_p)

__all__ = ["Candidate", "ProviderContext", "ProviderError", "SearchProvider", "SearchQuery", "all_providers", "get", "register"]
