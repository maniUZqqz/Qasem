# -*- coding: utf-8 -*-
"""ویرایشِ متن و عکسِ قالب‌های کدی (پروژهٔ واردشده و قالبِ ویوهای CRUD) بی‌دست‌زدن به تگ‌های قالب.

اصل: فایل هرگز از نو ساخته نمی‌شود. فقط بازه‌های مشخصی از «متنِ ساده» و «آدرسِ ثابتِ عکس» با جایگزینیِ مستقیم عوض
می‌شوند و بقیه بایت‌به‌بایت همان می‌ماند. پیش از ذخیره سنجیده می‌شود که دنبالهٔ تگ‌های {% %} و {{ }} و {# #} دقیقاً
با قبل یکی باشد؛ اگر نبود، چیزی ذخیره نمی‌شود. متنِ تازه escape می‌شود و { و } خنثی می‌شوند تا نتواند تگ بسازد.
"""
import hashlib
import html
import re

TAG_RE = re.compile(r'({%.*?%}|{{.*?}}|{#.*?#})', re.S)
RAW_ELEMENTS = {'script', 'style', 'textarea', 'pre', 'code', 'svg', 'noscript', 'title', 'option', 'select', 'iframe'}
SKIP_BLOCKS = {'comment': 'endcomment', 'verbatim': 'endverbatim'}
HAS_WORD_RE = re.compile(r'[^\W\d_]', re.U)
SAFE_IMG_RE = re.compile(r'^(?:https?://|/)[^\s"\'<>{}\\]+$')
IMG_SRC_RE = re.compile(r'''\ssrc\s*=\s*("([^"]*)"|'([^']*)')''', re.I)
MAX_VALUE = 4000


class EditError(ValueError):
    pass


def digest(text):
    return hashlib.sha256((text or '').encode('utf-8')).hexdigest()[:24]


def tags_of(text):
    """همهٔ تگ‌های قالب به ترتیب، بایت‌به‌بایت."""
    return TAG_RE.findall(text or '')


class _Scanner:
    """یک گذر روی متن: بازه‌های ویرایش‌پذیر را با آفستِ دقیق پیدا می‌کند."""

    def __init__(self, text):
        self.text = text
        self.items = []
        self.tag_spans = []
        self._scan()

    def _add_text(self, start, end):
        raw = self.text[start:end]
        core = raw.strip()
        if not core or not HAS_WORD_RE.search(html.unescape(core)):
            return
        a = start + (len(raw) - len(raw.lstrip()))
        b = a + len(core)
        self.items.append({'id': 't%d' % a, 'kind': 'text', 'start': a, 'end': b, 'value': html.unescape(core)})

    def _scan(self):
        text = self.text
        # تگ‌های قالب را اول پیدا می‌کنیم تا < و > ِ داخلشان گمراه نکند
        tags = [(m.start(), m.end(), m.group(0)) for m in TAG_RE.finditer(text)]
        self.tag_spans = [(a, b) for a, b, _ in tags]
        tag_at = {a: (b, t) for a, b, t in tags}
        i, n = 0, len(text)
        run = None
        raw_until = None      # نامِ عنصری که داخلش هیچ چیز ویرایش نمی‌شود
        skip_block = None     # comment / verbatim
        while i < n:
            if i in tag_at:
                end, tag = tag_at[i]
                if run is not None:
                    self._add_text(run, i)
                    run = None
                name = re.match(r'{%\s*(\w+)', tag)
                name = name.group(1) if name else ''
                if skip_block:
                    if name == skip_block:
                        skip_block = None
                elif name in SKIP_BLOCKS:
                    skip_block = SKIP_BLOCKS[name]
                i = end
                continue
            if skip_block:
                i += 1
                continue
            ch = text[i]
            if raw_until:
                if ch == '<' and text[i:i + len(raw_until) + 2].lower() == '</' + raw_until:
                    raw_until = None
                else:
                    i += 1
                    continue
            if ch == '<' and re.match(r'[!/a-zA-Z]', text[i + 1:i + 2] or ' '):
                if run is not None:
                    self._add_text(run, i)
                    run = None
                if text.startswith('<!--', i):
                    j = text.find('-->', i)
                    i = n if j < 0 else j + 3
                    continue
                j = self._tag_end(i)
                segment = text[i:j]
                m = re.match(r'<\s*([a-zA-Z][\w:-]*)', segment)
                if m:
                    tname = m.group(1).lower()
                    if tname == 'img':
                        self._add_image(i, segment)
                    if tname in RAW_ELEMENTS and not segment.endswith('/>'):
                        raw_until = tname
                i = j
                continue
            if run is None:
                run = i
            i += 1
        if run is not None and not raw_until and not skip_block:
            self._add_text(run, n)

    def _tag_end(self, start):
        """پایانِ تگِ HTML؛ > ِ داخلِ رشته و تگِ قالب حساب نیست."""
        text, n = self.text, len(self.text)
        i, quote = start + 1, None
        spans = {a: b for a, b in self.tag_spans}
        while i < n:
            if i in spans:
                i = spans[i]
                continue
            ch = text[i]
            if quote:
                if ch == quote:
                    quote = None
            elif ch in '"\'':
                quote = ch
            elif ch == '>':
                return i + 1
            i += 1
        return n

    def _add_image(self, start, segment):
        m = IMG_SRC_RE.search(segment)
        if not m:
            return
        value = m.group(2) if m.group(2) is not None else m.group(3)
        group = 2 if m.group(2) is not None else 3
        if not value or '{' in value or '}' in value:
            return                     # آدرسی که تگِ قالب دارد عوض نمی‌شود
        a = start + m.start(group)
        self.items.append({'id': 'i%d' % a, 'kind': 'image', 'start': a, 'end': a + len(value), 'value': value})


def scan(text):
    return _Scanner(text or '').items


def public_items(text):
    return [{'id': x['id'], 'kind': x['kind'], 'value': x['value']} for x in scan(text)]


def _encode_text(value):
    value = str(value or '').replace('\r', ' ').replace('\n', ' ').replace('\x00', '').strip()
    if not value:
        raise EditError('متن نمی‌تواند خالی باشد؛ اگر این بخش را نمی‌خواهی باید از حالتِ کد حذفش کنی.')
    if len(value) > MAX_VALUE:
        raise EditError('این متن خیلی بلند است.')
    return html.escape(value, quote=False).replace('{', '&#123;').replace('}', '&#125;')


def _encode_image(value):
    value = str(value or '').strip()
    if not SAFE_IMG_RE.match(value) or len(value) > 1000:
        raise EditError('نشانیِ عکس درست نیست.')
    return value


def apply_edits(text, edits):
    """edits: {id: مقدارِ تازه}. ⇒ متنِ تازه. هر ناهمخوانی ⇒ EditError و هیچ تغییری."""
    text = text or ''
    items = {x['id']: x for x in scan(text)}
    chosen = []
    for key, value in (edits or {}).items():
        item = items.get(str(key))
        if item is None:
            raise EditError('این بخش دیگر در قالب نیست. صفحه را دوباره باز کن.')
        if str(value) == item['value']:
            continue
        encoded = _encode_text(value) if item['kind'] == 'text' else _encode_image(value)
        chosen.append((item['start'], item['end'], encoded))
    out, pos = [], 0
    for a, b, encoded in sorted(chosen):
        out.append(text[pos:a])
        out.append(encoded)
        pos = b
    out.append(text[pos:])
    result = ''.join(out)
    if tags_of(result) != tags_of(text):
        raise EditError('این تغییر به تگ‌های قالب دست می‌زد و ذخیره نشد.')
    return result


_SCRIPT_RE = re.compile(r'<script\b[^>]*>.*?</script\s*>|<script\b[^>]*/?>', re.I | re.S)
_ON_RE = re.compile(r"""\son[a-z]+\s*=\s*("[^"]*"|'[^']*'|[^\s>]+)""", re.I)
_JS_RE = re.compile(r"""(href|src)\s*=\s*(["']?)\s*javascript:[^"'\s>]*\2""", re.I)


def preview_html(text):
    """نمای ساده برای ویرایش در جا: تگ‌های قالب نشان داده نمی‌شوند ولی {{ }} یک «…» می‌شود؛ متن‌ها و عکس‌ها نشانه دارند.
    فقط نمایش است و هرگز ذخیره نمی‌شود؛ iframe هم اجازهٔ اجرای اسکریپت ندارد."""
    text = text or ''
    items = sorted(scan(text), key=lambda x: x['start'])
    out, pos = [], 0
    for item in items:
        out.append(_strip_tags(text[pos:item['start']]))
        if item['kind'] == 'text':
            out.append('<span data-te="%s">%s</span>' % (item['id'], html.escape(item['value'], quote=False)))
        else:
            # آدرسِ عکس داخلِ تگِ img است؛ نشانه کنارِ src می‌نشیند
            out.append('%s" data-te-img="%s' % (html.escape(item['value']), item['id']))
        pos = item['end']
    out.append(_strip_tags(text[pos:]))
    joined = ''.join(out)
    joined = _SCRIPT_RE.sub('', joined)
    joined = _ON_RE.sub('', joined)
    return _JS_RE.sub(r'\1="#"', joined)


def _strip_tags(chunk):
    def repl(m):
        return '…' if m.group(0).startswith('{{') else ''
    return TAG_RE.sub(repl, chunk)
