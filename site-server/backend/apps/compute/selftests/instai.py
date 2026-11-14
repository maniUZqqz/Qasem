"""آزمونِ خودکارِ «InstAI روی این رایانه» — ماژولِ آمادهٔ افتادن در backend/apps/compute/selftests/.

InstAI (استودیوی انیمیشن و داستانِ مالک؛ github.com/maniUZqqz/Instai) روی همان رایانهٔ GPUدار کار می‌کند. عاملِ گره (processing/instai_jobs.py)
پوشهٔ آن را پیدا می‌کند، اگر قدیمی بود (START.bat بدونِ به‌روزرسانیِ خودکار) یا نسخهٔ تازه‌ای روی GitHub بود و InstAI خاموش بود با همان
به‌روزرسانِ خودِ InstAI به‌روزش می‌کند و روشنش می‌کند، و گزارشِ خودآزمونِ InstAI (data/selftest/pc.json) را در ضربانِ قلب می‌فرستد
(caps["instai"]). این آزمون فقط همان گزارش را می‌سنجد؛ کاری روی گره نمی‌فرستد و چیزی را روشن/خاموش نمی‌کند.

اختیاری است: نبودنِ InstAI روی گره (یا پیدا نشدنِ پوشه‌اش) «رد» نیست و نتیجهٔ کلیِ آزمونِ گره را قرمز نمی‌کند.
"""
from . import SelfTest, Verdict, register

MIN_AGENT = "2.25"            # عاملی که instai_jobs.py را دارد (در زمانِ استقرار با نسخهٔ زندهٔ عامل پر می‌شود)


def _available(node):
    rep = (node.capabilities or {}).get("instai")
    if not isinstance(rep, dict):
        return False, "عاملِ این گره گزارشِ InstAI نمی‌دهد (processing/instai_jobs.py در بستهٔ گره نیست؟)"
    return True, ""


def _fa(n):
    return str(n).translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹"))


def evaluate(rep: dict) -> Verdict:
    """گزارشِ caps["instai"] ⇒ حکم. تابعِ خالص (آزمونِ واحد دارد)."""
    state = rep.get("state") or ""
    ver = rep.get("version") or "؟"
    msg = (rep.get("message_fa") or "").strip()
    if state == "not_found":
        return Verdict.skipped(msg or "پوشهٔ InstAI روی این رایانه پیدا نشد؛ اگر جای دیگری است NM_INSTAI_DIR را برای عامل بگذارید")
    if state == "disabled":
        return Verdict.skipped(msg or "همگام‌سازی خودکارِ InstAI خاموش است")
    if state == "updating":
        return Verdict.waiting("InstAI در حالِ به‌روزرسانی است (نسخهٔ %s) ..." % ver)
    if state == "starting":
        return Verdict.waiting("InstAI روشن شده و بسته‌های خودش را آماده می‌کند (نسخهٔ %s)؛ بارِ اول چند دقیقه" % ver)
    if state == "waiting_running":
        old = "" if rep.get("has_updater") else " (پوشه قدیمی است و خودش را به‌روز نمی‌کند)"
        return Verdict.passed("InstAI نسخهٔ %s روشن است%s" % (ver, old),
                              warning="نسخهٔ تازه‌تر روی GitHub هست (%s)؛ وقتی InstAI خاموش شود (STOP.bat) یا دوباره روشن شود خودکار نصب می‌شود" % (rep.get("github") or "؟"))
    if state == "failed":
        last = rep.get("last_update") or {}
        return Verdict.failed("به‌روزرسانیِ خودکارِ InstAI شکست خورد: %s (خودش دوباره تلاش می‌کند)" % ((last.get("tail") or msg or "بدونِ پیام")[-300:]))
    if state == "current":
        return Verdict.failed("InstAI نسخهٔ %s به‌روز است ولی روشن نیست؛ عامل بارِ اولِ بالا آمدنِ گره آن را روشن می‌کند و این بار بالا نیامد (START.bat را در پوشهٔ InstAI یک بار اجرا کنید و data\\logs را ببینید)" % ver)
    if state != "ok":
        return Verdict.waiting("وضعیتِ InstAI هنوز معلوم نیست (%s)" % (state or "بدون گزارش"))
    st = rep.get("selftest")
    head = "InstAI نسخهٔ %s روشن است و به‌روز" % ver
    if not isinstance(st, dict):
        return Verdict.waiting(head + "؛ آزمونِ خودکارِ خودش هنوز اجرا نشده (چند دقیقه بعد از روشن شدن خودش اجرا می‌شود)")
    n = lambda k: _fa(st.get(k) or 0)  # noqa: E731
    counts = "%s سالم، %s هشدار، %s خطا، %s منتظر" % (n("ok"), n("warn"), n("fail"), n("pending"))
    if (st.get("fail") or 0) > 0:
        return Verdict.failed("%s؛ آزمونِ خودکارِ InstAI خطا دارد (%s): %s" % (head, "، ".join(st.get("failing") or []) or "؟", counts))
    extra = {"selftest": {k: st.get(k) for k in ("state", "ok", "warn", "fail", "pending", "waiting", "warning")}}
    warn = ""
    if (st.get("pending") or 0) > 0:
        warn = "این بررسی‌های InstAI هنوز منتظرند: %s" % "، ".join(st.get("waiting") or [])
    elif (st.get("warn") or 0) > 0:
        warn = "این بررسی‌های InstAI هشدار دارند: %s" % "، ".join(st.get("warning") or [])
    return Verdict.passed("%s؛ آزمونِ خودکارِ خودش: %s" % (head, counts), warning=warn, extra=extra)


def virtual(ctx):
    return evaluate((ctx.caps or {}).get("instai") or {})


register(SelfTest(key="instai", label="InstAI روی این رایانه: به‌روز، روشن و آزمونِ خودکارِ خودش", group="system", virtual=virtual, available=_available,
                  optional=True, order=62, min_agent=MIN_AGENT, wait_install_s=45 * 60,
                  describe="عامل پوشهٔ InstAI را پیدا و (در صورتِ قدیمی بودن) به‌روز و روشن می‌کند و گزارشِ خودآزمونِ InstAI را می‌فرستد"))
