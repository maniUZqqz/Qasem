"""Persian-aware helpers for matching: names, distances, small text cleaners. Pure functions (no I/O, no database)."""
from __future__ import annotations

import math
import re
from difflib import SequenceMatcher

from apps.growth_engine.core import normalization as nz

#: words that start almost every business name and say nothing about WHICH business it is: «باشگاه ورزشی آرمان» == «آرمان»
GENERIC_PREFIX = (
    "باشگاه بدنسازی", "باشگاه ورزشی", "باشگاه فیتنس", "باشگاه", "سالن بدنسازی", "سالن ورزشی", "مجموعه ورزشی", "مجموعه فرهنگی ورزشی", "مجموعه",
    "کافه رستوران", "کافی شاپ", "کافیشاپ", "کافه", "رستوران", "سفره خانه", "فروشگاه", "بوتیک", "مزون", "دندانپزشکی", "کلینیک", "مطب", "آتلیه",
    "آموزشگاه", "گالری", "هتل", "فست فود", "قنادی", "شیرینی سرا", "داروخانه", "آرایشگاه", "سالن زیبایی",
    "gym", "fitness", "fitness club", "club", "cafe", "coffee", "restaurant", "shop", "store", "boutique", "clinic",
)
_GENERIC_SORTED = sorted({nz.search_key(w) for w in GENERIC_PREFIX if nz.search_key(w)}, key=len, reverse=True)
_PLACE_SUFFIX = re.compile(r"\s*[-–—|،,]\s*(شعبه|منطقه|تهران|اصفهان|شیراز|مشهد|تبریز|همدان|کرج|قم|اهواز|رشت)\b.*$")


def name_core(name: str) -> str:
    """A key that is the same for the spellings of one business name: letters unified, no spaces / ZWNJ / punctuation, and the
    generic first word (باشگاه، کافه، فروشگاه ...) removed - unless nothing else would be left."""
    text = _PLACE_SUFFIX.sub("", nz.normalize_text(name))
    key = nz.search_key(text)
    for word in _GENERIC_SORTED:
        if key.startswith(word) and len(key) - len(word) >= 2:
            key = key[len(word):]
            break
    return key[:120]


_NUMBERS = re.compile(r"\d+")


def similar(a: str, b: str) -> float:
    """0..1 similarity of two name cores (1 = identical). Two names that differ in a NUMBER are two businesses
    («باشگاه بدنسازی 7» and «باشگاه بدنسازی 12»; branch numbers, «2» and «3»), however alike the letters are."""
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    if _NUMBERS.findall(a) != _NUMBERS.findall(b):
        return 0.0
    if min(len(a), len(b)) >= 4 and (a in b or b in a) and min(len(a), len(b)) / max(len(a), len(b)) >= 0.6:
        return 0.93
    return SequenceMatcher(None, a, b).ratio()


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distance in metres between two points on the Earth."""
    r = 6_371_000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


def valid_geo(lat, lon) -> bool:
    try:
        return lat is not None and lon is not None and -90 <= float(lat) <= 90 and -180 <= float(lon) <= 180 and not (float(lat) == 0 and float(lon) == 0)
    except (TypeError, ValueError):
        return False


def geo_cell(lat: float, lon: float, size_m: int = 150) -> str:
    """A coarse map-grid cell id (about ``size_m`` metres wide), used as part of a lookup key."""
    dlat = size_m / 111_320.0
    dlon = size_m / (111_320.0 * max(0.2, math.cos(math.radians(lat))))
    return f"{int(lat // dlat)}:{int(lon // dlon)}"


def domain_key(url: str) -> str:
    """The identity of a website (host without www; shared platforms keep their path). '' when it is not a usable URL."""
    try:
        return nz.clean_url(url).identity
    except nz.NormalizationError:
        return ""


def text_has_any(text: str, words) -> list[str]:
    """The words (of ``words``) that occur in ``text`` (case-insensitive, letters unified)."""
    hay = nz.normalize_text(text).casefold()
    return [w for w in words if w and nz.normalize_text(w).casefold() in hay]


def name_has_word(text: str, words) -> list[str]:
    """The words (of ``words``) in ``text``; a Latin word only as a whole word («spa» is not in «Sparta»), a Persian one anywhere (the script has no capital letters)."""
    hay = nz.normalize_text(text).casefold()
    out: list[str] = []
    for w in words:
        w = nz.normalize_text(w).casefold()
        if not w:
            continue
        if re.fullmatch(r"[a-z0-9 .\-]+", w):
            if re.search(rf"(?<![a-z0-9]){re.escape(w)}(?![a-z0-9])", hay):
                out.append(w)
        elif w in hay:
            out.append(w)
    return out


def clip(text: str, n: int) -> str:
    text = nz.normalize_text(text or "")
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


#: Iranian video / streaming sites by the START of the site's name («aparat.com», «aparatsport.ir», «telewebion.ir»), the others by the whole name
_MEDIA_PREFIXES = ("aparat", "telewebion", "namava", "filimo", "tamashakhoneh")
_MEDIA_NAMES = frozenset({
    "youtube", "youtu", "vimeo", "dailymotion", "twitch", "soundcloud", "spotify", "namasha", "radiojavan", "musixmatch", "genius", "wikipedia", "wikiwand",
    "digikala", "torob", "divar", "sheypoor", "basalam", "emalls", "tripadvisor", "booking", "lenz",
})


def is_media_host(host: str) -> bool:
    """``aparat.com``, ``aparatsport.ir``, ``telewebion.ir``, ``www.youtube.com`` ...: a video / music / marketplace / encyclopedia site - a page ABOUT something, never a business's own website."""
    parts = [p for p in (host or "").lower().split(".") if p]
    if len(parts) < 2:
        return False
    labels = parts[:-1]  # everything but the domain ending
    return any(lab.startswith(_MEDIA_PREFIXES) or lab in _MEDIA_NAMES for lab in labels)
