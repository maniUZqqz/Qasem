"""حذفِ پس‌زمینه با چند مدل (دورِ ۸): RVM روی خودِ سایت و u2netp / IS-Net / BiRefNet-lite روی سرورِ پردازش.

مدل‌های سرورِ پردازش با کارِ ``photo.matting`` در «صفِ ماندگار» اجرا می‌شوند (قراردادِ توافق‌شده با عاملِ compute):

* ورودی: ``{"image": <نامِ فایل>, "model": "u2netp"|"isnet"|"birefnet-lite", "feather": 0, "keep_size": true}``
* خروجی: ``cutout.png`` (RGBA، اندازهٔ اصل؛ ``meta.primary``)، ``mask.png`` (L) و ``photo-matting.json`` ({model, seconds, size, device})
* گزارشِ گره: ``capabilities["matting_models"] = {id: {state: installed|downloading|queued|missing|failed, size_mb, progress, error}}``
  و ``capabilities["photo_matting"] = True``؛ مدلِ نصب‌نشده ⇒ کار در صف می‌ماند («منتظرِ دانلودِ مدل»)، ناموفق نمی‌شود.

هیچ دانلودی روی سرورِ سایت انجام نمی‌شود؛ این‌جا فقط وضعیت خوانده می‌شود و کار ثبت می‌شود.
"""
from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

from . import matting, ops, services
from .models import PhotoAsset

logger = logging.getLogger(__name__)

CAPABILITY = "photo_matting"
JOB_KIND = "photo.matting"
ORIGIN = "photomatting"

NODE_MODELS: dict[str, dict] = {
    "u2netp": {"title": "U²-Net سبک (u2netp)", "size_mb": 5, "hint": "سریع و کم‌حجم؛ برای زمینهٔ ساده و کالای روشن خوب است"},
    "isnet": {"title": "IS-Net", "size_mb": 170, "hint": "لبه‌های دقیق‌تر برای کالا و لباس"},
    "birefnet-lite": {"title": "BiRefNet-lite", "size_mb": 220, "hint": "دقیق‌ترین؛ برای مو و لبه‌های ریز"},
}
SITE_MODEL = {"id": "rvm", "title": "RVM (روی سرورِ سایت)", "size_mb": 15, "hint": "سبک و همیشه آماده؛ برای آدم عالی است و برای کالا فقط وقتی با زمینه فرق دارد"}
ALL_IDS = ("rvm",) + tuple(NODE_MODELS)

STATE_FA = {"installed": "نصب است", "downloading": "در حالِ دانلود", "queued": "در صفِ دانلود", "missing": "در انتظارِ دانلود روی سرورِ پردازش",
            "failed": "دانلود ناموفق بود"}


def _nodes():
    from apps.compute import services as compute

    try:
        return compute.known_nodes(CAPABILITY)
    except Exception:  # noqa: BLE001 — فقط برای فروشگاهِ بی‌گره
        return []


def _model_report(node, model_id: str) -> dict:
    rep = ((node.capabilities or {}).get("matting_models") or {}).get(model_id)
    return rep if isinstance(rep, dict) else {}


def _official_status() -> dict | None:
    """وضعیتِ رسمیِ جداسازی از عاملِ compute (نسخهٔ ۲٫۷+)؛ اگر در دسترس نبود None و خوانشِ خودم می‌ماند."""
    try:
        from apps.compute import matting as official

        return official.status()
    except Exception:  # noqa: BLE001 — اختیاری
        return None


def status(store=None) -> dict:
    """وضعیتِ همهٔ مدل‌ها برای پنل: روی سایت (RVM) و روی سرورِ پردازش (هر کدام: نصب است / در حالِ دانلود / در انتظارِ دانلود)."""
    from apps.compute import services as compute

    from . import brand as brand_mod

    nodes = _nodes()
    try:
        online = {n.pk for n in compute.online_nodes(CAPABILITY)}
    except Exception:  # noqa: BLE001
        online = set()
    official = _official_status()
    rows = [{"id": "rvm", "where": "site", "title": SITE_MODEL["title"], "hint": SITE_MODEL["hint"], "size_mb": SITE_MODEL["size_mb"],
             "state": "installed" if matting.available() else "missing", "state_fa": "آماده روی سایت" if matting.available() else "مدلِ سایت پیدا نشد",
             "installed_on": [], "progress": None, "error": ""}]
    for mid, meta in NODE_MODELS.items():
        installed, downloading, failed, progress, err = [], [], [], None, ""
        for n in nodes:
            rep = _model_report(n, mid)
            st = rep.get("state")
            if st == "installed":
                installed.append(n.name)
            elif st == "downloading":
                downloading.append(n.name)
                progress = rep.get("progress", progress)
            elif st == "failed":
                failed.append(n.name)
                err = str(rep.get("error") or "")[:200]
        if installed:
            state = "installed"
        elif downloading:
            state = "downloading"
        elif failed:
            state = "failed"
        else:
            state = "missing"
        ready_now = False
        off = (official or {}).get("models", {}).get(mid)
        if off:                                    # گزارشِ رسمیِ عاملِ compute (apps.compute.matting) بر خوانشِ خودم مقدم است
            state = off.get("state", state)
            installed = off.get("installed_on", installed) or installed
            progress = off.get("progress", progress)
            err = off.get("error", err) or err
            ready_now = bool(off.get("ready_now"))
        fa_text = STATE_FA["missing"] if state == "missing" else STATE_FA[state]
        if state == "installed":
            fa_text = "نصب است روی " + "، ".join(installed)
        elif state == "downloading" and isinstance(progress, (int, float)):
            fa_text = f"{STATE_FA['downloading']} ({int(progress * 100)}٪)"
        rows.append({"id": mid, "where": "node", "title": meta["title"], "hint": meta["hint"], "size_mb": meta["size_mb"], "state": state, "state_fa": fa_text,
                     "installed_on": installed, "progress": progress, "error": err, "ready_now": ready_now})
    runtime = next(((n.capabilities or {}).get("matting_runtime") for n in nodes if (n.capabilities or {}).get("matting_runtime")), None)
    return {"models": rows, "node_known": bool(nodes), "node_online": bool(online), "runtime": runtime,
            "needs_update": (official or {}).get("needs_update", []), "update_text": (official or {}).get("update_text", ""),
            "message": (official or {}).get("message", ""),
            "default": brand_mod.matting_model(store) if store is not None else "rvm"}


# ───────────────────────────── اجرا

def _site_path(asset: PhotoAsset) -> Path:
    return services.abs_path(asset.dir_rel) / "matting-rvm.png"


def run_site(asset: PhotoAsset) -> dict:
    """RVM روی همین سرور (همزمان؛ چند ثانیه). ⇒ {"state": "ready", "seconds"} یا {"state": "failed", "message"}."""
    import time

    t0 = time.monotonic()
    try:
        img = ops.load(services.abs_path(asset.original)).convert("RGB")
        a = matting.alpha(img)
    except Exception as exc:  # noqa: BLE001
        logger.exception("photoedit: site matting failed")
        return {"state": "failed", "message": f"جداسازی روی سایت ناموفق بود: {exc}"[:300]}
    if a is None:
        return {"state": "failed", "message": "مدلِ جداسازیِ سایت در دسترس نیست."}
    rgba = np.dstack([np.asarray(img), np.clip(a * 255.0 + 0.5, 0, 255).astype(np.uint8)])
    Image.fromarray(rgba, "RGBA").save(_site_path(asset), "PNG")
    return {"state": "ready", "seconds": round(time.monotonic() - t0, 2)}


def request(store, user, asset: PhotoAsset, models: list[str]) -> dict:
    """هر مدلِ خواسته‌شده: rvm ⇒ همین حالا روی سایت؛ مدلِ سرورِ پردازش ⇒ کارِ photo.matting در صفِ ماندگار.
    ⇒ {"jobs": [{model, state, message, uid?, url?}], "skipped": [...]}"""
    from apps.compute import services as compute

    src = services.abs_path(asset.original)
    name = f"photo-a{asset.pk}{src.suffix.lower()}"
    out, skipped = [], []
    for mid in dict.fromkeys(models or []):
        if mid not in ALL_IDS:
            skipped.append({"model": mid, "message": "مدلِ ناشناخته"})
            continue
        if mid == "rvm":
            r = run_site(asset)
            row = {"model": "rvm", "state": r["state"], "message": r.get("message", "آماده"), "uid": "", "seconds": r.get("seconds")}
            if r["state"] == "ready":
                row["url"] = f"/stores/{store.pk}/photo-editor/matting/site/{asset.pk}/"
            out.append(row)
            continue
        payload = {"image": name, "model": mid, "feather": 0, "keep_size": True}
        try:
            job = compute.enqueue_durable(JOB_KIND, payload, {name: str(src)}, store=store, origin=ORIGIN, priority=60)
        except compute.ComputeUnavailable:
            skipped.append({"model": mid, "message": "هیچ سرورِ پردازشی برای حذفِ پس‌زمینه ثبت نیست"})
            continue
        out.append({"model": mid, "uid": str(job.uid), **job_state(job)})
    return {"jobs": out, "skipped": skipped}


def job_state(job) -> dict:
    """وضعیتِ یک کارِ photo.matting برای پنل."""
    from apps.compute import services as compute
    from apps.compute.models import ComputeJob

    S = ComputeJob.State
    model = (job.payload or {}).get("model", "")
    base = {"model": model, "progress": float(job.progress or 0)}
    if job.state == S.COMPLETED:
        outs = {o["name"]: o for o in job.outputs()}
        if "cutout.png" not in outs:
            return base | {"state": "failed", "message": "سرورِ پردازش بریده‌ای پس نفرستاد."}
        meta = {}
        side = outs.get("photo-matting.json")
        if side:
            try:
                import json

                meta = json.loads(compute.output_path(job, "photo-matting.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                meta = {}
        took = (job.finished_at - job.claimed_at).total_seconds() if (job.finished_at and job.claimed_at) else meta.get("seconds")
        return base | {"state": "ready", "message": "آماده", "seconds": round(float(took), 1) if took else None,
                       "device": meta.get("device", ""), "node": job.node.name if job.node else "",
                       "url": f"/stores/{job.store_id}/photo-editor/matting/jobs/{job.uid}/cutout.png"}
    if job.state == S.FAILED:
        return base | {"state": "failed", "message": (job.error or "ناموفق")[:300]}
    if job.state == S.CANCELLED:
        return base | {"state": "cancelled", "message": "لغو شد"}
    if job.state == S.QUEUED:
        online = bool(compute.online_nodes(CAPABILITY)) if _capable() else bool(compute.online_nodes("photo"))
        msg = job.message if job.message and "دانلود" in job.message else services.queued_message(job, online)
        return base | {"state": "queued", "message": msg}
    return base | {"state": "running", "message": f"روی {job.node.name if job.node else 'سرورِ پردازش'}: {job.message or 'در حالِ جداسازی'}"}


def _capable() -> bool:
    return bool(_nodes())


def result_file(job) -> Path | None:
    from apps.compute import services as compute

    p = compute.output_path(job, "cutout.png")
    return p if p.is_file() else None


def import_result(store, user, asset: PhotoAsset, path: Path, model: str) -> PhotoAsset:
    """نتیجه را به‌عنوانِ عکسِ تازه (با پس‌زمینهٔ شفاف) در کتابخانه می‌گذارد."""
    data = Path(path).read_bytes()
    title = f"{asset.title} — بدونِ پس‌زمینه ({model})"
    return services.add_upload(store, user, SimpleUploadedFile("cutout.png", data, content_type="image/png"), title)
