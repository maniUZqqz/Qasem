"""آزمونِ «همه‌چیزِ لازم خودکار نصب شد؟» — فهرستِ نیازمندی‌های هر ویژگی (requirements.d) روی گره: آماده / در حالِ نصب / ناموفق."""
from . import SelfTest, Verdict, register

STATE_FA = {"ready": "آماده", "installing": "در حال نصب", "waiting": "منتظر", "failed": "ناموفق", "skipped": "لازم نیست"}


def virtual(ctx):
    boot = ctx.caps.get("bootstrap")
    if not isinstance(boot, dict) or not boot.get("features"):
        kinds = ctx.caps.get("kinds")
        if isinstance(kinds, list):
            return Verdict.passed("این سرور چیزی برای نصبِ خودکار ندارد")
        return Verdict.failed("عاملِ این سرور هنوز نصبِ خودکار را نمی‌شناسد (۲٫۱۱ به بعد) — «به‌روزرسانی» را بزنید.")
    feats = boot["features"]
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
    ready = [f.get("title") or k for k, f in feats.items() if f.get("state") == "ready"]
    return Verdict.passed("%d ویژگی آماده: %s" % (len(ready), "، ".join(ready)[:300]))


register(SelfTest(key="bootstrap", label="نصبِ خودکارِ نیازمندی‌ها (پایتون، ffmpeg، Node.js، مدل‌ها)", group="system", virtual=virtual, order=8,
                  wait_install_s=6 * 3600, describe="هر ویژگی فایلِ requirements.d خودش را دارد؛ عامل همه را در پس‌زمینه نصب می‌کند"))
