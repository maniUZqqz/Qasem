"""آزمونِ «صداهای چغر خودشان ساخته می‌شوند؟» — پیوندِ قراردادِ `docs/selftests/chagher-content.md`.

صداهای گویندگیِ MOSS فروشگاهِ «چغر» (شناسهٔ ۳۴) که تا روشن‌شدنِ سرورِ پردازش در صف مانده‌اند یا با خطای قدیمیِ «BFloat16»
ناموفق شده بودند باید بی‌هیچ کلیکی ساخته شوند: کارِ زمان‌بندی‌شدهٔ `audio-retry-stale-failed` (هر ۵ دقیقه) ردیف‌های منتظر را با
نتیجهٔ کارشان به‌روز می‌کند و ناموفق‌های قدیمی را یک بار دوباره می‌سازد. این آزمون (بی کارِ تازه) نتیجه را می‌سنجد:
تا ۳۰ دقیقه پس از شروع «در انتظار» می‌ماند و بعد از آن اگر چیزی هنوز در صف باشد یا دوباره‌ساخته‌شده باز ناموفق شده باشد، رد می‌شود."""
from __future__ import annotations

from datetime import timedelta

from django.utils import timezone

from . import SelfTest, Verdict, register

STORE_ID = 34
WAIT_S = 30 * 60
RECENT_DAYS = 45


def virtual(ctx):
    from apps.ai.models import AudioAsset

    now = timezone.now()
    rows = AudioAsset.objects.filter(store_id=STORE_ID, kind=AudioAsset.Kind.SPEECH, engine="moss-fa",
                                     created_at__gt=now - timedelta(days=RECENT_DAYS))
    total = rows.count()
    if not total:
        return Verdict.passed("صدای MOSS برای چغر در کتابخانه نیست", extra={"takes": 0})
    ready = rows.filter(status=AudioAsset.Status.READY).count()
    waiting = rows.filter(status__in=[AudioAsset.Status.PENDING, AudioAsset.Status.RUNNING]).count()
    failed = list(rows.filter(status=AudioAsset.Status.FAILED))
    again = [a for a in failed if (a.params or {}).get("auto_retried")]
    old_bug = [a for a in failed if "bfloat16" in (a.error or "").lower() and not (a.params or {}).get("auto_retried")]
    extra = {"takes": total, "ready": ready, "waiting": waiting, "failed": len(failed), "again_failed": len(again)}
    if again:
        a = again[0]
        return Verdict.failed("%d صدای چغر بعد از «دوباره‌سازیِ خودکار» باز ناموفق شد؛ نمونه (شمارهٔ %d): %s" % (len(again), a.pk, (a.error or "—")[:160]),
                              extra=extra)
    started = ctx.result.started_at if ctx.result is not None and ctx.result.started_at else now
    young = (now - started).total_seconds() < WAIT_S
    if waiting or old_bug:
        why = "%d صدا هنوز در صف/در حالِ ساخت و %d صدای ناموفقِ قدیمی در انتظارِ دوباره‌سازیِ خودکار" % (waiting, len(old_bug))
        return Verdict.waiting(why, extra=extra) if young else Verdict.failed(why + " (بیش از %d دقیقه پس از شروع)" % (WAIT_S // 60), extra=extra)
    if failed:
        return Verdict.passed("%d صدا آماده؛ %d ناموفق با دلیلی غیر از خطای قدیمی (با «دوباره بساز» ساخته می‌شود)" % (ready, len(failed)), extra=extra)
    return Verdict.passed("همهٔ %d صدای MOSS چغر آماده است" % ready, extra=extra)


register(SelfTest(key="chagher_audio", label="صداهای چغر خودشان ساخته می‌شوند", group="audio", virtual=virtual, optional=True, order=96,
                  wait_install_s=WAIT_S + 120, describe="بدونِ کلیک: صداهای منتظر یا ناموفقِ قدیمیِ چغر با روشن‌شدنِ سرور ساخته می‌شوند"))
