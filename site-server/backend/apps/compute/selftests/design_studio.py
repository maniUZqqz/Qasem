# -*- coding: utf-8 -*-
"""آزمونِ خودکارِ «استودیوی طراحی» (قراردادِ docs/selftests/design_studio.md).

· `design_deck_ai` (کارِ واقعی، روی کارت): پیش‌نویسِ ارائهٔ چغر با مدلِ متنیِ خودِ مالک (`ollama.generate`؛ هیچ مدلی عوض نمی‌شود). قبول = JSONِ درست، دست‌کم ۳ اسلایدِ معتبر
  و هیچ عددِ ساختگی (نگهبانِ عدد). تا روشن‌شدنِ گره «منتظرِ گره» می‌ماند؛ ساختِ ارائه با قاعده‌ها منتظرِ این نمی‌ماند.
· `design_slides_mp4` (کارِ واقعی، روی کارت): ۳ اسلایدِ کوچک ⇒ MP4 با `edit.slides_mp4`؛ قبول فقط اگر رمزگذاری روی کارت (NVENC) انجام شده باشد.
· `design_offline` (مجازی، بی‌گره): چیدمان، کاتالوگ + PDF چاپی (بلید و علامت برش)، ارائه + PPTX، فریم‌های UI، نگهبانِ عدد و مسیرهای هوش مصنوعی.

اگر اپِ `apps.design_studio` در این نسخه نیست، چیزی ثبت نمی‌شود و هیچ خطایی نمی‌آید.
"""
try:  # pragma: no cover — بسته به این‌که وصلهٔ استودیوی طراحی اعمال شده باشد
    from apps.design_studio import selftest as _ds
except Exception:  # noqa: BLE001
    _ds = None

from . import SelfTest, Spec, Verdict, caps_ok, register
from .ollama import _configured, _text_available, pick_text


def build_ai(ctx):
    model = pick_text(ctx.installed_ollama(), _configured("text"))
    s = _ds.node_spec(model)
    return Spec(s["kind"], s["payload"], timeout_s=int(s.get("timeout_s") or 1800))


def check_ai(ctx, job):
    data = ctx.read_json(job, "ollama.json")
    meta = ctx.meta(job)
    dev = meta.get("device", "")
    if not isinstance(data, dict):
        return Verdict.failed("جوابِ ollama.json نرسید.", device=dev)
    text = str(data.get("response") or (data.get("message") or {}).get("content") or "").strip()
    model = (job.payload or {}).get("model")
    if len(text) < 60:
        return Verdict.failed("مدلِ «%s» جوابِ خیلی کوتاه داد (%d نویسه)." % (model, len(text)), device=dev)
    ok, message = _ds.node_check(text)
    detail = "«%s» · %s" % (model, message)
    return Verdict.passed(detail, device=dev) if ok else Verdict.failed(detail, device=dev)


def _video_available(node):
    """عاملی که «edit.slides_mp4» را در caps["kinds"] اعلام نکرده (نسخهٔ قدیمی) آن را نمی‌گیرد ⇒ آزمون «ردشده» می‌شود و با به‌روزرسانیِ گره خودکار اجرا می‌شود."""
    kinds = (node.capabilities or {}).get("kinds")
    if not isinstance(kinds, list) or "edit.slides_mp4" not in kinds:
        return False, "عاملِ این سرور هنوز «ساختِ ویدیو از ارائه» را نمی‌شناسد؛ با به‌روزرسانیِ گره اضافه می‌شود"
    return caps_ok(node, "ffmpeg", why="ffmpeg روی این سرور آماده نیست")


def build_video(ctx):
    s = _ds.video_spec()
    return Spec(s["kind"], s["payload"], files=s["files"], timeout_s=int(s.get("timeout_s") or 600))


def check_video(ctx, job):
    info = ctx.read_json(job, "video.json")
    ok, message, dev = _ds.video_check(info)
    if not ok:
        return Verdict.failed(message, device=dev)
    if dev != "nvenc":
        return Verdict.failed("ویدیو روی پردازنده (libx264) ساخته شد، نه کارت: " + message, device="cpu", extra={"info": info})
    return Verdict.passed(message, device="nvenc", extra={"info": info})


def virtual(ctx):
    res = _ds.run_offline()
    failed = [c for c in res["checks"] if not c["ok"]]
    if failed:
        return Verdict.failed("؛ ".join("%s: %s" % (c["key"], c["detail"]) for c in failed)[:400])
    return Verdict.passed("؛ ".join("%s ✓" % c["key"] for c in res["checks"]))


if _ds is not None:
    register(SelfTest(key="design_deck_ai", label="استودیوی طراحی: پیش‌نویسِ ارائه با مدلِ خودِ شما", group="text", kind="ollama.generate", build=build_ai, check=check_ai,
                      available=_text_available, gpu_required=False, optional=True, order=34, after=("ollama_text",), requeue={"kinds": ("ollama.generate",)},
                      describe="پرسشِ واقعیِ ارائهٔ چغر؛ باید JSONِ فارسیِ معتبر و بی‌عددِ ساختگی بدهد"))
    register(SelfTest(key="design_slides_mp4", label="استودیوی طراحی: ویدیوی ارائه روی کارت (NVENC)", group="video", kind="edit.slides_mp4", build=build_video, check=check_video,
                      available=_video_available, gpu_required=True, optional=True, order=35, needs_features=("ffmpeg-nvenc",), requeue={"kinds": ("edit.slides_mp4",)},
                      describe="۳ اسلاید ⇒ MP4 با ffmpeg روی کارتِ گرافیک؛ عاملِ قدیمی «ردشده» است تا به‌روزرسانی شود"))
    register(SelfTest(key="design_offline", label="استودیوی طراحی: چیدمان، PDF چاپی، PPTX و فریم‌ها", group="system", virtual=virtual, optional=True, order=98,
                      describe="بی‌گره: کاتالوگ با بلید و علامت برش، ارائه، PPTX، SVG، نگهبانِ عدد و مسیرهای هوش مصنوعی"))
