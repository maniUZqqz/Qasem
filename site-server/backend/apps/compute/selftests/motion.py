"""آزمونِ «استودیوی موشن» — یک رندرِ واقعیِ ۳ ثانیه‌ای (۵۴۰×۹۶۰، سبکِ «وکتورِ تخت»، متنِ فارسی) با `motion.render` روی کارتِ گرافیکِ گره.

کار و سنجش از `apps.motion.selftest` می‌آید (PAYLOAD / check: خروجیِ out.mp4 با ffprobe ⇒ ۹۰ فریم، ۵۴۰×۹۶۰، ۳ ثانیه). گره باید
`motion.render` را اعلام کرده باشد؛ تا نصبِ خودکارِ ابزارِ موشن (Node.js قابل‌حمل + بستهٔ رندر + مرورگرِ بی‌سر؛ یک تا چند دقیقه) تمام نشود
کار در صفِ ماندگار می‌ماند و این آزمون «منتظرِ نصب» است (runner.py: `SV.motion_blocked`). `device` نباید `cpu` باشد: یعنی Chromium با ANGLE/D3D11
روی کارت رسم کرده است (کدگذاریِ H.264 در Remotion روی ویندوز CPU است و عمداً رد حساب نمی‌شود).

قراردادِ هم‌ارزِ بدونِ کد: docs/selftests/motion.md (اگر این ماژول بار نشود docs_loader همان را ثبت می‌کند)."""
from . import SelfTest, Spec, Verdict, register

KIND = "motion.render"
KEY = "motion_studio"


def _available(node):
    caps = node.capabilities or {}
    kinds = caps.get("kinds")
    if not isinstance(kinds, list) or KIND not in kinds:
        return False, "عاملِ این سرور نوعِ «%s» را اعلام نکرده است (به‌روزرسانیِ نرم‌افزارِ سرورِ پردازش لازم است)" % KIND
    if not caps.get("motion_render"):
        return False, "ابزارِ موشن روی این سرور خاموش است (NM_MOTION=0)"
    return True, ""


def build(ctx):
    from apps.motion import selftest

    return Spec(KIND, dict(selftest.PAYLOAD), timeout_s=1200)


def check(ctx, job):
    from apps.motion import selftest

    meta = ctx.meta(job)
    device = str(meta.get("device") or "")
    ok, why = selftest.check(job)
    if not ok:
        return Verdict.failed(why, device=device)
    note = str(meta.get("device_note") or "")
    return Verdict.passed("۹۰ فریم · ۵۴۰×۹۶۰ · %s ثانیه%s" % (meta.get("seconds", "؟"), (" · " + note) if note else ""), device=device)


register(SelfTest(key=KEY, label="استودیوی موشن: رندرِ موشن‌گرافیک روی کارت", group="video", kind=KIND, build=build, check=check,
                  available=_available, gpu_required=True, order=160, requeue={"kinds": (KIND,)},
                  describe="رندرِ ۳ ثانیه‌ایِ قالبی با متنِ فارسی؛ نصبِ ابزارِ موشن خودکار است"))
