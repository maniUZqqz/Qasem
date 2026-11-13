"""آزمونِ خودکارِ «آباگرام» (خواننده‌ی اینستاگرام) روی سرورِ پردازش — ماژولِ آمادهٔ افتادن در backend/apps/compute/selftests/.

این فایل را بدونِ تغییر در `backend/apps/compute/selftests/trends_instagram.py` بگذارید (پوشه وقتی در کدِ زنده آمد). منطقِ سنجش در
`apps.igtrends.selftest.evaluate` است و آزمونِ واحد دارد؛ این‌جا فقط به چارچوبِ آزمون وصلش می‌کند.

۱) ig_health  — کارِ ig.health: آباگرام روی گره نصب است، روشن است و جواب می‌دهد؟ (بدونِ هیچ درخواستی به اینستاگرام؛ فقط یک آزمونِ
               اتصالِ بی‌نام). نبودنِ ورود به اینستاگرام «رد» نیست: همان‌جا نوشته می‌شود که یک بار Open-Abagram.bat لازم است.
۲) ig_scrape  — کارِ ig.scrape: یک صفحهٔ عمومی (instagram) با بودجه‌ی بسیار کوچک. فقط وقتی اجرا می‌شود که گره خودش بگوید آباگرام
               آماده است (وارد شده و خط باز است)؛ وگرنه «ردشده» (نه رد). ایستادنِ اینستاگرام (صبر کن / تأییدِ انسان / سقف) هم «ردشده» است:
               خودِ ایستادن درست کار کرده. اختیاری است تا حالِ اینستاگرام نتیجهٔ کلیِ آزمونِ گره را قرمز نکند.
"""
from apps.igtrends import selftest as T

from . import SelfTest, Spec, Verdict, register


def _capable(node):
    caps = node.capabilities or {}
    if not caps.get("instagram"):
        return False, "این گره هنوز با نسخه‌ای که آباگرام دارد به‌روز نشده (به‌روزرسانی/START.bat)"
    return True, ""


def _ready(node):
    ok, why = _capable(node)
    if not ok:
        return ok, why
    rep = (node.capabilities or {}).get("abagram") or {}
    if not rep.get("ready"):
        return False, T.PROBLEM_FA.get(rep.get("problem") or "", "آباگرام هنوز آماده نیست")
    return True, ""


def _build_health(ctx):
    return Spec(T.HEALTH["kind"], dict(T.HEALTH["payload"]), timeout_s=T.HEALTH["timeout_s"])


def _check_health(ctx, job):
    v = T.evaluate("health", ctx.meta(job))
    if v["status"] == "pass":
        return Verdict.passed(v["message"])
    problem = ((ctx.meta(job).get("report") or {}).get("problem")) or ""
    if problem in ("installing", "starting"):          # the node is still installing/starting it by itself: judge later
        return Verdict.waiting(v["message"])
    return Verdict.failed(v["message"])


def _build_scrape(ctx):
    return Spec(T.SCRAPE["kind"], dict(T.SCRAPE["payload"]), timeout_s=T.SCRAPE["timeout_s"])


def _check_scrape(ctx, job):
    v = T.evaluate("scrape", ctx.meta(job))
    if v["status"] == "pass":
        return Verdict.passed(v["message"])
    if v["status"] == "skip":
        return Verdict.skipped(v["message"])
    return Verdict.failed(v["message"])


register(SelfTest(key="ig_health", label="آباگرام (خواننده‌ی اینستاگرام): نصب و روشن بودن", group="system", kind="ig.health", build=_build_health,
                  check=_check_health, available=_capable, order=60,
                  describe="آباگرام خودکار نصب می‌شود و روی همین کامپیوتر جواب می‌دهد (بدونِ درخواست به اینستاگرام)"))
register(SelfTest(key="ig_scrape", label="آباگرام: خواندنِ یک صفحهٔ عمومی", group="system", kind="ig.scrape", build=_build_scrape,
                  check=_check_scrape, available=_ready, after=("ig_health",), optional=True, order=61,
                  describe="فقط وقتی آباگرام وارد اینستاگرام است؛ یک صفحه، چند پست، بودجه‌ی کوچک",
                  requeue={"kinds": ("ig.scrape",)}))
