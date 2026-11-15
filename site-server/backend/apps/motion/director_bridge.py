"""پلِ «کارگردان» ⇄ استودیوی موشن: ابزارِ `motion` ِ کارگردانِ ویدیو از اینجا صحنهٔ موشن می‌سازد، رندر می‌کند و ردیفِ ویدیوی فروشگاه (video:<id>) را برمی‌گرداند
تا روی تایم‌لاین به‌صورتِ کلیپ بنشیند.

انواع: title_card (تیترِ کینتیک) · stat (عددِ بزرگ) · list (چک‌لیست) · cta (دعوت به اقدام) · lower_third (نوارِ نام) · captions (زیرنویسِ کلمه‌به‌کلمه).
رندر: گره (اگر آنلاین و آماده) ⇐ وگرنه سایت (محدود، یک‌به‌یک) ⇐ وگرنه `Waiting` («در صف …»: کارگردان این گام را بعداً خودش پر می‌کند).
lower_third و captions روی زمینهٔ مشکیِ ساده (bare) رندر می‌شوند تا روی تایم‌لاین با ترکیبِ screen روی تصویر بنشینند.
"""
from __future__ import annotations

import logging
import time

from . import assets, catalog, specs

logger = logging.getLogger(__name__)

KINDS = ("title_card", "stat", "list", "cta", "lower_third", "captions")
KIND_LABELS = {"title_card": "کارتِ عنوان", "stat": "عددِ بزرگ", "list": "فهرست", "cta": "دعوت به اقدام", "lower_third": "نوارِ نام", "captions": "زیرنویسِ کلمه‌به‌کلمه"}
WAITING = "در صف — منتظرِ روشن شدنِ سرورِ پردازش؛ رندرِ موشن هر وقت روشن شد خودکار انجام می‌شود."
DEFAULT_STYLE = "flat-vector"


class MotionBridgeError(Exception):
    pass


class Waiting(MotionBridgeError):
    pass


def aspect_of(width: float, height: float) -> str:
    r = (width or 1080) / max(1.0, height or 1920)
    return min(("9:16", "4:5", "1:1", "16:9"), key=lambda a: abs(r - (int(a.split(":")[0]) / int(a.split(":")[1]))))


def build_spec(req: dict, brand: dict | None = None) -> dict:
    """درخواستِ ابزار ⇒ طرحِ صحنهٔ معتبر. متن‌ها همان‌هایی‌اند که کارگردان داده؛ چیزی ساخته نمی‌شود."""
    kind = str(req.get("kind") or "title_card")
    if kind not in KINDS:
        raise MotionBridgeError(f"نوعِ موشنِ «{kind}» را نمی‌شناسم (مجاز: {'، '.join(KINDS)}).")
    text, text2 = str(req.get("text") or "").strip(), str(req.get("text2") or "").strip()
    items = [x.strip(" -•\t") for x in str(req.get("items") or "").replace("؛", "\n").split("\n") if x.strip(" -•\t")]
    dur = float(req.get("duration") or 4)
    if kind == "title_card":
        if not text:
            raise MotionBridgeError("متنِ کارتِ عنوان لازم است.")
        scene = {"type": "kinetic_title", "duration": dur, "text": text[:140]} if len(text.split()) <= 7 and not text2 else {"type": "title", "duration": dur, "title": text[:140], "subtitle": text2[:220]}
    elif kind == "stat":
        val = str(req.get("value") or "").strip()
        if not val:
            raise MotionBridgeError("عدد لازم است.")
        scene = {"type": "stat", "duration": dur, "value": val[:24], "label": (str(req.get("label") or "") or text)[:160], "kicker": text2[:60] if text2 and (req.get("label") or text) else ""}
    elif kind == "list":
        if not items:
            raise MotionBridgeError("آیتم‌های فهرست لازم است.")
        scene = {"type": "checklist", "duration": max(dur, 3 + 1.3 * len(items)), "title": text[:100], "items": items[:6]}
    elif kind == "cta":
        if not text:
            raise MotionBridgeError("متنِ دعوت به اقدام لازم است.")
        scene = {"type": "cta", "duration": dur, "title": text[:140], "button": (text2 or "همین حالا")[:40]}
    elif kind == "lower_third":
        if not text:
            raise MotionBridgeError("نام لازم است.")
        scene = {"type": "lower_third", "duration": dur, "name": text[:60], "role": text2[:60]}
    else:
        if not text:
            raise MotionBridgeError("متنِ زیرنویس لازم است.")
        scene = {"type": "captions", "duration": max(dur, 0.32 * len(text.split()) + 1.2), "text": text[:300]}
    scene = {k: v for k, v in scene.items() if v not in ("", None)}
    style = str(req.get("style") or "") if catalog.get(str(req.get("style") or "")) else DEFAULT_STYLE
    b = brand or {}
    over = kind in ("lower_third", "captions") and req.get("track") == "overlay"
    spec = {"style": style, "aspect": str(req.get("aspect") or "9:16"), "fps": 30, "lang": "fa", "bare": over,
            "brand": {"use_brand_colors": True, "show_logo": bool(b.get("logo")) and not over, "colors": b.get("colors") or [], **({"logo": b["logo"]} if b.get("logo") else {})},
            "scenes": [scene]}
    if over:
        scene["tokens"] = {"text": "#ffffff"}
    return specs.normalize_spec(spec)


def make_clip(store, user, req: dict, *, wait_s: float = 420.0, render_fn=None) -> dict:
    """⇒ {"ref": "video:<id>", "duration": s, "render_id": id, "qa": خلاصه}. render_fn(render) را آزمون‌ها می‌دهند (جای رندرِ واقعی)."""
    from apps.compute import services as CS

    from . import pipeline, runner, services
    from .models import MotionRender

    spec = build_spec(req, assets.store_defaults(store))
    site_ok = runner.site_status()["ready"]
    node_ok = bool(CS.online_nodes(services.CAPABILITY)) and services.node_status()["state"] == "ready"
    if render_fn is None and not node_ok and not site_ok:
        if services.node_status()["registered"]:
            raise Waiting(WAITING)
        raise MotionBridgeError("ابزارِ رندرِ موشن روی سایت آماده نیست و سرورِ پردازشی هم ثبت نشده.")
    target = "node" if node_ok else "site"
    r = services.create(store, user, mode=MotionRender.Mode.TEMPLATE, title=f"{KIND_LABELS[str(req.get('kind') or 'title_card')]} — کارگردان", spec=spec,
                        quality=str(req.get("quality") or "720"), target=target, qa=True)
    outcome = pipeline.prepare_render(r)
    r.refresh_from_db()
    if outcome != "ready":
        raise MotionBridgeError(r.error or r.message or "آماده‌سازیِ موشن ناموفق بود.")
    if render_fn is not None:
        render_fn(r)
    elif node_ok:
        services.start(r)
        end = time.monotonic() + wait_s
        while time.monotonic() < end:
            r.refresh_from_db()
            if services.refresh(r):
                break
            time.sleep(4)
        r.refresh_from_db()
        if r.state in MotionRender.ACTIVE:
            raise Waiting(WAITING)
    else:
        services.start(r)                                   # SITE ⇒ QUEUED
        services.render_on_site(r)
    r.refresh_from_db()
    if r.state != MotionRender.State.READY or not r.video_id:
        raise MotionBridgeError(r.error or "رندرِ موشن تمام نشد.")
    return {"ref": f"video:{r.video_id}", "duration": r.duration_s or spec["total_s"], "render_id": r.pk, "bare": bool(spec.get("bare")), "qa": (r.qa or {}).get("summary", "")}
