"""آزمونِ «ماسکوتِ برند» — قراردادِ `docs/selftests/mascot.md` (همیشه روشن؛ به گره نیاز ندارد).

شخصیتِ «مربیِ چغر» (رنگ‌های برندِ چغر، لوگوی ساختگی) در همهٔ ژست‌ها × چهار اندازه روی پردازنده کشیده می‌شود؛ شخصیت باید در هر قاب دیده شود و همهٔ رنگ‌های
امضایش (کلیدِ رنگ) در آن باشد. هیچ مدل، گره یا هوش مصنوعی لازم نیست؛ پس حتی وقتی گرهٔ پردازش خاموش است و متیس اعتبار ندارد کار می‌کند.
اگر این نسخه `apps.mascot` را ندارد، چیزی ثبت نمی‌شود و هیچ خطایی نمی‌آید (دو وصله مستقل‌اند)."""
from __future__ import annotations

try:  # pragma: no cover — بسته به این‌که وصلهٔ ماسکوت اعمال شده باشد
    from apps.mascot import selftest as _mascot
except Exception:  # noqa: BLE001
    _mascot = None

from . import SelfTest, Verdict, register


def virtual(ctx) -> Verdict:
    res = _mascot.run()
    if res["ok"]:
        return Verdict.passed("%d ژست × %d اندازه = %d تصویر روی پردازنده (%s ثانیه): شخصیت همه‌جا دیده شد و همهٔ رنگ‌های امضا بود؛ بدونِ GPU و بدونِ هوش مصنوعی"
                              % (res["poses"], res["sizes"], res["total"], res["seconds"]), device="cpu")
    bad = res["failed"][0]
    return Verdict.failed("%d از %d تصویر رد شد؛ نمونه: ژستِ «%s» در اندازهٔ «%s»: %s" % (len(res["failed"]), res["total"], bad["pose"], bad["size"], "؛ ".join(bad["notes"])), device="cpu")


if _mascot is not None:
    register(SelfTest(key="mascot_render", label="ماسکوتِ برند: شخصیت در همهٔ ژست‌ها و اندازه‌ها یکی است", group="system", virtual=virtual, optional=True, order=97,
                      describe="بی‌گره و بدونِ هوش مصنوعی: ۲۹ ژست × ۴ اندازه روی پردازنده؛ شخصیت خالی نیست و رنگ‌های امضایش (کلیدِ رنگ) دیده می‌شوند"))
