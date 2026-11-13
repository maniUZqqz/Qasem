"""آزمونِ «چندزاویه» — پیوندِ قراردادِ `docs/selftests/multiangle.md` (ویژگیِ چندزاویه خودش هم آزمونِ خودکارِ جدا دارد؛ این‌جا همان کار
در اجرای کاملِ سرورِ پردازش هم دیده می‌شود). اگر عاملِ گره نوعِ `multiangle.selftest` را اعلام نکرده باشد، «اجرا نشد» ثبت می‌شود (نه «رد»).

کار: `multiangle.selftest` با `{"selftest": true}` و بدونِ ورودی؛ خروجی `selftest.json` = {"ok": bool, "checks": [{"name", "ok", "detail"}]}."""
from . import SelfTest, Spec, Verdict, register

KIND = "multiangle.selftest"


def _available(node):
    kinds = (node.capabilities or {}).get("kinds")
    if isinstance(kinds, list) and KIND in kinds:
        return True, ""
    return False, "چندزاویه روی این سرور نیست (عاملِ گره نوعِ «%s» را اعلام نکرده)" % KIND


def build(ctx):
    return Spec(KIND, {"selftest": True}, timeout_s=1500)


def check(ctx, job):
    rep = ctx.read_json(job, "selftest.json")
    if not isinstance(rep, dict):
        return Verdict.failed("selftest.json از گره نرسید")
    checks = [c for c in rep.get("checks") or [] if isinstance(c, dict)]
    bad = [c for c in checks if not c.get("ok")]
    if rep.get("ok") and not bad:
        return Verdict.passed("%d بررسی گذشت (%s)" % (len(checks), "، ".join(str(c.get("name")) for c in checks)[:160]))
    return Verdict.failed("رد شد: " + "؛ ".join("%s (%s)" % (c.get("name"), str(c.get("detail") or "")[:80]) for c in bad)[:600])


register(SelfTest(key="multiangle", label="چندزاویه: زاویه‌های مجازی و حرکتِ دوربین", group="video", kind=KIND, build=build, check=check,
                  available=_available, optional=True, gpu_required=False, order=85, requeue={"kinds": (KIND,)},
                  describe="ورودی را خودِ موتور با ffmpeg می‌سازد؛ مدل‌ها باید نصب باشند"))
