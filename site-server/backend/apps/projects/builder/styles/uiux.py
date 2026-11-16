# -*- coding: utf-8 -*-
"""دادهٔ کاملِ «ui-ux-pro-max-skill» (MIT، Next Level Builder): سبک‌ها، پالت‌ها، جفتِ قلم‌ها، رهنمودهای UX، الگوهای صفحهٔ فرود، نمودارها، محصولات،
استدلالِ طراحی، پشته‌ها، آیکون‌ها، حرکت، اپ، کارایی، اسلاید، هویتِ برند، قلم‌های گوگل و مستندها — جست‌وجوپذیر، بی‌اینترنت.

فایل‌های dataset/uiux/<نوع>.json را import_uiux_full.py از آینهٔ مخزن (/opt/nm-mirror/ui-ux-pro-max-skill) ساخته؛ مجوز و نشانیِ مخزن کنارشان است.
هر نوع فقط وقتی خواسته شود خوانده و در حافظه نگه داشته می‌شود (کل ۲٫۳ مگابایت؛ بیشترش «پشته‌ها»، «قلم‌های گوگل» و «مستندها» است).
"""
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, 'dataset', 'uiux')
KINDS = ('styles', 'colors', 'fonts', 'ux', 'landing', 'motion', 'charts', 'products', 'reasoning', 'icons', 'app', 'react', 'stacks', 'google_fonts', 'slides', 'brand', 'docs')

#: نامِ فارسی و توضیحِ هر نوعِ داده (برای صفحهٔ «منبع‌های طراحی»)
KIND_FA = {
    'styles': ('سبک‌های طراحی', 'هر سبک یک ردیف: کلیدواژه‌ها، رنگ‌ها، افکت‌ها، کجا بیاید و کجا نه، چک‌لیستِ اجرا و سطحِ پشتیبانیِ راست‌به‌چپ.'),
    'colors': ('پالت‌های رنگ', 'یک پالتِ کامل برای هر نوعِ محصول: اصلی، تأکید، زمینه، متن، کارت، حاشیه و رنگِ خطا.'),
    'fonts': ('جفتِ قلم‌ها', 'جفتِ قلمِ تیتر و متنِ لاتین؛ کنارِ هر کدام جفتِ فارسیِ مجوزدارِ سایت‌ساز نشان داده می‌شود.'),
    'ux': ('رهنمودهای تجربهٔ کاربری', 'کار درست و نادرست با نمونه؛ شدتِ هر مورد مشخص است.'),
    'landing': ('الگوهای صفحهٔ فرود', 'ترتیبِ بخش‌ها، جای دعوت به اقدام، راهبردِ رنگ و بهینه‌سازیِ تبدیل.'),
    'motion': ('حرکت و انیمیشن', 'مدت، منحنی، محرک و نکتهٔ کارایی برای هر نوعِ حرکت.'),
    'charts': ('نوعِ نمودار', 'برای هر نوعِ داده کدام نمودار، چه زمانی نه، رنگ و دسترس‌پذیری.'),
    'products': ('توصیهٔ سبک برای هر نوعِ محصول', 'برای هر نوعِ کسب‌وکار: سبکِ اصلی و جایگزین، الگوی صفحه، داشبورد و ملاحظات.'),
    'reasoning': ('قاعده‌های تصمیمِ طراحی', 'برای هر دسته: الگو، اولویتِ سبک، حال‌وهوای رنگ و قلم، قاعده‌ها و ضدالگوها.'),
    'icons': ('آیکون‌ها', 'فهرستِ آیکونِ پیشنهادی با نقشِ معنایی و کدِ وارد کردن.'),
    'app': ('رهنمودهای رابطِ اپ', 'نکته‌های اپِ موبایل (لمس، ناوبری، بازخورد…).'),
    'react': ('کارایی در React', 'قاعده‌های کارایی با مثالِ خوب و بد.'),
    'stacks': ('یادداشت‌های پشتهٔ فناوری', 'رهنمودِ هر پشته (html-tailwind، react، nextjs، vue، svelte، shadcn و ...).'),
    'google_fonts': ('قلم‌های گوگل', 'کلِ فهرستِ قلم‌های گوگل با نشانِ «عربی/فارسی‌پذیر» و آنچه در سایت‌ساز هست.'),
    'slides': ('اسلاید', 'چیدمان، راهبرد، نمودار و متن‌نویسیِ اسلاید.'),
    'brand': ('هویتِ برند', 'لوگو، رنگ، آیکن و محصولاتِ هویتی (CIP).'),
    'docs': ('مستندها', 'مرجع‌های نوشتاریِ مخزن (توکن‌ها، تیلویند، shadcn، برند، اسلاید…).'),
}

#: ستون‌هایی که در جست‌وجو می‌آیند (اولی وزنِ بیشتر دارد)
SEARCH_FIELDS = {
    'styles': ('name', 'id', 'keywords', 'best_for', 'effects', 'type', 'aliases', 'ai_prompt'),
    'colors': ('product', 'notes'),
    'fonts': ('name', 'heading', 'body', 'mood', 'best_for', 'category'),
    'ux': ('issue', 'category', 'description', 'platform'),
    'landing': ('name', 'keywords', 'sections', 'aliases'),
    'motion': ('category', 'keywords', 'trigger'),
    'charts': ('data_type', 'keywords', 'best', 'when'),
    'products': ('product', 'keywords', 'primary_style', 'landing', 'notes'),
    'reasoning': ('category', 'pattern', 'style_priority', 'rules', 'reasoning'),
    'icons': ('name', 'keywords', 'category', 'role'),
    'app': ('issue', 'category', 'keywords', 'description'),
    'react': ('issue', 'category', 'keywords', 'description'),
    'stacks': ('guideline', 'category', 'stack', 'description'),
    'google_fonts': ('family', 'category', 'classes', 'keywords'),
    'slides': ('layout_name', 'name', 'keywords', 'file', 'use_case'),
    'brand': ('deliverable', 'name', 'keywords', 'file', 'description'),
    'docs': ('title', 'path', 'skill', 'text'),
}
_cache = {}


def rows(kind):
    """همهٔ ردیف‌های یک نوع (فهرستِ دیکشنری)؛ فایلِ ناموجود ⇒ فهرستِ خالی."""
    if kind not in KINDS:
        return []
    if kind not in _cache:
        try:
            with open(os.path.join(DATA_DIR, kind + '.json'), encoding='utf-8') as fh:
                _cache[kind] = json.load(fh)
        except (OSError, ValueError):
            _cache[kind] = []
    return _cache[kind]


def index():
    try:
        with open(os.path.join(DATA_DIR, 'index.json'), encoding='utf-8') as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def data():
    """سازگاریِ قدیمی: {نوع: ردیف‌ها}؛ فقط نوع‌های خواسته‌شده بار می‌شوند."""
    return {k: rows(k) for k in KINDS}


def attribution():
    d = index()
    return {'source': d.get('source', ''), 'license': d.get('license', ''), 'copyright': d.get('copyright', ''), 'commit': d.get('commit', ''),
            'commit_date': d.get('commit_date', ''), 'retrieved': d.get('retrieved', ''), 'mirror': d.get('mirror', ''),
            'counts': {k: len(rows(k)) for k in KINDS}, 'skipped': d.get('skipped', {})}


def _words(text):
    return [w for w in re.split(r'[^\w؀-ۿ]+', (text or '').lower()) if len(w) > 1]


def _score(row, q_words, fields, extra=''):
    hay = ' '.join(str(row.get(f, '')) for f in fields).lower() + ' ' + extra.lower()
    if not hay.strip():
        return 0
    score = 0
    first = str(row.get(fields[0], '')).lower() + ' ' + extra.lower()
    for w in q_words:
        if w in hay:
            score += 3 if w in first else 1
    return score


def search(kind, query, limit=8, offset=0, where=None, extra=None):
    """⇒ ردیف‌های مرتبط‌ترین (امتیازِ کلمه‌های مشترک). where: {ستون: مقدار} فیلترِ دقیق (بی‌توجه به بزرگ/کوچکیِ حروف).
    extra(row) ⇒ متنِ افزوده برای جست‌وجو (مثلاً نامِ فارسیِ سبک)."""
    if kind not in SEARCH_FIELDS:
        return []
    words = _words(query)
    out = []
    for i, r in enumerate(rows(kind)):
        if where and any(str(r.get(k, '')).lower() != str(v).lower() for k, v in where.items() if v not in (None, '')):
            continue
        ex = extra(r) if extra else ''
        s = _score(r, words, SEARCH_FIELDS[kind], ex) if words else 1
        if s > 0:
            out.append((s, i, r))
    if words:
        out.sort(key=lambda x: (-x[0], x[1]))
    return [r for _s, _i, r in out[offset:offset + limit]] if limit else [r for _s, _i, r in out[offset:]]


def count(kind, query='', where=None, extra=None):
    if not _words(query) and not where:
        return len(rows(kind))
    words = _words(query)
    n = 0
    for r in rows(kind):
        if where and any(str(r.get(k, '')).lower() != str(v).lower() for k, v in where.items() if v not in (None, '')):
            continue
        if not words or _score(r, words, SEARCH_FIELDS[kind], extra(r) if extra else '') > 0:
            n += 1
    return n


def by_id(kind, key, value):
    for r in rows(kind):
        if str(r.get(key, '')).lower() == str(value).lower():
            return r
    return None


def reference_for(style):
    """سطرهای مرجعِ یک سبکِ ما در دادهٔ ui-ux-pro-max (برای نمایش و پرامپت)."""
    ref = style.get('uiux') or {}
    return {'style': by_id('styles', 'id', ref.get('style_id', '')), 'font_pairing': by_id('fonts', 'name', ref.get('font_pairing', '')),
            'palette': by_id('colors', 'product', ref.get('palette', ''))}


__all__ = ['rows', 'index', 'data', 'search', 'count', 'attribution', 'by_id', 'reference_for', 'KINDS', 'KIND_FA', 'SEARCH_FIELDS']
