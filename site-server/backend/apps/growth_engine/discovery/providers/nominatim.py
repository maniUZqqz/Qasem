"""City lookup through Nominatim (OpenStreetMap's geocoder) - used ONLY to turn a city name into the area the map query
runs in. Usage policy followed: at most one request per second (``delay`` below), an honest User-Agent (``SafeFetcher``), the
result cached by the caller (``services/geo.py``), never used for bulk geocoding or autocomplete.
"""
from __future__ import annotations

import json
from urllib.parse import urlsplit

from apps.growth_engine.integrations import safe_http as sh

from .base import ProviderError

DEFAULT_URL = "https://nominatim.openstreetmap.org/search"
MIN_DELAY = 1.1  # seconds between two requests to the host: the policy says "no more than 1 per second"

#: OSM classes/types that mean "a settlement or an administrative area" - what a city name should resolve to
_PLACE_CLASSES = ("boundary", "place")


def validate_url(url: str) -> str:
    parts = urlsplit(url or "")
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ProviderError("bad_endpoint", "نشانیِ سرویسِ جست‌وجوی شهر معتبر نیست.")
    return url


def lookup(fetcher, city: str, country: str, *, url: str = DEFAULT_URL) -> dict:
    """The best match for ``city`` as ``{"name", "osm_type", "osm_id", "bbox": [south, north, west, east], "lat", "lon"}``.

    Raises ``ProviderError`` (``city_not_found`` / ``service_busy`` ...)."""
    city = (city or "").strip()
    if not city:
        raise ProviderError("city_required", "نامِ شهر را بنویسید.")
    params = {"q": city, "format": "jsonv2", "limit": "5", "accept-language": "fa,en", "addressdetails": "0"}
    if country:
        params["countrycodes"] = country.lower()
    result = fetcher.get_api(validate_url(url), params=params, delay=MIN_DELAY, retries=1, backoff=(5.0,))
    if result.outcome != sh.OK:
        raise ProviderError(
            "service_busy",
            f"سرویسِ جست‌وجوی شهرِ OpenStreetMap الان جواب نمی‌دهد ({result.label}). کمی بعد دوباره امتحان کنید.",
            retryable=True,
        )
    try:
        rows = json.loads(result.text)
    except ValueError as exc:
        raise ProviderError("service_busy", "پاسخِ سرویسِ جست‌وجوی شهر قابل‌خواندن نبود؛ کمی بعد دوباره امتحان کنید.", retryable=True) from exc
    if not isinstance(rows, list):
        raise ProviderError("service_busy", "پاسخِ سرویسِ جست‌وجوی شهر غیرمنتظره بود.", retryable=True)
    usable = [r for r in rows if isinstance(r, dict) and r.get("osm_type") and r.get("osm_id") and len(r.get("boundingbox") or []) == 4]
    if not usable:
        raise ProviderError("city_not_found", f"شهرِ «{city}» روی نقشه پیدا نشد؛ املای دیگری (فارسی یا انگلیسی) امتحان کنید.")
    # prefer a settlement / boundary over a street or a shop that happens to carry the same name
    usable.sort(key=lambda r: (r.get("category", r.get("class")) not in _PLACE_CLASSES, -float(r.get("importance") or 0)))
    best = usable[0]
    south, north, west, east = (float(x) for x in best["boundingbox"])
    return {
        "name": str(best.get("display_name") or best.get("name") or city)[:200],
        "osm_type": str(best["osm_type"]), "osm_id": int(best["osm_id"]),
        "bbox": [south, north, west, east], "lat": float(best.get("lat") or 0), "lon": float(best.get("lon") or 0),
    }
