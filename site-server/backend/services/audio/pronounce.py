"""The one door the voice providers use to reach the pronunciation layer.

``fa_pron`` is pure Python (it also runs on the GPU node). This module is the
Django-aware wrapper: it knows the store (its on/off switch and its lexicon) and it
**never lets a bug in the layer silence a narration** - every public function returns
``None`` when anything goes wrong and the caller then speaks the original text exactly
as it did before the layer existed.

    rendered = pronounce.prepare(text, "piper", store=store)
    if rendered is not None: ... use rendered.ipa_sentences / rendered.text ...

Engines: ``piper`` (phoneme input), ``edge`` (the free Edge endpoint accepts plain text
only, measured: any SSML tag gets "no audio" - so it receives respelled text), ``moss``
(text), ``azure`` (SSML ``<sub>``), ``plain`` (every other text engine). English
narration is never touched.
"""
from __future__ import annotations

import logging

from . import fa_pron

logger = logging.getLogger(__name__)

#: provider name -> layer engine
ENGINE_OF = {"piper": "piper", "edge": "edge", "moss": "moss", "node_moss": "moss", "azure": "edge",
             "clone": "moss", "openai": "plain", "elevenlabs": "plain"}


def _store_state(store):
    """(enabled, ezafe, depth overrides, Dictionary). Defaults when the app/tables are not there."""
    try:
        from apps.pronunciation import services as svc

        return svc.runtime_for(store)
    except Exception as exc:  # noqa: BLE001 — the layer must never block narration
        logger.debug("pronunciation runtime unavailable (%s): shared lexicon only", exc)
        return True, True, {}, fa_pron.Dictionary()


def prepare(text: str, engine: str, *, store=None, language: str = "fa", depth: str | None = None,
            record: bool = True, **render_opts) -> fa_pron.Rendered | None:
    """Text -> what ``engine`` should be given, or None to speak the text unchanged."""
    if language != "fa" or not (text or "").strip():
        return None
    key = ENGINE_OF.get(engine, engine)
    try:
        enabled, ezafe, overrides, dictionary = _store_state(store)
        if not enabled:
            return None
        chosen = depth or overrides.get(key) or fa_pron.DEFAULT_DEPTH.get(key, "lexicon")
        prep = fa_pron.prepare(text, depth=chosen, dictionary=dictionary, ezafe=ezafe)
        if engine == "azure":
            rendered = fa_pron.render_prepared(prep, "edge", **render_opts)       # SSML: Azure accepts <sub> (the free Edge endpoint does not)
        elif key in fa_pron.ENGINES:
            if key == "edge":
                # the free Edge endpoint takes text only: respelling instead of SSML tags
                rendered = fa_pron.render_prepared(prep, "plain", **render_opts)
                rendered.engine = "edge"
            else:
                rendered = fa_pron.render_prepared(prep, key, **render_opts)
        else:
            rendered = fa_pron.render_prepared(prep, "plain", **render_opts)
        if record and store is not None:
            _record(store, prep, key)
        return rendered
    except Exception as exc:  # noqa: BLE001
        logger.warning("pronunciation layer failed for engine %s, speaking the plain text: %s", engine, exc)
        return None


def _record(store, prep, engine: str) -> None:
    """Latin words we had to guess go to the store's «مشکل‌دار» list (best effort, never raises)."""
    guesses = list(dict.fromkeys(prep.notes.latin_guesses))
    if not guesses:
        return
    try:
        from apps.pronunciation import services as svc

        svc.record_problems(store, guesses, source="latin", engine=engine, context=prep.original)
    except Exception as exc:  # noqa: BLE001
        logger.debug("could not record pronunciation problems: %s", exc)


def text_for(text: str, engine: str, *, store=None, language: str = "fa", depth: str | None = None) -> str:
    """The string a text-only engine should read (falls back to the input)."""
    rendered = prepare(text, engine, store=store, language=language, depth=depth)
    if rendered is None or not rendered.text.strip():
        return text
    return rendered.text


def fingerprint(store, engine: str) -> str:
    """Key of what the layer does for this store and engine right now (see ``apps.pronunciation.services.fingerprint``);
    the studio puts it in the cache key of a finished take."""
    try:
        from apps.pronunciation import services as svc

        return svc.fingerprint(store, engine)
    except Exception:  # noqa: BLE001
        return fa_pron.VERSION
