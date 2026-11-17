"""OpenStreetMap through Overpass (tags per business type) with Nominatim as the fallback.

Why it is the backbone: it is free, its data licence (ODbL) allows this use, and a mapped business carries a real name, a real
position and - when the mapper wrote them - phone, website, Instagram and opening hours. Nothing is guessed from it.

* One Overpass query per (city, group of up to ``TYPES_PER_QUERY`` business types): «every object tagged as one of these inside the
  city's area». The tags come from ``presets`` (validated: a preset can never smuggle anything into the query language).
* The public Overpass servers are often «at capacity» (checked from Iran on 2026-11-16: the main server answered after 33 s, two
  mirrors did not answer at all). So: a list of mirrors tried in turn, long read timeouts, the answer **cached** for three days,
  and a busy answer is a ``RetryLater`` (the task goes back to the queue, 3 attempts) - never a crash.
* When every mirror stays busy the task falls back to Nominatim's own text search (``q=<type> <city>``, 40 places a call, with
  ``extratags`` = the phone / website tags), so a run still gets the best-known places.
"""
from __future__ import annotations

import json

from apps.growth_engine.core import normalization as nz
from apps.growth_engine.discovery.providers import nominatim
from apps.growth_engine.discovery.providers.base import ProviderError
from apps.growth_engine.discovery.services import geo
from apps.growth_engine.integrations import safe_http as sh

from .. import extras, textnorm
from ..candidates import Found
from ... import presets
from .base import RetryLater, SourceContext, TaskFailed, TaskSpec

SOURCE = "osm"
TYPES_PER_QUERY = 6
ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]
ATTRIBUTION = "© OpenStreetMap contributors (ODbL)"
_RELATION_AREA = 3_600_000_000
_WAY_AREA = 2_400_000_000
OVERPASS_TIMEOUT = 90

PHONE_TAGS = ("phone", "contact:phone", "mobile", "contact:mobile")
EMAIL_TAGS = ("email", "contact:email")
WEBSITE_TAGS = ("website", "contact:website", "url")
INSTAGRAM_TAGS = ("contact:instagram", "instagram")
TELEGRAM_TAGS = ("contact:telegram", "telegram")
WHATSAPP_TAGS = ("contact:whatsapp", "whatsapp")


# --------------------------------------------------------------------------- planning


def plan(spec: dict) -> list[TaskSpec]:
    types = [t for t in spec.get("business_types", []) if presets.get_type(t) and presets.get_type(t).osm]
    if not types:
        return []
    out: list[TaskSpec] = []
    for city in spec.get("cities", []):
        city = nz.normalize_text(city)
        if not city:
            continue
        for i in range(0, len(types), TYPES_PER_QUERY):
            group = types[i:i + TYPES_PER_QUERY]
            out.append(TaskSpec(
                source=SOURCE, kind="area", key=f"osm:{nz.search_key(city)}:{','.join(group)}", priority=10,
                label=f"نقشه: {city} · " + "، ".join(presets.get_type(t).fa for t in group),
                params={"city": city, "types": group, "country": spec.get("country") or "IR"},
            ))
    return out


# --------------------------------------------------------------------------- the query


def area_id(place: dict) -> int | None:
    if place.get("osm_type") == "relation":
        return _RELATION_AREA + int(place["osm_id"])
    if place.get("osm_type") == "way":
        return _WAY_AREA + int(place["osm_id"])
    return None


def selectors_for(types: list[str]) -> list[tuple[str, str]]:
    seen: list[tuple[str, str]] = []
    for key in types:
        bt = presets.get_type(key)
        if bt is None:
            continue
        for pair in bt.osm_selectors:
            if pair not in seen:
                seen.append(pair)
    return seen


def build_query(selectors: list[tuple[str, str]], place: dict, limit: int, *, use_area: bool = True) -> str:
    area = area_id(place) if use_area else None
    south, north, west, east = (float(x) for x in place["bbox"])
    scope = "(area.a)" if area else f"({south:.6f},{west:.6f},{north:.6f},{east:.6f})"
    lines = []
    for k, v in selectors:
        sel = f'["{k}"]' if v == "*" else f'["{k}"="{v}"]'
        lines.append(f"  nwr{sel}{scope};")
    head = f"[out:json][timeout:{OVERPASS_TIMEOUT}];\n" + (f"area({area})->.a;\n" if area else "")
    return head + "(\n" + "\n".join(lines) + f"\n);\nout center tags {int(limit)};"


def _first(tags: dict, names: tuple[str, ...]) -> list[str]:
    out: list[str] = []
    for name in names:
        out.extend(nz.split_multi(tags.get(name)))
    return out


def _address(tags: dict) -> str:
    if tags.get("addr:full"):
        return nz.normalize_text(tags["addr:full"])[:400]
    parts = []
    for key in ("addr:street", "addr:suburb"):
        if tags.get(key):
            parts.append(tags[key])
    if tags.get("addr:housenumber"):
        parts.insert(1 if parts else 0, f"پلاک {tags['addr:housenumber']}")
    return "، ".join(parts)[:400]


def parse_elements(elements: list, *, city: str, allowed: list[str]) -> list[Found]:
    out: list[Found] = []
    for el in elements:
        if not isinstance(el, dict):
            continue
        tags = el.get("tags") or {}
        name = (tags.get("name:fa") or tags.get("name") or tags.get("brand") or tags.get("operator") or tags.get("name:en") or "").strip()
        etype, eid = el.get("type"), el.get("id")
        if not name or etype not in ("node", "way", "relation") or not eid:
            continue
        centre = el.get("center") or el
        websites = _first(tags, WEBSITE_TAGS)
        instagram = _first(tags, INSTAGRAM_TAGS)
        telegram = _first(tags, TELEGRAM_TAGS)
        types = presets.type_for_osm_tags(tags, allowed)
        label = presets.get_type(types[0]).fa if types else ""
        out.append(Found(
            name=name, source=SOURCE, ref=f"osm:{etype}/{eid}", url=f"https://www.openstreetmap.org/{etype}/{eid}",
            category=label, types=types, city=(tags.get("addr:city") or city or "").strip(), city_src="evidence" if tags.get("addr:city") else "", address=_address(tags),
            lat=centre.get("lat"), lon=centre.get("lon"), phones=_first(tags, PHONE_TAGS), emails=_first(tags, EMAIL_TAGS),
            whatsapp=_first(tags, WHATSAPP_TAGS), website=websites[0] if websites else "", instagram=instagram[0] if instagram else "",
            telegram=telegram[0] if telegram else "", hours=extras.osm_hours_fa(str(tags.get("opening_hours") or "")),
            signals={"osm_tags": {k: str(tags[k])[:60] for k in ("leisure", "amenity", "shop", "sport", "cuisine", "craft", "tourism", "office", "healthcare") if tags.get(k)}},
        ))
    return out


# --------------------------------------------------------------------------- running a task


def _geocode(ctx: SourceContext, city: str, country: str) -> dict:
    try:
        ctx.web.budget.check()
        return geo.geocode(ctx.web.fetcher, city, country)
    except ProviderError as exc:
        if exc.retryable:
            raise RetryLater(exc.message, 300) from exc
        raise TaskFailed(exc.message) from exc


def _overpass(ctx: SourceContext, query: str) -> list:
    last = ""
    for endpoint in ENDPOINTS:
        if ctx.stop():
            raise RetryLater("متوقف شد.", 5)
        result = ctx.web.api(endpoint, {"data": query}, ttl_hours=72, delay=2.0, retries=0, max_bytes=30_000_000)
        if result.outcome == sh.OK and result.status == 200:
            try:
                data = json.loads(result.text)
            except ValueError:
                last = "پاسخِ نامفهوم"
                continue
            remark = str(data.get("remark") or "") if isinstance(data, dict) else ""
            if remark and ("timed out" in remark or "out of memory" in remark or "runtime error" in remark):
                last = "سرورِ نقشه جست‌وجو را رها کرد (سنگین بود)"
                continue
            if isinstance(data, dict) and isinstance(data.get("elements"), list):
                ctx.log("info", f"نقشه: {len(data['elements'])} مورد از {endpoint.split('/')[2]}")
                return data["elements"]
            last = "پاسخِ غیرمنتظره"
            continue
        last = result.label if result.outcome != sh.OK else f"HTTP {result.status}"
        ctx.log("warn", f"سرورِ نقشه {endpoint.split('/')[2]} جواب نداد ({last}).")
    raise RetryLater(f"همهٔ سرورهای نقشه شلوغ‌اند یا جواب ندادند ({last}).", 600)


def execute(task, ctx: SourceContext) -> dict:
    p = task.params
    if task.kind == "nominatim":
        return _execute_nominatim(task, ctx)
    city, types, country = p["city"], list(p.get("types") or []), p.get("country") or "IR"
    place = _geocode(ctx, city, country)
    limit = min(2500, max(300, int(ctx.spec.get("max_results") or 300) * 4))
    selectors = selectors_for(types)
    if not selectors:
        raise TaskFailed("برای این نوعِ کسب‌وکار برچسبِ نقشه تعریف نشده.")
    try:
        elements = _overpass(ctx, build_query(selectors, place, limit, use_area=area_id(place) is not None))
        if not elements and area_id(place) is not None:
            elements = _overpass(ctx, build_query(selectors, place, limit, use_area=False))
    except RetryLater as busy:
        if task.attempts >= 2:  # the third time: take what Nominatim knows instead of nothing
            ctx.log("warn", "سرورهای نقشه شلوغ ماند؛ از جست‌وجوی متنیِ نقشه استفاده می‌شود (نتیجهٔ کمتر).")
            ctx.add_tasks([TaskSpec(source=SOURCE, kind="nominatim", key=f"osm-nom:{nz.search_key(city)}:{','.join(types)}", priority=12,
                                    label=f"نقشه (جست‌وجوی متنی): {city}", params={"city": city, "types": types, "country": country})])
            return {"fallback": "nominatim", "reason": busy.message}
        raise
    found = parse_elements(elements, city=city, allowed=types)
    new = 0
    for f in found:
        _, created = ctx.emit(f)
        new += 1 if created else 0
    return {"elements": len(elements), "named": len(found), "new_candidates": new, "attribution": ATTRIBUTION}


def _execute_nominatim(task, ctx: SourceContext) -> dict:
    p = task.params
    city, types, country = p["city"], list(p.get("types") or []), p.get("country") or "IR"
    place = _geocode(ctx, city, country)
    new = total = 0
    for key in types[:4]:
        bt = presets.get_type(key)
        if bt is None or not bt.terms_fa:
            continue
        if ctx.stop():
            break
        params = {
            "q": f"{bt.terms_fa[0]} {city}", "format": "jsonv2", "limit": "40", "accept-language": "fa,en", "extratags": "1", "namedetails": "1",
            "countrycodes": country.lower(), "viewbox": f"{place['bbox'][2]},{place['bbox'][1]},{place['bbox'][3]},{place['bbox'][0]}", "bounded": "1",
        }
        result = ctx.web.api(nominatim.DEFAULT_URL, params, ttl_hours=72, delay=nominatim.MIN_DELAY + 0.4, retries=1)
        if result.outcome != sh.OK:
            raise RetryLater(f"سرویسِ جست‌وجوی نقشه جواب نداد ({result.label}).", 600)
        try:
            rows = json.loads(result.text)
        except ValueError:
            continue
        for r in rows if isinstance(rows, list) else []:
            tags = {**(r.get("extratags") or {}), **{k: v for k, v in [(r.get("category"), r.get("type"))] if k}}
            name = (r.get("namedetails") or {}).get("name:fa") or (r.get("namedetails") or {}).get("name") or r.get("name") or ""
            if not name:
                continue
            total += 1
            websites = _first(tags, WEBSITE_TAGS)
            types_hit = presets.type_for_osm_tags(tags, types) or [key]
            parts = [p.strip() for p in str(r.get("display_name") or "").split(",")]
            _, created = ctx.emit(Found(
                name=name, source=SOURCE, ref=f"osm:{r.get('osm_type')}/{r.get('osm_id')}", url=f"https://www.openstreetmap.org/{r.get('osm_type')}/{r.get('osm_id')}",
                category=bt.fa, types=types_hit, city=city, address="، ".join(parts[1:3]),
                lat=_f(r.get("lat")), lon=_f(r.get("lon")), phones=_first(tags, PHONE_TAGS), emails=_first(tags, EMAIL_TAGS),
                website=websites[0] if websites else "", instagram=(_first(tags, INSTAGRAM_TAGS) or [""])[0], hours=extras.osm_hours_fa(str(tags.get("opening_hours") or "")),
                signals={"via": "nominatim"},
            ))
            new += 1 if created else 0
    return {"places": total, "new_candidates": new, "attribution": ATTRIBUTION}


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None
