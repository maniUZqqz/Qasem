"""What the Growth Engine's contact parser does not read: opening hours, a rating, the words a page uses, a bio's contact details.

Pure functions over HTML / text. Nothing is invented: a value is returned only when the page itself says it.
"""
from __future__ import annotations

import json
import re

from bs4 import BeautifulSoup

from apps.growth_engine.core import normalization as nz

MAX_TEXT = 40_000

_DAYS_FA = "شنبه|یکشنبه|یک‌شنبه|دوشنبه|سه‌شنبه|سه شنبه|چهارشنبه|پنجشنبه|پنج‌شنبه|جمعه|همه روزه|همه‌روزه|هر روز|روزهای هفته|ایام هفته"
_HOURS_LABEL = re.compile(r"(?:ساعات?\s*(?:کاری|کار|فعالیت|پذیرش|کارکرد)|opening\s*hours|business\s*hours|working\s*hours|hours)\s*[:：\-–]?", re.I)
_TIME_RE = re.compile(r"\d{1,2}(?::\d{2})?\s*(?:تا|الی|–|-|to|until)\s*\d{1,2}(?::\d{2})?", re.I)
_DAY_LINE = re.compile(rf"(?:{_DAYS_FA})[^\n]{{0,30}}\d{{1,2}}", re.I)

_RATING_RES = (
    re.compile(r"امتیاز[^\d]{0,12}(\d(?:[.,٫]\d)?)\s*(?:از\s*۵|از\s*5|/\s*5)?"),
    re.compile(r"(\d(?:[.,٫]\d))\s*(?:از\s*۵|از\s*5|/\s*5)"),
    re.compile(r"rating[^\d]{0,12}(\d(?:\.\d)?)", re.I),
)


def visible_text(html: str, limit: int = MAX_TEXT) -> str:
    """The text a person sees (no scripts, styles, nav chrome kept short). Digits stay as written; callers normalise."""
    soup = BeautifulSoup(html or "", "html.parser")
    for tag in soup(["script", "style", "noscript", "svg", "template", "iframe"]):
        tag.decompose()
    text = soup.get_text("\n")
    text = re.sub(r"[ \t ]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text)
    return nz.to_ascii_digits(text).strip()[:limit]


def _json_ld(soup: BeautifulSoup) -> list[dict]:
    out: list[dict] = []
    for tag in soup.find_all("script", type=lambda t: t and "ld+json" in t):
        try:
            data = json.loads(tag.string or tag.get_text() or "null")
        except ValueError:
            continue
        stack = [data]
        while stack:
            node = stack.pop()
            if isinstance(node, list):
                stack.extend(node)
            elif isinstance(node, dict):
                out.append(node)
                for key in ("@graph", "itemListElement", "mainEntity", "subOrganization"):
                    if key in node:
                        stack.append(node[key])
    return out


def hours_from_jsonld(nodes: list[dict]) -> str:
    for node in nodes:
        spec = node.get("openingHoursSpecification")
        if isinstance(spec, dict):
            spec = [spec]
        if isinstance(spec, list) and spec:
            parts = []
            for s in spec[:8]:
                if not isinstance(s, dict):
                    continue
                days = s.get("dayOfWeek")
                days = ", ".join(str(d).rsplit("/", 1)[-1] for d in (days if isinstance(days, list) else [days]) if d)
                if s.get("opens") and s.get("closes"):
                    parts.append(f"{days} {s['opens']}–{s['closes']}".strip())
            if parts:
                return "؛ ".join(parts)[:400]
        oh = node.get("openingHours")
        if isinstance(oh, str) and oh.strip():
            return oh.strip()[:400]
        if isinstance(oh, list) and oh:
            return "؛ ".join(str(x) for x in oh[:8])[:400]
    return ""


def find_hours(html: str, text: str | None = None) -> str:
    """Opening hours as the page states them (one short line), or ''. JSON-LD first, then a «ساعت کاری …» line, then day lines."""
    soup = BeautifulSoup(html or "", "html.parser")
    ld = hours_from_jsonld(_json_ld(soup))
    if ld:
        return ld
    text = text if text is not None else visible_text(html)
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    for i, line in enumerate(lines):
        if _HOURS_LABEL.search(line):
            tail = _HOURS_LABEL.split(line, maxsplit=1)[-1].strip(" :–-")
            chunk = tail if _TIME_RE.search(tail) else " ".join(lines[i + 1:i + 4])
            if _TIME_RE.search(chunk):
                return nz.normalize_text(chunk)[:240]
    day_lines = [ln for ln in lines if _DAY_LINE.search(ln) and _TIME_RE.search(ln)]
    if day_lines:
        return "؛ ".join(nz.normalize_text(ln) for ln in day_lines[:7])[:400]
    return ""


def find_rating(text: str) -> float | None:
    for rx in _RATING_RES:
        m = rx.search(text or "")
        if m:
            try:
                v = float(m.group(1).replace(",", ".").replace("٫", "."))
            except ValueError:
                continue
            if 0 < v <= 5:
                return v
    return None


def find_words(text: str, words) -> list[str]:
    hay = nz.normalize_text(text).casefold()
    return [w for w in dict.fromkeys(words) if w and nz.normalize_text(w).casefold() in hay]


def page_meta(html: str) -> dict:
    """title / description / h1 / lang of a page (what a result list or a score needs)."""
    soup = BeautifulSoup(html or "", "html.parser")
    title = nz.normalize_text(soup.title.get_text(" ", strip=True)) if soup.title else ""
    desc = ""
    tag = soup.find("meta", attrs={"name": "description"}) or soup.find("meta", attrs={"property": "og:description"})
    if tag and tag.get("content"):
        desc = nz.normalize_text(tag["content"])
    og = soup.find("meta", attrs={"property": "og:site_name"})
    h1 = soup.find("h1")
    root = soup.find("html")
    return {
        "title": title[:200], "description": desc[:400], "site_name": nz.normalize_text(og["content"])[:120] if og and og.get("content") else "",
        "h1": nz.normalize_text(h1.get_text(" ", strip=True))[:160] if h1 else "", "lang": (root.get("lang") or "")[:8] if root else "",
    }


# --------------------------------------------------------------------------- bios (Instagram) and loose text

_PHONE_LOOSE = re.compile(r"(?<!\d)(?:\+?98|0)?9\d{9}(?!\d)|(?<!\d)0\d{2}[\s\-]?\d{7,8}(?!\d)|(?<!\d)0\d{10}(?!\d)")
_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)+")
_URL = re.compile(r"(?:https?://)?(?:www\.)?[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)*\.(?:ir|com|net|org|co|shop|store|app|site|online)(?:/[^\s،,]*)?", re.I)
_WA_LINK = re.compile(r"(?:wa\.me|api\.whatsapp\.com/send\?phone=)/?\+?(\d{10,13})")
_TG_LINK = re.compile(r"(?:t\.me|telegram\.me)/([A-Za-z0-9_]{4,32})")


def contacts_in_text(text: str) -> dict:
    """Phones / e-mails / websites / WhatsApp / Telegram written in a short free text (an Instagram bio). Callers validate them."""
    flat = nz.to_ascii_digits(text or "")
    phones = [m.group(0) for m in _PHONE_LOOSE.finditer(flat)]
    emails = _EMAIL.findall(flat)
    sites = [u for u in _URL.findall(flat) if not re.search(r"instagram\.|wa\.me|t\.me|@", u, re.I)]
    wa = _WA_LINK.findall(flat)
    tg = _TG_LINK.findall(flat)
    return {"phones": list(dict.fromkeys(phones)), "emails": list(dict.fromkeys(emails)), "websites": list(dict.fromkeys(sites)),
            "whatsapp": list(dict.fromkeys(wa)), "telegram": list(dict.fromkeys(tg))}


# --------------------------------------------------------------------------- OpenStreetMap opening_hours -> Persian

_OSM_DAYS = {"Mo": "دوشنبه", "Tu": "سه‌شنبه", "We": "چهارشنبه", "Th": "پنجشنبه", "Fr": "جمعه", "Sa": "شنبه", "Su": "یکشنبه"}
_OSM_ORDER = ["Sa", "Su", "Mo", "Tu", "We", "Th", "Fr"]
_FA_DIGIT_TABLE = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


def osm_hours_fa(value: str) -> str:
    """«Mo-Su 10:00-24:00» -> «هر روز ۱۰:۰۰ تا ۲۴:۰۰». Anything the simple grammar does not cover is returned as it was written."""
    raw = (value or "").strip()
    if not raw:
        return ""
    parts = [p.strip() for p in raw.split(";") if p.strip()]
    out: list[str] = []
    for part in parts:
        m = re.fullmatch(r"([A-Za-z,\- ]+?)\s+((?:\d{1,2}:\d{2}-\d{1,2}:\d{2})(?:\s*,\s*\d{1,2}:\d{2}-\d{1,2}:\d{2})*)", part)
        if m is None:
            if part.lower() in ("24/7", "mo-su 00:00-24:00"):
                out.append("شبانه‌روزی")
                continue
            return raw
        days_txt, times_txt = m.group(1).strip(), m.group(2)
        names: list[str] = []
        for token in [t.strip() for t in days_txt.split(",") if t.strip()]:
            if "-" in token:
                a, _, b = token.partition("-")
                if a not in _OSM_DAYS or b not in _OSM_DAYS:
                    return raw
                if (a, b) == ("Mo", "Su") or (a, b) == ("Sa", "Fr"):
                    names.append("هر روز")
                    continue
                i, j = _OSM_ORDER.index(a), _OSM_ORDER.index(b)
                names.append(f"{_OSM_DAYS[a]} تا {_OSM_DAYS[b]}" if i <= j else f"{_OSM_DAYS[a]} تا {_OSM_DAYS[b]}")
            elif token in _OSM_DAYS:
                names.append(_OSM_DAYS[token])
            else:
                return raw
        spans = [s.strip().replace("-", " تا ") for s in times_txt.split(",")]
        out.append(" و ".join(names) + " " + "، ".join(spans))
    return "؛ ".join(out).translate(_FA_DIGIT_TABLE)
