"""Public business directories (listing sites) as a source - only ones whose robots.txt allows it, only their public listing data.

Two adapters:

* ``badanfit`` - badanfit.ir's public gym listing (robots.txt: «Allow: /»; checked 2026-11-16). A list page
  ``gym-hub.php?city=<slug>&type=<fitness|bodybuilding|crossfit|yoga|pilates>[&area=<north|south|east>]`` holds about 30 cards
  (name, address, rating, phone); a detail page adds the coordinates and the opening hours in schema.org JSON-LD. The adapter reads the cards (one
  request gives ~30 businesses with phones) and, as budget allows, the detail pages.
* ``generic`` - any list page the owner gives (``spec.directory_urls``) or a search result points to: the links that repeat the same
  «shape» (e.g. ``/gym/NNN``) are the detail pages; each detail page is read through its JSON-LD (LocalBusiness and its subtypes) and
  the common contact parser. Every page is fetched through the robots.txt check; a site that disallows is skipped and said so.

Only business facts are taken (name, address, phone, site, social page, hours, rating). A directory's own footer phone / e-mail would
otherwise be attached to every business, so ``runner.strip_boilerplate`` removes any value that appears on four or more candidates
of one directory.
"""
from __future__ import annotations

import re
from urllib.parse import parse_qs, urljoin, urlsplit

from bs4 import BeautifulSoup

from apps.growth_engine.core import normalization as nz
from apps.growth_engine.extraction.services import parser as contact_parser
from apps.growth_engine.integrations import safe_http as sh

from ... import presets
from .. import extras, textnorm
from ..candidates import Found
from .base import SourceContext, TaskFailed, TaskSpec

SOURCE = "directory"
BADANFIT = "https://badanfit.ir"
BADANFIT_CITIES = {
    "تهران": "tehran", "اصفهان": "isfahan", "مشهد": "mashhad", "شیراز": "shiraz", "تبریز": "tabriz", "کرج": "karaj", "قم": "qom", "اهواز": "ahvaz",
    "رشت": "rasht", "همدان": "hamedan", "کرمان": "kerman", "یزد": "yazd", "ارومیه": "urmia", "اراک": "arak", "ساری": "sari", "قزوین": "qazvin",
}
BADANFIT_TYPES = {
    "gym": ["fitness", "bodybuilding", "crossfit"], "sports_club": ["fitness"], "yoga_pilates": ["yoga", "pilates"], "personal_trainer": ["bodybuilding"],
}
BADANFIT_AREAS = {"tehran": ["north", "south", "east"]}
_LOCAL_BUSINESS = re.compile(r"(?:LocalBusiness|Gym|ExerciseGym|SportsActivityLocation|HealthClub|Restaurant|CafeOrCoffeeShop|Store|Dentist|BeautySalon|HairSalon|Hotel|Organization|MedicalClinic|FoodEstablishment)", re.I)
_SHAPE = re.compile(r"\d+")


def _digits(s: str) -> str:
    return nz.to_ascii_digits(s or "")


# --------------------------------------------------------------------------- planning


def plan(spec: dict) -> list[TaskSpec]:
    out: list[TaskSpec] = []
    limit = int((spec.get("budget") or {}).get("max_directory_pages") or 12)
    if spec.get("sources", {}).get("directory", True):
        for city in spec.get("cities", []):
            slug = BADANFIT_CITIES.get(nz.normalize_text(city))
            if not slug:
                continue
            kinds: list[str] = []
            for t in spec.get("business_types", []):
                for k in BADANFIT_TYPES.get(t, []):
                    if k not in kinds:
                        kinds.append(k)
            for k in kinds:
                out.append(_list_task("badanfit", city, slug, k, ""))
                for area in BADANFIT_AREAS.get(slug, []):
                    out.append(_list_task("badanfit", city, slug, k, area))
    out = out[:limit]
    for url in spec.get("directory_urls") or []:
        url = nz.normalize_text(str(url))
        if url:
            out.append(TaskSpec(source=SOURCE, kind="list", key=f"dir:{url[:300]}", priority=28, label=f"فهرستِ دلخواه: {urlsplit(url).hostname}",
                                params={"url": url, "directory": "generic", "types": spec.get("business_types", []), "city": (spec.get("cities") or [""])[0]}))
    return out


def _list_task(directory: str, city: str, slug: str, kind: str, area: str) -> TaskSpec:
    url = f"{BADANFIT}/gym-hub.php?city={slug}&type={kind}" + (f"&area={area}" if area else "")
    return TaskSpec(source=SOURCE, kind="list", key=f"dir:{url}", priority=24, label=f"بدن‌فیت: {city} · {kind}" + (f" · {area}" if area else ""),
                    params={"url": url, "directory": directory, "city": city, "dtype": kind, "types": _types_for_badan(kind)})


def _types_for_badan(kind: str) -> list[str]:
    return [t for t, kinds in BADANFIT_TYPES.items() if kind in kinds]


# --------------------------------------------------------------------------- reading list pages


def parse_badanfit_cards(html: str, base: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    cards = []
    for a in soup.select("a.gym-card"):
        href = a.get("href") or ""
        name = a.select_one(".gym-card-name")
        if not name:
            continue
        m = re.search(r"id=(\d+)", href)
        phone = a.select_one(".gym-card-phone")
        rating = a.select_one(".gym-card-rating")
        r = re.search(r"(\d(?:\.\d)?)", _digits(rating.get_text(" ", strip=True))) if rating else None
        cards.append({
            "id": m.group(1) if m else "", "url": urljoin(base + "/", href), "name": nz.normalize_text(name.get_text(" ", strip=True)),
            "address": nz.normalize_text(a.select_one(".gym-card-address").get_text(" ", strip=True)) if a.select_one(".gym-card-address") else "",
            "phone": nz.normalize_text(phone.get_text(" ", strip=True)) if phone else "", "rating": float(r.group(1)) if r else None,
        })
    return cards


def detail_links(html: str, page_url: str) -> list[str]:
    """Links of a list page that look like detail pages: the most common path «shape» (digits -> N) of same-host links, >= 5 of them."""
    soup = BeautifulSoup(html, "html.parser")
    host = textnorm.domain_key(page_url)
    shapes: dict[str, list[str]] = {}
    for a in soup.find_all("a", href=True):
        url = urljoin(page_url, a["href"]).split("#")[0]
        if textnorm.domain_key(url) != host or contact_parser._usable_href(a["href"]) is False:
            continue
        parts = urlsplit(url)
        if not parts.path or parts.path == "/" or parts.path.lower().endswith(contact_parser._SKIP_EXTENSIONS):
            continue
        text = a.get_text(" ", strip=True)
        if not 3 <= len(text) <= 120:
            continue
        shape = _SHAPE.sub("N", parts.path) + ("?" + ",".join(sorted(parse_qs(parts.query))) if parts.query else "")
        shapes.setdefault(shape, [])
        if url not in shapes[shape]:
            shapes[shape].append(url)
    best = [urls for urls in shapes.values() if len(urls) >= 5]
    best.sort(key=len, reverse=True)
    return best[0] if best else []


def _geo_of(node: dict) -> tuple[float | None, float | None]:
    geo = node.get("geo") if isinstance(node.get("geo"), dict) else {}
    try:
        return float(geo.get("latitude")), float(geo.get("longitude"))
    except (TypeError, ValueError):
        return None, None


def _address_of(node: dict) -> tuple[str, str]:
    addr = node.get("address")
    if isinstance(addr, dict):
        return nz.normalize_text(str(addr.get("streetAddress") or "")), nz.normalize_text(str(addr.get("addressLocality") or ""))
    return (nz.normalize_text(addr), "") if isinstance(addr, str) else ("", "")


def parse_detail(html: str, url: str, *, directory: str, types: list[str], city: str) -> Found | None:
    """One business from a detail page: JSON-LD first, the contact parser for what JSON-LD lacks."""
    soup = BeautifulSoup(html, "html.parser")
    node = next((n for n in extras._json_ld(soup) if _LOCAL_BUSINESS.search(str(n.get("@type") or "")) and n.get("name")), None)
    meta = extras.page_meta(html)
    page = contact_parser.parse_page(html, url, "contact")
    phones = [f.value for f in page.findings if f.field == "phone" and f.confidence >= 75]
    emails = [f.value for f in page.findings if f.field == "email" and f.confidence >= 80]
    social = {f.field: f.value for f in page.findings if f.field in ("instagram", "telegram", "whatsapp")}
    name = ""
    lat = lon = None
    street = loc = hours = ""
    website = ""
    rating = None
    if node:
        name = nz.normalize_text(str(node.get("name")))
        lat, lon = _geo_of(node)
        street, loc = _address_of(node)
        if node.get("telephone"):
            phones = [str(node["telephone"]), *phones]
        if node.get("email"):
            emails = [str(node["email"]), *emails]
        site = node.get("url")
        website = site if isinstance(site, str) and textnorm.domain_key(site) and textnorm.domain_key(site) != textnorm.domain_key(url) else ""
        hours = extras.hours_from_jsonld([node])
        agg = node.get("aggregateRating")
        if isinstance(agg, dict):
            try:
                rating = float(agg.get("ratingValue"))
            except (TypeError, ValueError):
                rating = None
    if not name:
        name = meta["h1"] or meta["site_name"] or (meta["title"].split("|")[0].strip() if meta["title"] else "")
    if not name:
        return None
    text = extras.visible_text(html)
    if not hours:
        hours = extras.find_hours(html, text)
    if rating is None:
        rating = extras.find_rating(text)
    ref_id = (re.search(r"id=(\d+)", url) or re.search(r"/(\d+)(?:/|$)", url) or re.search(r"/([^/]+)/?$", url))
    return Found(
        name=name, source=SOURCE, ref=f"directory:{directory}:{ref_id.group(1) if ref_id else textnorm.domain_key(url)}"[:120], url=url,
        types=list(types), city=loc or city, address=street, lat=lat, lon=lon, phones=phones, emails=emails, website=website,
        instagram=social.get("instagram", ""), telegram=social.get("telegram", ""), whatsapp=[social["whatsapp"]] if social.get("whatsapp") else [],
        hours=hours, rating=rating, signals={"directory": directory, "dir_host": urlsplit(url).hostname or ""},
    )


# --------------------------------------------------------------------------- running a task


def execute(task, ctx: SourceContext) -> dict:
    if task.kind == "list":
        return _list(task, ctx)
    if task.kind == "detail":
        return _detail(task, ctx)
    raise TaskFailed("نوعِ کارِ فهرست شناخته نشد.")


def _fetch(ctx: SourceContext, url: str):
    result = ctx.web.page(url)
    if result.outcome in (sh.ROBOTS_BLOCKED, sh.ROBOTS_UNAVAILABLE):
        ctx.log("warn", f"{urlsplit(url).hostname}: robots.txt اجازهٔ خواندن نمی‌دهد؛ رد شد.")
        raise TaskFailed("robots.txt سایت اجازه نمی‌دهد")
    if not result.ok:
        raise TaskFailed(result.label)
    return result


def _list(task, ctx: SourceContext) -> dict:
    p = task.params
    url = p["url"]
    result = _fetch(ctx, url)
    types, city, directory = list(p.get("types") or []), p.get("city", ""), p.get("directory", "generic")
    new = 0
    details: list[TaskSpec] = []
    max_details = ctx.budget("max_directory_details", 120)
    if directory == "badanfit":
        cards = parse_badanfit_cards(result.text, BADANFIT)
        for c in cards:
            _, created = ctx.emit(Found(
                name=c["name"], source=SOURCE, ref=f"directory:badanfit:{c['id']}", url=c["url"], types=types, city=city, address=c["address"],
                phones=[c["phone"]] if c["phone"] else [], rating=c["rating"], signals={"directory": "badanfit", "dir_host": "badanfit.ir"},
            ))
            new += 1 if created else 0
            if c["id"] and created:
                details.append(TaskSpec(source=SOURCE, kind="detail", key=f"dir:{c['url']}", priority=60, label=f"بدن‌فیت: {c['name'][:60]}",
                                        params={"url": c["url"], "directory": "badanfit", "types": types, "city": city}, stage="discover"))
        ctx.add_tasks(details[:max_details])
        return {"cards": len(cards), "new_candidates": new, "detail_tasks": min(len(details), max_details)}
    links = detail_links(result.text, url)
    for link in links[:max_details]:
        details.append(TaskSpec(source=SOURCE, kind="detail", key=f"dir:{link}", priority=60, label=f"صفحهٔ فهرست: {urlsplit(link).path[:60]}",
                                params={"url": link, "directory": textnorm.domain_key(url) or "generic", "types": types, "city": city}))
    ctx.add_tasks(details)
    return {"links": len(links), "detail_tasks": len(details), "new_candidates": 0}


def _detail(task, ctx: SourceContext) -> dict:
    p = task.params
    result = _fetch(ctx, p["url"])
    found = parse_detail(result.text, result.final_url or p["url"], directory=p.get("directory", "generic"), types=list(p.get("types") or []), city=p.get("city", ""))
    if found is None:
        return {"found": False}
    _, created = ctx.emit(found)
    return {"found": True, "new_candidates": 1 if created else 0, "has_geo": found.lat is not None, "has_hours": bool(found.hours)}
