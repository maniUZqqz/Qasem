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
    from apps.projects.builder import c21_crawl, c21st
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
    out = c21_crawl.run_turn(detail_limit=150, max_seconds=240.0)
    needs_node = c21_crawl.needs_node(out)
    if needs_node:
        # سرور ما را نمی‌پذیرد (۴۰۳)، به 21st.dev نمی‌رسد (robots.txt خوانده نشد) یا چند نوبتِ پشت‌سرِ هم هیچ پیشرفتی نکرد (مسیرِ شبکهٔ ایران): همین کار را
        # گرهٔ GPU با مرورگرِ بی‌سر می‌کند (کارِ crawl21.run؛ گرهٔ خاموش ⇒ در صفِ ماندگار می‌ماند و با روشن‌شدنِ گره خودکار شروع می‌شود؛ نوبتِ بعدیِ سرور هم برنامه‌ریزی می‌شود)
        from apps.projects.builder import c21_node
        c21_node.enqueue_batch()
    if out.get('blocked'):
        pass
    elif not out.get('finished'):
        # پیشرفت داریم ⇒ نوبتِ بعدی ۳۰ ثانیه دیگر؛ robots.txt خوانده نشد یا نوبتِ بی‌پیشرفت (اینترنتِ ایران لنگید) ⇒ ده دقیقه صبر
        c21st_refresh.apply_async(kwargs={'force': True}, countdown=600 if needs_node else 30)
    else:
        c21_convert.apply_async(countdown=20)                      # کاتالوگ کامل شد ⇒ تبدیلِ قطعه‌های قابلِ درج
    return {'total': out.get('total'), 'remaining': out.get('remaining'), 'finished': out.get('finished'), 'blocked': out.get('blocked'),
            'progress': out.get('turn_progress'), 'node': needs_node}


@shared_task(name='apps.projects.tasks.c21_node_collect', ignore_result=True)
def c21_node_collect():
    """نتیجهٔ کارهای crawl21.run (خزشِ گرهٔ GPU) را می‌خواند و می‌ریزد توی کاتالوگ؛ چیزی در انتظار نباشد هیچ‌کاری نمی‌کند."""
    from apps.projects.builder import c21_crawl, c21_node, c21st
    out = c21_node.collect() if c21_node.state().get('pending') else {'pending': 0}
    # مسیرِ گره همان‌وقت که فعال است (سرور مسدود شده یا به 21st.dev نمی‌رسد) خودش را پر نگه می‌دارد: نتیجه جمع شد ⇒ دستهٔ بعدی (۲۵ قطعه، تا ۴ کارِ هم‌زمان) تا کاتالوگ تمام شود
    st = c21st.crawl_state()
    if c21_crawl.needs_node(st):
        job = c21_node.enqueue_batch()
        if job is not None:
            out = dict(out, refilled=str(job.uid))
    return out


@shared_task(name='apps.projects.tasks.c21_convert', ignore_result=True)
def c21_convert(force=False):
    """قطعه‌های با مجوزِ آزادِ کتابخانه‌هایی که مخزنِ عمومی دارند را به قطعهٔ قابلِ درج تبدیل می‌کند (نوبتی؛ تمام نشد خودش را دوباره صدا می‌زند).
    خودکار: هر شش ساعت یک نوبت؛ دستی: سایت‌ساز ⇒ قطعه‌ها ⇒ «کاتالوگِ 21st.dev» ⇒ «تبدیلِ قطعه‌ها»."""
    from apps.projects.builder import c21_convert as CV, c21_crawl, c21_pipeline, c21_rtl
    try:                                                       # دسته‌های تازه (۱۲۲ قطعه بی‌دسته بود) و سطرِ درستِ حقِ نشر (Apache)؛ ارزان و بی‌اثر روی رکوردهای درست
        c21_crawl.recategorize_catalog()
        CV.recategorize_records()
        CV.repair_attribution()
    except Exception as exc:                                   # noqa: BLE001 - نگهداریِ داده هرگز تبدیل را نمی‌خوابانَد
        import logging
        logging.getLogger(__name__).warning('c21 maintenance: %s', exc)
    recheck = {}
    try:                                                       # قطعه‌هایی که با سنجشِ قدیمی (بدونِ «خالی‌بودنِ ایستا») تأیید شده‌اند خودکار دوباره سنجیده می‌شوند
        recheck = c21_rtl.recheck_outdated(limit=50)
    except Exception as exc:                                   # noqa: BLE001 - سنجش اختیاری است
        recheck = {'error': str(exc)[:100]}
    out = c21_pipeline.run(max_seconds=840.0, libs_limit=4)
    if (out.get('remaining_libs') and out.get('converted', 0) + out.get('failed', 0) + out.get('no_source', 0) > 0) or (recheck.get('left') or 0) > 0:
        c21_convert.apply_async(countdown=60)
    return {**{k: out.get(k) for k in ('converted', 'failed', 'no_source', 'libs_done', 'remaining_libs', 'converted_total')}, 'rechecked': recheck.get('checked'), 'recheck_left': recheck.get('left')}
