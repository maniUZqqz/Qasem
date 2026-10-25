"""The shop's side of sound: its narrator, its pronunciations, its scenes' sounds.

Which ENGINES exist is the operator's decision, made in the Django admin
(`AudioEngine`). What a shop decides is everything above that: male or female,
a little faster or slower, how its brand name is said, and — per scene — rain
or no rain. Before these endpoints the backend could do all of it and the
dashboard could do none of it; `StoreProfile.voice_profile` and
`pronunciations` were JSON fields nobody could reach.

Four endpoints:

* `GET/PATCH /stores/{id}/voice/` — the voice profile and pronunciation list,
  with the form's options and a live answer to "who will actually read this".
* `POST /stores/{id}/voice/preview/` — a real sample, synthesised through the
  same chain, polish and pronunciation table the video will use. A setting
  a shop cannot hear before committing a video to it is a guess.
* `GET /audio/sounds/` — every ambience and effect the mixer can place, with
  a sample to listen to and whether a real recording exists for it.
* `PATCH /video-scripts/{id}/scenes/{index}/sound/` — choose a scene's
  ambience and effects by hand, or hand the choice back to the planner.
* `PATCH /video-scripts/{id}/scenes/{index}/on-camera/` — the person in this
  scene speaks the narration (lip-sync) instead of it being a voice-over.
"""
from __future__ import annotations

import hashlib
import logging
import time
from pathlib import Path

from django.core.files import File
from django.core.files.storage import default_storage
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.stores import access

from .models import VideoScript

logger = logging.getLogger(__name__)

#: Longest pronunciation list a shop keeps. The lexicon reads the first 200;
#: accepting more would store entries that silently do nothing.
MAX_PRONUNCIATIONS = 200
MAX_PREVIEW_CHARS = 300

SAMPLE_TEXT = {
    "fa": "سلام! این صدای گوینده‌ی ویدیوهای فروشگاه شماست. محصول تازه‌ی ما همین حالا با ارسال رایگان.",
    "en": "Hello! This is the narrator of your shop's videos. Our new arrival, with free delivery today.",
}


def _error(code: str, message: str, http=status.HTTP_400_BAD_REQUEST) -> Response:
    return Response({"error": {"code": code, "message": message}}, status=http)


def _profile_from(data, language: str):
    """A VoiceProfile from request data; raises ProfileError on bad values."""
    from services.audio.profile import ProfileError, VoiceProfile

    try:
        cloned = data.get("cloned_voice")
        profile = VoiceProfile(
            gender=str(data.get("gender", "male") or "male"),
            rate=int(data.get("rate", 0) or 0),
            pitch=int(data.get("pitch", 0) or 0),
            volume=int(data.get("volume", 0) or 0),
            language=language,
            cloned_voice=int(cloned) if cloned not in (None, "", 0, "0", False) else None,
            preset=str(data.get("preset") or "")[:40],
        )
    except (TypeError, ValueError) as exc:
        raise ProfileError("سرعت، زیروبمی و بلندی باید عدد باشند") from exc
    profile.validate()
    return profile


def _clean_pronunciations(raw) -> dict[str, str]:
    """`[{written, spoken}]` or `{written: spoken}` → a clean dict, or ValueError."""
    if isinstance(raw, dict):
        pairs = list(raw.items())
    elif isinstance(raw, list):
        pairs = [
            (item.get("written"), item.get("spoken")) for item in raw if isinstance(item, dict)
        ]
    else:
        raise ValueError("فهرست تلفظ باید فهرستی از {written, spoken} باشد")
    out: dict[str, str] = {}
    for written, spoken in pairs:
        written = str(written or "").strip()[:60]
        spoken = str(spoken or "").strip()[:120]
        if not written and not spoken:
            continue
        if not written or not spoken:
            raise ValueError(f"برای «{written or spoken}» هر دو ستون نوشتار و تلفظ لازم است")
        out[written] = spoken
    if len(out) > MAX_PRONUNCIATIONS:
        raise ValueError(f"حداکثر {MAX_PRONUNCIATIONS} تلفظ نگه داشته می‌شود")
    return out


def _voice_payload(store) -> dict:
    from services.audio import engines, lexicon, profile as voice_profile, tts

    saved = voice_profile.VoiceProfile.from_store(store, "fa")
    try:
        saved.validate()
        valid = True
    except voice_profile.ProfileError:
        # An old or hand-edited value. Shown as the default so the form is
        # usable; the narration already falls back to the default for it.
        saved = voice_profile.VoiceProfile(language="fa")
        valid = False

    builtin = {**lexicon.COMMON_BRANDS, **lexicon.COMMON_WORDS}
    en_profile = voice_profile.VoiceProfile(
        gender=saved.gender, rate=saved.rate, pitch=saved.pitch, volume=saved.volume, language="en",
    )
    from apps.ai.models import ClonedVoice

    from services.audio import node_audio
    from services.audio.voice_clone import engine_meta

    cloned_voices = [
        {"id": v.pk, "name": v.name, "person": v.person, "status": v.status,
         "status_label": v.get_status_display(), "usable": v.usable, "license": engine_meta(v)["license"],
         "commercial": engine_meta(v)["commercial"], "engine": v.engine}
        for v in ClonedVoice.objects.filter(store=store).order_by("-created_at")
    ]
    moss_ok, moss_why = node_audio.moss_ready()
    return {
        "profile": {
            "gender": saved.gender, "rate": saved.rate,
            "pitch": saved.pitch, "volume": saved.volume,
            "cloned_voice": saved.cloned_voice,
            "preset": saved.preset,
        },
        "cloned_voices": cloned_voices,
        # MOSS default voices (processing node, commercial use allowed): who reads when MOSS narrates
        "moss": {"ready": moss_ok, "why": moss_why, "presets": node_audio.presets()},
        "profile_was_invalid": not valid,
        "description": saved.describe(),
        "options": voice_profile.options("fa"),
        "voices_en": voice_profile.options("en")["voices"],
        # Who will actually read, for each language, in fallback order.
        "speakers": {
            "fa": tts.speakers("fa", store, profile=saved),
            "en": tts.speakers("en", store, profile=en_profile),
        },
        "local_only": engines.local_only(store),
        "pronunciations": [
            {"written": w, "spoken": s} for w, s in lexicon.store_entries(store).items()
        ],
        "builtin_pronunciations": [
            {"written": w, "spoken": s} for w, s in sorted(builtin.items(), key=lambda kv: kv[0].lower())
        ],
        "max_pronunciations": MAX_PRONUNCIATIONS,
    }


class StoreVoiceView(APIView):
    """`GET/PATCH` a shop's narrator: voice, prosody and pronunciations.

    CONTENT permission, like the content-automation page: the content manager
    is the person whose videos these are.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, store_id):
        store = access.get_store(request.user, store_id, access.CONTENT, write=False)
        return Response(_voice_payload(store))

    def patch(self, request, store_id):
        from services.audio.profile import ProfileError

        store = access.get_store(request.user, store_id, access.CONTENT)
        profile_row = store.profile
        changed = []
        if "profile" in request.data:
            try:
                chosen = _profile_from(request.data.get("profile") or {}, "fa")
            except ProfileError as exc:
                return _error("bad_profile", str(exc))
            if chosen.cloned_voice:
                from apps.ai.models import ClonedVoice

                row = ClonedVoice.objects.filter(pk=chosen.cloned_voice, store=store).first()
                if row is None or not row.usable:
                    return _error("bad_profile", "صدای کلون‌شدهٔ انتخاب‌شده آماده نیست — اول آن را در «کلونِ صدا» بسازید.")
            from services.audio import node_audio

            profile_row.voice_profile = {
                "gender": chosen.gender, "rate": chosen.rate,
                "pitch": chosen.pitch, "volume": chosen.volume,
                **({"cloned_voice": chosen.cloned_voice} if chosen.cloned_voice else {}),
                **({"preset": chosen.preset} if node_audio.preset(chosen.preset) else {}),
            }
            changed.append("voice_profile")
        if "pronunciations" in request.data:
            try:
                profile_row.pronunciations = _clean_pronunciations(request.data.get("pronunciations"))
            except ValueError as exc:
                return _error("bad_pronunciations", str(exc))
            changed.append("pronunciations")
        if changed:
            profile_row.save(update_fields=changed)
        return Response(_voice_payload(store))


class VoicePreviewView(APIView):
    """`POST` — hear a voice setting before a video is narrated with it.

    Synchronous: one or two short sentences take about a second on Piper and
    two on Edge. Samples are cached by their exact inputs, so pressing play
    twice does not synthesise twice, and swept after a day.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request, store_id):
        from services.audio import lexicon, polish, tts
        from services.audio.profile import ProfileError

        store = access.get_store(request.user, store_id, access.CONTENT, write=False)
        language = "en" if request.data.get("language") == "en" else "fa"
        try:
            profile = _profile_from(request.data, language)
        except ProfileError as exc:
            return _error("bad_profile", str(exc))

        text = str(request.data.get("text") or "").strip()[:MAX_PREVIEW_CHARS] or SAMPLE_TEXT[language]
        # The same rewrite the narration gets: brand names as the shop says
        # them, numbers as words. Hearing "Nike" spelled out here is exactly
        # the moment a shop adds it to the list.
        extra = None
        if request.data.get("pronunciations") is not None:
            try:
                extra = _clean_pronunciations(request.data.get("pronunciations"))
            except ValueError as exc:
                return _error("bad_pronunciations", str(exc))
        spoken = lexicon.apply(text, store, extra=extra)
        unresolved = lexicon.unresolved_latin(spoken, store, extra)

        try:
            provider = tts.get_tts_provider(language, store, profile=profile)
        except tts.TTSError as exc:
            return _error("no_voice", str(exc), status.HTTP_409_CONFLICT)
        if getattr(provider, "name", "") == "clone":
            # spoken on a processing node: a sample waits for it, but not past the web timeout
            provider.wait_s = 240

        mix = polish.settings_mix()
        key = hashlib.sha256("|".join([
            str(store.pk), language, profile.gender, str(profile.rate), str(profile.pitch),
            str(profile.volume), spoken, provider.name, provider.voice, str(mix.voice_lufs),
            str(getattr(mix, "polish_voice", True)),
        ]).encode("utf-8")).hexdigest()[:20]
        name = f"voice_previews/store_{store.pk}/{key}.m4a"

        if not default_storage.exists(name):
            import tempfile

            with tempfile.TemporaryDirectory(prefix="voice_preview_") as folder:
                work = Path(folder)
                try:
                    raw = Path(provider.synthesize(spoken, work / "raw.mp3"))
                except tts.TTSError as exc:
                    return _error("synthesis_failed", f"ساخت نمونه‌ی صدا نشد: {exc}",
                                  status.HTTP_502_BAD_GATEWAY)
                final = polish.maybe_polish(raw, work / "sample.m4a")
                if final.suffix != ".m4a":
                    from services.video.ffmpeg import FFMPEG, _run

                    _run([FFMPEG, "-y", "-i", str(final), "-c:a", "aac", "-b:a", "128k",
                          str(work / "sample.m4a")])
                    final = work / "sample.m4a"
                with final.open("rb") as handle:
                    name = default_storage.save(name, File(handle))
            _sweep_previews(store.pk)

        speaker = provider.describe() if hasattr(provider, "describe") else {}
        return Response({
            "url": default_storage.url(name),
            "speaker": speaker,
            "spoken_text": spoken,
            "unresolved": unresolved,
        })


def _sweep_previews(store_id: int, max_age_s: int = 24 * 3600) -> None:
    """Delete this store's samples older than a day. Best effort."""
    folder = f"voice_previews/store_{store_id}"
    try:
        _dirs, files = default_storage.listdir(folder)
    except Exception:  # noqa: BLE001 — folder missing, or storage without listdir
        return
    cutoff = time.time() - max_age_s
    for filename in files:
        path = f"{folder}/{filename}"
        try:
            if default_storage.get_modified_time(path).timestamp() < cutoff:
                default_storage.delete(path)
        except Exception:  # noqa: BLE001
            continue


class SoundCatalogueView(APIView):
    """`GET` — every sound the mixer can place, with something to listen to."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        from apps.ai.models import SoundClip
        from services.audio import soundscape
        from services.audio.polish import settings_mix

        samples: dict[str, str] = {}
        counts: dict[str, int] = {}
        for clip in SoundClip.objects.filter(is_active=True).order_by("category", "id"):
            counts[clip.category] = counts.get(clip.category, 0) + 1
            if clip.category not in samples and clip.file:
                try:
                    samples[clip.category] = clip.file.url
                except Exception:  # noqa: BLE001
                    pass
        rows = []
        for item in soundscape.catalogue():
            rows.append({
                **item,
                "recordings": counts.get(item["key"], 0),
                "sample_url": samples.get(item["key"]),
                # Placeable = a real recording exists, or code can make it.
                "available": bool(counts.get(item["key"])) or item["procedural"],
            })
        mix = settings_mix()
        return Response({
            "sounds": rows,
            "ambience_enabled": bool(getattr(mix, "ambience_enabled", True)),
            "effects_enabled": bool(getattr(mix, "effects_enabled", True)),
        })


class SceneSoundView(APIView):
    """`PATCH` one scene's sound by hand.

    Body: `{"ambience": key | "none" | null, "effects": [{key, at}] | null}`.
    `null` hands that half back to the planner (the scene's words decide);
    `"none"` and `[]` are decisions and are kept as such. Takes effect on the
    next «صداگذاری» — the voiced file already made is not touched.
    """

    permission_classes = [IsAuthenticated]

    def patch(self, request, pk, index):
        from services.ai.prompts.video_script import _clean_sound

        script = get_object_or_404(
            VideoScript.objects.filter(store__in=access.stores_for(request.user)), pk=pk,
        )
        access.get_store(request.user, script.store_id, access.CONTENT)
        scene = get_object_or_404(script.scenes, index=index)

        current = dict(scene.sound or {})
        wanted = dict(current)
        for part in ("ambience", "effects"):
            if part not in request.data:
                continue
            value = request.data.get(part)
            if value is None:
                wanted.pop(part, None)
            else:
                wanted[part] = value
        cleaned = _clean_sound(wanted, scene.duration)
        # _clean_sound drops an unknown ambience silently (right for a model's
        # output); a person who picked one should be told instead.
        if "ambience" in wanted and "ambience" not in cleaned:
            return _error("bad_ambience", f"صدای محیط «{wanted['ambience']}» شناخته نشد")
        scene.sound = cleaned
        scene.save(update_fields=["sound"])

        from .serializers import VideoSceneSerializer

        return Response(VideoSceneSerializer(scene).data)


class SceneSpeakerView(APIView):
    """`PATCH {"enabled": bool}` — does the person in this scene speak the narration?

    On: the video prompt asks for a frontal face (scene_state.ON_CAMERA), the
    mouth check stops rejecting the scene for talking, and the voicing step
    redraws the mouth to the narration (services.video.lipsync). Best set
    before the video is generated; set afterwards, the next «صداگذاری» still
    lip-syncs whatever face the render has.
    """

    permission_classes = [IsAuthenticated]

    def patch(self, request, pk, index):
        script = get_object_or_404(
            VideoScript.objects.filter(store__in=access.stores_for(request.user)), pk=pk,
        )
        access.get_store(request.user, script.store_id, access.CONTENT)
        scene = get_object_or_404(script.scenes, index=index)
        value = request.data.get("enabled")
        if not isinstance(value, bool):
            return _error("bad_value", "enabled باید true یا false باشد")
        scene.speaker_on_camera = value
        scene.save(update_fields=["speaker_on_camera"])

        from .serializers import VideoSceneSerializer

        return Response(VideoSceneSerializer(scene).data)
