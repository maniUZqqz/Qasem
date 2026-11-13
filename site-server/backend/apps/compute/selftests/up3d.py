"""آزمونِ خودکارِ رندرِ سه‌بعدی (Blender 4.5، Cycles روی کارتِ گرافیک) — کارِ `up3d.render` (عامل ۲٫۱۲).

دو آزمون، هر دو با صحنهٔ واقعیِ موتورِ ۱٫۳ که **همین‌جا روی سایت** تا `compiled.json` آماده می‌شود (شکل‌دهیِ حروفِ فارسیِ سه‌بعدی با Pillow
روی سایت است، نه روی گره) و به شکلِ بستهٔ زیپ همراهِ کار به گره می‌رود:

  up3d_stage   استیجِ محصول + نورِ HDRI (Poly Haven) + متنِ سه‌بعدیِ فارسی «چغر» (طلا) + کرهٔ کروم؛ دو تصویرِ ثابت با Cycles/OptiX.
               قبول = دو PNG سالم و روشن (نه سیاه، نه تخت)، Cycles واقعاً روی کارت (OptiX یا CUDA) بوده، بی‌بازگشت به پردازنده.
  up3d_phone   «نمایشِ اپ»: گوشی با صفحه‌های برندِ چغر، دوربینِ کمانی، تاری حرکت و عمقِ میدان؛ ۸ فریم و ساختِ MP4 (عمیق، اختیاری).

نصبِ Blender روی گره خودکار است (processing/requirements.d/blender-3d.json)؛ تا پایانِ نصب آزمون «منتظرِ نصب» می‌ماند.
محتوا فقط نام و شعارِ چغر است (docs/chagher/brand-facts-fa.md)؛ قیمت یا آماری ساخته نمی‌شود.
"""
from __future__ import annotations

import io
import json
import os
import shutil
import tempfile
import zipfile

from . import SelfTest, Spec, Verdict, register

KIND = "up3d.render"
BRAND = {"product_name": "چغر", "brand": "چغر", "tagline": "با چغر چغر تر شو", "brand_color": "#126F85", "brand_color_2": "#163F75",
         "benefits": ["پیش‌نویسِ برنامهٔ ورزشی و غذایی", "دستورالعملِ شخصیِ مربی", "خروجیِ PDF برندشده و قابل‌چاپ"]}


def _available(node):
    kinds = (node.capabilities or {}).get("kinds")
    if isinstance(kinds, list) and KIND in kinds:
        return True, ""
    return False, "عاملِ این سرور هنوز رندرِ سه‌بعدی را بلد نیست (۲٫۱۲ به بالا)؛ «به‌روزرسانی» را بزنید"


def stage_doc(reg):
    """استیج + HDRI + متنِ سه‌بعدیِ فارسی + کرهٔ کروم؛ ۳ ثانیه، یک شاتِ کمانی."""
    from up3d import scene as S

    doc = S.new_scene(title="آزمونِ استیج", duration=3.0, aspect="9:16")
    doc["environment"] = {"id": "stage", "params": {"floor_gloss": 0.6}}
    doc["lighting"] = {"id": "hdri_studio", "params": {}}
    doc["products"] = [
        {"id": "p1", "asset": "text_3d", "name": "چغر", "surface": "platform",
         "params": {"text": BRAND["brand"], "width_m": 0.26, "depth_m": 0.035, "finish": "gold"}},
    ]
    doc["shots"] = [{"shot": "stage_hero", "start": 0, "duration": 3.0, "subject": "p1", "move": "orbit_left",
                     "params": {"height": 0.42}}]
    doc["render"] = {"look": "agx", "dof": True, "motion_blur": True, "bloom": 0.2}
    return doc


def phone_doc(reg):
    from up3d import templates

    doc = templates.build("app_showcase", dict(BRAND), reg)
    doc["output"]["duration"] = 2.4
    doc["shots"] = [{"shot": "phone_angle", "start": 0, "duration": 2.4, "subject": "p1", "move": "arc_right", "params": {}}]
    doc["overlays"] = []
    return doc


def _package(doc_fn, profile_overrides):
    """سایت: سند ⇐ compiled.json + inputs/ ⇐ زیپ (همان قالبِ بستهٔ کارگر)."""
    from up3d import pipeline
    from up3d.assets import registry

    reg = registry()
    d = tempfile.mkdtemp(prefix="up3d-selftest-")
    try:
        pipeline.prepare(doc_fn(reg), d, "standard", None, log=lambda m: None, reg=reg, profile_overrides=profile_overrides)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.write(os.path.join(d, "compiled.json"), "compiled.json")
            inputs = os.path.join(d, "inputs")
            if os.path.isdir(inputs):
                for dp, _dirs, fns in os.walk(inputs):
                    for f in fns:
                        full = os.path.join(dp, f)
                        zf.write(full, os.path.relpath(full, d).replace(os.sep, "/"))
        return buf.getvalue()
    finally:
        shutil.rmtree(d, ignore_errors=True)


def build_stage(ctx):
    pkg = _package(stage_doc, {"resolution": 480, "samples": 24})
    return Spec(KIND, {"package": "package.zip", "mode": "contact", "extra": ["--count", "2"], "require_gpu": True},
                {"package.zip": pkg}, timeout_s=2400)


def build_phone(ctx):
    pkg = _package(phone_doc, {"resolution": 540, "samples": 24, "frame_step": 3})
    return Spec(KIND, {"package": "package.zip", "mode": "render", "require_gpu": True}, {"package.zip": pkg}, timeout_s=3600)


def _device_check(ctx, job):
    """(ok, device, text): Cycles must have run on the card."""
    rep = ctx.read_json(job, "engine_report.json") or {}
    dev = rep.get("device") or {}
    typ = str(dev.get("type") or "?").upper()
    meta = ctx.meta(job)
    on_gpu = typ in ("OPTIX", "CUDA", "HIP", "ONEAPI", "METAL") and meta.get("device") != "cpu"
    text = "Cycles %s%s · %s" % (typ, (" (" + dev.get("name") + ")") if dev.get("name") else "", rep.get("denoiser") or "denoise ?")
    if rep.get("fallbacks"):
        text += " · بازگشت: " + str((rep["fallbacks"][0] or {}).get("error") or "")[:120]
    return on_gpu, ("cuda" if on_gpu else "cpu"), text


def _image_ok(raw):
    """PNG سالم، نه سیاه و نه تخت: میانگین و پراکندگیِ روشنایی."""
    from PIL import Image, ImageStat

    im = Image.open(io.BytesIO(raw)).convert("L")
    st = ImageStat.Stat(im)
    return im.size, st.mean[0], st.stddev[0]


def check_stage(ctx, job):
    outs = [o for o in job.outputs() if str(o.get("name", "")).startswith("contact_") and str(o["name"]).endswith(".png")]
    if len(outs) < 2:
        return Verdict.failed("دو تصویرِ آزمون ساخته نشد (%d)" % len(outs))
    stats = []
    for o in outs[:2]:
        raw = ctx.read_output(job, o["name"])
        if not raw or len(raw) < 4000:
            return Verdict.failed("تصویرِ «%s» خالی یا خیلی کوچک است" % o["name"])
        size, mean, std = _image_ok(raw)
        if mean < 18 or mean > 238 or std < 10:
            return Verdict.failed("تصویرِ «%s» سیاه/سفید یا تخت است (میانگین %.0f، پراکندگی %.0f)؛ نور یا دوربینِ صحنه کار نکرده" % (o["name"], mean, std))
        stats.append((size, mean, std))
    ok, device, text = _device_check(ctx, job)
    if not ok:
        return Verdict.failed("Cycles روی کارتِ گرافیک اجرا نشد (%s)؛ درایورِ NVIDIA یا نصبِ Blender را ببینید" % text, device=device)
    return Verdict.passed("%s · %dx%d · روشنایی %.0f/%.0f · %s ثانیه" % (text, stats[0][0][0], stats[0][0][1], stats[0][1], stats[1][1],
                                                                       ctx.meta(job).get("seconds")), device=device)


def check_phone(ctx, job):
    outs = {o.get("name"): o for o in job.outputs()}
    mp4 = outs.get("render.mp4")
    if not mp4 or (mp4.get("size") or 0) < 8000:
        return Verdict.failed("render.mp4 ساخته نشد یا خالی است")
    raw = ctx.read_output(job, "render.mp4") or b""
    if raw[4:8] != b"ftyp":
        return Verdict.failed("render.mp4 فایلِ MP4 سالم نیست")
    ok, device, text = _device_check(ctx, job)
    if not ok:
        return Verdict.failed("Cycles روی کارتِ گرافیک اجرا نشد (%s)" % text, device=device)
    return Verdict.passed("%s · %s کیلوبایت · %s فریم" % (text, (mp4.get("size") or 0) // 1024, ctx.meta(job).get("frames")), device=device)


register(SelfTest(key="up3d_stage", label="ویدیوی سه‌بعدی: استیج، HDRI و متنِ فارسی (Blender / Cycles)", group="video", kind=KIND, build=build_stage,
                  check=check_stage, available=_available, gpu_required=True, order=60,
                  requeue={"kinds": (KIND,)}, describe="دو تصویرِ ۴۸۰ پیکسلی با OptiX؛ قبول = Blender نصب است و Cycles روی کارت کار می‌کند"))
register(SelfTest(key="up3d_phone", label="ویدیوی سه‌بعدی: نمایشِ اپ روی گوشی (۸ فریم، MP4)", group="video", kind=KIND, build=build_phone,
                  check=check_phone, available=_available, gpu_required=True, optional=True, deep=True, order=61, after=("up3d_stage",),
                  requeue={"kinds": (KIND,)}, describe="گوشی با صفحه‌های برندِ چغر، دوربینِ کمانی، تاری حرکت و عمقِ میدان؛ خروجی MP4"))
