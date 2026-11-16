"""آزمونِ «شخصیتِ برند» — قراردادِ `docs/selftests/brandchar.md`.

دو آزمون:
  * ``brandchar_engine`` (بی‌گره، همیشه روشن): همین شخصیت در هر سه سبکِ برداری و آدمک‌چوبی × چند ژست × ۴ اندازه روی پردازنده کشیده می‌شود؛ خالی نیست و همهٔ رنگ‌های امضا (کلیدِ رنگ) دیده می‌شوند.
  * ``brandchar_render`` (روی گره، کارتی): یک کارِ واقعیِ کوچکِ ``brandchar.render`` (FLUX روی ComfyUI، img2img از روی استیکرِ شخصیت). قبول = تصویرِ سالم + سنجشِ ثبات روی خروجی انجام شد
    (رنگ‌های امضا و سیلوئت؛ نتیجه «پرچم» است و در گزارش می‌آید). گرهٔ خاموش ⇒ کار در صفِ ماندگار می‌ماند و با روشن‌شدنِ گره خودکار اجرا می‌شود.
اگر این نسخه `apps.brandchar` را ندارد، چیزی ثبت نمی‌شود و هیچ خطایی نمی‌آید."""
from __future__ import annotations

import io

try:  # pragma: no cover — بسته به این‌که وصلهٔ شخصیتِ برند اعمال شده باشد
    from apps.brandchar import selftest as _bc
except Exception:  # noqa: BLE001
    _bc = None

from . import SelfTest, Spec, Verdict, caps_ok, register


def virtual(ctx) -> Verdict:
    res = _bc.run_engine()
    if res["ok"]:
        return Verdict.passed("%d سبک × %d ژست × %d اندازه = %d تصویر روی پردازنده (%s ثانیه): شخصیت همه‌جا دیده شد و همهٔ رنگ‌های امضا بود؛ بدونِ GPU و بدونِ هوش مصنوعی"
                              % (res["styles"], res["poses"], res["sizes"], res["total"], res["seconds"]), device="cpu")
    bad = res["failed"][0]
    return Verdict.failed("%d از %d تصویر رد شد؛ نمونه: سبکِ «%s»، ژستِ «%s» در اندازهٔ «%s»: %s" % (len(res["failed"]), res["total"], bad["style"], bad["pose"], bad["size"], "؛ ".join(bad["notes"])), device="cpu")


def available(node):
    ok, why = caps_ok(node, "comfyui", why="ComfyUI روی این سرور نیست و عامل هم نمی‌تواند روشنش کند")
    if not ok:
        return ok, why
    caps = node.capabilities or {}
    kinds = caps.get("kinds")
    if not (isinstance(kinds, list) and "brandchar.render" in kinds):
        return False, "عاملِ این سرور هنوز ماژولِ شخصیتِ برند را ندارد؛ با به‌روزرسانیِ بعدی می‌آید و آزمون خودکار اجرا می‌شود"
    bc = caps.get("brandchar")
    if isinstance(bc, dict) and bc.get("ready") is False:
        return False, "پروفایلِ FLUX برای ویرایشِ تصویر روی این سرور نیست"
    return True, ""


def build(ctx):
    s = _bc.node_spec()
    return Spec("brandchar.render", s["payload"], files=s["files"], timeout_s=2400)


def check(ctx, job):
    outs = [o for o in job.outputs() if str(o.get("name", "")).lower().endswith((".png", ".jpg", ".jpeg", ".webp"))]
    if not outs:
        return Verdict.failed("گره تصویری برنگرداند (خروجی‌ها: %s)" % ", ".join(o.get("name", "?") for o in job.outputs()))
    raw = ctx.read_output(job, outs[0]["name"])
    ok, detail = _bc.check_node_image(raw or b"")
    return Verdict.passed(detail) if ok else Verdict.failed(detail)


if _bc is not None:
    register(SelfTest(key="brandchar_engine", label="شخصیتِ برند: همهٔ سبک‌ها، ژست‌ها و اندازه‌ها", group="system", virtual=virtual, optional=True, order=98,
                      describe="بی‌گره و بدونِ هوش مصنوعی: ۴ سبک × ژست‌ها × ۴ اندازه روی پردازنده؛ شخصیت خالی نیست و رنگ‌های امضایش دیده می‌شوند"))
    register(SelfTest(key="brandchar_render", label="شخصیتِ برند: تصویرِ هوش مصنوعی از شخصیت (FLUX)", group="image", kind="brandchar.render", build=build, check=check,
                      available=available, gpu_required=True, optional=True, order=46, needs_features=("brandchar",), files=("processing/brandchar_jobs.py", "processing/requirements.d/brandchar.json"),
                      requeue={"kinds": ("brandchar.render",)}, describe="یک تصویرِ ۵۱۲ با ۴ گام از روی استیکرِ شخصیت؛ بارگذاریِ اولِ FLUX چند دقیقه می‌برد"))
