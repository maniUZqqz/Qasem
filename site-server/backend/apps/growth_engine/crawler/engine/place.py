"""Where is a business? Evidence-based place checks (pure functions: no network, no database).

A crawl for «باشگاه‌های تهران» must only keep businesses that really are in Tehran. A page that merely turned up while searching for Tehran is
NOT evidence: a directory's Isfahan list, a search hit for an Isfahan gym and a map object 400 km away all «belong» to the mission only by
accident. What counts as evidence, strongest first:

  1. the business's own address / city field names a city (``address_cities``: whole-word, ZWNJ-insensitive, a city that is only the name of a
     street - «خیابان شیراز» - is ignored);
  2. its map position against the known centre of the wanted city (``geo_state``);
  3. the area code of its landline (031 = Isfahan province, 021 = Tehran province ...).

``verdict`` combines them into ``in`` (it is in the wanted place), ``out`` (the evidence says another place) or ``unknown`` (no evidence; the
caller decides - the crawler keeps such a business, but never claims «در تهران است» for it).

``conflicts`` says two descriptions cannot be one business (different cities in their addresses, or two map positions far apart): the dedupe
must never merge them, however alike their names are.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import parse_qs, unquote, urlsplit

from apps.growth_engine.core import normalization as nz
from apps.growth_engine.extraction.services import parser as contact_parser

from . import textnorm

#: city -> (lat, lon, radius in km that still counts as «in the city»); outside radius + OUT_MARGIN_KM the position says «another place»
CITY_CENTERS: dict[str, tuple[float, float, float]] = {
    "تهران": (35.6892, 51.3890, 32), "اصفهان": (32.6546, 51.6680, 18), "مشهد": (36.2605, 59.6168, 22), "شیراز": (29.5918, 52.5837, 18),
    "تبریز": (38.0962, 46.2738, 16), "کرج": (35.8400, 50.9391, 18), "قم": (34.6416, 50.8746, 14), "اهواز": (31.3183, 48.6706, 16),
    "رشت": (37.2808, 49.5832, 12), "همدان": (34.7992, 48.5146, 12), "کرمان": (30.2839, 57.0834, 14), "یزد": (31.8974, 54.3569, 14),
    "ارومیه": (37.5527, 45.0761, 12), "اراک": (34.0954, 49.7013, 12), "ساری": (36.5633, 53.0601, 12), "قزوین": (36.2688, 50.0041, 12),
    "بندرعباس": (27.1865, 56.2808, 12), "زاهدان": (29.4963, 60.8629, 12), "کرمانشاه": (34.3277, 47.0778, 14), "گرگان": (36.8427, 54.4439, 12),
    "سنندج": (35.3219, 46.9862, 10), "اردبیل": (38.2498, 48.2933, 10), "بوشهر": (28.9234, 50.8203, 10), "خرم‌آباد": (33.4878, 48.3558, 10),
    "زنجان": (36.6736, 48.4787, 10), "سمنان": (35.5769, 53.3920, 10),
}
OUT_MARGIN_KM = 20.0
#: two map positions further apart than this are two places (one business does not stand in two cities)
CONFLICT_KM = 25.0

#: city -> province (used with the landline's area code)
CITY_PROVINCE: dict[str, str] = {
    "تهران": "تهران", "ورامین": "تهران", "اسلامشهر": "تهران", "پردیس": "تهران", "شهریار": "تهران", "کرج": "البرز", "قم": "قم",
    "مشهد": "خراسان رضوی", "نیشابور": "خراسان رضوی", "سبزوار": "خراسان رضوی", "کاشمر": "خراسان رضوی",
    "اصفهان": "اصفهان", "کاشان": "اصفهان", "نجف‌آباد": "اصفهان", "فولادشهر": "اصفهان", "شاهین‌شهر": "اصفهان", "خمینی‌شهر": "اصفهان", "زرین‌شهر": "اصفهان",
    "شیراز": "فارس", "تبریز": "آذربایجان شرقی", "مراغه": "آذربایجان شرقی", "میانه": "آذربایجان شرقی", "ارومیه": "آذربایجان غربی", "خوی": "آذربایجان غربی",
    "اهواز": "خوزستان", "دزفول": "خوزستان", "آبادان": "خوزستان", "خرمشهر": "خوزستان", "ماهشهر": "خوزستان", "بهبهان": "خوزستان",
    "کرمانشاه": "کرمانشاه", "رشت": "گیلان", "لاهیجان": "گیلان", "بندر انزلی": "گیلان", "زاهدان": "سیستان و بلوچستان", "کرمان": "کرمان", "رفسنجان": "کرمان",
    "سیرجان": "کرمان", "بم": "کرمان", "همدان": "همدان", "ملایر": "همدان", "یزد": "یزد", "اردکان": "یزد", "اردبیل": "اردبیل", "بندرعباس": "هرمزگان", "کیش": "هرمزگان",
    "قشم": "هرمزگان", "اراک": "مرکزی", "ساوه": "مرکزی", "زنجان": "زنجان", "سنندج": "کردستان", "قزوین": "قزوین", "خرم‌آباد": "لرستان", "بروجرد": "لرستان",
    "گرگان": "گلستان", "گنبد کاووس": "گلستان", "ساری": "مازندران", "بابل": "مازندران", "آمل": "مازندران", "چالوس": "مازندران", "رامسر": "مازندران",
    "قائم‌شهر": "مازندران", "بجنورد": "خراسان شمالی", "بیرجند": "خراسان جنوبی", "طبس": "خراسان جنوبی", "ایلام": "ایلام", "شهرکرد": "چهارمحال و بختیاری",
    "بوشهر": "بوشهر", "یاسوج": "کهگیلویه و بویراحمد", "سمنان": "سمنان", "شاهرود": "سمنان",
}
AREA_CODE_PROVINCE: dict[str, str] = {
    "021": "تهران", "026": "البرز", "025": "قم", "031": "اصفهان", "041": "آذربایجان شرقی", "044": "آذربایجان غربی", "045": "اردبیل", "051": "خراسان رضوی",
    "056": "خراسان جنوبی", "058": "خراسان شمالی", "061": "خوزستان", "066": "لرستان", "071": "فارس", "076": "هرمزگان", "077": "بوشهر", "081": "همدان",
    "083": "کرمانشاه", "084": "ایلام", "086": "مرکزی", "087": "کردستان", "011": "مازندران", "013": "گیلان", "017": "گلستان", "023": "سمنان", "024": "زنجان",
    "028": "قزوین", "034": "کرمان", "035": "یزد", "038": "چهارمحال و بختیاری", "054": "سیستان و بلوچستان", "074": "کهگیلویه و بویراحمد",
}
#: cities the contact parser does not know but that show up next to a big city's name in addresses
_EXTRA_CITIES = ("فولادشهر", "شاهین‌شهر", "خمینی‌شهر", "زرین‌شهر")
_EXTRA_PATTERNS = [(name, contact_parser._city_pattern(name)) for name in _EXTRA_CITIES]
_EN_TO_FA = {
    "tehran": "تهران", "isfahan": "اصفهان", "esfahan": "اصفهان", "mashhad": "مشهد", "meshed": "مشهد", "shiraz": "شیراز", "tabriz": "تبریز", "karaj": "کرج", "qom": "قم", "ghom": "قم",
    "ahvaz": "اهواز", "ahwaz": "اهواز", "rasht": "رشت", "hamedan": "همدان", "hamadan": "همدان", "kerman": "کرمان", "yazd": "یزد", "urmia": "ارومیه", "orumiyeh": "ارومیه",
    "arak": "اراک", "sari": "ساری", "qazvin": "قزوین", "ghazvin": "قزوین", "bandar abbas": "بندرعباس", "bandarabbas": "بندرعباس", "zahedan": "زاهدان",
    "kermanshah": "کرمانشاه", "gorgan": "گرگان", "sanandaj": "سنندج", "ardabil": "اردبیل", "bushehr": "بوشهر", "khorramabad": "خرم‌آباد", "zanjan": "زنجان",
    "semnan": "سمنان", "kashan": "کاشان", "najafabad": "نجف‌آباد", "shahriar": "شهریار", "varamin": "ورامین", "pardis": "پردیس", "kish": "کیش", "qeshm": "قشم",
}
_EN_PATTERNS = [(en, fa, re.compile(rf"(?<![a-z]){re.escape(en)}(?![a-z])")) for en, fa in sorted(_EN_TO_FA.items(), key=lambda kv: -len(kv[0]))]
#: «خیابان شیراز»، «بلوار اصفهان»، «میدان تبریز»، «نرسیده به کرج»: the city's name is the name of a street / landmark, not the place
_STREET_BEFORE = re.compile(r"(?:^|[\s،,.\-–/(])(?:خیابان|خ|بلوار|کوچه|میدان|بزرگراه|اتوبان|آزادراه|چهارراه|چهار راه|پل|فلکه|ایستگاه|مترو|محله|کوی|جاده|جنب|روبروی|روبه‌روی|نرسیده به|بعد از|قبل از|street|st|blvd|boulevard|avenue|ave|road|rd|square|sq)\.?\s*(?:[^\s،,]+\s*[-–/]\s*)?$", re.I)
_PLUS_CODE = re.compile(r"(?<![A-Za-z0-9])[23456789CFGHJMPQRVWX]{4,8}\+[23456789CFGHJMPQRVWX]{2,3}(?![A-Za-z0-9])\s*[،,]?\s*")


def strip_plus_code(address: str) -> str:
    """Google «plus codes» (Q863+VV3) are map references, not part of an address a person can read."""
    return re.sub(r"\s{2,}", " ", _PLUS_CODE.sub("", address or "")).strip(" ،,-–")


def _clean(text: str) -> str:
    # a ZWNJ becomes a space, and a ZWNJ typed next to a space («نجف‌ آباد»، «شاهین‌ شهر») must not leave TWO spaces: the city patterns allow one
    return re.sub(r"\s+", " ", nz.normalize_text(text or "").replace("‌", " ").replace("‎", "")).strip()


def _all_patterns():
    return [*contact_parser._CITY_PATTERNS, *_EXTRA_PATTERNS]


def address_cities(text: str, *, street_filter: bool = True) -> list[str]:
    """Canonical Persian names of the known cities named in ``text``, in the order they appear (a city that is only a street's name is skipped)."""
    raw = _clean(text)
    if not raw:
        return []
    hits: list[tuple[int, str]] = []
    for name, pattern in _all_patterns():
        for m in pattern.finditer(raw):
            if street_filter and _STREET_BEFORE.search(raw[max(0, m.start() - 20):m.start()]):
                continue
            hits.append((m.start(), name))
            break
    low = raw.casefold()
    for en, fa, pattern in _EN_PATTERNS:
        m = pattern.search(low)
        if m and not (street_filter and _STREET_BEFORE.search(low[max(0, m.start() - 20):m.start()])):
            hits.append((m.start(), fa))
    hits.sort()
    out: list[str] = []
    for _, name in hits:
        if name not in out:
            out.append(name)
    return out


def canonical_city(text: str) -> str:
    """«شهر تهران» / «tehran» / «Tehran» / «منطقه ۴ شهر تهران» -> «تهران». A name this table does not know is only cleaned («شهرِ X» -> «X»)."""
    value = nz.normalize_text(text or "")
    if not value:
        return ""
    names = address_cities(value, street_filter=False)
    if names:
        return names[0]
    value = re.sub(r"^(?:شهر|شهرستان|استان)\s+", "", value).strip(" ،,-")
    return value[:100]


def city_of_url(url: str) -> str:
    """The city a listing URL is about (``?city=isfahan``, ``/isfahan/``, a percent-encoded Persian path), or ''."""
    parts = urlsplit(url or "")
    query = parse_qs(parts.query)
    for key in ("city", "c", "town", "location"):
        for value in query.get(key, []):
            got = canonical_city(unquote(value))
            if got in CITY_CENTERS or got in CITY_PROVINCE:
                return got
    text = unquote(parts.path)
    for seg in re.split(r"[/_\-]+", text):
        fa = _EN_TO_FA.get(seg.casefold())
        if fa:
            return fa
    named = address_cities(text.replace("-", " "), street_filter=False)
    return named[0] if named else ""


# --------------------------------------------------------------------------- the verdict


@dataclass(frozen=True)
class Verdict:
    state: str  # in | out | unknown
    reason: str = ""
    city: str = ""  # the city the evidence names (for «out»: the other city)


def geo_state(lat, lon, wanted: set[str]) -> str:
    """``in`` | ``out`` | ``unknown`` of a position against the wanted cities (only when EVERY wanted city has a known centre)."""
    if not textnorm.valid_geo(lat, lon) or not wanted:
        return "unknown"
    centres = [CITY_CENTERS.get(c) for c in wanted]
    if not all(centres):
        return "unknown"
    best = min((textnorm.haversine_m(float(lat), float(lon), c[0], c[1]) / 1000.0 - c[2], c) for c in centres)[0]
    if best <= 0:
        return "in"
    return "out" if best > OUT_MARGIN_KM else "unknown"


def geo_city(lat, lon) -> str:
    """The known big city a position is inside (its centre's radius), or ''."""
    if not textnorm.valid_geo(lat, lon):
        return ""
    best, best_d = "", None
    for city, (clat, clon, radius) in CITY_CENTERS.items():
        d = textnorm.haversine_m(float(lat), float(lon), clat, clon) / 1000.0
        if d <= radius and (best_d is None or d < best_d):
            best, best_d = city, d
    return best


def phone_provinces(phones) -> set[str]:
    """Provinces named by the area codes of the LANDLINES (a mobile number says nothing about where a business is)."""
    out: set[str] = set()
    for p in phones or []:
        digits = re.sub(r"\D", "", str(p))
        if len(digits) >= 10 and digits.startswith("0") and not digits.startswith("09"):
            prov = AREA_CODE_PROVINCE.get(digits[:3])
            if prov:
                out.add(prov)
    return out


def _named(address: str, cities_ev) -> list[str]:
    """The cities the business's own data names: its ADDRESS first (the most specific thing it says about itself); only when the address names no
    city, the city fields (a listing's city, JSON-LD addressLocality, an OSM ``addr:city``). A card on «Tehran's list» whose address says Isfahan is in Isfahan."""
    named = address_cities(address)
    if named:
        return named
    out: list[str] = []
    for ev in cities_ev or []:
        canon = canonical_city(ev)
        if canon and canon not in out:
            out.append(canon)
    return out


def verdict(cities, *, address: str = "", cities_ev=(), lat=None, lon=None, phones=(), mapped: bool = False) -> Verdict:
    """Is this business in one of the ``cities`` the mission asked for?  ``mapped``: it came from a map query bounded to the city."""
    wanted = {canonical_city(c) for c in (cities or []) if c}
    wanted.discard("")
    if not wanted:
        return Verdict("unknown")
    named = _named(address, cities_ev)
    here = [c for c in named if c in wanted]
    if named and not here and all(c in CITY_PROVINCE or c in CITY_CENTERS for c in named):
        return Verdict("out", f"نشانی یا شهرِ ثبت‌شده «{named[0]}» است", named[0])
    geo = geo_state(lat, lon, wanted)
    if geo == "out":
        return Verdict("out", "جای دقیقش روی نقشه بیرون از شهرِ خواسته‌شده است", named[0] if named else "")
    if geo == "in" or here:
        return Verdict("in", "نشانی/جایش در شهرِ خواسته‌شده است", (here or sorted(wanted))[0])
    provs = phone_provinces(phones)
    wanted_provs = {CITY_PROVINCE[c] for c in wanted if c in CITY_PROVINCE}
    if provs and wanted_provs and not (provs & wanted_provs):
        return Verdict("out", "پیش‌شمارهٔ تلفنِ ثابتش به استانِ دیگری می‌خورد", "")
    if mapped:
        return Verdict("in", "روی نقشه در محدودهٔ جست‌وجوی شهر بود", sorted(wanted)[0])
    return Verdict("unknown")


# --------------------------------------------------------------------------- «can these be one business?»


@dataclass(frozen=True)
class Place:
    cities: tuple[str, ...] = ()
    lat: float | None = None
    lon: float | None = None


def place_of(address: str = "", city_ev=(), lat=None, lon=None) -> Place:
    named = _named(address, city_ev)
    return Place(tuple(named), float(lat) if textnorm.valid_geo(lat, lon) else None, float(lon) if textnorm.valid_geo(lat, lon) else None)


def conflicts(a: Place, b: Place) -> bool:
    """True when two descriptions cannot be the same business: no city in common although both name one, or two positions far apart."""
    if a.cities and b.cities and not (set(a.cities) & set(b.cities)):
        return True
    if a.lat is not None and b.lat is not None and textnorm.haversine_m(a.lat, a.lon, b.lat, b.lon) > CONFLICT_KM * 1000:
        return True
    return False
