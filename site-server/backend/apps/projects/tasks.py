# -*- coding: utf-8 -*-
"""کارهای پس‌زمینهٔ انتشارِ سایت."""
from celery import shared_task


@shared_task(name='apps.projects.tasks.run_site_job', ignore_result=True)
def run_site_job(job_id):
    from apps.projects.hosting import publisher
    from apps.projects.models import SiteJob
    job = SiteJob.objects.select_related('site', 'site__project').filter(pk=job_id).first()
    if job is not None and job.state == SiteJob.QUEUED:
        publisher.run_job(job)


@shared_task(name='apps.projects.tasks.published_sites_daily', ignore_result=True)
def published_sites_daily():
    from apps.projects.hosting import publisher
    return publisher.daily_maintenance()


@shared_task(name='apps.projects.tasks.c21st_refresh', ignore_result=True)
def c21st_refresh(force=False):
    """کاتالوگِ 21st.dev را (فقط فهرست و جزئیاتِ .md؛ نه کد) به‌روز می‌کند: نوبتی تا ۴ دقیقه، و اگر تمام نشد خودش را دوباره صدا می‌زند.
    خودکار: بار اولِ خالی، و هفته‌ای یک بار. مؤدبانه: ۱٫۲ ثانیه بینِ دو درخواست؛ فقط صفحه‌هایی که robots.txt ِ 21st.dev برای عامل‌ها باز گذاشته."""
    from apps.projects.builder import c21st
    st = c21st.crawl_state()
    rows = c21st.load()
    if not force and rows and st.get('finished'):
        import datetime
        try:
            age = (datetime.datetime.now(datetime.timezone.utc) - datetime.datetime.fromisoformat(st.get('finished_at') or st.get('started_at'))).days
        except (TypeError, ValueError):
            age = 99
        if age < 7:
            return {'skipped': 'fresh'}
    out = c21st.crawl(detail_limit=150, max_seconds=240.0)
    if not out.get('finished'):
        c21st_refresh.apply_async(kwargs={'force': True}, countdown=30)
    return {'total': out.get('total'), 'remaining': out.get('remaining'), 'finished': out.get('finished')}
