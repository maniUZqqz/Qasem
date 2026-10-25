"""«صدا»: speech, ambience/effects, background music and the shop's audio library — and the same sounds
under a finished social video.

    GET          /stores/{id}/audio/                          engines (which node has which model), voices,
                                                              presets, music styles, today's allowance
    GET  POST    /stores/{id}/audio/assets/                   the library (?kind=SPEECH|SFX|MUSIC&saved=1) ·
                                                              generate {kind: speech|sfx|music, ...}
    GET  PATCH   /stores/{id}/audio/assets/{pk}/              one (follows its node job) · {title, saved}
    DELETE
    GET          /stores/{id}/audio/assets/{pk}/file/         the audio (?download=1 for a file name)
    GET  POST    /stores/{id}/video-scripts/{pk}/sound-mix/   a video's background: music + ambience bed with
                                                              levels, ducked under the voice → final_video_music

Everything is store-scoped with the CONTENT permission, like the rest of the content tools.
"""
from __future__ import annotations

import logging
import shutil
from pathlib import Path

from django.conf import settings
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.stores import access

logger = logging.getLogger(__name__)

MEDIA_TYPES = {".wav": "audio/wav", ".mp3": "audio/mpeg", ".m4a": "audio/mp4", ".ogg": "audio/ogg", ".flac": "audio/flac"}
MUSIC_LEVELS = (-28.0, -10.0)
AMBIENCE_LEVELS = (-40.0, -20.0)


def _error(code, message, http=status.HTTP_400_BAD_REQUEST):
    return Response({"error": {"code": code, "message": message}}, status=http)


def _asset(request, store_id, pk, *, write):
    from apps.ai.models import AudioAsset

    store = access.get_store(request.user, store_id, access.CONTENT, write=write)
    return store, get_object_or_404(AudioAsset, pk=pk, store=store)


class AudioOverviewView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, store_id):
        from services.audio import node_audio, soundscape, studio

        store = access.get_store(request.user, store_id, access.CONTENT, write=False)
        return Response({
            "status": node_audio.status(),
            "voices": studio.voices(store),
            "sfx_presets": [{"key": k.key, "label": k.label, "kind": k.kind, "prompt": k.queries[0]}
                            for k in soundscape.CATALOGUE.values()],
            "music_styles": studio.MUSIC_STYLES,
            "limits": {"speech_chars": studio.MAX_SPEECH_CHARS, "sfx": [studio.SFX_MIN, studio.SFX_MAX],
                       "music": [studio.MUSIC_MIN, studio.MUSIC_MAX], "speed": [studio.SPEED_MIN, studio.SPEED_MAX],
                       "daily_seconds": studio.daily_limit(), "used_today": round(studio.used_today(store))},
        })


class AudioAssetListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, store_id):
        from apps.ai.models import AudioAsset
        from services.audio import studio

        store = access.get_store(request.user, store_id, access.CONTENT, write=False)
        studio.sweep_drafts(store)
        rows = AudioAsset.objects.filter(store=store).select_related("cloned_voice")
        kind = (request.query_params.get("kind") or "").upper()
        if kind in AudioAsset.Kind.values:
            rows = rows.filter(kind=kind)
        if request.query_params.get("saved") in ("1", "true"):
            rows = rows.filter(saved=True)
        ids = request.query_params.get("ids")
        if ids:
            rows = rows.filter(pk__in=[int(x) for x in ids.split(",") if x.strip().isdigit()][:50])
        out = []
        for asset in rows[:200]:
            out.append(studio.asset_json(studio.sync(asset)))
        return Response({"assets": out})

    def post(self, request, store_id):
        from services.audio import node_audio, studio

        store = access.get_store(request.user, store_id, access.CONTENT)
        d = request.data
        kind = str(d.get("kind") or "").lower()
        seed = d.get("seed")
        try:
            seed = int(seed) if seed not in (None, "") else None
            if kind == "speech":
                asset = studio.create_speech(store, request.user, text=d.get("text"), voice_id=d.get("voice"),
                                             speed=d.get("speed", 1.0), title=d.get("title", ""), seed=seed)
            elif kind == "sfx":
                asset = studio.create_sfx(store, request.user, description=d.get("description", ""),
                                          preset=d.get("preset", ""), seconds=d.get("seconds", 8), seed=seed,
                                          title=d.get("title", ""))
            elif kind == "music":
                asset = studio.create_music(store, request.user, description=d.get("description", ""),
                                            style=d.get("style", ""), seconds=d.get("seconds", 30), bpm=d.get("bpm"),
                                            seed=seed, title=d.get("title", ""))
            else:
                return _error("bad_kind", "نوع باید speech، sfx یا music باشد.")
        except studio.StudioError as exc:
            return _error(exc.code, str(exc), exc.status)
        except node_audio.NodeAudioError as exc:
            return _error("node_" + exc.code, str(exc), status.HTTP_503_SERVICE_UNAVAILABLE)
        except (TypeError, ValueError):
            return _error("bad_request", "مقدارها درست نیست.")
        if d.get("save") in (True, "1", "true"):
            asset.saved = True
            asset.save(update_fields=["saved", "updated_at"])
        return Response(studio.asset_json(asset), status=status.HTTP_201_CREATED)


class AudioAssetDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, store_id, pk):
        from services.audio import studio

        _store, asset = _asset(request, store_id, pk, write=False)
        return Response(studio.asset_json(studio.sync(asset)))

    def patch(self, request, store_id, pk):
        from services.audio import studio

        _store, asset = _asset(request, store_id, pk, write=True)
        fields = []
        if "title" in request.data:
            asset.title = str(request.data.get("title") or "").strip()[:120] or asset.title
            fields.append("title")
        if "saved" in request.data:
            asset.saved = bool(request.data.get("saved"))
            fields.append("saved")
        if fields:
            asset.save(update_fields=fields + ["updated_at"])
        return Response(studio.asset_json(asset))

    def delete(self, request, store_id, pk):
        from services.audio import studio

        _store, asset = _asset(request, store_id, pk, write=True)
        studio.delete(asset)
        return Response(status=status.HTTP_204_NO_CONTENT)


class AudioAssetFileView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, store_id, pk):
        from services.audio import studio

        _store, asset = _asset(request, store_id, pk, write=False)
        path = studio.asset_path(asset)
        if path is None:
            raise Http404("فایلِ این صدا آماده نیست.")
        download = bool(request.query_params.get("download"))
        name = "".join(ch for ch in (asset.title or asset.kind.lower()) if ch.isalnum() or ch in " -_")[:60].strip()
        response = FileResponse(open(path, "rb"), content_type=MEDIA_TYPES.get(path.suffix.lower(), "audio/wav"),
                                as_attachment=download, filename=f"{name or f'audio-{asset.pk}'}{path.suffix}")
        response["Cache-Control"] = "private, max-age=300"
        return response


# ───────────────────────────── a finished video's background sound

def _script(request, store_id, pk, *, write):
    from .models import VideoScript

    store = access.get_store(request.user, store_id, access.CONTENT, write=write)
    return store, get_object_or_404(VideoScript, pk=pk, store=store)


def _sound_state(script) -> dict:
    from services.audio import music as music_engine

    bed = (script.finishing or {}).get("ambience_bed") or {}
    return {
        "music": script.music.name.rsplit("/", 1)[-1] if script.music else None,
        "music_asset": (script.finishing or {}).get("music_asset"),
        "music_licence": script.music_licence, "music_level_db": script.music_level_db,
        "ambience": {k: bed.get(k) for k in ("asset", "title", "level_db", "license")} if bed.get("file") else None,
        "ambience_default_db": music_engine.AMBIENCE_DB,
        "voiced": bool(script.final_video_voiced),
        "video": script.final_video_music.url if script.final_video_music else None,
    }


def _clamp(value, bounds, default):
    try:
        return max(bounds[0], min(bounds[1], float(value)))
    except (TypeError, ValueError):
        return default


class VideoSoundMixView(APIView):
    """The video studio's «صدای پس‌زمینه»: pick (or generate) music and an ambience bed from the library."""

    permission_classes = [IsAuthenticated]

    def get(self, request, store_id, pk):
        _store, script = _script(request, store_id, pk, write=False)
        return Response(_sound_state(script))

    def post(self, request, store_id, pk):
        from apps.ai.models import AudioAsset
        from apps.jobs.models import Job
        from apps.jobs.services import dispatch_job
        from services.audio import music as music_engine
        from services.audio import studio
        from services.media import files as media

        from .tasks_audio import mix_sound_task

        store, script = _script(request, store_id, pk, write=True)
        d = request.data
        finishing = dict(script.finishing or {})
        fields = set()
        now = timezone.now().isoformat()

        def library(asset_id, kind):
            asset = AudioAsset.objects.filter(pk=asset_id, store=store, kind=kind).first()
            if asset is None:
                raise ValueError("این صدا در کتابخانه‌ی فروشگاه نیست.")
            studio.sync(asset)
            path = studio.asset_path(asset)
            if path is None:
                raise ValueError("این صدا هنوز آماده نیست.")
            return asset, path

        try:
            if "music_asset" in d:
                if d["music_asset"] in (None, "", "none"):
                    finishing.pop("music_asset", None)
                else:
                    asset, path = library(d["music_asset"], AudioAsset.Kind.MUSIC)
                    target = Path(settings.MEDIA_ROOT) / "uploads" / "music" / f"script_{script.pk}_asset_{asset.pk}{path.suffix}"
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(path, target)
                    media.store(script.music, target)
                    script.music_source, script.music_licence, script.music_attribution = "", "MIT (ACE-Step)"[:20], ""
                    finishing["music_asset"] = asset.pk
                    asset.saved = True
                    asset.used_in = list(asset.used_in or []) + [{"script": script.pk, "as": "music", "at": now}]
                    asset.save(update_fields=["saved", "used_in", "updated_at"])
                    fields |= {"music", "music_source", "music_licence", "music_attribution"}
            if "music_level_db" in d:
                script.music_level_db = _clamp(d["music_level_db"], MUSIC_LEVELS, script.music_level_db)
                fields.add("music_level_db")
            bed = dict(finishing.get("ambience_bed") or {})
            if "ambience_asset" in d:
                if d["ambience_asset"] in (None, "", "none"):
                    bed = {}
                else:
                    asset, path = library(d["ambience_asset"], AudioAsset.Kind.SFX)
                    rel = f"generated/audio/script_{script.pk}/ambience_bed_{asset.pk}{path.suffix}"
                    target = Path(settings.MEDIA_ROOT) / rel
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(path, target)
                    bed.update({"asset": asset.pk, "title": asset.title, "file": rel, "license": asset.license})
                    asset.saved = True
                    asset.used_in = list(asset.used_in or []) + [{"script": script.pk, "as": "ambience", "at": now}]
                    asset.save(update_fields=["saved", "used_in", "updated_at"])
            if "ambience_level_db" in d and bed:
                bed["level_db"] = _clamp(d["ambience_level_db"], AMBIENCE_LEVELS, music_engine.AMBIENCE_DB)
            if bed:
                bed.setdefault("level_db", music_engine.AMBIENCE_DB)
                finishing["ambience_bed"] = bed
            else:
                finishing.pop("ambience_bed", None)
        except ValueError as exc:
            return _error("bad_asset", str(exc))
        script.finishing = finishing
        script.save(update_fields=sorted(fields | {"finishing", "updated_at"}))

        if not d.get("mix"):
            return Response(_sound_state(script))
        if not script.music and not (finishing.get("ambience_bed") or {}).get("file"):
            return _error("nothing_to_mix", "اول یک موسیقی یا صدای محیط انتخاب کنید.")
        if not (script.final_video_real or script.final_video_voiced or script.final_video):
            return _error("no_video", "اول باید ویدیو ساخته شده باشد.")
        job = Job.objects.create(store=store, type=Job.Type.VIDEO_EDIT,
                                 context={"script_id": script.pk, "what": "sound_mix"})
        failed = dispatch_job(job, mix_sound_task, job.id, script.pk, d.get("duck", True) not in (False, "0", "false"))
        if failed is not None:
            return failed
        return Response({"job_id": job.id, **_sound_state(script)}, status=status.HTTP_202_ACCEPTED)
