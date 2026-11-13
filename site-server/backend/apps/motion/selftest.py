"""آزمونِ خودکارِ گره برای «استودیوی موشن»: یک رندرِ قالبیِ ۳ ثانیه‌ای (۵۴۰×۹۶۰) با متنِ فارسی.

وقتی صفحهٔ «آزمونِ خودکارِ سرورِ پردازش» (apps/compute/selftests/) در دسترس باشد، همین ماژول را به‌عنوانِ یک آزمونِ «motion» ثبت می‌کند:

    from apps.motion import selftest
    job = selftest.enqueue()            # کارِ واقعیِ motion.render در صف (منتظرِ روشن‌شدنِ گره می‌ماند)
    ok, why = selftest.check(job)       # پس از پایانِ کار: خروجی و اندازه‌ها درست است؟

اگر آن پوشه در این نسخه نیست، قرارداد در docs/selftests/motion.md آمده است.
"""
from __future__ import annotations

from apps.compute import services as CS
from apps.compute.models import ComputeJob

KIND = "motion.render"
SPEC = {
    "version": 1, "style": "flat-vector", "aspect": "9:16", "fps": 30, "lang": "fa", "digits": "auto",
    "brand": {"use_brand_colors": True, "show_logo": False, "colors": ["#126F85", "#163F75"]},
    "scenes": [{"type": "title", "duration": 3, "kicker": "آزمونِ موشن", "title": "سلام، چغر!", "subtitle": "رندرِ ۳ ثانیه‌ای با متنِ فارسی"}],
}
PAYLOAD = {"composition": "Template", "props": {"spec": SPEC}, "scale": 0.5, "crf": 23, "max_seconds": 10, "title": "motion selftest",
           "style": "flat-vector", "mode": "template", "selftest": True}
EXPECT = {"frames": 90, "width": 540, "height": 960, "fps": 30}


def enqueue() -> ComputeJob:
    """کارِ آزمون را در صفِ ماندگار می‌گذارد (dedupe خاموش: هر بار یک رندرِ واقعی)."""
    return CS.enqueue(KIND, dict(PAYLOAD), None, origin="selftest", priority=50, timeout_s=900, dedupe=False, require_online=False, category="selftest")


def check(job: ComputeJob) -> tuple[bool, str]:
    """(قبول؟, دلیلِ فارسی). فقط اگر کار COMPLETED باشد و ویدیو واقعاً ۹۰ فریمِ ۵۴۰×۹۶۰ باشد قبول است."""
    if job.state != ComputeJob.State.COMPLETED:
        return False, f"کار تمام نشده است ({job.get_state_display()}){': ' + job.error[:160] if job.error else ''}"
    outs = {o["name"]: o for o in job.outputs()}
    if "out.mp4" not in outs or outs["out.mp4"].get("size", 0) < 5000:
        return False, "ویدیوی خروجی (out.mp4) نرسید یا خیلی کوچک است."
    meta = (job.result or {}).get("meta") or {}
    for k, want in EXPECT.items():
        if meta.get(k) not in (None, want):
            return False, f"«{k}» باید {want} باشد، گره {meta.get(k)} گزارش کرد."
    path = CS.output_path(job, "out.mp4")
    try:
        from services.video import ffmpeg as ff

        v = ff.probe_video(path)
        if (int(v["width"]), int(v["height"])) != (EXPECT["width"], EXPECT["height"]) or abs(float(v["duration"]) - 3.0) > 0.3:
            return False, f"ویدیو {v['width']}×{v['height']} و {float(v['duration']):.1f} ثانیه است؛ انتظار ۵۴۰×۹۶۰ و ۳ ثانیه."
    except Exception as exc:  # noqa: BLE001
        return False, f"ویدیو خوانده نشد: {exc}"
    return True, "ok"
