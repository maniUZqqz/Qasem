"""Persian sentences for the numbers: «چرا ترند است» for a topic and for a post. Pure functions."""
from __future__ import annotations

from . import textproc

_FA = str.maketrans("0123456789.", "۰۱۲۳۴۵۶۷۸۹٫")
FORMAT_FA = {"reel": "ریلز", "carousel": "کاروسل (چنداسلایدی)", "photo": "عکس", "video": "ویدیو"}
FORMAT_VERB = {"reel": "یک ریلز", "carousel": "یک کاروسل", "photo": "یک پستِ عکس", "video": "یک ویدیو"}


def fa(n) -> str:
    return str(n).translate(_FA)


def num(x, digits: int = 1) -> str:
    """۳٫۲ — a number with a Persian decimal point, no trailing zero."""
    try:
        v = float(x)
    except (TypeError, ValueError):
        return "—"
    if v >= 100:
        return fa(int(round(v)))
    text = ("%.*f" % (digits, v)).rstrip("0").rstrip(".")
    return fa(text)


def compact(n) -> str:
    """۱٫۲ هزار / ۳ میلیون."""
    try:
        v = float(n)
    except (TypeError, ValueError):
        return "—"
    if v >= 1_000_000:
        return num(v / 1_000_000) + " میلیون"
    if v >= 1_000:
        return num(v / 1_000) + " هزار"
    return fa(int(v))


def age_text(hours: float) -> str:
    if hours < 1:
        return "کمتر از یک ساعت"
    if hours < 48:
        return fa(int(round(hours))) + " ساعت"
    return fa(int(round(hours / 24))) + " روز"


def why_cluster(c: dict) -> list[str]:
    """Short reasons, most important first."""
    out = []
    n, a = c.get("size", 0), c.get("accounts_count", 0)
    if c.get("kind") == "breakout":
        out.append("یک پست که تعاملش %s برابرِ حدِ معمولِ همان صفحه است" % num(c.get("best_ratio")))
    else:
        out.append("%s پست از %s صفحه دربارهٔ این موضوع منتشر شده" % (fa(n), fa(a)))
        if a >= 2:
            out.append("چند صفحهٔ مستقل هم‌زمان همین موضوع را ساخته‌اند، پس تکرارِ یک صفحه نیست")
        if c.get("median_ratio", 0) >= 1.2:
            out.append("تعاملِ پست‌ها به‌طورِ میانه %s برابرِ حدِ معمولِ همان صفحه‌هاست (بهترینشان %s برابر)" % (num(c["median_ratio"]), num(c["best_ratio"])))
        elif c.get("best_ratio", 0) >= 2:
            out.append("بهترین پستش %s برابرِ حدِ معمولِ صفحه‌اش تعامل گرفته" % num(c["best_ratio"]))
    if c.get("recent_share", 0) >= 0.5:
        out.append("%s از %s پست در ۷۲ ساعتِ اخیر آمده؛ موضوع تازه است" % (fa(c.get("recent", 0)), fa(n)))
    fm = c.get("formats") or {}
    if fm:
        top = max(fm, key=lambda k: fm[k])
        if fm[top] >= max(2, n // 2):
            out.append("بیشترشان %s هستند" % FORMAT_FA.get(top, top))
    if c.get("audio"):
        a0 = c["audio"][0]
        if a0.get("uses", 0) >= 2:
            out.append("آهنگِ «%s» در %s پست استفاده شده" % (a0.get("title", ""), fa(a0["uses"])))
    if c.get("in_niche"):
        out.append("با واژه‌های دیده‌بانیِ شما هم‌خوان است")
    return out


def why_post(e: dict) -> str:
    """One line from a post's scoring numbers (IgPost.explain)."""
    bits = []
    if e.get("ratio", 0) >= 1.2:
        bits.append("تعاملش %s برابرِ حدِ معمولِ صفحه (پس از %s)" % (num(e["ratio"]), age_text(e.get("age_h", 0))))
    elif e.get("ratio") is not None:
        bits.append("تعاملش در حدِ معمولِ صفحه است")
    if e.get("growth") and e["growth"] >= 1.5:
        bits.append("و الان سریع‌تر از قبل رشد می‌کند (%s برابر)" % num(e["growth"]))
    if e.get("reach_bonus", 0) >= 0.05:
        bits.append("بیشتر از دنبال‌کننده‌های صفحه دیده شده")
    return " ".join(bits)


def hook_label(kind: str) -> str:
    return textproc.HOOK_TYPES.get(kind, "جمله‌ی خبری")
