"""آزمونِ «کارهای GPUِ برنامهٔ بازاریابی خودشان اجرا می‌شوند؟» — بدونِ کارِ تازه.

«برنامهٔ بازاریابی» (apps/mktplan) کارهای سرورِ پردازش (تصویرِ FLUX، موشن، گوینده با لایهٔ تلفظ، موسیقی، ویدیو از ارائه، خواندنِ ترند، تصویرِ
شخصیت) را در صفِ ماندگار می‌گذارد. وقتی سرور روشن شد باید خودشان اجرا شوند و وضعیتِ هر کارِ برنامه خودکار «آماده» شود. این آزمون
(بی کارِ تازه) همان را می‌سنجد: یک تیکِ همگام‌سازی می‌زند، بعد

  * کارِ ناموفقِ برنامه ⇒ رد (با نامِ کار و دلیل)،
  * کارِ GPU هنوز «منتظرِ سرور» ⇒ تا ۴۵ دقیقه پس از شروعِ اجرا «در انتظار»، بعدش رد،
  * وگرنه ⇒ قبول.

اگر هیچ برنامه‌ای ثبت نشده باشد قبول است (چیزی برای سنجیدن نیست).
"""
from __future__ import annotations

from django.utils import timezone

from . import SelfTest, Verdict, register

WAIT_S = 45 * 60


def virtual(ctx):
    from apps.mktplan import runner
    from apps.mktplan.models import MarketingPlan, PlanItem

    plans = list(MarketingPlan.objects.filter(autorun=True).select_related("store"))
    if not plans:
        return Verdict.passed("برنامهٔ بازاریابی‌ای ثبت نشده است", extra={"plans": 0})
    try:
        runner.tick()                                         # همگام‌سازیِ وضعیت + پیش‌بردنِ کارهای منتظر (سبک؛ بدونِ GPU)
    except Exception as exc:  # noqa: BLE001
        return Verdict.failed(f"تیکِ برنامهٔ بازاریابی خطا داد: {exc}"[:300])
    S = PlanItem.Status
    items = list(PlanItem.objects.filter(plan__in=plans, decision="").select_related("plan"))
    failed = [i for i in items if i.status == S.FAILED]
    waiting = [i for i in items if i.status == S.WAITING_NODE and i.needs_node]
    extra = {"plans": len(plans), "items": len(items), "failed": len(failed), "waiting_node": len(waiting)}
    if failed:
        i = failed[0]
        return Verdict.failed("%d کارِ برنامه ناموفق است؛ نمونه «%s»: %s" % (len(failed), i.title[:60], (i.message or i.last_error or "—")[:140]), extra=extra)
    if waiting:
        started = ctx.result.started_at if ctx.result is not None and ctx.result.started_at else timezone.now()
        why = "%d کارِ GPUِ برنامه هنوز منتظرِ سرور است (با روشن‌شدنِ گره یکی‌یکی اجرا می‌شوند)" % len(waiting)
        if (timezone.now() - started).total_seconds() < WAIT_S:
            return Verdict.waiting(why, extra=extra)
        return Verdict.failed(why + " — بیش از %d دقیقه پس از شروعِ اجرا" % (WAIT_S // 60), extra=extra)
    return Verdict.passed("همهٔ %d کارِ برنامهٔ بازاریابی یا آماده‌اند یا پیش‌نویس (کارِ GPUِ منتظر نیست)" % len(items), extra=extra)


register(SelfTest(key="mktplan", label="کارهای GPUِ برنامهٔ بازاریابی خودشان اجرا می‌شوند", group="system", virtual=virtual, optional=True, order=97,
                  wait_install_s=WAIT_S + 120,
                  describe="بدونِ کلیک: تصویر، موشن، گوینده، موسیقی و ویدیوی برنامهٔ بازاریابی با روشن‌شدنِ سرور ساخته و وضعیتشان «آماده» می‌شود"))
