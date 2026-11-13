"""آزمونِ مقاومت در برابرِ قطعِ اینترنت: نتیجه‌های در انتظارِ ارسال (outbox) و وضعیتِ خطِ گره به سایت، و راهروی سبک."""
from . import SelfTest, Verdict, register


def virtual(ctx):
    caps = ctx.caps
    if not isinstance(caps.get("outbox"), dict):
        return Verdict.failed("عاملِ این سرور صندوقِ ارسالِ مقاوم را ندارد (۲٫۱۱ به بعد لازم است).")
    pending = int(caps["outbox"].get("pending") or 0)
    net = caps.get("net") or {}
    lanes = caps.get("lanes") or {}
    parts = ["راهروی سبک: %s" % ("فعال" if lanes.get("light") else "ندارد")]
    if pending:
        parts.append("%d نتیجه در انتظارِ رسیدنِ خط" % pending)
    if net.get("offline_s"):
        return Verdict.failed("خطِ این سرور به سایت قطع است (%d ثانیه؛ %s) — نتیجه‌ها روی خودِ سرور می‌مانند و وصل شد می‌رسند." % (
            net["offline_s"], net.get("last_error") or ""), extra={"pending": pending})
    return Verdict.passed("، ".join(parts) + " · نتیجه‌ها گم نمی‌شوند", extra={"pending": pending})


register(SelfTest(key="net", label="مقاومت در برابر قطعِ اینترنت و راهروی سبک", group="system", virtual=virtual, order=9,
                  describe="نتیجهٔ کارِ تمام‌شده تا رسیدن به سایت روی سرور می‌ماند"))
