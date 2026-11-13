# -*- coding: utf-8 -*-
"""آزمونِ خودکارِ «سایت‌ساز: سبکِ طراحی + قطعه‌های آماده در حالتِ AI» (پیوندِ docs/site-styles-and-components.md).

· `site_styles_ai` (کارِ واقعی، روی کارت): همان بسته‌ای که حالتِ AI می‌سازد (سبکِ «بنتو» + دو قطعه، کوچک و محدود) با مدلِ متنیِ خودِ مالک (qwen3:8b یا هر مدلِ کوچکِ نصب‌شده؛
  هیچ مدلی عوض نمی‌شود) به‌صورتِ یک کارِ `ollama.generate` فرستاده می‌شود. قبول یعنی: جوابِ فارسی، بی‌اسکریپت، و دست‌کم یک قطعهٔ داده‌شده را با کلاسِ `nbc-…` به‌کار برده.
· `site_styles_render` (مجازی، بی‌گره): همهٔ ۱۴ سبک × همهٔ قطعه‌ها بدونِ خطا رندر می‌شوند و پرامپتِ AI از سقف بیرون نمی‌زند.
"""
import re

from . import SelfTest, Spec, Verdict, register
from .ollama import _configured, _text_available, persian_letters, pick_text

BRIEF = ('«چغر» دستیار هوش مصنوعیِ مربی‌های ورزشی است و برنامهٔ ورزشی و غذاییِ هر ورزشکار را پیش‌نویس می‌کند؛ شعارش «با چغر چغر تر شو» است. '
         'تصمیمِ نهایی همیشه با مربی است. عدد، قیمت و آمار ننویس.')
PINNED = ['hero_center_glow', 'cta_center_box']


def _design():
    from apps.projects.builder import ai_context
    return ai_context.build('bento-grid', BRIEF, 'home', PINNED, limit=2)


def build(ctx):
    import json
    design = _design()
    prompt = ('تو طراحِ فرانتِ یک سایتِ فارسی هستی. با «design» زیر یک صفحهٔ فرودِ کوتاه بساز: فقط HTMLِ بدنه (بدونِ توضیح و بدونِ ```). '
              'قطعه‌های design.components را عیناً با همان کلاس‌ها بگذار و فقط متن‌ها را برای این برند بنویس.\n\nبرند: %s\n\ndesign:\n%s'
              % (BRIEF, json.dumps(design, ensure_ascii=False)))
    model = pick_text(ctx.installed_ollama(), _configured('text'))
    return Spec('ollama.generate', {'model': model, 'prompt': prompt, 'stream': False, 'think': False, 'options': {'num_predict': 900, 'temperature': 0.2}}, timeout_s=1800)


def check(ctx, job):
    from apps.projects.builder import ai_context, components as C
    data = ctx.read_json(job, 'ollama.json')
    if not isinstance(data, dict):
        return Verdict.failed('جوابِ ollama.json نرسید.')
    text = str(data.get('response') or (data.get('message') or {}).get('content') or '').strip()
    model = (job.payload or {}).get('model')
    meta = ctx.meta(job)
    if len(text) < 100:
        return Verdict.failed('مدلِ «%s» جوابِ خیلی کوتاه داد (%d نویسه).' % (model, len(text)), device=meta.get('device', ''))
    if persian_letters(text) < 12:
        return Verdict.failed('جوابِ مدلِ «%s» فارسی نیست.' % model, device=meta.get('device', ''))
    if re.search(r'<script\b', text, re.I):
        return Verdict.failed('جوابِ مدل اسکریپت دارد.', device=meta.get('device', ''))
    used = C.used_in_html(text)
    sent = {c['key'] for c in _design()['components']}
    if not (set(used) & sent):
        return Verdict.failed('مدلِ «%s» هیچ‌کدام از قطعه‌های داده‌شده را (با کلاسِ nbc-…) به‌کار نبرد.' % model, device=meta.get('device', ''))
    css = ai_context.attach_css(text, '')
    if not css.strip():
        return Verdict.failed('CSSِ قطعه‌ها به صفحه چسبانده نشد.', device=meta.get('device', ''))
    return Verdict.passed('«%s» %d قطعه را به‌کار برد (%s) و CSSِ آن‌ها خودکار چسبید' % (model, len(set(used) & sent), '، '.join(sorted(set(used) & sent))), device=meta.get('device', ''))


def virtual(ctx):
    from apps.projects.builder import ai_context, components as C, styles as S, theme as T
    from apps.projects.builder.clean import clean_doc, new_block
    from apps.projects.builder.render import Ctx, render_doc
    n = 0
    for key, comp in C.COMPONENTS.items():
        target = comp['root'] if comp['root'] in ('header', 'footer') else 'page'
        out = render_doc(clean_doc({'blocks': [new_block(C.block_type(key))]}, target), Ctx(target=target))
        if C.class_of(key) not in out.html:
            return Verdict.failed('قطعهٔ %s رندر نشد.' % key)
        n += 1
    for style in S.ORDER:
        if '--st-card-bg' not in T.blocks_css(T.clean_theme(S.apply_to_theme(T.default_theme(), style)), '', ''):
            return Verdict.failed('سبکِ %s CSS نداد.' % style)
        payload = ai_context.build(style, BRIEF, 'home')
        if payload['stats']['chars'] > ai_context.MAX_CHARS or len(payload['components']) > ai_context.MAX_COMPONENTS:
            return Verdict.failed('بستهٔ AI برای سبکِ %s از سقف بیرون زد.' % style)
    return Verdict.passed('%d قطعه و %d سبک بی‌خطا رندر شد؛ بستهٔ AI همیشه ≤ %d نویسه و ≤ %d قطعه است' % (n, len(S.ORDER), ai_context.MAX_CHARS, ai_context.MAX_COMPONENTS))


register(SelfTest(key='site_styles_ai', label='سایت‌ساز: سبک و قطعه‌ها در حالتِ AI (مدلِ خودِ شما)', group='text', kind='ollama.generate', build=build, check=check,
                  available=_text_available, gpu_required=True, order=32, optional=True,
                  describe='بستهٔ کوچکِ «سبک + دو قطعه» را به مدلِ متنیِ روی کارت می‌دهد؛ باید فارسی و با کلاس‌های nbc-… جواب بدهد'))
register(SelfTest(key='site_styles_render', label='سایت‌ساز: همهٔ سبک‌ها و قطعه‌ها رندر می‌شوند', group='system', virtual=virtual, optional=True, order=96,
                  describe='بی‌گره: ۱۴ سبک × ۴۹ قطعه؛ سقفِ اندازهٔ پرامپتِ AI'))
