# -*- coding: utf-8 -*-
"""HTML ⇐⇒ بلوک‌ها: هر چیزی که شناخته نشود «کدِ سفارشی» می‌شود؛ هیچ‌وقت حذف نمی‌شود.

برای صفحه‌ای که قبلاً از ویرایشگر منتشر شده و بعد AI یا کد عوضش کرده، از نسخهٔ قبلی کمک می‌گیریم:
  ۱. بلوکی که عیناً همان خروجی را دارد ⇐ همان بلوک (با تنظیماتش) می‌ماند.
  ۲. بلوکی که فقط متنش عوض شده ⇐ متن در همان بلوک می‌نشیند.
  ۳. بخش و ستون ⇐ فرزندانش جدا سنجیده می‌شوند.
  ۴. بقیه ⇐ کدِ سفارشی + CSSِ قبلیِ آن بلوک حفظ می‌شود.
"""
import copy
import html as _html
import re

from .catalog import BLOCKS
from .clean import ALLOWED_TAGS, clean_rich, new_block, new_id, walk
from .render import Ctx, Renderer, split_page_css

VOID = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'}
RAW_TEXT = {'script', 'style', 'textarea'}
TPL_OPEN = re.compile(r'{%\s*(if|for|with|block|comment|autoescape|spaceless|filter|ifchanged|verbatim|cache)\b')
TPL_CLOSE = re.compile(r'{%\s*end(if|for|with|block|comment|autoescape|spaceless|filter|ifchanged|verbatim|cache)\b')
TPL_ANY = re.compile(r'{%|{{|{#')
ATTR_RE = re.compile(r"""([^\s=/>]+)(?:\s*=\s*("[^"]*"|'[^']*'|[^\s>]+))?""", re.S)
BID_RE = re.compile(r'(?:^|\s)b-([a-z0-9]{4,16})(?:\s|$)')
LOAD_STATIC = '{% load static %}'


class Node:
    __slots__ = ('kind', 'tag', 'attrs', 'start', 'end', 'inner_start', 'inner_end', 'children')

    def __init__(self, kind, tag='', attrs=None, start=0, end=0):
        self.kind = kind            # el | text | tpl | comment
        self.tag = tag
        self.attrs = attrs or {}
        self.start = start
        self.end = end
        self.inner_start = end
        self.inner_end = end
        self.children = []


def _tag_end(src, i):
    """پایانِ تگِ بازشده در i؛ کوتیشن و تگ‌های جنگوی داخلش را می‌فهمد."""
    n, q = len(src), None
    j = i + 1
    while j < n:
        ch = src[j]
        if src.startswith('{%', j) or src.startswith('{{', j):
            close = src.find('%}' if src[j + 1] == '%' else '}}', j)
            if close < 0:
                return -1
            j = close + 2
            continue
        if q:
            if ch == q:
                q = None
        elif ch in '"\'':
            q = ch
        elif ch == '>':
            return j + 1
        j += 1
    return -1


def parse(src):
    """⇒ (ریشه، سالم؟). اگر ساختار به‌هم‌ریخته باشد سالم=False تا کلِ متن کدِ سفارشی شود."""
    root = Node('el', tag='#root', start=0, end=len(src))
    root.inner_start, root.inner_end = 0, len(src)
    stack = [root]
    i, n, ok = 0, len(src), True

    def add(node):
        stack[-1].children.append(node)

    while i < n:
        if src.startswith('{%', i) or src.startswith('{{', i) or src.startswith('{#', i):
            close = {'%': '%}', '{': '}}', '#': '#}'}[src[i + 1]]
            j = src.find(close, i)
            if j < 0:
                return root, False
            add(Node('tpl', start=i, end=j + 2))
            i = j + 2
            continue
        if src.startswith('<!--', i):
            j = src.find('-->', i)
            j = n if j < 0 else j + 3
            add(Node('comment', start=i, end=j))
            i = j
            continue
        if src[i] == '<' and i + 1 < n and (src[i + 1].isalpha() or src[i + 1] == '/'):
            j = _tag_end(src, i)
            if j < 0:
                return root, False
            raw = src[i:j]
            if raw[1] == '/':
                tag = raw[2:-1].strip().lower()
                if any(x.tag == tag for x in stack[1:]):
                    while stack[-1].tag != tag:      # تگی بسته نشده بود
                        ok = False
                        node = stack.pop()
                        node.inner_end = node.end = i
                    node = stack.pop()
                    node.inner_end, node.end = i, j
                else:
                    ok = False
                i = j
                continue
            m = re.match(r'<([a-zA-Z][\w:-]*)', raw)
            tag = m.group(1).lower()
            attrs = {}
            body = raw[m.end():-1].rstrip('/')
            if not TPL_ANY.search(body):
                for k, v in ATTR_RE.findall(body):
                    attrs[k.lower()] = _html.unescape(v.strip('"\'')) if v else ''
            else:
                attrs['__tpl__'] = '1'             # تگ داخلِ خودش قالبِ جنگو دارد
            node = Node('el', tag, attrs, i, j)
            add(node)
            if tag in VOID or raw.endswith('/>'):
                i = j
                continue
            if tag in RAW_TEXT:
                c = re.compile(r'</%s\s*>' % tag, re.I).search(src, j)
                if not c:
                    return root, False
                node.inner_start, node.inner_end, node.end = j, c.start(), c.end()
                i = c.end()
                continue
            node.inner_start = j
            stack.append(node)
            i = j
            continue
        j = i + 1
        while j < n and src[j] != '<' and not (src[j] == '{' and j + 1 < n and src[j + 1] in '%{#'):
            j += 1
        add(Node('text', start=i, end=j))
        i = j
    if len(stack) > 1:
        ok = False
    return root, ok


def norm(s):
    return re.sub(r'>\s+<', '><', re.sub(r'\s+', ' ', s or '')).strip()


def _net(raw):
    return len(TPL_OPEN.findall(raw)) - len(TPL_CLOSE.findall(raw))


def _chunks(nodes, src):
    """خواهر و برادرها ⇐ تکه‌هایی که از نظرِ تگ‌های جنگو متوازن‌اند."""
    out, cur, depth = [], [], 0
    for nd in nodes:
        raw = src[nd.start:nd.end]
        depth += _net(raw)
        cur.append(nd)
        if depth <= 0:
            depth = 0
            out.append(cur)
            cur = []
    if cur:
        out.append(cur)
    return out


def _klass(node):
    return node.attrs.get('class', '')


def _only(node, allowed):
    return all(k in allowed for k in node.attrs)


class Importer:
    def __init__(self, src, prev_doc, ctx, target='page'):
        self.src = src
        self.ctx = ctx
        self.target = target
        self.prev = {b['id']: b for b in walk((prev_doc or {}).get('blocks'))}
        self.used = set()
        self.keep_css = []
        self.report = {'kept': 0, 'text_merged': 0, 'custom': 0, 'converted': 0, 'custom_labels': []}

    def raw(self, node):
        return self.src[node.start:node.end]

    def inner(self, node):
        return self.src[node.inner_start:node.inner_end]

    def custom(self, raw, label=''):
        code = raw.strip()
        self.report['custom'] += 1
        if label:
            self.report['custom_labels'].append(label)
        return new_block('custom_html', code=code)

    # ── تبدیلِ خواهر و برادرها ──
    def convert(self, nodes, nested=False):
        blocks = []
        buffered = []

        def flush():
            if buffered:
                code = self.src[buffered[0].start:buffered[-1].end]
                if code.strip():
                    blocks.append(self.custom(code))
                buffered.clear()

        for chunk in _chunks(nodes, self.src):
            if len(chunk) == 1 and chunk[0].kind == 'text' and not chunk[0].end - chunk[0].start:
                continue
            if len(chunk) == 1 and chunk[0].kind == 'text' and not self.raw(chunk[0]).strip():
                if buffered:
                    buffered.append(chunk[0])
                continue
            el = chunk[0] if len(chunk) == 1 and chunk[0].kind == 'el' else None
            b = self.element(el, nested) if el is not None else None
            if b is None:
                buffered.extend(chunk)
                continue
            flush()
            blocks.append(b)
        flush()
        return blocks

    def element(self, el, nested):
        m = BID_RE.search(_klass(el))
        if m and m.group(1) in self.prev and m.group(1) not in self.used:
            b = self.from_prev(el, self.prev[m.group(1)], nested)
            if b is not None:
                self.used.add(m.group(1))
                return b
        b = self.heuristic(el, nested)
        if b is not None:
            self.report['converted'] += 1
        return b

    # ── با کمکِ نسخهٔ قبلی ──
    def rendered(self, b, mark=False):
        ctx = copy.copy(self.ctx)
        ctx.canvas = False
        ctx.mark = mark
        r = Renderer(ctx)
        return r.block(b), r

    def from_prev(self, el, prev, nested):
        raw = self.raw(el)
        html, r = self.rendered(prev)
        if norm(html) == norm(raw):
            self.report['kept'] += 1 + sum(1 for _ in walk(prev.get('children')))
            return copy.deepcopy(prev)
        # بخش و ستون: پوسته همان است؟ فرزندان را جدا بسنج
        if prev['type'] in ('section', 'columns', 'column'):
            kids = self.container_kids(el, prev)
            if kids is not None:
                b = copy.deepcopy(prev)
                b['children'] = kids
                return b
        merged = self.text_merge(el, prev)
        if merged is not None:
            self.report['text_merged'] += 1
            return merged
        # تبدیل نشد ⇐ کدِ سفارشی؛ ظاهرِ قبلی‌اش با CSS می‌ماند
        css = r.css()
        if css:
            self.keep_css.append(css)
        label = BLOCKS[prev['type']]['label']
        return self.custom(raw, label)

    def container_kids(self, el, prev):
        kids_nodes = None
        if prev['type'] == 'section':
            inner = [c for c in el.children if not (c.kind == 'text' and not self.raw(c).strip())]
            want = prev['props'].get('inner_cls') or 'nb-wrap'
            if want == '-':
                kids_nodes = el.children
            elif len(inner) == 1 and inner[0].kind == 'el' and inner[0].tag == 'div' and _klass(inner[0]) == want:
                kids_nodes = inner[0].children
        elif prev['type'] in ('columns', 'column'):
            kids_nodes = el.children
        if kids_nodes is None:
            return None
        kids = self.convert(kids_nodes, nested=True)
        if prev['type'] == 'columns':
            if not kids or any(k['type'] != 'column' for k in kids):
                return None
        elif any(k['type'] == 'column' or BLOCKS[k['type']].get('root') for k in kids):
            return None
        return kids

    def text_merge(self, el, prev):
        """همان ساختار با متنِ تازه: مسیرِ هر متن را از رندرِ نشان‌دار می‌گیریم."""
        marked, _ = self.rendered(prev, mark=True)
        root, ok = parse(marked)
        if not ok or len([c for c in root.children if c.kind == 'el']) != 1:
            return None
        old = next(c for c in root.children if c.kind == 'el')
        edits = {}
        if not self._parallel(old, el, marked, edits):
            return None
        if not edits:
            return None
        b = copy.deepcopy(prev)
        for path, value in edits.items():
            obj, keys = b['props'], path.split('.')
            for k in keys[:-1]:
                obj = obj[int(k)] if k.isdigit() else obj[k]
            obj[keys[-1]] = value
        return b

    def _parallel(self, a, b, marked, edits):
        if a.kind != b.kind:
            return False
        if a.kind != 'el':
            return norm(marked[a.start:a.end]) == norm(self.raw(b))
        if a.tag != b.tag:
            return False
        ax = {k: v for k, v in a.attrs.items() if not k.startswith('data-nb-')}
        if ax != b.attrs:
            return False
        path = a.attrs.get('data-nb-edit')
        if path:
            inner = self.inner(b)
            if TPL_ANY.search(inner):
                return False
            if a.attrs.get('data-nb-mode') == 'rich':
                edits[path] = clean_rich(inner)
            else:
                if re.search(r'<(?!br\s*/?>)', inner):
                    return False
                edits[path] = _html.unescape(re.sub(r'<br\s*/?>', '\n', inner)).strip()
            return True
        ak = [c for c in a.children if not (c.kind == 'text' and not marked[c.start:c.end].strip())]
        bk = [c for c in b.children if not (c.kind == 'text' and not self.raw(c).strip())]
        if len(ak) != len(bk):
            return False
        return all(self._parallel(x, y, marked, edits) for x, y in zip(ak, bk))

    # ── بدونِ نسخهٔ قبلی: حدس از روی HTML ──
    def heuristic(self, el, nested):
        tag = el.tag
        raw = self.raw(el)
        cls = _klass(el)
        if '__tpl__' in el.attrs:
            return None
        if tag == 'section' and not nested and _only(el, {'class'}):
            return self.section(el, cls)
        if TPL_ANY.search(raw):
            return None
        if tag in ('h1', 'h2', 'h3', 'h4') and _only(el, {'class'}) and not any(c.kind != 'text' for c in el.children):
            return new_block('heading', text=_html.unescape(self.inner(el)).strip(), level=int(tag[1]), cls=cls, legacy=True)
        if tag in ('p', 'ul', 'ol') and _only(el, {'class'}) and self.simple_inline(el):
            return new_block('text', html=clean_rich(raw), cls=cls, legacy=True)
        if tag == 'img' and _only(el, {'src', 'alt', 'class', 'width', 'height', 'loading', 'decoding'}) and not cls:
            src = el.attrs.get('src', '')
            if re.match(r'^(https?://|/)', src):
                return new_block('image', src=src, alt=el.attrs.get('alt', ''))
        if tag == 'hr' and not el.attrs:
            return new_block('divider')
        if tag == 'a' and _only(el, {'class', 'href'}) and re.search(r'(^|\s)btn(\s|$)', cls) and not any(c.kind != 'text' for c in el.children):
            return new_block('button', text=_html.unescape(self.inner(el)).strip(), link=el.attrs.get('href', '#'), btn_cls=cls)
        return None

    def simple_inline(self, el):
        for c in el.children:
            if c.kind == 'el':
                if c.tag not in ALLOWED_TAGS or set(c.attrs) - ({'href'} if c.tag == 'a' else set()):
                    return False
                if not self.simple_inline(c):
                    return False
            elif c.kind != 'text':
                return False
        return True

    def section(self, el, cls):
        inner = [c for c in el.children if not (c.kind == 'text' and not self.raw(c).strip())]
        if len(inner) == 1 and inner[0].kind == 'el' and inner[0].tag == 'div' and _only(inner[0], {'class'}) and _klass(inner[0]):
            inner_cls, nodes = _klass(inner[0]), inner[0].children
        else:
            inner_cls, nodes = '-', el.children
        kids = self.convert(nodes, nested=True)
        b = new_block('section', children=kids, cls=cls)
        b['props']['inner_cls'] = inner_cls
        b['props']['legacy'] = True
        return b


def strip_shared_wrapper(src, target):
    """سربرگ/پابرگی که خودمان ساخته‌ایم یک پیشوندِ load و یک پوششِ footer دارد."""
    s = (src or '').strip()
    if s.startswith(LOAD_STATIC):
        s = s[len(LOAD_STATIC):].strip()
    if target == 'footer':
        m = re.match(r'^<footer class="nb-footer">(.*)</footer>$', s, re.S)
        if m:
            s = m.group(1).strip()
    return s


def import_html(html, css='', prev_doc=None, ctx=None, target='page'):
    """متنِ HTML + CSS ⇐ (سند، گزارش). هیچ متنی از دست نمی‌رود."""
    ctx = ctx or Ctx()
    src = strip_shared_wrapper(html, target) if target != 'page' else (html or '').strip()
    root, ok = parse(src)
    imp = Importer(src, prev_doc, ctx, target)
    if not ok:
        blocks = [imp.custom(src, 'کلِ صفحه')] if src else []
    else:
        blocks = imp.convert(root.children)
    # تکهٔ رو-ریشهٔ غیرِ مجاز (مثلاً heading در ریشه) مانعی ندارد؛ سند ریشهٔ آزاد دارد
    gen, rest = split_page_css(css)
    prev_lines = set()
    if prev_doc:
        r = Renderer(_mark_off(ctx))
        for b in prev_doc.get('blocks') or []:
            r.block(b)
        prev_lines = set(r.css().splitlines())
    changed = [ln for ln in gen.splitlines() if ln.strip() and ln not in prev_lines]
    extra = '\n'.join(x for x in ([rest] + imp.keep_css + changed) if x.strip())
    doc = {'v': 1, 'blocks': blocks}
    if extra.strip():
        doc['extra_css'] = extra
    imp.report['total'] = sum(1 for _ in walk(blocks))
    imp.report['ok'] = ok
    return doc, imp.report


def _mark_off(ctx):
    c = copy.copy(ctx)
    c.canvas = False
    c.mark = False
    return c


__all__ = ['import_html', 'parse', 'norm', 'new_id', 'strip_shared_wrapper']
