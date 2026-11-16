"""پل‌ها: «ویرایش در طراح» (ادیتورِ عکس)، «ساخت ویدیو» (سرورِ پردازش)، «ساختِ سایت از این طرح» (سایت‌ساز).

هیچ موتورِ تازه‌ای نیست؛ هر پل به موتورِ موجود وصل می‌شود: ادیتورِ عکس (PhotoProject با لایه‌های متنِ قابل‌ویرایش)، صفِ پردازش (کارِ ``edit.slides_mp4`` روی GPU) و سایت‌ساز (Project/Design).
"""
from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

from django.core.files.uploadedfile import SimpleUploadedFile

from . import exports, render_png, scene, services, ui_doc, typeset
from .models import DesignDoc, DesignExport

VIDEO_KIND = "edit.slides_mp4"
VIDEO_PRIORITY = 85
VIDEO_TIMEOUT_S = 1800


# ───────────────────────────── ویرایش در طراح

FONT_MAP = {"vazirmatn": "vazirmatn", "estedad": "estedad", "lalezar": "lalezar", "shabnam": "shabnam", "sahel": "sahel", "samim": "samim"}


def edit_in_designer(doc: DesignDoc, page_id: str, user) -> dict:
    """یک صفحه/اسلاید/فریم ⇒ پروژهٔ ادیتورِ عکس: پس‌زمینه و عکس‌ها یک تصویرِ پایه، هر متن یک «لایهٔ متنِ» قابل‌ویرایش."""
    from apps.photoedit import services as photo
    from apps.photoedit.designer import render as photo_render

    b = services.bundle_for(doc, with_checks=False)
    page = next((p for p in b.pages if p["id"] == page_id), None)
    if page is None:
        raise services.DesignError("صفحه پیدا نشد.")
    width_px = 1800 if b.unit == "mm" else min(1920, int(page["w"]))
    scale = width_px / page["w"]
    base_page = {**page, "elements": [e for e in page["elements"] if e["type"] != "text" or e.get("bg")]}
    base = render_png.render_page(base_page, b.src, scale=scale)
    png = exports.to_bytes(base, "PNG")
    asset = photo.add_upload(doc.store, user, SimpleUploadedFile(f"design-{doc.pk}-{page_id}.png", png, content_type="image/png"), title=f"{doc.title} — {page.get('name', page_id)}")
    layers = [{"id": "base", "type": "base", "name": "صفحه", "visible": True, "locked": False, "opacity": 1, "blend": "normal", "mask": None}]
    W, H = page["w"], page["h"]
    for i, e in enumerate([e for e in page["elements"] if e["type"] == "text" and str(e.get("text", "")).strip()][:60], 1):
        lay = e.get("lay") or {}
        ch = lay.get("h") or e["h"]
        cy = e["y"] + ((e["h"] / 2) if e.get("valign") == "middle" else ch / 2)
        rtl = bool(lay.get("lines") and lay["lines"][0].get("rtl"))
        align = e.get("align", "auto")
        align = ("right" if rtl else "left") if align in ("auto", "justify") else align
        layers.append({"id": f"t{i}", "type": "text", "name": str(e["text"])[:30], "visible": True, "locked": False, "opacity": float(e.get("opacity", 1)), "blend": "normal", "mask": None,
                       "cx": round((e["x"] + e["w"] / 2) / W, 5), "cy": round(cy / H, 5), "rot": 0, "text": str(e["text"])[:500], "font": FONT_MAP.get(e.get("font"), "vazirmatn"),
                       "weight": int(e.get("weight", 400)), "size": round(max(0.005, min(0.5, lay.get("size", e["size"]) / W)), 5), "color": e.get("color", "#000000"), "align": align,
                       "dir": "rtl" if rtl else "ltr", "line_height": float(e.get("lh", 1.5)), "width": round(min(4.0, e["w"] / W), 5)})
    state = photo_render.default_state()
    state["layers"] = layers
    project = photo.create_project(doc.store, asset, f"{doc.title} — {page.get('name', page_id)}", state)
    return {"project": project.pk, "asset": asset.pk, "layers": len(layers) - 1, "url": f"/stores/{doc.store_id}/photo-editor?asset={asset.pk}&mode=manual"}


# ───────────────────────────── ویدیو (سرورِ پردازش)

def node_state() -> dict:
    from apps.compute import services as CS

    try:
        online = bool(CS.online_nodes("ffmpeg"))
        known = bool(CS.known_nodes("ffmpeg"))
    except Exception:  # noqa: BLE001
        return {"state": "unknown", "message": "وضعیتِ سرورِ پردازش معلوم نیست."}
    if online:
        return {"state": "online", "message": "سرورِ پردازش آنلاین است؛ ویدیو روی کارتِ گرافیک ساخته می‌شود."}
    if known:
        return {"state": "offline", "message": "سرورِ پردازش خاموش است؛ درخواست در صفِ ماندگار می‌ماند و با روشن‌شدنش ساخته می‌شود."}
    return {"state": "none", "message": "هیچ سرورِ پردازشی ثبت نشده است."}


def deck_to_video(doc: DesignDoc, user, params: dict | None = None) -> DesignExport:
    """اسلایدها ⇒ PNG ⇒ کارِ ``edit.slides_mp4`` در صفِ ماندگار؛ خروجی یک DesignExport (kind=mp4) است."""
    from apps.compute import services as CS

    if doc.kind != "deck":
        raise services.DesignError("ویدیو فقط از «ارائه» ساخته می‌شود.")
    p = params or {}
    seconds = max(2.0, min(30.0, float(p.get("seconds") or 5)))
    transition = p.get("transition") if p.get("transition") in ("fade", "fadeblack", "wipeleft", "wiperight", "slideleft", "slideright", "dissolve", "none") else "fade"
    b = services.bundle_for(doc, with_checks=False)
    tmp = Path(tempfile.mkdtemp(prefix="nm-design-video-"))
    try:
        paths, slides = {}, []
        for i, page in enumerate(b.pages, 1):
            name = f"s{i:02d}.png"
            (tmp / name).write_bytes(exports.to_bytes(render_png.render_page(page, b.src, scale=1920 / page["w"]), "PNG"))
            paths[name] = str(tmp / name)
            slides.append({"file": name, "duration": seconds})
        payload = {"slides": slides, "width": 1920, "height": 1080, "fps": 30, "transition": transition, "transition_s": 0.6 if transition != "none" else 0.0, "title": doc.title[:80]}
        try:
            job = CS.enqueue_durable(VIDEO_KIND, payload, paths, store=doc.store, origin="design", priority=VIDEO_PRIORITY, timeout_s=VIDEO_TIMEOUT_S, dedupe=False, lease_s=900,
                                     max_attempts=2, category="render")
        except Exception as exc:  # noqa: BLE001 — ComputeUnavailable
            raise services.DesignError(str(exc)) from exc
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    e = DesignExport.objects.create(doc=doc, created_by=user, kind="mp4", params={"seconds": seconds, "transition": transition}, doc_rev=doc.rev, state=DesignExport.State.RUNNING,
                                    message=job.message or "در صفِ سرورِ پردازش", info={"job": str(job.uid), "slides": len(slides), "node": node_state()})
    return e


def refresh_video(e: DesignExport) -> DesignExport:
    from apps.compute import services as CS
    from apps.compute.models import ComputeJob

    if e.kind != "mp4" or e.state not in DesignExport.ACTIVE:
        return e
    job = ComputeJob.objects.filter(uid=(e.info or {}).get("job")).first()
    if job is None:
        e.state, e.error, e.message = DesignExport.State.FAILED, "کارِ پردازش در صف پیدا نشد.", "ناموفق"
        e.save()
        return e
    S = ComputeJob.State
    if job.state == S.COMPLETED:
        out = CS.output_path(job, "out.mp4")
        if not out.is_file() or out.stat().st_size < 1000:
            e.state, e.error, e.message = DesignExport.State.FAILED, "سرورِ پردازش کار را تمام‌شده گزارش کرد ولی ویدیو نرسید.", "ناموفق"
        else:
            rel = f"s{e.doc.store_id}/d{e.doc_id}/exports/{e.pk}-video-{e.doc_id}.mp4"
            dest = exports.data_root() / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(out, dest)
            meta = (job.result or {}).get("meta") or {}
            e.file, e.filename, e.size_bytes = rel, f"deck-{e.doc_id}.mp4", dest.stat().st_size
            e.info = {**(e.info or {}), "encoder": meta.get("encoder", ""), "duration_s": meta.get("duration_s"), "render_s": meta.get("seconds")}
            e.state, e.progress, e.message, e.error = DesignExport.State.READY, 1.0, "آماده", ""
    elif job.state in (S.FAILED, S.CANCELLED):
        e.state, e.error, e.message = DesignExport.State.FAILED, (job.error or "ساختِ ویدیو ناموفق بود.")[:500], "ناموفق"
    else:
        e.message = job.message or ("در صفِ سرورِ پردازش" if job.state == S.QUEUED else "در حالِ ساختِ ویدیو")
        e.progress = max(e.progress, float(job.progress or 0))
        e.info = {**(e.info or {}), "node": node_state()}
    e.save()
    return e


# ───────────────────────────── سایت‌ساز

def create_site(doc: DesignDoc, user, params: dict | None = None) -> dict:
    """«ساختِ سایت از این طرح»: فقط پیش‌نویس در سایت‌ساز (هیچ‌چیز منتشر نمی‌شود)."""
    if doc.kind != "ui":
        raise services.DesignError("ساختِ سایت فقط از «طراحیِ UI/UX» است.")
    p = params or {}
    info = services.store_info(doc.store, doc.data.get("settings") or {})
    logo_bytes = None
    store = doc.store
    try:
        if getattr(store, "logo", None) and store.logo.name:
            logo_bytes = Path(store.logo.path).read_bytes()
    except (OSError, ValueError):
        logo_bytes = None
    try:
        out = ui_doc.to_site(doc.data, info, name=str(p.get("name") or "")[:100], slug=str(p.get("slug") or "")[:60], logo_bytes=logo_bytes)
    except ui_doc.SiteError as exc:
        raise services.DesignError(str(exc)) from exc
    meta = dict(doc.meta or {})
    meta.setdefault("sites", []).append({"project_id": out["project_id"], "slug": out["slug"], "at": __import__("django.utils.timezone", fromlist=["now"]).now().isoformat()})
    meta["site"] = out
    DesignDoc.objects.filter(pk=doc.pk).update(meta=meta)
    return out
