"""The store-scoped `Ctx`: how the director reaches the shop's media, analysis caches, speech recognition and voices.

This is the ONLY module of the package that touches Django models / the compute node; everything else takes a `Ctx`.
"""
from __future__ import annotations

import json
import logging
import tempfile
import time
from pathlib import Path

from .spec import Ctx, StepError

logger = logging.getLogger(__name__)


def store_ctx(store, *, user=None, asr: bool = True, tts_wait: float = 150.0) -> Ctx:
    from apps.content import editor_project
    from services.editing import captions, media_cache
    from services.editing import timeline as tl

    cache: dict[str, dict | None] = {}

    def describe(ref: str):
        if ref in cache:
            return cache[ref]
        try:
            item = editor_project.describe(store, ref)
        except tl.TimelineError:
            cache[ref] = None
            return None
        cache[ref] = item
        return item

    def public(ref: str):
        item = describe(ref)
        return editor_project.public(item) if item else None

    def spans(ref: str):
        item = describe(ref)
        if not item or not item.get("has_audio") or item["kind"] == "image":
            return []
        return media_cache.speech_spans(Path(item["path"]))

    def beats(ref: str):
        item = describe(ref)
        if not item or not item.get("has_audio"):
            return {"beats": [], "bpm": None}
        return media_cache.beats(Path(item["path"]))

    def words(ref: str, a: float, b: float):
        item = describe(ref)
        if not item or not item.get("has_audio"):
            return []
        # ONE transcript per source file (kept on disk): captions, filler removal and the analysis all slice it, and re-running an
        # edited plan never listens to the same speech again; after silence removal a clip is many pieces, which must not mean many jobs.
        whole = min(float(item.get("duration") or 0) or captions.MAX_SECONDS, float(captions.MAX_SECONDS))
        cache_file = media_cache.cache_dir() / f"asr-{media_cache._key(Path(item['path']), 'asr-whole')}.json"
        words_all = media_cache._read_json(cache_file)
        if not (isinstance(words_all, list) and words_all):
            state = captions.status()
            if asr and state.get("waiting"):
                raise captions.waiting_error()           # the server is only off: the step is filled in later (director_fill_task)
            if not asr or not state["ok"]:
                raise captions.CaptionsUnavailable(state["message"] or "تشخیصِ گفتار خاموش است.")
            wav = Path(tempfile.NamedTemporaryFile(suffix=".wav", delete=False).name)
            try:
                captions.extract_audio(item["path"], 0.0, whole, wav)
                heard = captions.transcribe_wav(wav, store=store)
                words_all = [{"w": w["w"], "s": w["s"], "e": w["e"]} for w in heard.get("words", [])]
                if words_all:
                    media_cache._write_atomic(cache_file, json.dumps(words_all, ensure_ascii=False).encode("utf-8"))
            finally:
                wav.unlink(missing_ok=True)
        lo, hi = float(a), float(b)
        return [{"w": w["w"], "s": round(max(0.0, w["s"] - lo), 3), "e": round(min(hi - lo, w["e"] - lo), 3)}
                for w in words_all if w["e"] > lo and w["s"] < hi]

    def path_of(ref: str):
        item = describe(ref)
        return str(item["path"]) if item and item.get("path") else None

    def find_music(query: str):
        from apps.ai.models import AudioAsset

        rows = AudioAsset.objects.filter(store=store, kind=AudioAsset.Kind.MUSIC, status=AudioAsset.Status.READY).order_by("-saved", "-id")
        row = rows.first()
        return f"audio:{row.pk}" if row else None

    def make_speech(text: str, voice: str):
        from apps.ai.models import AudioAsset
        from services.audio import node_audio, studio

        voice_id = voice
        if not voice_id:
            usable = [v for v in studio.voices(store) if v.get("available")]
            usable.sort(key=lambda v: (v.get("where") != "site", v.get("name", "")))     # site voices answer in a second
            if not usable:
                from services.editing import captions as _captions

                if _captions.node_registered("voice"):
                    raise StepError("در صف — منتظرِ روشن شدنِ سرورِ پردازش: صدای گوینده روی آن ساخته می‌شود و هر وقت روشن شد خودکار اضافه می‌شود.")
                raise StepError("هیچ صدای گوینده‌ای در دسترس نیست (سرورِ پردازش خاموش است و صدای سایت هم نصب نیست).")
            voice_id = usable[0]["id"]
        try:
            asset = studio.create_speech(store, user, text=text, voice_id=voice_id, title="گویندگیِ کارگردان")
        except studio.StudioError as exc:
            raise StepError(str(exc)) from exc
        except node_audio.NodeAudioError as exc:
            raise StepError(str(exc)) from exc
        end = time.monotonic() + tts_wait
        while asset.status in (AudioAsset.Status.PENDING, AudioAsset.Status.RUNNING) and time.monotonic() < end:
            time.sleep(2.0)
            asset = studio.sync(AudioAsset.objects.get(pk=asset.pk))
        if asset.status != AudioAsset.Status.READY:
            raise StepError(asset.error or "ساختنِ گفتار به‌موقع تمام نشد؛ دوباره امتحان کنید.")
        asset.saved = True
        asset.save(update_fields=["saved", "updated_at"])
        return f"audio:{asset.pk}"

    ctx = Ctx(describe=public, spans=spans, beats=beats, words=words, path_of=path_of, make_speech=make_speech, find_music=find_music, store=store)
    return ctx
