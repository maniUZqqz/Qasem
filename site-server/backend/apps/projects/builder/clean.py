# -*- coding: utf-8 -*-
"""پاک‌سازیِ سندِ بلوک‌ها: چیزی که از مرورگر می‌آید هرگز مستقیم به خروجی نمی‌رسد.

· متن همیشه escape می‌شود؛ `{` و `}` هم خنثی می‌شوند تا متنِ کاربر نتواند قالبِ جنگو اجرا کند.
· متنِ قالب‌دار (rich) فقط چند تگِ بی‌خطر نگه می‌دارد.
· رنگ، اندازه و نشانی با الگوی صریح سنجیده می‌شوند؛ رشتهٔ دلخواهِ CSS راه ندارد.
· کدِ سفارشی فقط برای کارمند است (همهٔ APIِ سایت‌ساز IsAdminUser است) و موقعِ انتشار وارسیِ قالب می‌شود.
"""
import html as _html
import json
import re
import secrets
from html.parser import HTMLParser

from .catalog import BLOCKS, CONTAINERS, DEVICE_KEYS, LEGACY_PROPS, ROOT_ONLY, STYLE_BY_KEY
from .icons import ICONS

MAX_DOC_BYTES = 1_500_000
MAX_DEPTH = 8
MAX_ITEMS = 60
MAX_BLOCKS = 800
ID_RE = re.compile(r'^[a-z0-9]{4,16}$')
COLOR_RE = re.compile(r'^(#[0-9a-fA-F]{3}|#[0-9a-fA-F]{6}|#[0-9a-fA-F]{8}|t:(primary|on_primary|text|text2|muted|line|bg|surface|white|black))$')
CLASS_RE = re.compile(r'^[A-Za-z_][\w -]*$')
MODEL_RE = re.compile(r'^[a-z][a-z0-9_]*\.[A-Za-z][A-Za-z0-9_]*$')
FIELD_RE = re.compile(r'^[A-Za-z][A-Za-z0-9_]*$')
SORT_RE = re.compile(r'^-?[A-Za-z][A-Za-z0-9_]*$')
MEDIA_RE = re.compile(r'^m:\d+$')
PAGE_LINK_RE = re.compile(r'^page:\d+$')
SAFE_URL_RE = re.compile(r'^(https?://|mailto:|tel:|/|#)', re.I)


class DocError(ValueError):
    """سندِ نامعتبر؛ متنِ خطا فارسی است و به کاربر نشان داده می‌شود."""


def new_id():
    return secrets.token_hex(4)


def neutralize(text):
    """{ و } ِ متن را خنثی می‌کند تا هیچ‌وقت تگِ جنگو نشود."""
    return text.replace('{', '&#123;').replace('}', '&#125;')


def esc(value):
    return neutralize(_html.escape(str(value if value is not None else ''), quote=True))


def safe_url(value):
    """نشانیِ پیوند؛ javascript: و هر طرحِ ناشناخته ⇐ #"""
    u = str(value or '').strip()
    if not u:
        return ''
    if PAGE_LINK_RE.match(u) or SAFE_URL_RE.match(u):
        return u[:800]
    if re.match(r'^[\w.-]+\.[a-z]{2,}(/|$)', u, re.I):
        return 'https://' + u[:800]        # «example.com» نوشته بود
    return '#'


ALLOWED_TAGS = {'p', 'br', 'b', 'strong', 'i', 'em', 'u', 'a', 'ul', 'ol', 'li', 'span'}


class _Rich(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out = []
        self.stack = []

    def handle_starttag(self, tag, attrs):
        if tag == 'div':
            tag = 'p'                      # contenteditable در مرورگر div می‌سازد
        if tag not in ALLOWED_TAGS:
            return
        attr = ''
        if tag == 'a':
            href = safe_url(dict(attrs).get('href'))
            attr = ' href="%s"' % _html.escape(href, quote=True)
        if tag == 'br':
            self.out.append('<br>')
            return
        self.out.append('<%s%s>' % (tag, attr))
        self.stack.append(tag)

    def handle_startendtag(self, tag, attrs):
        if tag == 'br':
            self.out.append('<br>')

    def handle_endtag(self, tag):
        if tag == 'div':
            tag = 'p'
        if tag not in self.stack:
            return
        while self.stack:
            top = self.stack.pop()
            self.out.append('</%s>' % top)
            if top == tag:
                break

    def handle_data(self, data):
        self.out.append(_html.escape(data, quote=False))

    def result(self):
        while self.stack:
            self.out.append('</%s>' % self.stack.pop())
        return ''.join(self.out)


def clean_rich(value):
    p = _Rich()
    p.feed(str(value or '')[:40000])
    p.close()
    return p.result().strip()


def plain(value, limit=2000):
    """متنِ ساده: تگ حذف نمی‌شود چون هنگامِ نمایش escape می‌شود؛ فقط کوتاه و بی‌نویسهٔ کنترلی."""
    s = str(value if value is not None else '')
    s = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', s)
    return s[:limit]


def clean_color(value):
    v = str(value or '').strip()
    return v if COLOR_RE.match(v) else ''


def clean_image_ref(value):
    v = str(value or '').strip()
    if MEDIA_RE.match(v):
        return v
    if re.match(r'^https?://', v, re.I) or (v.startswith('/') and not v.startswith('//')):
        return v[:800]
    return ''


def _num(value, lo, hi, default=None, integer=True):
    try:
        n = float(value)
    except (TypeError, ValueError):
        return default
    if n != n:                              # NaN
        return default
    n = max(lo, min(hi, n))
    return int(round(n)) if integer else n


def clean_classes(value):
    v = str(value or '').strip()
    return v[:200] if CLASS_RE.match(v) else ''


def clean_field(field, value):
    kind = field['kind']
    if kind in ('text', 'link_text'):
        return plain(value, 1000)
    if kind == 'textarea':
        return plain(value, 8000)
    if kind == 'rich':
        return clean_rich(value)
    if kind == 'code':
        return str(value or '').replace('\r\n', '\n')[:200_000]
    if kind == 'slider':
        lo, hi = field.get('min', 0), field.get('max', 100)
        if field.get('device'):
            src = value if isinstance(value, dict) else {'d': value}
            out = {}
            for dev in ('d', 't', 'p'):
                n = _num(src.get(dev), lo, hi)
                if n is not None:
                    out[dev] = n
            return out
        return _num(value, lo, hi)
    if kind == 'decimal':
        return _num(value, -1000, 1000, integer=False)
    if kind == 'select':
        allowed = [o['value'] for o in field.get('options', [])]
        for a in allowed:
            if value == a or str(value) == str(a):
                return a
        return None
    if kind == 'toggle':
        return bool(value)
    if kind == 'color':
        return clean_color(value)
    if kind == 'image':
        return clean_image_ref(value)
    if kind in ('link', 'detail_link'):
        if kind == 'detail_link' and value == 'auto':
            return 'auto'
        return safe_url(value)
    if kind == 'icon':
        return value if value in ICONS else 'star'
    if kind == 'model':
        v = str(value or '')
        return v if MODEL_RE.match(v) else ''
    if kind == 'fields':
        return [x for x in (value if isinstance(value, list) else []) if isinstance(x, str) and FIELD_RE.match(x)][:30]
    if kind == 'sort':
        v = str(value or '')
        return v if SORT_RE.match(v) else ''
    if kind == 'items':
        rows = []
        for row in (value if isinstance(value, list) else [])[:MAX_ITEMS]:
            if not isinstance(row, dict):
                continue
            rows.append({f['key']: clean_field(f, row.get(f['key'])) for f in field['fields']})
        return rows
    return None


def clean_style(style, allowed):
    """{d:{…}, t:{…}, p:{…}} با کلیدهای مجازِ همان بلوک و مقدارهای سنجیده."""
    out = {}
    if not isinstance(style, dict):
        return out
    for dev in ('d', 't', 'p'):
        src = style.get(dev)
        if not isinstance(src, dict):
            continue
        row = {}
        for key, val in src.items():
            spec = STYLE_BY_KEY.get(key)
            if not spec or key not in allowed:
                continue
            if dev != 'd' and key not in DEVICE_KEYS:
                continue
            kind = spec['kind']
            if kind == 'color':
                v = clean_color(val)
            elif kind == 'image':
                v = clean_image_ref(val)
            elif kind == 'slider':
                v = _num(val, spec['min'], spec['max'])
            elif kind == 'select':
                v = val if any(o['value'] == val for o in spec['options']) else None
            elif kind == 'align':
                v = val if val in ('start', 'center', 'end') else None
            elif kind == 'toggle':
                v = True if val else None
            else:
                v = None
            if v not in (None, ''):
                row[key] = v
        if row:
            out[dev] = row
    return out


class _Cleaner:
    def __init__(self, target):
        self.target = target
        self.seen = set()
        self.count = 0

    def block(self, raw, depth):
        if not isinstance(raw, dict):
            raise DocError('ساختارِ صفحه خراب است.')
        btype = raw.get('type')
        spec = BLOCKS.get(btype)
        if not spec:
            raise DocError('بلوکِ ناشناخته: %s' % str(btype)[:40])
        scope = spec.get('scope')
        if scope and self.target not in scope:
            raise DocError('«%s» فقط در سربرگ یا پابرگ می‌آید.' % spec['label'])
        if depth > MAX_DEPTH:
            raise DocError('تو در تو بیش از حد شد.')
        self.count += 1
        if self.count > MAX_BLOCKS:
            raise DocError('این صفحه بیش از اندازه بلوک دارد.')
        bid = str(raw.get('id') or '')
        if not ID_RE.match(bid) or bid in self.seen:
            bid = new_id()
        self.seen.add(bid)
        props = raw.get('props') if isinstance(raw.get('props'), dict) else {}
        clean = {}
        for f in spec.get('fields', []):
            if f['key'] in props:
                v = clean_field(f, props[f['key']])
            else:
                v = None
            if v is None:
                v = spec.get('defaults', {}).get(f['key'])
            clean[f['key']] = v
        for key in LEGACY_PROPS:                # کلاس‌هایی که از صفحهٔ کدی/AI مانده‌اند
            if props.get(key):
                c = '-' if props[key] == '-' else clean_classes(props[key])
                if c:
                    clean[key] = c
        if props.get('legacy'):
            clean['legacy'] = True
        out = {'id': bid, 'type': btype, 'props': clean, 'style': clean_style(raw.get('style'), set(spec.get('style', [])))}
        if btype in CONTAINERS or btype == 'columns':
            kids = raw.get('children') if isinstance(raw.get('children'), list) else []
            children = []
            for k in kids:
                ktype = k.get('type') if isinstance(k, dict) else None
                if btype == 'columns' and ktype != 'column':
                    raise DocError('داخلِ «ستون‌ها» فقط ستون می‌آید.')
                if btype != 'columns' and ktype == 'column':
                    raise DocError('ستون باید داخلِ «ستون‌ها» باشد.')
                if ktype in ROOT_ONLY:
                    raise DocError('«%s» باید مستقیم در صفحه باشد، نه داخلِ بخشِ دیگر.' % BLOCKS[ktype]['label'])
                children.append(self.block(k, depth + 1))
            if btype == 'columns':
                clean['count'] = max(1, min(4, len(children) or 1))
            out['children'] = children
        return out


def clean_doc(doc, target='page'):
    """سندِ خام ⇐ سندِ تمیز؛ DocError اگر ساختار بی‌معنا باشد."""
    if not isinstance(doc, dict):
        raise DocError('سند باید شیء باشد.')
    if len(json.dumps(doc, ensure_ascii=False)) > MAX_DOC_BYTES:
        raise DocError('این صفحه بیش از اندازه بزرگ است.')
    blocks = doc.get('blocks')
    if not isinstance(blocks, list):
        raise DocError('فهرستِ بلوک‌ها پیدا نشد.')
    cl = _Cleaner(target)
    out = {'v': 1, 'blocks': []}
    for raw in blocks:
        btype = raw.get('type') if isinstance(raw, dict) else None
        if btype == 'column':
            raise DocError('ستون باید داخلِ «ستون‌ها» باشد.')
        out['blocks'].append(cl.block(raw, 1))
    extra = doc.get('extra_css')
    if isinstance(extra, str) and extra.strip():
        if '</style' in extra.lower():
            raise DocError('CSS نباید تگِ HTML داشته باشد.')
        out['extra_css'] = extra.replace('\r\n', '\n')[:200_000]
    return out


def walk(blocks):
    for b in blocks or []:
        yield b
        yield from walk(b.get('children'))


def new_block(btype, children=None, style=None, **props):
    """ساختِ بلوک از کد (قالب‌های آماده و تبدیلِ HTML)."""
    from .catalog import default_props
    p = default_props(btype)
    p.update(props)
    b = {'id': new_id(), 'type': btype, 'props': p, 'style': style or {}}
    if btype in CONTAINERS or btype == 'columns':
        b['children'] = children or []
    return b


def refresh_ids(block):
    """کپیِ بلوک با شناسه‌های تازه (بخشِ ذخیره‌شده و تکثیر)."""
    block['id'] = new_id()
    for k in block.get('children') or []:
        refresh_ids(k)
    return block


def canonical(doc):
    return json.dumps(doc or {}, ensure_ascii=False, sort_keys=True)
