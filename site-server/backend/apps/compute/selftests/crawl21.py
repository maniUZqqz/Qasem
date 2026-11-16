"""آزمونِ «خزندهٔ 21st.dev با مرورگرِ بی‌سر» (سایت‌ساز) — کارِ واقعیِ کوچک: `crawl21.run` برای یک قطعهٔ آشنا.

کار: payload = {"ids": ["dillionverma/marquee"], "want": "md,page", "delay_s": 1.5, "selftest": true}؛ خروجی `results.json`.
قبول: یک ردیفِ `ok` که `md` اش با «#» شروع می‌شود و «License:» دارد، و `page.demo.code` یک نمونهٔ استفاده (import/export) است؛ یعنی مرورگر باز شد،
صفحهٔ عمومی را خواند، robots.txt رعایت شد و دادهٔ لازم برای سایت‌ساز آمد. اگر عاملِ گره نوعِ `crawl21.run` را اعلام نکرده باشد «اجرا نشد» ثبت می‌شود (نه «رد»)؛
تا پایانِ نصبِ خودکار (`requirements.d/crawl21.json`) هم صبر می‌شود. پس از قبول، نتیجه همان‌جا هم به کاتالوگ می‌رود (c21_node.ingest_results).
"""
from . import SelfTest, Spec, Verdict, register

KIND = "crawl21.run"
PROBE = "dillionverma/marquee"


def _available(node):
    kinds = (node.capabilities or {}).get("kinds")
    if isinstance(kinds, list) and KIND in kinds:
        return True, ""
    return False, "خزندهٔ 21st.dev روی این سرور نیست (عاملِ گره نوعِ «%s» را اعلام نکرده)" % KIND


def build(ctx):
    return Spec(KIND, {"ids": [PROBE], "want": "md,page", "delay_s": 1.5, "selftest": True}, timeout_s=900)


def judge(data) -> tuple[bool, str]:
    """دادهٔ results.json ⇒ (قبول؟، توضیح) — جدا از ctx تا آزمون‌پذیر باشد."""
    if not isinstance(data, dict):
        return False, "results.json از گره نرسید"
    rows = [r for r in data.get("results") or [] if isinstance(r, dict)]
    row = next((r for r in rows if r.get("id") == PROBE), None)
    if row is None or not row.get("ok"):
        return False, "ردیفِ %s ناموفق بود (%s)" % (PROBE, (row or {}).get("error") or "بی‌پاسخ")
    md = str(row.get("md") or "")
    if not md.startswith("#") or "License:" not in md:
        return False, "متنِ .md ِ قطعه نرسید یا مجوز نداشت"
    demo = ((row.get("page") or {}).get("demo") or {})
    code = str(demo.get("code") or "")
    if "import" not in code:
        return False, "نمونهٔ استفادهٔ صفحه (Usage.tsx) از مرورگر نرسید"
    return True, "مرورگر %s؛ .md و نمونهٔ استفاده (%d نویسه) رسید" % (data.get("browser", "?"), len(code))


def check(ctx, job):
    data = ctx.read_json(job, "results.json")
    ok, why = judge(data)
    if not ok:
        return Verdict.failed(why)
    try:                                         # نتیجه همان‌جا به کاتالوگِ سایت‌ساز هم می‌رود تا آزمون «کارِ واقعی» بماند
        from apps.projects.builder import c21_node

        c21_node.ingest_results(data.get("results") or [])
    except Exception:                            # noqa: BLE001 - ریختن در کاتالوگ اختیاری است
        pass
    return Verdict.passed(why)


register(SelfTest(key="crawl21", label="خزندهٔ 21st.dev با مرورگرِ بی‌سر (سایت‌ساز)", group="system", kind=KIND, build=build, check=check, available=_available,
                  optional=True, gpu_required=False, order=88, needs_features=("crawl21",), requeue={"kinds": (KIND,)},
                  describe="یک صفحهٔ عمومیِ 21st.dev با Edge/Chrome باز می‌شود؛ robots.txt رعایت می‌شود"))
