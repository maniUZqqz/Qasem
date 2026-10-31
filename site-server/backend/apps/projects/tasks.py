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
