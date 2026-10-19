"""Background crawl of a competitor's site.

Registered through ``apps.ai.tasks`` (which imports this module) so the worker
knows it. Its name is ``apps.ai.competitor_tasks.*``, which the ``apps.ai.tasks.*``
route does not match, so it runs on the default ``celery`` queue: a crawl is
network-bound and should not wait behind GPU work on the ``ai`` queue.
"""
import logging

from celery import shared_task

from apps.jobs.models import Job

logger = logging.getLogger(__name__)

JOB_KIND = "competitor_crawl"


@shared_task(bind=True)
def crawl_competitor_task(self, job_id, competitor_id, max_pages=30):
    from services.research import shop_crawler

    from . import competitor_research
    from .competitor_models import Competitor

    job = Job.objects.get(id=job_id)
    try:
        competitor = Competitor.objects.select_related("store").get(id=competitor_id)
        job.total_steps = int(max_pages)
        job.mark_running(f"کرالِ {competitor.website}")

        def progress(done, total, label):
            job.mark_progress(done, f"{done} از حداکثر {total} محصول — {label}"[:200])

        report = shop_crawler.crawl(
            competitor.website, max_pages=max_pages, progress=progress,
            should_stop=job.cancel_pending,
        )
        saved = competitor_research.save_crawl(competitor, report.products)
        job.mark_progress(len(report.products), "سنجشِ «رقیب کالایی» با محصولاتِ شما")
        verdict = competitor_research.match_competitor(competitor, use_llm=True, job=job)
        job.mark_completed({
            "kind": JOB_KIND,
            "competitor_id": competitor.id,
            "crawl": report.as_dict(),
            "saved": saved,
            "verdict": verdict,
        })
    except Exception as exc:  # noqa: BLE001 — the panel shows the reason
        logger.exception("Competitor crawl %s failed", competitor_id)
        job.mark_failed(str(exc))
