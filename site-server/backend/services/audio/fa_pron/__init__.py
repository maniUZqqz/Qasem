"""Persian pronunciation layer: normaliser + phonetic layer + per-engine output.

    from services.audio import fa_pron
    out = fa_pron.for_engine("قیمت ۲۵۰,۰۰۰ تومان", "piper", dictionary=store_dict)
    out.ipa / out.ssml / out.text

See ``docs/pronunciation/README-fa.md``.
"""
from __future__ import annotations

#: Bump whenever a rule or the lexicon changes what a text turns into: caches of finished audio include it.
VERSION = "2026.11.17"

from . import dictionary, eval_set, quality
from .dictionary import Dictionary, canon
from .normalize import normalize as normalize_text
from .pipeline import DEPTHS, Prepared, Token, prepare
from .render import ENGINES, Rendered
from .render import render as render_prepared

#: How deep each engine needs us to go, from the ASR round-trip (docs/pronunciation/results-fa.md):
#:   piper  «normalize». Measured on the voice the site really has (gyro, 272 sentences, Vosk): 12.7% raw -> 8.0% with the
#:          normaliser alone, 9.0% with the lexicon on top, i.e. the lexicon is NOT better than the normaliser yet (the
#:          earlier 27.1% -> 20.9% figure was for the voice amir, which this site does not have). «lexicon» stays one click away
#:          (settings, or «try another depth» in the test box) and the node's Whisper measurement switches the default by itself
#:          (``apps.pronunciation.services.measured_depths``) once it shows the lexicon to be better.
#:   edge    7.1% ->  4.9% with «normalize», but 6.5% with «lexicon»: Edge already reads ع/ه/و right, and a respelling
#:          with short-vowel marks only disturbs it - numbers, dates, phone numbers and Latin words are what it needs
#:   moss   not measured yet (the node is off): the safe floor. The node self-test measures both depths and
#:          ``apps.pronunciation.services.measured_depths`` switches the platform default to the better one by itself.
DEFAULT_DEPTH = {"piper": "normalize", "edge": "normalize", "moss": "normalize", "plain": "normalize"}


def for_engine(text: str, engine: str, *, dictionary: Dictionary | None = None,  # noqa: F811
               depth: str | None = None, ezafe: bool = True, **render_opts) -> Rendered:
    """One call: text -> what ``engine`` should be given."""
    prep = prepare(text, depth=depth or DEFAULT_DEPTH.get(engine, "lexicon"),
                   dictionary=dictionary, ezafe=ezafe)
    return render_prepared(prep, engine, **render_opts)


__all__ = ["VERSION", "dictionary", "eval_set", "quality", "Dictionary", "canon", "normalize_text", "prepare", "render_prepared", "for_engine", "Prepared",
           "Token", "Rendered", "ENGINES", "DEPTHS", "DEFAULT_DEPTH"]
