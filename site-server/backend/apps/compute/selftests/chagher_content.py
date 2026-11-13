"""آزمونِ «محتوای چغر خودش رها می‌شود؟» — پیوندِ قراردادِ `docs/selftests/chagher-content.md`.

فروشگاهِ «چغر» (شناسهٔ ۳۴) سیاستِ «فقط لوکال» دارد؛ کارهایش تا روشن شدنِ سرورِ پردازش در صفِ «منتظرِ گره» (wait.node) می‌مانند.
وقتی سرور روشن شد باید خودشان رها شوند و بی‌هیچ کلیکی اجرا شوند. این آزمون (بی کارِ تازه) می‌سنجد: تا ۲۰ دقیقه پس از شروعِ اجرا
هیچ کارِ منتظرِ چغر نباید در صف بماند، و خطای «dtype» ِ گویندگیِ MOSS نباید برگشته باشد."""
from __future__ import annotations

from datetime import timedelta

from django.utils import timezone

from . import SelfTest, Verdict, register

STORE_ID = 34
WAIT_S = 20 * 60


def virtual(ctx):
    from ..models import ComputeJob
    from ..park import PARK_KIND

    now = timezone.now()
    parked = ComputeJob.objects.filter(kind=PARK_KIND, state=ComputeJob.State.QUEUED, store_id=STORE_ID).count()
    bad = ComputeJob.objects.filter(store_id=STORE_ID, state=ComputeJob.State.FAILED, finished_at__gte=now - timedelta(hours=24),
                                    error__icontains="same dtype").count()
    if bad:
        return Verdict.failed("%d کارِ چغر با خطای «dtype» (گویندگیِ MOSS) ناموفق شد؛ این خطا باید رفع شده باشد." % bad)
    if not parked:
        return Verdict.passed("کارِ منتظری برای چغر در صف نیست", extra={"parked": 0})
    started = ctx.result.started_at if ctx.result is not None and ctx.result.started_at else now
    if (now - started).total_seconds() < WAIT_S:
        return Verdict.waiting("%d کارِ چغر هنوز منتظرِ بیدار شدن است (هر دقیقه چند تا رها می‌شود)" % parked, extra={"parked": parked})
    return Verdict.failed("%d کارِ چغر بیش از %d دقیقه پس از روشن شدنِ سرور هنوز «منتظرِ گره» است." % (parked, WAIT_S // 60),
                          extra={"parked": parked})


register(SelfTest(key="chagher_content", label="کارهای منتظرِ چغر خودشان رها می‌شوند", group="system", virtual=virtual, optional=True, order=95,
                  wait_install_s=WAIT_S + 120, describe="بدونِ کلیک: کارهای «فقط لوکالِ» چغر که منتظرِ سرور بودند اجرا می‌شوند"))
