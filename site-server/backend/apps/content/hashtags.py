"""Hashtags the way Instagram wants them, and repair of glued ones.

Instagram ends a hashtag at the first space, so «#هوش مصنوعی» tags only
«#هوش». Persian writers join the words with an underscore («#هوش_مصنوعی») or
a half-space. A local model often glues them with nothing at all
(«#برنامهورزشی», «#PDFبرندشده») and the tag then matches no real search.

This module repairs the glued ones with a list of everyday Persian words: a tag
is split only when EVERY piece is a known word, so a legitimate single word
(«مربیگری») is never cut and an unknown word is left exactly as written.
Nothing here calls a model; it works when the AI is off.
"""
from __future__ import annotations

import re

from apps.common.fatext import normalize

#: everyday words of a fitness / coaching / software shop. Compared in the
#: `normalize` form (no half-space, no kasra). Extending the list can only make
#: a split more likely to be right; a word that is not listed is never cut.
_WORDS = frozenset(normalize(w) for w in """
برنامه ورزشی ورزش ورزشکار ورزشکاران هوش مصنوعی غذایی تمرینی تمرین مربی مربیگری مربیان
بدنسازی باشگاه باشگاهی تناسب اندام تکنولوژی فناوری چغر برند شده رایگان توکن
دستی دستیار نرم افزار پیش نویس پیشنویس غذا رژیم تغذیه سلامت سلامتی فیتنس
آموزش آموزشی ایرانی اپلیکیشن کوچ کوچینگ حرکت حرکات کتابخانه هفته ماه ابزار ابزارها
مجموعه تجهیزات دستگاه اسکن مشاوره چاپ چاپی لینک بایو زندگی سبک سالم
حرفهای شخصی اختصاصی بازبینی ثبتنام شروع چغرتر وقت اینستاگرام ریلز استوری پست کپشن محتوا
تولید ویدیو عکس تصویر طراحی بازاریابی کسبوکار مشتری مشتریان فروشگاه فروش خرید
خانگی خانه دمبل وزنه عضله حجم
""".split())

_LATIN = re.compile(r"([A-Za-z0-9]+)")
_MIN_LEN = 6
#: a tag this long with no separator, that we could not explain, is worth a warning
_LONG = 13


def _segment(word: str) -> list[str] | None:
    """Fewest-pieces split of `word` into known words, or None."""
    n = len(word)
    best: list[list[str] | None] = [None] * (n + 1)
    best[0] = []
    for end in range(1, n + 1):
        for start in range(end):
            piece = word[start:end]
            if best[start] is None or piece not in _WORDS:
                continue
            cand = best[start] + [piece]
            if best[end] is None or len(cand) < len(best[end]):
                best[end] = cand
    return best[n]


def _cut_like(raw: str, pieces: list[str]) -> list[str]:
    """Cut `raw` where its normalised form was cut, so the repaired tag keeps
    the writer's own spelling (kasra, ي/ی ...) in each piece."""
    out, i = [], 0
    for piece in pieces:
        need, chunk = len(piece), ""
        while i < len(raw) and need > 0:
            chunk += raw[i]
            need -= len(normalize(raw[i]))
            i += 1
        while i < len(raw) and normalize(raw[i]) == "":  # marks belong to the piece before them
            chunk += raw[i]
            i += 1
        out.append(chunk.replace("‌", ""))
    return out


def clean(tag) -> str:
    """«# هوش  مصنوعی» -> «هوش_مصنوعی» (no leading #, spaces become underscores)."""
    word = str(tag or "").strip().lstrip("#").strip()
    return re.sub(r"[\s_]+", "_", word).strip("_")


def repair(tag) -> str:
    """The tag, split at word boundaries if it was glued; a leading # is kept.

    «برنامهورزشی» -> «برنامه_ورزشی», «PDFبرندشده» -> «PDF_برند_شده»;
    «مربیگری», «هوش_مصنوعی» and unknown words come back unchanged.
    """
    prefix = "#" if str(tag or "").lstrip().startswith("#") else ""
    word = clean(tag)
    if not word:
        return ""
    parts: list[str] = []
    for chunk in word.split("_"):
        for run in (r for r in _LATIN.split(chunk) if r):
            if _LATIN.fullmatch(run):  # a Latin run next to Persian is its own word
                parts.append(run)
                continue
            norm = normalize(run)
            seg = None if len(norm) < _MIN_LEN or norm in _WORDS else _segment(norm)
            parts.extend(_cut_like(run, seg) if seg and len(seg) >= 2 else [run])
    return prefix + "_".join(p for p in parts if p)


def parse(value) -> list[str]:
    """What a person typed or a model stored -> a list of tags.

    A list is taken as is; text with «#» is split on the hashtags; other text is
    split on commas and new lines (so «برنامه ورزشی» stays ONE tag).
    """
    if isinstance(value, (list, tuple)):
        return [v.strip() for v in value if isinstance(v, str) and v.strip()]
    text = str(value or "")
    if "#" in text:
        return re.findall(r"#[^\s#،,]+", text)
    return [t.strip() for t in re.split(r"[,،\n]+", text) if t.strip()]


def repair_all(value) -> list[str]:
    """`repair` over a stored list (or typed text); empty results dropped."""
    return [r for r in (repair(t) for t in parse(value)) if r]


def is_glued(tag) -> bool:
    """A long tag with no separator that `repair` could not explain: probably
    several words stuck together that this module does not know how to split."""
    word = clean(tag)
    norm = normalize(word)
    return (
        len(norm) >= _LONG
        and "_" not in word
        and "‌" not in str(tag)
        and not _LATIN.fullmatch(word)
        and norm not in _WORDS
        and clean(repair(tag)) == word
    )
