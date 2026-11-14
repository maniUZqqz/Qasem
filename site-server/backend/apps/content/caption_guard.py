"""A quality gate for caption text, read from the shop's own rules.

A local model that writes Persian marketing copy is fast and tireless and now
and then wrong in ways a tired owner does not see at 11 p.m.: a price with a
lost digit («۶۰۰٬۰۰ تومان»), the same call-to-action printed twice, a claim the
owner explicitly banned. None of that is worth blocking a draft over, but all
of it is worth *saying* before the draft is copied into a post.

So this module never rewrites and never rejects. It reads a caption and returns
plain warnings; the panel shows them next to the text and the owner decides.
Every rule here is arithmetic or a list the owner wrote («never_say» in the
sales-agent rules) — no model is asked, so the check works when the AI is off.
"""
from __future__ import annotations

import re

from apps.common.fatext import contains_phrase, en_digits, fa_digits, normalize

from . import hashtags as hashtag_tools

#: a Persian/Latin price whose thousands separator is followed by 1-2 digits,
#: i.e. a number that lost its last zero(s): «600,00» «۶۰۰٬۰۰»
_BROKEN_NUMBER = re.compile(r"(?<![\d.,٬،])(\d{1,3}[,٬،]\d{1,2})(?![\d,٬،])")

_EMOJI = re.compile(
    "[\U0001F300-\U0001FAFF\u2600-\u27BF\u2B50\u2B06\u2194-\u21AA\u231A-\u23FF\uFE0F]"
)

#: more than this many emoji in one caption reads as noise, not warmth
MAX_EMOJI = 6

#: a repeated phrase shorter than this is probably a connective, not a copy-paste
MIN_REPEAT_CHARS = 8

#: words that belong in an instruction to an IMAGE model, not in a post:
#: «بدون آدم، فقط فضای باشگاه و تبلت» was printed to followers as if it were copy.
#: Compared in the `normalize` form (no half-space, no kasra).
_PROMPT_LEAK = re.compile(
    r"(بدون\s*(?:آدم|انسان)|فقط\s*فضای|(?:تصویر|عکس)\s*زمینه|پرامپت|\bprompt\b|نمای\s*کلوز)"
)

#: «۶۰۰٬۰۰۰ تومان», «600 هزار تومان»: a price a person must confirm before it is published
_PRICE = re.compile(r"(\d[\d,.٬،]*\s*(?:هزار\s*|میلیون\s*)?(?:تومان|ریال))")

#: a long text should end where a sentence ends (or on an emoji)
_SENTENCE_END = tuple(".!؟?…)»\"'")
_LONG_MIN_CHARS = 120

# ── Round 3 (review of 2026-11-13): errors a reader sees at once that none of the rules above could see ──
_PERSIAN_LETTER = re.compile(r"[\u0600-\u06FF]")
#: ASCII digits inside Persian copy («1300 حرکت»): the shop writes Persian digits everywhere (Latin ones next to «۶۰۰٬۰۰۰» look like a slip)
_LATIN_DIGITS = re.compile(r"(?<![A-Za-z0-9_])[0-9][0-9,.]*(?![A-Za-z_])")
#: a whole sentence in parentheses: the model's remark to the owner, not copy for followers
#: («(مقایسه دربارهٔ روندِ کار است، نه وعدهٔ نتیجه.)» was printed in post #9)
_INTERNAL_NOTE = re.compile(r"\(([^()\n]{18,}?[.؟!])\)")
_DOUBLE_PUNCT = re.compile(r"(?<!\.)\.\.(?!\.)|،،|؟؟|؛؛")
#: claims the brand facts do not make (docs/chagher/brand-facts-fa.md §4 and §6): the sales line stays «بدونِ اغراق»
UNVERIFIED_CLAIMS = ("با یک کلیک", "بدون خطا", "بهترین", "هرگز نمی‌تواند", "۱۰۰٪")
#: «اسکنِ دستگاه … به‌صورتِ خودکار»: the scan registers nothing until the coach confirms
_AUTO_SCAN = re.compile(r"(?:اسکن[^.!؟\n]{0,45}خودکار|خودکار[^.!؟\n]{0,45}اسکن)")
#: the owner's slogan is «با چغر چغر تر شو» (two words); the glued «چغرتر» is the most common deviation
_SLOGAN_GLUED = "چغرتر"
#: everyday spoken forms (compared in the `normalize` form: no half-space) and the written verb forms
_COLLOQUIAL = frozenset("رو میشه میتونه میتونید میتونم بذار بذاری بذارید داره نداره میکنه مینویسه میده میگیره نمیشه".split())
_FORMAL_VERB = re.compile(r"^(?:میکند|میشود|میدهد|میتواند|میکنند|میدارد|میگذارد|میدهند|میگیرد|میکنیم|میشوند|مینویسد)$")
#: the model sometimes writes the NAME of a typing character instead of using it («۳۰ نیم‌فاصله تومان»)
_ARTIFACT = re.compile(r"نیم‌?\s?فاصله|ZWNJ")
_WORDS = re.compile(r"[\w]+")
_HOOK_STRIP = re.compile(r"[\W_]+|" + _EMOJI.pattern)


def _fields(caption) -> list[tuple[str, str]]:
    return [
        ("short_text", caption.short_text or ""),
        ("medium_text", caption.medium_text or ""),
        ("long_text", caption.long_text or ""),
        ("cta", caption.cta or ""),
    ]


def _repeated_phrase(text: str) -> str | None:
    """A sentence/phrase that appears twice in a row (the classic «لینک در بایو.
    لینک در بایو»), or None."""
    parts = [p.strip(" \t\n.!؟?،,;؛…-—") for p in re.split(r"[.!؟?\n]+", normalize(text))]
    parts = [p for p in parts if p]
    for a, b in zip(parts, parts[1:]):
        if len(a) >= MIN_REPEAT_CHARS and a == b:
            return a
    return None


def hook_key(short_text: str) -> str:
    """The opening line in a comparison form (no emoji, punctuation, half-space): two captions that start alike share a key."""
    return _HOOK_STRIP.sub("", normalize(short_text or ""))


def check(caption, banned: list[str] | None = None, hook_counts: dict[str, int] | None = None) -> list[dict]:
    """Warnings for one `Caption` row: `[{"code", "message"}]`, possibly empty.

    `banned` is the shop's «never say» list (one phrase each). Passing it in,
    rather than looking it up here, keeps this function free of queries so a
    list of thirty captions costs one lookup, not thirty.

    `hook_counts` maps `hook_key(short_text)` to how many captions of the SAME product open with that line: the model likes to write the
    same hook for every draft («چرا وقتت رو صرف نوشتن برنامه بذاری؟» ×4); it is passed in for the same reason as `banned`.
    """
    banned = banned or []
    warnings: list[dict] = []
    seen: set[tuple[str, str]] = set()

    def add(code: str, message: str, key: str = "") -> None:
        if (code, key) not in seen:
            seen.add((code, key))
            warnings.append({"code": code, "message": message})

    emoji_total = 0
    for name, text in _fields(caption):
        if not text:
            continue
        for phrase in banned:
            # a sentence that DENIES the claim («ما نتیجه را تضمین نمی‌کنیم») is not the claim
            if contains_phrase(text, phrase, ignore_negated=True):
                add("banned", f"عبارتِ ممنوعِ شما در متن آمده: «{phrase}»", phrase)
        for m in _BROKEN_NUMBER.finditer(en_digits(text)):
            add("broken_number", f"عددِ ناقص: «{m.group(1)}» — احتمالاً صفرِ آخر افتاده است.", m.group(1))
        rep = _repeated_phrase(text)
        if rep:
            add("repeated", f"یک جمله دو بار پشتِ هم آمده: «{rep}»", rep)
        leak = _PROMPT_LEAK.search(normalize(text))
        if leak:
            add(
                "image_prompt",
                f"به نظر می‌رسد دستورِ ساختِ تصویر وارد متن شده: «{leak.group(1)}» — از متنِ پست حذفش کنید.",
                leak.group(1),
            )
        for m in _PRICE.finditer(en_digits(text)):
            add(
                "price_check",
                f"قیمت در متن آمده («{fa_digits(m.group(1).strip())}»): پیش از انتشار با قیمتِ تأییدشدهٔ مالک بسنجید.",
                m.group(1),
            )
        emoji_total += len(_EMOJI.findall(text))
        if _PERSIAN_LETTER.search(text):
            for m in _LATIN_DIGITS.finditer(text):
                add("latin_digits", f"عددِ لاتین در متنِ فارسی: «{m.group(0).strip(',.')}» — با ارقامِ فارسی بنویسید («{fa_digits(m.group(0).strip(',.'))}»).",
                    m.group(0))
        note = _INTERNAL_NOTE.search(text)
        if note:
            add("internal_note", f"به نظر می‌رسد یادداشتِ درونیِ مدل در متن مانده: «({note.group(1)[:50]}…)» — از متنِ پست حذفش کنید.", note.group(1)[:30])
        if _ARTIFACT.search(text):
            add("model_artifact", "کلمهٔ «نیم‌فاصله» (یا ZWNJ) به‌جای خودِ نویسه در متن مانده است — احتمالاً عددی یا واژه‌ای خراب شده.", "artifact")
        if _DOUBLE_PUNCT.search(text):
            add("double_punct", "علامتِ نگارشیِ دوبل («..» یا «،،») در متن هست.", "dp:" + name)
        norm = normalize(text)
        for claim in UNVERIFIED_CLAIMS:
            if contains_phrase(text, claim, ignore_negated=False):
                add("unverified_claim", f"ادعایی که در واقعیت‌های برند نیامده: «{claim}» — پیش از انتشار با مالک بسنجید (لحنِ برند: بدونِ اغراق).", claim)
        scan = _AUTO_SCAN.search(norm)
        if scan:
            add("unverified_claim", "«اسکنِ دستگاه» خودکار معرفی شده؛ طبقِ واقعیت‌های برند تا تأییدِ مربی چیزی ثبت نمی‌شود — این را بنویسید.", "auto-scan")
        if normalize(_SLOGAN_GLUED) in norm:
            add("slogan_spelling", "شعارِ برند «با چغر چغر تر شو» است (دو واژه، با فاصله)؛ «چغرتر» چسبیده نوشته شده.", "slogan")
        words = _WORDS.findall(norm)
        if any(w in _COLLOQUIAL for w in words) and any(_FORMAL_VERB.match(w) for w in words):
            add("register_mix", "لحنِ محاوره‌ای و رسمی در یک متن قاطی شده («رو/می‌شه» کنارِ «می‌کند/را») — یک لحن انتخاب کنید.", "register")

    if hook_counts:
        key = hook_key(caption.short_text or "")
        n = hook_counts.get(key, 0) if key else 0                         # a caption without an opening line is not «a repeat»
        if n > 1:
            add("repeated_hook", f"همین جملهٔ آغازین در {fa_digits(n - 1)} کپشنِ دیگرِ همین محصول هم هست — برای هر پست یک آغازِ تازه بنویسید.")

    long_text = (caption.long_text or "").rstrip()
    if (
        len(long_text) >= _LONG_MIN_CHARS
        and not long_text.endswith(_SENTENCE_END)
        and not _EMOJI.search(long_text[-1])
    ):
        add("truncated", "متنِ بلند ناتمام به نظر می‌رسد (جمله به نقطه نرسیده) — پیش از انتشار تکمیلش کنید.")

    if emoji_total > MAX_EMOJI:
        add("emoji", f"ایموجی زیاد است ({emoji_total}).")
    # Hashtags are stored as plain words («هوش مصنوعی»); the panel writes them as Instagram wants them
    # (#هوش_مصنوعی) when it shows and copies them, so a missing «#» is not something to warn about.
    # What IS wrong is a tag whose words were glued together («#برنامهورزشی»): it matches no search.
    for tag in getattr(caption, "hashtags", None) or []:
        if not isinstance(tag, str):
            continue
        fixed = hashtag_tools.repair(tag)
        if hashtag_tools.clean(fixed) != hashtag_tools.clean(tag):
            add(
                "glued_hashtag",
                f"هشتگِ چسبیده: «{tag}» ← «{fixed}» (در نمایش اصلاح شد؛ با «ویرایش» ذخیره کنید).",
                tag,
            )
        elif hashtag_tools.is_glued(tag):
            add(
                "glued_hashtag",
                f"هشتگِ بلند بدونِ «_»: «{tag}» — اگر چند واژه است با «_» جدایشان کنید.",
                tag,
            )
    return warnings


def banned_for(store) -> list[str]:
    """The store's «never say» phrases, without creating a settings row."""
    from apps.stores.models import SalesAgentSettings

    row = SalesAgentSettings.objects.filter(store=store).first()
    return row.banned_phrases if row else []
