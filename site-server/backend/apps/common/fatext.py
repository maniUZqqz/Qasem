"""Small Persian-text helpers shared by the checks that read Persian prose.

Why this exists: the same sentence can be typed in several byte-different
ways — Persian or Arabic-Indic or Latin digits, with or without a half-space
(ZWNJ), with Arabic ي/ك from an old keyboard, with a kasra mark that the
brand copy uses («جایگزینِ مربی»). A "never say" list written one way and a
caption written another way must still meet, otherwise the protection looks
on but silently misses the very words the owner banned.
"""
from __future__ import annotations

import re

_FA_TO_EN = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
_EN_TO_FA = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")

# ZWNJ, ZWJ, LRM/RLM, tatweel, and the Arabic short-vowel / kasra marks.
_STRIP = re.compile("[\u200c\u200d\u200e\u200f\u0640\u064b-\u065f\u0670]")
_PERCENT = str.maketrans({"٪": "%"})
_LETTERS = str.maketrans({"ي": "ی", "ى": "ی", "ك": "ک", "ۀ": "ه", "ة": "ه"})
_SPACES = re.compile(r"\s+")


def en_digits(text: str) -> str:
    """Persian and Arabic-Indic digits -> ASCII digits."""
    return (text or "").translate(_FA_TO_EN)


def fa_digits(text) -> str:
    """ASCII digits -> Persian digits (for text a person will read)."""
    return str(text if text is not None else "").translate(_EN_TO_FA)


def fa_datetime(value, *, with_time: bool = True) -> str:
    """A moment as a person in Iran reads it: «۱۴۰۵/۰۸/۲۳ ۰۶:۰۰», Tehran time.

    `value` is an ISO string or a datetime (naive = UTC). Anything unreadable
    gives "" so a caller can fall back to a plain sentence. The panel used to
    print «۲۰۲۶-۱۱-۱۴ ۰۲:۳۰» (UTC, Gregorian) next to «۱۴۰۵/۸/۲۳» (Tehran,
    Shamsi) on the same card.
    """
    import datetime as dt

    from apps.common.versioning import gregorian_to_jalali

    if isinstance(value, str):
        try:
            when = dt.datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return ""
    elif isinstance(value, dt.datetime):
        when = value
    else:
        return ""
    if when.tzinfo is None:
        when = when.replace(tzinfo=dt.timezone.utc)
    try:
        from zoneinfo import ZoneInfo

        when = when.astimezone(ZoneInfo("Asia/Tehran"))
    except Exception:  # no tz database: Iran has used a fixed +03:30 since 2022
        when = when.astimezone(dt.timezone(dt.timedelta(hours=3, minutes=30)))
    jy, jm, jd = gregorian_to_jalali(when.year, when.month, when.day)
    text = f"{jy:04d}/{jm:02d}/{jd:02d}"
    if with_time:
        text += f" {when.hour:02d}:{when.minute:02d}"
    return fa_digits(text)


def normalize(text: str) -> str:
    """A comparison form: casefolded, ASCII digits, no half-spaces or marks,
    Persian letters unified, single spaces. Never shown to a person."""
    t = en_digits(text or "")
    t = _STRIP.sub("", t)
    t = t.translate(_LETTERS).translate(_PERCENT)
    # "98 %" and "98%" are the same claim
    t = re.sub(r"(\d)\s+%", r"\1%", t)
    return _SPACES.sub(" ", t).casefold().strip()


# A clause ends at sentence punctuation, a comma, a colon or a bracket. Persian
# puts the finite verb (and with it «نیست» / «نمی‌…») at the END of the clause,
# so the negation of «جایگزینِ مربی» is looked for after the phrase, inside the
# same clause.
_CLAUSE_END = re.compile(r"[.!؟?؛;:\n،,()\[\]«»\"—–]")
# Words that open a NEW clause; a negation behind one of them belongs to
# something else («تضمین می‌دهیم و پشتیبانی نداریم» is not a negated guarantee).
_CLAUSE_JOINERS = frozenset({"و", "اما", "ولی", "بلکه", "که", "تا", "یا", "پس", "ولیکن", "امّا"})
# Negated verb forms, compared after `normalize` (half-spaces are gone):
# نیست/نیستیم/نبود/ندارد/نخواهد/نمی‌کنیم («نمی کنیم» too)/نشد/نکن…
_NEGATED_WORD = re.compile(r"^(?:نیست\w*|نبود\w*|ندار\w*|نخواه\w*|نمی\w*|نشد\w*|نشو\w*|نکن\w*|نباش\w*|نباید)$")
# «نه» / «هرگز» right before the phrase, or a negated verb right before it
# («چغر نمی‌خواهد جایگزین مربی شود»).
_NEGATING_HEAD = re.compile(r"^(?:نه|هرگز|هیچ‌وقت|هیچوقت|نباید)$")
_WORD = re.compile(r"\w+")
_TAIL_WORDS = 6
_HEAD_WORDS = 2


def _is_negated(norm_text: str, start: int, end: int) -> bool:
    """Whether the occurrence `norm_text[start:end]` is stated as NOT true.

    «چغر جایگزینِ مربی نیست» and «نتیجه را تضمین نمی‌کنیم» are exactly the
    answers the brand wants the agent to give, yet both contain the phrase the
    owner banned for the *claim* («جایگزین مربی», «تضمین»). A guard that cannot
    tell a claim from its denial rejects the correct answer to the flagship
    question «جای مربی رو می‌گیره؟» and sends the chat to a human.
    """
    tail = _WORD.findall(_CLAUSE_END.split(norm_text[end:], maxsplit=1)[0])
    for word in tail[:_TAIL_WORDS]:
        if word in _CLAUSE_JOINERS:
            break
        if _NEGATED_WORD.match(word):
            return True
    head_clause = _WORD.findall(_CLAUSE_END.split(norm_text[:start])[-1])
    head = head_clause[-_HEAD_WORDS:]
    for i, word in enumerate(head):
        if word == "نه" and i + 1 < len(head) and head[i + 1] == "تنها":
            continue  # «نه تنها جایگزین مربی است» is a claim, not a denial
        if _NEGATING_HEAD.match(word) or _NEGATED_WORD.match(word):
            return True
    return False


def contains_phrase(text: str, phrase: str, *, ignore_negated: bool = False) -> bool:
    """Whether the normalised `phrase` occurs in the normalised `text`.

    With `ignore_negated`, an occurrence the sentence itself denies
    («چغر جایگزینِ مربی نیست») does not count. Still no stemmer or model: a
    short window around the phrase is read for a negated verb, so the rule is
    cheap, predictable and works when the AI is off.
    """
    p = normalize(phrase)
    if not p:
        return False
    t = normalize(text)
    start = t.find(p)
    while start != -1:
        if not ignore_negated or not _is_negated(t, start, start + len(p)):
            return True
        start = t.find(p, start + 1)
    return False
