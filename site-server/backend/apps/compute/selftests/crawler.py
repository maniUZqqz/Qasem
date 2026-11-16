"""آزمونِ «مشتری‌یاب» — یک کارِ واقعیِ کوچک `crawl.selftest` روی سرورِ پردازش (قراردادِ docs/selftests/crawler.md).

گره روی 127.0.0.1 یک وب‌سرورِ کوچک بالا می‌آورد با دو سایت: یکی ساده (تلفن + صفحهٔ تماس) و یکی «فقط جاوااسکریپت» (محتوا را بعد از بارگذاری
می‌سازد). خزنده باید هر دو را بخواند؛ سایتِ دوم را فقط مرورگرِ واقعی می‌خواند، پس این آزمون هم نصبِ خودکارِ Playwright و مرورگر
(requirements.d/crawl.json) و هم رندر را می‌سنجد، و هم نگهبانِ شبکه (آدرسِ خصوصی رد می‌شود). نتیجه: `selftest.json` = {ok, checks:[{name, ok, detail}]}.

تا نصبِ خودکار تمام نشود کارِ `crawl.selftest` در صفِ ماندگار می‌ماند و این آزمون «منتظرِ نصب» است. عاملِ قدیمی که نوع را اعلام نکرده
«اجرا نشد» ثبت می‌شود (نه «رد»)؛ با به‌روزرسانیِ خودکارِ گره دوباره امتحان می‌شود و بقیهٔ کارهای صف‌شدهٔ مشتری‌یاب هم از همان لحظه راه می‌افتند."""
from . import SelfTest, Spec, Verdict, register

KIND = "crawl.selftest"
KEY = "crawler"
RENDER_KIND = "crawl.render"
RENDER_KEY = "crawler_render"


def _available(node):
    caps = node.capabilities or {}
    kinds = caps.get("kinds")
    if isinstance(kinds, list) and KIND in kinds:
        return True, ""
    if caps.get("crawl"):
        return True, ""
    return False, "مشتری‌یاب روی این سرور نیست (عاملِ گره نوعِ «%s» را اعلام نکرده؛ به‌روزرسانیِ نرم‌افزارِ سرورِ پردازش لازم است)" % KIND


def build(ctx):
    return Spec(KIND, {"selftest": True}, timeout_s=900)


def build_render(ctx):
    """The same acceptance check, sent as the real kind `crawl.render` (the node's handler runs the self-test when the payload says so): it is the kind
    the install list holds back until the browser is ready, so this proves the hold-back lifts and the render path answers."""
    return Spec(RENDER_KIND, {"selftest": True}, timeout_s=900)


def check(ctx, job):
    rep = ctx.read_json(job, "selftest.json")
    if not isinstance(rep, dict):
        return Verdict.failed("selftest.json از گره نرسید")
    checks = [c for c in rep.get("checks") or [] if isinstance(c, dict)]
    bad = [c for c in checks if not c.get("ok")]
    if rep.get("ok") and not bad:
        return Verdict.passed("%d بررسی گذشت (%s)" % (len(checks), "، ".join(str(c.get("name")) for c in checks)[:160]))
    browser_missing = any(c.get("name") == "browser_ready" for c in bad)
    why = "؛ ".join("%s (%s)" % (c.get("name"), str(c.get("detail") or "")[:80]) for c in bad)[:600]
    if browser_missing:
        return Verdict.waiting("مرورگرِ خزنده هنوز آماده نیست (نصبِ خودکار ادامه دارد): " + why)
    return Verdict.failed("رد شد: " + why)


register(SelfTest(key=KEY, label="مشتری‌یاب: خواندنِ سایت و رندرِ صفحهٔ جاوااسکریپتی", group="system", kind=KIND, build=build, check=check, available=_available,
                  optional=True, gpu_required=False, order=170, requeue={"kinds": ("crawl.run", "crawl.render")}, files=("crawl_jobs.py", "requirements.d/crawl.json"),
                  needs_features=("crawl",), min_agent="2.33",
                  describe="دو سایتِ آزمایشی روی همان گره؛ یکی ساده و یکی فقط جاوااسکریپت"))

register(SelfTest(key=RENDER_KEY, label="مشتری‌یاب: رندرِ صفحه در مرورگرِ گره (crawl.render)", group="system", kind=RENDER_KIND, build=build_render, check=check, available=_available,
                  optional=True, gpu_required=False, order=171, requeue={"kinds": (RENDER_KIND,)}, files=("crawl_jobs.py", "requirements.d/crawl.json"),
                  needs_features=("crawl",), min_agent="2.33",
                  describe="همان دو سایتِ آزمایشی، با نوعِ کارِ واقعیِ رندر؛ تا آماده‌شدنِ مرورگر در صف می‌ماند"))
