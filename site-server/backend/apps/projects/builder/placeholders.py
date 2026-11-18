# -*- coding: utf-8 -*-
"""«هنوز نمونه است» — جاهایی از سایت که پیش از انتشار روی اینترنت باید با چیزِ واقعی عوض شوند.

قالب‌های آماده، قطعه‌ها و بلوک‌های تازه همه متنِ نمونه دارند («این متن نمونه است…»، شمارهٔ ۰۲۱-۱۲۳۴۵۶۷۸، info@example.com،
پیوندِ «#»). اگر کسی بی‌نگاه‌کردن «انتشار» را بزند همین‌ها روی اینترنت می‌رود. این ماژول آن‌ها را پیدا می‌کند و هر کدام را
به‌شکلِ یک هشدارِ رندر با «نوع» (`kind`) برمی‌گرداند؛ پس کانواس، پیش‌نمایش، انتشار و بررسیِ پیشنهادهای AI همه از یک راه می‌گذرند.

نوع‌ها:
  sample   متنی که عیناً از قالب یا قطعهٔ آماده مانده (یا «lorem ipsum» و «قیمتِ نمونه»)
  contact  شماره یا ایمیل یا نشانیِ ساختگی (۰۲۱-۱۲۳۴۵۶۷۸، example.com)
  link     دکمه یا پیوندی که هنوز به جایی وصل نیست («#» یا خالی، درحالی‌که متنِ دکمه هست)
  alt      تصویر بی‌توضیح (برای نابینایان و گوگل)
  media    تصویر یا ویدیویی که هنوز انتخاب نشده

تشخیصِ «متنِ نمونه» از خودِ منبعِ حقیقت می‌آید (پیش‌فرضِ بلوک‌ها و قطعه‌ها و قالب‌های آماده)، نه از فهرستِ جدایی که کهنه شود.
چیزی که کاربر خودش نوشته هرگز نمونه حساب نمی‌شود مگر عیناً همان جملهٔ نمونه باشد.
"""
import re
from functools import lru_cache

from .clean import walk

KIND_LABEL = {
    'sample': 'متنِ نمونه',
    'contact': 'شماره یا نشانیِ ساختگی',
    'link': 'پیوندِ خالی',
    'alt': 'تصویرِ بی‌توضیح',
    'media': 'تصویر یا ویدیوی انتخاب‌نشده',
    'static': 'قطعهٔ ثابت (بدونِ حرکت)',
}
KINDS = frozenset(KIND_LABEL)

TEXT_KINDS = ('text', 'textarea', 'rich')
MIN_SAMPLE_CHARS = 14          # جمله‌هایی که کوتاه‌تر از این‌اند («پایه»، «تماس بگیرید») نمونه حساب نمی‌شوند
MIN_SAMPLE_WORDS = 3
# جمله‌هایی که پیش‌فرضِ قالب‌اند ولی درستِ همه‌جایی‌اند؛ نمونه نیستند
GENERIC_OK = ('همهٔ حقوق محفوظ است.', 'همه حقوق محفوظ است', 'پرسش‌های پرتکرار', 'هنوز موردی ثبت نشده است.', 'این مورد پیدا نشد.',
              'پیامت رسید. به‌زودی با تو تماس می‌گیریم.')

_DIACRITICS = re.compile('[ً-ْٰ]')
_ZW = dict.fromkeys(map(ord, '‌‍‎‏ '), ' ')
_TAGS = re.compile(r'<[^>]*>')

# ── الگوها: (regex، نوع، متنِ توضیح که «%s» جایِ مقدارِ پیدا‌شده را می‌گیرد)
MARKERS = [
    (re.compile(r'[\w.+-]+@example\.(?:com|org|net)|example\.(?:com|org|net)', re.I), 'contact', 'نشانیِ نمونه (%s)'),
    (re.compile(r'۰?۲۱[\s-]*۱۲۳۴۵۶۷۸|021[\s-]*12345678|[۰0]۹۱۲[\s-]*۳۴۵۶۷۸۹|0912[\s-]*3456789|(?:۱۲۳۴۵۶۷۸|12345678)'), 'contact', 'شمارهٔ تماسِ نمونه (%s)'),
    (re.compile(r'lorem\s+ipsum', re.I), 'sample', 'متنِ آزمایشی (%s)'),
    (re.compile(r'این متن(?:ِ)? نمونه است|متنِ نمونه|قیمتِ نمونه|مقدارِ نمونه|خیابانِ نمونه|نامِ نمونه'), 'sample', 'متنِ نمونه (%s)'),
]
# هر خط «متن | نشانی» که نشانی‌اش «#» است (پیوندهای پابرگ)
_HASH_LINE = re.compile(r'\|\s*#\s*(?:\n|$)')


def norm(value):
    """برای مقایسه: بی‌تگ، بی‌اعراب و نیم‌فاصله، «ي/ك» عربی ⇒ فارسی، فاصله‌ها یکی."""
    s = _TAGS.sub(' ', str(value or ''))
    s = _DIACRITICS.sub('', s).translate(_ZW).replace('ي', 'ی').replace('ك', 'ک')
    return re.sub(r'\s+', ' ', s).strip()


def _sentence_like(n):
    return len(n) >= MIN_SAMPLE_CHARS and n.count(' ') + 1 >= MIN_SAMPLE_WORDS and n not in _GENERIC


_GENERIC = {norm(g) for g in GENERIC_OK}


@lru_cache(maxsize=1)
def sample_sentences():
    """جمله‌های نمونه: پیش‌فرضِ همهٔ بلوک‌ها و قطعه‌ها + متنِ همهٔ قالب‌های آمادهٔ صفحه (starters)."""
    from . import starters
    from .catalog import BLOCKS
    out = set()

    def take(v):
        if isinstance(v, str):
            lines = v.splitlines() if len(v.splitlines()) > 1 else []
            parts = [v] + [ln.split('|')[0] for ln in lines]      # متنِ چندخطی (پابرگ): هر خط جدا هم نمونه است
            for part in parts:
                n = norm(part)
                if _sentence_like(n):
                    out.add(n)
        elif isinstance(v, dict):
            for x in v.values():
                take(x)
        elif isinstance(v, (list, tuple)):
            for x in v:
                take(x)

    for spec in BLOCKS.values():
        take(spec.get('defaults'))
    docs = [starters.starter_doc(s['key']) for s in starters.STARTERS]
    docs += [starters.header_doc(None), starters.footer_doc(None)]
    for doc in docs:
        for b in walk(doc.get('blocks')):
            take(b.get('props'))
    return frozenset(out)


def _fa(n):
    return str(n).translate(str.maketrans('0123456789', '۰۱۲۳۴۵۶۷۸۹'))


def _snip(text, n=42):
    """برای نمایش: بی‌تگ و با فاصله‌های یکی، ولی با نیم‌فاصله و اعرابِ خودِ متن (norm برای مقایسه است، نه نمایش)."""
    t = re.sub(r'\s+', ' ', _TAGS.sub(' ', str(text or ''))).strip()
    return t if len(t) <= n else t[:n].rstrip() + '…'


def classify_text(value):
    """⇒ (نوع، توضیح) یا None. رشته‌ای که از قالب مانده یا شمارهٔ ساختگی دارد."""
    if not isinstance(value, str) or not value.strip():
        return None
    for rx, kind, msg in MARKERS:
        m = rx.search(value)
        if m:
            return kind, msg % _snip(m.group(0))
    n = norm(value)
    if n in sample_sentences():
        return 'sample', 'متنِ نمونه: «%s»' % _snip(value)
    if _HASH_LINE.search(value):
        return 'link', 'پیوندی در این فهرست هنوز به جایی وصل نیست («#»)'
    return None


def _partner_text(props, key, field_keys):
    """متنِ دکمه‌ای که این پیوند مالِ آن است، یا None اگر چنین متنی در تعریفِ این بلوک نیست.
    btn1_link ⇐ btn1؛ link ⇐ link_text / button / btn / text."""
    cands = [key[:-5]] if key.endswith('_link') else ['link_text', 'button', 'btn', 'text']
    for c in cands:
        if c in field_keys:
            return _snip(props.get(c), 200)
    return None


def _check_link(found, props, f, field_keys):
    key = f['key']
    value = str(props.get(key) or '').strip()
    if value not in ('', '#'):
        return
    partner = _partner_text(props, key, field_keys)
    if partner is None:                      # متنی کنارش نیست (مثلاً پیوندِ تصویر): فقط «#»ِ صریح اشتباه است
        if value == '#':
            found['link'].append('یک پیوند هنوز به جایی وصل نیست («#»)')
        return
    if partner:                              # دکمه هست ولی مقصد ندارد
        found['link'].append('دکمهٔ «%s» هنوز به جایی وصل نیست' % _snip(partner, 24))


def _scan_props(found, props, fields):
    keys = {f['key'] for f in fields}
    for f in fields:
        kind, key = f.get('kind'), f['key']
        v = props.get(key)
        if kind in TEXT_KINDS:
            hit = classify_text(v)
            if hit:
                found[hit[0]].append(hit[1])
        elif kind == 'link':
            _check_link(found, props, f, keys)
            hit = classify_text(v)                 # mailto:info@example.com
            if hit and hit[0] == 'contact':
                found['contact'].append(hit[1])
        elif kind == 'items' and isinstance(v, list):
            for row in v:
                if isinstance(row, dict):
                    _scan_props(found, row, f.get('fields') or [])


def check(blocks, r):
    """همهٔ بلوک‌های یک سند را می‌گردد و برای هر (بلوک، نوع) یک هشدار به رندرکننده `r` می‌دهد."""
    from .catalog import BLOCKS
    for b in walk(blocks):
        spec = BLOCKS.get(b.get('type'))
        if not spec or b.get('type') == 'custom_html':
            continue
        found = {k: [] for k in ('sample', 'contact', 'link')}
        _scan_props(found, b.get('props') or {}, spec.get('fields') or [])
        for kind in ('sample', 'contact', 'link'):
            msgs = list(dict.fromkeys(found[kind]))
            if not msgs:
                continue
            text = msgs[0] if len(msgs) == 1 else '%s — و %s مورد دیگر در همین بخش' % (msgs[0], _fa(len(msgs) - 1))
            r.warn(b, text, kind)
