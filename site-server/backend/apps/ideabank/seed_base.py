"""سازندهٔ ایده‌های آمادهٔ بانکِ ایده (فایل‌های ``seeds_*.py``).

SOURCE: شکلِ ``idea()`` / ``bundle()`` از InstAI:instai/ideabank/seed_base.py @ 2f8aa90 گرفته شده؛ ایده‌ها همه تازه و فارسی‌اند.

هر ایده: عنوان، یک‌جمله‌ای (logline)، قلاب (جملهٔ اولِ محتوا)، «چه چیزی فیلم/عکس بگیریم»، دعوت به اقدام (CTA)، قالبِ بهتر (ریلز/کاروسل/عکس/استوری)
و کانال. جای‌گیرهای ``{محصول} {فروشگاه} {مخاطب} {حوزه}`` از پروفایلِ فروشگاه پر می‌شوند؛ ``[...]`` یعنی «اینجا دادهٔ واقعیِ فروشگاه بنویسید».

قاعدهٔ سخت: هیچ عدد، قیمت، درصد، آمار، نتیجه یا نقلِ قولِ ساختگی در ایده نیست (آزمونِ ``tests_seeds`` هر ایده را می‌سنجد).
"""
from __future__ import annotations

from .catalog import CATEGORIES


def idea(key, fmt, channel, tags, title, logline, hook, shoot, cta, *, occasion=None):
    """یک ایدهٔ آماده. ``occasion`` = (ماهِ شمسی، روزِ شمسی، نامِ مناسبت) فقط برای مناسبت‌های ثابتِ تقویمِ شمسی."""
    data = {
        "category": "", "format": fmt, "channel": channel, "tags": list(tags), "title": title, "logline": logline, "hook": hook,
        "shoot": shoot, "cta": cta, "occasion": None,
    }
    if occasion:
        month, day, name = occasion
        data["occasion"] = {"month": month, "day": day, "name": name}
    return key, data


def bundle(category: str, rows: list[tuple[str, dict]]) -> list[tuple[str, dict]]:
    """دسته را روی هر ایده می‌زند و کلید را پیشوند می‌دهد تا در کلِ بانک یکتا باشد."""
    assert category in CATEGORIES, category
    out = []
    for k, d in rows:
        out.append((f"{category}_{k}", {**d, "category": category}))
    return out
