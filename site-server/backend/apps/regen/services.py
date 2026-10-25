"""گردشِ کارِ بازسازیِ تکه: منبع ⇐ جلسه ⇐ نسخه (آماده‌سازی ⇐ ساخت روی گره ⇐ چسباندن ⇐ آماده).

کجا چه اجرا می‌شود:

* **سرورِ سایت** — ffprobe، فریم‌های مرزی، نقشه، گراف، پس‌پردازشِ تکه (فقط فریم‌های جایگزین؛ numpy/OpenCV)،
  چسباندن و وارسیِ درز. چسباندن معمولاً «هوشمند» است (فقط GOPهای دورِ تکه دوباره رمزگذاری می‌شوند)، پس کارِ
  سرور متناسب با طولِ تکه است نه طولِ ویدیو؛ ویدیوی ۱۰ دقیقه‌ای هم چند ثانیه. رمزگذاریِ کامل فقط برای منبعی
  که x264 ِ قابلِ تکرار ندارد (گوشی/HEVC) و زیرِ nice.
* **سرورِ پردازش (GPU)** — فقط ساختِ تکه با ComfyUI، از راهِ همان کارِ «comfy.graph» که الان هست: چند PNG ِ
  مرزی بالا می‌رود و فریم‌های PNG ِ مدل پایین می‌آید. ویدیوی کامل هرگز جابه‌جا نمی‌شود (سقفِ ۲۰۰ مگابایتیِ
  nginx و اینترنتِ گره هم همین را می‌خواهد) و agent.py دست نمی‌خورد.

کارهای Celery هیچ‌جا منتظرِ گره نمی‌مانند: کار در صفِ apps.compute می‌نشیند و `refresh` (هر چند ثانیه از
Celery، و هر بار که پنل وضعیت را می‌خواهد) وضعیتش را می‌خواند؛ پایانِ کار ⇐ یک بار (با UPDATE ِ شرطی) چسباندن.
"""
from __future__ import annotations

import logging
import math
import os
import random
import re
import shutil
import statistics
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from services.video.regen import assemble as asm
from services.video.regen import media, seams
from services.video.regen import plan as planmod
from services.video.regen import stitch

from .models import RegenSession, RegenVersion

logger = logging.getLogger(__name__)

MAX_UPLOAD_MB = 500
ALLOWED_SUFFIXES = (".mp4", ".mov", ".m4v", ".webm", ".mkv", ".avi")
#: نسخه‌های قبول‌نشدهٔ آماده که ویدیوی کاملشان نگه داشته می‌شود (دیسکِ سرور کوچک است)
KEEP_RESULTS = 4
PREVIEW_PAD_SECONDS = 2.0


class RegenError(Exception):
    """خطایی که متنش برای کاربر است."""


def media_root() -> Path:
    return Path(settings.MEDIA_ROOT)


def abs_path(rel: str) -> Path:
    return media_root() / rel


def media_url(rel: str | None) -> str | None:
    if not rel:
        return None
    return settings.MEDIA_URL.rstrip("/") + "/" + rel.lstrip("/")


def max_seconds() -> float:
    return float(getattr(settings, "NM_REGEN_MAX_SECONDS", os.environ.get("NM_REGEN_MAX_SECONDS", 20)))


# ───────────────────────────── منبع‌ها

KIND_LABELS = {
    "script": "ویدیوی ساخته‌شده با AI",
    "cut": "برشِ شبکه‌ای",
    "upload": "ویدیوی آپلودی",
    "edited": "خروجیِ ادیتور",
    "up3d": "رندرِ سه‌بعدی",
    "regen": "بازسازی‌شده",
    "file": "آپلود در همین صفحه",
}


def _field_path(field) -> Path | None:
    try:
        if field and field.name:
            p = Path(field.path)
            return p if p.is_file() else None
    except (ValueError, NotImplementedError):
        return None
    return None


def _script_best(script):
    for name in ("final_video_music", "final_video_voiced", "final_video_real", "final_video"):
        f = getattr(script, name, None)
        if _field_path(f):
            return name, f
    return None, None


def list_sources(store, user, limit: int = 40) -> list[dict]:
    from apps.content.models import UploadedVideo, VideoCut, VideoScript

    out = []
    for s in VideoScript.objects.filter(store=store).select_related("product").order_by("-created_at")[:limit]:
        name, f = _script_best(s)
        if f:
            out.append({"ref": f"script:{s.pk}", "kind": "script", "title": f"{s.product.name} — ویدیوی #{s.pk}",
                        "url": f.url, "created_at": s.created_at})
    for c in VideoCut.objects.filter(script__store=store).select_related("script__product").order_by("-created_at")[:limit]:
        if _field_path(c.video):
            out.append({"ref": f"cut:{c.pk}", "kind": "cut", "title": f"{c.script.product.name} — برشِ {c.format}",
                        "url": c.video.url, "created_at": c.created_at})
    for u in UploadedVideo.objects.filter(store=store).order_by("-created_at")[:limit]:
        if _field_path(u.video):
            out.append({"ref": f"upload:{u.pk}", "kind": "upload", "title": u.title or f"آپلود #{u.pk}",
                        "url": u.video.url, "created_at": u.created_at})
        if _field_path(u.edited):
            out.append({"ref": f"upload:{u.pk}:edited", "kind": "edited",
                        "title": (u.title or f"آپلود #{u.pk}") + " — تدوین‌شده", "url": u.edited.url,
                        "created_at": u.updated_at})
    for v in (RegenVersion.objects.filter(session__store=store, accepted_at__isnull=False, discarded=False)
              .select_related("session").order_by("-accepted_at")[:limit]):
        if v.files.get("result") and abs_path(v.files["result"]).is_file():
            out.append({"ref": f"regen:{v.pk}", "kind": "regen", "title": f"{v.session.title} — نسخهٔ {v.number}",
                        "url": media_url(v.files["result"]), "created_at": v.accepted_at})
    out += _up3d_sources(user, limit=12)
    for item in out:
        item["kind_label"] = KIND_LABELS.get(item["kind"], item["kind"])
    out.sort(key=lambda x: x["created_at"] or timezone.now(), reverse=True)
    return out


def _up3d_sources(user, limit: int = 12) -> list[dict]:
    try:
        from apps.up3d.models import Job as Up3dJob
    except Exception:  # noqa: BLE001 — بخشِ سه‌بعدی نصب نیست
        return []
    qs = Up3dJob.objects.filter(state="COMPLETED").select_related("project").order_by("-finished")
    if not getattr(user, "is_staff", False):
        qs = qs.filter(project__owner=user)
    out = []
    for j in qs[:limit * 3]:
        rel = (j.files or {}).get("final.mp4")
        if not rel or not (Path(settings.UP3D_DATA_DIR) / rel).is_file():
            continue
        out.append({"ref": f"up3d:{j.pk}", "kind": "up3d",
                    "title": f"{j.project.title if j.project else 'سه‌بعدی'} — رندرِ #{j.pk}",
                    "url": settings.UP3D_FILES_URL + rel.replace("\\", "/"), "created_at": j.finished})
        if len(out) >= limit:
            break
    return out


def resolve_source(store, user, ref: str) -> tuple[str, str, Path]:
    """(title, kind, مسیرِ فایل) برای یک مرجع؛ RegenError اگر نیست یا اجازه نیست."""
    from apps.content.models import UploadedVideo, VideoCut, VideoScript

    m = re.fullmatch(r"(script|cut|upload|up3d|regen):(\d+)(?::(\w+))?", (ref or "").strip())
    if not m:
        raise RegenError("مرجعِ ویدیو نامعتبر است.")
    kind, pk, extra = m.group(1), int(m.group(2)), m.group(3)
    path = None
    title = ""
    if kind == "script":
        s = VideoScript.objects.filter(pk=pk, store=store).select_related("product").first()
        if s:
            field = getattr(s, extra, None) if extra and extra.startswith("final_video") else _script_best(s)[1]
            path, title = _field_path(field), f"{s.product.name} — ویدیوی #{s.pk}"
    elif kind == "cut":
        c = VideoCut.objects.filter(pk=pk, script__store=store).select_related("script__product").first()
        if c:
            path, title = _field_path(c.video), f"{c.script.product.name} — برشِ {c.format}"
    elif kind == "upload":
        u = UploadedVideo.objects.filter(pk=pk, store=store).first()
        if u:
            path = _field_path(u.edited if extra == "edited" else u.video)
            title = (u.title or f"آپلود #{u.pk}") + (" — تدوین‌شده" if extra == "edited" else "")
            kind = "edited" if extra == "edited" else "upload"
    elif kind == "up3d":
        try:
            from apps.up3d.models import Job as Up3dJob
        except Exception:  # noqa: BLE001
            Up3dJob = None
        j = Up3dJob.objects.filter(pk=pk).select_related("project").first() if Up3dJob else None
        if j and (getattr(user, "is_staff", False) or (j.project and j.project.owner_id == user.id)):
            rel = (j.files or {}).get("final.mp4")
            if rel:
                p = Path(settings.UP3D_DATA_DIR) / rel
                path = p if p.is_file() else None
            title = f"{j.project.title if j.project else 'سه‌بعدی'} — رندرِ #{j.pk}"
    elif kind == "regen":
        v = RegenVersion.objects.filter(pk=pk, session__store=store).select_related("session").first()
        if v and v.files.get("result"):
            p = abs_path(v.files["result"])
            path, title = (p if p.is_file() else None), f"{v.session.title} — نسخهٔ {v.number}"
    if path is None:
        raise RegenError("این ویدیو پیدا نشد یا فایلش روی سرور نیست.")
    return title, kind, path


# ───────────────────────────── جلسه

def _link_or_copy(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        dst.unlink()
    try:
        os.link(src, dst)        # جای اضافه نمی‌گیرد و اگر منبع بعداً عوض شود، این کپی همان می‌ماند
    except OSError:
        shutil.copy2(src, dst)


def create_session(store, user, *, ref: str = "", upload=None, title: str = "") -> RegenSession:
    if upload is not None:
        name = str(getattr(upload, "name", "video.mp4"))
        if not name.lower().endswith(ALLOWED_SUFFIXES):
            raise RegenError("فرمت‌های قابلِ قبول: " + "، ".join(ALLOWED_SUFFIXES))
        if upload.size > MAX_UPLOAD_MB * 1024 * 1024:
            raise RegenError(f"حداکثر اندازه {MAX_UPLOAD_MB} مگابایت است.")
        session = RegenSession.objects.create(store=store, created_by=user, title=(title or name)[:200],
                                              source_kind="file")
        dst = abs_path(session.dir_rel) / ("original" + Path(name).suffix.lower())
        dst.parent.mkdir(parents=True, exist_ok=True)
        with open(dst, "wb") as fh:
            for chunk in upload.chunks():
                fh.write(chunk)
    else:
        src_title, kind, src = resolve_source(store, user, ref)
        existing = (RegenSession.objects.filter(store=store, source_ref=ref, state__in=["PREPARING", "READY"])
                    .order_by("-created_at").first())
        if existing and abs_path(existing.original or "x").is_file() and existing.info.get("path_size") in (
                None, src.stat().st_size):
            return existing        # همان ویدیو، همان جلسه: نسخه‌های قبلی سرِ جایشان
        session = RegenSession.objects.create(store=store, created_by=user, title=(title or src_title)[:200],
                                              source_kind=kind, source_ref=ref)
        dst = abs_path(session.dir_rel) / ("original" + (src.suffix.lower() or ".mp4"))
        _link_or_copy(src, dst)
    session.original = str(dst.relative_to(media_root())).replace("\\", "/")
    session.save(update_fields=["original", "updated_at"])
    return session


def prepare_session(session: RegenSession) -> RegenSession:
    try:
        path = abs_path(session.original)
        info = media.probe(path)
        if info["n_frames"] < 3:
            raise RegenError("ویدیو کمتر از ۳ فریم دارد.")
        media.save_index(info, abs_path(session.dir_rel) / "index.json")
        sprite, frames = media.filmstrip(path, info, count=min(30, info["n_frames"]))
        strip = abs_path(session.dir_rel) / "filmstrip.jpg"
        strip.write_bytes(sprite)
        session.info = media.summary(info)
        session.filmstrip = {"path": str(strip.relative_to(media_root())).replace("\\", "/"), "frames": frames}
        session.state = RegenSession.State.READY
        session.error = ""
    except (RegenError, media.MediaError, OSError, ValueError) as exc:
        logger.warning("regen: session %s could not be prepared: %s", session.pk, exc)
        session.state = RegenSession.State.FAILED
        session.error = str(exc)[:2000]
    session.save()
    return session


def base_of(session: RegenSession, version: RegenVersion | None = None) -> tuple[Path, dict]:
    """(فایل، probe با فهرستِ pts) ِ ویدیوی پایهٔ یک نسخه (یا جلسه)."""
    if version is not None and version.base_id:
        base = version.base
        return abs_path(base.files["result"]), media.load_index(base.stats["result_info"],
                                                                abs_path(base.dir_rel) / "index.json")
    return abs_path(session.original), media.load_index(session.info, abs_path(session.dir_rel) / "index.json")


def current_base(session: RegenSession) -> tuple[RegenVersion | None, Path, dict]:
    cur = session.current
    if cur and cur.files.get("result") and abs_path(cur.files["result"]).is_file():
        return cur, abs_path(cur.files["result"]), media.load_index(cur.stats["result_info"],
                                                                    abs_path(cur.dir_rel) / "index.json")
    path, info = base_of(session)
    return None, path, info


# ───────────────────────────── موتورها و تخمینِ زمان

def _node_models(node) -> dict:
    caps = node.capabilities or {}
    m = caps.get("comfy_models") or {}
    return {"unet": m.get("unet"), "loras": m.get("loras"), "nodes": caps.get("comfy_nodes")}


def engines_status() -> list[dict]:
    """کدام موتور روی کدام گرهٔ آنلاین آماده است (از گزارشِ خودِ گره: نودهای ComfyUI و فهرستِ مدل‌ها)."""
    from apps.compute import services as compute

    nodes = compute.online_nodes("comfyui")
    out = []
    for key, spec in planmod.ENGINES.items():
        ready, missing, on = None, [], []
        for n in nodes:
            m = _node_models(n)
            ok = True
            if isinstance(m["nodes"], list) and m["nodes"]:
                if spec["node"] not in m["nodes"]:
                    ok = False
                    missing.append(f"نودِ {spec['node']} (ComfyUI را به‌روز کنید)")
            if isinstance(m["unet"], list) and len(m["unet"]) < 60:
                base = {str(x).replace("\\", "/").rsplit("/", 1)[-1] for x in m["unet"]}
                lack = [f for f in spec["files"]["unet"] if f not in base]
                if lack:
                    ok = False
                    missing += lack
            if ok:
                on.append(n.name)
        if nodes:
            ready = bool(on)
        out.append({"key": key, "label": spec["label"], "short": spec["short"], "license": spec["license"],
                    "qualities": list(spec["qualities"]), "ready": ready, "nodes": on,
                    "missing": sorted(set(missing))[:6], "sec_per_frame": learned_rate(key)})
    return out


def learned_rate(engine: str, quality: str | None = None) -> dict:
    """ثانیه بر فریم از نسخه‌های واقعیِ گذشته (میانهٔ ۵ تای آخر)؛ نبود ⇐ پیش‌فرض‌های plan.ENGINES."""
    spec = planmod.ENGINES[engine]
    out = {}
    for q in spec["qualities"]:
        if quality and q != quality:
            continue
        rates = []
        for v in (RegenVersion.objects.filter(engine=engine, quality=q, state=RegenVersion.State.READY)
                  .order_by("-created_at")[:5]):
            secs, frames = (v.stats or {}).get("gen_seconds"), (v.plan or {}).get("frames_total")
            chunks = len((v.plan or {}).get("chunks") or []) or 1
            if secs and frames:
                rates.append(max(0.2, (secs - spec["overhead"] * chunks) / frames))
        out[q] = round(statistics.median(rates), 2) if rates else spec["sec_per_frame"][q]
    return out


def estimate(plan: dict, info: dict) -> dict:
    spec = planmod.ENGINES[plan["engine"]]
    rate = learned_rate(plan["engine"], plan["quality"])[plan["quality"]]
    gen = rate * plan["frames_total"] + spec["overhead"] * len(plan["chunks"])
    smart = not asm.smart_possible(info)
    mpf = (plan["count"] if smart else info["n_frames"]) * info["width"] * info["height"] / 1e6
    post = 20 + plan["count"] * 0.25 + mpf * (0.02 if smart else 0.05)
    return {"generate_seconds": round(gen), "stitch_seconds": round(post), "total_seconds": round(gen + post),
            "smart_splice": smart, "smart_reason": asm.smart_possible(info)}


def plan_summary(plan: dict) -> dict:
    keys = ("start", "end", "count", "before", "after", "has_start", "has_end", "span", "fps", "model_fps",
            "effective_fps", "speed", "G", "context", "gen_size", "blend", "frames_total", "engine", "quality")
    out = {k: plan[k] for k in keys if k in plan}
    out["chunks"] = [{"length": c["length"]} for c in plan["chunks"]]
    return out


# ───────────────────────────── پرامپت

PROMPT_SYSTEM = (
    "You write prompts for an image-to-video model (Wan 2.2) that regenerates a short gap inside an existing "
    "video shot. The model receives the last frame before the gap and the first frame after it and must move "
    "naturally from one to the other. Turn the user's request (often in Persian) into ONE English prompt of "
    "40-90 words: describe the subject and exactly what happens during the gap, keep the same subject identity, "
    "setting, lighting, colours and camera of the surrounding shot, smooth natural continuous motion, no cuts, "
    "no text. Never mention frames, gaps or editing. Answer as JSON: {\"prompt\": \"...\"}"
)
QUALITY_TAIL = ("smooth natural continuous motion, same scene, same lighting and camera as the surrounding shot, "
                "consistent identity, photorealistic, no cuts")


def model_prompt(store, text: str) -> tuple[str, str]:
    """(پرامپتِ انگلیسیِ مدل، از کجا آمد). متنِ انگلیسی بی‌تغییر؛ فارسی با همان مدلِ متنیِ سامانه."""
    text = (text or "").strip()
    if not text:
        return "the same shot continues naturally, " + QUALITY_TAIL, "default"
    if not re.search(r"[؀-ۿ]", text):
        return f"{text.rstrip('. ')}. {QUALITY_TAIL}", "user"
    try:
        from services.ai.gateway import text_provider
        from services.ai.router import TASK_REASONING, models_for

        provider = text_provider(store)
        models = models_for(TASK_REASONING)
        data = provider.generate_json(models[0], f"User request:\n{text}", system=PROMPT_SYSTEM, timeout=120)
        out = str((data or {}).get("prompt") or "").strip() if isinstance(data, dict) else ""
        if len(out) > 15 and not re.search(r"[؀-ۿ]", out):
            return out[:1200], "ai"
    except Exception as exc:  # noqa: BLE001 — مدلِ متنی در دسترس نیست ⇐ همان متن (umT5 چندزبانه است)
        logger.info("regen: prompt translation unavailable (%s)", exc)
    return f"{text}. {QUALITY_TAIL}", "fallback"


# ───────────────────────────── نسخه

def _models_on_nodes() -> dict:
    """فهرستِ مدل‌های ComfyUI ِ گره (اول گره‌های آنلاین، وگرنه آخرین گزارشِ گره‌ای که خاموش است — کار تا روشن
    شدنش در صف می‌ماند و همان گره آن را می‌گیرد). نام‌ها با زیرپوشه‌ی واقعی روی گره در گراف می‌نشینند."""
    from apps.compute import services as compute
    from apps.compute.models import ComputeNode

    nodes = list(compute.online_nodes("comfyui")) + list(
        ComputeNode.objects.filter(enabled=True, last_seen__isnull=False).order_by("-last_seen"))
    for n in nodes:
        m = (n.capabilities or {}).get("comfy_models") or {}
        if m:
            return {"unet": m.get("unet"), "loras": m.get("loras")}
    return {}


def create_version(session: RegenSession, user, data: dict) -> RegenVersion:
    from apps.billing import services as billing
    from apps.billing.models import Usage

    if session.state != RegenSession.State.READY:
        raise RegenError("ویدیو هنوز آماده نیست.")
    if session.versions.filter(state__in=RegenVersion.ACTIVE).exists():
        raise RegenError("یک نسخه همین حالا در حالِ ساخت است؛ تا تمام شود صبر کنید یا لغوش کنید.")
    base_version, _path, info = current_base(session)
    try:
        start, end = int(data.get("start")), int(data.get("end"))
    except (TypeError, ValueError):
        raise RegenError("شروع و پایانِ بازه (شمارهٔ فریم) لازم است.")
    engine = str(data.get("engine") or "wan22_flf")
    quality = str(data.get("quality") or "480p")
    context = 5 if int(data.get("context") or 1) >= 5 else 1
    blend = data.get("blend")
    blend = None if blend in (None, "", "auto") else max(0, min(8, int(blend)))
    try:
        plan = planmod.make_plan(info, start, end, engine=engine, quality=quality, context=context, blend=blend,
                                 max_seconds=max_seconds())
    except planmod.PlanError as exc:
        raise RegenError(str(exc))
    seed = data.get("seed")
    seed = int(seed) if str(seed or "").lstrip("-").isdigit() and int(seed) >= 0 else random.randint(1, 2 ** 31 - 1)
    seconds = max(1, int(math.ceil(plan["count"] / plan["fps"])))
    with transaction.atomic():
        number = (session.versions.order_by("-number").values_list("number", flat=True).first() or 0) + 1
        usage = None
        try:
            usage = billing.reserve(session.store, Usage.Metric.VIDEO_SECONDS, seconds,
                                    detail=f"regen s{session.pk} v{number}")
        except billing.QuotaExceeded as exc:
            raise RegenError(f"سهمیهٔ ثانیهٔ ویدیو کافی نیست ({exc}).")
        version = RegenVersion.objects.create(
            session=session, number=number, base=base_version, created_by=user, start_frame=start, end_frame=end,
            prompt=str(data.get("prompt") or "")[:4000], engine=engine, quality=plan["quality"], seed=seed,
            context=context, blend=blend, plan=plan_summary(plan), usage_id=getattr(usage, "pk", None),
            negative_prompt=planmod.NEGATIVE, message="در صف")
    return version


def _set(version: RegenVersion, **fields) -> None:
    for k, v in fields.items():
        setattr(version, k, v)
    version.save(update_fields=list(fields) + ["updated_at"])


def _release(version: RegenVersion, reason: str) -> None:
    if not version.usage_id:
        return
    from apps.billing import services as billing
    from apps.billing.models import Usage

    billing.release(Usage.objects.filter(pk=version.usage_id).first(), reason=reason)


def _commit(version: RegenVersion) -> None:
    if not version.usage_id:
        return
    from apps.billing import services as billing
    from apps.billing.models import Usage

    billing.commit(Usage.objects.filter(pk=version.usage_id).first())


def fail(version: RegenVersion, message: str) -> None:
    _set(version, state=RegenVersion.State.FAILED, error=message[:4000], message="ناموفق")
    _release(version, "failed")


def start_version(version: RegenVersion) -> RegenVersion:
    """آماده‌سازی (روی سرور): فریم‌های مرزی، پرامپت، گراف ⇐ کارِ comfy.graph در صفِ سرورهای پردازش."""
    from apps.compute import services as compute
    from services.comfyui.remote import node_name

    if version.state != RegenVersion.State.QUEUED:
        return version
    _set(version, state=RegenVersion.State.PREPARING, progress=0.02, message="برداشتنِ فریم‌های مرزی")
    session = version.session
    try:
        base_path, info = base_of(session, version)
        plan = planmod.make_plan(info, version.start_frame, version.end_frame, engine=version.engine,
                                 quality=version.quality, context=version.context, blend=version.blend,
                                 max_seconds=max_seconds() + 1)
        vdir = abs_path(version.dir_rel)
        tag = f"s{session.pk}v{version.number}_{version.seed % 100000}"
        s_names, e_names, files = stitch.model_inputs(plan, info, base_path, vdir / "inputs", tag)
        # بندانگشتیِ دو فریمِ مرزی برای پنل
        for key, idx in (("frame_before", plan["before"]), ("frame_after", plan["after"])):
            if 0 <= idx < info["n_frames"]:
                (vdir / f"{key}.jpg").write_bytes(media.jpeg(media.read_frame(base_path, info, idx), width=640))
                version.files[key] = f"{version.dir_rel}/{key}.jpg"
        _set(version, progress=0.05, message="نوشتنِ پرامپتِ مدل", files=version.files)
        prompt, source = model_prompt(session.store, version.prompt)
        models = _models_on_nodes()
        graph = planmod.build_graph(plan, prompt=prompt, negative=version.negative_prompt or planmod.NEGATIVE,
                                    seed=version.seed, start_names=s_names, end_names=e_names,
                                    prefix=f"nmregen/{tag}", models=models)
        timeout = int(900 + 1.5 * planmod.ENGINES[version.engine]["sec_per_frame"][plan["quality"]]
                      * plan["frames_total"] * 3)
        job = compute.enqueue("comfy.graph", {"graph": graph, "uploads": sorted(files)}, files, store=session.store,
                              origin="regen", node=node_name(getattr(settings, "COMFYUI_BASE_URL", "agent://any")),
                              timeout_s=timeout, require_online=False, priority=90)
        version.stats.update({"prompt_source": source, "sampler": plan.get("sampler"), "enqueued_at": timezone.now().isoformat()})
        _set(version, state=RegenVersion.State.GENERATING, compute_job=str(job.uid), model_prompt=prompt,
             plan=plan_summary(plan) | {"positions_n": len(plan["positions"])}, stats=version.stats, progress=0.08,
             message="در صفِ سرورِ پردازش")
    except (RegenError, planmod.PlanError, media.MediaError, OSError) as exc:
        fail(version, str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.exception("regen: start of version %s failed", version.pk)
        fail(version, f"خطای داخلی: {exc}")
    return version


def refresh(version: RegenVersion) -> bool:
    """وضعیتِ کارِ گره را به نسخه منتقل می‌کند. True = نوبتِ چسباندن است (و همین فراخوان آن را گرفت)."""
    from apps.compute import services as compute
    from apps.compute.models import ComputeJob

    if version.state != RegenVersion.State.GENERATING or not version.compute_job:
        return False
    job = ComputeJob.objects.filter(uid=version.compute_job).select_related("node").first()
    if job is None:
        fail(version, "کارِ سرورِ پردازش پیدا نشد.")
        return False
    if job.state == ComputeJob.State.COMPLETED:
        took = (job.finished_at - job.claimed_at).total_seconds() if (job.finished_at and job.claimed_at) else None
        won = RegenVersion.objects.filter(pk=version.pk, state=RegenVersion.State.GENERATING).update(
            state=RegenVersion.State.STITCHING, progress=0.8, message="چسباندن و وارسیِ درز", updated_at=timezone.now())
        if won:
            version.refresh_from_db()
            version.stats.update({"gen_seconds": took, "node": job.node.name if job.node else "",
                                  # همان درخواست (همان seed و پرامپت) قبلاً ساخته شده بود ⇐ کارِ قبلی دوباره استفاده شد
                                  "reused": bool(job.created_at < version.created_at)})
            _set(version, stats=version.stats)
        return bool(won)
    if job.state in (ComputeJob.State.FAILED, ComputeJob.State.CANCELLED):
        fail(version, "ساختِ تکه روی سرورِ پردازش ناموفق بود: " + (job.error or job.get_state_display())[:1500])
        return False
    online = bool(compute.online_nodes("comfyui"))
    if job.state == ComputeJob.State.QUEUED:
        msg = "در صفِ سرورِ پردازش" if online else "منتظرِ سرورِ پردازش — الان هیچ سرورِ پردازشی با ComfyUI آنلاین نیست"
        prog = 0.08
    else:
        msg = f"ساخت روی {job.node.name if job.node else 'سرورِ پردازش'}: {job.message or ''}".strip(": ")
        prog = 0.1 + 0.68 * float(job.progress or 0)
    if msg != version.message or abs(prog - version.progress) > 0.005:
        _set(version, message=msg[:300], progress=round(prog, 3))
    return False


def stitch_version(version: RegenVersion, on_progress=None) -> RegenVersion:
    """فریم‌های مدل ⇐ تکه ⇐ ویدیوی کامل ⇐ پیش‌نمایش‌ها ⇐ نمرهٔ درز."""
    from apps.compute import services as compute
    from apps.compute.models import ComputeJob

    if version.state != RegenVersion.State.STITCHING:
        return version
    session = version.session
    vdir = abs_path(version.dir_rel)
    work = vdir / "work"
    try:
        job = ComputeJob.objects.get(uid=version.compute_job)
        base_path, info = base_of(session, version)
        plan = planmod.make_plan(info, version.start_frame, version.end_frame, engine=version.engine,
                                 quality=version.quality, context=version.context, blend=version.blend,
                                 max_seconds=max_seconds() + 1)
        outs = compute.job_root(job) / "outputs"
        by_chunk: dict[int, list] = {}
        for p in outs.glob("*.png"):
            m = re.match(r"c(\d+)_\d+_?\.png$", p.name)
            if m:
                by_chunk.setdefault(int(m.group(1)), []).append(p)
        gen = stitch.GenFrames(stitch.gen_index_files(plan, by_chunk), plan)

        def tick(lo, hi, msg):
            def f(x):
                p = lo + (hi - lo) * x
                if p - version.progress >= 0.01 or x >= 1:
                    RegenVersion.objects.filter(pk=version.pk).update(progress=round(p, 3), message=msg)
                    version.progress = p
            return f

        work.mkdir(parents=True, exist_ok=True)
        piece = work / "piece.mkv"
        st = stitch.build_piece(plan, gen, info, base_path, piece, seed=version.seed,
                                on_progress=tick(0.8, 0.86, "تطبیقِ رنگ، زمان و جزئیاتِ تکه"))
        result = vdir / ("result" + asm.container_for(info))
        res = asm.assemble(base_path, info, piece, plan["start"], plan["end"], result, work,
                           on_progress=tick(0.86, 0.95, "چسباندنِ تکه در ویدیو"))
        RegenVersion.objects.filter(pk=version.pk).update(progress=0.95, message="وارسیِ درزها و پیش‌نمایش")
        out_info = media.probe(result)
        media.save_index(out_info, vdir / "index.json")
        sm = seams.measure(base_path, info, result, out_info, plan["start"], plan["end"])
        pad = int(round(PREVIEW_PAD_SECONDS * info["fps"]))
        lo, hi = max(0, plan["start"] - pad), min(info["n_frames"] - 1, plan["end"] + pad)
        media.encode_window(result, out_info, vdir / "after.mp4", lo, hi)
        media.encode_window(base_path, info, vdir / "before.mp4", lo, hi)
        media.encode_window(result, out_info, vdir / "piece.mp4", plan["start"], plan["end"])
        files = dict(version.files)
        for key, name in (("result", result.name), ("after", "after.mp4"), ("before", "before.mp4"),
                          ("piece", "piece.mp4")):
            files[key] = f"{version.dir_rel}/{name}"
        stats = dict(version.stats)
        stats.update({"stitch": st, "assemble": res, "result_info": media.summary(out_info),
                      "window": [lo, hi], "result_size": result.stat().st_size,
                      "warnings": warnings_for(info, res, sm)})
        _set(version, state=RegenVersion.State.READY, progress=1.0, message="آماده", files=files, seams=sm,
             stats=stats, error="")
        _commit(version)
        shutil.rmtree(work, ignore_errors=True)
        shutil.rmtree(vdir / "inputs", ignore_errors=True)
        _drop_model_frames(job)
        prune_results(session)
    except Exception as exc:  # noqa: BLE001 — هر خطا ⇐ نسخهٔ ناموفق، ویدیوی اصل دست‌نخورده
        logger.exception("regen: stitching version %s failed", version.pk)
        shutil.rmtree(work, ignore_errors=True)
        fail(version, f"چسباندن ناموفق بود: {exc}")
    return version


def warnings_for(info: dict, res: dict, sm: dict) -> list[str]:
    out = []
    if info.get("vfr"):
        out.append("نرخِ فریمِ منبع متغیر بود؛ خروجی با نرخِ ثابت ساخته شد (ممکن است صدا چند میلی‌ثانیه جابه‌جا شود).")
    if info.get("hdr"):
        out.append("ویدیوی HDR: تکهٔ تازه در ۸ بیت ساخته شده؛ رنگِ آن را با دقت نگاه کنید.")
    if res.get("method") == "full":
        out.append("کلِ ویدیو دوباره رمزگذاری شد (" + (res.get("smart_skipped") or "") + ").")
    if sm.get("verdict") == "visible":
        out.append("درز ممکن است دیده شود؛ با seed یا پرامپتِ دیگر، یا بازهٔ کمی بزرگ‌تر دوباره بسازید.")
    return out


def _drop_model_frames(job) -> None:
    """فریم‌های PNG ِ مدل بعد از چسباندن لازم نیستند (دیسکِ سرور کوچک است)."""
    from apps.compute import services as compute

    outs = compute.job_root(job) / "outputs"
    for p in outs.glob("*.png"):
        p.unlink(missing_ok=True)


def prune_results(session: RegenSession) -> None:
    ready = [v for v in session.versions.filter(state=RegenVersion.State.READY).order_by("-number")
             if v.files.get("result") and not v.accepted_at and v.pk != session.current_id]
    for v in ready[KEEP_RESULTS:]:
        p = abs_path(v.files["result"])
        p.unlink(missing_ok=True)
        files = dict(v.files)
        files.pop("result", None)
        v.files = files
        v.stats = dict(v.stats) | {"result_pruned": True}
        v.save(update_fields=["files", "stats", "updated_at"])


def accept(version: RegenVersion) -> RegenVersion:
    if version.state != RegenVersion.State.READY or not version.files.get("result"):
        raise RegenError("فقط نسخهٔ آماده (با ویدیوی کامل) قبول می‌شود.")
    version.accepted_at = timezone.now()
    version.discarded = False
    version.save(update_fields=["accepted_at", "discarded", "updated_at"])
    session = version.session
    session.current = version
    session.save(update_fields=["current", "updated_at"])
    return version


def discard(version: RegenVersion) -> RegenVersion:
    if version.active:
        cancel(version)
    session = version.session
    if session.current_id == version.pk:
        # پایه به نسخهٔ قبول‌شدهٔ قبلی برمی‌گردد (یا اصل)
        prev = (session.versions.filter(accepted_at__isnull=False, discarded=False).exclude(pk=version.pk)
                .order_by("-accepted_at").first())
        session.current = prev
        session.save(update_fields=["current", "updated_at"])
    for key in ("result", "after", "piece"):
        rel = version.files.get(key)
        if rel:
            abs_path(rel).unlink(missing_ok=True)
    version.files = {k: v for k, v in version.files.items() if k not in ("result", "after", "piece")}
    version.discarded = True
    version.accepted_at = None
    version.save(update_fields=["files", "discarded", "accepted_at", "updated_at"])
    return version


def cancel(version: RegenVersion) -> RegenVersion:
    from apps.compute import services as compute
    from apps.compute.models import ComputeJob

    if not version.active:
        return version
    job = ComputeJob.objects.filter(uid=version.compute_job).first() if version.compute_job else None
    if job is not None:
        compute.cancel(job)
    _set(version, state=RegenVersion.State.CANCELLED, message="لغو شد")
    _release(version, "cancelled")
    return version


def recover_stale(version: RegenVersion) -> bool:
    """کارِ چسباندنی که Celery ِ آن وسطِ کار رفت (ری‌استارت) دوباره راه می‌افتد؛ True = دوباره فرستاده شد."""
    if version.state == RegenVersion.State.STITCHING and version.updated_at < timezone.now() - timedelta(minutes=20):
        tries = int((version.stats or {}).get("stitch_retries") or 0)
        if tries >= 2:
            fail(version, "چسباندن چند بار نیمه‌کاره ماند.")
            return False
        version.stats = dict(version.stats) | {"stitch_retries": tries + 1}
        version.save(update_fields=["stats", "updated_at"])
        return True
    if version.state in (RegenVersion.State.QUEUED, RegenVersion.State.PREPARING) and \
            version.updated_at < timezone.now() - timedelta(minutes=15):
        fail(version, "آماده‌سازی نیمه‌کاره ماند؛ دوباره بسازید.")
    return False


def send_to_editor(version: RegenVersion):
    """نتیجهٔ قبول‌شده به فهرستِ ادیتورِ ویدیو (UploadedVideo) — با همان بررسیِ خودکاری که آپلود دارد."""
    from django.core.files import File

    from apps.content.models import UploadedVideo

    if not version.accepted_at or not version.files.get("result"):
        raise RegenError("اول نسخه را قبول کنید.")
    src = abs_path(version.files["result"])
    session = version.session
    upload = UploadedVideo(store=session.store, title=f"{session.title} — بازسازی‌شده (نسخهٔ {version.number})"[:200])
    with open(src, "rb") as fh:
        upload.video.save(f"regen_s{session.pk}_v{version.number}{src.suffix}", File(fh), save=True)
    try:
        from apps.content.tasks_editing import analyze_upload_task
        from apps.jobs.models import Job
        from apps.jobs.services import dispatch_job

        job = Job.objects.create(store=session.store, type=Job.Type.VIDEO_ANALYSIS, context={"upload_id": upload.pk})
        dispatch_job(job, analyze_upload_task, job.id, upload.pk)
    except Exception as exc:  # noqa: BLE001 — بررسیِ خودکار اختیاری است
        logger.info("regen: analysis of the editor copy was not started: %s", exc)
    version.stats = dict(version.stats) | {"editor_upload": upload.pk}
    version.save(update_fields=["stats", "updated_at"])
    return upload
