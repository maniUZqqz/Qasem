"""Persian letters -> PN (the fallback grapheme-to-phoneme rules).

Persian script leaves the short vowels out, so no rule set can be right for every
word; the shared lexicon (``lexicon.py``) is consulted first and these rules are
the net underneath it. They get the *systematic* problems right, which is where
voice engines fail most audibly:

* «ع» and «ء» are a glottal stop, never a vowel and never dropped silently;
* word-final «ه» is the vowel /e/ after a consonant («خانه», «برنامه») and the
  consonant /h/ after a long vowel («راه», «کوه», «سیاه»);
* «و» is /v/ at the start of a word and before «ا», silent in «خوا-», long /u/
  between consonants («دوست»), and /ow/ in «او-» words;
* «ی» is /y/ at the start of a word and after «ا», /i/ elsewhere, «iy» before «ا»;
* a consonant cluster Persian cannot say is broken with the default vowel /a/,
  from the left before an explicit vowel («مدرسه» -> mad-ra-se) and from the
  right at the end of a word without one («چغر» -> Ca-qar).

``respelling_to_pn`` is the same machinery in "trust the marks" mode: it turns
what the owner types in the panel («مَعنی», «چِغِر») into PN.
"""
from __future__ import annotations

from . import phones as P

ZWNJ = "‌"
FATHA, KASRA, DAMMA = "َ", "ِ", "ُ"
SHADDA, SUKUN = "ّ", "ْ"
TAN_A, TAN_I, TAN_U = "ً", "ٍ", "ٌ"
DAGGER, HAMZA_ABOVE, MADDA = "ٰ", "ٔ", "ٓ"
MARKS = {FATHA, KASRA, DAMMA, SHADDA, SUKUN, TAN_A, TAN_I, TAN_U, DAGGER, HAMZA_ABOVE, MADDA}

CONS_MAP = {
    "ب": "b", "پ": "p", "ت": "t", "ث": "s", "ج": "j", "چ": "C", "ح": "h", "خ": "x",
    "د": "d", "ذ": "z", "ر": "r", "ز": "z", "ژ": "Z", "س": "s", "ش": "S", "ص": "s",
    "ض": "z", "ط": "t", "ظ": "z", "غ": "q", "ف": "f", "ق": "q", "ک": "k", "گ": "g",
    "ل": "l", "م": "m", "ن": "n", "ع": "'", "ء": "'", "ئ": "'", "ؤ": "'", "أ": "'",
    "إ": "'", "ة": "t",
}
_VOWEL_LETTERS = set("اآویٰ")
_MARK_VOWEL = {FATHA: "a", KASRA: "e", DAMMA: "o"}


def strip_marks(word: str) -> str:
    return "".join(c for c in word if c not in MARKS)


def has_marks(word: str) -> bool:
    return any(c in MARKS for c in word if c not in (SHADDA,)) or SHADDA in word


class _U:
    """One letter with the marks written on it."""
    __slots__ = ("ch", "vowel", "shadda", "sukun", "tan", "ezafe")

    def __init__(self, ch: str):
        self.ch = ch
        self.vowel: str | None = None  # 'a' 'e' 'o' from a short-vowel mark
        self.shadda = False
        self.sukun = False
        self.tan: str | None = None  # 'an' 'en' 'on'
        self.ezafe = False  # hamza-above: «خانهٔ»


def _units(word: str) -> list[_U]:
    units: list[_U] = []
    for ch in word:
        if ch in MARKS:
            if not units:
                continue
            u = units[-1]
            if ch in _MARK_VOWEL:
                u.vowel = _MARK_VOWEL[ch]
            elif ch == SHADDA:
                u.shadda = True
            elif ch == SUKUN:
                u.sukun = True
            elif ch == TAN_A:
                u.tan = "an"
            elif ch == TAN_I:
                u.tan = "en"
            elif ch == TAN_U:
                u.tan = "on"
            elif ch == HAMZA_ABOVE:
                u.ezafe = True
            elif ch == DAGGER:
                units.append(_U("ا"))
            continue
        units.append(_U(ch))
    return units


def _is_vowel_item(x: str) -> bool:
    return x in P.VOWELS


def rules_to_pn(word: str, *, trust_marks: bool = False) -> list[str]:
    """Letter rules for one ZWNJ-free word. Returns PN tokens (no stress)."""
    units = _units(word)
    n = len(units)
    explicit = trust_marks or any(u.vowel or u.sukun for u in units)
    items: list[str] = []  # PN tokens; consonants and vowels interleaved
    ez_tail: list[str] = []

    def prev_item() -> str | None:
        return items[-1] if items else None

    i = 0
    while i < n:
        u = units[i]
        ch = u.ch
        prv = units[i - 1].ch if i > 0 else None
        nxt = units[i + 1].ch if i + 1 < n else None
        nxt2 = units[i + 2].ch if i + 2 < n else None
        last = i == n - 1

        def emit_cons(sym: str, unit: _U = u):
            items.append(sym)
            if unit.shadda:
                items.append(sym)

        if ch == "آ":
            items.append("A")
        elif ch == "ا":
            if i == 0:
                if u.vowel:
                    items.append(u.vowel)
                elif nxt == "ی" and (nxt2 is None or nxt2 not in _VOWEL_LETTERS) and n > 2:
                    items.append("i")  # ایران، ایمان، ایجاد
                    i += 2
                    continue
                elif nxt == "و" and nxt2 is not None and nxt2 not in "اآی":
                    items.append("ow")  # اوج، اوقات
                    i += 2
                    continue
                elif nxt == "و" and nxt2 is None:
                    items.append("u")  # «او»
                    i += 2
                    continue
                else:
                    items.append("e")
            elif u.tan == "an" and last:
                items.extend(["a", "n"])  # مثلاً: the alef is only the seat of the tanwin
                i += 1
                continue
            else:
                items.append("A")
        elif ch == "و":
            role = _vav_role(units, i, items)
            if u.vowel and role != "silent":
                items.append("v")
                items.append(u.vowel)
            elif role == "v":
                emit_cons("v")
            elif role == "u":
                items.append("u")
            elif role == "o":
                items.append("o")
            elif role == "silent":
                pass
        elif ch == "ی":
            if u.vowel:
                emit_cons("y")
                items.append(u.vowel)
            elif i == 0:
                emit_cons("y")
            elif prv in ("ا", "آ"):
                emit_cons("y")
            elif prv == "و" and items and items[-1] in ("u", "o", "ow"):
                emit_cons("y")
            elif nxt in ("ا", "آ") and items and items[-1] in P.CONSONANTS:
                items.extend(["i", "y"])
            elif (nxt == "ه" and nxt2 is None and not units[i + 1].vowel
                  and items and items[-1] in P.CONSONANTS):
                items.extend(["i", "y"])  # تغذیه، قضیه، حاشیه
            elif nxt == "ه" and nxt2 is None and items and items[-1] in P.VOWELS:
                emit_cons("y")  # همسایه: after ā the ی is only the glide
            else:
                items.append("i")
        elif ch == "ه":
            if i == 0:
                emit_cons("h")
            elif last:
                if u.ezafe:
                    items.extend(["e"])
                    ez_tail = ["y", "e"]
                elif prev_item() in P.CONSONANTS:
                    items.append("e")
                elif prev_item() in P.VOWELS:
                    items.append("h")
                else:
                    items.append("h")
            else:
                emit_cons("h")
        elif ch in CONS_MAP:
            sym = CONS_MAP[ch]
            emit_cons(sym)
        elif ch in ("ـ", "‍", "‎", "‏"):
            pass
        else:
            # digits, latin letters, punctuation reach here only by mistake
            pass
        # explicit short vowel mark written on a consonant letter
        if ch in CONS_MAP and u.vowel:
            items.append(u.vowel)
        if ch in CONS_MAP and u.tan and not (ch == "ا"):
            items.extend({"an": ["a", "n"], "en": ["e", "n"], "on": ["o", "n"]}[u.tan])
        i += 1

    if not explicit:
        items = _insert_vowels(items)
    items.extend(ez_tail)
    return items


def _vav_role(units: list[_U], i: int, items: list[str]) -> str:
    prv = units[i - 1].ch if i > 0 else None
    nxt = units[i + 1].ch if i + 1 < len(units) else None
    if i == 0:
        return "v"
    if prv == "خ" and nxt in ("ا", "آ"):
        return "silent"
    if prv == "خ" and nxt == "ی":
        return "silent"
    if prv in ("ا", "آ"):
        return "v"
    if items and items[-1] in ("i", "y") and (nxt is None or nxt in "هاآ"):
        return "v"  # میوه، شیوه، دیو
    if nxt in ("ا", "آ"):
        return "v"
    if prv == "خ":
        return "o"  # خود، خوش، خورد (خوب and خون are in the lexicon)
    return "u"


def _insert_vowels(items: list[str]) -> list[str]:
    """Break consonant clusters Persian cannot pronounce with the default vowel /a/."""
    if not items:
        return items
    out: list[str] = []
    # split into runs: consonant runs separated by vowels
    runs: list[tuple[str, list[str]]] = []
    cur: list[str] = []
    for t in items:
        if t in P.CONSONANTS:
            cur.append(t)
        else:
            if cur:
                runs.append(("C", cur))
                cur = []
            runs.append(("V", [t]))
    if cur:
        runs.append(("C", cur))

    for idx, (kind, toks) in enumerate(runs):
        if kind == "V":
            out.extend(toks)
            continue
        first = idx == 0
        final = idx == len(runs) - 1
        if first and final:  # no vowel at all: Ca-qar, daf-tar, vaqt
            if len(toks) == 3 and "".join(toks[1:]) in CODA_CLUSTERS:
                out.extend([toks[0], "a", toks[1], toks[2]])
            else:
                out.extend(_pair_from_right(toks))
        elif first:  # initial run before an explicit vowel
            out.extend(_pair_from_left(toks[:-1]) + toks[-1:])
        elif final:
            if len(toks) >= 3:  # keep two as coda, the third starts a new syllable
                out.extend(toks[:-2] + _pair_from_right(toks[-2:]))
            elif len(toks) == 2 and "".join(toks) not in CODA_CLUSTERS:
                out.extend([toks[0], "e", toks[1]])  # خواهش، دانش، عاشق: an impossible ending gets its vowel
            else:
                out.extend(toks)
        else:
            if len(toks) >= 4:
                out.extend(toks[:2] + ["a"] + toks[2:])
            else:
                out.extend(toks)
    return out


#: Two-consonant endings Persian really has («وقت», «دست», «سخت», «رنگ», «شهر»).
CODA_CLUSTERS = {
    "st", "ft", "xt", "St", "qt", "pt", "kt", "nd", "nj", "ng", "nk", "nt", "ns", "nS",
    "nz", "rd", "rt", "rz", "rs", "rk", "rg", "rq", "rf", "rm", "rn", "rj", "rC", "rS",
    "rx", "rb", "rp", "rl", "lm", "lq", "ls", "lt", "lk", "ld", "lf", "lb", "mp", "mb",
    "mz", "ms", "fz", "sk", "sp", "sm", "xm", "qm", "zm", "Sm", "hr", "hn", "hm", "hl",
    "sr", "tr", "br", "fr", "kr", "gr", "xr", "dr", "Sr", "'r", "'l", "'m", "'n", "'d",
    "'b", "'s", "'t", "'q", "'z", "'f", "'k", "'x", "'j", "'S", "'h", "'g", "'p", "'C",
}


def _pair_from_left(cons: list[str]) -> list[str]:
    """«m d r» -> m a d r a ...  syllables CVC CVC, a leftover gets CV."""
    out: list[str] = []
    i = 0
    while i < len(cons):
        if i + 1 < len(cons):
            out.extend([cons[i], "a", cons[i + 1]])
            i += 2
        else:
            out.extend([cons[i], "a"])
            i += 1
    return out


def _pair_from_right(cons: list[str]) -> list[str]:
    """«C q r» -> Ca qar: the last syllable is CVC, a leftover first consonant is CV."""
    groups: list[list[str]] = []
    i = len(cons)
    while i > 0:
        if i >= 2:
            groups.append(cons[i - 2:i])
            i -= 2
        else:
            groups.append(cons[i - 1:i])
            i -= 1
    out: list[str] = []
    ordered = list(reversed(groups))
    for gi, g in enumerate(ordered):
        vowel = "a"
        if gi > 0 and gi == len(ordered) - 1 and g[-1:] == ["S"]:
            vowel = "e"  # ورزش، نرمش، خواهش: the -eš ending of verbal nouns
        out.extend([g[0], vowel] + g[1:])
    return out


def respelling_to_pn(text: str) -> str:
    """What the owner typed in the panel («چِغِر», «مَعنی», «xAne») -> PN.

    * ASCII input is taken to be PN already (validated);
    * Persian input goes through the letter rules with the written marks trusted.
    Several words are joined with spaces; ZWNJ pieces are joined without one.
    """
    text = (text or "").strip()
    if not text:
        return ""
    if all(ord(c) < 128 for c in text):
        if P.is_valid(text):
            return text.replace(" ", "")
        raise ValueError("بازنویسی نامعتبر است")
    words = []
    for w in text.split():
        parts = [p for p in w.split(ZWNJ) if p]
        pn = ""
        for part in parts:
            pn += P.join(rules_to_pn(part, trust_marks=has_marks(part)))
        words.append(pn)
    return " ".join(words)
