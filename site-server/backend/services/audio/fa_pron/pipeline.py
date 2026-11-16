"""From written text to a list of tokens with pronunciations.

    text --normalize--> clean text --tokenise--> words and pauses
         --lexicon / homograph / morphology / rules--> PN per word
         --ezafe--> «-e» / «-ye» between noun phrases

The *depth* decides how much we touch:

  ``normalize``  only the text normaliser (numbers, letters, Latin ...). Words are
                 left for the voice engine to pronounce on its own.
  ``lexicon``    + known problem words (shared lexicon, global and store entries,
                 homographs, phrases, and words built from known stems). Every other
                 word is left to the engine. This is the safe default: we only
                 override what we know.
  ``full``       + letter rules for every remaining word, so the whole sentence has a
                 pronunciation (used for engines with no usable Persian front end and
                 for the phoneme input of Piper).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import dictionary as D
from . import g2p, phones as P
from .ezafe import mark_ezafe
from .normalize import NormNotes, normalize

ZWNJ = "‌"
DEPTHS = ("normalize", "lexicon", "full")

_PAUSE_CHARS = "،.؟!"
_PERSIAN = re.compile(r"[؀-ۿ]")


@dataclass
class Token:
    kind: str                      # 'word' | 'pause'
    text: str                      # surface form
    pn: str | None = None          # pronunciation without ezafe, None = engine decides
    source: str = ""               # store|global|shared|phrase|homograph|morph|rule|conj
    tag: str = "-"
    ezafe: bool = False
    pause: str = ""                # 'short' | 'long' | 'para'  (kind == 'pause')
    n_words: int = 1               # phrases cover several written words
    apply: bool = True             # False: known, but the engine reads it right (kept for context)

    def tokens(self, *, stress: bool = False, stress_position: str = "last") -> list[str]:
        """PN tokens, optionally stressed, including the ezafe vowel when marked.

        The stress goes on the last syllable of the *word*; the ezafe is an
        unstressed enclitic, so it is appended after stress is placed.
        """
        if not self.pn:
            return []
        toks = P.parse(self.pn)
        if stress:
            toks = P.with_final_stress(toks, position=stress_position)
        if self.ezafe:
            toks = toks + (["y", "e"] if toks and toks[-1] in P.VOWELS else ["e"])
        return toks


@dataclass
class Prepared:
    original: str
    normalized: str
    tokens: list[Token]
    depth: str
    notes: NormNotes = field(default_factory=NormNotes)
    unknown: list[str] = field(default_factory=list)   # Persian words nobody knows (depth lexicon)

    @property
    def substitutions(self) -> list[Token]:
        return [t for t in self.tokens if t.kind == "word" and t.pn]


# ------------------------------------------------------------------ homographs

#: word -> (default PN, [(PN, triggers within two words)])
HOMOGRAPHS: dict[str, tuple[str, list[tuple[str, set[str]]]]] = {
    "کرم": ("kerem", [
        ("kerm", {"خاکی", "ابریشم", "پیله", "روده", "کدو", "ترب", "میوه", "سیب", "آفت", "حشره",
                  "لارو", "شب‌تاب", "خوردگی", "کرم‌خورده"}),
        ("karam", {"لطف", "جود", "بخشش", "سخاوت", "بزرگواری", "مهر", "کرمش", "احسان"}),
    ]),
    "کشتی": ("keSti", [
        ("kuSti", {"قهرمان", "مسابقه", "ورزش", "ورزشکار", "فرنگی", "آزاد", "پهلوان", "گیر", "گیری",
                   "وزنه", "جودو", "المپیک", "مبارزه", "تیم", "ملی"}),
    ]),
    "مرد": ("mard", [
        ("mord", {"فوت", "مرد.", "درگذشت", "ناگهان", "دیشب", "پدرم", "مادرم", "بابام", "مامانم"}),
    ]),
    "برد": ("bord", [
        ("bard", {"موثر", "وای‌فای", "موشک", "سیگنال", "آنتن", "شبکه", "بی‌سیم", "بلوتوث", "کوتاه",
                  "بلند", "فرستنده", "رادیو", "برد‌کوتاه"}),
    ]),
    "گرد": ("gerd", [("gard", {"غبار", "خاک"})]),
    "ترک": ("tark", [
        ("tork", {"زبان", "قوم", "مردم", "ترکیه", "استانبول", "آنکارا", "آذری", "ترکمن", "فارس", "لر"}),
    ]),
    "علم": ("'elm", [("'alam", {"پرچم", "کردن", "محرم", "عزاداری", "سینه‌زنی"})]),
    "شکر": ("Sekar", [("Sokr", {"خدا", "خدایا", "شکرگزار", "الهی", "کنم", "کردم", "کردیم", "گفتم", "هزار"})]),
}


def _homograph(word: str, words: list[str], i: int) -> str | None:
    key = D.canon(word)
    entry = HOMOGRAPHS.get(key)
    if not entry:
        return None
    default, rules = entry
    lo, hi = max(0, i - 2), min(len(words), i + 3)
    window = {D.canon(w) for j, w in enumerate(words[lo:hi], lo) if j != i}
    for pn, triggers in rules:
        if window & {D.canon(t) for t in triggers}:
            return pn
    # «مرد» at the end of a clause after a person: «او مرد.»
    if key == "مرد" and i + 1 < len(words) and words[i + 1] in ("،", ".", "؟", "!") and i > 0 \
            and D.canon(words[i - 1]) in {"او", "آن", "که", "پدر", "مادر", "بیمار", "پیرمرد", "پیرزن", "ناگهان"}:
        return "mord"
    return default


# ------------------------------------------------------------------ morphology

#: (written suffix, PN after a consonant, PN after a vowel)
_SUFFIXES = [
    ("‌هایی", "hAyi", "hAyi"), ("‌های", "hAye", "hAye"), ("‌ها", "hA", "hA"),
    ("‌ترین", "tarin", "tarin"), ("‌تر", "tar", "tar"),
    ("هایی", "hAyi", "hAyi"), ("های", "hAye", "hAye"), ("ها", "hA", "hA"),
    ("ترین", "tarin", "tarin"), ("تر", "tar", "tar"),
    ("ات", "At", "At"), ("ان", "An", "yAn"), ("ین", "in", "in"),
    ("ی", "i", "yi"),
]


def _final_is_vowel(pn: str) -> bool:
    toks = P.parse(pn)
    return bool(toks) and toks[-1] in P.VOWELS


def _morph(word: str, dic: D.Dictionary, depth: int = 0) -> str | None:
    """stem(+suffix)* built from lexicon stems; None if no confident analysis."""
    if depth > 2:
        return None
    w = D.canon(word)
    # compound with half-spaces: every part known?
    if ZWNJ in w:
        parts = [p for p in w.split(ZWNJ) if p]
        if len(parts) > 1:
            out = []
            for k, p in enumerate(parts):
                e = dic.lookup(p)
                if e:
                    out.append(e.pn)
                    continue
                suf = _suffix_only(p)
                if suf is not None and k > 0:
                    out.append(suf)
                    continue
                m = _morph(p, dic, depth + 1)
                if m is None:
                    return None
                out.append(m)
            return "".join(out)
    for suf, pc, pv in _SUFFIXES:
        s = suf.lstrip(ZWNJ)
        if w.endswith(s) and len(w) - len(s) >= 2:
            stem = w[: -len(s)].rstrip(ZWNJ)
            e = dic.lookup(stem)
            stem_pn = e.pn if e else _morph(stem, dic, depth + 1)
            if stem_pn:
                return stem_pn + (pv if _final_is_vowel(stem_pn) else pc)
    return None


def _suffix_only(part: str) -> str | None:
    for suf, pc, _ in _SUFFIXES:
        if D.canon(suf.lstrip(ZWNJ)) == part:
            return pc
    return None


# ------------------------------------------------------------------ tokeniser

def tokenise(text: str) -> list[Token]:
    toks: list[Token] = []
    for line in text.split("\n"):
        if toks and toks[-1].kind == "word":
            toks.append(Token("pause", "\n", pause="para"))
        elif toks and toks[-1].kind == "pause" and toks[-1].pause != "para":
            toks[-1] = Token("pause", "\n", pause="para")
        for raw in line.split(" "):
            if not raw:
                continue
            trailing = ""
            while raw and raw[-1] in _PAUSE_CHARS:
                trailing = raw[-1] + trailing
                raw = raw[:-1]
            if raw:
                toks.append(Token("word", raw))
            if trailing:
                ch = trailing[-1] if len(trailing) == 1 else next((c for c in "؟!." if c in trailing), "،")
                toks.append(Token("pause", ch, pause="short" if ch == "،" else "long"))
    return toks


# ------------------------------------------------------------------ driver

def _ends_in_vowel_letter(word: str) -> bool:
    w = D.canon(word).rstrip(ZWNJ)
    return bool(w) and w[-1] in "اآویه"


def prepare(text: str, *, depth: str = "lexicon", dictionary: D.Dictionary | None = None,
            ezafe: bool = True) -> Prepared:
    """The whole pronunciation layer for one text."""
    if depth not in DEPTHS:
        raise ValueError(f"depth must be one of {DEPTHS}")
    dic = dictionary or D.Dictionary()
    norm = normalize(text)
    toks = tokenise(norm.text)
    prep = Prepared(original=text, normalized=norm.text, tokens=toks, depth=depth, notes=norm.notes)
    if depth == "normalize":
        return prep

    surface = [t.text for t in toks]
    words_only = [x.text if x.kind == "word" else "" for x in toks]
    out: list[Token] = []
    i = 0
    while i < len(toks):
        t = toks[i]
        if t.kind != "word" or not _PERSIAN.search(t.text):
            out.append(t)
            i += 1
            continue
        # phrases first
        ph = dic.phrase_at(words_only, i)
        if ph:
            n, pn, src = ph
            out.append(Token("word", " ".join(words_only[i:i + n]), pn=pn, source="phrase",
                             tag="-", n_words=n))
            i += n
            continue
        out.append(_resolve_word(t, surface, i, dic, depth, out))
        i += 1
    prep.tokens = out
    if ezafe:
        mark_ezafe(prep.tokens, dic)
        if depth == "full":
            for t in prep.tokens:
                if t.kind == "word" and t.ezafe and not t.pn:
                    t.pn = _rule_pn(t.text)
                    t.source = "rule"
    prep.unknown = [t.text for t in prep.tokens
                    if t.kind == "word" and not t.pn and _PERSIAN.search(t.text)]
    return prep


def _rule_pn(word: str) -> str:
    parts = [p for p in word.split(ZWNJ) if p]
    return "".join(P.join(g2p.rules_to_pn(p)) for p in parts)


def _resolve_word(t: Token, words: list[str], i: int, dic: D.Dictionary, depth: str,
                  out: list[Token]) -> Token:
    w = t.text
    key = D.canon(w)
    # the conjunction «و» is /o/ after a consonant and /vo/ after a vowel
    if key == "و":
        prev = next((x for x in reversed(out) if x.kind == "word"), None)
        prev_pause = bool(out) and out[-1].kind == "pause"
        vowel_before = (prev is not None and not prev_pause and
                        (_final_is_vowel(prev.pn) if prev.pn else _ends_in_vowel_letter(prev.text)))
        # apply=False: the engines that read text keep the written «و» (a respelling «اُ» would be odd); Piper's phoneme input uses the pn
        return Token("word", w, pn="vo" if vowel_before else "o", source="conj", tag="F", apply=False)
    e = dic.lookup(w)
    # marked words («نُه») keep their own reading
    if e and e.source in ("store", "global"):
        return Token("word", w, pn=e.pn, source=e.source, tag=e.tag)
    hg = _homograph(w, words, i)
    if hg:
        return Token("word", w, pn=hg, source="homograph", tag="N")
    if e:
        return Token("word", w, pn=e.pn, source="shared", tag=e.tag,
                     apply=not (e.safe and depth == "lexicon"))
    m = _morph(w, dic)
    if m:
        return Token("word", w, pn=m, source="morph", tag="N")
    if depth == "full":
        return Token("word", w, pn=_rule_pn(w), source="rule", tag="-")
    return Token("word", w, tag="-")
