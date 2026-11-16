"""The phoneme layer: one internal notation («PN») and conversions to everything else.

PN is a small ASCII notation for Tehrani Persian, one character per phoneme, so a
lexicon can be written (and reviewed) by a person who does not read IPA:

    vowels      a = æ (short a)   e   o   A = ɒː (long ā)   i = iː   u = uː   ow
    consonants  b p t d k g  q = غ/ق  ' = ع/ء (glottal stop)  f v s z
                S = ش   Z = ژ   x = خ   h   C = چ   j = ج   m n r l   y = ی
    doubling    a doubled consonant is a geminate (tashdid): «tt»
    separators  space, '-' and '.' are ignored; 'ˈ' marks the stressed syllable

«ey» needs no symbol of its own: it is simply «e» then «y».

From PN this module produces
  * IPA for the espeak-ng based Piper voices   (``to_ipa``),
  * Persian script with short-vowel marks      (``to_respelling``) for engines
    that read text, and
  * SSML-friendly IPA                          (``to_ssml_ipa``).
And the other way round: ``parse`` reads PN, ``pn_from_respelling`` lives in
``g2p.py`` because it needs the letter rules.
"""
from __future__ import annotations

VOWELS = {"a", "e", "o", "A", "i", "u", "ow"}
CONSONANTS = set("bptdkgq'fvszSZxhCjmnrly")
STRESS = "ˈ"
_IGNORED = set(" -.·_")

# ---------------------------------------------------------------- parsing


def parse(pn: str) -> list[str]:
    """PN string -> list of phoneme tokens (stress mark kept as «ˈ»)."""
    out: list[str] = []
    i = 0
    pn = pn or ""
    while i < len(pn):
        ch = pn[i]
        if ch in _IGNORED:
            i += 1
        elif ch == STRESS or ch == "^":
            out.append(STRESS)
            i += 1
        elif ch == "o" and pn[i + 1:i + 2] == "w":
            out.append("ow")
            i += 2
        elif ch in "aeoAiu" or ch in CONSONANTS:
            out.append(ch)
            i += 1
        else:
            raise ValueError(f"bad PN symbol {ch!r} in {pn!r}")
    return out


def is_valid(pn: str) -> bool:
    try:
        parse(pn)
        return True
    except ValueError:
        return False


def join(tokens: list[str]) -> str:
    return "".join(tokens)


def is_vowel(tok: str) -> bool:
    return tok in VOWELS


def syllable_count(tokens: list[str]) -> int:
    return sum(1 for t in tokens if t in VOWELS)


def strip_stress(tokens: list[str]) -> list[str]:
    return [t for t in tokens if t != STRESS]


def with_final_stress(tokens: list[str], *, before_vowel: bool = True, position: str = "last") -> list[str]:
    """Place the stress mark on the last (or first) syllable.

    Persian word stress is on the last syllable of nouns and adjectives. espeak-ng
    writes the mark directly *before the vowel* («k ˈe t ɑ b»), which is what the
    Piper voices were trained on, so that is the default; IPA proper puts it before
    the onset consonant (``before_vowel=False``). One-syllable words get no mark.
    """
    toks = strip_stress(tokens)
    vowel_idx = [i for i, t in enumerate(toks) if t in VOWELS]
    if len(vowel_idx) < 2:
        return toks
    nucleus = vowel_idx[-1] if position == "last" else vowel_idx[0]
    at = nucleus
    if not before_vowel and nucleus - 1 >= 0 and toks[nucleus - 1] not in VOWELS:
        at = nucleus - 1
    return toks[:at] + [STRESS] + toks[at:]


# ---------------------------------------------------------------- IPA

#: What espeak-ng's Persian voice ("fa") prints, i.e. what the Piper fa_IR models were
#: trained on (measured with piper's own phonemizer, see docs/pronunciation/engines-fa.md):
#:   «سلام» -> s a l ˈ ɑ m     «کتاب» -> k ˈ e t ɑ b      «دوست» -> d ˈ u ː s t
#:   «چغر» -> t ʃ ˈ a q 1 a r (غ/ق is the two symbols «q» «1»)   «مربی» -> m o r ˈ a b b i
#: Every symbol is a single code point that exists in the voices' phoneme_id_map.
IPA_ESPEAK = {
    "a": "a", "e": "e", "o": "o", "A": "ɑ", "i": "i", "u": "uː", "ow": "oː",
    "b": "b", "p": "p", "t": "t", "d": "d", "k": "k", "g": "ɡ", "q": "q1",
    "'": "ʔ", "f": "f", "v": "v", "s": "s", "z": "z", "S": "ʃ", "Z": "ʒ",
    "x": "x", "h": "h", "C": "tʃ", "j": "dʒ", "m": "m", "n": "n", "r": "r",
    "l": "l", "y": "j",
}

#: Standard (textbook) IPA for SSML ``<phoneme alphabet="ipa">`` - Azure wants
#: real IPA, not espeak's variant.
IPA_STANDARD = dict(IPA_ESPEAK)
IPA_STANDARD.update({"a": "æ", "A": "ɒː", "i": "iː", "u": "uː", "ow": "ow", "q": "ɢ", "r": "ɾ"})


def _ipa(tokens: list[str], table: dict[str, str], *, glottal: str = "keep",
         geminate: str = "length") -> str:
    out: list[str] = []
    prev: str | None = None
    for t in tokens:
        if t == STRESS:
            out.append(STRESS)
            prev = None
            continue
        if t == "'":
            if glottal == "drop":
                continue
            if glottal == "medial" and not any(x != STRESS for x in out):
                continue          # espeak never writes a glottal stop before a word-initial vowel; the voice never heard one
        if t in CONSONANTS and prev == t:
            # tashdid: a geminate is a longer consonant
            if geminate == "length":
                out.append("ː")
            elif geminate == "double":
                out.append(table.get(t, t))
            # geminate == "drop": say it once
            continue
        out.append(table.get(t, t))
        prev = t
    return "".join(out)


def to_ipa(tokens: list[str], *, glottal: str = "keep", geminate: str = "double",
           table: dict[str, str] | None = None) -> str:
    """PN tokens -> espeak-flavoured IPA (what the Piper fa_IR voices were trained on)."""
    return _ipa(tokens, table or IPA_ESPEAK, glottal=glottal, geminate=geminate)


def to_ssml_ipa(tokens: list[str], *, glottal: str = "keep") -> str:
    """PN tokens -> standard IPA for an SSML ``<phoneme alphabet="ipa" ph="...">``."""
    return _ipa(strip_stress(tokens), IPA_STANDARD, glottal=glottal, geminate="length")


# ---------------------------------------------------------------- respelling

_LETTER = {
    "b": "ب", "p": "پ", "t": "ت", "d": "د", "k": "ک", "g": "گ", "q": "ق", "'": "ع",
    "f": "ف", "v": "و", "s": "س", "z": "ز", "S": "ش", "Z": "ژ", "x": "خ", "h": "ه",
    "C": "چ", "j": "ج", "m": "م", "n": "ن", "r": "ر", "l": "ل", "y": "ی",
}
FATHA, KASRA, DAMMA, SUKUN, SHADDA = "َ", "ِ", "ُ", "ْ", "ّ"
_SHORT = {"a": FATHA, "e": KASRA, "o": DAMMA}


def to_respelling(tokens: list[str], *, sukun: bool = False, final_he: bool = True) -> str:
    """PN tokens -> Persian script with the short vowels written out.

    «ma'ni» -> «مَعنی», «xAne» -> «خانه», «kitAb» -> «کیتاب» is avoided: «i» is the
    long vowel and is written «ی», short «e» is the kasra mark.
    """
    toks = strip_stress(tokens)
    out: list[str] = []
    n = len(toks)
    i = 0
    while i < n:
        t = toks[i]
        prev_is_cons = i > 0 and toks[i - 1] in CONSONANTS
        nxt = toks[i + 1] if i + 1 < n else None
        if t in CONSONANTS:
            letter = _LETTER[t]
            if nxt == t:  # geminate: one letter + shadda
                out.append(letter + SHADDA)
                i += 2
                continue
            out.append(letter)
            if sukun and nxt in CONSONANTS and nxt is not None:
                out.append(SUKUN)
            i += 1
            continue
        # vowels
        at_start = i == 0
        if t in _SHORT:
            if t == "e" and i == n - 1 and final_he and prev_is_cons and toks[i - 1] != "'":
                out.append("ه")  # word-final «e» is the silent «ه»
            elif at_start:
                out.append("ا" + _SHORT[t])
            else:
                out.append(_SHORT[t])
        elif t == "A":
            out.append("آ" if at_start else "ا")
        elif t == "i":
            out.append("ای" if at_start else "ی")
        elif t == "u":
            out.append("او" if at_start else "و")
        elif t == "ow":
            out.append(("ا" if at_start else "") + FATHA + "و" + SUKUN)
        i += 1
    return "".join(out)


def pn_to_syllables(tokens: list[str]) -> list[list[str]]:
    """Split PN into syllables: a single consonant between vowels starts the next one."""
    toks = strip_stress(tokens)
    nuclei = [i for i, t in enumerate(toks) if t in VOWELS]
    if not nuclei:
        return [toks] if toks else []
    bounds = [0]
    for a, b in zip(nuclei, nuclei[1:]):
        between = b - a - 1
        bounds.append(a + 1 + max(0, between - 1))
    bounds.append(len(toks))
    return [toks[bounds[k]:bounds[k + 1]] for k in range(len(bounds) - 1)]
