"""«مدل‌های صدا» of one processing node: on/off per model, «تست», installed / downloading / missing, «دانلود».

Four rows, three engines on the node (agent 1.8+):

    گفتار       speech   MOSS-TTS        package moss-tts
    کلونِ صدا   clone    MOSS-TTS        package moss-tts
    صدای محیط   sfx      MOSS-SoundEffect package moss-sfx
    موسیقی      music    ACE-Step 1.5    package acestep

The switches live in ComputeNode.desired["audio"] (the node gets them with every heartbeat: an engine switched off
stops at once and is never started; the site never sends it such a job - compute.audio_blocked / node_audio).
«تست» is a `node.bench` job; «دانلود» a `node.models` job - both wait in the queue while the node is off.
"""
from __future__ import annotations

from datetime import timedelta

from django.utils import timezone

from services.audio import node_audio

from .bench_models import AudioBenchmark
from .models import ComputeJob, ComputeNode

ROWS = [
    {"key": "speech", "label": "گفتار", "engine": "moss", "what": "متن به گفتارِ فارسی (MOSS-TTS)", "seconds": "۱۰ ثانیه گفتار"},
    {"key": "clone", "label": "کلونِ صدا", "engine": "moss", "what": "خواندن با صدای کلون‌شده (MOSS-TTS)", "seconds": "۸ ثانیه گفتار"},
    {"key": "sfx", "label": "صدای محیط", "engine": "sfx", "what": "صدای محیط و افکت (MOSS-SoundEffect)", "seconds": "۵ ثانیه صدا"},
    {"key": "music", "label": "موسیقی", "engine": "music", "what": "موسیقیِ بی‌کلام (ACE-Step 1.5)", "seconds": "۱۵ ثانیه موسیقی"},
]
MIN_AGENT = (1, 8)


class VoiceModelsError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def _agent_ok(node: ComputeNode) -> bool:
    try:
        return tuple(int(x) for x in str((node.capabilities or {}).get("agent") or "0").split(".")[:2]) >= MIN_AGENT
    except ValueError:
        return False


# ───────────────────────────── switches

def settings_of(node: ComputeNode) -> dict:
    return node_audio.node_settings(node.desired)


def set_settings(node: ComputeNode, data: dict) -> dict:
    desired = dict(node.desired or {})
    audio = dict(desired.get("audio") or {})
    for row in ROWS:
        if row["key"] in data:
            audio[row["key"]] = bool(data[row["key"]])
    if "idle_min" in data:
        try:
            audio["idle_min"] = max(1, min(240, int(data["idle_min"])))
        except (TypeError, ValueError):
            raise VoiceModelsError("«خالی کردنِ حافظه بعد از» باید عددی بین ۱ و ۲۴۰ دقیقه باشد.")
    desired["audio"] = audio
    node.desired = desired
    node.save(update_fields=["desired"])
    return settings_of(node)


# ───────────────────────────── benchmark

def _fa(n) -> str:
    return str(n).translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹"))


def verdict(r: dict) -> tuple[str, str]:
    """سبک / متوسط / سنگین, and what it means for the queue, from the measured numbers."""
    rtf = r.get("rtf")
    vram = (r.get("vram_peak_mb") or 0) - (r.get("vram_base_mb") or 0)
    ram_share = (r.get("ram_peak_used_mb") or 0) / (r.get("ram_total_mb") or 1) if r.get("ram_total_mb") else 0
    if rtf is None:
        return "", ""
    if rtf > 1.5 or vram > 10000 or ram_share > 0.9:
        level = "heavy"
    elif rtf <= 0.5 and vram <= 6000:
        level = "light"
    else:
        level = "medium"
    per_min = _fa(round(60 * rtf))
    load = _fa(round(r.get("load_s") or 0))
    meaning = (f"هر ۱ دقیقه صدای خروجی حدود {per_min} ثانیه کارِ سرور است؛ بالا آمدنِ مدل (بارِ اول، یا بعد از خالی شدنِ "
               f"حافظه) حدود {load} ثانیه. در این مدت کارِ دیگری (ویدیو، تصویر) روی همین سرور اجرا نمی‌شود.")
    if level == "heavy":
        meaning += " سنگین است: اگر کارِ ویدیو زیاد دارید، این مدل را فقط وقتِ لازم روشن کنید."
    return level, meaning


VERDICT_LABEL = {"light": "سبک", "medium": "متوسط", "heavy": "سنگین"}


def start_test(node: ComputeNode, model: str, user=None) -> AudioBenchmark:
    from . import services as compute

    if model not in {r["key"] for r in ROWS}:
        raise VoiceModelsError("مدلِ ناشناخته.")
    if not settings_of(node)[model]:
        raise VoiceModelsError("این مدل خاموش است؛ اول روشنش کنید.", 409)
    if (node.capabilities or {}).get("agent") and not _agent_ok(node):
        raise VoiceModelsError("عاملِ این سرور قدیمی است (تست از نسخهٔ ۱٫۸): روی آن کامپیوتر git pull و START.bat.", 409)
    job = compute.enqueue("node.bench", {"model": model}, origin="voice_models", priority=40, timeout_s=3600,
                          node=node.name, dedupe=False, require_online=False)
    return AudioBenchmark.objects.create(node=node, model=model, job_uid=job.uid, requested_by=user)


def sync_test(b: AudioBenchmark) -> AudioBenchmark:
    if b.status in (b.Status.DONE, b.Status.FAILED) or not b.job_uid:
        return b
    job = ComputeJob.objects.filter(uid=b.job_uid).first()
    if job is None:
        b.status, b.error = b.Status.FAILED, "کارِ تست در صف پیدا نشد."
    elif job.state == "COMPLETED":
        b.result = dict(((job.result or {}).get("meta") or {}).get("bench") or {})
        b.verdict = verdict(b.result)[0]
        b.status, b.finished_at = b.Status.DONE, timezone.now()
    elif job.state in ("FAILED", "CANCELLED"):
        b.status, b.finished_at = b.Status.FAILED, timezone.now()
        b.error = node_audio.friendly(job.error) if job.state == "FAILED" else "لغو شد."
    elif job.state in ("CLAIMED", "RUNNING"):
        b.status = b.Status.RUNNING
    b.save()
    return b


def test_json(b: AudioBenchmark, node: ComputeNode) -> dict:
    job = ComputeJob.objects.filter(uid=b.job_uid).first() if b.job_uid else None
    level, meaning = verdict(b.result) if b.result else ("", "")
    waiting = ""
    if b.status == b.Status.QUEUED:
        waiting = ("در صف است؛ وقتی سرورِ پردازش روشن شود اجرا می‌شود." if not node.online
                   else "در صف است؛ بعد از کارِ جاریِ سرور اجرا می‌شود.")
    has_audio = bool(job and any(o.get("name") == "bench.wav" for o in job.outputs()))
    return {"id": b.pk, "model": b.model, "label": b.get_model_display(), "status": b.status,
            "status_label": b.get_status_display(), "result": b.result, "verdict": level,
            "verdict_label": VERDICT_LABEL.get(level, ""), "meaning": meaning, "error": b.error, "waiting": waiting,
            "progress": round(job.progress, 3) if job and not job.final else None,
            "message": job.message if job and not job.final else "", "created_at": b.created_at,
            "finished_at": b.finished_at, "has_audio": has_audio,
            "audio": f"/api/v1/compute/jobs/{b.job_uid}/outputs/bench.wav" if has_audio else None}


# ───────────────────────────── downloads

def start_download(node: ComputeNode, packages: list[str]) -> ComputeJob:
    from . import services as compute

    packages = [str(p).strip() for p in packages if str(p).strip()]
    if not packages:
        raise VoiceModelsError("کدام بسته؟")
    if (node.capabilities or {}).get("agent") and not _agent_ok(node):
        raise VoiceModelsError("عاملِ این سرور قدیمی است (دانلود از پنل از نسخهٔ ۱٫۸): روی آن کامپیوتر git pull و "
                               "START.bat، یا Download-Models.bat.", 409)
    return compute.enqueue("node.models", {"action": "download", "packages": sorted(set(packages))},
                           origin="voice_models", priority=30, timeout_s=600, node=node.name, dedupe=False,
                           require_online=False)


# ───────────────────────────── the card

def card(node: ComputeNode) -> dict:
    caps = node.capabilities or {}
    audio = caps.get("audio") if isinstance(caps.get("audio"), dict) else {}
    models = caps.get("models") or {}
    pkgs = models.get("packages") or {}
    pr = models.get("progress") if models.get("running") else None
    running_pkgs = set((pr or {}).get("packages") or [])
    settings = settings_of(node)
    row_dicts = []
    for row in ROWS:
        eng = node_audio.ENGINES[row["engine"]]
        pk = pkgs.get(eng["package"]) or {}
        last = node.audio_benchmarks.filter(model=row["key"]).first()
        if last is not None:
            last = test_json(sync_test(last), node)
        row_dicts.append({
            **row, "engine_label": eng["label"], "license": eng["license"], "package": eng["package"],
            "enabled": settings[row["key"]], "installed": bool(audio.get(row["engine"])) if audio else None,
            "missing_mb": pk.get("missing_mb"), "total_mb": pk.get("total_mb"),
            "downloading": eng["package"] in running_pkgs or bool(models.get("running") and pk and not pk.get("installed")),
            "running": bool(caps.get(row["engine"])), "last_test": last,
        })
    packages = [{"package": p, **{k: v for k, v in r.items()}} for p, r in sorted(pkgs.items())]
    pct = None
    if pr and pr.get("bytes_total"):
        pct = round(100.0 * (pr.get("bytes_done") or 0) / pr["bytes_total"], 1)
    jobs = ComputeJob.objects.filter(kind="node.models", node_wanted=node.name)
    pending = list(jobs.exclude(state__in=ComputeJob.FINAL).values_list("payload", flat=True))
    started = jobs.filter(state="COMPLETED", finished_at__gte=timezone.now() - timedelta(seconds=90))
    pending += [pl for pl in started.values_list("payload", flat=True)
                if any(not (pkgs.get(p) or {}).get("installed") and p not in running_pkgs
                       for p in (pl or {}).get("packages") or [])]
    return {
        "node": {"id": node.pk, "name": node.name, "online": node.online, "agent": caps.get("agent") or "",
                 "agent_ok": _agent_ok(node), "gpu": caps.get("gpu") or ""},
        "settings": settings, "rows": row_dicts, "packages": packages,
        "download": {"running": bool(models.get("running")), "percent": pct, "progress": pr,
                     "error": models.get("error") or "",
                     "queued": sorted({p for pl in pending for p in (pl or {}).get("packages") or []
                                       if not (pkgs.get(p) or {}).get("installed") and p not in running_pkgs})},
        "preflight": caps.get("preflight") or [],
    }
