# -*- coding: utf-8 -*-
"""پیش‌نویس، انتشار، نسخه‌ها و هم‌زمانی با AI/کد.

قاعدهٔ اصلی: موتورِ تولید فقط Page.body_html/css و SharedPart را می‌بیند. انتشار یعنی رندرِ سند و نوشتن در همان‌ها.
`synced_hash` می‌گوید سند با چه محتوایی همخوان است؛ اگر محتوا بعداً با AI یا کد عوض شده باشد، بارِ بعدی که صفحه در
ویرایشگر باز می‌شود از روی همان محتوا دوباره بلوک ساخته می‌شود و پیش‌نویسِ قبلی در تاریخچه می‌ماند.
"""
import json

from django.utils import timezone

from apps.code_generation import generator, preview_runner, services
from apps.projects.models import App, Design, DesignVersion, Field, Model, Page, SharedPart, SiteTheme, View
from . import starters, theme as theme_mod
from .clean import DocError, canonical, clean_doc, walk
from .importer import LOAD_STATIC, import_html
from .render import build_ctx, has_block, page_css, render_doc

MAX_VERSIONS = 40
FORMS_APP = 'site_forms'
HIDDEN_APPS = {FORMS_APP}

FORM_VIEW = '''import json

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.shortcuts import redirect
from django.utils.http import url_has_allowed_host_and_scheme

from .models import FormMessage


def submit_form(request):
    """پیامِ فرم‌های سایت را ذخیره می‌کند؛ پیام‌ها در مدیریتِ سایت (پیام‌های فرم) دیده می‌شوند."""
    back = request.POST.get('_next') or '/'
    if not url_has_allowed_host_and_scheme(back, allowed_hosts={request.get_host()}):
        back = '/'
    if request.method != 'POST' or request.POST.get('website'):   # تله برای ربات‌ها
        return redirect(back)
    try:
        spec = json.loads(request.POST.get('_spec') or '[]')
    except ValueError:
        spec = []
    rows, data = [], {}
    for item in spec[:40] if isinstance(spec, list) else []:
        if not isinstance(item, dict):
            continue
        name = str(item.get('n') or '')
        label = str(item.get('l') or name)[:120]
        value = (request.POST.get(name) or '').strip()[:5000]
        if item.get('r') and not value:
            messages.error(request, 'لطفاً «%s» را پر کن.' % label)
            return redirect(back)
        if value and item.get('t') == 'email':
            try:
                validate_email(value)
            except ValidationError:
                messages.error(request, '«%s» درست نیست.' % label)
                return redirect(back)
        data[label] = value
        rows.append('%s: %s' % (label, value))
    if not any(data.values()):
        messages.error(request, 'فرم خالی بود.')
        return redirect(back)
    FormMessage.objects.create(form_title=(request.POST.get('_form') or 'فرم')[:200], page=back[:200],
                               content='\\n'.join(rows), data=data)
    messages.success(request, (request.POST.get('_success') or 'پیامت رسید.')[:300])
    return redirect(back)
'''

SEED_SCRIPT = '''
import random, uuid, datetime
from django.apps import apps
from django.db import models as m
from django.utils import timezone
TEXT = 'این یک متنِ نمونه است که بعداً با متنِ واقعی عوض می‌شود. می‌توانی از مدیریتِ سایت ویرایشش کنی.'
def fill(model, i, depth=0):
    vals = {}
    for f in model._meta.fields:
        if f.primary_key or getattr(f, 'auto_now', False) or getattr(f, 'auto_now_add', False):
            continue
        label = str(f.verbose_name)
        if f.choices:
            vals[f.name] = f.choices[0][0]
        elif isinstance(f, m.SlugField):
            vals[f.name] = 'sample-%s' % uuid.uuid4().hex[:8]
        elif isinstance(f, m.EmailField):
            vals[f.name] = 'name%d@example.com' % i
        elif isinstance(f, m.URLField):
            vals[f.name] = 'https://example.com/%d' % i
        elif isinstance(f, m.TextField):
            vals[f.name] = TEXT
        elif isinstance(f, m.CharField):
            vals[f.name] = ('%s نمونهٔ %d' % (model._meta.verbose_name, i))[:f.max_length]
        elif isinstance(f, m.BooleanField):
            vals[f.name] = True
        elif isinstance(f, (m.DecimalField, m.FloatField)):
            vals[f.name] = 100000 * random.randint(1, 30)
        elif isinstance(f, m.IntegerField):
            vals[f.name] = random.randint(5, 40)
        elif isinstance(f, m.DateTimeField):
            vals[f.name] = timezone.now()
        elif isinstance(f, m.DateField):
            vals[f.name] = timezone.now().date()
        elif isinstance(f, m.TimeField):
            vals[f.name] = timezone.now().time()
        elif isinstance(f, (m.ForeignKey, m.OneToOneField)):
            if f.null and depth > 0:
                continue
            target = f.related_model
            if target._meta.app_label == 'auth':
                continue
            rel = target.objects.first() or (target.objects.create(**fill(target, i, depth + 1)) if depth < 3 else None)
            if rel is not None:
                vals[f.name] = rel
    return vals
model = apps.get_model('__APP__', '__NAME__')
n = 0
for i in range(1, __COUNT__ + 1):
    model.objects.create(**fill(model, i))
    n += 1
print('SEEDED=%d' % n)
'''


class PublishError(ValueError):
    pass


def public_model_refs(project):
    """مدل‌هایی که می‌شود روی سایت نشان داد. پیام‌های فرم و سفارشِ مشتری هرگز در این فهرست نیستند."""
    out = []
    for m in Model.objects.filter(app__project=project).select_related('app'):
        if m.app.name in HIDDEN_APPS or (m.app.is_core and m.app.name == 'orders'):
            continue
        out.append(m)
    return out


# ─────────────────────────────── محتوای فعلی
def part_content(project, kind):
    part = SharedPart.objects.filter(project=project, kind=kind).first()
    return part.content if part else ''


def fingerprint(project, target, page):
    if target == 'page':
        return generator.sha((page.body_html or '') + '\x00' + (page.css or ''))
    return generator.sha(part_content(project, target) or '')


def _current_theme(project):
    t = SiteTheme.objects.filter(project=project).first()
    base = part_content(project, 'base_css') or (generator.BASE_CSS % {'brand': project.brand_color})
    return theme_mod.theme_for_editor(t, project, base)


def _ctx(project, target):
    return build_ctx(project, canvas=False, target=target, theme=_current_theme(project)['colors'])


def snapshot(design, doc, rendered_hash, label, kind, user=''):
    DesignVersion.objects.create(design=design, doc=doc, rendered_hash=rendered_hash or '', label=label[:160], kind=kind, user=user[:80])
    old = list(design.versions.order_by('-created_at', '-id').values_list('pk', flat=True)[MAX_VERSIONS:])
    if old:
        DesignVersion.objects.filter(pk__in=old).delete()


def get_design(project, target, page, create=True):
    q = Design.objects.filter(project=project, target=target)
    q = q.filter(page=page) if target == 'page' else q.filter(page__isnull=True)
    d = q.first()
    if d is None and create:
        d = Design.objects.create(project=project, target=target, page=page if target == 'page' else None, draft={'v': 1, 'blocks': []})
    return d


def open_design(project, target, page):
    """سند را برای ویرایشگر آماده می‌کند ⇒ (design, پیام برای کاربر یا '')"""
    current = fingerprint(project, target, page)
    d = get_design(project, target, page, create=False)
    ctx = _ctx(project, target)
    if d is None:
        d = get_design(project, target, page)
        if target == 'page':
            doc, report = import_html(page.body_html, page.css, None, ctx, 'page')
        else:
            content = part_content(project, target)
            if content.strip():
                doc, report = import_html(content, '', None, ctx, target)
            else:
                doc = starters.header_doc(ctx) if target == 'header' else starters.footer_doc(ctx)
                report = {'custom': 0}
        doc = clean_doc(doc, target)
        d.draft = doc
        d.synced_hash = current
        # تا اولین انتشار، «منتشرشده» همین محتوای واردشده است
        d.published = doc if (target == 'page' and (page.body_html or '').strip()) or (target != 'page' and part_content(project, target).strip()) else None
        d.save()
        msg = ''
        if report.get('custom'):
            msg = ('این صفحه با کد ساخته شده بود. %d بخش به بلوکِ «کدِ سفارشی» تبدیل شد تا چیزی از دست نرود؛ بقیه را می‌توانی مستقیم ویرایش کنی. '
                   'تا «انتشار» را نزنی، سایت تغییری نمی‌کند.' % report['custom'])
        return d, msg
    if d.synced_hash == current:
        return d, ''
    # بیرون از ویرایشگر عوض شده: AI، کد، یا بازگردانیِ پیشنهادِ AI
    dirty = canonical(d.draft) != canonical(d.published)
    if dirty:
        snapshot(d, d.draft, '', 'پیش‌نویس پیش از تغییرِ بیرون از ویرایشگر', 'draft')
    match = d.versions.filter(rendered_hash=current).order_by('-created_at', '-id').first()
    if match:
        doc, msg = match.doc, 'این صفحه با بازگردانیِ هوشِ مصنوعی یا کد به نسخهٔ قبلی‌اش برگشته بود؛ همان نسخه باز شد.'
    else:
        if target == 'page':
            doc, report = import_html(page.body_html, page.css, d.published, ctx, 'page')
        else:
            doc, report = import_html(part_content(project, target), '', d.published, ctx, target)
        doc = clean_doc(doc, target)
        msg = 'این بخش بیرون از ویرایشگرِ دیداری (با هوشِ مصنوعی یا کد) عوض شده بود؛ تغییرها این‌جا آمد.'
        if report.get('custom'):
            msg += ' %d بخش که قابلِ تشخیص نبود به «کدِ سفارشی» تبدیل شد و چیزی از دست نرفت.' % report['custom']
        snapshot(d, doc, current, 'تغییر با هوشِ مصنوعی یا کد', 'external')
    if dirty:
        msg += ' پیش‌نویسِ منتشرنشده‌ات در «نسخه‌ها» نگه داشته شد.'
    d.draft = doc
    d.published = doc
    d.synced_hash = current
    d.rev += 1
    d.save()
    return d, msg


def save_draft(design, doc, rev):
    """⇒ سندِ تمیز. اگر نسخهٔ کلاینت قدیمی باشد ValueError با متن فارسی."""
    if rev is not None and int(rev) != design.rev:
        raise ConflictError('این صفحه در زبانه یا دستگاهِ دیگری هم عوض شده. صفحه را دوباره باز کن تا چیزی روی هم نوشته نشود.')
    design.draft = clean_doc(doc, design.target)
    design.rev += 1
    design.save(update_fields=['draft', 'rev', 'updated_at'])
    return design.draft


class ConflictError(ValueError):
    pass


def status_of(design):
    return {'dirty': canonical(design.draft) != canonical(design.published), 'published_at': design.published_at.isoformat() if design.published_at else None,
            'rev': design.rev}


# ─────────────────────────────── وارسی پیش از انتشار
def validate_rendered(html, doc, url_names):
    from apps.ai_engine.services import validate_template
    ok, issues = validate_template(html, None)
    if ok:
        return
    # کدام بلوکِ سفارشی خراب است؟
    for b in walk(doc.get('blocks')):
        if b['type'] == 'custom_html':
            one_ok, one_issues = validate_template(b['props'].get('code') or '', None)
            if not one_ok:
                raise PublishError('کدِ سفارشی ایراد دارد و منتشر نشد: %s' % '؛ '.join(one_issues[:2]))
    raise PublishError('این صفحه منتشر نشد: %s' % '؛ '.join(issues[:2]))


def render_target(project, design, doc):
    ctx = _ctx(project, design.target)
    rendered = render_doc(doc, ctx)
    html = rendered.html
    load = LOAD_STATIC + '\n' if '{% static' in html else ''
    if design.target == 'page':
        full = html or '<!-- صفحهٔ خالی -->'
    elif design.target == 'footer':
        full = '%s<footer class="nb-footer">\n%s\n</footer>' % (load, html)
    else:
        full = load + html
    validate_rendered(full, doc, generator.url_names(project))
    return full, rendered


def write_target(project, design, doc, full, rendered, label, user=''):
    if design.target == 'page':
        page = design.page
        first = design.published_at is None
        page.body_html = full
        page.css = page_css(rendered.css, doc.get('extra_css'))
        fields = ['body_html', 'css']
        if first and not page.in_menu and not design.keep_out_of_menu:
            page.in_menu = True
            fields.append('in_menu')
        page.save(update_fields=fields)
        design.published_css = ''
    else:
        part, _ = SharedPart.objects.get_or_create(project=project, kind=design.target)
        part.content = full
        part.save()
        extra = doc.get('extra_css') or ''
        design.published_css = rendered.css + ('\n' + extra if extra else '')
    design.draft = doc
    design.published = doc
    design.published_at = timezone.now()
    design.synced_hash = fingerprint(project, design.target, design.page)
    design.rev += 1
    design.save()
    snapshot(design, doc, design.synced_hash, label, 'publish', user)


def ensure_forms_app(project):
    """فرمِ تماس واقعاً باید جایی بفرستد: اپ، مدل، ویو و نشانی از همان راهِ معمولیِ استودیو ساخته می‌شوند."""
    app, _ = App.objects.get_or_create(project=project, name=FORMS_APP, defaults={
        'verbose_name_fa': 'پیام‌های فرم', 'description': 'پیام‌هایی که از فرم‌های سایت می‌رسد', 'url_prefix': 'forms/',
        'order': 900})
    m, made = Model.objects.get_or_create(app=app, name='FormMessage', defaults={
        'verbose_name_fa': 'پیامِ فرم', 'verbose_plural_fa': 'پیام‌های فرم', 'ordering': '-created_at',
        'admin_list_display': 'form_title, content, page, is_read, created_at', 'order': 10})
    if made:
        for i, kw in enumerate([
            dict(name='form_title', verbose_name_fa='فرم', field_type='CharField', max_length=200),
            dict(name='page', verbose_name_fa='صفحه', field_type='CharField', max_length=200, blank=True),
            dict(name='content', verbose_name_fa='پیام', field_type='TextField'),
            dict(name='data', verbose_name_fa='داده', field_type='JSONField', default='dict', blank=True),
            dict(name='is_read', verbose_name_fa='خوانده شده', field_type='BooleanField', default='False'),
            dict(name='created_at', verbose_name_fa='زمان', field_type='DateTimeField', auto_now_add=True),
        ], 1):
            Field.objects.create(model=m, order=i * 10, **kw)
    if not View.objects.filter(app=app, name='submit_form').exists():
        services.add_view(app, 'submit_form', 'custom', with_route=True, custom_code=FORM_VIEW,
                          description='فرستادنِ فرم‌های سایت')
    return app


def publish_theme(project):
    t, _ = SiteTheme.objects.get_or_create(project=project)
    theme = theme_mod.clean_theme(_current_theme(project), project)
    t.draft = theme
    t.published = theme
    t.menu_published = t.menu or []
    t.active = True
    t.save()
    part, _ = SharedPart.objects.get_or_create(project=project, kind='base_css')
    current = part.content.strip() or (generator.BASE_CSS % {'brand': project.brand_color})
    part.content = theme_mod.apply_zone(current, theme)
    part.save()
    if project.brand_color != theme['colors']['primary']:
        project.brand_color = theme['colors']['primary']
        project.save(update_fields=['brand_color'])
    return theme


def publish_site(project, target, page, doc, user=''):
    """انتشار: همین صفحه + سربرگ/پابرگ/پوسته/منو ⇐ تولیدِ کد ⇐ پیش‌نمایش. ⇒ dict برای پنل."""
    design = get_design(project, target, page)
    doc = clean_doc(doc, target)
    # همه را اول رندر و وارسی می‌کنیم تا انتشارِ نیمه‌کاره نداشته باشیم
    jobs = [(design, doc)]
    for other in Design.objects.filter(project=project, target__in=('header', 'footer')):
        if other.pk != design.pk and canonical(other.draft) != canonical(other.published) and (other.draft or {}).get('blocks'):
            jobs.append((other, other.draft))
    prepared = [(d, dc) + render_target(project, d, dc) for d, dc in jobs]

    publish_theme(project)                    # رنگ‌ها و منو همراهِ هر انتشار
    title = page.title if page is not None else design.get_target_display()
    for d, dc, full, rendered in prepared:
        write_target(project, d, dc, full, rendered, 'انتشار', user)
    # ورودِ خودکارِ صفحهٔ تازه به منوی چیده‌شده
    t = SiteTheme.objects.get(project=project)
    if page is not None and t.menu and not any(r.get('page') == page.pk for r in t.menu) and page.in_menu and design.versions.filter(kind='publish').count() == 1 and not design.keep_out_of_menu:
        t.menu = t.menu + [{'id': 'p%d' % page.pk, 'page': page.pk, 'label': page.title}]
        t.menu_published = t.menu
        t.save(update_fields=['menu', 'menu_published'])

    uses_form = any(has_block(d.published, 'contact_form') for d in Design.objects.filter(project=project))
    if uses_form:
        ensure_forms_app(project)

    ok, summary, detail = services.generate(project, 'انتشار: %s' % title)
    warnings = render_doc(doc, _ctx(project, target)).warnings
    out = {'ok': ok, 'warnings': warnings, 'preview_url': '', 'message': '', 'technical': ''}
    if not ok:
        out['message'] = 'صفحه ذخیره شد ولی ساختِ سایت خطا داد. کسی که با کدِ سفارشی کار کرده باید ببیندش.'
        out['technical'] = detail[-3000:]
        return out
    mig_ok, mig_detail = services.migrate(project)
    if not mig_ok:
        out['ok'] = False
        out['message'] = 'صفحه ذخیره شد ولی به‌روزرسانیِ دادهٔ سایت خطا داد.'
        out['technical'] = mig_detail[-3000:]
        return out
    try:
        if preview_runner.status(project)[0]:
            preview_runner.stop(project)
        port, _ = preview_runner.start(project)
        running = preview_runner.status(project)[0]
    except Exception as exc:  # noqa
        running, port = False, None
        out['technical'] = str(exc)[:500]
    out['port'] = port if running else None
    out['message'] = 'منتشر شد!' if running else 'منتشر شد، ولی پیش‌نمایش بالا نیامد. از «پیش‌نمایش» دوباره امتحان کن.'
    return out


def seed_records(project, model_row, count=6):
    """چند ردیفِ نمونه در دیتابیسِ سایتِ تولیدشده (از همان محیطِ خودِ پروژه)."""
    ok, _s, detail = services.generate(project, 'آماده‌سازیِ داده')
    if not ok:
        raise PublishError('ساختِ سایت خطا داد: %s' % detail[-400:])
    ok, detail = services.migrate(project)
    if not ok:
        raise PublishError('به‌روزرسانیِ داده خطا داد: %s' % detail[-400:])
    script = SEED_SCRIPT.replace('__APP__', model_row.app.name).replace('__NAME__', model_row.name).replace('__COUNT__', str(int(count)))
    r = services._run(project, ['manage.py', 'shell', '-c', script], 120)
    if r.returncode != 0 or 'SEEDED=' not in (r.stdout or ''):
        raise PublishError('داده‌ی نمونه ساخته نشد: %s' % ((r.stderr or r.stdout) or '')[-400:])
    return int(r.stdout.split('SEEDED=')[1].split()[0])


__all__ = ['open_design', 'save_draft', 'publish_site', 'publish_theme', 'seed_records', 'status_of', 'fingerprint', 'snapshot',
           'ensure_forms_app', 'public_model_refs', 'ConflictError', 'PublishError', 'DocError', 'get_design', 'Page', 'json']
