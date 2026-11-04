"""OpenStreetMap through the Overpass API (free, ODbL-licensed data; attribution is required and shown in the panel).

What it does: one Overpass query per run - "every object tagged as <preset> inside <city>" - then keeps the objects that carry
a name (and, by default, at least one way to reach the business). It reads only what the mapper wrote in the tags: website,
phone, e-mail, Instagram / Telegram / WhatsApp handles. Nothing is guessed.

Politeness: one query (two at most: the second only when the city has no usable "area" and the bounding box is used instead),
a ``[timeout:60]`` header, the honest User-Agent, a pause between requests, and an automatic move to the next mirror when a
server answers "at capacity" (502/503/504/429) or does not answer. The endpoint list is editable in the panel.
"""
from __future__ import annotations

import json

from apps.growth_engine.integrations import safe_http as sh

from . import categories
from .base import Candidate, ProviderContext, ProviderError, SearchProvider, SearchQuery, sanitize, split_multi
from .nominatim import validate_url

#: the main public server first; the two well-known public mirrors only when it is at capacity / silent (editable in the panel)
DEFAULT_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]
OSM_COPYRIGHT = "https://www.openstreetmap.org/copyright"
ATTRIBUTION = "© OpenStreetMap contributors (ODbL)"

_RELATION_AREA = 3_600_000_000
_WAY_AREA = 2_400_000_000

PHONE_TAGS = ("phone", "contact:phone", "mobile", "contact:mobile")
EMAIL_TAGS = ("email", "contact:email")
WEBSITE_TAGS = ("website", "contact:website", "url")
INSTAGRAM_TAGS = ("contact:instagram", "instagram")
TELEGRAM_TAGS = ("contact:telegram", "telegram")
WHATSAPP_TAGS = ("contact:whatsapp", "whatsapp")


def area_id(place: dict) -> int | None:
    """The Overpass area number of a Nominatim place, when it has one (a relation or a closed way)."""
    if place.get("osm_type") == "relation":
        return _RELATION_AREA + int(place["osm_id"])
    if place.get("osm_type") == "way":
        return _WAY_AREA + int(place["osm_id"])
    return None


def build_query(tags: list[tuple[str, str]], place: dict, limit: int, *, use_area: bool = True) -> str:
    """The Overpass QL text. Tags come from the validated presets; numbers are formatted by us, never pasted from input."""
    area = area_id(place) if use_area else None
    south, north, west, east = (float(x) for x in place["bbox"])
    scope = "(area.a)" if area else f"({south:.6f},{west:.6f},{north:.6f},{east:.6f})"
    lines = []
    for key, value in tags:
        selector = f'["{key}"]' if value == "*" else f'["{key}"="{value}"]'
        lines.append(f"  nwr{selector}{scope};")
    head = "[out:json][timeout:60];\n" + (f"area({area})->.a;\n" if area else "")
    return head + "(\n" + "\n".join(lines) + f"\n);\nout center tags {int(limit)};"


def _first(tags: dict, names: tuple[str, ...]) -> list[str]:
    out: list[str] = []
    for name in names:
        out.extend(split_multi(tags.get(name)))
    return out


def _address(tags: dict) -> str:
    parts = []
    street = tags.get("addr:street")
    if street:
        parts.append(street)
    if tags.get("addr:housenumber"):
        parts.append(f"پلاک {tags['addr:housenumber']}")
    if tags.get("addr:suburb"):
        parts.append(tags["addr:suburb"])
    return "، ".join(parts)[:400]


def parse_elements(elements: list, *, category_label: str, city: str) -> list[Candidate]:
    out: list[Candidate] = []
    for element in elements:
        if not isinstance(element, dict):
            continue
        tags = element.get("tags") or {}
        name = (tags.get("name:fa") or tags.get("name") or tags.get("brand") or tags.get("operator") or "").strip()
        etype, eid = element.get("type"), element.get("id")
        if not name or etype not in ("node", "way", "relation") or not eid:
            continue
        centre = element.get("center") or element
        websites = _first(tags, WEBSITE_TAGS)
        instagram = _first(tags, INSTAGRAM_TAGS)
        telegram = _first(tags, TELEGRAM_TAGS)
        candidate = Candidate(
            name=name, external_id=f"{etype}/{eid}", source_ref=f"osm:{etype}/{eid}",
            source_url=f"https://www.openstreetmap.org/{etype}/{eid}", category=category_label,
            city=(tags.get("addr:city") or city or "").strip(), address=_address(tags),
            phone=_first(tags, PHONE_TAGS), email=_first(tags, EMAIL_TAGS), website=websites[0] if websites else "",
            instagram=instagram[0] if instagram else "", telegram=telegram[0] if telegram else "",
            whatsapp=_first(tags, WHATSAPP_TAGS), lat=centre.get("lat"), lon=centre.get("lon"),
            extra={k: tags[k] for k in ("opening_hours", "shop", "craft") if tags.get(k)},
        )
        out.append(sanitize(candidate))
    return out


class OsmProvider(SearchProvider):
    key = "osm"
    label = "نقشهٔ آزاد (OpenStreetMap)"
    description = "فروشگاه‌های ثبت‌شده روی نقشه در یک شهر، با وب‌سایت، تلفن، ایمیل و پیج‌هایی که نقشه‌کش‌ها نوشته‌اند. رایگان و بی‌نیاز از کلید."
    kind = "map"
    attribution = ATTRIBUTION
    attribution_url = OSM_COPYRIGHT
    license_note = "داده‌های OpenStreetMap تحتِ پروانهٔ ODbL است؛ نام منبع باید کنارِ داده بماند (در پنل و در منبعِ هر لید دیده می‌شود)."
    max_results_limit = 500
    source_provider = "osm_overpass"

    def settings_schema(self) -> list[dict]:
        return [
            {"name": "overpass_endpoints", "label": "سرورهای Overpass (هر خط یک نشانی؛ به ترتیب امتحان می‌شود)", "type": "lines",
             "default": list(DEFAULT_ENDPOINTS), "help": "اگر سرورِ اصلی شلوغ بود، آینهٔ دیگری اینجا اضافه کنید."},
            {"name": "nominatim_url", "label": "سرویسِ جست‌وجوی شهر (Nominatim)", "type": "url", "default": "https://nominatim.openstreetmap.org/search",
             "help": "فقط برای تبدیلِ نامِ شهر به محدودهٔ نقشه؛ نتیجه ذخیره می‌شود و بیش از یک درخواست در ثانیه نمی‌رود."},
        ]

    def categories(self) -> list[dict]:
        return categories.listing()

    def endpoints(self, settings: dict) -> list[str]:
        raw = (settings or {}).get("overpass_endpoints") or DEFAULT_ENDPOINTS
        urls = [validate_url(str(u).strip()) for u in raw if str(u).strip()]
        return urls or list(DEFAULT_ENDPOINTS)

    # ------------------------------------------------------------------ fetch
    def fetch(self, query: SearchQuery, ctx: ProviderContext) -> list[Candidate]:
        tags = categories.tags_of(query.category)
        if tags is None:
            raise ProviderError("bad_category", "دسته‌ای که انتخاب کرده‌اید شناخته نشد.")
        label = categories.label_of(query.category)
        if ctx.geocode is None:
            raise ProviderError("no_geocoder", "جست‌وجوی شهر در دسترس نیست.")
        place = ctx.geocode(query.city, query.country)
        # ask for more than needed: many mapped shops carry no contact detail and are dropped below
        fetch_n = min(1000, max(100, query.max_results * 4))
        elements = self._query(ctx, tags, place, fetch_n, use_area=area_id(place) is not None)
        if not elements and area_id(place) is not None and not ctx.cancelled():
            elements = self._query(ctx, tags, place, fetch_n, use_area=False)  # the area did not exist for this city: bounding box
        candidates = parse_elements(elements, category_label=label, city=query.city)
        if query.require_contact:
            candidates = [c for c in candidates if c.has_contact]
        seen: set[str] = set()
        unique: list[Candidate] = []
        for c in candidates:  # the same shop may be mapped as a node and as a building: keep one
            sig = (c.website or "") + "|" + ",".join(c.phone) + "|" + c.name
            if sig in seen:
                continue
            seen.add(sig)
            unique.append(c)
        return unique[: query.max_results]

    def _query(self, ctx: ProviderContext, tags, place, limit, *, use_area: bool) -> list:
        if ctx.cancelled():
            raise ProviderError("cancelled", "متوقف شد.")
        ql = build_query(tags, place, limit, use_area=use_area)
        last = ""
        for endpoint in self.endpoints(ctx.settings):
            result = ctx.fetcher.get_api(endpoint, params={"data": ql}, delay=2.0, retries=1, backoff=(8.0,))
            if result.outcome == sh.OK and result.status == 200:
                try:
                    data = json.loads(result.text)
                except ValueError:
                    last = "پاسخِ نامفهوم"
                    continue
                remark = str(data.get("remark") or "") if isinstance(data, dict) else ""
                if remark and ("timed out" in remark or "out of memory" in remark or "runtime error" in remark):
                    raise ProviderError("query_too_big", "جست‌وجو برای این شهر و این دسته خیلی سنگین بود و سرورِ نقشه آن را رها کرد؛ دستهٔ دیگری یا شهرِ کوچک‌تری امتحان کنید.")
                if isinstance(data, dict) and isinstance(data.get("elements"), list):
                    return data["elements"]
                last = "پاسخِ غیرمنتظره"
                continue
            last = result.label if result.outcome != sh.OK else f"HTTP {result.status}"
        raise ProviderError(
            "service_busy",
            f"سرورِ نقشه الان شلوغ است یا جواب نمی‌دهد ({last}). چند دقیقه بعد دوباره امتحان کنید؛ کارِ شما با «ادامه» دوباره اجرا می‌شود.",
            retryable=True,
        )
