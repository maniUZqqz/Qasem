"""آزمونِ اتصال: کارِ echo از صف تا گره و برگشت (مسیرِ گرفتن، بسته، آپلود و پایان)."""
from . import SelfTest, Spec, Verdict, register


def build(ctx):
    return Spec("echo", {"sleep": 0, "selftest": True}, timeout_s=120)


def check(ctx, job):
    data = ctx.read_json(job, "echo.json")
    if not isinstance(data, dict):
        return Verdict.failed("پاسخِ echo.json نرسید.")
    if data.get("node") and data["node"] != ctx.node.name:
        return Verdict.failed("کار را گرهٔ دیگری (%s) انجام داد." % data["node"])
    return Verdict.passed("رفت‌وبرگشتِ کار %s ثانیه" % (job.run_s if job.run_s is not None else "؟"))


register(SelfTest(key="echo", label="اتصال: صف ⇒ سرورِ پردازش ⇒ برگشت", group="system", kind="echo", build=build, check=check,
                  order=5, describe="گرفتنِ کار، دریافتِ بسته، آپلودِ خروجی و پایان"))
