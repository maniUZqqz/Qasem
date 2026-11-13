"""آزمونِ «همه‌چیزِ لازم خودکار نصب شد؟» — فهرستِ نیازمندی‌های هر ویژگی (requirements.d) روی گره: آماده / در حالِ نصب / ناموفق."""
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from . import BOOT_ABSENT_S, BOOT_MIN_AGENT, YOUNG_AGENT_S, SelfTest, Verdict, agent_age_s, bootstrap_features, register

STATE_FA = {"ready": "آماده", "installing": "در حال نصب", "waiting": "منتظر", "failed": "ناموفق", "skipped": "لازم نیست"}


def virtual(ctx):
    """«همه‌چیز خودکار نصب شد؟» — هرگز بی‌گزارشِ عامل قبول نمی‌شود: عاملی که تازه بالا آمده نصبش را حدودِ یک دقیقه بعد شروع و
    گزارش می‌کند؛ تا آن موقع (و تا وقتی ویژگی‌ای در حالِ نصب است) «منتظر» می‌ماند، نه «قبول»."""
    caps = ctx.caps
    boot = caps.get("bootstrap")
    feats = bootstrap_features(caps)
    now = timezone.now()
    extra = dict((ctx.result.extra if ctx.result else None) or {})
    if feats is None:
        if isinstance(boot, dict) and boot.get("error"):
            return Verdict.failed("نصبِ خودکار روی سرور خطا داد: %s" % boot["error"])
        if isinstance(boot, dict):                    # گزارش هست ولی فهرستِ نیازمندی‌ها خالی است
            errs = boot.get("errors") or []
            return Verdict.failed("فهرستِ نیازمندی‌های سرور (requirements.d) خالی یا خراب است%s" % (
                (": " + "؛ ".join(str(e) for e in errs)[:300]) if errs else ""))
        since = parse_datetime(extra.get("absent_since") or "") if extra.get("absent_since") else None
        since = since or now
        extra["absent_since"] = since.isoformat()
        age = agent_age_s(caps)
        if (now - since).total_seconds() > BOOT_ABSENT_S and (age is None or age > BOOT_ABSENT_S):
            return Verdict.failed("عاملِ این سرور نصبِ خودکار را راه نینداخت: تا %d دقیقه بعد از شروع هیچ گزارشی نداد (bootstrap.py در بستهٔ "
                                  "گره هست؟ لاگِ عامل را ببینید)." % (BOOT_ABSENT_S // 60), extra=extra)
        return Verdict.waiting("عاملِ سرور تازه بالا آمده و نصبِ خودکار را هنوز شروع/گزارش نکرده (حدودِ یک دقیقه) ...", extra=extra)
    age = agent_age_s(caps)
    failed = {k: f for k, f in feats.items() if f.get("state") == "failed"}
    busy = {k: f for k, f in feats.items() if f.get("state") in ("installing", "waiting")}
    if failed:
        lines = []
        for k, f in failed.items():
            bad = next((i for i in f.get("items", []) if i.get("state") == "failed"), {})
            lines.append("%s: %s" % (f.get("title") or k, bad.get("error") or "ناموفق"))
        return Verdict.failed("نصبِ این‌ها شکست خورد (دکمهٔ «تلاش دوباره»): " + "؛ ".join(lines)[:600], extra={"features": list(failed)})
    if busy:
        return Verdict.waiting("در حالِ نصب: " + "، ".join(f.get("title") or k for k, f in busy.items()))
    if age is not None and age < YOUNG_AGENT_S:
        return Verdict.waiting("عاملِ سرور تازه بالا آمده؛ منتظرِ پایانِ بررسیِ نصب‌ها ...")
    ready = [f.get("title") or k for k, f in feats.items() if f.get("state") == "ready"]
    return Verdict.passed("%d ویژگی آماده: %s" % (len(ready), "، ".join(ready)[:300]))


register(SelfTest(key="bootstrap", label="نصبِ خودکارِ نیازمندی‌ها (پایتون، ffmpeg، Node.js، مدل‌ها)", group="system", virtual=virtual, order=8,
                  wait_install_s=6 * 3600, min_agent=BOOT_MIN_AGENT, describe="هر ویژگی فایلِ requirements.d خودش را دارد؛ عامل همه را در پس‌زمینه نصب می‌کند"))
