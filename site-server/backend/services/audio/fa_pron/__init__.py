"""Persian pronunciation layer: normaliser + phonetic layer + per-engine output.

    from services.audio import fa_pron
    out = fa_pron.for_engine("قیمت ۲۵۰,۰۰۰ تومان", "piper", dictionary=store_dict)
    out.ipa / out.ssml / out.text

See ``docs/pronunciation/README-fa.md``.
"""
from __future__ import annotations

#: Bump whenever a rule or the lexicon changes what a text turns into: caches of finished audio include it.
VERSION = "2026.11.17.3"

from . import dictionary, eval_set, quality
from .dictionary import Dictionary, canon
from .normalize import normalize as normalize_text
from .pipeline import DEPTHS, Prepared, Token, prepare
from .render import ENGINES, Rendered
from .render import render as render_prepared

#: How deep each engine needs us to go, from the ASR round-trip (docs/pronunciation/results-fa.md) and from listening to what changes:
#:   piper  «lexicon». The owner's complaint (ع، ه، و/او، ی، اضافه) is about exactly the words this depth fixes, and espeak, the voice's own
#:          front end, gets them wrong: «و» is read as a stressed «vˈa» instead of the reduced «o», «هزار» as hezɑr, «چهار» as tʃɑhɑr, an
#:          ezafe is never said, «مدرسه», «اشتراک», «ددلیفت» ... are respelled. On the voice the site really has (gyro, 296 sentences, small
#:          Vosk) the word error rate is 13.6% raw, ~7.7% with the normaliser alone and ~8.6% with the lexicon: a recogniser that cannot hear
#:          a glottal stop, a short vowel or a reduced «و» (it drops «گوشت و ماهی» to «گوشت ماهی» although the voice says it right) cannot
#:          rank the two, and the difference is under the one point the platform treats as noise. «normalize» stays one click away
#:          (settings, or «try another depth» in the test box), and the node's Whisper run decides by itself
#:          (``apps.pronunciation.services.measured_depths``): the better depth wins when it is better by a point.
#:   edge   «normalize»: 7.1% -> 4.9%, but 6.5% with «lexicon»: Edge already reads ع/ه/و right and a respelling with short-vowel marks
#:          only disturbs it - numbers, dates, phone numbers and Latin words are what it needs
#:   moss   «normalize», not measured yet (the node is off): the safe floor. The node self-test measures both depths and
#:          ``apps.pronunciation.services.measured_depths`` switches the platform default to the better one by itself.
DEFAULT_DEPTH = {"piper": "lexicon", "edge": "normalize", "moss": "normalize", "plain": "normalize"}


def for_engine(text: str, engine: str, *, dictionary: Dictionary | None = None,  # noqa: F811
               depth: str | None = None, ezafe: bool = True, **render_opts) -> Rendered:
    """One call: text -> what ``engine`` should be given."""
    prep = prepare(text, depth=depth or DEFAULT_DEPTH.get(engine, "lexicon"),
                   dictionary=dictionary, ezafe=ezafe)
    return render_prepared(prep, engine, **render_opts)


__all__ = ["VERSION", "dictionary", "eval_set", "quality", "Dictionary", "canon", "normalize_text", "prepare", "render_prepared", "for_engine", "Prepared",
           "Token", "Rendered", "ENGINES", "DEPTHS", "DEFAULT_DEPTH"]
