"""Word forms, so «ورزشی» and «ورزشکاران» are recognised as «ورزش».

The first trend-relevance matcher compared whole tokens. Persian attaches
endings to the word («ورزش» → «ورزشی»، «ورزشکار»، «ورزشکاران»، «ورزش‌ها») and a
shop that sells to «مربیان» never matched a trend about a «مربی». A coaching app
(Chagher) therefore showed up as «موبایل و دیجیتال» only and every fitness trend
was labelled «نامرتبط».

The fix is deliberately small and honest — not a morphological analyser:

* :func:`stems` returns a SET of candidate stems for a token: the token itself,
  plus what is left after stripping up to two known endings (Persian plurals,
  adjective/agent endings, a leading «می»/«نمی»; English plural / -ing / -ed / -er).
* Two tokens are "the same word" when their stem sets intersect.
* A stripped form must stay long enough to mean something (``MIN_STEM``), so a
  short word never turns into noise («کتاب» is not «کت»).

A wrong match costs a card the label «مرتبط» that it did not deserve; the card
still shows *which* words matched, so the owner can see and judge it.
"""
from __future__ import annotations

import re
from functools import lru_cache

#: (ending, letters that must remain). Plural endings that are written apart
#: («کفش‌ها») or are unambiguous keep a three-letter stem; «ان» and the
#: adjective / agent / abstract endings need four, because on a short word they
#: are usually part of the word («ایران» is not «ایر», «شیرین» is not «شیر»).
_PERSIAN_SUFFIXES = sorted(
    [("هایی", 3), ("های", 3), ("ها", 3), ("ات", 3), ("ان", 4),
     ("ترین", 4), ("گری", 4), ("گاه", 4), ("کار", 4), ("تر", 4), ("گر", 4), ("یی", 4), ("ی", 4)],
    key=lambda item: -len(item[0]),  # longest first: «هایی» before «ها», «ترین» before «تر»
)
_PERSIAN_PREFIXES = ("نمی", "می")
_ENGLISH_SUFFIXES = ("ing", "ers", "er", "es", "ed", "s")

MIN_STEM_FA = 3
MIN_STEM_EN = 4
_LATIN = re.compile(r"^[a-z0-9]+$")


def _strip_persian(token: str) -> set[str]:
    found = {token}
    frontier = [token]
    for _ in range(2):  # «ورزشکاران» → «ورزشکار» → «ورزش»
        following = []
        for current in frontier:
            for suffix, minimum in _PERSIAN_SUFFIXES:
                if current.endswith(suffix) and len(current) - len(suffix) >= minimum:
                    stem = current[: -len(suffix)]
                    for candidate in ((stem, stem + "ه") if suffix == "ات" else (stem,)):
                        # Arabic-style plural: «مسابقات» is the plural of «مسابقه»
                        if candidate not in found:
                            found.add(candidate)
                            following.append(candidate)
        frontier = following
    return found


def _strip_english(token: str) -> set[str]:
    found = {token}
    for suffix in _ENGLISH_SUFFIXES:
        if token.endswith(suffix) and len(token) - len(suffix) >= MIN_STEM_EN:
            stem = token[: -len(suffix)]
            found.add(stem)
            if len(stem) >= MIN_STEM_EN + 1 and stem[-1] == stem[-2]:
                found.add(stem[:-1])  # «running» → «runn» → «run» (kept only when long enough)
    return found


@lru_cache(maxsize=65536)
def stems(token: str) -> frozenset[str]:
    """Candidate stems of one (already folded) token, the token itself included."""
    if not token:
        return frozenset()
    if _LATIN.match(token):
        return frozenset(_strip_english(token)) if not token.isdigit() else frozenset({token})
    out = set(_strip_persian(token))
    for prefix in _PERSIAN_PREFIXES:
        if token.startswith(prefix) and len(token) - len(prefix) >= MIN_STEM_FA + 1:
            out |= _strip_persian(token[len(prefix):])
    return frozenset(out)


def stem_sequence(folded_text: str) -> list[frozenset[str]]:
    """The stem sets of every token in a folded text, in order."""
    return [stems(token) for token in folded_text.split() if token]


def same_word(a: frozenset[str], b: frozenset[str]) -> bool:
    return not a.isdisjoint(b)


def contains_phrase(sequence: list[frozenset[str]], phrase: list[frozenset[str]]) -> bool:
    """Does ``phrase`` (stem sets of a multi-word term) occur contiguously in ``sequence``?"""
    n = len(phrase)
    if n == 0 or n > len(sequence):
        return False
    for start in range(len(sequence) - n + 1):
        if all(same_word(sequence[start + k], phrase[k]) for k in range(n)):
            return True
    return False
