# -*- coding: utf-8 -*-
"""APIِ انتشار روی اینترنت — زیرِ /api/v1/studio/projects/<slug>/hosting/ . فقط کارمند (مثلِ بقیهٔ سایت‌ساز)."""
import datetime
import re

from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.response import Response

from apps.projects.api import bad, studio_api
from apps.projects.models import Design, Project, PublishedSite, SiteJob
from . import domains, publisher, sysops

STATE_LABEL = {
    PublishedSite.NONE: 'هنوز روی اینترنت نیست', PublishedSite.PUBLISHING: 'در حالِ انتشار', PublishedSite.LIVE: 'روی اینترنت است',
    PublishedSite.STOPPED: 'خاموش است', PublishedSite.FAILED: 'خراب است', PublishedSite.UNPUBLISHED: 'از اینترنت برداشته شده',
}
STALE_MINUTES = 25


def _project(slug):
    return get_object_or_404(Project, slug=slug)


def _job_json(job):
    if job is None:
        return None
    return {'id': job.pk, 'kind': job.kind, 'state': job.state, 'steps': job.steps or [], 'message': job.message, 'technical': job.technical,
            'created_at': job.created_at.isoformat(), 'finished_at': job.finished_at.isoformat() if job.finished_at else None}


def _active_job(site):
    job = site.jobs.filter(state__in=(SiteJob.QUEUED, SiteJob.RUNNING)).order_by('-id').first()
    if job is not None and job.updated_at < timezone.now() - datetime.timedelta(minutes=STALE_MINUTES):
        job.state = SiteJob.FAILED
        job.message = 'این کار نیمه‌تمام ماند (سرور در میانه‌اش بازنشانی شد). دوباره امتحان کن.'
        job.finished_at = timezone.now()
        job.save()
        return None
    return job


def start_job(site, kind, user='', payload=None):
    """یک کار در هر لحظه برای هر سایت. ⇒ (job، None) یا (None، پاسخِ خطا)"""
    from apps.projects.tasks import run_site_job
    with transaction.atomic(using='studio'):
        if _active_job(site) is not None:
            return None, bad('کارِ دیگری روی این سایت در جریان است. چند لحظه صبر کن.', code=409)
        job = SiteJob.objects.create(site=site, kind=kind, user=str(user or '')[:80], payload=payload or {}, state=SiteJob.QUEUED)
    try:
        run_site_job.delay(job.pk)
    except Exception as exc:  # noqa: BLE001 — صف در دسترس نیست
        job.state = SiteJob.FAILED
        job.message = 'صفِ کارهای پس‌زمینه در دسترس نیست. چند دقیقه بعد دوباره امتحان کن.'
        job.technical = repr(exc)[:500]
        job.finished_at = timezone.now()
        job.save()
    job.refresh_from_db()
    return job, None


def _cert_days(text):
    try:
        end = datetime.datetime.strptime(text, '%b %d %H:%M:%S %Y %Z').replace(tzinfo=datetime.timezone.utc)
    except (TypeError, ValueError):
        return None, None
    return end.isoformat(), (end - timezone.now()).days


ERROR_LINE = re.compile(r'error|exception|traceback|critical|failed|killed|memory', re.I)


def _recent_errors(site):
    out = []
    for line in sysops.journal_tail(site.key, 80).splitlines():
        if ERROR_LINE.search(line) and 'nm-site' in line and 'Started' not in line:
            out.append(line[:300])
    return out[-8:]


def _pending_changes(site):
    if not site.last_publish_at:
        return []
    rows = Design.objects.filter(project=site.project, published_at__gt=site.last_publish_at).select_related('page')
    return [(d.page.title if d.page_id else d.get_target_display()) for d in rows]


def _other_drafts(site):
    from apps.projects.builder.clean import canonical
    out = []
    for d in Design.objects.filter(project=site.project).select_related('page'):
        if canonical(d.draft) != canonical(d.published) and (d.draft or {}).get('blocks'):
            out.append(d.page.title if d.page_id else d.get_target_display())
    return out


def site_json(site, light=False):
    project = site.project
    state = site.state
    unit = sysops.unit_active(site.key) if site.port and sysops.unit_exists(site.key) else ''
    # اگر سرویس افتاده باشد، حرفِ سیستم معتبر است نه آن‌چه در دیتابیس نوشته‌ایم
    if state == PublishedSite.LIVE and unit and unit not in ('active', 'activating', 'reloading'):
        state = PublishedSite.FAILED
    end_iso, days = _cert_days(site.cert_expires)
    records = domains.records_for(site.domain) if site.domain else []
    data = {
        'key': site.key, 'state': state, 'state_label': STATE_LABEL.get(state, state), 'imported': project.is_imported,
        'address': publisher.public_address(site) if site.port else '',
        'port_address': 'http://%s:%d/' % (sysops.public_ip(), site.port) if site.port else '',
        'admin_url': (publisher.public_address(site) + 'admin/') if site.port else '',
        'admin_user': site.admin_user, 'admin_password': site.admin_password,
        'domain': site.domain, 'domain_state': site.domain_state, 'domain_error': site.domain_error, 'domain_www': site.domain_www,
        'domain_staging': site.domain_staging, 'domain_records': records, 'domain_instruction': domains.instruction(site.domain) if site.domain else [],
        'cert_expires': end_iso, 'cert_days_left': days, 'server_ip': sysops.public_ip(),
        'last_publish_at': site.last_publish_at.isoformat() if site.last_publish_at else None,
        'last_error': site.last_error, 'last_technical': site.last_technical,
        'can_rollback': bool(site.previous_release and site.current_release and site.previous_release != site.current_release),
        'unit': unit, 'published': bool(site.port),
    }
    if not light:
        unread = total = 0
        if site.port or site.state == PublishedSite.UNPUBLISHED:
            try:
                m = publisher.read_messages(site, count_only=True)
                unread, total = m['unread'], m['total']
            except publisher.HostingError:
                pass
        data.update({
            'unread': unread, 'messages_total': total, 'errors': _recent_errors(site) if site.port else [],
            'memory_mb': sysops.unit_memory_mb(site.key) if unit == 'active' else None,
            'disk_mb': sysops.dir_size_mb(site.key) if site.port else None,
            'pending': _pending_changes(site), 'drafts': _other_drafts(site),
            'backups': publisher.list_backups(site)[:12] if site.port else [],
        })
    return data


@studio_api('GET')
def status(request, slug):
    p = _project(slug)
    site = publisher.get_site(p)
    light = request.query_params.get('light') == '1'
    job = _active_job(site) or site.jobs.order_by('-id').first()
    return Response({'site': site_json(site, light=light), 'job': _job_json(job), 'capacity': publisher.capacity() if not light else None})


@studio_api('POST')
def do_publish(request, slug):
    p = _project(slug)
    if p.is_imported:
        return bad('پروژهٔ واردشده هنوز از این راه منتشر نمی‌شود (تنظیمات و دیتابیسِ خودش را دارد). می‌توانی ZIP را بگیری.')
    site = publisher.get_site(p)
    from apps.projects.builder.publish import refresh_all
    refresh_all(p)
    try:
        publisher.guard_capacity(site)
    except publisher.HostingError as exc:
        return bad(exc.message, code=409)
    job, err = start_job(site, SiteJob.PUBLISH, getattr(request.user, 'username', ''))
    if err:
        return err
    return Response({'ok': True, 'job': _job_json(job)}, status=202)


def _simple(kind, need_published=True):
    @studio_api('POST')
    def view(request, slug):
        p = _project(slug)
        site = publisher.get_site(p)
        if need_published and not site.port:
            return bad('این سایت هنوز روی اینترنت نیست.')
        job, err = start_job(site, kind, getattr(request.user, 'username', ''))
        if err:
            return err
        return Response({'ok': True, 'job': _job_json(job)}, status=202)
    return view


do_stop = _simple(SiteJob.STOP)
do_start = _simple(SiteJob.START)
do_rollback = _simple(SiteJob.ROLLBACK)
do_unpublish = _simple(SiteJob.UNPUBLISH)
do_reset_admin = _simple(SiteJob.RESET_ADMIN)


@studio_api('POST')
def do_purge(request, slug):
    """حذفِ کاملِ داده‌های یک سایتِ برداشته‌شده؛ با نوشتنِ نشانی، تا تصادفی نشود."""
    p = _project(slug)
    site = publisher.get_site(p)
    if site.port:
        return bad('اول سایت را از اینترنت بردار.')
    if str(request.data.get('confirm') or '').strip() != site.key:
        return bad('برای حذفِ داده‌ها باید عبارتِ «%s» را دقیق بنویسی.' % site.key)
    try:
        sysops.purge(site.key)
    except sysops.SysError as exc:
        return bad(str(exc))
    site.admin_user = ''
    site.admin_password = ''
    site.domain = ''
    site.domain_state = PublishedSite.DOMAIN_NONE
    site.state = PublishedSite.NONE
    site.save()
    return Response({'ok': True})


@studio_api('POST', 'DELETE')
def domain(request, slug):
    """POST: دامنه را می‌گیرد و راهنمای DNS را برمی‌گرداند. DELETE: جدا کردن."""
    p = _project(slug)
    site = publisher.get_site(p)
    if request.method == 'DELETE':
        if not site.domain:
            return bad('دامنه‌ای وصل نیست.')
        if not site.port:
            site.domain = ''
            site.domain_state = PublishedSite.DOMAIN_NONE
            site.save(update_fields=['domain', 'domain_state'])
            return Response({'ok': True, 'job': None})
        job, err = start_job(site, SiteJob.DOMAIN_OFF, getattr(request.user, 'username', ''))
        if err:
            return err
        return Response({'ok': True, 'job': _job_json(job)}, status=202)
    if not site.port:
        return bad('اول سایت را منتشر کن، بعد دامنه را وصل کن.')
    if site.domain and site.domain_state == PublishedSite.DOMAIN_ACTIVE:
        return bad('این سایت الان به «%s» وصل است. اول آن را جدا کن.' % site.domain)
    try:
        name = domains.normalize(request.data.get('domain'))
        domains.check_allowed(name, site.key)
    except domains.DomainError as exc:
        return bad(exc, 'domain')
    if PublishedSite.objects.filter(domain=name).exclude(pk=site.pk).exists():
        return bad('این دامنه الان به سایتِ دیگری از همین پنل وصل است؛ اول از آن‌جا جدایش کن.', 'domain')
    if site.domain and site.domain != name:
        # دامنهٔ قبلی هنوز گواهی نگرفته بود؛ vhost ِ http اش باید برود
        sysops.certbot_delete(site.key)
    site.domain = name
    site.domain_www = False
    site.domain_state = PublishedSite.DOMAIN_WAITING
    site.domain_error = ''
    site.save(update_fields=['domain', 'domain_www', 'domain_state', 'domain_error'])
    try:
        sysops.write_vhost(site.key, publisher.render_vhost(site))
    except sysops.SysError:
        pass
    return Response({'ok': True, 'domain': name, 'records': domains.records_for(name), 'instruction': domains.instruction(name)})


@studio_api('POST')
def domain_check(request, slug):
    """DNS را می‌سنجد؛ اگر درست بود گواهی و HTTPS در پس‌زمینه شروع می‌شود."""
    p = _project(slug)
    site = publisher.get_site(p)
    if not site.domain or not site.port:
        return bad('اول دامنه را بنویس.')
    result = domains.check_dns(site.domain)
    if not result['ready']:
        return Response({'ok': False, 'ready': False, 'problems': result['problems']})
    # فقط کارمندِ کل می‌تواند گواهیِ آزمایشی بخواهد؛ در رابط نیست و فقط برای آزمونِ سرتاسری است
    staging = bool(request.data.get('staging') and request.user.is_superuser)
    job, err = start_job(site, SiteJob.DOMAIN, getattr(request.user, 'username', ''), {'names': result['names'], 'staging': staging})
    if err:
        return err
    return Response({'ok': True, 'ready': True, 'problems': result['problems'], 'job': _job_json(job)}, status=202)


@studio_api('GET', 'POST')
def messages(request, slug):
    """پیام‌های فرمِ سایتِ منتشرشده. POST {id, read} یا {all: true} وضعیتِ خوانده‌شدن را عوض می‌کند."""
    p = _project(slug)
    site = publisher.get_site(p)
    if not site.current_release and site.state != PublishedSite.UNPUBLISHED:
        return Response({'rows': [], 'total': 0, 'unread': 0, 'published': False})
    try:
        if request.method == 'POST':
            mark = 'all' if request.data.get('all') else int(request.data.get('id') or 0)
            if not mark:
                return bad('کدام پیام؟')
            data = publisher.read_messages(site, mark=mark, read=bool(request.data.get('read', True)))
        else:
            limit = min(max(int(request.query_params.get('limit') or 30), 1), 100)
            offset = max(int(request.query_params.get('offset') or 0), 0)
            data = publisher.read_messages(site, limit=limit, offset=offset)
    except (TypeError, ValueError):
        return bad('درخواست درست نیست.')
    except publisher.HostingError as exc:
        return bad(exc.message, code=500)
    data['published'] = bool(site.port)
    return Response(data)
