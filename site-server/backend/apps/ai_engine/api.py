# -*- coding: utf-8 -*-
"""APIِ هوشِ مصنوعیِ استودیو: تنظیمات، ساختِ فرانت، دستیارِ مدل،
پیشنهادها (Diff + تأیید/رد/بازگردانی). زیرِ /api/v1/studio/ سوار می‌شود."""
import json

from django.shortcuts import get_object_or_404
from django.urls import reverse
from rest_framework import permissions
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from apps.projects.helpers import FormData, change_json, page_json, project_json, proposal_json, shared_parts
from apps.projects.models import Page, Project, SharedPart, View
from . import services
from .models import AiProposal, AiSettings
from .providers import AiError, get_provider

PRESETS = [
    # (نام، سرویس، نشانیِ پایه، مدلِ پیشنهادی) — همه با کتابخانهٔ openai
    ('OpenAI', 'openai', 'https://api.openai.com/v1', 'gpt-4o-mini'),
    ('Metis (ایران)', 'openai', 'https://api.metisai.ir/openai/v1', 'gpt-4o-mini'),
    ('OpenRouter', 'openai', 'https://openrouter.ai/api/v1', 'openai/gpt-4o-mini'),
    ('آزمایشی (بی‌اینترنت)', 'mock', '', 'mock'),
]
NOT_READY = 'اول در «تنظیماتِ هوشِ مصنوعی» کلید را بگذار (یا سرویسِ آزمایشی را انتخاب کن).'


def studio_api(*methods):
    def deco(fn):
        return api_view(list(methods))(permission_classes([permissions.IsAdminUser])(fn))
    return deco


def _p(slug):
    return get_object_or_404(Project, slug=slug)


def bad(msg, field=None, code=400):
    body = {'error': str(msg)}
    if field:
        body['errors'] = {field: str(msg)}
    return Response(body, status=code)


def settings_json(cfg):
    return {
        'provider': cfg.provider, 'provider_display': cfg.get_provider_display(),
        'base_url': cfg.base_url, 'model': cfg.model, 'temperature': cfg.temperature,
        'max_tokens': cfg.max_tokens, 'timeout_s': cfg.timeout_s,
        'has_key': bool(cfg.api_key), 'masked_key': cfg.masked_key if cfg.api_key else '',
        'is_ready': cfg.is_ready, 'updated_at': cfg.updated_at.isoformat() if cfg.updated_at else None,
    }


# ──────────────────────────────────────────────── تنظیمات
@studio_api('GET', 'POST', 'PUT')
def ai_settings(request):
    cfg = AiSettings.get()
    if request.method != 'GET':
        post = FormData(request.data)
        cfg.provider = post.get('provider') or 'mock'
        if cfg.provider not in dict(AiSettings.PROVIDERS):
            cfg.provider = 'mock'
        cfg.base_url = (post.get('base_url') or '').strip()
        key = (post.get('api_key') or '').strip()
        if post.get('clear_key') == 'on':
            cfg.api_key = ''
        elif key:
            cfg.api_key = key                 # خالی = کلیدِ قبلی بماند
        cfg.model = (post.get('model') or 'gpt-4o-mini').strip()
        try:
            cfg.temperature = min(2.0, max(0.0, float(post.get('temperature') or 0.3)))
            cfg.max_tokens = max(256, int(post.get('max_tokens') or 6000))
            cfg.timeout_s = max(10, int(post.get('timeout_s') or 120))
        except ValueError:
            return bad('عددها درست نیستند.')
        cfg.save()
        d = settings_json(cfg)
        d.update({'ok': True, 'message': 'تنظیماتِ هوشِ مصنوعی ذخیره شد.'})
        return Response(d)
    d = settings_json(cfg)
    d.update({
        'providers': AiSettings.PROVIDERS, 'presets': PRESETS,
        'admin_url': reverse('admin:ai_engine_aisettings_change', args=[cfg.pk]),
    })
    return Response(d)


@studio_api('POST')
def ai_settings_test(request):
    """یک درخواستِ کوچک با تنظیماتِ ذخیره‌شده؛ اگر سرویس اجازه بدهد نامِ مدل‌هایش را هم می‌دهد."""
    cfg = AiSettings.get()
    prov = get_provider(cfg)
    try:
        out = prov.ping()
    except AiError as exc:
        return Response({'ok': False, 'message': 'اتصال برقرار نشد: %s' % exc})
    msg = 'اتصال برقرار است — مدلِ «%s» جواب داد: «%s»' % (cfg.model, (out or '').strip()[:80])
    names = prov.list_models(25)
    if names:
        msg += ' · مدل‌هایی که این سرویس اعلام می‌کند: ' + '، '.join(names)
    return Response({'ok': True, 'message': msg, 'models': names or []})


# ──────────────────────────────────────────────── خانهٔ AI هر پروژه
@studio_api('GET', 'POST')
def ai_home(request, slug):
    p = _p(slug)
    cfg = AiSettings.get()
    if request.method == 'POST':
        if not cfg.is_ready:
            return bad(NOT_READY)
        post = FormData(request.data)
        act = post.get('act')
        if act == 'frontend':
            if p.is_imported:
                return bad('ساختِ فرانتِ کامل مالِ پروژه‌های ساختهٔ استودیوست؛ در پروژهٔ واردشده هر قالب را جدا ویرایش کن.')
            brief = (post.get('brief') or p.description or '').strip()
            if not brief:
                return bad('توضیحِ فروشگاه لازم است.', 'brief')
            ids = [int(x) for x in post.getlist('pages') if x.isdigit()] or None
            prop = services.generate_frontend(p, brief, include_shell=post.get('shell') == 'on', page_ids=ids,
                                              include_samples=post.get('samples') == 'on')
            return Response({'ok': True, 'proposal': proposal_json(prop)}, status=201)
        if act == 'models':
            desc = (post.get('description') or '').strip()
            if not desc:
                return bad('توضیح بده چه مدل‌هایی می‌خواهی.', 'description')
            prop = services.suggest_models(p, desc)
            return Response({'ok': True, 'proposal': proposal_json(prop)}, status=201)
        return bad('کارِ ناشناخته.')
    for prop in p.ai_proposals.filter(status='running'):
        services.mark_stale(prop)
    return Response({
        'project': project_json(p),
        'cfg': {'provider': cfg.provider, 'provider_display': cfg.get_provider_display(),
                'model': cfg.model, 'is_ready': cfg.is_ready},
        'pages': [page_json(pg) for pg in p.pages.exclude(kind='imported')],
        'proposals': [proposal_json(x) for x in p.ai_proposals.all()[:40]],
    })


def _instruction(request):
    post = FormData(request.data)
    instr = (post.get('instruction') or '').strip()
    if not instr:
        return post, None, bad('بگو چه تغییری می‌خواهی.', 'instruction')
    if not AiSettings.get().is_ready:
        return post, None, bad(NOT_READY)
    return post, instr, None


@studio_api('POST')
def ai_edit_page(request, slug, pk):
    p = _p(slug)
    page = get_object_or_404(Page, pk=pk, project=p)
    post, instr, err = _instruction(request)
    if err:
        return err
    prop = services.edit_page(page, instr, section=(post.get('section') or '').strip() or None)
    return Response({'ok': True, 'proposal': proposal_json(prop)}, status=201)


@studio_api('POST')
def ai_edit_shared(request, slug, kind):
    p = _p(slug)
    if kind not in dict(SharedPart.KIND):
        return bad('بخشِ ناشناخته.')
    _post, instr, err = _instruction(request)
    if err:
        return err
    prop = services.edit_shared(p, kind, instr)
    return Response({'ok': True, 'proposal': proposal_json(prop)}, status=201)


@studio_api('POST')
def ai_edit_view(request, slug, pk):
    p = _p(slug)
    view = get_object_or_404(View, pk=pk, app__project=p)
    _post, instr, err = _instruction(request)
    if err:
        return err
    prop = services.edit_view(view, instr)
    return Response({'ok': True, 'proposal': proposal_json(prop)}, status=201)


# ──────────────────────────────────────────────── پیشنهاد: Diff و تصمیم
def _proposal_payload(p, prop):
    changes = list(prop.changes.select_related('page', 'view'))
    spec, samples = None, {}
    for ch in changes:
        if ch.target == 'model_spec':
            try:
                spec = json.loads(ch.new_content)
            except ValueError:
                spec = []
        if ch.target == 'sample_data':
            try:
                samples = json.loads(ch.new_content)
            except ValueError:
                samples = {}
    return {
        'project': project_json(p), 'proposal': proposal_json(prop),
        'changes': [change_json(ch) for ch in changes], 'spec': spec, 'samples': samples,
        'shared': shared_parts(p),
    }


@studio_api('GET')
def ai_proposal(request, slug, pk):
    p = _p(slug)
    prop = services.mark_stale(get_object_or_404(AiProposal, pk=pk, project=p))
    return Response(_proposal_payload(p, prop))


@studio_api('GET')
def ai_proposal_status(request, slug, pk):
    """برای تازه‌شدنِ خودکارِ صفحهٔ پیشنهاد."""
    p = _p(slug)
    prop = services.mark_stale(get_object_or_404(AiProposal, pk=pk, project=p))
    return Response({'status': prop.status, 'calls': prop.calls, 'changes': prop.changes.count()})


@studio_api('POST')
def ai_apply(request, slug, pk):
    p = _p(slug)
    prop = get_object_or_404(AiProposal, pk=pk, project=p)
    ids = [int(x) for x in FormData(request.data).getlist('change') if x.isdigit()]
    ok, msg = services.apply_proposal(prop, ids or None)
    prop.refresh_from_db()
    d = _proposal_payload(p, prop)
    d.update({'ok': ok, 'message': msg})
    return Response(d)


@studio_api('POST')
def ai_reject(request, slug, pk):
    p = _p(slug)
    prop = get_object_or_404(AiProposal, pk=pk, project=p)
    services.reject_proposal(prop)
    return Response({'ok': True, 'proposal': proposal_json(prop), 'message': 'پیشنهاد رد شد؛ هیچ‌چیز تغییر نکرد.'})


@studio_api('POST')
def ai_revert(request, slug, pk):
    p = _p(slug)
    prop = get_object_or_404(AiProposal, pk=pk, project=p)
    ok, msg = services.revert_proposal(prop)
    prop.refresh_from_db()
    d = _proposal_payload(p, prop)
    d.update({'ok': ok, 'message': msg})
    return Response(d)
