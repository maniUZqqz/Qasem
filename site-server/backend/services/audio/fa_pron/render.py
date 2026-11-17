"""Turn a ``Prepared`` text into what each engine takes.

Engines differ in what they let us control, so there is one renderer per kind:

  piper   phoneme input. The Piper fa_IR voices were trained on espeak-ng
          phonemes, so the best a caller can do is hand them IPA in the same
          alphabet and skip espeak's weak Persian front end. Words we have no
          opinion on may be phonemised by espeak itself (``native_ipa`` callback)
          so only the words we know are overridden.
  edge    SSML. ``<phoneme alphabet="ipa">`` where the service honours it,
          ``<sub alias>`` (a respelling) otherwise, ``<break>`` for pauses.
  text    everything else (MOSS-TTS, voice cloning, unknown engines): plain
          text in which the words we know are *respelled* with the short-vowel
          marks written out («مَعنی»), and the rest is left alone.

Nothing here talks to an engine; the glue lives in ``tts.py`` and on the node.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable
from xml.sax.saxutils import escape

from . import latin, phones as P
from .pipeline import Prepared, Token

ZWNJ = "‌"
KASRA = "ِ"

ENGINES = ("piper", "edge", "moss", "plain")

#: pause lengths in milliseconds for SSML
BREAK_MS = {"short": 250, "long": 550, "para": 900}


@dataclass
class Rendered:
    engine: str
    depth: str
    text: str = ""                    # text for text engines / the "after" text for display
    ssml: str = ""                    # SSML fragment (edge)
    ipa: str = ""                     # one IPA string for the whole input (piper)
    ipa_sentences: list[str] = field(default_factory=list)
    subs: list[dict] = field(default_factory=list)
    notes: dict = field(default_factory=dict)


# ------------------------------------------------------------------ helpers

def respell_token(tok: Token, *, sukun: bool = False) -> str:
    """Persian script with the vowels written, ezafe included."""
    if not tok.pn or not tok.apply:
        return _surface_with_ezafe(tok)
    toks = P.parse(tok.pn)
    base = P.to_respelling(toks, sukun=sukun, q_letter=P.q_letter_for(tok.text))
    if not tok.ezafe:
        return base
    last = toks[-1] if toks else ""
    if last == "i":
        return base + KASRA  # «معنیِ»: the ی already carries the glide
    if last in P.VOWELS:
        if last == "e":
            return base + ZWNJ + "ی" + KASRA
        return base + "ی" + KASRA
    return base + KASRA


def _surface_with_ezafe(tok: Token) -> str:
    text = tok.text
    if not tok.ezafe:
        return text
    last = text.rstrip(ZWNJ)[-1:] if text else ""
    if last == "ی":
        return text + KASRA               # «اختصاصی» -> «اختصاصیِ» (the ی already carries the glide)
    if last in "اآو":
        return text + "ی" + KASRA
    if last == "ه":
        return text + ZWNJ + "ی" + KASRA
    return text + KASRA


def _pause_text(tok: Token) -> str:
    return "\n" if tok.pause == "para" else tok.text


def _joined_text(tokens: list[Token], word_fn: Callable[[Token], str]) -> str:
    out: list[str] = []
    for t in tokens:
        if t.kind == "pause":
            s = _pause_text(t)
            if s == "\n":
                out.append("\n")
            else:
                if out and out[-1] == " ":
                    out.pop()
                out.append(s + " ")
            continue
        out.append(word_fn(t))
        out.append(" ")
    return "".join(out).strip()


def _subs(prep: Prepared, *, glottal: str = "keep") -> list[dict]:
    rows = []
    for t in prep.tokens:
        if t.kind == "word" and t.pn:
            toks = t.tokens()
            rows.append({
                "word": t.text, "pn": t.pn, "source": t.source, "ezafe": t.ezafe, "applied": t.apply,
                "respelling": respell_token(t), "ipa": P.to_ipa(t.tokens(stress=True), glottal=glottal),
                "ssml_ipa": P.to_ssml_ipa(toks, glottal=glottal),
            })
    return rows


# ------------------------------------------------------------------ renderers

def render_text(prep: Prepared, *, engine: str = "plain", sukun: bool = False,
                only_sources: set[str] | None = None, **_ignored) -> Rendered:
    """Plain text with known words respelled (MOSS-TTS and any text-in engine)."""
    def word(t: Token) -> str:
        if t.pn and t.apply and (only_sources is None or t.source in only_sources):
            return respell_token(t, sukun=sukun)
        return _surface_with_ezafe(t) if t.ezafe else t.text

    text = _joined_text(prep.tokens, word)
    return Rendered(engine=engine, depth=prep.depth, text=text, subs=_subs(prep))


def render_edge(prep: Prepared, *, mode: str = "sub", glottal: str = "keep", **_ignored) -> Rendered:
    """SSML fragment for the inside of ``<prosody>``.

    mode ``sub``      <sub alias="respelling">word</sub>      works on every voice
    mode ``phoneme``  <phoneme alphabet="ipa" ph="..">word</phoneme>   only where honoured
    """
    parts: list[str] = []
    plain: list[str] = []
    for t in prep.tokens:
        if t.kind == "pause":
            if t.pause == "para":
                parts.append(f'<break time="{BREAK_MS["para"]}ms"/>')
                plain.append("\n")
            else:
                parts.append(escape(t.text) + f'<break time="{BREAK_MS[t.pause]}ms"/>')
                plain.append(t.text)
            continue
        if t.pn and t.apply:
            if mode == "phoneme":
                ph = P.to_ssml_ipa(t.tokens(), glottal=glottal)
                parts.append(f'<phoneme alphabet="ipa" ph="{escape(ph, {chr(34): "&quot;"})}">{escape(t.text)}</phoneme>')
            else:
                parts.append(f'<sub alias="{escape(respell_token(t), {chr(34): "&quot;"})}">{escape(t.text)}</sub>')
            plain.append(respell_token(t))
        else:
            surf = _surface_with_ezafe(t) if t.ezafe else t.text
            parts.append(escape(surf))
            plain.append(surf)
        parts.append(" ")
    ssml = "".join(parts).strip()
    return Rendered(engine="edge", depth=prep.depth, text=" ".join(plain), ssml=ssml,
                    subs=_subs(prep, glottal=glottal), notes={"mode": mode})


def _reconciled(t: Token, native_ipa: Callable[[str], str], glottal: str, geminate: str) -> str | None:
    """A lexicon word, written for the voice WITHOUT harming what the voice already reads right.

    The voice's own front end phonemises the word too; when its segments equal ours the voice's string is used as it is
    (the lexicon agrees: nothing to change), otherwise our segments are used with the voice's own stress (``phones.reconcile_ipa``).
    The ezafe is appended after. With a deferred native (the node worker phonemises later) a ``{{word|ours}}`` piece is
    written and the worker does the same reconciliation. None => the caller falls back to our own stress rule."""
    if t.source in ("letters", "rule", "conj"):      # letter names and the conjunction «و» (/o/ after a consonant, /vo/ after a vowel) are ours alone
        return None
    base = P.parse(t.pn)
    ours = P.to_ipa(P.strip_stress(base), glottal=glottal, geminate=geminate)
    if not ours:
        return None
    ez = ""
    if t.ezafe:
        ez = P.to_ipa(["y", "e"] if base and base[-1] in P.VOWELS else ["e"])
    try:
        native = native_ipa(t.text)
    except Exception:  # noqa: BLE001 - the voice's front end failing must never stop the narration
        native = ""
    if not native:
        return None
    if native.startswith("{{") and native.endswith("}}"):
        return "{{%s|%s}}" % (t.text, ours) + ez
    return P.reconcile_ipa(ours, native) + ez


def _is_letters(t: Token) -> bool:
    """A spelled-out acronym (letter names joined by half-spaces) that no store word overrides."""
    return t.kind == "word" and (t.source == "letters" or not t.pn) and latin.letters_ipa(t.text) is not None


def render_piper(prep: Prepared, *, native_ipa: Callable[[str], str] | None = None,
                 glottal: str = "medial", stress: str = "last",
                 geminate: str = "double") -> Rendered:
    """IPA for Piper's phoneme input.

    ``native_ipa(word)`` (optional) phonemises a word with the voice's own front
    end (espeak-ng). It is used for words we have no pronunciation for, so the
    layer overrides only what it knows. Without it, those words fall back to the
    letter rules (depth ``full`` guarantees every word has some PN).
    """
    if prep.depth == "normalize":
        # nothing of ours to say: the voice reads the normalised text with its own front end ... except (1) a spelled-out acronym
        # («پی‌دی‌اف»): that front end reads the Persian spelling as the words «پی» and «دی» (pˈej dˈej), and (2) a word the OWNER
        # wrote in the store's own lexicon (only such words carry a pronunciation at this depth). Such a text goes in as phonemes:
        # those words are ours, every other word is phonemised by the voice itself (word by word)
        if native_ipa is None or not any(t.kind == "word" and (t.pn or _is_letters(t)) for t in prep.tokens):
            return Rendered(engine="piper", depth=prep.depth, text=prep.normalized, notes={"native_words": 0, "rule_words": 0})
    sentences: list[str] = []
    cur: list[str] = []
    native_used = 0
    reconciled = 0
    rule_used = 0

    def flush():
        if cur:
            sentences.append(" ".join(cur).strip())
            cur.clear()

    letters_used = 0
    for t in prep.tokens:
        if _is_letters(t):
            cur.append(latin.letters_ipa(t.text))
            letters_used += 1
            continue
        if t.kind == "pause":
            mark = {"short": ",", "long": ".", "para": "."}[t.pause]
            if t.text == "؟":
                mark = "?"
            elif t.text == "!":
                mark = "!"
            if cur:
                cur[-1] = cur[-1] + mark
            if t.pause in ("long", "para"):
                flush()
            continue
        if t.pn:
            word_ipa = _reconciled(t, native_ipa, glottal, geminate) if (native_ipa is not None and stress != "none") else None
            if word_ipa is None:
                toks = t.tokens(stress=stress != "none", stress_position=stress if stress != "none" else "last")
                word_ipa = P.to_ipa(toks, glottal=glottal, geminate=geminate)
            else:
                reconciled += 1
            cur.append(word_ipa)
            if t.source == "rule":
                rule_used += 1
        elif native_ipa is not None:
            # a word the writer marked with an ezafe is handed over WITH the mark: the voice's own front end reads «هٔ» / «ِ» right
            ipa = native_ipa(_surface_with_ezafe(t) if t.written_ezafe else t.text)
            if ipa:
                cur.append(ipa)
                native_used += 1
        else:
            rule_used += 1
    flush()
    return Rendered(engine="piper", depth=prep.depth, text=prep.normalized, ipa=" ".join(sentences),
                    ipa_sentences=sentences, subs=_subs(prep, glottal=glottal),
                    notes={"native_words": native_used, "rule_words": rule_used, "reconciled_words": reconciled,
                           "letter_words": letters_used})


def render(prep: Prepared, engine: str, **opts) -> Rendered:
    if engine == "piper":
        return render_piper(prep, **opts)
    if engine == "edge":
        return render_edge(prep, **opts)
    if engine in ("moss", "plain"):
        return render_text(prep, engine=engine, **opts)
    raise ValueError(f"unknown engine {engine!r}")
