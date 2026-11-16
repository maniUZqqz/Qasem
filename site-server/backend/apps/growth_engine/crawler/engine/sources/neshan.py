"""Neshan (نشان) Search API - ONLY when the owner has put an API key into the Growth Engine's provider settings.

Neshan's place search needs a key that only the owner can get (https://platform.neshan.org). Without it this source is switched off and
the run says so; nothing is scraped from Neshan's or Balad's websites (their terms do not allow it and they offer no public listing).
With a key, one request per (term, city) asks ``GET https://api.neshan.org/v1/search?term=..&lat=..&lng=..`` with the key in the
``Api-Key`` header, and keeps the places' name, address, category and position (the API returns no phone numbers).

The key is stored through the existing provider-settings page (``ProviderConfig`` row «neshan», ``secrets.api_key``); this module
reads it, never writes it, and never logs it.
"""
from __future__ import annotations

import json

from apps.growth_engine.core import normalization as nz
from apps.growth_engine.integrations import safe_http as sh

from ... import presets
from ..candidates import Found
from .base import RetryLater, SourceContext, TaskFailed, TaskSpec

SOURCE = "neshan"
URL = "https://api.neshan.org/v1/search"
PROVIDER_KEY = "neshan"


def api_key() -> str:
    from apps.growth_engine.discovery.models import ProviderConfig

    row = ProviderConfig.objects.filter(provider=PROVIDER_KEY).first()
    return str((row.secrets or {}).get("api_key") or "") if row and row.enabled else ""


def plan(spec: dict) -> list[TaskSpec]:
    if not spec.get("sources", {}).get("neshan"):
        return []
    out: list[TaskSpec] = []
    for city in spec.get("cities", []):
        for t in spec.get("business_types", []):
            bt = presets.get_type(t)
            if bt and bt.terms_fa:
                out.append(TaskSpec(source=SOURCE, kind="search", key=f"neshan:{nz.search_key(city)}:{t}", priority=20,
                                    label=f"نشان: {bt.terms_fa[0]} · {city}", params={"city": city, "term": bt.terms_fa[0], "types": [t]}))
    return out


def execute(task, ctx: SourceContext) -> dict:
    key = ctx.secrets.get("neshan_api_key") or api_key()
    if not key:
        raise TaskFailed("کلیدِ API نشان وارد نشده (تنظیماتِ ارائه‌دهنده‌های کشف). این منبع بدونِ کلید کار نمی‌کند.")
    from apps.growth_engine.discovery.services import geo

    p = task.params
    try:
        place = geo.geocode(ctx.web.fetcher, p["city"], "IR")
    except Exception as exc:  # noqa: BLE001
        raise RetryLater(f"مرکزِ شهر پیدا نشد: {exc}", 600) from exc
    result = ctx.web.api(URL, {"term": p["term"], "lat": str(place["lat"]), "lng": str(place["lon"])}, ttl_hours=72, delay=1.5, headers={"Api-Key": key})
    if result.outcome != sh.OK or result.status != 200:
        if result.status in (401, 403):
            raise TaskFailed("کلیدِ نشان پذیرفته نشد.")
        raise RetryLater(f"سرویسِ نشان جواب نداد ({result.label})", 600)
    try:
        data = json.loads(result.text)
    except ValueError as exc:
        raise RetryLater("پاسخِ نشان قابل‌خواندن نبود", 600) from exc
    new = 0
    items = data.get("items") if isinstance(data, dict) else []
    for it in items or []:
        loc = it.get("location") or {}
        name = nz.normalize_text(str(it.get("title") or ""))
        if not name:
            continue
        _, created = ctx.emit(Found(
            name=name, source=SOURCE, ref=f"neshan:{nz.search_key(name)}:{loc.get('x')}:{loc.get('y')}"[:120], url="", types=list(p.get("types") or []), city=p["city"],
            address=str(it.get("address") or ""), lat=loc.get("y"), lon=loc.get("x"), category=str(it.get("category") or ""), signals={"neshan_region": it.get("region", "")},
        ))
        new += 1 if created else 0
    return {"items": len(items or []), "new_candidates": new}
