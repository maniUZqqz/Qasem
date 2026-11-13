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


def _faces_in_window(folder: Path, faces) -> bool | None:
    """Is somebody in the frames `analysis.window_stats` just cut out (`look_*.png`)?  True / False, or None when the face model is not available
    (the caller then looks the old way).  The measurement of a shot and the answer «is there a person in it» come from the same three frames."""
    try:
        import cv2
    except Exception:  # noqa: BLE001
        return None
    seen = 0
    for png in sorted(Path(folder).glob("look_*.png")):
        img = cv2.imread(str(png))
        if img is None:
            continue
        try:
            found = faces._yunet(img)
        except Exception:  # noqa: BLE001
            return None
        if found is None:
            return None
        seen += sum(1 for b in found if b.area >= faces.MIN_FACE_FRACTION)
    return seen > 0


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

    face_seen: dict[str, bool] = {}
    boxes: dict[str, dict] = {}

    def content_box(ref: str):
        """Where the real picture is inside black bars (a phone screen recorded in a landscape frame…), kept next to the other analyses."""
        if ref in boxes:
            return boxes[ref]
        item = describe(ref)
        if not item or item.get("kind") != "video" or not item.get("path") or float(item.get("duration") or 0) <= 2.0:
            boxes[ref] = {}
            return {}
        from services.editing import letterbox

        path = Path(item["path"])
        cache_file = media_cache.cache_dir() / f"box-{media_cache._key(path, 'box1')}.json"
        hit = media_cache._read_json(cache_file)
        if isinstance(hit, dict) and "found" in hit:
            boxes[ref] = hit
            return hit
        found = letterbox.detect(path, float(item["duration"]), size=(int(item["width"]), int(item["height"])) if item.get("width") and item.get("height") else None)
        try:
            media_cache._write_atomic(cache_file, json.dumps(found, ensure_ascii=False).encode("utf-8"))
        except Exception as exc:  # noqa: BLE001 — a cache that cannot be written only costs a second look
            logger.info("box cache not written: %s", exc)
        boxes[ref] = found
        return found

    def look_stats(ref: str, a: float, b: float):
        item = describe(ref)
        if not item or item.get("kind") != "video" or not item.get("path"):
            return {}
        from services.editing import analysis
        from services.video import faces

        box = content_box(ref) or {}
        pre = f"crop={box['w']}:{box['h']}:{box['x']}:{box['y']}" if box.get("found") else ""      # exposure of the picture, not of the black bars around it
        with tempfile.TemporaryDirectory(prefix="nm-look-") as work:
            stats = analysis.window_stats(item["path"], max(0.0, float(a)), max(float(a) + 0.5, float(b)), work, tag="look", pre_filter=pre) or {}
            if not stats:
                return {}
            seen = _faces_in_window(Path(work) / "shots", faces)             # a person in THIS shot (the three frames just measured)
            if seen is None:                                                    # the face model is not here: look the old way, once per video
                if ref not in face_seen:
                    try:
                        face_seen[ref] = bool((faces.in_video(item["path"], work, samples=5) or {}).get("faces"))
                    except Exception:  # noqa: BLE001 — "could not look" must not block the correction
                        face_seen[ref] = False
                seen = face_seen[ref]
            stats["faces"] = 1 if seen else 0
            stats["height"] = int(item.get("height") or 0)
        return stats

    def rank_music(target: dict, seconds: float):
        from apps.ai.models import AudioAsset
        from services.editing import music_match

        rows = AudioAsset.objects.filter(store=store, kind=AudioAsset.Kind.MUSIC, status=AudioAsset.Status.READY).order_by("-saved", "-id")[:40]
        cands = []
        for row in rows:
            ref = f"audio:{row.pk}"
            item = describe(ref)
            if not item:
                continue
            bpm = energy = None
            try:
                b = media_cache.beats(Path(item["path"]))
                bpm = b.get("bpm")
                if b.get("beats") and item.get("duration"):
                    rate = len(b["beats"]) / max(1.0, float(item["duration"]))
                    energy = max(0.0, min(1.0, (rate - 0.6) / 2.4))          # beats per second → 0..1 (a pad ≈ 0.6/s, a driving track ≈ 3/s)
            except Exception:  # noqa: BLE001
                pass
            params = row.params if isinstance(row.params, dict) else {}
            bpm = bpm or params.get("bpm")
            cands.append(music_match.describe_track(ref, row.title, f"{row.text} {row.prompt} {params.get('style', '')}", bpm=bpm, energy=energy,
                                                    duration=float(item.get("duration") or 0), license=row.license))
        return music_match.rank(cands, target, need_seconds=seconds)

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

    def make_matte(ref: str, s0: float, s1: float):
        """Cut the subject out of source seconds s0..s1 of a video, on the processing server's GPU (RVM): the same job the editor's «حذف پس‌زمینه»
        button runs, started from here and waited for.  Off → «در صف» (the Director fills the step in when the server comes back)."""
        from apps.content import tasks_editing as te
        from apps.jobs.models import Job

        state = te.matte_status()
        if not state["ok"]:
            if not state.get("node") and captions.node_registered("ffmpeg"):
                raise StepError(captions.WAITING_TEXT)
            raise StepError(state["message"])
        job = Job.objects.create(store=store, type=Job.Type.VIDEO_EDIT, context={"what": "matte", "ref": ref, "origin": "autoedit"})
        out = te.matte_task(job.id, ref, float(s0), float(s1)) or {}
        if out.get("cancelled") or out.get("error") or not out.get("key"):
            raise StepError("جداسازیِ پس‌زمینه انجام نشد: " + str(out.get("error") or "لغو شد")[:160])
        return {"key": out["key"], "s0": float(out.get("s0", s0)), "engine": out.get("engine", "")}

    ctx = Ctx(describe=public, spans=spans, beats=beats, words=words, path_of=path_of, make_speech=make_speech, find_music=find_music, store=store,
              look_stats=look_stats, rank_music=rank_music, make_matte=make_matte, content_box=content_box)
    return ctx
