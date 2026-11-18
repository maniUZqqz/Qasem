# -*- coding: utf-8 -*-
"""«خودترمیمی» پس از روشن شدنِ سرورِ پردازش (۱۴۰۵/۰۸/۲۸) — کارهایی که کاربر یک بار خواسته بود ولی چیزی دوباره راهشان نمی‌اندازد.

نمونهٔ زنده (آزمونِ «chagher_content»): پنج محصولِ چغر (۱۶ تا ۲۰) تحلیلِ «هوش محصول» را خواسته بودند؛ کارها با «سرور ری‌استارت شد و کار از بین رفت» ناموفق شدند و
هیچ‌چیز دوباره صفشان نکرد ⇒ «هوش محصول» برایشان هرگز پر نمی‌شد. صفِ ماندگار (park.py) فقط کارهایی را نگه می‌دارد که تا همان لحظه زنده بودند.

قاعده (محتاطانه، تا گره با کارِ ناخواسته پر نشود): محصولی که **پیش‌تر دست‌کم یک کارِ تحلیل داشته** (یعنی کسی/چیزی خواسته)، ولی نه تحلیل دارد و نه کارِ زنده،
و در ۱۲ ساعتِ اخیر کمتر از ۲ بار ناموفق شده، وقتی گرهٔ دارایِ Ollama روشن است دوباره صف می‌شود — هر دقیقه حداکثر یکی، و هیچ‌وقت بیش از ۲ تحلیلِ زنده هم‌زمان.
محصولی که هرگز تحلیل نخواسته (فروشگاهِ تازه‌واردِ پر از محصول) به این روش خودکار تحلیل نمی‌شود.
"""
from __future__ import annotations

import logging
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from . import services as SV

logger = logging.getLogger(__name__)

MAX_LIVE = 2
MAX_RECENT_FAILS = 2
FAIL_WINDOW = timedelta(hours=12)


def _live_states():
    from apps.jobs.models import Job

    return (Job.State.QUEUED, Job.State.PROCESSING, Job.State.PREVIEW, Job.State.WAITING_APPROVAL)


def orphaned_products(limit: int = 20) -> list:
    """محصول‌هایی که تحلیل خواسته‌اند ولی نه تحلیل دارند و نه کارِ زنده؛ قدیمی‌ترین درخواست اول."""
    from apps.ai.models import ProductIntelligence
    from apps.jobs.models import Job
    from apps.products.models import Product

    asked: dict[int, int] = {}
    live: set[int] = set()
    now = timezone.now()
    recent_fail: dict[int, int] = {}
    for job in Job.objects.filter(type=Job.Type.PRODUCT_ANALYSIS).only("id", "state", "context", "updated_at").iterator():
        pid = (job.context or {}).get("product_id")
        if not pid:
            continue
        asked.setdefault(int(pid), job.pk)
        if job.state in _live_states():
            live.add(int(pid))
        elif job.state == Job.State.FAILED and job.updated_at and now - job.updated_at <= FAIL_WINDOW:
            recent_fail[int(pid)] = recent_fail.get(int(pid), 0) + 1
    have = set(ProductIntelligence.objects.values_list("product_id", flat=True))
    out = []
    for pid in sorted(asked, key=asked.get):
        if pid in have or pid in live or recent_fail.get(pid, 0) >= MAX_RECENT_FAILS:
            continue
        product = Product.objects.filter(pk=pid, is_available=True).select_related("store").first()
        if product is not None:
            out.append(product)
        if len(out) >= limit:
            break
    return out


def live_count() -> int:
    from apps.jobs.models import Job

    return Job.objects.filter(type=Job.Type.PRODUCT_ANALYSIS, state__in=_live_states()).count()


def requeue_analysis(limit: int = 1) -> int:
    """⇒ چند تحلیل دوباره صف شد. فقط وقتی گرهٔ Ollama روشن است (وگرنه خودِ صفِ ماندگار کار را نگه می‌داشت و دوباره ناموفق نمی‌شد، ولی بی‌دلیل صف را پر نمی‌کنیم)."""
    if getattr(settings, "CELERY_TASK_ALWAYS_EAGER", False):
        return 0                              # بی‌صفِ واقعیِ Celery کار همین‌جا و همین لحظه اجرا می‌شد؛ نه از maintenance
    if not SV.online_nodes("ollama") or live_count() >= MAX_LIVE:
        return 0
    from apps.ai.tasks import analyze_product_task
    from apps.jobs.models import Job
    from apps.jobs.services import dispatch_job

    n = 0
    for product in orphaned_products(limit=limit):
        job = Job.objects.create(store=product.store, type=Job.Type.PRODUCT_ANALYSIS, state=Job.State.QUEUED,
                                 context={"product_id": product.id, "healed": True})
        err = dispatch_job(job, analyze_product_task, job.id, product.id)
        if err is not None:
            logger.warning("heal: could not dispatch the analysis of product %s", product.pk)
            continue
        logger.info("heal: product %s (store %s) had no analysis and no live job - queued job %s", product.pk, product.store_id, job.pk)
        n += 1
        if live_count() >= MAX_LIVE:
            break
    return n


def tick() -> dict:
    out: dict = {}
    try:
        out["analysis"] = requeue_analysis()
    except Exception as exc:  # noqa: BLE001 - ترمیم نباید maintenance را بخواباند
        logger.exception("heal: analysis failed")
        out["analysis_error"] = str(exc)[:200]
    return out
