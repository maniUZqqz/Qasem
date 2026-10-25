"""Voice cloning — the site's half. «کلونِ صدا»

Someone reads a few sentences (recorded in the browser or uploaded), each clip
is checked HERE right away — length, loudness, clipping, background noise —
with the same rules and thresholds as PersianAiKit's own clip check, so a shop
learns «دوباره بخوانید» while the person is still at the microphone, not after
a build on a computer that may be switched off.

The voice is built on a processing node (`voice.clone` job → agent.py →
PersianAiKit Voice `/api/voice/clone` + `/clone/clip`), where the kit checks
every clip again, this time also with speech recognition (was the sentence
actually read?), keeps the accepted ones and picks the cleanest 3–10 s clip as
the reference. Speech in the cloned voice is a `voice.tts` job naming that
voice (`/api/voice/tts`). If the node has lost the voice (another node, a
wiped folder), the job fails with VOICE_MISSING and is sent again with the best
clips attached («restore»): the node rebuilds the voice and answers.

There is no silent fallback: a shop that chose its own voice and gets
somebody else's has been lied to. When no processing node is on, narration
stops with a message that says so (`NodeOffline` → `TTSError`).

Two engines (`ClonedVoice.engine`), chosen per voice:

* **moss-fa** — MOSS-TTS-Realtime + Persian LoRA, Apache-2.0: **commercial use allowed**. Zero-shot: the
  "build" is a reference the site makes from the best accepted clips (8-20 s, `moss_ref.wav`) plus a test
  sentence on the node; every narration job carries that reference, so any node with the model can speak in
  the voice and nothing has to be kept on a node. Needs the models (Download-Models.bat on the node).
* **pocket** — Pocket-TTS-Farsi in the voice kit, CC-BY-NC-4.0: NOT for commercial use. The node keeps the
  voice; if it loses it, the site sends the clips again (VOICE_MISSING → restore).
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import wave
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote

from django.conf import settings
from django.utils import timezone

from .tts import BaseTTSProvider, TTSError, _require_output

logger = logging.getLogger(__name__)

ENGINES = {
    "moss-fa": {"id": "moss-fa", "label": "MOSS-TTS فارسی (روی سرورِ پردازش)", "license": "Apache-2.0",
                "commercial": True, "note": "استفادهٔ تجاری مجاز؛ کیفیتِ بهتر. مدل‌هایش با Download-Models.bat نصب می‌شود."},
    "pocket": {"id": "pocket", "label": "Pocket-TTS فارسی (کیتِ صدا)", "license": "CC-BY-NC-4.0", "commercial": False,
               "note": "فقط غیرتجاری؛ مدلِ سبک‌تر (بارِ اول خودکار نصب می‌شود)."},
}
ENGINE = "moss-fa"                      # new voices: the commercially usable engine
ENGINE_LABEL = ENGINES[ENGINE]["label"]
ENGINE_LICENSE = ENGINES[ENGINE]["license"]
ENGINE_COMMERCIAL = ENGINES[ENGINE]["commercial"]
MOSS_REF_MIN, MOSS_REF_MAX = 8.0, 20.0  # seconds of the reference MOSS clones from (the LoRA card: 10-30 s)


def engine_meta(voice) -> dict:
    return ENGINES.get(getattr(voice, "engine", "") or "pocket") or ENGINES["pocket"]

MIN_CLIPS = 3                  # the kit works from one; three gives it a choice of reference
RECOMMENDED_CLIPS = 20         # ~1.5–2 minutes: the reference is then nearly always a clean one
MIN_SECONDS = 1.2              # = the kit's clip check
MAX_SECONDS = 25.0
MAX_UPLOAD_BYTES = 30 * 1024 * 1024
MAX_CLIPS = 200
CUSTOM_INDEX_BASE = 1001       # sentences the shop writes itself
UPLOAD_EXTENSIONS = {".wav", ".mp3", ".m4a", ".mp4", ".aac", ".ogg", ".oga", ".opus", ".webm", ".flac", ".3gp", ".amr"}

BUILD_TIMEOUT_S = 3600         # a fresh node installs the voice service (~0.7 GB) on the first build
TTS_TIMEOUT_S = 900

SAMPLE_TEXT = "سلام! این صدای ساخته شده من است. محصول تازه ما همین حالا با ارسال رایگان به دستتان می‌رسد."

#: What the person who presses «ساختِ صدا» agrees to — stored verbatim with the voice.
CONSENT_TEMPLATE = (
    "تأیید می‌کنم که صاحبِ این صدا ({person}) خودم هستم یا رضایتِ کتبیِ او را گرفته‌ام که از روی صدایش "
    "یک صدای مصنوعی ساخته شود و فقط برای «{purpose}» در محتوای فروشگاهِ «{store}» به کار رود. "
    "از این صدا برای فریب، جعلِ هویت، تماس یا پیامِ جعلی از زبانِ او استفاده نمی‌شود، و هر وقت صاحبِ صدا "
    "بخواهد، همهٔ ضبط‌ها و صدای ساخته‌شده پاک می‌شود."
)
DEFAULT_PURPOSE = "گویندگیِ ویدیوها و محتوای فروشگاه"

#: Used only when the kit's script file is not next to the site (tests, a stripped deploy).
FALLBACK_SCRIPT = [
    "صبح زود از خانه بیرون آمدم و هوای خنکِ پاییز را نفس کشیدم.",
    "پدرم همیشه می‌گفت کارِ امروز را به فردا نینداز.",
    "کتابی که دیروز خریدم دربارهٔ تاریخِ شهرهای قدیمیِ ایران است.",
    "قطارِ مشهد ساعتِ هفت و ربع از ایستگاه حرکت می‌کند.",
    "ژاله ژاکتِ آبیِ تازه‌اش را پوشید و به پژوهشگاه رفت.",
]

SCRIPT_FILE = (Path(settings.BASE_DIR).parent / "processing" / "tools" / "PersianAiKit" / "Voice" / "tools"
               / "voice-clone-script-fa.txt")


class VoiceCloneError(Exception):
    """Something the shop must be told, in Persian."""


class NodeOffline(VoiceCloneError):
    """No processing node with the voice service is on."""


# ───────────────────────────── the reading script

@lru_cache(maxsize=1)
def script() -> tuple:
    """The kit's reading script: ({index, text, group}, …) — 81 sentences that cover every Persian sound."""
    try:
        lines = SCRIPT_FILE.read_text(encoding="utf-8").splitlines()
    except OSError:
        lines = FALLBACK_SCRIPT
    out, group = [], ""
    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#"):
            m = re.match(r"#\s*─+\s*(.+?)\s*─+\s*$", line)
            if m:
                group = m.group(1)
            continue
        out.append({"index": len(out) + 1, "text": line, "group": group})
    return tuple(out)


def script_text(index: int) -> str | None:
    rows = script()
    return rows[index - 1]["text"] if 1 <= index <= len(rows) else None


# ───────────────────────────── where the audio lives (outside MEDIA_ROOT: it is a person's voice)

def root() -> Path:
    from apps.compute.services import data_root

    return data_root() / "voice_clone"


def voice_dir(voice) -> Path:
    return root() / f"store_{voice.store_id}" / f"voice_{voice.pk}"


def clip_wav(voice, index: int) -> Path:
    return voice_dir(voice) / "clips" / f"{int(index):04d}.wav"


def preview_path(voice) -> Path:
    """The node's test sentence in the new voice, made right after the build."""
    return voice_dir(voice) / "preview.wav"


def reference_path(voice) -> Path:
    """The clip the node chose as the reference (its ref.wav)."""
    return voice_dir(voice) / "reference.wav"


def moss_reference_path(voice) -> Path:
    """The reference MOSS speaks from: the best accepted clips, one after another (24 kHz mono)."""
    return voice_dir(voice) / "moss_ref.wav"


def kit_name(voice) -> str:
    """The voice's id inside PersianAiKit: ASCII and unique per site, so two shops' «علی» never collide."""
    return f"nm-s{voice.store_id}-v{voice.pk}"


# ───────────────────────────── audio checks

def normalize(src: Path, dest: Path) -> None:
    """Any phone/browser format ⇒ 16-bit mono 44.1 kHz WAV (lossless from here on; the kit resamples itself)."""
    from services.video.ffmpeg import FFMPEG

    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.stem + ".tmp.wav")
    cmd = [str(FFMPEG), "-nostdin", "-y", "-v", "error", "-i", str(src), "-vn", "-ac", "1", "-ar", "44100",
           "-c:a", "pcm_s16le", "-t", "60", str(tmp)]
    try:
        done = subprocess.run(cmd, capture_output=True, timeout=120)
    except (OSError, subprocess.SubprocessError) as exc:
        raise VoiceCloneError(f"تبدیلِ فایلِ صوتی نشد: {exc}") from exc
    if done.returncode != 0 or not tmp.is_file() or tmp.stat().st_size <= 44:
        tmp.unlink(missing_ok=True)
        raise VoiceCloneError("این فایلِ صوتی خوانده نشد — wav، mp3، m4a یا ogg بفرستید.")
    os.replace(tmp, dest)


def read_wav(path) -> tuple:
    """16-bit WAV ⇒ (mono float32 in [-1, 1], sample rate)."""
    import numpy as np

    with wave.open(str(path), "rb") as handle:
        channels, width, rate = handle.getnchannels(), handle.getsampwidth(), handle.getframerate()
        raw = handle.readframes(handle.getnframes())
    if width != 2:
        raise VoiceCloneError("قالبِ WAV پشتیبانی نمی‌شود (فقط ۱۶ بیتی).")
    a = np.frombuffer(raw, "<i2").astype(np.float32) / 32768.0
    if channels > 1:
        a = a[: len(a) - len(a) % channels].reshape(-1, channels).mean(axis=1)
    return a, rate


def clip_quality(a, sr: int) -> dict:
    """One sentence read for cloning: length, loudness, clipping, background noise.

    The same measurements and limits as PersianAiKit's `clip_quality` (voice/gateway.py), so a clip that
    passes here passes there — except the speech-recognition test, which only the node can run.
    """
    import numpy as np

    dur = len(a) / sr if sr else 0.0
    hop = max(1, int(0.02 * sr))
    n = len(a) // hop
    frames = np.sqrt((a[: n * hop].reshape(n, hop) ** 2).mean(axis=1)) if n else np.zeros(1)
    noise = float(np.percentile(frames, 10)) + 1e-7
    speech = float(np.percentile(frames, 90)) + 1e-7
    snr = round(20 * float(np.log10(speech / noise)), 1)
    level = round(20 * float(np.log10(speech)), 1)
    clipped = float(np.mean(np.abs(a) >= 0.985)) if len(a) else 0.0
    voiced = float(np.sum(frames > noise * 4)) * hop / sr if sr else 0.0     # 12 dB above the floor
    problems = []
    if dur < MIN_SECONDS:
        problems.append("خیلی کوتاه بود — کلِ جمله را بخوانید.")
    elif dur > MAX_SECONDS:
        problems.append("خیلی بلند بود — فقط همین یک جمله را بخوانید.")
    if level < -38:
        problems.append("صدا خیلی آرام است — نزدیک‌تر به میکروفون یا بلندتر بخوانید.")
    elif voiced < 0.6 and dur >= MIN_SECONDS:
        problems.append("تقریباً صدایی ضبط نشد — میکروفون را وارسی کنید.")
    if clipped > 0.002:
        problems.append("صدا بریده (خیلی بلند) است — کمی دورتر از میکروفون یا آرام‌تر بخوانید.")
    if snr < 18:
        problems.append("نویزِ زمینه زیاد است — جای ساکت‌تری بروید یا پنکه/کولر را خاموش کنید.")
    return {"ok": not problems, "problems": problems, "message": " ".join(problems) if problems else "خوب بود ✓",
            "seconds": round(dur, 2), "snr": snr, "level": level, "clipped": round(clipped, 4),
            "voiced": round(voiced, 2)}


def clean_text(text) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def save_clip(voice, *, index: int, text: str, upload, source: str = "record"):
    """Store one read sentence: original kept, normalised WAV made, checked. Returns (clip, check)."""
    from apps.ai.models import ClonedVoiceClip

    try:
        index = int(index)
    except (TypeError, ValueError):
        raise VoiceCloneError("شمارهٔ جمله نامعتبر است.")
    official = script_text(index) if index < CUSTOM_INDEX_BASE else None
    if index < 1 or (index < CUSTOM_INDEX_BASE and official is None) or index >= CUSTOM_INDEX_BASE + MAX_CLIPS:
        raise VoiceCloneError("شمارهٔ جمله نامعتبر است.")
    # a script sentence is always the script's text: the kit compares what it hears with it
    text = official or clean_text(text)
    if not text:
        raise VoiceCloneError("متنِ جمله‌ای که خوانده شد لازم است.")
    if len(text) > 400:
        raise VoiceCloneError("متنِ جمله حداکثر ۴۰۰ نویسه.")
    if upload is None:
        raise VoiceCloneError("فایلِ صدا نیامد.")
    size = getattr(upload, "size", None) or 0
    if size > MAX_UPLOAD_BYTES:
        raise VoiceCloneError("فایل بزرگ‌تر از ۳۰ مگابایت است — فقط همان یک جمله را بفرستید.")
    original_name = os.path.basename(getattr(upload, "name", "") or "")[:200]
    ext = os.path.splitext(original_name)[1].lower() or ".wav"
    if ext not in UPLOAD_EXTENSIONS:
        raise VoiceCloneError("قالبِ فایل پشتیبانی نمی‌شود — wav، mp3، m4a، ogg یا webm بفرستید.")
    if not voice.clips.filter(index=index).exists() and voice.clips.count() >= MAX_CLIPS:
        raise VoiceCloneError(f"حداکثر {MAX_CLIPS} نمونه برای هر صدا.")

    folder = voice_dir(voice)
    orig_dir = folder / "orig"
    orig_dir.mkdir(parents=True, exist_ok=True)
    for old in orig_dir.glob(f"{index:04d}.*"):
        old.unlink(missing_ok=True)
    original = orig_dir / f"{index:04d}{ext}"
    with open(original, "wb") as fh:
        for chunk in upload.chunks() if hasattr(upload, "chunks") else [upload.read()]:
            fh.write(chunk)
    target = clip_wav(voice, index)
    normalize(original, target)
    audio, rate = read_wav(target)
    check = clip_quality(audio, rate)
    clip, _ = ClonedVoiceClip.objects.update_or_create(
        voice=voice, index=index,
        defaults={"text": text, "source": source if source in ("record", "upload") else "upload",
                  "original_name": original_name, "seconds": check["seconds"], "snr": check["snr"],
                  "level": check["level"], "clipped": check["clipped"], "ok": check["ok"],
                  "message": check["message"][:400], "node": {}},
    )
    return clip, check


def delete_clip(voice, index: int) -> bool:
    clip = voice.clips.filter(index=index).first()
    if clip is None:
        return False
    clip_wav(voice, index).unlink(missing_ok=True)
    for old in (voice_dir(voice) / "orig").glob(f"{int(index):04d}.*"):
        old.unlink(missing_ok=True)
    clip.delete()
    return True


def signature(voice) -> str:
    """Which accepted clips a build used — a different signature means «build again to include the changes»."""
    rows = [f"{c.index}:{c.updated_at.isoformat()}" for c in voice.clips.filter(ok=True).order_by("index")]
    return hashlib.sha1("|".join(rows).encode()).hexdigest()[:16]


# ───────────────────────────── processing nodes

def _ago(when) -> str:
    if not when:
        return "هرگز"
    seconds = (timezone.now() - when).total_seconds()
    if seconds < 3600:
        return f"{max(1, int(seconds // 60))} دقیقه پیش"
    if seconds < 86400:
        return f"{int(seconds // 3600)} ساعت پیش"
    return f"{int(seconds // 86400)} روز پیش"


def voice_nodes() -> list:
    """Every enabled node that has (or can start) the voice kit, with what the panel should know about it."""
    from apps.compute.models import ComputeNode

    rows = []
    for node in ComputeNode.objects.filter(enabled=True).order_by("name"):
        caps = node.capabilities or {}
        if not (caps.get("voice") or (caps.get("startable") or {}).get("voice")):
            continue
        rows.append({"name": node.name, "online": node.online and node.has("voice"), "agent": caps.get("agent"),
                     "voice_up": bool(caps.get("voice")), "clone_ready": caps.get("voice_clone"),
                     "last_seen": node.last_seen, "last_seen_text": _ago(node.last_seen), "gpu": caps.get("gpu")})
    return rows


def offline_message(voice=None) -> str:
    nodes = voice_nodes()
    seen = "، ".join(f"«{n['name']}» آخرین بار {n['last_seen_text']}" for n in nodes[:2]) or "هیچ سروری ثبت نشده"
    who = f"صدای کلون‌شدهٔ «{voice.name}»" if voice is not None else "صدای کلون‌شده"
    return (f"{who} فقط روی سرورِ پردازش (کامپیوترِ گرافیکی) ساخته و خوانده می‌شود و الان هیچ سرورِ پردازشی "
            f"با سرویسِ صدا روشن نیست ({seen}). آن کامپیوتر را روشن و START.bat را اجرا کنید. "
            "صدای دیگری به‌جای این صدا خوانده نمی‌شود.")


def pick_node(voice=None) -> str:
    """The node to use: the one that already holds this voice if it is on, else any node with the voice kit."""
    from apps.compute import services as compute

    names = [n.name for n in compute.online_nodes("voice")]
    if not names:
        raise NodeOffline(offline_message(voice))
    if voice is not None and voice.node_name in names:
        return voice.node_name
    return names[0]


def nodes_status() -> dict:
    nodes = voice_nodes()
    online = [n for n in nodes if n["online"]]
    return {"online": bool(online), "nodes": nodes, "message": "" if online else offline_message()}


def friendly(error: str) -> str:
    """A node's error as the shop should read it (the agent's own messages are bilingual already)."""
    text = (error or "").strip()
    text = re.sub(r"^(RuntimeError|JobError|VoiceMissing|SiteError|Exception):\s*", "", text)
    if "VOICE_SETUP" in text or "Setup-Voice.bat" in text:
        return ("سرویسِ صدای طبیعی و کلون روی سرورِ پردازش نصب نیست و نصبِ خودکار هم نشد. روی آن کامپیوتر یک بار "
                "tools\\PersianAiKit\\Voice\\Setup-Voice.bat را اجرا کنید (پایتونِ ۳٫۱۰ تا ۳٫۱۳) و START.bat را دوباره باز کنید. "
                "جزئیات: " + text[:300])
    if "not reachable" in text or "unreachable" in text:
        return "سرویسِ صدا روی سرورِ پردازش جواب نداد (ویرایشگرِ صدا بالا نیامد). جزئیات: " + text[:300]
    return text[:600] or "کار روی سرورِ پردازش ناموفق بود."


#: the agent reports progress in English; the panel shows it in Persian
_PROGRESS_FA = [
    (r"^voice clone: clip (\d+)/(\d+) checked", r"نمونهٔ \1 از \2 روی سرور وارسی شد"),
    (r"^voice clone: preparing the voice service", "آماده‌سازیِ سرویسِ صدا"),
    (r"^voice clone: speaking a test sentence", "ساختِ جملهٔ نمونه با صدای تازه"),
    (r"^voice: creating the Python environment.*", "نصبِ بارِ اولِ سرویسِ صدا: محیطِ پایتون"),
    (r"^voice: installing (core )?Python packages.*|^voice: installing core packages.*",
     "نصبِ بارِ اولِ سرویسِ صدا: بسته‌های پایتون"),
    (r"^voice: downloading Pocket-TTS.*", "نصبِ بارِ اولِ سرویسِ صدا: دانلودِ مدل (۴۹۰ مگابایت)"),
    (r"^voice: waiting for the voice service.*", "منتظرِ بالا آمدنِ سرویسِ صدا"),
    (r"^preparing the voice service", "آماده‌سازیِ سرویسِ صدا"),
    (r"^rebuilding the voice on this node.*", "ساختِ دوبارهٔ صدا روی این سرور از روی ضبط‌ها"),
    (r"^preparing services|^starting voice.*|^still waiting for voice.*", "روشن کردنِ ویرایشگرِ صدا روی سرورِ پردازش"),
    (r"^downloading inputs", "دریافتِ ورودی‌ها"),
    (r"^started on (.+)", r"شروع روی \1"),
]


def progress_fa(message: str) -> str:
    for pattern, repl in _PROGRESS_FA:
        if re.match(pattern, message or ""):
            return re.sub(pattern, repl, message, count=1)
    return message or ""


def job_state(job) -> dict | None:
    if job is None:
        return None
    return {"uid": str(job.uid), "state": job.state, "label": job.get_state_display(), "progress": round(job.progress, 3),
            "message": progress_fa(job.message), "node": job.node.name if job.node_id else None, "final": job.final,
            "error": friendly(job.error) if job.error and job.state in ("FAILED", "CANCELLED") else "",
            "created": job.created_at, "finished": job.finished_at}


# ───────────────────────────── building

def consent_text(person: str, purpose: str, store_name: str) -> str:
    return CONSENT_TEMPLATE.format(person=person, purpose=purpose or DEFAULT_PURPOSE, store=store_name)


def _consent_payload(voice) -> dict:
    return {"given": True, "text": voice.consent_text, "at": voice.consent_at.isoformat() if voice.consent_at else "",
            "by": voice.consent_by_id, "store": voice.store_id}


def _clip_rows(voice, clips) -> tuple[list, dict]:
    rows, files = [], {}
    for clip in clips:
        name = f"clip_{clip.index:04d}.wav"
        rows.append({"file": name, "index": clip.index, "text": clip.text})
        files[name] = str(clip_wav(voice, clip.index))
    return rows, files


def usable_clips(voice) -> list:
    return [c for c in voice.clips.filter(ok=True).order_by("index") if clip_wav(voice, c.index).is_file()]


def start_build(voice):
    """Send every accepted clip to a node: it makes the voice and a test sentence in it (`voice.clone`)."""
    from apps.compute import services as compute
    from apps.compute.models import ComputeJob

    if voice.status == voice.Status.BUILDING and voice.build_job:
        running = ComputeJob.objects.filter(uid=voice.build_job).exclude(state__in=ComputeJob.FINAL).first()
        if running is not None:
            raise VoiceCloneError("این صدا همین حالا در حالِ ساخت است.")
    if not voice.consent_text or not voice.consent_at:
        raise VoiceCloneError("بدونِ رضایتِ ثبت‌شدهٔ صاحبِ صدا ساخته نمی‌شود.")
    clips = usable_clips(voice)
    if len(clips) < MIN_CLIPS:
        raise VoiceCloneError(f"دست‌کم {MIN_CLIPS} جملهٔ پذیرفته لازم است (الان {len(clips)}). "
                              f"برای بهترین نتیجه {RECOMMENDED_CLIPS} جمله یا بیشتر بخوانید.")
    if voice.engine == "moss-fa":
        return _start_moss_build(voice, clips)
    node = pick_node(voice)
    old_node, old_id = voice.node_name, voice.node_voice_id
    rows, files = _clip_rows(voice, clips)
    payload = {
        "name": kit_name(voice), "person": voice.person, "purpose": voice.purpose or DEFAULT_PURPOSE,
        "consent": _consent_payload(voice), "clips": rows, "sample_text": SAMPLE_TEXT,
        # same node ⇒ the agent deletes the old copy first (a rebuild, not a second voice)
        "replace": old_id if (old_id and old_node == node and old_id != kit_name(voice)) else "",
        "nm_voice": voice.pk, "nm_signature": signature(voice),
    }
    job = compute.enqueue("voice.clone", payload, files, store=voice.store, origin="voice_clone", priority=50,
                          timeout_s=BUILD_TIMEOUT_S, node=node, dedupe=False)
    if old_id and old_node and old_node != node:
        forget_on_node(voice, old_node, old_id)
    voice.status = voice.Status.BUILDING
    voice.build_job = job.uid
    voice.error = ""
    voice.save(update_fields=["status", "build_job", "error", "updated_at"])
    return job


def _rank(clip):
    node = clip.node or {}
    snr = node.get("snr") if node.get("snr") is not None else clip.snr
    return (bool(node.get("ok", True)), 3.0 <= (clip.seconds or 0) <= 10.0, snr or 0)


def build_moss_reference(voice, clips) -> tuple[Path, list]:
    """The cleanest accepted clips, joined with short pauses until 8-20 s: what MOSS clones the voice from."""
    import numpy as np

    chosen, total = [], 0.0
    for clip in sorted(clips, key=_rank, reverse=True):
        if total >= MOSS_REF_MIN and total + (clip.seconds or 0) > MOSS_REF_MAX:
            continue
        chosen.append(clip)
        total += (clip.seconds or 0) + 0.25
        if total >= MOSS_REF_MAX - 2:
            break
    chosen.sort(key=lambda c: c.index)
    parts, rate = [], 44100
    for clip in chosen:
        audio, rate = read_wav(clip_wav(voice, clip.index))
        parts += [audio, np.zeros(int(0.25 * rate), dtype=np.float32)]
    joined = np.concatenate(parts[:-1]) if parts else np.zeros(rate, dtype=np.float32)
    peak = float(np.max(np.abs(joined))) or 1.0
    joined = joined * min(1.0, 0.89 / peak)
    tmp = voice_dir(voice) / "moss_ref.44k.wav"
    tmp.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(tmp), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes((np.clip(joined, -1, 1) * 32767).astype("<i2").tobytes())
    out = moss_reference_path(voice)
    from services.video.ffmpeg import FFMPEG

    done = subprocess.run([str(FFMPEG), "-nostdin", "-y", "-v", "error", "-i", str(tmp), "-ac", "1", "-ar", "24000",
                           "-c:a", "pcm_s16le", str(out)], capture_output=True, timeout=120)
    if done.returncode != 0 or not out.is_file():
        shutil.copyfile(tmp, out)
    tmp.unlink(missing_ok=True)
    return out, chosen


def _start_moss_build(voice, clips):
    from apps.compute import services as compute

    from . import node_audio

    try:
        node = node_audio.pick_node("moss", prefer=voice.node_name)
    except node_audio.NodeAudioError as exc:
        raise (NodeOffline if exc.code == "offline" else VoiceCloneError)(str(exc)) from exc
    ref, chosen = build_moss_reference(voice, clips)
    used = {c.index for c in chosen}
    payload = {
        "engine": "moss-fa", "name": kit_name(voice), "person": voice.person,
        "purpose": voice.purpose or DEFAULT_PURPOSE, "consent": _consent_payload(voice), "sample_text": SAMPLE_TEXT,
        "reference": "moss_ref.wav", "nm_voice": voice.pk, "nm_signature": signature(voice),
        "clips": [{"index": c.index, "text": c.text, "seconds": c.seconds, "in_reference": c.index in used} for c in clips],
    }
    job = compute.enqueue("voice.clone", payload, {"moss_ref.wav": str(ref)}, store=voice.store, origin="voice_clone",
                          priority=50, timeout_s=BUILD_TIMEOUT_S, node=node, dedupe=False)
    voice.status = voice.Status.BUILDING
    voice.build_job = job.uid
    voice.error = ""
    voice.save(update_fields=["status", "build_job", "error", "updated_at"])
    return job


def forget_on_node(voice, node_name: str, node_voice_id: str) -> None:
    """Delete a voice's copy on a node (best effort; waits in the queue if that node is off)."""
    from apps.compute import services as compute

    if not (node_name and node_voice_id):
        return
    try:
        compute.enqueue("voice.http", {"method": "DELETE", "path": f"/api/voice/voices/{quote(node_voice_id)}",
                                       "out": "deleted.json"},
                        store=voice.store, origin="voice_clone", node=node_name, dedupe=False,
                        require_online=False, timeout_s=300)
    except Exception as exc:  # noqa: BLE001 — never block deleting the site's copy
        logger.warning("voice clone: could not queue the node-side delete of %s on %s: %s", node_voice_id, node_name, exc)


def sync(voice):
    """Pick up a finished build (called whenever the panel looks). Returns the build job or None."""
    from apps.compute.models import ComputeJob

    if not voice.build_job:
        return None
    job = ComputeJob.objects.select_related("node").filter(uid=voice.build_job).first()
    if voice.status != voice.Status.BUILDING:
        return job
    if job is None:
        _build_failed(voice, "کارِ ساخت در صفِ پردازش پیدا نشد — دوباره «ساختِ صدا» را بزنید.")
    elif job.state == ComputeJob.State.COMPLETED:
        ingest(voice, job)
    elif job.state in (ComputeJob.State.FAILED, ComputeJob.State.CANCELLED):
        _build_failed(voice, friendly(job.error) if job.state == "FAILED" else "ساخت لغو شد.")
    return job


def _build_failed(voice, message: str) -> None:
    # a voice that was built before keeps narrating (the node rebuilds it from the clips if it lost it)
    voice.status = voice.Status.READY if voice.revision > 0 and voice.node_voice_id else voice.Status.FAILED
    voice.error = (("ساختِ دوباره نشد؛ صدای قبلی هنوز به کار می‌رود. " if voice.status == voice.Status.READY else "")
                   + message)[:2000]
    voice.save(update_fields=["status", "error", "updated_at"])


def ingest(voice, job) -> None:
    """A finished `voice.clone`: per-clip verdicts, the voice id, the reference and the test sentence."""
    from apps.compute import services as compute

    data = {}
    path = compute.output_path(job, "clone.json")
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
    results = {}
    for row in data.get("clips") or []:
        try:
            results[int(row.get("index"))] = row
        except (TypeError, ValueError):
            continue
    for clip in voice.clips.all():
        row = results.get(clip.index)
        if row is not None:
            clip.node = {k: row.get(k) for k in ("ok", "message", "heard", "wer", "snr", "seconds")}
            clip.save(update_fields=["node"])
    accepted = [r for r in results.values() if r.get("ok")]
    rejected = [r for r in results.values() if not r.get("ok")]
    report = {"accepted": len(accepted), "rejected": len(rejected), "minutes": data.get("minutes"),
              "check": data.get("check"), "took": data.get("took"), "engine": data.get("engine") or ENGINE,
              "job": str(job.uid), "node": job.node.name if job.node_id else "", "signature": signature(voice),
              "sample_text": data.get("sample_text") or SAMPLE_TEXT}
    voice.report = report
    if not data.get("ready") or not data.get("voice_id"):
        reasons = "؛ ".join(sorted({str(r.get("message") or "") for r in rejected if r.get("message")}))[:600]
        _build_failed(voice, "سرورِ پردازش هیچ‌کدام از نمونه‌ها را نپذیرفت" + (f": {reasons}" if reasons else "."))
        voice.save(update_fields=["report"])
        return
    folder = voice_dir(voice)
    folder.mkdir(parents=True, exist_ok=True)
    for out_name, dest in (("ref.wav", reference_path(voice)), ("sample.wav", preview_path(voice))):
        src = compute.output_path(job, out_name)
        if src.is_file():
            shutil.copyfile(src, dest)
    voice.node_name = job.node.name if job.node_id else voice.node_name
    voice.node_voice_id = str(data["voice_id"])[:80]
    voice.revision += 1
    voice.built_at = timezone.now()
    voice.status = voice.Status.READY
    voice.error = ""
    voice.engine = data.get("engine") or ENGINE
    voice.save()


# ───────────────────────────── speaking in the cloned voice

def restore_bundle(voice, limit: int = 3) -> tuple[dict, dict]:
    """The best accepted clips, so a node that lacks the voice can rebuild it before speaking."""
    clips = usable_clips(voice)

    def rank(c):
        node = c.node or {}
        snr = node.get("snr") if node.get("snr") is not None else c.snr
        in_range = 3.0 <= (c.seconds or 0) <= 10.0
        return (bool(node.get("ok", True)), in_range, snr or 0)

    best = sorted(clips, key=rank, reverse=True)[:limit]
    rows, files = _clip_rows(voice, best)
    return {"name": kit_name(voice), "person": voice.person, "purpose": voice.purpose or DEFAULT_PURPOSE,
            "consent": _consent_payload(voice), "clips": rows}, files


def enqueue_tts(voice, text: str, *, seed=None, origin: str = "voice_clone", restore: bool = False):
    from apps.compute import services as compute

    if voice.engine == "moss-fa":
        return _enqueue_moss_tts(voice, text, seed=seed, origin=origin)
    node = pick_node(voice)
    payload = {"text": text, "voice": voice.node_voice_id or kit_name(voice), "engine": voice.engine or ENGINE,
               "clone": True, "strict": True, "out": "speech.wav", "rev": voice.revision, "nm_voice": voice.pk}
    if seed is not None:
        payload["seed"] = int(seed)
    files = {}
    if restore or node != voice.node_name:
        payload["restore"], files = restore_bundle(voice)
    return compute.enqueue("voice.tts", payload, files, store=voice.store, origin=origin, priority=60,
                           timeout_s=TTS_TIMEOUT_S, node=node)


def _enqueue_moss_tts(voice, text, *, seed=None, origin="voice_clone"):
    """MOSS speaks in the voice of the reference that travels with every job: any node with the model will do."""
    from . import node_audio

    ref = moss_reference_path(voice)
    if not ref.is_file():
        clips = usable_clips(voice)
        if not clips:
            raise VoiceCloneError("ضبط‌های این صدا روی سایت نیست؛ صدا را دوباره بسازید.")
        ref, _chosen = build_moss_reference(voice, clips)
    payload = {"text": text, "engine": "moss-fa", "reference": "moss_ref.wav", "clone": True, "strict": True,
               "out": "speech.wav", "rev": voice.revision, "nm_voice": voice.pk}
    if seed is not None:
        payload["seed"] = int(seed)
    try:
        return node_audio.enqueue("moss", "voice.tts", payload, {"moss_ref.wav": str(ref)}, store=voice.store,
                                  origin=origin, timeout_s=TTS_TIMEOUT_S, prefer=voice.node_name)
    except node_audio.NodeAudioError as exc:
        raise (NodeOffline if exc.code == "offline" else VoiceCloneError)(str(exc)) from exc


def needs_restore(job) -> bool:
    return bool(job is not None and job.state == "FAILED" and "VOICE_MISSING" in (job.error or "")
                and not (job.payload or {}).get("restore"))


def note_node_copy(voice, job) -> None:
    """A speech job that rebuilt the voice (restore) tells us where it now lives."""
    meta = (job.result or {}).get("meta") or {}
    new_id = meta.get("voice_id")
    node = job.node.name if job.node_id else ""
    if new_id and (new_id != voice.node_voice_id or (node and node != voice.node_name)):
        voice.node_voice_id = str(new_id)[:80]
        if node:
            voice.node_name = node
        voice.save(update_fields=["node_voice_id", "node_name", "updated_at"])


def speech_output(job) -> Path | None:
    from apps.compute import services as compute

    for out in job.outputs():
        if str(out.get("name", "")).lower().endswith(".wav"):
            path = compute.output_path(job, out["name"])
            if path.is_file():
                return path
    return None


def synthesize_job(voice, text: str, *, seed=None, origin: str = "narration", wait_s: int = TTS_TIMEOUT_S):
    """Speak `text` in the cloned voice and wait (Celery / short web requests). Raises VoiceCloneError."""
    from apps.compute import services as compute

    try:
        job = enqueue_tts(voice, text, seed=seed, origin=origin)
        try:
            job = compute.wait(job, wait_s)
        except compute.ComputeFailed as exc:
            job.refresh_from_db()
            if not needs_restore(job):
                raise VoiceCloneError(friendly(str(exc))) from exc
            logger.info("voice clone %s: node %s lost the voice, restoring it from the clips", voice.pk, job.node_id)
            job = compute.wait(enqueue_tts(voice, text, seed=seed, origin=origin, restore=True), wait_s)
    except compute.ComputeUnavailable as exc:
        raise NodeOffline(offline_message(voice)) from exc
    except compute.ComputeError as exc:
        raise VoiceCloneError(friendly(str(exc))) from exc
    note_node_copy(voice, job)
    if speech_output(job) is None:
        raise VoiceCloneError("سرورِ پردازش صدایی برنگرداند.")
    return job


class ClonedVoiceProvider(BaseTTSProvider):
    """Narration in a cloned voice, spoken by a processing node. Never falls back to another voice."""

    name = "clone"
    #: our own processing server, like Ollama/ComfyUI on a node: the text stays inside the company
    is_local = True
    #: how long one take may wait for the node (the voice-settings preview lowers it)
    wait_s = TTS_TIMEOUT_S

    def __init__(self, voice):
        self.row = voice
        self.voice = f"clone:{voice.name} r{voice.revision}"
        online = any(n["online"] for n in voice_nodes())
        engine = "MOSS-TTS" if voice.engine == "moss-fa" else "Pocket-TTS"
        self.processor = (f"صدای کلون‌شدهٔ «{voice.name}» — سرورِ پردازش ({engine})"
                          + ("" if online else " · سرور الان خاموش است"))
        self._takes: dict[str, int] = {}

    def synthesize(self, text: str, out_path) -> Path:
        out = Path(out_path).with_suffix(".wav")
        out.parent.mkdir(parents=True, exist_ok=True)
        takes = self._takes.get(text, 0)
        self._takes[text] = takes + 1
        # a retake (narration QC asked for one) must be a different take, not the cached first one
        seed = None if takes == 0 else 7919 * takes + len(text)
        try:
            job = synthesize_job(self.row, text, seed=seed, wait_s=self.wait_s)
        except VoiceCloneError as exc:
            raise TTSError(str(exc)) from exc
        shutil.copyfile(speech_output(job), out)
        return _require_output(out, "voice clone")

    def describe(self) -> dict:
        out = super().describe()
        meta = engine_meta(self.row)
        out.update({"cloned_voice": self.row.pk, "license": meta["license"], "commercial": meta["commercial"]})
        return out


def provider_for(store, clone_id) -> ClonedVoiceProvider:
    from apps.ai.models import ClonedVoice

    voice = ClonedVoice.objects.filter(pk=clone_id, store=store).first() if store is not None else None
    if voice is None:
        raise TTSError("صدای کلون‌شده‌ای که گوینده بود دیگر نیست — در «صدا و گوینده» گوینده را دوباره انتخاب کنید.")
    if not voice.usable:
        raise TTSError(f"صدای کلون‌شدهٔ «{voice.name}» هنوز ساخته نشده ({voice.get_status_display()}) — "
                       "در زبانهٔ «کلونِ صدا» آن را بسازید یا گوینده را عوض کنید.")
    return ClonedVoiceProvider(voice)


# ───────────────────────────── using / deleting

def set_in_use(voice, use: bool) -> None:
    profile = voice.store.profile
    saved = dict(profile.voice_profile or {})
    if use:
        if not voice.usable:
            raise VoiceCloneError("اول صدا را بسازید؛ صدای ساخته‌نشده نمی‌تواند گوینده باشد.")
        saved["cloned_voice"] = voice.pk
    elif saved.get("cloned_voice") == voice.pk:
        saved.pop("cloned_voice", None)
    else:
        return
    profile.voice_profile = saved
    profile.save(update_fields=["voice_profile"])


def in_use_id(store):
    try:
        return (store.profile.voice_profile or {}).get("cloned_voice")
    except Exception:  # noqa: BLE001
        return None


def delete_voice(voice) -> None:
    """Everything goes: the node's copy (queued), the recordings, the row — and the shop's choice of narrator."""
    from apps.compute import services as compute
    from apps.compute.models import ComputeJob

    if voice.build_job:
        job = ComputeJob.objects.filter(uid=voice.build_job).first()
        if job is not None and not job.final:
            compute.cancel(job)
    forget_on_node(voice, voice.node_name, voice.node_voice_id)
    try:
        set_in_use(voice, False)
    except Exception:  # noqa: BLE001
        pass
    shutil.rmtree(voice_dir(voice), ignore_errors=True)
    voice.delete()


# ───────────────────────────── what the panel sees

def clip_json(clip) -> dict:
    return {"index": clip.index, "text": clip.text, "source": clip.source, "original_name": clip.original_name,
            "seconds": clip.seconds, "snr": clip.snr, "level": clip.level, "clipped": clip.clipped, "ok": clip.ok,
            "message": clip.message, "node": clip.node or {}, "updated_at": clip.updated_at}


def voice_json(voice, *, with_clips: bool = False, job=None) -> dict:
    clips = list(voice.clips.all())
    ok = [c for c in clips if c.ok]
    report = voice.report or {}
    data = {
        "id": voice.pk, "name": voice.name, "person": voice.person, "purpose": voice.purpose,
        "status": voice.status, "status_label": voice.get_status_display(), "usable": voice.usable,
        "in_use": in_use_id(voice.store) == voice.pk,
        "engine": voice.engine, "engine_label": engine_meta(voice)["label"], "license": engine_meta(voice)["license"],
        "commercial": engine_meta(voice)["commercial"],
        "consent": {"text": voice.consent_text, "at": voice.consent_at,
                    "by": (voice.consent_by.get_full_name() or voice.consent_by.get_username()) if voice.consent_by_id else ""},
        "node_name": voice.node_name, "revision": voice.revision, "built_at": voice.built_at,
        "error": voice.error, "report": report,
        "clips_ok": len(ok), "clips_total": len(clips), "seconds_ok": round(sum(c.seconds for c in ok), 1),
        "needs_rebuild": bool(voice.revision and report.get("signature") and report.get("signature") != signature(voice)),
        "has_preview": preview_path(voice).is_file(),
        "has_reference": reference_path(voice).is_file() or moss_reference_path(voice).is_file(),
        "build": job_state(job),
        "created_at": voice.created_at,
    }
    if with_clips:
        data["clips"] = [clip_json(c) for c in clips]
    return data


def set_engine(voice, engine: str) -> None:
    """Switch a voice between MOSS and Pocket; the next «ساختِ صدا» builds it for the new engine."""
    if engine not in ENGINES:
        raise VoiceCloneError("موتورِ کلونِ ناشناخته.")
    if engine == voice.engine:
        return
    voice.engine = engine
    voice.engine_license = ENGINES[engine]["license"]
    if voice.revision:
        voice.report = dict(voice.report or {}, signature="engine-changed")   # shows «build again»
    voice.save(update_fields=["engine", "engine_license", "report", "updated_at"])


def limits() -> dict:
    return {"min_clips": MIN_CLIPS, "recommended_clips": RECOMMENDED_CLIPS, "min_seconds": MIN_SECONDS,
            "max_seconds": MAX_SECONDS, "max_upload_mb": MAX_UPLOAD_BYTES // (1024 * 1024),
            "custom_index_base": CUSTOM_INDEX_BASE, "extensions": sorted(UPLOAD_EXTENSIONS)}
