# -*- coding: utf-8 -*-
"""چرخهٔ امنِ تغییر با AI (idea.md §۶، §۷):

  ۱. Context ِ محدود ساخته می‌شود — فقط همان صفحه/بخش + قراردادها، نه کلِ پروژه.
  ۲. مدل یک JSON برمی‌گرداند.
  ۳. خروجی وارسی می‌شود (قالبِ جنگو کامپایل شود، تگِ ممنوع نداشته باشد،
     نامِ URLهای ناشناخته هشدار بدهد).
  ۴. هر هدف یک AiChange با «قبل/بعد/Diff» می‌شود؛ همه زیرِ یک AiProposal.
  ۵. کاربر در صفحهٔ پیشنهاد Diff را می‌بیند و اعمال/رد می‌کند.
  ۶. اعمال ⇒ نوشتن در متادیتا ⇒ تولیدِ کد. بازگردانی ⇒ «قبل» برمی‌گردد.

ساختارِ هدر/بدنه/فوتر خودش مرز است: AI برای «ویرایشِ صفحه» فقط بدنه و CSSِ
همان صفحه را می‌تواند برگرداند — هیچ راهی برای دست‌زدن به هدر، فوتر یا
بک‌اند ندارد (معیارِ پایانِ فازِ ۰۷).

⚠ کارِ AI در پس‌زمینه اجرا می‌شود (thread): ساختِ فرانتِ کامل چند فراخوانی
   است و با مدلِ واقعی از مهلتِ ۱۸۰ ثانیه‌ایِ gunicorn بیشتر می‌شود.
   صفحهٔ پیشنهاد تا پایانِ کار خودش تازه می‌شود.
"""
import datetime
import difflib
import json
import os
import re
import threading

from django.conf import settings
from django.db import connections
from django.template import Engine, TemplateSyntaxError
from django.utils import timezone

from apps.code_generation import generator, preview_runner, services as gen_services
from apps.projects.models import App, Field, Model, SharedPart, View
from .models import AiChange, AiProposal, AiSettings
from .providers import AiError, extract_json, get_provider

STALE_AFTER = datetime.timedelta(minutes=45)      # کارِ چندمرحله‌ای روی سرورِ پردازش می‌تواند طولانی باشد

# ──────────────────────────────────────────────── قراردادهای مشترک
RULES_FA = """قراردادهای قالب:
- خروجی قالبِ جنگو (Django template) است؛ تگ‌ها و متغیرهای جنگو را حفظ کن ({% url %}, {% for %}, {{ var }}).
- هیچ‌وقت {% extends %}، {% load %} (جز load static)، {% include %} خارج از components/ ننویس.
- سایت فارسی و راست‌به‌چپ (RTL) است؛ متن‌ها فارسی باشند.
- JavaScript خارجی و فریم‌ورک (React، Tailwind CDN…) اضافه نکن؛ CSS ساده و کلاس‌های موجود.
- فقط از نام‌های URL که داده شده استفاده کن ({% url 'name' %}) یا مسیرهای نسبی (/products/).
- محتوای بدنه داخلِ <main> می‌نشیند؛ هدر و فوتر را تکرار نکن.
- پاسخ فقط JSON باشد."""

PAGE_VARS = {
    'home': "products (فهرستِ محصول: name, slug, price_display, image, category, stock, get_absolute_url), categories (name, slug), SITE_TITLE, q, cat",
    'product_list': "products, categories, q, cat, SITE_TITLE — کارتِ محصول: {% include \"components/product_card.html\" %} با متغیرِ p",
    'product_detail': "product (name, description, price_display, image, category, stock, pk), related",
    'cart': "cart (قابلِ تکرار: product, qty, price, total؛ cart.total_display؛ cart|length) — فرم‌ها به {% url 'cart_update' pk %} و {% url 'cart_remove' pk %}",
    'checkout': "form (فیلدهای customer_name, phone, address)، cart",
    'static': "SITE_TITLE, MENU, CURRENT_PATH, page_title",
}


SCOPED = ('.site-header', '.site-footer', 'header', 'footer', ':root', '.topbar')


def global_selectors(css, chrome_only=()):
    """انتخابگرهایی که به هدر/فوتر محدود نیستند ⇒ روی کلِ سایت اثر دارند.
    chrome_only: کلاس‌هایی که فقط در هدر/فوتر هستند (مثلِ main-nav، cart-link) — آن‌ها محدود حساب می‌شوند."""
    out = []
    for sel, _ in re.findall(r'([^{}]+)\{([^{}]*)\}', re.sub(r'/\*.*?\*/', '', css or '', flags=re.S)):
        for one in sel.split(','):
            one = one.strip()
            if not one or one.startswith('@'):
                continue
            if any(one.startswith(x) or (' ' + x) in one for x in SCOPED):
                continue
            if set(re.findall(r'\.([A-Za-z][\w-]*)', one)) & set(chrome_only):
                continue
            out.append(one)
    return out


def _css_defined(css):
    return set(re.findall(r'\.([A-Za-z][\w-]*)', re.sub(r'{[^{}]*}', '{}', css or '')))


def _css_classes(css):
    return sorted({m for m in re.findall(r'\.([a-zA-Z][\w-]*)', css or '') if not m.startswith('b-')})[:200]


def _shared(project):
    parts = {s.kind: s.content for s in project.shared_parts.all()}
    return {
        'header': parts.get('header') or generator.DEFAULT_HEADER,
        'footer': parts.get('footer') or generator.DEFAULT_FOOTER,
        'base_css': parts.get('base_css') or (generator.BASE_CSS % {'brand': project.brand_color}),
    }


def _project_ctx(project):
    sh = _shared(project)
    return {
        'site_title': project.site_title or project.name,
        'description': project.description,
        'brand_color': project.brand_color,
        'pages': [{'slug': p.slug, 'title': p.title, 'kind': p.kind} for p in project.pages.exclude(kind='imported')],
        'url_names': generator.url_names(project),
        'css_classes': _css_classes(sh['base_css']),
    }


# ──────────────────────────────────────────────── وارسی
_engine = None


def _tpl_engine():
    global _engine
    if _engine is None:
        _engine = Engine(libraries={'static': 'django.templatetags.static'}, builtins=['django.templatetags.static', 'apps.projects.builder.nb_filters'])
    return _engine


def validate_template(src, url_names=None, is_css=False, full_file=False):
    """(معتبر؟، فهرستِ ایرادها) — ایرادِ سخت ⇒ نامعتبر، هشدار ⇒ معتبر با یادداشت.

    full_file=True برای قالبِ کاملِ پروژهٔ واردشده: extends/load/include آزاد است
    (مالِ خودِ پروژه است)، فقط باید از نظرِ نحوِ جنگو درست باشد.
    """
    issues, hard = [], False
    if is_css:
        if '</style' in src.lower() or '<script' in src.lower():
            issues.append('CSS نباید تگِ HTML داشته باشد.')
            hard = True
        return not hard, issues
    low = src.lower()
    if not full_file:
        if re.search(r'{%\s*extends', low):
            issues.append('{% extends %} در بدنه مجاز نیست.')
            hard = True
        for m in re.finditer(r'{%\s*load\s+([^%]+)%}', src):
            libs = m.group(1).split()
            if any(l not in ('static',) for l in libs):
                issues.append('{%% load %s %%} مجاز نیست (فقط static).' % ' '.join(libs))
                hard = True
        for m in re.finditer(r'{%\s*include\s+["\']([^"\']+)', src):
            if not m.group(1).startswith('components/'):
                issues.append('include فقط از components/ مجاز است: %s' % m.group(1))
                hard = True
        try:
            _tpl_engine().from_string(src)
        except TemplateSyntaxError as exc:
            issues.append('خطای قالبِ جنگو: %s' % exc)
            hard = True
        except Exception as exc:  # noqa
            issues.append('خطای قالب: %s' % exc)
            hard = True
    else:
        # کتابخانه‌های تگِ پروژه این‌جا در دسترس نیستند؛ فقط توازنِ بلوک‌ها را می‌سنجیم
        opens = len(re.findall(r'{%\s*(?:block|if|for|with|comment|autoescape|spaceless|filter|ifchanged)\b', src))
        closes = len(re.findall(r'{%\s*end(?:block|if|for|with|comment|autoescape|spaceless|filter|ifchanged)\b', src))
        if opens != closes:
            issues.append('تعدادِ تگ‌های باز و بسته برابر نیست (%d باز، %d بسته).' % (opens, closes))
            hard = True
    if url_names is not None:
        for m in re.finditer(r'{%\s*url\s+["\']([^"\']+)["\']', src):
            if m.group(1) not in url_names:
                issues.append('نامِ URL ناشناخته: %s (در پروژه نیست)' % m.group(1))
    if '<script' in low and 'src=' in low:
        issues.append('اسکریپتِ بیرونی اضافه شده — بررسی کن.')
    return not hard, issues


def unified_diff(old, new, label):
    return ''.join(difflib.unified_diff((old or '').splitlines(True), (new or '').splitlines(True),
                                        fromfile='قبل/' + label, tofile='بعد/' + label, n=3))


def _add_change(proposal, target, label, old, new, page=None, view=None, url_names=None, order=0, scope_note=False):
    if new is None:
        return None
    if isinstance(new, (dict, list)):
        new = json.dumps(new, ensure_ascii=False, indent=2)
    new = str(new).replace('\r\n', '\n')
    is_css = target in ('page_css', 'shared_css', 'view_css')
    if target in ('model_spec', 'sample_data'):
        ok, issues = True, []
    else:
        ok, issues = validate_template(new, url_names, is_css=is_css, full_file=(target == 'page_file'))
    if is_css and ok:
        added = new[len(old or ''):] if (old and new.startswith(old.rstrip())) else new
        known = _known_classes(proposal.project)
        for c in _css_defined(old):
            known.setdefault(c, set())
        unknown = css_unknown_classes(added, known)
        if unknown:
            issues.append('این انتخابگرها به هیچ عنصری نمی‌خورند و اثری ندارند: %s' % '، '.join(unknown[:12]))
        if scope_note:
            sh = _shared(proposal.project)
            in_chrome = {c for t in (sh['header'], sh['footer']) for c in _class_tags(t)}
            elsewhere = set()
            for t in list(proposal.project.pages.values_list('body_html', flat=True)) + list(generator.DEFAULT_BODIES.values()):
                elsewhere |= set(_class_tags(t))
            from apps.code_generation import tpl
            elsewhere |= set(_class_tags(tpl.PRODUCT_CARD_TPL)) | set(_class_tags(tpl.ORDER_DONE_TPL))
            wide = global_selectors(added, in_chrome - elsewhere)
            if wide:
                issues.append('این قاعده‌ها روی همهٔ صفحه‌ها اثر دارند (نه فقط هدر/فوتر): %s — اگر نخواسته بودی رد کن.'
                              % '، '.join(wide[:10]))
    return AiChange.objects.create(
        proposal=proposal, target=target, label=label, page=page, view=view,
        old_content=old or '', new_content=new, diff_text=unified_diff(old, new, label),
        valid=ok, issues='\n'.join(issues), order=order)


def _note_route(provider, proposal):
    """کدام مدل جواب داد؛ در صفحهٔ پیشنهاد صریح نشان داده می‌شود."""
    who = getattr(provider, 'answered_by', '')
    if not who:
        return
    proposal.answered_by = who[:120]
    proposal.fallback_note = (getattr(provider, 'fallback_reason', '') or '')[:400] if getattr(provider, 'fell_back', False) else ''
    proposal.save(update_fields=['answered_by', 'fallback_note'])


def _call(provider, proposal, system, payload):
    """یک فراخوانی: JSON می‌فرستد، JSON می‌گیرد، شمارنده را بالا می‌برد."""
    proposal.calls += 1
    proposal.save(update_fields=['calls'])
    try:
        raw = provider.complete(system, json.dumps(payload, ensure_ascii=False))
    except (ValueError, KeyError, TypeError, OSError) as exc:
        raise AiError('سرویس جواب نداد: %s' % str(exc)[:300])
    _note_route(provider, proposal)
    data = extract_json(raw)
    if not isinstance(data, dict):
        raise AiError('پاسخِ مدل شیءِ JSON نبود.')
    return data


# ──────────────────────────────────────────────── اجرای پس‌زمینه
def _new_proposal(project, task, title, prompt_text):
    cfg = AiSettings.get()
    return AiProposal.objects.create(project=project, task=task, title=title[:200], prompt_text=prompt_text,
                                     status='running',
                                     provider_model='%s / %s' % (cfg.get_provider_display(), cfg.model))


def _finish(proposal, summary):
    proposal.summary = summary or ''
    if not proposal.changes.exists():
        proposal.status = 'failed'
        proposal.error = proposal.error or 'AI چیزی برای تغییر برنگرداند.'
    else:
        proposal.status = 'pending'
    proposal.save()
    return proposal


def _fail(proposal, exc):
    proposal.status = 'failed'
    proposal.error = str(exc)[:4000]
    proposal.save()
    return proposal


def _launch(proposal, fn, *args):
    def job():
        try:
            fn(proposal, *args)
        except (AiError, ValueError, KeyError, TypeError) as exc:
            _fail(proposal, exc)
        except Exception as exc:  # noqa — هر خطایی باید در پیشنهاد ثبت شود، نه این‌که «در حالِ کار» بماند
            _fail(proposal, 'خطای داخلی: %r' % exc)
        finally:
            if not sync:
                connections.close_all()

    sync = getattr(settings, 'AI_RUN_SYNC', False)
    if sync:
        job()
    else:
        threading.Thread(target=job, daemon=True, name='ai-proposal-%s' % proposal.pk).start()
    return proposal


def mark_stale(proposal):
    """اگر سرویس وسطِ کار ری‌استارت شد، پیشنهاد برای همیشه «در حالِ کار» نماند."""
    if proposal.status == 'running' and timezone.now() - proposal.created_at > STALE_AFTER:
        _fail(proposal, 'کار نیمه‌تمام ماند (سرویس ری‌استارت شد یا مدل جواب نداد). دوباره بفرست.')
    return proposal


# ──────────────────────────────────────────────── فازِ ۰۶: فرانتِ اولیه
SYSTEM_SHELL = """تو طراحِ ارشدِ فرانت‌اندِ یک فروشگاهِ اینترنتیِ فارسی با Django هستی و ظاهرِ سایت را از روی توضیحِ فروشگاه طراحی می‌کنی.
%s
یک CSSِ پایه از قبل هست و همهٔ چیدمان را دارد (هدر و منو، هیرو، کارتِ محصول، فرم‌ها، سبد و تسویه، فوتر).
آن را تکرار نکن و هیچ کلاسی را بی‌استایل نگذار؛ فقط «پوسته» (theme_css) بنویس که بعد از آن می‌آید و ظاهر را عوض می‌کند:
مقدارهای :root (base_css_root را ببین و همان متغیرها را با رنگ‌های این برند عوض کن)، رنگ و پس‌زمینهٔ هدر و فوتر،
هیرو (.hero با گرادیان یا رنگِ برند)، کارت‌ها (.card)، دکمه‌ها (.btn)، تیترها، فاصله‌ها و جزئیاتِ تزیینیِ متناسب با برند.
کلیدهای JSON: summary, header, footer, theme_css.
- header دقیقاً با همین ساختار و کلاس‌ها (می‌توانی بالایش یک نوارِ پیامِ کوتاه با کلاسِ topbar اضافه کنی):
  <header class="site-header"><div class="wrap"><a class="brand" href="/">{{ SITE_TITLE }}</a>
  <nav class="main-nav">{%% for title, href in MENU %%}<a href="{{ href }}" class="{%% if CURRENT_PATH == href %%}on{%% endif %%}">{{ title }}</a>{%% endfor %%}</nav>
  <a class="cart-link" href="/cart/">سبد{%% if cart|length %%}<span class="badge">{{ cart|length }}</span>{%% endif %%}</a></div></header>
- footer با همین ساختار: <footer class="site-footer"><div class="wrap"><div class="cols">سه ستون: معرفیِ کوتاهِ فروشگاه، دسترسیِ سریع با {%% for title, href in MENU %%}، تماس</div><p class="copy">…</p></div></footer>
- theme_css: فقط بازنویسی‌ها و افزوده‌ها (۴۰ تا ۱۲۰ خط)، شاملِ :root.
- --ink و --ink-2 و --ink-3 رنگِ متن روی --bg و --card هستند؛ پس روی پس‌زمینهٔ روشن باید تیره بمانند (سفید نکن).
- خوانایی اجباری است: اگر پس‌زمینهٔ هدر یا فوتر را تیره می‌کنی، رنگِ .site-header .brand، .main-nav a، .main-nav a.on، .cart-link
  و .site-footer a و .site-footer b را روشن (مثلاً کرم یا سفید) بگذار؛ هیچ متنی هم‌رنگِ پس‌زمینه‌اش نباشد.""" % RULES_FA

SYSTEM_PAGE = """تو طراحِ فرانت‌اندِ یک فروشگاهِ اینترنتیِ فارسی با Django هستی.
فقط «بدنهٔ» یک صفحه را بساز (داخلِ <main>)؛ هدر و فوتر جدا هستند و نباید تکرار شوند.
%s
کلیدهای JSON: summary, body_html, css.
- body_html: HTML/قالبِ جنگو با متغیرهای داده‌شده. بخش‌ها را با <section class="section"><div class="wrap">…</div></section> بساز.
  از کلاس‌های موجود (project.css_classes) استفاده کن: hero, section-h, grid, card, btn, btn lg, cats, cat-chip, muted, price…
  برای فهرستِ محصول همیشه از {%% include "components/product_card.html" %%} داخلِ {%% for p in products %%} استفاده کن و برای خالی بودن {%% empty %%} بگذار.
- css: CSSِ مخصوصِ همین صفحه برای کلاس‌های تازه‌ای که خودت ساخته‌ای (می‌تواند خالی باشد).
- اگر current_body کلاس‌هایی با پیشوندِ nb- و b- دارد (بلوک‌های ویرایشگرِ دیداری)، همان ساختار و همان کلاس‌ها را دقیقاً نگه دار و فقط متن‌ها را متناسب با توضیح عوض کن؛ کلاس‌ها را حذف یا بازنویسی نکن تا صفحه با کلیک قابلِ ویرایش بماند.""" % RULES_FA


THEME_MARK = '/* ── پوستهٔ هوشِ مصنوعی'


def _rules_for(css, keywords, limit=9000):
    """قاعده‌هایی از CSS که انتخابگرشان یکی از این کلمه‌ها را دارد (برای Context ِ کوچک ولی دقیق)."""
    out = []
    for sel, body in re.findall(r'([^{}]+)\{([^{}]*)\}', css or ''):
        if any(k in sel for k in keywords):
            out.append('%s{%s}' % (sel.strip(), body.strip()))
    return '\n'.join(out)[:limit]


def _class_tags(text):
    tags = {}
    for tag, cl in re.findall(r'<([a-zA-Z][\w-]*)\b[^>]*?\bclass="([^"]*)"', text or ''):
        for c in re.split(r'\s+', re.sub(r'{[%{].*?[%}]}', ' ', cl)):
            if re.fullmatch(r'[A-Za-z][\w-]*', c):
                tags.setdefault(c, set()).add(tag.lower())
    return tags


def _known_classes(project):
    """همهٔ کلاس‌هایی که در قالب‌های این پروژه واقعاً به‌کار رفته‌اند."""
    texts = [generator.DEFAULT_HEADER, generator.DEFAULT_FOOTER] + list(generator.DEFAULT_BODIES.values())
    from apps.code_generation import tpl
    texts += [tpl.PRODUCT_CARD_TPL, tpl.BASE_TPL, tpl.ORDER_DONE_TPL]
    texts += [x.content for x in project.shared_parts.exclude(kind='base_css')]
    texts += list(project.pages.values_list('body_html', flat=True))
    texts += [v.template_body for v in View.objects.filter(app__project=project)]
    tags = {}                                   # کلاس ⇒ تگ‌هایی که این کلاس را دارند
    for t in texts:
        for tag, cl in re.findall(r'<([a-zA-Z][\w-]*)\b[^>]*?\bclass="([^"]*)"', t or ''):
            for c in re.split(r'\s+', re.sub(r'{[%{].*?[%}]}', ' ', cl)):
                if re.fullmatch(r'[A-Za-z][\w-]*', c):
                    tags.setdefault(c, set()).add(tag.lower())
    return tags


def css_unknown_classes(added_css, known):
    """انتخابگرهای بی‌اثر در CSSِ تازه: کلاسی که در هیچ قالبی نیست، یا «تگ.کلاس» با تگِ غلط (b.brand وقتی <a class="brand"> است).

    known: dict کلاس ⇒ تگ‌ها (کلاس‌های تعریف‌شده در CSSِ پایه با تگِ خالی).
    """
    sels = re.sub(r'{[^{}]*}', '{}', added_css or '')
    out = set()
    for c in set(re.findall(r'\.([A-Za-z][\w-]*)', sels)):
        if c not in known:
            out.add('.' + c)
    for tag, c in set(re.findall(r'(?<![\w.#-])([a-zA-Z][\w-]*)\.([A-Za-z][\w-]*)', sels)):
        tags = known.get(c)
        if tags and tag.lower() not in tags:
            out.add('%s.%s (در قالب: %s)' % (tag, c, '، '.join('<%s>' % x for x in sorted(tags))))
    return sorted(out)


def _base_root(css):
    m = re.search(r':root\s*{[^}]*}', css or '')
    return m.group(0) if m else ''


_VAR_DECL = r'--%s\s*:\s*(#[0-9a-fA-F]{3}(?:[0-9a-fA-F]{3})?)\b'
# متن روی پس‌زمینه: اگر مدل این جفت‌ها را نخوانا بسازد، رنگِ متن به مقدارِ پایه برمی‌گردد
_THEME_PAIRS = (('ink', 'bg', 3.0), ('ink', 'card', 3.0), ('ink-2', 'bg', 3.0), ('ink-2', 'card', 3.0), ('ink-3', 'bg', 2.0), ('brand-ink', 'brand', 2.0))


def fix_theme_contrast(theme, base):
    """مدلِ واقعی روی صفحهٔ روشن --ink را سفید کرد و همهٔ متن‌ها نامرئی شدند. ⇒ (پوستهٔ اصلاح‌شده، نام‌های برگشته)"""
    from apps.projects.builder.render import contrast

    def value(name):
        found = re.findall(_VAR_DECL % name, theme) or re.findall(_VAR_DECL % name, base)
        return found[-1] if found else None
    dropped = []
    for fg, bg, minimum in _THEME_PAIRS:
        a, b = value(fg), value(bg)
        if not a or not b or fg in dropped or not re.search(_VAR_DECL % fg, theme):
            continue
        if contrast(a, b) < minimum:
            theme = re.sub(_VAR_DECL % fg + r'\s*;?', '', theme)
            dropped.append(fg)
    return theme, dropped


def _with_theme(base_now, theme, label):
    """پوستهٔ تازه بعد از CSSِ پایه؛ پوستهٔ قبلیِ AI (اگر بود) کنار می‌رود تا روی هم انباشته نشوند."""
    base = base_now.split(THEME_MARK)[0].rstrip()
    theme, _dropped = fix_theme_contrast(theme, base)
    return '%s\n\n%s: %s ── */\n%s\n' % (base, THEME_MARK, label[:60].replace('*/', ''), theme.strip())


SYSTEM_SAMPLES = """تو برای یک فروشگاهِ اینترنتیِ فارسی دادهٔ نمونهٔ واقع‌گرایانه می‌سازی (برای دیدنِ ظاهرِ سایت).
فقط JSON با کلیدهای summary, categories, products:
- categories: ۳ تا ۴ مورد {"name": "نامِ فارسی", "slug": "english-slug"}
- products: ۸ تا ۱۰ مورد {"name": "...", "slug": "english-slug", "description": "دو جملهٔ فارسی", "price": عدد به تومان, "stock": عدد, "category": "slug ِ یکی از دسته‌ها"}
نام‌ها و قیمت‌ها باید مناسبِ همین فروشگاه و بازارِ ایران باشد. slugها فقط حروفِ کوچکِ انگلیسی، عدد و خط‌تیره."""


def _clean_samples(data):
    """خروجیِ AI ⇒ دادهٔ امن و یکتا. ⇒ dict یا None"""
    slug = lambda s: re.sub(r'[^a-z0-9-]+', '-', str(s or '').lower()).strip('-')[:60]
    cats, seen = [], set()
    for c in data.get('categories') or []:
        if isinstance(c, dict) and c.get('name') and slug(c.get('slug')) and slug(c['slug']) not in seen:
            seen.add(slug(c['slug']))
            cats.append({'name': str(c['name'])[:120], 'slug': slug(c['slug'])})
    prods, pseen = [], set()
    for p in data.get('products') or []:
        if not (isinstance(p, dict) and p.get('name') and slug(p.get('slug'))) or slug(p['slug']) in pseen:
            continue
        pseen.add(slug(p['slug']))
        try:
            price = max(0, int(float(str(p.get('price') or 0).replace(',', ''))))
            stock = max(0, int(float(str(p.get('stock') or 10))))
        except ValueError:
            price, stock = 0, 10
        prods.append({'name': str(p['name'])[:200], 'slug': slug(p['slug']), 'description': str(p.get('description') or '')[:600],
                      'price': price, 'stock': stock, 'category': slug(p.get('category')) if slug(p.get('category')) in seen else ''})
    if not cats and not prods:
        return None
    return {'categories': cats, 'products': prods}


def generate_frontend(project, brief, include_shell=True, page_ids=None, include_samples=False):
    """از توضیحِ متنی ⇒ پوسته/هدر/فوتر + بدنهٔ صفحه‌ها (+ دادهٔ نمونه). هر صفحه یک فراخوانیِ جدا."""
    prop = _new_proposal(project, 'generate_frontend', 'فرانتِ اولیه از توضیح', brief)
    return _launch(prop, _do_generate_frontend, brief, include_shell, page_ids, include_samples)


def _do_generate_frontend(proposal, brief, include_shell, page_ids, include_samples=False):
    project = proposal.project
    provider = get_provider()
    ctx = _project_ctx(project)
    sh = _shared(project)
    url_names = set(ctx['url_names'])
    summaries, order = [], 0
    if include_shell:
        data = _call(provider, proposal, SYSTEM_SHELL, {
            'task': 'shell', 'brief': brief, 'project': ctx,
            'current_header': sh['header'], 'current_footer': sh['footer'],
            'base_css_root': _base_root(sh['base_css']),
            'base_rules_header_footer_hero': _rules_for(sh['base_css'], ('site-header', 'main-nav', 'cart-link', 'brand',
                                                                         'badge', 'site-footer', 'hero', '.btn')),
        })
        summaries.append(data.get('summary', ''))
        for key, target, label in (('header', 'shared_header', 'هدر'), ('footer', 'shared_footer', 'فوتر')):
            new = data.get(key)
            if 'nb-header' in (sh[key] or '') or 'nb-footer' in (sh[key] or ''):
                continue       # سربرگ و پابرگِ دیداری با کلیک ویرایش می‌شوند؛ کد جایشان را نمی‌گیرد
            if new and str(new).strip():
                _add_change(proposal, target, label, sh[key], new, url_names=url_names, order=order)
                order += 1
        theme = data.get('theme_css') or data.get('base_css') or ''
        if str(theme).strip():
            _add_change(proposal, 'shared_css', 'پوستهٔ CSS (روی CSSِ پایه)', sh['base_css'],
                        _with_theme(sh['base_css'], str(theme), brief), order=order)
            order += 1
    if include_samples and any(a.name == 'catalog' for a in project.apps.all()):
        data = _call(provider, proposal, SYSTEM_SAMPLES, {'task': 'samples', 'brief': brief,
                                                         'site_title': ctx['site_title']})
        samples = _clean_samples(data)
        if samples:
            summaries.append('دادهٔ نمونه: %d دسته، %d محصول' % (len(samples['categories']), len(samples['products'])))
            _add_change(proposal, 'sample_data', 'دسته و محصولِ نمونه', '', samples, order=order)
            order += 1
    pages = project.pages.exclude(kind='imported')
    if page_ids:
        pages = pages.filter(pk__in=page_ids)
    for pg in pages:
        if 'class="nb-' in (pg.body_html or ''):
            # صفحهٔ دیداری: بازنویسیِ کامل کلاس‌ها را می‌برد و صفحه یک بلوکِ کد می‌شود؛ فقط متن‌ها عوض می‌شوند
            data = _call(provider, proposal, SYSTEM_EDIT_PAGE, {
                'task': 'edit_page', 'project': ctx,
                'instruction': 'متن‌های این صفحه را مناسبِ این کسب‌وکار بازنویسی کن: %s' % brief,
                'page': {'slug': pg.slug, 'title': pg.title, 'kind': pg.kind},
                'available_variables': PAGE_VARS.get(pg.kind, PAGE_VARS['static']),
                'current_body': pg.body_html, 'current_css': pg.css,
                'visual_editor_note': 'این صفحه بلوک‌بندی شده است. ساختار و کلاس‌های nb-* و b-* را دقیقاً نگه دار و فقط متن‌ها را عوض کن. css را null بگذار.',
            })
        else:
            data = _call(provider, proposal, SYSTEM_PAGE, {
                'task': 'page', 'brief': brief, 'project': ctx,
                'slug': pg.slug, 'title': pg.title, 'kind': pg.kind,
                'available_variables': PAGE_VARS.get(pg.kind, PAGE_VARS['static']),
                'current_body': pg.body_html, 'current_css': pg.css,
            })
        summaries.append('/%s: %s' % (pg.slug, data.get('summary', '')))
        if data.get('body_html'):
            _add_change(proposal, 'page_body', '%s  (/%s)' % (pg.title, pg.slug), pg.body_html, data['body_html'],
                        page=pg, url_names=url_names, order=order)
            order += 1
        if data.get('css') is not None and str(data['css']).strip() != (pg.css or '').strip():
            _add_change(proposal, 'page_css', '%s — CSS' % pg.title, pg.css, data['css'], page=pg, order=order)
            order += 1
    return _finish(proposal, '\n'.join(s for s in summaries if s))


# ──────────────────────────────────────────────── فازِ ۰۷: ویرایشِ یک صفحه/بخش
SYSTEM_EDIT_PAGE = """تو ویرایشگرِ فرانت‌اندِ یک فروشگاهِ Django هستی.
فقط بدنهٔ همین یک صفحه (و در صورتِ نیاز CSSِ همین صفحه) را طبقِ دستورِ کاربر تغییر بده.
هر چه کاربر نخواسته، دست نزن. هدر، فوتر، صفحه‌های دیگر و بک‌اند در دسترسِ تو نیستند.
%s
کلیدهای JSON: summary, body_html (کاملِ بدنهٔ جدید), css (کاملِ CSSِ جدید یا null اگر تغییری ندارد).""" % RULES_FA

SYSTEM_EDIT_SHARED = """تو ویرایشگرِ فرانت‌اندِ یک فروشگاهِ Django هستی.
فقط همین بخشِ مشترک (kind) را طبقِ دستورِ کاربر تغییر بده و کاملش را برگردان.
%s
کلیدهای JSON: summary, content.""" % RULES_FA

SYSTEM_EDIT_CSS = """تو ویرایشگرِ CSSِ یک فروشگاهِ Django هستی. فایلِ CSSِ مشترک را عوض نکن؛
فقط قاعده‌هایی را بنویس که طبقِ دستورِ کاربر باید اضافه یا بازنویسی شوند (بعد از فایلِ فعلی می‌آیند و بر آن غلبه می‌کنند).
انتخابگرها را از روی HTML ِ واقعی (header_html, footer_html) و قاعده‌های فعلی (current_css) بنویس، نه حدسی
(مثلاً نامِ فروشگاه <a class="brand"> است و لینکِ فعال کلاسِ on دارد) و دستِ کم به همان دقتِ قاعدهٔ فعلی باشند تا اعمال شوند.
اگر رنگِ متنی را عوض می‌کنی، پس‌زمینهٔ همان عنصر را در current_css ببین تا خوانا بماند.
فقط چیزی را عوض کن که کاربر نام برده: اگر دستور دربارهٔ هدر یا فوتر است، همهٔ انتخابگرها را با .site-header یا .site-footer
شروع کن و قاعدهٔ سراسری (مثل .btn، a، body، .card) ننویس.
پاسخ فقط JSON با کلیدهای summary و css."""

SYSTEM_EDIT_FILE = """تو ویرایشگرِ قالب‌های یک پروژهٔ Django هستی.
کلِ فایلِ قالب را طبقِ دستورِ کاربر تغییر بده و کاملِ فایلِ جدید را برگردان؛ ساختار، extends/block و تگ‌های جنگو را حفظ کن.
هر چه کاربر نخواسته، دست نزن. پاسخ فقط JSON با کلیدهای summary و content."""


def edit_page(page, instruction, section=None):
    title = ('ویرایشِ %s' % page.title) if page.is_imported else ('ویرایشِ «%s» (/%s)' % (page.title, page.slug))
    prop = _new_proposal(page.project, 'edit_page', title, instruction)
    return _launch(prop, _do_edit_page, page, instruction, section)


def _do_edit_page(proposal, page, instruction, section):
    project = page.project
    provider = get_provider()
    if page.is_imported:
        data = _call(provider, proposal, SYSTEM_EDIT_FILE, {
            'task': 'edit_file', 'instruction': instruction, 'file': page.file_path,
            'current': page.body_html})
        _add_change(proposal, 'page_file', page.file_path, page.body_html, data.get('content'), page=page)
        return _finish(proposal, data.get('summary'))
    ctx = _project_ctx(project)
    sh = _shared(project)
    payload = {
        'task': 'edit_page', 'instruction': instruction,
        'page': {'slug': page.slug, 'title': page.title, 'kind': page.kind},
        'available_variables': PAGE_VARS.get(page.kind, PAGE_VARS['static']),
        'project': ctx,
        'header_reference_readonly': sh['header'][:1500],
        'current_body': page.body_html, 'current_css': page.css,
    }
    if section:
        payload['focus_section'] = section
    if hasattr(page, 'design'):
        # صفحه با ویرایشگرِ دیداری ساخته شده: کلاس‌های b-xxxx نشانهٔ بلوک‌اند؛ اگر بمانند صفحه بعد از AI هم با کلیک ویرایش می‌شود
        payload['visual_editor_note'] = ('این صفحه بلوک‌بندی شده است. ساختار و کلاس‌های nb-* و b-* را حفظ کن، '
                                         'و تا می‌توانی فقط متن‌ها را عوض کن یا بخشِ تازه با <section> اضافه کن.')
    data = _call(provider, proposal, SYSTEM_EDIT_PAGE, payload)
    url_names = set(ctx['url_names'])
    if data.get('body_html'):
        _add_change(proposal, 'page_body', '%s  (/%s)' % (page.title, page.slug), page.body_html, data['body_html'],
                    page=page, url_names=url_names, order=0)
    if data.get('css') is not None and str(data['css']).strip() != (page.css or '').strip():
        _add_change(proposal, 'page_css', '%s — CSS' % page.title, page.css, data['css'], page=page, order=1)
    return _finish(proposal, data.get('summary'))


def edit_shared(project, kind, instruction):
    part, _ = SharedPart.objects.get_or_create(project=project, kind=kind)
    prop = _new_proposal(project, 'edit_shared', 'ویرایشِ %s' % part.get_kind_display(), instruction)
    return _launch(prop, _do_edit_shared, kind, instruction)


def _do_edit_shared(proposal, kind, instruction):
    project = proposal.project
    part, _ = SharedPart.objects.get_or_create(project=project, kind=kind)
    current = part.content if part.content.strip() else _shared(project)[kind]
    ctx = _project_ctx(project)
    if kind == 'base_css':
        data = _call(get_provider(), proposal, SYSTEM_EDIT_CSS, {
            'task': 'edit_shared', 'kind': kind, 'instruction': instruction, 'project': ctx,
            'header_html': _shared(project)['header'], 'footer_html': _shared(project)['footer'],
            'current_css': current[-20000:]})
    else:
        data = _call(get_provider(), proposal, SYSTEM_EDIT_SHARED, {
            'task': 'edit_shared', 'kind': kind, 'instruction': instruction, 'project': ctx, 'current': current})
    target = {'header': 'shared_header', 'footer': 'shared_footer', 'base_css': 'shared_css'}[kind]
    new = data.get('content')
    if kind == 'base_css':
        # CSS همیشه «افزوده» است: مدل فقط قاعده‌های تازه/بازنویسی را می‌دهد و ته فایل می‌نشیند؛
        # پس هیچ‌وقت کلاسی از CSSِ پایه گم نمی‌شود.
        rules = data.get('css') or new or ''
        new = '%s\n\n/* ── ویرایشِ هوشِ مصنوعی: %s ── */\n%s\n' % (current.rstrip(), instruction[:60].replace('*/', ''),
                                                                str(rules).strip()) if str(rules).strip() else None
    _add_change(proposal, target, part.get_kind_display(), current, new, url_names=set(ctx['url_names']),
                scope_note=(kind == 'base_css'))
    return _finish(proposal, data.get('summary'))


def edit_view(view, instruction):
    prop = _new_proposal(view.app.project, 'edit_view', 'ویرایشِ قالبِ %s.%s' % (view.app.name, view.name), instruction)
    return _launch(prop, _do_edit_view, view, instruction)


def _do_edit_view(proposal, view, instruction):
    project = view.app.project
    ctx = _project_ctx(project)
    fields = [{'name': f.name, 'label': f.verbose_name_fa, 'type': f.field_type}
              for f in view.model.fields.all()] if view.model_id else []
    data = _call(get_provider(), proposal, SYSTEM_EDIT_PAGE, {
        'task': 'edit_view', 'instruction': instruction, 'project': ctx,
        'view': {'name': view.name, 'kind': view.kind, 'model': view.model.name if view.model_id else None,
                 'context_variable': view.context_object_name or ('%s_list' % view.model.snake if view.model_id else 'object'),
                 'model_fields': fields},
        'available_variables': 'object / object_list / form / page_obj / is_paginated + فیلدهای مدل',
        'current_body': view.template_body, 'current_css': view.css,
    })
    if data.get('body_html'):
        _add_change(proposal, 'view_template', '%s.%s' % (view.app.name, view.name), view.template_body,
                    data['body_html'], view=view, url_names=set(ctx['url_names']), order=0)
    if data.get('css') is not None and str(data['css']).strip() != (view.css or '').strip():
        _add_change(proposal, 'view_css', '%s — CSS' % view.name, view.css, data['css'], view=view, order=1)
    return _finish(proposal, data.get('summary'))


# ──────────────────────────────────────────────── دستیارِ مدل (Model Assistant)
SYSTEM_MODELS = """تو معمارِ دیتابیسِ یک پروژهٔ Django هستی. از توضیحِ کاربر، اپ/مدل/فیلدهای لازم را پیشنهاد بده.
فقط JSON با این ساختار:
{"summary": "...", "apps": [{"name": "snake_case", "verbose": "فارسی", "models": [{"name": "CamelCase", "verbose": "فارسی", "verbose_plural": "فارسی",
  "fields": [{"name": "snake", "verbose": "فارسی", "type": "CharField|TextField|IntegerField|PositiveIntegerField|DecimalField|BooleanField|DateField|DateTimeField|EmailField|URLField|SlugField|ImageField|FileField|ForeignKey|ManyToManyField|OneToOneField",
  "max_length": 120, "null": false, "blank": false, "unique": false, "default": "…", "auto_now_add": false, "related_model": "app.Model", "on_delete": "CASCADE|PROTECT|SET_NULL", "related_name": "…"}]}]}]}
- اپ‌ها و مدل‌هایی که از قبل در پروژه هستند را دوباره نساز؛ می‌توانی به آن‌ها رابطه بدهی (related_model مثل catalog.Product).
- نام‌ها انگلیسی، برچسب‌ها فارسی."""


def suggest_models(project, description):
    prop = _new_proposal(project, 'suggest_models', 'پیشنهادِ مدل', description)
    return _launch(prop, _do_suggest_models, description)


def _do_suggest_models(proposal, description):
    project = proposal.project
    existing = [{'app': a.name, 'models': [{'name': m.name, 'fields': [f.name for f in m.fields.all()]}
                                           for m in a.models.all()]} for a in project.apps.all()]
    data = _call(get_provider(), proposal, SYSTEM_MODELS, {
        'task': 'suggest_models', 'description': description, 'existing': existing})
    apps = data.get('apps') or []
    if not isinstance(apps, list) or not apps:
        raise AiError('هیچ مدلی پیشنهاد نشد.')
    _add_change(proposal, 'model_spec', 'ساختارِ پیشنهادی', '', apps)
    return _finish(proposal, data.get('summary'))


def _apply_model_spec(project, spec):
    """پیشنهادِ مدل‌ها ⇒ ردیف‌های App/Model/Field (چیزهای موجود رد می‌شوند)."""
    created = []
    valid_types = {t for t, _ in Field.TYPES} - {'custom'}
    pending_rel = []
    for a in spec:
        if not isinstance(a, dict):
            continue
        app, made_app = App.objects.get_or_create(
            project=project, name=re.sub(r'[^a-z0-9_]', '', (a.get('name') or 'extra').lower()) or 'extra',
            defaults={'verbose_name_fa': a.get('verbose') or '', 'order': project.apps.count() * 10 + 100})
        if made_app and not app.url_prefix:
            app.url_prefix = app.name + '/'
            app.save(update_fields=['url_prefix'])
        if not app.managed:
            continue                      # به اپِ واردشده دست نمی‌زنیم
        for m in a.get('models') or []:
            mdl, made = Model.objects.get_or_create(
                app=app, name=re.sub(r'\W', '', m.get('name') or 'Item') or 'Item',
                defaults={'verbose_name_fa': m.get('verbose') or '',
                          'verbose_plural_fa': m.get('verbose_plural') or '',
                          'order': app.models.count() * 10 + 10})
            if made:
                created.append('%s.%s' % (app.name, mdl.name))
            for i, f in enumerate(m.get('fields') or [], 1):
                name = re.sub(r'[^a-z0-9_]', '', (f.get('name') or '').lower())
                if not name or Field.objects.filter(model=mdl, name=name).exists():
                    continue
                ftype = f.get('type') if f.get('type') in valid_types else 'CharField'
                fld = Field(model=mdl, name=name, verbose_name_fa=str(f.get('verbose') or '')[:80], field_type=ftype,
                            max_length=f.get('max_length') if isinstance(f.get('max_length'), int) else None,
                            null=bool(f.get('null')), blank=bool(f.get('blank')), unique=bool(f.get('unique')),
                            auto_now_add=bool(f.get('auto_now_add')), auto_now=bool(f.get('auto_now')),
                            default=_safe_default(f.get('default'), ftype),
                            on_delete=f.get('on_delete') if f.get('on_delete') in dict(Field.ON_DELETE) else 'CASCADE',
                            related_name=re.sub(r'[^a-z0-9_]', '', str(f.get('related_name') or '').lower()),
                            order=i * 10)
                if ftype in Field.RELATIONAL:
                    if fld.on_delete == 'SET_NULL':
                        fld.null = True
                    pending_rel.append((fld, str(f.get('related_model') or '')))
                else:
                    fld.save()
    for fld, ref in pending_rel:
        target = None
        if ref:
            app_name, _, model_name = ref.partition('.')
            if model_name:
                target = Model.objects.filter(app__project=project, app__name=app_name, name=model_name).first()
            else:
                target = Model.objects.filter(app__project=project, name=ref).first()
        if target:
            fld.related_model = target
        elif ref.lower() in ('user', 'auth.user', 'settings.auth_user_model'):
            fld.related_ref = 'settings.AUTH_USER_MODEL'
        else:
            continue                       # مقصدِ ناشناخته ⇒ این فیلد را نساز، کد نشکند
        fld.save()
    return created


def _safe_default(value, ftype):
    """پیش‌فرضِ پیشنهادیِ AI عیناً در کد می‌نشیند؛ فقط شکل‌های امن پذیرفته می‌شود."""
    if value is None or value == '':
        return ''
    if isinstance(value, bool):
        return 'True' if value else 'False'
    if isinstance(value, (int, float)):
        return repr(value)
    v = str(value).strip()
    if v in ('True', 'False', 'None', 'timezone.now', 'uuid.uuid4', 'dict', 'list'):
        return '' if v == 'None' else v
    if re.fullmatch(r'-?\d+(\.\d+)?', v):
        return v
    if ftype in ('BooleanField',):
        return 'True' if v.lower() in ('true', '1', 'yes') else 'False'
    return repr(v)                          # متن ⇒ رشتهٔ پایتونیِ امن


# ──────────────────────────────────────────────── اعمال / رد / بازگردانی
def _write_change(change, content):
    """محتوا را در هدفِ تغییر می‌نشاند (متادیتا)؛ فایل‌ها با تولیدِ کد نوشته می‌شوند."""
    t = change.target
    if t in ('page_body', 'page_file') and change.page_id:
        change.page.body_html = content
        change.page.save(update_fields=['body_html'])
    elif t == 'page_css' and change.page_id:
        change.page.css = content
        change.page.save(update_fields=['css'])
    elif t.startswith('shared_'):
        kind = {'shared_header': 'header', 'shared_footer': 'footer', 'shared_css': 'base_css'}[t]
        part, _ = SharedPart.objects.get_or_create(project=change.proposal.project, kind=kind)
        part.content = content
        part.save()
    elif t == 'view_template' and change.view_id:
        change.view.template_body = content
        change.view.save(update_fields=['template_body'])
    elif t == 'view_css' and change.view_id:
        change.view.css = content
        change.view.save(update_fields=['css'])
    elif t == 'sample_data':
        path = os.path.join(str(change.proposal.project.path), 'fixtures', 'sample_data.json')
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as fh:
            fh.write(json.dumps(json.loads(content), ensure_ascii=False, indent=2) + '\n')
        return None
    elif t == 'model_spec':
        return _apply_model_spec(change.proposal.project, json.loads(content) if content.strip() else [])
    return None


def _current_content(change):
    t = change.target
    if t in ('page_body', 'page_file') and change.page_id:
        return change.page.body_html
    if t == 'page_css' and change.page_id:
        return change.page.css
    if t.startswith('shared_'):
        kind = {'shared_header': 'header', 'shared_footer': 'footer', 'shared_css': 'base_css'}[t]
        part = SharedPart.objects.filter(project=change.proposal.project, kind=kind).first()
        return part.content if part and part.content.strip() else _shared(change.proposal.project)[kind]
    if t == 'view_template' and change.view_id:
        return change.view.template_body
    if t == 'view_css' and change.view_id:
        return change.view.css
    return None


def _regenerate(project, message):
    ok, summary, detail = gen_services.generate(project, message=message)
    if preview_runner.status(project)[0]:
        preview_runner.stop(project)
        try:
            preview_runner.start(project)
        except Exception:  # noqa
            pass
    return ok, detail


def apply_proposal(proposal, change_ids=None):
    """اعمالِ تغییرهای معتبر + تولیدِ کد. (ok, message)"""
    if proposal.status != 'pending':
        return False, 'این پیشنهاد «%s» است و اعمال نمی‌شود.' % proposal.get_status_display()
    changes = proposal.changes.filter(valid=True)
    if change_ids is not None:
        changes = changes.filter(pk__in=change_ids)
    if not changes.exists():
        return False, 'تغییرِ معتبری برای اعمال انتخاب نشده.'
    notes, applied = [], 0
    for ch in changes:
        # تعارض (idea.md §۹): اگر از زمانِ پیشنهاد، هدف دستی عوض شده باشد، کورکورانه اعمال نکن
        current = _current_content(ch)
        if ch.target not in ('model_spec', 'sample_data') and current is not None and current.strip() != (ch.old_content or '').strip():
            ch.valid = False
            ch.issues = (ch.issues + '\n' if ch.issues else '') + 'از زمانِ پیشنهاد، این بخش دستی تغییر کرده؛ اعمال نشد.'
            ch.save(update_fields=['valid', 'issues'])
            notes.append('«%s» به‌خاطرِ تعارض اعمال نشد.' % ch.label)
            continue
        made = _write_change(ch, ch.new_content)
        applied += 1
        if made:
            notes.append('ساخته شد: ' + '، '.join(made))
    if not applied:
        return False, ' '.join(notes) or 'هیچ تغییری اعمال نشد.'
    # تغییرهایی که انتخاب نشدند از این پیشنهاد کنار می‌روند (تا «بازگردانی» فقط اعمال‌شده‌ها را برگرداند)
    if change_ids is not None:
        proposal.changes.exclude(pk__in=change_ids).update(valid=False, issues='انتخاب نشد؛ اعمال نشد.')
    proposal.status = 'applied'
    proposal.applied_at = timezone.now()
    proposal.save(update_fields=['status', 'applied_at'])
    ok, detail = _regenerate(proposal.project, 'AI: %s' % (proposal.title or proposal.get_task_display()))
    if ok and changes.filter(target='sample_data').exists():
        okm, _ = gen_services.migrate(proposal.project)
        r = gen_services._run(proposal.project, ['manage.py', 'load_sample_data'], 180)
        notes.append(('دادهٔ نمونه بارگذاری شد: ' + r.stdout.strip()[-120:]) if okm and r.returncode == 0
                     else 'دادهٔ نمونه بارگذاری نشد: ' + (r.stderr or r.stdout)[-300:])
    msg = 'اعمال شد و کد تولید شد.' if ok else 'اعمال شد ولی تولیدِ کد خطا داد — «نمای کلی» را ببین (می‌توانی بازگردانی کنی).'
    if notes:
        msg += ' ' + ' '.join(notes)
    return ok, msg


def reject_proposal(proposal):
    if proposal.status in ('pending', 'running'):
        proposal.status = 'rejected'
        proposal.save(update_fields=['status'])


def revert_proposal(proposal):
    """«قبل» را برمی‌گرداند — فقط اگر از اعمال به بعد کسی دستی عوضش نکرده باشد."""
    if proposal.status != 'applied':
        return False, 'فقط پیشنهادِ اعمال‌شده بازگردانی می‌شود.'
    notes = []
    for ch in proposal.changes.filter(valid=True):
        if ch.target == 'model_spec':
            notes.append('مدل‌های ساخته‌شده خودکار حذف نمی‌شوند (از «بک‌اند» حذف کن).')
            continue
        if ch.target == 'sample_data':
            notes.append('دادهٔ نمونه در دیتابیسِ سایت می‌ماند (از ادمینِ سایت پاک کن).')
            continue
        current = _current_content(ch)
        if current is not None and current.strip() != (ch.new_content or '').strip():
            notes.append('«%s» بعد از اعمال دستی عوض شده؛ برنگشت.' % ch.label)
            continue
        _write_change(ch, ch.old_content)
    proposal.status = 'reverted'
    proposal.save(update_fields=['status'])
    ok, _ = _regenerate(proposal.project, 'بازگردانیِ AI: %s' % (proposal.title or proposal.pk))
    return True, ('بازگردانی شد و کد دوباره تولید شد. ' if ok else 'بازگردانی شد ولی تولیدِ کد خطا داد. ') + ' '.join(notes)
