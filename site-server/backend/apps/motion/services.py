"""منطقِ «استودیوی موشن»: ساختنِ رندر، فرستادن به گرهٔ پردازش یا رندرِ سایت، پیگیری و ثبتِ ویدیو در رسانهٔ فروشگاه."""
from __future__ import annotations

import logging
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from django.conf import settings
from django.utils import timezone

from apps.compute import services as CS
from apps.compute.models import ComputeJob, ComputeNode

from . import assets, catalog, runner, safety, specs
from .models import MotionRender

logger = logging.getLogger(__name__)

KIND = "motion.render"
CAPABILITY = "motion_render"
NODE_PRIORITY = 80
NODE_TIMEOUT_S = 3600


class MotionError(ValueError):
    """خطای قابلِ‌نمایش به کاربر (فارسی)."""


# ───────────────────────────────────────────── node / site status

def node_status() -> dict:
    nodes = list(ComputeNode.objects.filter(enabled=True))
    capable = [n for n in nodes if n.has(CAPABILITY)]
    online_capable = [n for n in capable if n.online]
    info: dict = {}
    for n in online_capable or capable:
        m = (n.capabilities or {}).get("motion")
        if isinstance(m, dict):
            info = m
            break
    if not nodes:
        state, message = "none", "هیچ سرورِ پردازشی ثبت نشده؛ رندر روی سایت انجام می‌شود (محدود)."
    elif online_capable:
        st = info.get("state")
        if st == "ready":
            state, message = "ready", "سرورِ پردازش آماده است."
        elif st == "installing":
            state, message = "installing", info.get("message") or "سرورِ پردازش در حالِ نصبِ ابزارِ موشن است…"
        elif st == "failed":
            state, message = "failed", "نصبِ ابزارِ موشن روی سرورِ پردازش ناموفق بود: " + str(info.get("message") or "")[:200]
        else:
            state, message = "checking", "سرورِ پردازش آنلاین است؛ ابزارِ موشن در حالِ بررسی است…"
    elif capable:
        state, message = "offline", "سرورِ پردازش خاموش است؛ رندر در صف می‌ماند تا روشن شود."
    else:
        state, message = "outdated", "سرورِ پردازش ثبت است ولی نسخه‌اش هنوز موشن را نمی‌شناسد؛ با روشن شدن و به‌روزرسانی، رندر در صف انجام می‌شود."
    return {
        "registered": len(nodes), "capable": len(capable), "online": len([n for n in nodes if n.online]),
        "capable_online": len(online_capable), "state": state, "message": message, "detail": info,
        "names": [n.name for n in nodes][:5],
    }


def choose_target(requested: str | None) -> str:
    """رندرِ نهایی منتظرِ گره می‌ماند؛ فقط اگر هیچ گره‌ای ثبت نیست (یا کاربر «رندر روی سایت» را زد) روی سایت می‌رود."""
    if requested == "site":
        return MotionRender.Target.SITE
    if not ComputeNode.objects.filter(enabled=True).exists():
        return MotionRender.Target.SITE
    return MotionRender.Target.NODE


# ───────────────────────────────────────────── building the job

def _slug(s: str) -> str:
    s = re.sub(r"[^\w؀-ۿ-]+", "-", s or "").strip("-")
    return (s or "motion")[:40]


def materialize(store, spec: dict) -> tuple[dict, dict[str, tuple[bytes, str]]]:
    """spec (با ref ها) ⇒ (spec با «asset:aN» و assets={aN: "@file:aN.ext"}, {aN: (بایت, پسوند)})."""
    refs = specs.asset_refs(spec)
    out = _deepcopy(spec)
    files: dict[str, tuple[bytes, str]] = {}
    names: dict[str, str] = {}
    for i, ref in enumerate(refs, 1):
        try:
            data, ext = assets.load(store, ref)
        except assets.AssetError as exc:
            raise MotionError(str(exc)) from exc
        key = f"a{i}"
        names[ref] = key
        files[key] = (data, ext)

    def sub(v):
        return f"asset:{names[v]}" if isinstance(v, str) and v in names else v

    if out.get("brand", {}).get("logo"):
        out["brand"]["logo"] = sub(out["brand"]["logo"])
    for sc in out.get("scenes", []):
        for k in ("image", "before_image", "after_image", "screenshot"):
            if sc.get(k):
                sc[k] = sub(sc[k])
    out["assets"] = {k: f"@file:{k}{files[k][1]}" for k in files}
    out.pop("total_s", None)
    return out, files


def _deepcopy(o):
    import json

    return json.loads(json.dumps(o))


def preview_payload(store, spec: dict) -> dict:
    """برای پیش‌نمایشِ زندهٔ پنل: spec با data: URI ِ تصویرها."""
    out = _deepcopy(spec)
    out["assets"] = {}
    mapping: dict[str, str] = {}
    for i, ref in enumerate(specs.asset_refs(spec), 1):
        try:
            mapping[ref] = f"a{i}"
            out["assets"][f"a{i}"] = assets.data_uri(store, ref)
        except assets.AssetError as exc:
            raise MotionError(str(exc)) from exc
    if out.get("brand", {}).get("logo") in mapping:
        out["brand"]["logo"] = f"asset:{mapping[out['brand']['logo']]}"
    for sc in out.get("scenes", []):
        for k in ("image", "before_image", "after_image", "screenshot"):
            if sc.get(k) in mapping:
                sc[k] = f"asset:{mapping[sc[k]]}"
    out.pop("total_s", None)
    return out


def build_job(render: MotionRender) -> tuple[dict, dict[str, tuple[bytes, str]]]:
    """(job.json بدونِ مسیرها, فایل‌های ورودی). render.mjs همین را می‌خواند."""
    opts = render.options or {}
    quality = str(opts.get("quality") or specs.DEFAULT_QUALITY)
    site = render.target == MotionRender.Target.SITE
    if render.mode == MotionRender.Mode.CODE:
        res = runner.compile_code(render.code)
        if not res.get("ok"):
            raise MotionError("کد کامپایل نشد: " + str(res.get("error")))
        wh = (int(opts.get("width") or 1080), int(opts.get("height") or 1920))
        job = {"composition": "User", "props": {}, "user_js": res["js"], "scale": runner.scale_for(wh, quality, site=site),
               "max_seconds": runner.SITE_MAX_SECONDS if site else specs.MAX_TOTAL_S_NODE}
        return job, {}
    spec = render.spec
    spec, files = materialize(render.store, spec)
    wh = specs.ASPECTS[spec["aspect"]]
    return {"composition": "Template", "props": {"spec": spec}, "scale": runner.scale_for(wh, quality, site=site),
            "max_seconds": runner.SITE_MAX_SECONDS if site else specs.MAX_TOTAL_S_NODE}, files


# ───────────────────────────────────────────── creating / starting

def create(store, user, *, mode: str, title: str = "", spec: dict | None = None, code: str = "", quality: str = "",
           target: str | None = None, fps: int | None = None, size: tuple[int, int] | None = None) -> MotionRender:
    target = choose_target(target)
    max_total = specs.MAX_TOTAL_S_SITE if target == MotionRender.Target.SITE else specs.MAX_TOTAL_S_NODE
    quality = quality if quality in specs.QUALITY else specs.DEFAULT_QUALITY
    opts = {"quality": quality}
    if mode == MotionRender.Mode.CODE:
        try:
            safety.scan(code)
        except safety.UnsafeCode as exc:
            raise MotionError(str(exc)) from exc
        row = MotionRender(store=store, user=user, mode=mode, title=(title or "ویدیوی کد")[:200], code=code, style="", aspect="", options=opts, target=target)
        if size:
            opts["width"], opts["height"] = size
    else:
        try:
            clean = specs.normalize_spec(spec or {}, max_total=max_total)
        except specs.SpecError as exc:
            raise MotionError(str(exc)) from exc
        row = MotionRender(store=store, user=user, mode=mode, title=(title or _default_title(clean))[:200], spec=clean,
                           style=clean["style"], aspect=clean["aspect"], options=opts, target=target)
    row.message = "در صف"
    row.save()
    return row


def _default_title(spec: dict) -> str:
    st = catalog.get(spec["style"]) or {}
    first = spec["scenes"][0]
    base = first.get("title") or first.get("name") or first.get("text") or st.get("name_fa", "")
    return f"{base} — {st.get('name_fa', '')}".strip(" —")[:120]


def start(render: MotionRender) -> MotionRender:
    """رندر را شروع می‌کند: روی صفِ پردازش (گره) یا Celery ِ سایت."""
    if render.target == MotionRender.Target.SITE:
        render.state = MotionRender.State.QUEUED
        render.message = "در صفِ رندرِ سایت"
        render.save(update_fields=["state", "message", "updated_at"])
        return render
    try:
        job_spec, files = build_job(render)
    except MotionError as exc:
        return fail(render, str(exc))
    tmp = Path(tempfile.mkdtemp(prefix="nm-motion-job-"))
    try:
        paths = {}
        for key, (data, ext) in files.items():
            p = tmp / f"{key}{ext}"
            p.write_bytes(data)
            paths[f"{key}{ext}"] = str(p)
        payload = {**job_spec, "title": render.title, "style": render.style, "mode": render.mode, "render_id": render.pk}
        job = CS.enqueue(KIND, payload, paths, store=render.store, origin="motion", priority=NODE_PRIORITY, timeout_s=NODE_TIMEOUT_S,
                         dedupe=False, require_online=False, lease_s=900, max_attempts=2, category="render")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    render.job_uid = str(job.uid)
    render.state = MotionRender.State.WAITING_NODE if not CS.online_nodes(CAPABILITY) else MotionRender.State.QUEUED
    render.message = job.message or "در صفِ سرورِ پردازش"
    render.save(update_fields=["job_uid", "state", "message", "updated_at"])
    return render


def switch_to_site(render: MotionRender) -> MotionRender:
    """«رندر روی سایت»: کارِ منتظرِ گره لغو و همان رندر روی سایت (با سقفِ سایت) انجام می‌شود."""
    if render.state not in MotionRender.ACTIVE:
        raise MotionError("این رندر دیگر فعال نیست.")
    if render.mode != MotionRender.Mode.CODE:
        try:
            specs.normalize_spec(render.spec, max_total=specs.MAX_TOTAL_S_SITE)
        except specs.SpecError as exc:
            raise MotionError("رندرِ سایت محدود است: " + str(exc)) from exc
    if render.job_uid:
        job = ComputeJob.objects.filter(uid=render.job_uid).first()
        if job and not job.final:
            CS.cancel(job, "به رندرِ سایت منتقل شد")
    render.target = MotionRender.Target.SITE
    render.job_uid = ""
    render.save(update_fields=["target", "job_uid", "updated_at"])         # start() below saves only state/message
    return start(render)


# ───────────────────────────────────────────── following a render

def fail(render: MotionRender, message: str) -> MotionRender:
    render.state = MotionRender.State.FAILED
    render.error = message[:2000]
    render.message = "ناموفق"
    render.finished_at = timezone.now()
    render.save()
    return render


def cancel(render: MotionRender) -> MotionRender:
    if render.state not in MotionRender.ACTIVE:
        return render
    if render.job_uid:
        job = ComputeJob.objects.filter(uid=render.job_uid).first()
        if job and not job.final:
            CS.cancel(job, "لغو توسطِ کاربر")
    render.state = MotionRender.State.CANCELLED
    render.message = "لغو شد"
    render.finished_at = timezone.now()
    render.save()
    return render


def refresh(render: MotionRender) -> bool:
    """وضعیتِ کارِ گره را به رندر می‌آورد. True = کار تمام شد (موفق یا ناموفق) و دیگر poll لازم نیست."""
    if render.state not in MotionRender.ACTIVE or render.target != MotionRender.Target.NODE or not render.job_uid:
        return render.state not in MotionRender.ACTIVE
    job = ComputeJob.objects.filter(uid=render.job_uid).first()
    if job is None:
        fail(render, "کارِ پردازش در صف پیدا نشد.")
        return True
    S = ComputeJob.State
    if job.state == S.COMPLETED:
        return finalize_from_job(render, job)
    if job.state in (S.FAILED, S.CANCELLED):
        if job.state == S.CANCELLED or render.state == MotionRender.State.CANCELLED:
            render.state = MotionRender.State.CANCELLED
            render.message = "لغو شد"
            render.finished_at = timezone.now()
            render.save()
        else:
            fail(render, job.error or "رندر روی سرورِ پردازش ناموفق بود.")
        return True
    if job.state == S.QUEUED:
        render.state = MotionRender.State.WAITING_NODE if not CS.online_nodes(CAPABILITY) else MotionRender.State.QUEUED
        render.message = job.message or "در صفِ سرورِ پردازش"
        render.progress = 0.0
    else:
        render.state = MotionRender.State.RENDERING
        render.message = job.message or "در حال رندر روی سرورِ پردازش"
        render.progress = max(render.progress, float(job.progress or 0))
    render.save(update_fields=["state", "message", "progress", "updated_at"])
    return False


def finalize_from_job(render: MotionRender, job: ComputeJob) -> bool:
    out = CS.output_path(job, "out.mp4")
    if not out.is_file() or out.stat().st_size < 1000:
        fail(render, "سرورِ پردازش کار را تمام‌شده گزارش کرد ولی ویدیو نرسید.")
        return True
    meta = (job.result or {}).get("meta") or {}
    try:
        finalize(render, out, render_s=float(job.run_s or meta.get("seconds") or 0))
    except Exception as exc:  # noqa: BLE001
        logger.exception("motion: finalize of render %s failed", render.pk)
        fail(render, f"ثبتِ ویدیو ناموفق بود: {exc}")
    return True


def _probe(path: Path) -> dict:
    from services.video import ffmpeg as ff

    try:
        v = ff.probe_video(path)
        return {"width": int(v.get("width") or 0), "height": int(v.get("height") or 0), "fps": float(v.get("fps") or 0), "duration": float(v.get("duration") or 0)}
    except Exception:  # noqa: BLE001
        return {"width": 0, "height": 0, "fps": 0, "duration": 0.0}


def _poster(src: Path, dest: Path, at: float) -> bool:
    try:
        from services.video.ffmpeg import FFMPEG
    except Exception:  # noqa: BLE001
        FFMPEG = shutil.which("ffmpeg") or "ffmpeg"
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run([FFMPEG, "-v", "error", "-y", "-ss", f"{max(0.0, at):.2f}", "-i", str(src), "-frames:v", "1", "-vf", "scale=540:-2", str(dest)],
                       check=True, timeout=60, capture_output=True)
        return dest.is_file()
    except (subprocess.SubprocessError, OSError):
        return False


def finalize(render: MotionRender, mp4: Path, *, render_s: float = 0.0) -> MotionRender:
    """ویدیوی تمام‌شده ⇒ رسانهٔ فروشگاه (UploadedVideo) + پوستر؛ رندر READY."""
    from apps.content.models import UploadedVideo
    from services.media import files as media

    store = render.store
    rel_dir = Path("generated") / "motion" / str(store.pk)
    base = f"{render.pk}-{_slug(render.title)}"
    dest = Path(settings.MEDIA_ROOT) / rel_dir / f"{base}.mp4"
    dest.parent.mkdir(parents=True, exist_ok=True)
    if Path(mp4).resolve() != dest.resolve():
        shutil.copyfile(mp4, dest)
    facts = _probe(dest)
    poster_rel = ""
    poster = dest.with_suffix(".jpg")
    if _poster(dest, poster, min(1.2, max(0.0, facts["duration"] * 0.3))):
        poster_rel = media.media_rel(poster)
    uv = UploadedVideo(store=store, title=f"موشن — {render.title}"[:200], state=UploadedVideo.State.READY,
                       duration=facts["duration"], has_audio=False)
    uv.video.name = media.media_rel(dest)
    uv.facts = {"readable": True, "duration": facts["duration"], "has_audio": False, "width": facts["width"], "height": facts["height"],
                "fps": facts["fps"], "source": "motion", "motion_render": render.pk}
    uv.save()
    render.video_id = uv.pk
    render.poster = poster_rel
    render.width, render.height, render.fps = facts["width"], facts["height"], int(round(facts["fps"]))
    render.duration_s = facts["duration"]
    render.bytes = dest.stat().st_size
    render.render_s = render_s
    render.state = MotionRender.State.READY
    render.progress = 1.0
    render.message = "آماده"
    render.error = ""
    render.finished_at = timezone.now()
    render.save()
    return render


# ───────────────────────────────────────────── the site render (capped fallback)

def render_on_site(render: MotionRender, on_wait=None) -> MotionRender:
    """اجرای رندرِ سایت (Celery). یک رندر در هر لحظه، ≤۱۰۸۰p، ≤۶۰ ثانیه، هم‌زمانیِ ۱."""
    render.refresh_from_db()
    if render.state not in (MotionRender.State.QUEUED, MotionRender.State.WAITING_NODE) or render.target != MotionRender.Target.SITE:
        return render

    def cancelled() -> bool:
        return MotionRender.objects.filter(pk=render.pk, state=MotionRender.State.CANCELLED).exists()

    lock = runner.SiteLock()
    work = Path(tempfile.mkdtemp(prefix="nm-motion-site-"))
    try:
        try:
            lock.acquire(on_wait=lambda s: MotionRender.objects.filter(pk=render.pk).update(message=f"منتظرِ نوبت — رندرِ دیگری در حال اجراست ({s} ثانیه)"), cancelled=cancelled)
        except runner.RenderError as exc:
            if exc.code == "cancelled":
                return render
            return fail(render, str(exc))
        render.refresh_from_db()
        if render.state == MotionRender.State.CANCELLED:
            return render
        render.state = MotionRender.State.RENDERING
        render.message = "در حال رندر روی سایت"
        render.progress = 0.0
        render.save(update_fields=["state", "message", "progress", "updated_at"])
        try:
            job, files = build_job(render)
            adir = work / "assets"
            adir.mkdir()
            for key, (data, ext) in files.items():
                (adir / f"{key}{ext}").write_bytes(data)
            job["assets_dir"] = str(adir)
            if render.mode == MotionRender.Mode.CODE:
                (work / "user.js").write_text(job.pop("user_js"), encoding="utf-8")
                job["user_js"] = str(work / "user.js")
            job["out"] = str(work / "out.mp4")

            last = [0.0]

            def on_progress(ev):
                p = float(ev.get("progress") or 0)
                if p - last[0] >= 0.02:
                    last[0] = p
                    MotionRender.objects.filter(pk=render.pk).update(progress=round(p, 3), message=("کدگذاری" if ev.get("stage") == "encoding" else "در حال رندر روی سایت"))

            done = runner.run_render(job, workdir=work, on_progress=on_progress, cancelled=cancelled)
            render.refresh_from_db()
            if render.state == MotionRender.State.CANCELLED:
                return render
            finalize(render, Path(done["out"]), render_s=round(done.get("ms", 0) / 1000, 1))
        except runner.RenderError as exc:
            if exc.code == "cancelled":
                return render
            fail(render, str(exc))
        except MotionError as exc:
            fail(render, str(exc))
        except Exception as exc:  # noqa: BLE001
            logger.exception("motion: site render %s crashed", render.pk)
            fail(render, f"خطای پیش‌بینی‌نشده: {exc}")
    finally:
        lock.release()
        shutil.rmtree(work, ignore_errors=True)
    return render


# ───────────────────────────────────────────── JSON for the panel

def video_url(render: MotionRender) -> str | None:
    if not render.video_id:
        return None
    from apps.content.models import UploadedVideo

    uv = UploadedVideo.objects.filter(pk=render.video_id).first()
    if uv is None or not uv.video:
        return None
    return settings.MEDIA_URL.rstrip("/") + "/" + uv.video.name


def render_dict(r: MotionRender) -> dict:
    st = catalog.get(r.style) if r.style else None
    return {
        "id": r.pk, "mode": r.mode, "mode_label": r.get_mode_display(), "title": r.title, "style": r.style,
        "style_name": (st or {}).get("name_fa", ""), "aspect": r.aspect, "state": r.state, "state_label": r.get_state_display(),
        "active": r.state in MotionRender.ACTIVE, "progress": round(r.progress, 3), "message": r.message, "error": r.error,
        "target": r.target, "target_label": r.get_target_display(), "quality": (r.options or {}).get("quality"),
        "duration_s": round(r.duration_s, 2), "width": r.width, "height": r.height, "bytes": r.bytes, "render_s": round(r.render_s, 1),
        "video_id": r.video_id, "video_ref": f"video:{r.video_id}" if r.video_id else None, "video_url": video_url(r),
        "poster_url": assets.media_url(r.poster) if r.poster else None,
        "created_at": r.created_at.isoformat(), "finished_at": r.finished_at.isoformat() if r.finished_at else None,
        "job_uid": r.job_uid,
    }
