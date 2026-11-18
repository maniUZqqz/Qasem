"""Lookup of pronunciations: store lexicon > global additions > shared lexicon.

The shared lexicon is the curated text in ``lexicon_data.py``; ``store`` and
``extra`` are plain ``{word: pn}`` dicts supplied by the caller (the Django layer
loads them from the database), so this module has no Django import.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

from . import phones as P
from .g2p import MARKS, ZWNJ
from .lexicon_data import PHRASES_TEXT, SHARED_TEXT

_ARABIC_FIX = {
    ord("ي"): "ی", ord("ى"): "ی", ord("ك"): "ک", ord("ۀ"): "ه", ord("ة"): "ه",
    ord("أ"): "ا", ord("إ"): "ا", ord("ٱ"): "ا",
}
_TANWIN = "ًٌٍ"


def _nfc(word: str) -> str:
    return word.translate(_ARABIC_FIX).replace("ـ", "")


def canon(word: str) -> str:
    """Key form used for lookups: Persian letters, no short-vowel marks, no tatweel."""
    w = word.translate(_ARABIC_FIX).replace("ـ", "")
    return "".join(c for c in w if c not in MARKS)


def key_variants(word: str) -> list[str]:
    """The spellings a word is looked up under, most specific first."""
    base = canon(word)
    out = [base]
    nz = base.replace(ZWNJ, "")
    if nz != base:
        out.append(nz)
    sp = base.replace(ZWNJ, " ")
    if sp != base:
        out.append(sp)
    return out


@dataclass(frozen=True)
class Entry:
    word: str
    pn: str
    source: str  # 'store' | 'global' | 'shared'
    tag: str = "-"
    category: str = ""
    safe: bool = False   # engines read it right on their own: skipped at depth «lexicon»


#: Words every Persian engine reads right (checked on Piper, Edge and MOSS output);
#: substituting them only adds risk, so they are skipped at depth «lexicon».
SAFE_WORDS = set("""من ما شما است هست بود شد را که از در به با تا بر برای این آن هم هر یا اگر اما ولی چون پس
نیز فقط خیلی بسیار باید شاید نیست دارد دارم داریم دارید دارند ندارد هستم هستیم هستید هستند باشد
باشید کرد کردن بودن شده شدن گفت گفتن داشتن تو سلام""".split())


def _parse_shared() -> tuple[dict[str, Entry], list[str]]:
    entries: dict[str, Entry] = {}
    errors: list[str] = []
    category = ""
    section_safe = False
    for lineno, raw in enumerate(SHARED_TEXT.splitlines(), 1):
        line = raw.strip()
        if not line:
            continue
        if line.startswith("##"):
            category = line[2:].strip()
            section_safe = category.endswith("~")
            category = category.rstrip("~").strip()
            continue
        parts = line.split()
        if len(parts) < 2:
            errors.append(f"line {lineno}: {line!r}")
            continue
        forced = parts[0].startswith("!")
        word = parts[0].lstrip("!").replace("_", ZWNJ)
        pn = parts[1]
        tag = parts[2] if len(parts) > 2 and parts[2] in ("N", "F", "V") else "-"
        if not P.is_valid(pn):
            errors.append(f"line {lineno}: bad PN {pn!r} for {word!r}")
            continue
        entry = Entry(word, pn, "shared", tag, category, safe=(section_safe or canon(word) in SAFE_WORDS) and not forced)
        if any(c in MARKS for c in word):
            # a word written with a vowel mark («نُه» = nine) is kept apart from its
            # unmarked twin («نه» = no); lookups try the marked spelling first.
            entries["\x00" + _nfc(word)] = entry
        else:
            entries[canon(word)] = entry
            plain = canon(word).replace(ZWNJ, "")
            if plain != canon(word):
                entries.setdefault(plain, entry)      # «چربیسوزی» finds «چربی‌سوزی»
    return entries, errors


@lru_cache(maxsize=1)
def shared() -> dict[str, Entry]:
    entries, _ = _parse_shared()
    return entries


@lru_cache(maxsize=1)
def shared_entries() -> tuple[Entry, ...]:
    """The shared lexicon as the curated list reads, one entry per line. ``shared()`` is a LOOKUP table: a word written with a half-space
    is stored twice (as written and without the half-space, «چربیسوزی» finds «چربی‌سوزی»), so its length and its values count some words
    twice («سی‌ام», «علاقه‌مند» showed up twice in the panel and the count 1338 was too big)."""
    seen: set[str] = set()
    out: list[Entry] = []
    for e in shared().values():
        # a word written with a vowel mark («نُه» = nine) stays apart from its unmarked twin («نه» = no), like in the lookup
        key = (_nfc(e.word) if any(c in MARKS for c in e.word) else canon(e.word)).replace(ZWNJ, "")
        if key not in seen:
            seen.add(key)
            out.append(e)
    return tuple(out)


def shared_errors() -> list[str]:
    return _parse_shared()[1]


@lru_cache(maxsize=1)
def phrases() -> dict[tuple[str, ...], str]:
    out: dict[tuple[str, ...], str] = {}
    for raw in PHRASES_TEXT.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        # the written words come first, the PN after them: ONE PN for the whole expression («inSAlA») or one per word
        # («dar mored»). (The old reading took only the last token as the PN, so every entry with a PN per word never matched.)
        k = next((i for i, x in enumerate(parts) if x.isascii()), None)
        if not k:
            continue
        words, pn = parts[:k], " ".join(parts[k:])
        if P.is_valid(pn):
            out[tuple(canon(w.replace("_", ZWNJ)) for w in words)] = pn
    return out


_MAX_PHRASE = 5


class Dictionary:
    """Layered lexicon. ``store``/``extra`` map written word -> PN."""

    def __init__(self, store: dict[str, str] | None = None, extra: dict[str, str] | None = None):
        self._store = {canon(k): v for k, v in (store or {}).items() if P.is_valid(v)}
        self._extra = {canon(k): v for k, v in (extra or {}).items() if P.is_valid(v)}
        for table in (self._store, self._extra):
            for k, v in list(table.items()):
                table.setdefault(k.replace(ZWNJ, ""), v)
        self._store_phr = {tuple(k.split()): v for k, v in self._store.items() if " " in k}
        self._extra_phr = {tuple(k.split()): v for k, v in self._extra.items() if " " in k}

    # --- words
    def lookup(self, word: str) -> Entry | None:
        for k in key_variants(word):
            if k in self._store:
                return Entry(word, self._store[k], "store", "-")
        for k in key_variants(word):
            if k in self._extra:
                return Entry(word, self._extra[k], "global", "-")
        sh = shared()
        if any(c in MARKS for c in word):
            hit = sh.get("\x00" + _nfc(word))
            if hit:
                return hit
        for k in key_variants(word):
            if k in sh:
                return sh[k]
        return None

    def has_owner_words(self) -> bool:
        """Does the store (or the platform) have words of its own? They are honoured at every depth."""
        return bool(self._store or self._extra)

    def tag(self, word: str) -> str:
        e = self.lookup(word)
        return e.tag if e else "-"

    # --- phrases (longest first)
    def phrase_at(self, words: list[str], i: int) -> tuple[int, str, str] | None:
        """If words[i:i+n] is a known phrase return (n, pn, source)."""
        for n in range(min(_MAX_PHRASE, len(words) - i), 1, -1):
            key = tuple(canon(w) for w in words[i:i + n])
            if key in self._store_phr:
                return n, self._store_phr[key], "store"
            if key in self._extra_phr:
                return n, self._extra_phr[key], "global"
            if key in phrases():
                return n, phrases()[key], "shared"
        return None

    def __len__(self) -> int:
        return len(shared_entries()) + len(self._extra) + len(self._store)


def piper_ipa(toks: list[str]) -> str:
    """The phonemes of one word in the alphabet and with the options the Piper renderer hands the voice (espeak's IPA, no glottal stop
    before a word-initial vowel, a geminate written twice): «چهار» -> «tʃahɑr». The panel shows THIS next to the lexicon words, not the
    textbook IPA of an SSML ``<phoneme>`` (that is ``phones.to_ssml_ipa``: «tʃæhɒːɾ», kept as ``ipa_ssml``)."""
    return P.to_ipa(P.strip_stress(toks), glottal="medial", geminate="double")


def all_shared_rows() -> list[dict]:
    """For the panel: the shared lexicon as plain rows (word, pn, respelling, category), each word once."""
    rows = []
    for e in shared_entries():
        toks = P.parse(e.pn)
        rows.append({
            "word": e.word.replace(ZWNJ, "‌"),
            "pn": e.pn,
            "respelling": P.to_respelling(toks, q_letter=P.q_letter_for(e.word)),
            "ipa": piper_ipa(toks),
            "ipa_ssml": P.to_ssml_ipa(toks),
            "category": e.category,
            "tag": e.tag,
        })
    return rows


_WORD_RE = re.compile(r"[؀-ۿ‌]+")


def is_persian_word(token: str) -> bool:
    return bool(_WORD_RE.fullmatch(token))
