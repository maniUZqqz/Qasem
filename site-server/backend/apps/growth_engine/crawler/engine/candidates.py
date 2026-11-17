"""Candidates: what the sources found, normalised and merged across sources (dedupe: name + phone + domain + geo).

``Found`` is the one shape every source returns. ``add_found`` puts it into the run's ``CrawlCandidate`` table and decides whether it
is a business already seen in this run:

  strong identities   the same OpenStreetMap object / phone number / website domain / Instagram handle / e-mail / Telegram handle
  name + place        the same name (after ``name_core``; two names that differ in a NUMBER are two businesses) AND either within
                      ``GEO_SAME_M`` metres, or - when one of them has no coordinates - not in different cities.
                      Two branches of a chain 5 km apart stay two candidates.

Two descriptions that CANNOT be one business never merge, whatever they share: an address in Isfahan and one in Tehran, two map
positions further apart than ``place.CONFLICT_KM`` (``place.conflicts``). A business whose own evidence (address, map position, landline area
code) puts it outside the cities the mission asked for is not taken at all (``add_found`` returns ``(None, False)``).

A merge never loses information: lists are united, empty fields are filled, and every source stays in ``sources``. Every contact value also
remembers the page it was read from (``signals['prov']``), so a lead's contact point names ITS page, not the first source of the business.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from django.db import IntegrityError, transaction

from apps.growth_engine.core import normalization as nz
from apps.growth_engine.leads.choices import ContactKind
from apps.growth_engine.leads.services.drafts import normalize_contact

from ..models import CandidateKey, CrawlCandidate, CrawlRun
from . import contactrules, place, textnorm

GEO_SAME_M = 350
NAME_SIMILAR = 0.9
MAX_PHONES = 6
MAX_EMAILS = 4
MAX_PROV = 60
#: how sure each kind of source is about the contact values it gives (the confidence stored on a lead's contact point) and what to call it
SOURCE_CONF = {"osm": 80, "directory": 75, "search": 55, "website": 70, "instagram": 70, "neshan": 70}
SOURCE_EVIDENCE = {"osm": "برچسبِ نقشهٔ آزاد (OpenStreetMap)", "directory": "فهرستِ عمومیِ کسب‌وکار", "search": "نتیجهٔ جست‌وجوی وب", "website": "سایتِ خودِ کسب‌وکار",
                   "instagram": "بیوِ پیجِ اینستاگرام", "neshan": "نشان"}


@dataclass
class Found:
    """One business as one source described it (nothing invented: a field the source did not give stays empty)."""

    name: str
    source: str  # osm | search | directory | website | instagram | neshan
    ref: str = ""  # osm:node/1 · directory:badanfit:4364 · search:bing:host · ig:handle
    url: str = ""  # the page it came from
    category: str = ""
    types: list[str] = field(default_factory=list)
    city: str = ""
    city_src: str = ""  # "evidence" = the source's own data says this city (an address, a listing of that city); "" = only what the mission asked for
    address: str = ""
    lat: float | None = None
    lon: float | None = None
    phones: list[str] = field(default_factory=list)
    emails: list[str] = field(default_factory=list)
    whatsapp: list[str] = field(default_factory=list)
    website: str = ""
    instagram: str = ""
    telegram: str = ""
    contact_form: str = ""
    hours: str = ""
    rating: float | None = None
    signals: dict = field(default_factory=dict)
    prov: dict = field(default_factory=dict)  # «phone:09121234567» -> {"url", "evidence", "confidence"}: where THIS value was read


# --------------------------------------------------------------------------- cleaning what a source gave


def _clean_phones(values) -> list[str]:
    out: list[str] = []
    for raw in nz.split_multi(values):
        try:
            _, key = normalize_contact(ContactKind.PHONE, raw)
        except nz.NormalizationError:
            continue
        if key and key not in out and not contactrules.is_placeholder_phone(key):
            out.append(key)
    return out[:MAX_PHONES]


def _clean_emails(values) -> list[str]:
    out: list[str] = []
    for raw in nz.split_multi(values):
        try:
            _, key = normalize_contact(ContactKind.EMAIL, raw)
        except nz.NormalizationError:
            continue
        if key and not nz.is_placeholder_email(key) and key not in out:
            out.append(key)
    return out[:MAX_EMAILS]


def _clean_one(kind: str, value: str) -> str:
    if not value:
        return ""
    try:
        return normalize_contact(kind, value)[0]
    except nz.NormalizationError:
        return ""


def prov_key(kind: str, value: str) -> str:
    """The key under which a contact value's provenance is kept (the same ``kind:normalized`` the lead drafts use). '' when it does not normalise."""
    try:
        return f"{kind}:{normalize_contact(kind, value)[1]}"
    except nz.NormalizationError:
        return ""


_ADDR_JUNK = re.compile(r"^[\s,،\-–]+|[\s,،\-–]+$")


def _route_platform_url(f: Found) -> None:
    """A map tag often has an Instagram / Telegram page in the «website» box: file it where it belongs; other shared platforms are not a business's own site."""
    if not f.website:
        return
    try:
        clean = nz.clean_url(f.website)
    except nz.NormalizationError:
        return
    host = clean.host_ascii
    if host in ("instagram.com", "instagr.am"):
        f.instagram = f.instagram or clean.url
        f.website = ""
    elif host in ("t.me", "telegram.me", "telegram.dog"):
        f.telegram = f.telegram or clean.url
        f.website = ""
    elif host in ("wa.me", "api.whatsapp.com", "whatsapp.com"):
        f.website = ""
    elif nz._is_shared_platform(host) or textnorm.is_foreign_site(host):
        f.website = ""


def clean_found(f: Found) -> Found:
    """Normalise every field the way the lead tables expect it. Invalid values are dropped, never guessed."""
    _route_platform_url(f)
    f.name = nz.normalize_text(f.name)[:200]
    f.city = place.canonical_city(f.city)[:100]
    f.address = _ADDR_JUNK.sub("", place.strip_plus_code(nz.normalize_text(f.address)))[:400]
    f.category = nz.normalize_text(f.category)[:120]
    f.phones = _clean_phones(f.phones)
    f.emails = _clean_emails(f.emails)
    f.whatsapp = [p for p in _clean_phones(f.whatsapp) if not contactrules.is_placeholder_phone(p)]
    f.website = _clean_one(ContactKind.WEBSITE, f.website)
    f.instagram = _clean_one(ContactKind.INSTAGRAM, f.instagram)
    f.telegram = _clean_one(ContactKind.TELEGRAM, f.telegram)
    if contactrules.is_placeholder_handle(f.instagram, "instagram"):
        f.instagram = ""
    if contactrules.is_placeholder_handle(f.telegram, "telegram"):
        f.telegram = ""
    f.contact_form = _clean_one(ContactKind.CONTACT_FORM, f.contact_form)
    f.hours = nz.normalize_text(f.hours)[:400]
    if not textnorm.valid_geo(f.lat, f.lon):
        f.lat = f.lon = None
    else:
        f.lat, f.lon = round(float(f.lat), 6), round(float(f.lon), 6)
    try:
        f.rating = round(float(f.rating), 1) if f.rating is not None and 0 < float(f.rating) <= 5 else None
    except (TypeError, ValueError):
        f.rating = None
    return f


# --------------------------------------------------------------------------- identity keys


def strong_keys(f: Found | CrawlCandidate) -> list[str]:
    keys: list[str] = []
    ref = getattr(f, "ref", "")
    if ref.startswith("osm:"):
        keys.append(ref)
    for p in (f.phones if isinstance(f.phones, list) else []):
        keys.append(f"ph:{p}")
    for e in (f.emails if isinstance(f.emails, list) else []):
        keys.append(f"em:{e}")
    if f.website:
        ident = textnorm.domain_key(f.website)
        if ident:
            keys.append(f"dom:{ident}")
    if f.instagram:
        try:
            keys.append(f"ig:{nz.parse_instagram(f.instagram).handle}")
        except nz.NormalizationError:
            pass
    if f.telegram:
        try:
            keys.append(f"tg:{normalize_contact(ContactKind.TELEGRAM, f.telegram)[1]}")
        except nz.NormalizationError:
            pass
    return list(dict.fromkeys(k[:320] for k in keys))


def _city_key(city: str) -> str:
    return nz.search_key(place.canonical_city(city))[:40]


def place_of(obj: Found | CrawlCandidate) -> place.Place:
    """What an entry itself says about where it is (an address, the cities its own data names, a map position) - never the city the mission asked for."""
    if isinstance(obj, Found):
        ev = [obj.city] if obj.city and obj.city_src == "evidence" else []
    else:
        ev = list((obj.signals or {}).get("city_ev") or [])
    return place.place_of(obj.address, ev, obj.lat, obj.lon)


def _same_place(f: Found, c: CrawlCandidate) -> bool:
    if place.conflicts(place_of(f), place_of(c)):
        return False
    if textnorm.valid_geo(f.lat, f.lon) and textnorm.valid_geo(c.lat, c.lon):
        return textnorm.haversine_m(f.lat, f.lon, c.lat, c.lon) <= GEO_SAME_M
    ca, cb = _city_key(f.city), _city_key(c.city)
    return not ca or not cb or ca == cb


# --------------------------------------------------------------------------- the merge


def _union(a: list, b: list, limit: int) -> list:
    out = list(a or [])
    for x in b or []:
        if x not in out:
            out.append(x)
    return out[:limit]


def _fill(cur, new):
    return cur if cur not in ("", None) else new


def _auto_prov(f: Found) -> dict:
    """Where each contact value of ``f`` came from when its source did not say more: the page ``f`` itself was read from."""
    if not f.source:
        return {}
    base = {"url": (f.url or "")[:300], "evidence": SOURCE_EVIDENCE.get(f.source, ""), "confidence": SOURCE_CONF.get(f.source, 60)}
    out: dict = {}
    pairs = [("phone", v) for v in f.phones] + [("email", v) for v in f.emails] + [("whatsapp", v) for v in f.whatsapp]
    pairs += [(kind, getattr(f, kind)) for kind in ("instagram", "telegram", "website", "contact_form") if getattr(f, kind)]
    for kind, value in pairs:
        key = prov_key(kind, value)
        if key:
            out[key] = dict(base)
    return out


def _merge_prov(cur: dict, new: dict) -> dict:
    """Provenance of contact values: a value keeps the page it was first read from, unless a later page is more sure of it."""
    out = dict(cur or {})
    for key, entry in (new or {}).items():
        old = out.get(key)
        if old is None or int((entry or {}).get("confidence") or 0) > int(old.get("confidence") or 0):
            out[key] = entry
    return dict(list(out.items())[-MAX_PROV:])


def _apply(c: CrawlCandidate, f: Found) -> bool:
    """Merge ``f`` into candidate ``c`` (in memory). True when something changed."""
    before = (c.name, c.phones, c.emails, c.website, c.instagram, c.telegram, c.lat, c.address, c.hours, c.rating, c.types, c.signals, c.sources, c.city)
    # a longer, richer name wins only when the shorter one is contained in it (never swap «کافه نادری» for «اینستاگرام»)
    if not c.name or (len(f.name) > len(c.name) and textnorm.name_core(c.name) in textnorm.name_core(f.name)):
        c.name = f.name or c.name
    c.name_core = textnorm.name_core(c.name)
    c.category = _fill(c.category, f.category)
    c.types = _union(c.types, f.types, 8)
    signals = dict(c.signals or {})
    if f.city:
        if f.city_src == "evidence":
            ev = _union(list(signals.get("city_ev") or []), [f.city], 4)
            signals["city_ev"] = ev
            if signals.get("city_src") != "evidence":  # a city the source's own data names beats one that only came from the search
                c.city = f.city
                signals["city_src"] = "evidence"
        else:
            c.city = _fill(c.city, f.city)
    c.address = c.address if len(c.address) >= len(f.address) else f.address
    if c.lat is None and f.lat is not None:
        c.lat, c.lon = f.lat, f.lon
    c.phones = _union(c.phones, f.phones, MAX_PHONES)
    c.emails = _union(c.emails, f.emails, MAX_EMAILS)
    c.whatsapp = _union(c.whatsapp, f.whatsapp, 3)
    c.website = _fill(c.website, f.website)
    c.instagram = _fill(c.instagram, f.instagram)
    c.telegram = _fill(c.telegram, f.telegram)
    c.contact_form = _fill(c.contact_form, f.contact_form)
    c.hours = _fill(c.hours, f.hours)
    c.rating = _fill(c.rating, f.rating)
    for k, v in (f.signals or {}).items():
        if k == "city_src":
            continue
        if k == "prov" and isinstance(v, dict):
            signals["prov"] = _merge_prov(signals.get("prov") or {}, v)
        elif isinstance(v, list):
            signals[k] = _union(signals.get(k, []), v, 30)
        elif isinstance(v, dict) and isinstance(signals.get(k), dict) and signals[k]:
            # two descriptions of the same kind of signal: what was already there stays - except an Instagram page's own numbers (read by the node) which replace the
            # public counters a search result only showed (``ig.from == "search"``)
            signals[k] = {**signals[k], **v} if k == "ig" else {**v, **signals[k]}
        elif k not in signals or signals[k] in ("", None, 0):
            signals[k] = v
    new_prov = {**_auto_prov(f), **(f.prov or {})}
    if new_prov:
        signals["prov"] = _merge_prov(signals.get("prov") or {}, new_prov)
    c.signals = signals
    entry = {"source": f.source, "ref": f.ref[:120], "url": f.url[:300]}
    if f.source and entry not in (c.sources or []):
        c.sources = [*(c.sources or []), entry][:12]
    return before != (c.name, c.phones, c.emails, c.website, c.instagram, c.telegram, c.lat, c.address, c.hours, c.rating, c.types, c.signals, c.sources, c.city)


def _register_keys(c: CrawlCandidate, keys: list[str]) -> None:
    """Attach identity keys to ``c``; a key that already belongs to ANOTHER candidate means they are one business: merge them -
    unless their own evidence says they are in different places (then the key stays with its first owner)."""
    for key in keys:
        owner = CandidateKey.objects.filter(run_id=c.run_id, key=key).select_related("candidate").first()
        if owner is None:
            try:
                with transaction.atomic():
                    CandidateKey.objects.create(run_id=c.run_id, key=key, candidate=c)
            except IntegrityError:
                continue
        elif owner.candidate_id != c.pk:
            if place.conflicts(place_of(c), place_of(owner.candidate)):
                continue
            _absorb(c, owner.candidate)


def _absorb(keep: CrawlCandidate, other: CrawlCandidate) -> None:
    """Move everything of ``other`` into ``keep`` and delete ``other`` (two candidates turned out to be one business)."""
    osig = dict(other.signals or {})
    f = Found(
        name=other.name, source="", category=other.category, types=list(other.types), city=other.city, city_src=str(osig.get("city_src") or ""), address=other.address,
        lat=other.lat, lon=other.lon, phones=list(other.phones), emails=list(other.emails), whatsapp=list(other.whatsapp), website=other.website, instagram=other.instagram,
        telegram=other.telegram, contact_form=other.contact_form, hours=other.hours, rating=other.rating, signals=osig,
    )
    _apply(keep, f)
    keep.sources = _union(keep.sources, other.sources, 12)
    keep.save()
    CandidateKey.objects.filter(candidate=other).update(candidate=keep)
    other.delete()


def find_existing(run: CrawlRun, f: Found) -> CrawlCandidate | None:
    here = place_of(f)
    for key in strong_keys(f):
        row = CandidateKey.objects.filter(run=run, key=key).select_related("candidate").first()
        if row is not None and not place.conflicts(here, place_of(row.candidate)):
            return row.candidate
    core = textnorm.name_core(f.name)
    if len(core) < 3:
        return None
    pool = CrawlCandidate.objects.filter(run=run, name_core__startswith=core[:3])[:80]
    for c in pool:
        if textnorm.similar(core, c.name_core) >= NAME_SIMILAR and _same_place(f, c):
            return c
    return None


def out_of_area(run: CrawlRun, f: Found) -> place.Verdict | None:
    """The verdict when ``f`` is NOT in the mission's cities (its own address / position / landline says another place), else None."""
    cities = [c for c in ((run.spec or {}).get("cities") or []) if c]
    if not cities or (f.signals or {}).get("place_free"):  # no city asked, or an online coach (wanted wherever he or she lives)
        return None
    ev = [f.city] if f.city and f.city_src == "evidence" else []
    v = place.verdict(cities, address=f.address, cities_ev=ev, lat=f.lat, lon=f.lon, phones=f.phones, mapped=f.source == "osm")
    return v if v.state == "out" else None


def add_found(run: CrawlRun, f: Found) -> tuple[CrawlCandidate | None, bool]:
    """Put one found business into the run. Returns ``(candidate, created)``; ``(None, False)`` when the business is in another city than the mission asked for."""
    f = clean_found(f)
    if out_of_area(run, f) is not None:
        return None, False
    existing = find_existing(run, f)
    if existing is not None:
        if _apply(existing, f):
            existing.save()
        _register_keys(existing, list(dict.fromkeys([*strong_keys(f), *strong_keys(existing)])))
        return existing, False
    c = CrawlCandidate(run=run, name=f.name, name_core=textnorm.name_core(f.name))
    _apply(c, f)
    c.save()
    _register_keys(c, list(dict.fromkeys([*strong_keys(f), *strong_keys(c)])))
    return c, True
