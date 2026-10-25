"""«صدا» — making speech, ambience/effects and background music, and keeping them in the shop's library.

One function per generator, each returning an AudioAsset at once:

* engines on a processing node (MOSS-TTS, a cloned voice, MOSS-SoundEffect, ACE-Step) queue a compute job;
  the row stays PENDING/RUNNING and `sync()` copies the node's file in when it is done (the panel polls);
* engines on this server (Piper offline, Edge online) answer in a second or two and the row is READY at once.

Every generator first checks what it can know without a node: the store's data policy (Edge sends the text
out), the daily allowance of generated seconds (NM_AUDIO_DAILY_SECONDS) and a node that actually has the model
(services.audio.node_audio). Identical requests are not made twice: the compute queue returns its earlier
output, and site-side speech reuses a READY row with the same settings.

Persian descriptions of a sound or of a music style are turned into English (both models were trained on
English captions) by the store's text model; a preset from the catalogue already has its English prompt.
"""
from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import uuid
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.utils import timezone

from . import node_audio

logger = logging.getLogger(__name__)

MAX_SPEECH_CHARS = 2000
SFX_MIN, SFX_MAX = 1.0, 30.0
MUSIC_MIN, MUSIC_MAX = 10.0, 180.0
SPEED_MIN, SPEED_MAX = 0.8, 1.25
SPEAKING_CPS = 12.5
DRAFT_HOURS = 24

#: music styles a shop can pick without writing a prompt (English prompts: ACE-Step reads English captions)
MUSIC_STYLES = [
    {"id": "calm", "label": "آرام و گرم", "prompt": "calm warm acoustic guitar and soft piano, gentle, cozy, instrumental", "bpm": 80},
    {"id": "upbeat", "label": "شاد و پرانرژی", "prompt": "upbeat bright pop, claps, light percussion, happy and catchy, instrumental", "bpm": 118},
    {"id": "corporate", "label": "رسمی و اطمینان‌بخش", "prompt": "modern corporate background, light piano and strings, confident and optimistic, instrumental", "bpm": 100},
    {"id": "lofi", "label": "لوفای خودمانی", "prompt": "lo-fi hip hop beat, mellow electric piano, vinyl warmth, relaxed, instrumental", "bpm": 85},
    {"id": "luxury", "label": "لوکس و مینیمال", "prompt": "elegant minimal deep house, soft pads, smooth bass, luxurious fashion runway, instrumental", "bpm": 112},
    {"id": "cinematic", "label": "سینمایی و حماسی", "prompt": "cinematic orchestral build, strings and soft drums, inspiring and emotional, instrumental", "bpm": 95},
    {"id": "persian", "label": "سنتیِ ایرانی", "prompt": "Persian traditional instrumental, santur and tar melody, soft daf rhythm, warm and nostalgic", "bpm": 90},
    {"id": "kids", "label": "کودکانه و بازیگوش", "prompt": "playful cheerful children music, ukulele, glockenspiel, whistling, instrumental", "bpm": 120},
]


class StudioError(Exception):
    """Said in Persian; status is the HTTP status the API answers with."""

    def __init__(self, message, status=400, code="bad_request"):
        super().__init__(message)
        self.status, self.code = status, code


# ───────────────────────────── files

def root() -> Path:
    from apps.compute.services import data_root

    return data_root() / "audio_library"


def asset_path(asset) -> Path | None:
    if not asset.file_name:
        return None
    path = root() / asset.file_name
    return path if path.is_file() else None


def _new_file(asset, suffix=".wav") -> tuple[str, Path]:
    rel = f"store_{asset.store_id}/{asset.kind.lower()}_{uuid.uuid4().hex[:16]}{suffix}"
    path = root() / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    return rel, path


def _probe(path) -> float:
    try:
        from services.video.ffmpeg import probe_duration

        return round(float(probe_duration(path)), 2)
    except Exception:  # noqa: BLE001
        return 0.0


def _tempo(src: Path, dest: Path, speed: float) -> Path:
    """Speech faster or slower without changing the voice (atempo); 1.0 is a plain copy."""
    if abs(speed - 1.0) < 0.01:
        shutil.copyfile(src, dest)
        return dest
    from services.video.ffmpeg import FFMPEG

    done = subprocess.run([str(FFMPEG), "-nostdin", "-y", "-v", "error", "-i", str(src), "-filter:a",
                           f"atempo={speed:.3f}", str(dest)], capture_output=True, timeout=300)
    if done.returncode != 0 or not dest.is_file():
        shutil.copyfile(src, dest)
    return dest


def store_file(asset, src: Path, *, speed: float = 1.0) -> None:
    src = Path(src)
    suffix = src.suffix.lower() if src.suffix.lower() in (".wav", ".mp3", ".m4a", ".ogg", ".flac") else ".wav"
    rel, dest = _new_file(asset, suffix)
    if asset.kind == asset.Kind.SPEECH:
        _tempo(src, dest, speed)
    else:
        shutil.copyfile(src, dest)
    asset.file_name = rel
    asset.size = dest.stat().st_size
    asset.duration = _probe(dest)
    asset.status = asset.Status.READY
    asset.error = ""


# ───────────────────────────── allowance

def daily_limit() -> int:
    return int(getattr(settings, "NM_AUDIO_DAILY_SECONDS", None) or os.environ.get("NM_AUDIO_DAILY_SECONDS") or 3600)


def seconds_of(asset) -> float:
    p = asset.params or {}
    if asset.kind == asset.Kind.SPEECH:
        return max(1.0, len(asset.text or "") / SPEAKING_CPS)
    return float(p.get("seconds") or 0)


def used_today(store) -> float:
    from apps.ai.models import AudioAsset

    since = timezone.now() - timedelta(hours=24)
    rows = AudioAsset.objects.filter(store=store, created_at__gte=since).exclude(status=AudioAsset.Status.FAILED)
    return sum(seconds_of(a) for a in rows)


def check_allowance(store, seconds: float) -> None:
    limit = daily_limit()
    used = used_today(store)
    if used + seconds > limit:
        left = max(0, int(limit - used))
        raise StudioError(f"سقفِ روزانهٔ ساختِ صدا برای این فروشگاه {limit // 60} دقیقه است و {left} ثانیه مانده؛ "
                          "فردا دوباره امتحان کنید یا متن را کوتاه‌تر کنید.", 429, "quota")


# ───────────────────────────── translation of descriptions

_PERSIAN = re.compile(r"[؀-ۿ]")


def to_english(text: str, store, kind: str) -> str:
    """A Persian description of a sound / music style -> a short English caption for the model."""
    text = re.sub(r"\s+", " ", text or "").strip()
    if not _PERSIAN.search(text):
        return text
    what = "a sound effect or ambience" if kind == "sfx" else "background music (instrumental)"
    try:
        from apps.ai.models import AIRequest
        from apps.ai.services import recorded_json_call
        from services.ai.gateway import text_provider
        from services.ai.router import TASK_REASONING, models_for

        parsed, _ = recorded_json_call(
            store=store, task_type=AIRequest.TaskType.REASONING, prompt_id="audio_prompt_en", prompt_version="1",
            provider=text_provider(store), models=models_for(TASK_REASONING),
            system="You write short English captions for an audio generation model. Answer JSON only.",
            prompt=(f"Describe {what} in English for an AI audio model, in at most 25 words, concrete sounds "
                    f"only, no names. Persian description: «{text}». Answer as {{\"prompt\": \"...\"}}"),
            validate=lambda parsed: (bool(str((parsed or {}).get("prompt", "")).strip())
                                     and not _PERSIAN.search(str((parsed or {}).get("prompt", ""))), ["prompt"]),
            validation_message="ترجمه برنگشت",
        )
        english = str(parsed.get("prompt", "")).strip()[:400]
        if english:
            return english
    except Exception as exc:  # noqa: BLE001
        logger.info("audio prompt translation failed: %s", exc)
    raise StudioError("توضیح را نشد به انگلیسی برگرداند (مدل‌ها روی توضیحِ انگلیسی آموزش دیده‌اند). یکی از "
                      "پیشنهادهای آماده را بردارید یا توضیح را انگلیسی بنویسید.", 422, "translate")


# ───────────────────────────── voices

def voices(store) -> list[dict]:
    """Every voice the «گفتار» page can speak in, best (commercial, natural) first."""
    from apps.ai.models import ClonedVoice
    from . import engines as engine_registry
    from .voice_clone import ENGINES as CLONE_ENGINES

    moss_ok, moss_why = node_audio.moss_ready()
    out = []
    for p in node_audio.presets():
        out.append({"id": f"moss:{p['id']}", "engine": "moss-fa", "name": p["name"], "gender": p["gender"],
                    "note": p["note"], "license": "Apache-2.0", "commercial": True, "where": "node",
                    "available": moss_ok, "why": moss_why, "group": "MOSS-TTS فارسی (تجاری مجاز)"})
    for v in ClonedVoice.objects.filter(store=store).order_by("-created_at"):
        meta = CLONE_ENGINES.get(v.engine) or CLONE_ENGINES["pocket"]
        ready_ok, why = (moss_ok, moss_why) if v.engine == "moss-fa" else (True, "")
        out.append({"id": f"clone:{v.pk}", "engine": v.engine, "name": v.name, "gender": "", "note": f"صدای {v.person}",
                    "license": meta["license"], "commercial": meta["commercial"], "where": "node", "cloned": True,
                    "available": v.usable and ready_ok, "why": "" if v.usable else "هنوز ساخته نشده" if not why else why,
                    "group": "صداهای کلون‌شدهٔ شما"})
    local_only = engine_registry.local_only(store)
    piper_ok = engine_registry.readiness(engine_registry.Engine(role="VOICE", kind="PIPER", name="Piper",
                                                                model_name="fa_IR-gyro-medium"))
    for vid, name, gender in (("fa_IR-gyro-medium", "gyro", "male"), ("fa_IR-mana-medium", "mana (Piper)", "female")):
        out.append({"id": f"piper:{vid}", "engine": "piper", "name": name, "gender": gender, "note": "آفلاین، روی همین سرور",
                    "license": "MIT / CC0", "commercial": True, "where": "site", "available": piper_ok[0],
                    "why": piper_ok[1], "group": "Piper (آفلاین)"})
    for vid, name, gender in (("fa-IR-FaridNeural", "فرید", "male"), ("fa-IR-DilaraNeural", "دلارا", "female")):
        out.append({"id": f"edge:{vid}", "engine": "edge", "name": name, "gender": gender,
                    "note": "آنلاین، غیررسمی — قراردادِ تجاری با مایکروسافت ندارد", "license": "بدونِ مجوزِ تجاری",
                    "commercial": False, "where": "site", "available": not local_only,
                    "why": "سیاستِ دادهٔ فروشگاه «فقط لوکال» است" if local_only else "", "group": "Edge (آنلاین)"})
    return out


# ───────────────────────────── generators

def _asset(store, user, kind, **fields):
    from apps.ai.models import AudioAsset

    return AudioAsset.objects.create(store=store, created_by=user if getattr(user, "is_authenticated", False) else None,
                                     kind=kind, **fields)


def _clean(text) -> str:
    return re.sub(r"[ \t]+", " ", str(text or "")).strip()


def create_speech(store, user, *, text, voice_id, speed=1.0, title="", seed=None):
    from apps.ai.models import AudioAsset, ClonedVoice
    from . import lexicon

    text = _clean(text)[:MAX_SPEECH_CHARS]
    if not text:
        raise StudioError("متنی برای خواندن ننوشته‌اید.")
    try:
        speed = min(SPEED_MAX, max(SPEED_MIN, float(speed or 1.0)))
    except (TypeError, ValueError):
        speed = 1.0
    engine, _sep, ref = str(voice_id or "").partition(":")
    spoken = lexicon.apply(text, store)              # brand names as the shop says them, numbers as words
    check_allowance(store, len(spoken) / SPEAKING_CPS)
    params = {"voice": voice_id, "speed": speed}
    if seed is not None:
        params["seed"] = int(seed)
    common = dict(text=text, prompt=spoken, params=params, title=(title or text[:60])[:120], saved=False)

    if engine == "moss":
        row = node_audio.preset(ref)
        if row is None:
            raise StudioError("این صدا در فهرستِ صداهای MOSS نیست.")
        payload = {"text": spoken, "engine": "moss-fa", "voice": row["id"], "out": "speech.wav", "strict": True}
        if seed is not None:
            payload["seed"] = int(seed)
        asset = _asset(store, user, AudioAsset.Kind.SPEECH, engine="moss-fa", voice_label=row["name"],
                       license="Apache-2.0", commercial=True, **common)
        return _queue(asset, "moss", "voice.tts", payload)

    if engine == "clone":
        from . import voice_clone as vc

        voice = ClonedVoice.objects.filter(pk=ref, store=store).first() if str(ref).isdigit() else None
        if voice is None:
            raise StudioError("این صدای کلون‌شده پیدا نشد.", 404, "not_found")
        vc.sync(voice)
        if not voice.usable:
            raise StudioError("این صدای کلون‌شده هنوز ساخته نشده.", 409, "not_ready")
        meta = vc.ENGINES.get(voice.engine) or vc.ENGINES["pocket"]
        asset = _asset(store, user, AudioAsset.Kind.SPEECH, engine=voice.engine, voice_label=voice.name,
                       cloned_voice=voice, license=meta["license"], commercial=meta["commercial"], **common)
        try:
            job = vc.enqueue_tts(voice, spoken, seed=seed, origin="audio_studio")
        except vc.VoiceCloneError as exc:
            asset.delete()
            raise StudioError(str(exc), 503, "node_offline") from exc
        asset.job_uid = job.uid
        asset.status = AudioAsset.Status.RUNNING if job.state != "QUEUED" else AudioAsset.Status.PENDING
        asset.save(update_fields=["job_uid", "status", "updated_at"])
        return sync(asset)

    if engine in ("piper", "edge"):
        return _site_speech(store, user, engine, ref, spoken, speed, common)
    raise StudioError("صدای انتخاب‌شده شناخته نشد.")


def _site_speech(store, user, engine, ref, spoken, speed, common):
    """Piper / Edge answer in a second or two: synthesise now, reuse an identical earlier take."""
    import tempfile

    from apps.ai.models import AudioAsset
    from . import engines as engine_registry
    from .tts import EdgeTTSProvider, PiperProvider, TTSError

    if engine == "edge" and engine_registry.local_only(store):
        raise StudioError("سیاستِ دادهٔ این فروشگاه «فقط لوکال» است و Edge متن را به مایکروسافت می‌فرستد.", 409, "policy")
    same = AudioAsset.objects.filter(store=store, kind=AudioAsset.Kind.SPEECH, engine=engine, prompt=spoken,
                                     params__voice=f"{engine}:{ref}", params__speed=speed,
                                     status=AudioAsset.Status.READY).first()
    if same is not None and asset_path(same):
        return same
    provider = PiperProvider(ref) if engine == "piper" else EdgeTTSProvider(voice=ref)
    asset = _asset(store, user, AudioAsset.Kind.SPEECH, engine=engine, voice_label=ref,
                   license="MIT / CC0" if engine == "piper" else "بدونِ مجوزِ تجاری",
                   commercial=engine == "piper", **common)
    with tempfile.TemporaryDirectory(prefix="nm-speech-") as tmp:
        try:
            raw = Path(provider.synthesize(spoken, Path(tmp) / "speech.mp3"))
        except TTSError as exc:
            asset.status, asset.error = AudioAsset.Status.FAILED, str(exc)[:2000]
            asset.save(update_fields=["status", "error", "updated_at"])
            raise StudioError(f"ساختِ گفتار نشد: {exc}", 502, "synthesis_failed") from exc
        store_file(asset, raw, speed=speed)
    asset.save()
    return asset


def create_sfx(store, user, *, description="", preset="", seconds=8, seed=None, title=""):
    from apps.ai.models import AudioAsset
    from .soundscape import BED, CATALOGUE

    try:
        seconds = min(SFX_MAX, max(SFX_MIN, float(seconds or 8)))
    except (TypeError, ValueError):
        raise StudioError("مدت باید عدد باشد.")
    kind = CATALOGUE.get(preset) if preset else None
    if kind is not None:
        prompt = kind.queries[0] + (", seamless ambience, no music, no speech" if kind.kind == BED else ", no music")
        label = kind.label
    else:
        if not _clean(description):
            raise StudioError("بنویسید چه صدایی می‌خواهید، یا یکی از پیشنهادها را بردارید.")
        prompt = to_english(description, store, "sfx")
        label = _clean(description)[:60]
    node_audio.pick_node("sfx")            # fail early, with the exact fix, before anything is stored
    check_allowance(store, seconds)
    payload = {"prompt": prompt, "seconds": seconds, "out": "sfx.wav", "seed": int(seed) if seed is not None else 0}
    asset = _asset(store, user, AudioAsset.Kind.SFX, text=_clean(description) or label, prompt=prompt,
                   params={"seconds": seconds, "preset": preset or "", "seed": payload["seed"]},
                   title=(title or label)[:120], engine="moss-sfx", license="Apache-2.0", commercial=True)
    return _queue(asset, "sfx", "voice.sfx", payload)


def create_music(store, user, *, description="", style="", seconds=30, bpm=None, seed=None, title=""):
    from apps.ai.models import AudioAsset

    try:
        seconds = min(MUSIC_MAX, max(MUSIC_MIN, float(seconds or 30)))
    except (TypeError, ValueError):
        raise StudioError("مدت باید عدد باشد.")
    chosen = next((s for s in MUSIC_STYLES if s["id"] == style), None)
    parts = [chosen["prompt"]] if chosen else []
    if _clean(description):
        parts.append(to_english(description, store, "music"))
    if not parts:
        raise StudioError("یک حال‌وهوا انتخاب کنید یا توضیح بنویسید.")
    prompt = ", ".join(parts)
    if "instrumental" not in prompt.lower():
        prompt += ", instrumental"
    try:
        bpm = int(bpm) if bpm not in (None, "", 0, "0") else (chosen or {}).get("bpm")
    except (TypeError, ValueError):
        bpm = (chosen or {}).get("bpm")
    if bpm is not None and not 50 <= int(bpm) <= 200:
        raise StudioError("ضرب‌آهنگ باید بین ۵۰ و ۲۰۰ باشد.")
    node_audio.pick_node("music")
    check_allowance(store, seconds)
    payload = {"prompt": prompt, "seconds": seconds, "out": "music.wav"}
    if bpm:
        payload["bpm"] = int(bpm)
    if seed is not None:
        payload["seed"] = int(seed)
    label = (chosen or {}).get("label") or _clean(description)[:60]
    asset = _asset(store, user, AudioAsset.Kind.MUSIC, text=_clean(description) or label, prompt=prompt,
                   params={"seconds": seconds, "style": style or "", "bpm": bpm, "seed": seed},
                   title=(title or f"موسیقی: {label}")[:120], engine="acestep", license="MIT (ACE-Step)", commercial=True)
    return _queue(asset, "music", "voice.music", payload, timeout_s=1800)


def _queue(asset, key, kind, payload, timeout_s=1200):
    try:
        job = node_audio.enqueue(key, kind, payload, store=asset.store, origin="audio_studio", timeout_s=timeout_s)
    except node_audio.NodeAudioError as exc:
        asset.delete()
        raise StudioError(str(exc), 503, "node_" + exc.code) from exc
    asset.job_uid = job.uid
    asset.save(update_fields=["job_uid", "updated_at"])
    return sync(asset)


# ───────────────────────────── following a node job

def job_of(asset):
    from apps.compute.models import ComputeJob

    if not asset.job_uid:
        return None
    return ComputeJob.objects.select_related("node").filter(uid=asset.job_uid).first()


def sync(asset):
    """Bring a PENDING / RUNNING row up to date with its compute job (cheap; called by every read)."""
    from apps.ai.models import AudioAsset

    if asset.final or not asset.job_uid:
        return asset
    job = job_of(asset)
    if job is None:
        asset.status, asset.error = AudioAsset.Status.FAILED, "کارِ این صدا در صفِ پردازش پیدا نشد؛ دوباره بسازید."
    elif job.state == "COMPLETED":
        path = node_audio.output_file(job)
        if path is None:
            asset.status, asset.error = AudioAsset.Status.FAILED, "سرورِ پردازش فایلِ صوتی برنگرداند."
        else:
            store_file(asset, path, speed=float((asset.params or {}).get("speed") or 1.0))
            if asset.cloned_voice_id:
                from . import voice_clone as vc

                vc.note_node_copy(asset.cloned_voice, job)
    elif job.state in ("FAILED", "CANCELLED"):
        from . import voice_clone as vc

        if asset.cloned_voice_id and vc.needs_restore(job):
            try:      # the node lost a Pocket voice: send it again with the recordings (as narration does)
                again = vc.enqueue_tts(asset.cloned_voice, asset.prompt, origin="audio_studio", restore=True)
                asset.job_uid = again.uid
                asset.save(update_fields=["job_uid", "updated_at"])
                return asset
            except vc.VoiceCloneError as exc:
                asset.status, asset.error = AudioAsset.Status.FAILED, str(exc)
        else:
            asset.status = AudioAsset.Status.FAILED
            asset.error = node_audio.friendly(job.error) if job.state == "FAILED" else "لغو شد."
    elif job.state in ("CLAIMED", "RUNNING"):
        asset.status = AudioAsset.Status.RUNNING
    asset.save()
    return asset


def job_progress(asset) -> dict | None:
    if asset.final:
        return None
    job = job_of(asset)
    if job is None:
        return None
    from .voice_clone import progress_fa

    return {"state": job.state, "label": job.get_state_display(), "progress": round(job.progress, 3),
            "message": progress_fa(job.message), "node": job.node.name if job.node_id else None}


def sweep_drafts(store) -> int:
    """Generated but never saved: gone after a day (the file too)."""
    from apps.ai.models import AudioAsset

    old = AudioAsset.objects.filter(store=store, saved=False, created_at__lt=timezone.now() - timedelta(hours=DRAFT_HOURS))
    n = 0
    for asset in old:
        delete(asset)
        n += 1
    return n


def delete(asset) -> None:
    path = asset_path(asset)
    if path is not None:
        path.unlink(missing_ok=True)
    asset.delete()


def asset_json(asset, *, progress=True) -> dict:
    return {
        "id": asset.pk, "kind": asset.kind, "kind_label": asset.get_kind_display(), "status": asset.status,
        "status_label": asset.get_status_display(), "title": asset.title, "text": asset.text, "prompt": asset.prompt,
        "params": asset.params or {}, "engine": asset.engine, "voice_label": asset.voice_label,
        "cloned_voice": asset.cloned_voice_id, "license": asset.license, "commercial": asset.commercial,
        "duration": asset.duration, "size": asset.size, "error": asset.error, "saved": asset.saved,
        "used_in": asset.used_in or [], "created_at": asset.created_at,
        "has_file": bool(asset.file_name) and asset.status == asset.Status.READY,
        "job": job_progress(asset) if progress else None,
    }
