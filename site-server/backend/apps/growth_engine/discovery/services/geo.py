"""City -> map area, with a database cache so the same city is never asked of Nominatim twice within ``CACHE_DAYS``."""
from __future__ import annotations

from datetime import timedelta

from django.utils import timezone

from apps.growth_engine.core import normalization as nz

from ..models import GeoCache
from ..providers import nominatim

CACHE_DAYS = 90


def cache_key(city: str, country: str) -> str:
    return f"nominatim:{(country or '').lower()}:{nz.search_key(city)}"[:250]


def geocode(fetcher, city: str, country: str, *, url: str = nominatim.DEFAULT_URL) -> dict:
    """The place of ``city`` (see ``nominatim.lookup``) plus ``cached: bool``. Raises ``ProviderError``."""
    city = nz.normalize_text(city)
    key = cache_key(city, country)
    row = GeoCache.objects.filter(key=key).first()
    if row is not None and row.fetched_at > timezone.now() - timedelta(days=CACHE_DAYS) and row.value.get("bbox"):
        return {**row.value, "cached": True}
    place = nominatim.lookup(fetcher, city, country, url=url)
    GeoCache.objects.update_or_create(key=key, defaults={"value": place, "fetched_at": timezone.now()})
    return {**place, "cached": False}
