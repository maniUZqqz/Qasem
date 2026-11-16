"""Candidates: what the sources found, normalised and merged across sources (dedupe: name + phone + domain + geo).

``Found`` is the one shape every source returns. ``add_found`` puts it into the run's ``CrawlCandidate`` table and decides whether it
is a business already seen in this run:

  strong identities   the same OpenStreetMap object / phone number / website domain / Instagram handle / e-mail / Telegram handle
  name + place        the same name (after ``name_core``) AND either within ``GEO_SAME_M`` metres, or - when one of them has no
                      coordinates - in the same city. Two branches of a chain 5 km apart stay two candidates.

A merge never loses information: lists are united, empty fields are filled, and every source stays in ``sources``.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from django.db import IntegrityError, transaction

from apps.growth_engine.core import normalization as nz
from apps.growth_engine.leads.choices import ContactKind
from apps.growth_engine.leads.services.drafts import normalize_contact

from ..models import CandidateKey, CrawlCandidate, CrawlRun
from . import textnorm

GEO_SAME_M = 350
NAME_SIMILAR = 0.9
MAX_PHONES = 6
MAX_EMAILS = 4


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


# --------------------------------------------------------------------------- cleaning what a source gave


def _clean_phones(values) -> list[str]:
    out: list[str] = []
    for raw in nz.split_multi(values):
        try:
            _, key = normalize_contact(ContactKind.PHONE, raw)
        except nz.NormalizationError:
            continue
        if key and key not in out:
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
    elif nz._is_shared_platform(host):
        f.website = ""


def clean_found(f: Found) -> Found:
    """Normalise every field the way the lead tables expect it. Invalid values are dropped, never guessed."""
    _route_platform_url(f)
    f.name = nz.normalize_text(f.name)[:200]
    f.city = nz.normalize_text(f.city)[:100]
    f.address = _ADDR_JUNK.sub("", nz.normalize_text(f.address))[:400]
    f.category = nz.normalize_text(f.category)[:120]
    f.phones = _clean_phones(f.phones)
    f.emails = _clean_emails(f.emails)
    f.whatsapp = _clean_phones(f.whatsapp)
    f.website = _clean_one(ContactKind.WEBSITE, f.website)
    f.instagram = _clean_one(ContactKind.INSTAGRAM, f.instagram)
    f.telegram = _clean_one(ContactKind.TELEGRAM, f.telegram)
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
    return nz.search_key(city)[:40]


def _same_place(a_lat, a_lon, a_city, b_lat, b_lon, b_city) -> bool:
    if textnorm.valid_geo(a_lat, a_lon) and textnorm.valid_geo(b_lat, b_lon):
        return textnorm.haversine_m(a_lat, a_lon, b_lat, b_lon) <= GEO_SAME_M
    ca, cb = _city_key(a_city), _city_key(b_city)
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


def _apply(c: CrawlCandidate, f: Found) -> bool:
    """Merge ``f`` into candidate ``c`` (in memory). True when something changed."""
    before = (c.name, c.phones, c.emails, c.website, c.instagram, c.telegram, c.lat, c.address, c.hours, c.rating, c.types, c.signals, c.sources)
    # a longer, richer name wins only when the shorter one is contained in it (never swap «کافه نادری» for «اینستاگرام»)
    if not c.name or (len(f.name) > len(c.name) and textnorm.name_core(c.name) in textnorm.name_core(f.name)):
        c.name = f.name or c.name
    c.name_core = textnorm.name_core(c.name)
    c.category = _fill(c.category, f.category)
    c.types = _union(c.types, f.types, 8)
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
    signals = dict(c.signals or {})
    for k, v in (f.signals or {}).items():
        if isinstance(v, list):
            signals[k] = _union(signals.get(k, []), v, 30)
        elif k not in signals or signals[k] in ("", None, 0):
            signals[k] = v
    c.signals = signals
    entry = {"source": f.source, "ref": f.ref[:120], "url": f.url[:300]}
    if f.source and entry not in (c.sources or []):
        c.sources = [*(c.sources or []), entry][:12]
    return before != (c.name, c.phones, c.emails, c.website, c.instagram, c.telegram, c.lat, c.address, c.hours, c.rating, c.types, c.signals, c.sources)


def _register_keys(c: CrawlCandidate, keys: list[str]) -> None:
    """Attach identity keys to ``c``; a key that already belongs to ANOTHER candidate means they are one business: merge them."""
    for key in keys:
        owner = CandidateKey.objects.filter(run_id=c.run_id, key=key).select_related("candidate").first()
        if owner is None:
            try:
                with transaction.atomic():
                    CandidateKey.objects.create(run_id=c.run_id, key=key, candidate=c)
            except IntegrityError:
                continue
        elif owner.candidate_id != c.pk:
            _absorb(c, owner.candidate)


def _absorb(keep: CrawlCandidate, other: CrawlCandidate) -> None:
    """Move everything of ``other`` into ``keep`` and delete ``other`` (two candidates turned out to be one business)."""
    f = Found(
        name=other.name, source="", category=other.category, types=list(other.types), city=other.city, address=other.address, lat=other.lat, lon=other.lon,
        phones=list(other.phones), emails=list(other.emails), whatsapp=list(other.whatsapp), website=other.website, instagram=other.instagram,
        telegram=other.telegram, contact_form=other.contact_form, hours=other.hours, rating=other.rating, signals=dict(other.signals or {}),
    )
    _apply(keep, f)
    keep.sources = _union(keep.sources, other.sources, 12)
    keep.save()
    CandidateKey.objects.filter(candidate=other).update(candidate=keep)
    other.delete()


def find_existing(run: CrawlRun, f: Found) -> CrawlCandidate | None:
    for key in strong_keys(f):
        row = CandidateKey.objects.filter(run=run, key=key).select_related("candidate").first()
        if row is not None:
            return row.candidate
    core = textnorm.name_core(f.name)
    if len(core) < 3:
        return None
    pool = CrawlCandidate.objects.filter(run=run, name_core__startswith=core[:3])[:80]
    for c in pool:
        if textnorm.similar(core, c.name_core) >= NAME_SIMILAR and _same_place(f.lat, f.lon, f.city, c.lat, c.lon, c.city):
            return c
    return None


def add_found(run: CrawlRun, f: Found) -> tuple[CrawlCandidate, bool]:
    """Put one found business into the run. Returns ``(candidate, created)``."""
    f = clean_found(f)
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
