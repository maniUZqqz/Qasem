"""آزمونِ «درخواست‌های هوش مصنوعیِ صف‌دار خودشان اجرا می‌شوند؟» — پیوندِ قراردادِ `docs/selftests/ai-queue.md`.

وقتی گره خاموش و متیس بی‌اعتبار بود، درخواست‌های متنیِ ویژگی‌ها (پیش‌نویسِ شخصیت، ایده‌ها، ایدهٔ تامنیل، «توصیف کن، بساز»، اسلاید، پیامِ مشتری‌یاب، ترجمهٔ 21st)
«در صف تا روشن شدنِ سرورِ پردازش» ماندند (apps.compute.deferred). این آزمون (بی کارِ تازه) می‌سنجد: پس از روشن شدنِ گره
  * هیچ درخواستی بیش از ۲۰ دقیقه بی‌حرکت در صف نماند (هر دقیقه یکی بیدار می‌شود، پس چند درخواست زمان می‌خواهند)،
  * درخواستی که چند بار «هنوز AI در دسترس نبود» گفت و گره روشن است گزارش شود (مثلاً مدلِ متنی روی گره نصب نیست)،
  * و مسیر درست است: گرهٔ روشنِ دارای Ollama ⇒ `ai_ready` بله.
"""
from __future__ import annotations

from django.utils import timezone

from . import SelfTest, Verdict, register

WAIT_S = 20 * 60
MAX_ATTEMPTS = 4


def virtual(ctx):
    from .. import deferred, services as SV

    rows = deferred.pending_rows()
    now = timezone.now()
    done = deferred.recent_done_count()
    if not rows:
        return Verdict.passed("درخواستِ صف‌داری نمانده است%s" % ((" (%d درخواستِ صف‌شده با هوش مصنوعی تمام شد)" % done) if done else ""), extra={"pending": 0, "done": done})
    ready, how = deferred.ai_ready()
    if not ready:
        return Verdict.waiting("%d درخواست در صف است و هیچ مسیرِ هوش مصنوعی (گرهٔ روشن یا متیسِ بی‌مدارِ باز) آماده نیست" % len(rows), extra={"pending": len(rows)})
    started = ctx.result.started_at if ctx.result is not None and ctx.result.started_at else now
    young = (now - started).total_seconds() < WAIT_S
    stuck = []
    for ph in rows:
        d = (ph.payload or {}).get("deferred") or {}
        if int(d.get("attempts") or 0) >= MAX_ATTEMPTS:
            stuck.append("%s (%d بار «هنوز در دسترس نبود»: %s)" % ((ph.payload or {}).get("title") or d.get("feature"), int(d.get("attempts") or 0), (d.get("reason") or "")[:120]))
    if stuck and not young:
        return Verdict.failed("هوش مصنوعی آماده است ولی این درخواست‌ها هنوز انجام نمی‌شوند: " + "؛ ".join(stuck[:3]) +
                              ". مدلِ متنیِ گره را بسنجید (آزمونِ «Ollama»).", extra={"pending": len(rows), "stuck": len(stuck)})
    if young or SV.online_nodes("ollama"):
        return Verdict.waiting("%d درخواست در صف است و هر دقیقه یکی اجرا می‌شود (مسیر: %s)" % (len(rows), "گره" if how == "local" else "متیس"), extra={"pending": len(rows)})
    return Verdict.failed("%d درخواستِ صف‌دار بیش از %d دقیقه پس از آماده شدنِ هوش مصنوعی هنوز در صف است." % (len(rows), WAIT_S // 60), extra={"pending": len(rows)})


register(SelfTest(key="ai_queue", label="درخواست‌های هوش مصنوعیِ صف‌دار خودشان اجرا می‌شوند", group="system", virtual=virtual, optional=True, order=96,
                  wait_install_s=WAIT_S + 120, describe="بدونِ کلیک: «در صف تا روشن شدنِ سرورِ پردازش» ها با روشن شدنِ گره (یا برگشتنِ متیس) اجرا می‌شوند"))
