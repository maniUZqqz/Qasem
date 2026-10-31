# -*- coding: utf-8 -*-
"""APIِ ویرایشگرِ دیداری — زیرِ /api/v1/studio/projects/<slug>/builder/…

همان قاعدهٔ بقیهٔ سایت‌ساز: فقط کارمند (IsAdminUser) و هر شیء با پروژه‌اش سنجیده می‌شود.
تنها دو مسیرِ عمومی داریم (تصویرهای رسانه و فونت‌ها) که فقط‌خواندنی‌اند و نامشان با الگوی سفت سنجیده می‌شود؛
این فایل‌ها به‌هرحال روی سایتِ عمومی هم دیده خواهند شد.
"""
import mimetypes
import os
import re

from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_GET
from rest_framework.response import Response

from apps.code_generation import generator, preview_runner, services
from apps.projects.api import bad, studio_api
from apps.projects.helpers import preview_url
from apps.projects.models import Design, DesignVersion, MediaAsset, Model, Page, Project, SavedSection, SharedPart, SiteTheme
from . import canvas, media as media_mod, publish as P, starters, theme as theme_mod
from .catalog import BLOCKS, catalog_json
from .clean import DocError, canonical, clean_doc, refresh_ids
from .icons import PICKABLE
from .importer import import_html
from .render import build_ctx, default_fields, render_doc

TARGETS = ('page', 'header', 'footer')


def _project(slug):
    p = get_object_or_404(Project, slug=slug)
    return p


def _guard(p):
    if p.is_imported:
        return bad('ویرایشگرِ دیداری فعلاً فقط برای پروژه‌های ساختهٔ سایت‌ساز است؛ قالب‌های پروژهٔ واردشده با کد ویرایش می‌شوند.')
    return None


def _target(request_data, p):
    target = request_data.get('target') or 'page'
    if target not in TARGETS:
        raise Http404
    page = None
    if target == 'page':
        page = get_object_or_404(Page, pk=request_data.get('page') or 0, project=p)
        if page.is_imported:
            raise Http404
    return target, page


def _models_json(p):
    ctx = build_ctx(p)
    out = []
    refs = {'%s.%s' % (m.app.name, m.name) for m in P.public_model_refs(p)}
    for ref, m in ctx.models.items():
        if ref not in refs:
            continue
        out.append({'ref': ref, 'pk': m['pk'], 'label': m['label'], 'fields': m['fields'], 'default_fields': default_fields(m),
                    'has_detail': ref in ctx.routes or ref == 'catalog.Product',
                    'is_product': ref == 'catalog.Product' and ctx.has_cart})
    return out


def _pages_json(p):
    rows = []
    designs = {d.page_id: d for d in Design.objects.filter(project=p, target='page')}
    for pg in p.pages.exclude(kind='imported'):
        d = designs.get(pg.pk)
        rows.append({'id': pg.pk, 'title': pg.title, 'slug': pg.slug, 'in_menu': pg.in_menu, 'has_design': d is not None,
                     'dirty': bool(d and canonical(d.draft) != canonical(d.published)), 'url': '/%s/' % pg.slug if pg.slug else '/'})
    return rows


def _theme_row(p):
    t, _ = SiteTheme.objects.get_or_create(project=p)
    return t


def _theme_json(p):
    t = _theme_row(p)
    base = P.part_content(p, 'base_css') or (generator.BASE_CSS % {'brand': p.brand_color})
    return theme_mod.theme_for_editor(t, p, base), (t.menu or [])


def _preview(request, p):
    running, port, _pid = preview_runner.status(p)
    user, password = preview_runner.admin_login(p)
    return {'running': running, 'url': preview_url(request, port) if running else '', 'admin_user': user, 'admin_password': password}


def _version_json(v):
    return {'id': v.pk, 'label': v.label, 'kind': v.kind, 'created_at': v.created_at.isoformat(), 'user': v.user}


def _section_json(s):
    return {'id': s.pk, 'title': s.title, 'type': (s.doc or {}).get('type'), 'created_at': s.created_at.isoformat()}


# ─────────────────────────────── راه‌اندازی
@studio_api('GET')
def catalog(request, slug):
    """فهرستِ بلوک‌ها، قالب‌های آماده، فونت‌ها — بی‌وابستگی به صفحه."""
    p = _project(slug)
    g = _guard(p)
    if g:
        return g
    c = catalog_json()
    c['icon_names'] = PICKABLE
    return Response({'catalog': c, 'starters': starters.starters_json(), 'theme_options': theme_mod.public_json(),
                     'pages': _pages_json(p), 'project': {'slug': p.slug, 'name': p.name, 'site_title': p.site_title,
                                                           'has_cart': build_ctx(p).has_cart}})


@studio_api('GET')
def bootstrap(request, slug):
    """همهٔ چیزی که ویرایشگر برای یک صفحه لازم دارد."""
    p = _project(slug)
    g = _guard(p)
    if g:
        return g
    target, page = _target(request.query_params, p)
    design, notice = P.open_design(p, target, page)
    theme, menu = _theme_json(p)
    c = catalog_json()
    c['icon_names'] = PICKABLE
    return Response({
        'project': {'slug': p.slug, 'name': p.name, 'site_title': p.site_title, 'has_cart': build_ctx(p).has_cart},
        'target': target, 'page': {'id': page.pk, 'title': page.title, 'slug': page.slug, 'in_menu': page.in_menu, 'kind': page.kind} if page else None,
        'doc': design.draft, 'status': P.status_of(design), 'notice': notice,
        'catalog': c, 'starters': starters.starters_json(), 'theme': theme, 'menu': menu, 'theme_options': theme_mod.public_json(),
        'pages': _pages_json(p), 'models': _models_json(p), 'media': [media_mod.asset_json(a) for a in MediaAsset.objects.filter(project=p)],
        'sections': [_section_json(s) for s in SavedSection.objects.filter(project=p)],
        'versions': [_version_json(v) for v in design.versions.all()[:40]],
        'preview': _preview(request, p),
    })


# ─────────────────────────────── سند
@studio_api('PUT', 'POST')
def design_save(request, slug):
    p = _project(slug)
    g = _guard(p)
    if g:
        return g
    target, page = _target(request.data, p)
    design = P.get_design(p, target, page)
    try:
        P.save_draft(design, request.data.get('doc'), request.data.get('rev'))
    except P.ConflictError as exc:
        return bad(exc, code=409)
    except (DocError, TypeError) as exc:
        return bad(exc)
    return Response({'ok': True, 'status': P.status_of(design)})


@studio_api('POST')
def render_canvas(request, slug):
    p = _project(slug)
    g = _guard(p)
    if g:
        return g
    target, page = _target(request.data, p)
    try:
        doc = clean_doc(request.data.get('doc'), target)
    except (DocError, TypeError) as exc:
        return bad(exc)
    theme = theme_mod.clean_theme(request.data.get('theme'), p) if request.data.get('theme') else _theme_json(p)[0]
    menu = request.data.get('menu') if isinstance(request.data.get('menu'), list) else (_theme_row(p).menu or [])
    return Response(canvas.render_canvas(p, target, page, doc, theme, _clean_menu(menu, p)))


@studio_api('POST')
def publish(request, slug):
    p = _project(slug)
    g = _guard(p)
    if g:
        return g
    target, page = _target(request.data, p)
    try:
        out = P.publish_site(p, target, page, request.data.get('doc'), getattr(request.user, 'username', '') or '')
    except (DocError, P.PublishError, TypeError) as exc:
        return bad(exc)
    if out.get('port'):
        out['preview_url'] = preview_url(request, out['port'])
    design = P.get_design(p, target, page)
    out['status'] = P.status_of(design)
    out['versions'] = [_version_json(v) for v in design.versions.all()[:40]]
    out['pages'] = _pages_json(p)
    out['preview'] = _preview(request, p)
    return Response(out, status=200 if out['ok'] else 500)


@studio_api('GET', 'POST')
def version_detail(request, slug, pk):
    """GET: سندِ یک نسخه. POST: برگرداندنش به پیش‌نویس (سایت تا انتشار عوض نمی‌شود)."""
    p = _project(slug)
    v = get_object_or_404(DesignVersion.objects.select_related('design'), pk=pk, design__project=p)
    if request.method == 'GET':
        return Response({'version': _version_json(v), 'doc': v.doc})
    d = v.design
    if canonical(d.draft) != canonical(d.published):
        P.snapshot(d, d.draft, '', 'پیش‌نویس پیش از بازگشت به نسخهٔ قبلی', 'draft')
    d.draft = v.doc
    d.rev += 1
    d.save(update_fields=['draft', 'rev', 'updated_at'])
    return Response({'ok': True, 'doc': d.draft, 'status': P.status_of(d), 'versions': [_version_json(x) for x in d.versions.all()[:40]],
                     'message': 'نسخهٔ قبلی به پیش‌نویس برگشت. برای اثر روی سایت «انتشار» را بزن.'})


@studio_api('POST')
def roundtrip_check(request, slug, pk):
    """پیش از ذخیرهٔ کد: اگر این کد در ویرایشگرِ دیداری کامل برنمی‌گردد، به کاربر بگو."""
    p = _project(slug)
    page = get_object_or_404(Page, pk=pk, project=p)
    d = Design.objects.filter(project=p, target='page', page=page).first()
    if d is None:
        return Response({'has_design': False, 'custom': 0, 'labels': [], 'dirty': False})
    html = request.data.get('body_html')
    if not isinstance(html, str):
        return bad('متنِ صفحه نیامد.')
    ctx = build_ctx(p, target='page')
    _doc, report = import_html(html, request.data.get('css') or '', d.published, ctx, 'page')
    before = sum(1 for b in _walk((d.published or {}).get('blocks')) if b['type'] == 'custom_html')
    return Response({'has_design': True, 'custom': report['custom'], 'new_custom': max(0, report['custom'] - before),
                     'labels': report.get('custom_labels', [])[:8], 'dirty': canonical(d.draft) != canonical(d.published)})


def _walk(blocks):
    for b in blocks or []:
        yield b
        yield from _walk(b.get('children'))


# ─────────────────────────────── صفحه‌ها
def _free_slug(p, wanted):
    used = set(p.pages.values_list('slug', flat=True))
    if wanted not in used:
        return wanted
    base = wanted or 'page'
    i = 2
    while '%s-%d' % (base, i) in used:
        i += 1
    return '%s-%d' % (base, i)


@studio_api('POST')
def page_create(request, slug):
    """صفحهٔ تازه از روی قالب؛ پیش‌فرضِ کاربرِ تازه‌کار همین است."""
    p = _project(slug)
    g = _guard(p)
    if g:
        return g
    key = request.data.get('starter') or 'blank'
    spec = starters.BY_KEY.get(key)
    if not spec:
        return bad('این قالب پیدا نشد.')
    title = (str(request.data.get('title') or '').strip() or spec['title'])[:120]
    pslug = _free_slug(p, spec['slug'])
    if key == 'shop' and p.pages.filter(slug='products').exists() and build_ctx(p).has_cart:
        pslug = _free_slug(p, 'shop')
    page = Page.objects.create(project=p, title=title, slug=pslug, kind='home' if pslug == '' else 'static', body_html='',
                               in_menu=False, order=p.pages.count() * 10 + 10)
    ctx = build_ctx(p)
    doc = clean_doc(starters.starter_doc(key, ctx), 'page')
    Design.objects.create(project=p, target='page', page=page, draft=doc, synced_hash=P.fingerprint(p, 'page', page))
    if request.data.get('setup_chrome'):
        _setup_chrome(p, ctx)
    return Response({'ok': True, 'page': {'id': page.pk, 'title': page.title, 'slug': page.slug}, 'pages': _pages_json(p)}, status=201)


def _setup_chrome(p, ctx):
    """سربرگ و پابرگِ دیداری برای کسی که تازه شروع کرده (فقط اگر کدی ننوشته باشد)."""
    for target, fn in (('header', starters.header_doc), ('footer', starters.footer_doc)):
        if not P.part_content(p, target).strip() and not Design.objects.filter(project=p, target=target).exists():
            Design.objects.create(project=p, target=target, draft=clean_doc(fn(ctx), target), synced_hash=P.fingerprint(p, target, None))


@studio_api('POST')
def page_starter(request, slug, pk):
    """قالبِ آماده روی صفحهٔ موجود؛ پیش‌نویسِ قبلی در نسخه‌ها می‌ماند."""
    p = _project(slug)
    g = _guard(p)
    if g:
        return g
    page = get_object_or_404(Page, pk=pk, project=p)
    spec = starters.BY_KEY.get(request.data.get('starter'))
    if not spec:
        return bad('این قالب پیدا نشد.')
    design, _ = P.open_design(p, 'page', page)
    if (design.draft or {}).get('blocks'):
        P.snapshot(design, design.draft, '', 'پیش‌نویس پیش از قالبِ آماده', 'draft')
    ctx = build_ctx(p)
    design.draft = clean_doc(starters.starter_doc(spec['key'], ctx), 'page')
    design.rev += 1
    design.save(update_fields=['draft', 'rev', 'updated_at'])
    if request.data.get('setup_chrome'):
        _setup_chrome(p, ctx)
    return Response({'ok': True, 'doc': design.draft, 'status': P.status_of(design)})


@studio_api('POST', 'PUT')
def page_meta(request, slug, pk):
    p = _project(slug)
    page = get_object_or_404(Page, pk=pk, project=p)
    title = str(request.data.get('title') or '').strip()
    if title:
        page.title = title[:120]
        page.save(update_fields=['title'])
    return Response({'ok': True, 'page': {'id': page.pk, 'title': page.title, 'slug': page.slug}, 'pages': _pages_json(p)})


# ─────────────────────────────── پوسته و منو
def _clean_menu(rows, p):
    pages = set(p.pages.values_list('pk', flat=True))
    out = []
    for row in (rows if isinstance(rows, list) else [])[:40]:
        if not isinstance(row, dict):
            continue
        label = str(row.get('label') or '').strip()[:60]
        rid = re.sub(r'[^a-z0-9]', '', str(row.get('id') or ''))[:16] or 'm%d' % len(out)
        if row.get('page'):
            try:
                pk = int(row['page'])
            except (TypeError, ValueError):
                continue
            if pk in pages:
                out.append({'id': rid, 'page': pk, 'label': label})
        elif row.get('url'):
            from .clean import safe_url
            url = safe_url(row['url'])
            if url and not url.startswith('page:'):
                out.append({'id': rid, 'url': url, 'label': label or url})
    return out


@studio_api('GET', 'PUT', 'POST')
def theme_detail(request, slug):
    p = _project(slug)
    g = _guard(p)
    if g:
        return g
    if request.method == 'GET':
        theme, menu = _theme_json(p)
        return Response({'theme': theme, 'menu': menu})
    t = _theme_row(p)
    if 'theme' in request.data:
        t.draft = theme_mod.clean_theme(request.data.get('theme'), p)
    if 'menu' in request.data:
        t.menu = _clean_menu(request.data.get('menu'), p)
    t.save()
    return Response({'ok': True, 'theme': t.draft, 'menu': t.menu})


# ─────────────────────────────── رسانه
@studio_api('GET', 'POST')
def media_list(request, slug):
    p = _project(slug)
    g = _guard(p)
    if g:
        return g
    if request.method == 'GET':
        return Response({'media': [media_mod.asset_json(a) for a in MediaAsset.objects.filter(project=p)]})
    upload = request.FILES.get('file')
    if upload is None:
        return bad('فایلی انتخاب نشده.')
    try:
        asset = media_mod.save_upload(p, upload, str(request.data.get('alt') or '')[:200])
    except media_mod.MediaError as exc:
        return bad(exc)
    return Response({'ok': True, 'asset': media_mod.asset_json(asset)}, status=201)


@studio_api('PUT', 'POST', 'DELETE')
def media_detail(request, slug, pk):
    p = _project(slug)
    asset = get_object_or_404(MediaAsset, pk=pk, project=p)
    if request.method == 'DELETE':
        used = media_mod.where_used(p, asset)
        if used and str(request.query_params.get('force')) != '1':
            return Response({'error': 'این فایل در این صفحه‌ها به‌کار رفته: %s' % '، '.join(used[:6]), 'used': used}, status=409)
        media_mod.delete_asset(asset)
        return Response({'ok': True})
    asset.alt = str(request.data.get('alt') or '')[:200]
    if request.data.get('name'):
        asset.name = media_mod._clean_display_name(request.data['name'])
    asset.save(update_fields=['alt', 'name'])
    return Response({'ok': True, 'asset': media_mod.asset_json(asset)})


# ─────────────────────────────── بخش‌های ذخیره‌شده
@studio_api('GET', 'POST')
def section_list(request, slug):
    p = _project(slug)
    g = _guard(p)
    if g:
        return g
    if request.method == 'GET':
        return Response({'sections': [_section_json(s) for s in SavedSection.objects.filter(project=p)]})
    title = str(request.data.get('title') or '').strip()[:120] or 'بخشِ ذخیره‌شده'
    block = request.data.get('block')
    try:
        clean = clean_doc({'blocks': [block]}, 'page')['blocks'][0]
    except (DocError, TypeError, AttributeError) as exc:
        return bad(exc)
    s = SavedSection.objects.create(project=p, title=title, doc=clean)
    return Response({'ok': True, 'section': _section_json(s)}, status=201)


@studio_api('GET', 'DELETE')
def section_detail(request, slug, pk):
    p = _project(slug)
    s = get_object_or_404(SavedSection, pk=pk, project=p)
    if request.method == 'DELETE':
        s.delete()
        return Response({'ok': True})
    return Response({'section': _section_json(s), 'block': refresh_ids(s.doc)})


# ─────────────────────────────── داده
@studio_api('POST')
def model_seed(request, slug, pk):
    """چند موردِ نمونه تا فهرستِ پویا از همان اول چیزی نشان بدهد."""
    p = _project(slug)
    m = get_object_or_404(Model.objects.select_related('app'), pk=pk, app__project=p)
    if m not in P.public_model_refs(p):
        return bad('برای این بخش نمی‌شود دادهٔ نمونه ساخت.')
    try:
        n = P.seed_records(p, m, 6)
    except P.PublishError as exc:
        return bad(exc)
    preview_running = preview_runner.status(p)[0]
    return Response({'ok': True, 'count': n, 'preview_running': preview_running,
                     'message': '%d موردِ نمونه ساخته شد. از مدیریتِ سایت می‌توانی ویرایش یا حذفشان کنی.' % n})


# ─────────────────────────────── فایل‌های عمومی (بی‌ورود، فقط خواندن)
def _serve(path):
    ext = path.rsplit('.', 1)[-1].lower()
    ctype = media_mod.CONTENT_TYPES.get(ext) or mimetypes.guess_type(path)[0] or 'application/octet-stream'
    resp = FileResponse(open(path, 'rb'), content_type=ctype)
    resp['Cache-Control'] = 'public, max-age=604800'
    resp['X-Content-Type-Options'] = 'nosniff'
    return resp


@require_GET
def public_media(request, slug, name):
    p = get_object_or_404(Project, slug=slug)
    path = media_mod.public_path(p, name)
    if not path:
        raise Http404
    return _serve(path)


USER_MEDIA_RE = re.compile(r'^[\w./-]+\.(jpg|jpeg|png|webp|gif)$', re.I)


@require_GET
def public_user_media(request, slug, rel):
    """تصویرِ ردیف‌های واقعی (ImageField) برای نمایش در بوم."""
    p = get_object_or_404(Project, slug=slug)
    if not USER_MEDIA_RE.match(rel or '') or '..' in rel:
        raise Http404
    root = os.path.realpath(os.path.join(str(p.path), 'media'))
    full = os.path.realpath(os.path.join(root, rel))
    if not full.startswith(root + os.sep) or not os.path.isfile(full):
        raise Http404
    return _serve(full)


@require_GET
def public_font(request, name):
    if name not in theme_mod.FONT_FILES:
        raise Http404
    resp = FileResponse(open(os.path.join(theme_mod.FONT_DIR, name), 'rb'), content_type='font/woff2')
    resp['Cache-Control'] = 'public, max-age=2592000'
    return resp


__all__ = ['BLOCKS', 'SharedPart', 'services']
