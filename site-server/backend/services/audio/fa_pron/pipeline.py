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
from . import g2p, latin, phones as P
from .ezafe import mark_ezafe
from .normalize import NormNotes, normalize

ZWNJ = "‌"
KASRA = "ِ"
HAMZA_ABOVE = "ٔ"
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
    written_ezafe: bool = False    # the writer put the ezafe on the word («هٔ», «ِ», «ه‌ی»): always honoured

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
                   "وزنه", "جودو", "المپیک", "مبارزه", "تیم", "ملی", "کشتی‌گیر", "کشتی‌گیران", "کشتی‌گیری",
                   "تشک", "حریف", "رقیب", "زورخانه", "گود", "فدراسیون"}),
    ]),
    "مرد": ("mard", [
        ("mord", {"فوت", "مرد.", "درگذشت", "ناگهان", "دیشب", "پدرم", "مادرم", "بابام", "مامانم", "مرحوم", "مرحومه",
                  "تشییع", "جنازه", "قبرستان", "ختم", "کشته", "جان"}),
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
    # the letter D (vitamin D) is «دی» too: the lexicon has the month Dey
    "دی": ("dey", [("di", {"ویتامین", "ویتامینی", "کلسیم", "اچ", "دبلیو"})]),
}

#: forms that cannot be listed one by one (conjugated verbs, possessive endings): word -> [(PN, regex on a neighbour)]
_RE_GIR = re.compile(r"^(?:ن?می‌?|ب|ن)?(?:گیر|گرف)")            # گرفتن: کشتی گرفت / می‌گیرد / بگیر / نگیر / گرفته
HOMOGRAPH_PATTERNS: dict[str, list[tuple[str, "re.Pattern[str]"]]] = {
    "کشتی": [("kuSti", _RE_GIR)],
}

HOMOGRAPH_TAGS = {"mord": "V", "di": "F"}          # read as a verb / a letter name: no ezafe in front of it

_PUNCT = set("،.؟!") | {""}
#: after «مرد» one of these starts a new clause: «پدرش مرد و ...»
_CLAUSE_JOIN = {"و", "که", "اما", "ولی", "تا", "پس", "بعد", "سپس", "در", "از", "به", "با", "پیش", "قبل", "همان", "همین"}
#: who dies in «X مرد»: a person word, a kinship word with its possessive ending, or a time word («بعد از یک سال مرد»)
_RE_KIN = re.compile(r"^(?:پدر|مادر|پدربزرگ|مادربزرگ|عمو|دایی|خاله|عمه|برادر|خواهر|همسر|شوهر|پسر|دختر|بابا|مامان|"
                     r"پیرمرد|پیرزن|بیمار|مریض|مادربزرگم|پدربزرگم|دوستم|همسایه)(?:م|ت|ش|مان|تان|شان)?$")
_DIES_AFTER = {D.canon(w) for w in (
    "او", "وی", "ایشان", "که", "همه", "ناگهان", "بالاخره", "سرانجام", "آخر", "نهایتا", "نهایتاً", "دیروز", "دیشب", "امروز",
    "پارسال", "پیرارسال", "سال", "ماه", "هفته", "روز", "شب", "بعد", "پس", "زود", "دیر", "اونجا", "آنجا", "همان‌جا",
    "بیچاره", "مرحوم", "قهرمان", "پهلوان", "شاعر", "نویسنده", "هنرمند", "پادشاه", "سرباز")}


def _window(words: list[str], i: int, span: int = 2) -> list[str]:
    lo, hi = max(0, i - span), min(len(words), i + span + 1)
    return [D.canon(w) for j, w in enumerate(words[lo:hi], lo) if j != i]


def _mard_or_mord(words: list[str], i: int) -> str:
    """«مرد»: a man (mard) or died (mord). The verb ends its clause and follows who died or when."""
    prev = D.canon(words[i - 1]) if i > 0 else ""
    nxt = D.canon(words[i + 1]) if i + 1 < len(words) else ""
    ends_clause = nxt in _PUNCT or nxt in _CLAUSE_JOIN
    if ends_clause and prev not in _PUNCT and (_RE_KIN.match(prev) or prev in _DIES_AFTER):
        return "mord"
    return "mard"


def _homograph(word: str, words: list[str], i: int) -> str | None:
    key = D.canon(word)
    entry = HOMOGRAPHS.get(key)
    if not entry:
        return None
    default, rules = entry
    near = _window(words, i)
    window = set(near)
    for pn, triggers in rules:
        if window & {D.canon(t) for t in triggers}:
            return pn
    if key == "مرد":
        return _mard_or_mord(words, i)
    if key == "کشتی":
        nxt = D.canon(words[i + 1]) if i + 1 < len(words) else ""
        if nxt == "را":                  # «کشتی را گرفتند»: they seized the ship
            return default
        if any(rx.match(w) for pn, rx in HOMOGRAPH_PATTERNS["کشتی"] for w in near):
            return "kuSti"
    return default


# ------------------------------------------------------------------ morphology

#: (written suffix, PN after a consonant, PN after a vowel)
_SUFFIXES = [
    ("‌هایی", "hAyi", "hAyi"), ("‌های", "hAye", "hAye"), ("‌ها", "hA", "hA"),
    ("‌ترین", "tarin", "tarin"), ("‌تر", "tar", "tar"),
    ("هایی", "hAyi", "hAyi"), ("های", "hAye", "hAye"), ("ها", "hA", "hA"),
    ("ترین", "tarin", "tarin"), ("تر", "tar", "tar"),
    ("ات", "At", "At"), ("ان", "An", "yAn"), ("ین", "in", "in"),
    ("یی", "yi", "yi"),            # «رضایی» = «رضا» + one ی (the first ی is only the glide): never two suffixes
    ("ی", "i", "yi"),
]
#: «خانه‌ای»: the written suffix after a half-space; the word «ای» (vocative) is never meant there
_ZWNJ_SUFFIXES = {"ای": "yi"}


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
                if k > 0 and p in _ZWNJ_SUFFIXES:          # «خانه‌ای»: the suffix, not the word «ای»
                    out.append(_ZWNJ_SUFFIXES[p])
                    continue
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
            if s == "ی" and stem.endswith("ی"):
                continue                  # «رضای» is not a stem: its ی is the glide of the suffix itself («رضایی»)
            e = dic.lookup(stem)
            stem_pn = e.pn if e else _morph(stem, dic, depth + 1)
            if stem_pn:
                return stem_pn + (pv if _final_is_vowel(stem_pn) else pc)
    return None


def _suffix_only(part: str) -> str | None:
    if part in _ZWNJ_SUFFIXES:
        return _ZWNJ_SUFFIXES[part]
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
        if dic.has_owner_words():
            prep.tokens = _owner_words_only(toks, dic)       # the owner's own words are honoured at every depth («fix it, listen again»)
        return prep

    surface = [t.text for t in toks]
    words_only = [x.text if x.kind == "word" else "" for x in toks]
    stems = [explicit_ezafe(w)[1] if w else "" for w in words_only]       # «برنامه‌ی» -> «برنامه»: phrases are written without the mark
    out: list[Token] = []
    i = 0
    while i < len(toks):
        t = toks[i]
        if t.kind != "word" or not _PERSIAN.search(t.text):
            out.append(t)
            i += 1
            continue
        # phrases first
        ph = dic.phrase_at(stems, i)
        if ph:
            n, pn, src = ph
            last_ez = explicit_ezafe(words_only[i + n - 1])[0]
            per_word = pn.split()
            if n > 1 and len(per_word) == n:
                # one PN per written word: every word keeps its own stress and its own place in the output
                for k, one in enumerate(per_word):
                    out.append(Token("word", stems[i + k], pn=one, source="phrase", tag="-", ezafe=last_ez and k == n - 1,
                                     written_ezafe=last_ez and k == n - 1))
            else:
                out.append(Token("word", " ".join(stems[i:i + n]), pn=pn, source="phrase",
                                 tag="-", n_words=n, ezafe=last_ez, written_ezafe=last_ez))
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


def _owner_words_only(toks: list[Token], dic: D.Dictionary) -> list[Token]:
    """Depth «normalize»: nothing of ours is said EXCEPT what the store (or the platform) wrote in its own lexicon."""
    words_only = [x.text if x.kind == "word" else "" for x in toks]
    stems = [explicit_ezafe(w)[1] if w else "" for w in words_only]
    out: list[Token] = []
    i = 0
    while i < len(toks):
        t = toks[i]
        if t.kind == "word" and _PERSIAN.search(t.text):
            ph = dic.phrase_at(stems, i)
            if ph and ph[2] in ("store", "global"):
                n, pn, src = ph
                ez = explicit_ezafe(words_only[i + n - 1])[0]
                out.append(Token("word", " ".join(stems[i:i + n]), pn=pn, source=src, tag="-", n_words=n, ezafe=ez, written_ezafe=ez))
                i += n
                continue
            ez, stem = explicit_ezafe(t.text)
            word = stem if ez and stem else t.text
            e = dic.lookup(word)
            if e and e.source in ("store", "global"):
                out.append(Token("word", word, pn=e.pn, source=e.source, tag=e.tag, ezafe=ez, written_ezafe=ez))
                i += 1
                continue
        out.append(t)
        i += 1
    return out


def _rule_pn(word: str) -> str:
    parts = [p for p in word.split(ZWNJ) if p]
    return "".join(P.join(g2p.rules_to_pn(p)) for p in parts)


def explicit_ezafe(word: str) -> tuple[bool, str]:
    """Is the ezafe WRITTEN on this word? -> (flag, the word without the mark).

    «برنامهٔ» (hamza above), «مربیِ» (kasra) and the everyday «برنامه‌ی» (a half-space and a ی after a word that ends in «ه»)
    all mean "-e / -ye comes here". The mark is the writer's word, so it is always honoured (a missing ezafe in the
    lexicon of the NEXT word must not drop it) and the «ی» of «ه‌ی» is not the indefinite «ی» of «برنامه‌ای».
    """
    if len(word) < 3:
        return False, word
    if word.endswith(HAMZA_ABOVE) or word.endswith(KASRA):
        return True, word[:-1]
    if word.endswith(ZWNJ + "ی"):
        stem = word[:-2]
        if stem.endswith("ه") and len(stem) >= 2:
            return True, stem
    return False, word


def _resolve_word(t: Token, words: list[str], i: int, dic: D.Dictionary, depth: str,
                  out: list[Token]) -> Token:
    ez, stem = explicit_ezafe(t.text)
    if ez and stem:
        tok = _resolve_core(Token("word", stem), stem, words, i, dic, depth, out)
        tok.ezafe = tok.written_ezafe = True
        if tok.tag == "V":                # a verb never takes an ezafe: the mark belongs to a homograph read the other way
            tok.tag = "N"
        return tok
    return _resolve_core(t, t.text, words, i, dic, depth, out)


def _resolve_core(t: Token, w: str, words: list[str], i: int, dic: D.Dictionary, depth: str,
                  out: list[Token]) -> Token:
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
    lp = latin.letters_pn(w)
    if lp:
        # a spelled-out acronym («پی‌دی‌اف»): the letter names, never the words «پی» (footprint) and «دی» (the month)
        return Token("word", w, pn=lp, source="letters", tag="F", apply=False)
    hg = _homograph(w, words, i)
    if hg:
        return Token("word", w, pn=hg, source="homograph", tag=HOMOGRAPH_TAGS.get(hg, "N"))
    if e:
        return Token("word", w, pn=e.pn, source="shared", tag=e.tag,
                     apply=not (e.safe and depth == "lexicon"))
    m = _morph(w, dic)
    if m:
        return Token("word", w, pn=m, source="morph", tag="N")
    if depth == "full":
        return Token("word", w, pn=_rule_pn(w), source="rule", tag="-")
    return Token("word", w, tag="-")
