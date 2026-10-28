"""جلسه، برداشت (با آپلودِ تکه‌تکه و قابلِ ادامه) و خروجی‌ها."""
from __future__ import annotations

import logging
import os
import re
import shutil
from datetime import timedelta
from pathlib import Path

from django.core.files import File
from django.db.models import Max
from django.utils import timezone
from PIL import Image, ImageOps

from . import checks, media
from . import plan as planmod
from .models import ShootOutput, ShootSession, ShootTake

logger = logging.getLogger(__name__)

PHOTO_MAX_BYTES = 40 * 1024 * 1024
VIDEO_MAX_BYTES = 400 * 1024 * 1024
CHUNK_MAX_BYTES = 4 * 1024 * 1024
PHOTO_MAX_SIDE = 3000
THUMB_SIDE = 480
VIDEO_SUFFIXES = (".mp4", ".mov", ".webm", ".m4v", ".3gp", ".mkv")
_UPLOAD_ID = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
STALE_MINUTES = 30


class ShootError(Exception):
    def __init__(self, message: str, code: str = "shoot", status: int = 400, **extra):
        super().__init__(message)
        self.code, self.status, self.extra = code, status, extra


# ───────────────────────────── جلسه

def create_session(store, product, user, *, purpose: str, analyze: bool) -> ShootSession:
    purpose = purpose if purpose in ShootSession.Purpose.values else ShootSession.Purpose.AD
    plan = planmod.template_plan(product, purpose=purpose)
    plan["notes"] = ["الگوی آمادهٔ همین دسته؛ تحلیلِ هوش مصنوعی در راه است."] if analyze else \
        ["الگوی آمادهٔ همین دسته."]
    return ShootSession.objects.create(
        store=store, product=product, created_by=user, purpose=purpose, plan=plan, plan_source="template",
        state=ShootSession.State.ANALYZING if analyze else ShootSession.State.READY,
        message="در حالِ تحلیلِ محصول…" if analyze else "برنامه آماده است.")


def run_analysis(session: ShootSession) -> ShootSession:
    try:
        new_plan, source, notes = planmod.analyze(session.product)
    except Exception as exc:  # noqa: BLE001 — تحلیل هرگز جلسه را خراب نمی‌کند
        logger.exception("shoot: analysis of session %s failed", session.pk)
        new_plan, source, notes = session.plan, session.plan_source or "template", [f"تحلیل نشد: {exc}"]
    session.refresh_from_db()
    if session.plan_source == "edited" or session.takes.exists():
        # کاربر شروع کرده یا برنامه را دستی عوض کرده: کلیدهای برداشت‌ها نباید زیرِ پایش عوض شوند
        session.plan = dict(session.plan) | {"notes": notes + ["چون کار را شروع کرده بودی، برنامه عوض نشد."],
                                             "suggested": new_plan}
        session.message = "تحلیل آماده شد (برنامهٔ فعلی نگه داشته شد)."
    else:
        new_plan["notes"] = notes
        session.plan, session.plan_source = new_plan, source
        session.message = notes[0] if notes else "برنامه آماده است."
    session.state = ShootSession.State.READY
    session.save(update_fields=["plan", "plan_source", "state", "message", "updated_at"])
    return session


def save_plan(session: ShootSession, raw) -> list[str]:
    plan, problems = planmod.validate_plan(raw, session.product, fallback_category=session.plan.get("category"))
    plan["notes"] = ["برنامه دستی ویرایش شد."] + problems
    session.plan, session.plan_source = plan, "edited"
    session.message = "برنامه ذخیره شد."
    session.save(update_fields=["plan", "plan_source", "message", "updated_at"])
    return problems


def find_shot(plan: dict, key: str) -> dict | None:
    for item in (plan.get("photos") or []) + (plan.get("video") or []):
        if item.get("key") == key:
            return item
    return None


def delete_session(session: ShootSession) -> None:
    shutil.rmtree(media.abs_path(session.dir_rel), ignore_errors=True)
    session.delete()


# ───────────────────────────── آپلودِ تکه‌تکه

def _part(session: ShootSession, upload_id: str) -> Path:
    if not _UPLOAD_ID.match(upload_id or ""):
        raise ShootError("شناسهٔ آپلود درست نیست.", "bad_upload")
    return media.abs_path(f"{session.dir_rel}/parts/{upload_id}.part")


def received(session: ShootSession, upload_id: str) -> int:
    p = _part(session, upload_id)
    return p.stat().st_size if p.is_file() else 0


def receive_chunk(session: ShootSession, *, upload_id: str, offset: int, total: int, kind: str, chunk) -> int:
    """یک تکه را به آخرِ فایل می‌چسباند و اندازهٔ تازه را برمی‌گرداند.

    تکهٔ تکراری یا جاافتاده ⇐ ۴۰۹ با «چقدر رسیده» تا گوشی از همان‌جا ادامه دهد (اینترنتِ قطع‌ووصل)."""
    limit = VIDEO_MAX_BYTES if kind == ShootTake.Kind.VIDEO else PHOTO_MAX_BYTES
    if total <= 0 or total > limit:
        raise ShootError(f"حجمِ فایل مجاز نیست (حداکثر {limit // (1024 * 1024)} مگابایت).", "too_big")
    if chunk is None or chunk.size <= 0 or chunk.size > CHUNK_MAX_BYTES:
        raise ShootError("تکهٔ آپلود خالی یا بزرگ است.", "bad_chunk")
    p = _part(session, upload_id)
    have = p.stat().st_size if p.is_file() else 0
    if offset != have:
        raise ShootError("این تکه با چیزی که رسیده جور نیست.", "offset", 409, received=have)
    if offset + chunk.size > total:
        raise ShootError("تکه از اندازهٔ کلِ فایل بیرون می‌زند.", "bad_chunk")
    if offset == 0:
        if kind == ShootTake.Kind.VIDEO and media.disk_free() < media.MIN_FREE_BYTES + total:
            raise ShootError("جای خالیِ سرور برای ویدیو کم است؛ جلسه‌های قدیمی را پاک کنید یا ویدیوی کوتاه‌تر بگیرید.",
                             "disk_full", 507)
        if media.dir_size(media.abs_path(session.dir_rel)) + total > media.SESSION_MAX_BYTES:
            raise ShootError("فضای این جلسه پر شده (۱٫۵ گیگ)؛ برداشت‌های ردشده را پاک کنید.", "session_full", 507)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "ab") as fh:
        for piece in chunk.chunks():
            fh.write(piece)
    return p.stat().st_size


def _next_name(session: ShootSession, shot: str, suffix: str) -> str:
    n = session.takes.filter(shot=shot).count() + 1
    base = f"{session.dir_rel}/takes/{shot}_{n}"
    while media.abs_path(base + suffix).exists():
        n += 1
        base = f"{session.dir_rel}/takes/{shot}_{n}"
    return base


def finalize(session: ShootSession, *, upload_id: str, shot_key: str, kind: str, name: str, mode: str,
             vision: bool = True) -> ShootTake:
    shot = find_shot(session.plan, shot_key)
    if shot is None or shot.get("kind") != kind:
        raise ShootError("این زاویه/نما در برنامه نیست؛ صفحه را تازه کنید.", "no_shot")
    part = _part(session, upload_id)
    if not part.is_file():
        raise ShootError("فایلِ آپلود پیدا نشد.", "no_upload")
    try:
        if kind == ShootTake.Kind.PHOTO:
            return _finalize_photo(session, part, shot, mode, vision)
        return _finalize_video(session, part, shot, mode, name)
    finally:
        part.unlink(missing_ok=True)


def _finalize_photo(session, part: Path, shot: dict, mode: str, vision: bool) -> ShootTake:
    try:
        img = Image.open(part)
        img.load()
        img = ImageOps.exif_transpose(img).convert("RGB")
    except Exception as exc:  # noqa: BLE001
        raise ShootError("این عکس خوانده نشد؛ در تنظیماتِ دوربین قالبِ JPEG («سازگارترین») را انتخاب کنید.",
                         "bad_image") from exc
    if max(img.size) > PHOTO_MAX_SIDE:
        img.thumbnail((PHOTO_MAX_SIDE, PHOTO_MAX_SIDE), Image.Resampling.LANCZOS)
    base = _next_name(session, shot["key"], ".jpg")
    out = media.abs_path(base + ".jpg")
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, "JPEG", quality=92, optimize=True)      # بی EXIF (مکانِ عکس نشت نمی‌کند)
    thumb = img.copy()
    thumb.thumbnail((THUMB_SIDE, THUMB_SIDE))
    thumb.save(media.abs_path(base + "_t.jpg"), "JPEG", quality=82)
    metrics = checks.photo_metrics(img)
    result = checks.judge_photo(metrics, shot.get("check"))
    vis = None
    if vision and result["ok"]:
        vis = checks.vision_check(session.store, img, product_name=session.product.name, shot=shot)
        result = checks.merge_vision(result, vis)
    return ShootTake.objects.create(
        session=session, shot=shot["key"], kind=ShootTake.Kind.PHOTO, file=base + ".jpg", thumb=base + "_t.jpg",
        mime="image/jpeg", size=out.stat().st_size, width=img.width, height=img.height, mode=mode[:12],
        checks={"problems": checks.clean_problems(result["problems"]), "metrics": metrics, "vision": vis,
                "summary": checks.summary(result), "where": "سرورِ سایت" + (" + هوش مصنوعیِ بینایی" if vis else "")},
        ok=result["ok"], accepted=result["ok"], score=result["score"])


def _finalize_video(session, part: Path, shot: dict, mode: str, name: str) -> ShootTake:
    from services.video.ffmpeg import VideoProcessingError

    suffix = Path(name or "").suffix.lower()
    if suffix not in VIDEO_SUFFIXES:
        suffix = ".mp4"
    base = _next_name(session, shot["key"], suffix)
    out = media.abs_path(base + suffix)
    out.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(part), out)
    work = media.abs_path(f"{session.dir_rel}/work/check")
    try:
        metrics = checks.video_metrics(out, work)
        mid = max(0.0, min(float(metrics["duration"] or 0) / 2, 3.0))
        media.run_ff(["-y", "-ss", f"{mid:.2f}", "-i", out, "-frames:v", "1", "-vf", "scale=480:-2",
                      media.abs_path(base + "_t.jpg")], timeout=120)
        media.run_ff(["-y", "-i", out, "-t", "20", "-vf", "scale=-2:480,format=yuv420p", "-c:v", "libx264",
                      "-preset", "ultrafast", "-crf", "30", "-an", "-movflags", "+faststart",
                      media.abs_path(base + "_p.mp4")], timeout=300)
    except VideoProcessingError as exc:
        out.unlink(missing_ok=True)
        raise ShootError("این ویدیو خوانده نشد: " + str(exc)[:200], "bad_video") from exc
    result = checks.judge_video(metrics, shot.get("check"))
    return ShootTake.objects.create(
        session=session, shot=shot["key"], kind=ShootTake.Kind.VIDEO, file=base + suffix, thumb=base + "_t.jpg",
        preview=base + "_p.mp4", mime={".webm": "video/webm", ".mov": "video/quicktime"}.get(suffix, "video/mp4"),
        size=out.stat().st_size, width=metrics.get("width") or 0, height=metrics.get("height") or 0,
        duration=float(metrics.get("duration") or 0), mode=mode[:12],
        checks={"problems": checks.clean_problems(result["problems"]), "metrics": metrics,
                "summary": checks.summary(result), "where": "سرورِ سایت (ffmpeg)"},
        ok=result["ok"], accepted=result["ok"], score=result["score"])


def delete_take(take: ShootTake) -> None:
    for rel in (take.file, take.thumb, take.preview):
        if rel:
            media.abs_path(rel).unlink(missing_ok=True)
    take.delete()


def best_take(session: ShootSession, shot_key: str) -> ShootTake | None:
    return session.takes.filter(shot=shot_key, accepted=True).order_by("-score", "-created_at").first()


# ───────────────────────────── ذخیره در محصول

def save_photos_to_product(session: ShootSession) -> list[int]:
    """بهترین عکسِ پذیرفتهٔ هر زاویه، به ترتیبِ برنامه ⇐ عکس‌های محصول. دوباره زدن تکراری نمی‌سازد."""
    from apps.products.models import ProductImage

    product = session.product
    order = (product.images.aggregate(m=Max("order"))["m"] or 0) + 1
    has_main = product.images.filter(is_main=True).exists()
    made = []
    for shot in session.plan.get("photos") or []:
        take = best_take(session, shot["key"])
        if take is None:
            continue
        if take.saved_image_id and ProductImage.objects.filter(pk=take.saved_image_id, product=product).exists():
            continue
        path = media.abs_path(take.file)
        if not path.is_file():
            continue
        with open(path, "rb") as fh:
            image = product.images.create(
                image=File(fh, name=f"shoot_{session.pk}_{shot.get('angle', shot['key'])}.jpg"),
                is_main=not has_main and not made, alt_text=f"{product.name} — {shot.get('title', '')}"[:200],
                order=order)
        order += 1
        take.saved_image_id = image.pk
        take.save(update_fields=["saved_image_id", "updated_at"])
        made.append(image.pk)
    return made


# ───────────────────────────── خروجی‌ها

def new_output(session: ShootSession, *, kind: str, aspect: str, template: str, options: dict) -> ShootOutput:
    version = (session.outputs.filter(kind=kind).aggregate(m=Max("version"))["m"] or 0) + 1
    return ShootOutput.objects.create(session=session, kind=kind, aspect=aspect, template=template[:20],
                                      options=options, version=version, message="در صف")


def set_output(output: ShootOutput, **fields) -> None:
    for k, v in fields.items():
        setattr(output, k, v)
    output.save(update_fields=list(fields) + ["updated_at"])


def delete_output(output: ShootOutput) -> None:
    for rel in (output.file, output.thumb):
        if rel:
            media.abs_path(rel).unlink(missing_ok=True)
    output.delete()


def _ready_file(output: ShootOutput) -> Path:
    if output.state != ShootOutput.State.READY or not output.file:
        raise ShootError("این خروجی هنوز آماده نیست.", "not_ready")
    p = media.abs_path(output.file)
    if not p.is_file():
        raise ShootError("فایلِ خروجی پیدا نشد.", "missing")
    return p


def output_to_product(output: ShootOutput) -> dict:
    """پوستر ⇐ عکسِ محصول؛ ویدیو ⇐ «ویدیوهای آپلودشده»ِ همان محصول (در ادیتورِ ویدیو)."""
    path = _ready_file(output)
    session = output.session
    product = session.product
    saved = dict(output.saved or {})
    if output.kind == ShootOutput.Kind.POSTER:
        with open(path, "rb") as fh:
            image = product.images.create(
                image=File(fh, name=f"poster_{session.pk}_{output.version}_{output.aspect.replace(':', 'x')}.jpg"),
                alt_text=f"پوسترِ {product.name}"[:200],
                order=(product.images.aggregate(m=Max("order"))["m"] or 0) + 1)
        saved["product_images"] = (saved.get("product_images") or []) + [image.pk]
        set_output(output, saved=saved)
        return {"product_image": image.pk}
    return output_to_editor(output)


def output_to_content(output: ShootOutput) -> dict:
    """پوستر ⇐ «تصویرِ ساخته‌شده» (پوسترِ تبلیغاتی: در استودیو، کپشن و کمپین انتخاب‌شدنی)؛ ویدیو ⇐ ادیتورِ ویدیو."""
    if output.kind == ShootOutput.Kind.VIDEO:
        return output_to_editor(output)
    from apps.content.models import GeneratedImage

    path = _ready_file(output)
    session = output.session
    with open(path, "rb") as fh:
        gi = GeneratedImage.objects.create(
            store=session.store, product=session.product, kind=GeneratedImage.Kind.POSTER,
            concept=f"فیلم‌برداریِ هدایت‌شده: پوستر {output.aspect} — نسخهٔ {output.version}"[:500],
            style=output.template, workflow_version="guided-shoot",
            image=File(fh, name=f"shoot_poster_{session.pk}_{output.pk}.jpg"),
            metadata={"source": "guided_shoot", "session": session.pk, "output": output.pk,
                      "aspect": output.aspect, "template": output.template})
    saved = dict(output.saved or {})
    saved["generated_images"] = (saved.get("generated_images") or []) + [gi.pk]
    set_output(output, saved=saved)
    return {"generated_image": gi.pk}


def output_to_editor(output: ShootOutput) -> dict:
    from apps.content.models import UploadedVideo
    from apps.content.tasks_editing import analyze_upload_task
    from apps.jobs.models import Job
    from apps.jobs.services import dispatch_job

    path = _ready_file(output)
    session = output.session
    saved = dict(output.saved or {})
    if saved.get("uploaded_videos"):
        return {"uploaded_video": saved["uploaded_videos"][-1], "existing": True}
    with open(path, "rb") as fh:
        upload = UploadedVideo.objects.create(
            store=session.store, product=session.product,
            title=f"تبلیغِ {session.product.name} ({output.aspect}، نسخهٔ {output.version})"[:200],
            video=File(fh, name=f"shoot_{session.pk}_{output.pk}.mp4"))
    job = Job.objects.create(store=session.store, type=Job.Type.VIDEO_ANALYSIS, context={"upload_id": upload.pk})
    dispatch_job(job, analyze_upload_task, job.id, upload.pk)
    saved["uploaded_videos"] = [upload.pk]
    set_output(output, saved=saved)
    return {"uploaded_video": upload.pk}


# ───────────────────────────── برای پنل

def take_dict(t: ShootTake) -> dict:
    return {
        "id": t.pk, "shot": t.shot, "kind": t.kind, "url": media.url(t.file), "thumb": media.url(t.thumb),
        "preview": media.url(t.preview), "ok": t.ok, "accepted": t.accepted, "score": t.score,
        "duration": t.duration, "width": t.width, "height": t.height, "mode": t.mode, "size": t.size,
        "problems": (t.checks or {}).get("problems") or [], "summary": (t.checks or {}).get("summary") or "",
        "vision": (t.checks or {}).get("vision"), "where": (t.checks or {}).get("where") or "",
        "saved_image_id": t.saved_image_id, "created_at": t.created_at,
    }


def _expire_stale(output: ShootOutput) -> None:
    if output.state in (ShootOutput.State.QUEUED, ShootOutput.State.RUNNING) and \
            timezone.now() - output.updated_at > timedelta(minutes=STALE_MINUTES):
        set_output(output, state=ShootOutput.State.FAILED, message="ناموفق",
                   error="کار بیش از ۳۰ دقیقه بی‌خبر ماند (احتمالاً سرویس بازنشانی شد). دوباره بسازید.")


def output_dict(o: ShootOutput) -> dict:
    _expire_stale(o)
    return {
        "id": o.pk, "kind": o.kind, "aspect": o.aspect, "version": o.version, "template": o.template,
        "options": o.options, "state": o.state, "progress": o.progress, "message": o.message, "error": o.error,
        "url": media.url(o.file), "thumb": media.url(o.thumb), "stats": o.stats, "saved": o.saved,
        "created_at": o.created_at,
    }


def _product_thumb(product) -> str | None:
    first = product.images.first()
    return first.image.url if first else None


def session_dict(s: ShootSession, *, full: bool = True) -> dict:
    out = {
        "id": s.pk, "purpose": s.purpose, "state": s.state, "plan_source": s.plan_source, "message": s.message,
        "error": s.error, "created_at": s.created_at, "updated_at": s.updated_at,
        "product": {"id": s.product_id, "name": s.product.name, "price": str(s.product.price),
                    "thumb": _product_thumb(s.product)},
    }
    if not full:
        takes = list(s.takes.all())
        out["counts"] = {"takes": len(takes), "accepted_shots": len({t.shot for t in takes if t.accepted}),
                         "shots": len(s.plan.get("photos") or []) + len(s.plan.get("video") or []),
                         "outputs": s.outputs.filter(state=ShootOutput.State.READY).count()}
        return out
    out.update({
        "plan": s.plan, "voice": s.voice or {},
        "takes": [take_dict(t) for t in s.takes.all()],
        "outputs": [output_dict(o) for o in s.outputs.all()],
    })
    return out


def media_free_note() -> str:
    free = media.disk_free()
    return f"{free / 1e9:.1f}".replace(".", "٫") + " گیگ جای خالی"


def safe_remove(path: Path) -> None:
    try:
        os.remove(path)
    except OSError:
        pass
