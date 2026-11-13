# -*- coding: utf-8 -*-
"""موتورِ قالبِ قطعه‌های آماده: یک قالبِ HTML با «شکاف»‌ها ⇒ همان HTMLِ بلوک‌های سایت‌ساز (با ویرایشِ درجا روی بوم).

نشانه‌گذاری (فقط روی تگ‌هایی که خالی نوشته می‌شوند):
  <h2 data-s="title"></h2>                 متنِ ساده؛ خالی باشد در سایت نمی‌آید و روی بوم جای خالی نشان می‌دهد
  <p  data-s="text|m"></p>                 چندخطی (بعد از | حرفِ m)؛ |r یعنی متنِ قالب‌دار (rich)
  <a  data-s="btn" data-h="btn_link"></a>  دکمه/پیوند: متن از btn، نشانی از btn_link (با پیوندِ صفحه‌ها کار می‌کند)
  <img data-i="image" data-alt="alt" class="nbc-img">     تصویر از کتابخانهٔ رسانه (srcset و ابعاد خودکار)
  <span data-ic="icon" class="nbc-ic"></span>              نمادِ خطی
  <ul data-links="links"></ul>             هر خطِ «متن | نشانی» یک <li><a>
  <!--each:items-->…<!--/each-->           تکرار؛ داخلش شکاف‌ها از همان ردیف می‌آیند؛ data-req="image" یعنی بدونِ این مقدار ردیف نیاید
  <!--each:items.dup-->…<!--/each-->       نسخهٔ دومِ همان ردیف‌ها (برای نوارِ متحرک)؛ بی‌ویرایشِ درجا تا روی بوم دو بار ویرایش نشود
  <!--if:key-->…<!--/if-->                 فقط اگر مقدارِ key پر باشد (روی بوم همیشه)
  <a data-href="video_link">…</a>          پیوندی که درونش تصویر یا هر چیزِ دیگر است؛ نشانی از شکافِ video_link (خارجی ⇒ زبانهٔ تازه)
  <ul data-lines="features"></ul>         هر خطِ متن یک <li> با نمادِ تیک (برای فهرستِ امکانات)
  data-keep                                با data-s: حتی اگر خالی بود تگ در سایت بماند (مثلاً خانهٔ جدول)
  data-ifc="flag:class"                    اگر مقدارِ flag (کلید یا تیک) پر بود، کلاسِ class به همین تگ اضافه می‌شود
  data-co                                  فقط روی <details>: روی بوم باز است
  {{n}}                                    شمارهٔ ردیف (فارسی) داخلِ each
  [[MENU]] [[TITLE]] [[ID]]                فقط در سربرگ/پابرگ: منوی سایت، نامِ سایت، شناسهٔ بلوک
هر متنِ کاربر escape می‌شود و { } خنثی می‌شوند؛ هیچ تگِ جنگو از کاربر نمی‌آید.
"""
import re

from .. import icons
from ..clean import esc, neutralize

RE_EACH = re.compile(r'<!--each:(\w+(?:\.dup)?)-->(.*?)<!--/each-->', re.S)
RE_IF = re.compile(r'<!--if:(\w+)-->(.*?)<!--/if-->', re.S)
RE_TEXT = re.compile(r'<(?P<tag>[a-zA-Z][\w-]*)(?P<a>(?:\s[^<>]*?)?)\sdata-s="(?P<slot>[^"]+)"(?P<b>[^<>]*)></(?P=tag)>')
RE_IMG = re.compile(r'<img(?P<a>[^<>]*?)\sdata-i="(?P<slot>\w+)"(?P<b>[^<>]*)>')
RE_ICON = re.compile(r'<(?P<tag>[a-zA-Z]+)(?P<a>[^<>]*?)\sdata-ic="(?P<slot>\w+)"(?P<b>[^<>]*)></(?P=tag)>')
RE_LINKS = re.compile(r'<(?P<tag>ul|ol|div|nav)(?P<a>[^<>]*?)\sdata-links="(?P<slot>\w+)"(?P<b>[^<>]*)></(?P=tag)>')
RE_LINES = re.compile(r'<(?P<tag>ul|ol)(?P<a>[^<>]*?)\sdata-lines="(?P<slot>\w+)"(?P<b>[^<>]*)></(?P=tag)>')
RE_HREF = re.compile(r'<a(?P<a>[^<>]*?)\sdata-href="(?P<slot>\w+)"(?P<b>[^<>]*)>')
RE_IFC = re.compile(r'<(?P<tag>[a-zA-Z][\w-]*)(?P<a>[^<>]*?)\sdata-ifc="(?P<flag>\w+):(?P<cls>[\w-]+)"(?P<b>[^<>]*)>')
RE_CO = re.compile(r'(<details[^<>]*?)\sdata-co([^<>]*>)')
FA_DIGITS = str.maketrans('0123456789', '۰۱۲۳۴۵۶۷۸۹')


def _attr(s, name):
    m = re.search(r'\s%s="([^"]*)"' % re.escape(name), s)
    return m.group(1) if m else None


def _strip(s, *names):
    for n in names:
        s = re.sub(r'\s%s="[^"]*"' % re.escape(n), '', s)
    return s


def _add_class(attrs, cls):
    m = re.search(r'\sclass="([^"]*)"', attrs)
    if m:
        return attrs.replace(m.group(0), ' class="%s %s"' % (m.group(1), cls), 1)
    return attrs + ' class="%s"' % cls


def _val(scope, key):
    v = scope.get(key) if isinstance(scope, dict) else None
    return '' if v is None else str(v)


def _blank_ok(r):
    """جای خالیِ ویرایشی (نوشتهٔ کم‌رنگ، تصویرِ نمونه) فقط روی بومِ خودِ بخش؛ در سربرگ/پابرگِ نمایشی نه."""
    return bool(r.ctx.canvas and not getattr(r.ctx, 'chrome_only', False))


def _fill_href(r, scope, m):
    attrs = (m.group('a') or '') + (m.group('b') or '')
    url = r.link(_val(scope, m.group('slot')))
    ext = ' target="_blank" rel="noopener"' if url.startswith('http') else ''
    return '<a%s href="%s"%s>' % (attrs, esc(url), ext)


def _fill_text(r, scope, prefix, m):
    attrs = (m.group('a') or '') + (m.group('b') or '')
    key, _, mode = m.group('slot').partition('|')
    val = _val(scope, key)
    link_key = _attr(attrs, 'data-h')
    keep = re.search(r'\sdata-keep(?=\s|$)', ' ' + attrs.strip() + ' ') is not None
    attrs = _strip(attrs, 'data-h')
    attrs = re.sub(r'\sdata-keep(?=\s|$)', '', attrs)
    if not val.strip() and not _blank_ok(r) and not keep:
        return ''
    if not val.strip() and _blank_ok(r):
        attrs = _add_class(attrs, 'nb-blank')
    href = ''
    if link_key is not None:
        href = ' href="%s"' % esc(r.link(_val(scope, link_key)))
    if mode == 'r':
        inner = neutralize(val)
    elif mode == 'm':
        inner = r.line(val)
    else:
        inner = esc(val)
    tag = m.group('tag')
    return '<%s%s%s%s>%s</%s>' % (tag, attrs, href, r.ed(prefix + key, rich=(mode == 'r'), multi=(mode == 'm')), inner, tag)


def _fill_img(r, scope, prefix, m):
    attrs = (m.group('a') or '') + (m.group('b') or '')
    alt_key = _attr(attrs, 'data-alt')
    cls = _attr(attrs, 'class') or ''
    sizes = _attr(attrs, 'data-sizes') or '(max-width:800px) 100vw, 640px'
    if not _val(scope, m.group('slot')).strip() and not _blank_ok(r):
        return ''
    return r.img(_val(scope, m.group('slot')), _val(scope, alt_key) if alt_key else '', cls, sizes=sizes)


def _fill_icon(r, scope, m):
    attrs = _strip((m.group('a') or '') + (m.group('b') or ''), 'data-ic')
    return '<%s%s>%s</%s>' % (m.group('tag'), attrs, icons.svg(_val(scope, m.group('slot')) or 'star'), m.group('tag'))


def _fill_lines(r, scope, m):
    attrs = (m.group('a') or '') + (m.group('b') or '')
    lines = [x.strip() for x in _val(scope, m.group('slot')).splitlines() if x.strip()]
    if not lines:
        return ''
    rows = ''.join('<li>%s<span>%s</span></li>' % (icons.svg('check'), esc(x)) for x in lines)
    return '<%s%s>%s</%s>' % (m.group('tag'), attrs, rows, m.group('tag'))


def _fill_links(r, scope, m):
    attrs = (m.group('a') or '') + (m.group('b') or '')
    rows = []
    for line in _val(scope, m.group('slot')).splitlines():
        if not line.strip():
            continue
        label, _, url = line.partition('|')
        rows.append('<li><a href="%s">%s</a></li>' % (esc(r.link(url.strip() or '#')), esc(label.strip())))
    if not rows:
        return ''
    tag = m.group('tag')
    if tag in ('ul', 'ol'):
        return '<%s%s>%s</%s>' % (tag, attrs, ''.join(rows), tag)
    return '<%s%s>%s</%s>' % (tag, attrs, ''.join(x.replace('<li>', '').replace('</li>', '') for x in rows), tag)


class _Quiet:
    """رندرکننده‌ای که ویرایشِ درجا نمی‌نویسد (نسخهٔ تکراری)."""

    def __init__(self, r):
        self._r = r

    def __getattr__(self, name):
        return getattr(self._r, name)

    def ed(self, *a, **kw):
        return ''


def expand(tpl, scope, prefix, r):
    """قالب + مقدارها ⇒ HTML. prefix مسیرِ ویرایشِ درجا (مثلاً items.2.) است."""
    def each(m):
        name, inner = m.group(1), m.group(2)
        rr = r
        if name.endswith('.dup'):
            name, rr = name[:-4], _Quiet(r)
        out = []
        for i, row in enumerate(scope.get(name) or []):
            if not isinstance(row, dict):
                continue
            req = re.search(r'\sdata-req="(\w+)"', inner)
            if req and not _val(row, req.group(1)).strip() and not _blank_ok(r):
                continue
            body = re.sub(r'\sdata-req="\w+"', '', inner).replace('{{n}}', str(i + 1).translate(FA_DIGITS))
            out.append(expand(body, row, '%s%s.%d.' % (prefix, name, i), rr))
        return ''.join(out)

    def cond(m):
        return m.group(2) if (_val(scope, m.group(1)).strip() or _blank_ok(r)) else ''

    def ifc(m):
        on = _val(scope, m.group('flag')).strip().lower() not in ('', '0', 'false', 'none')
        attrs = (m.group('a') or '') + (m.group('b') or '')
        return '<%s%s>' % (m.group('tag'), _add_class(attrs, m.group('cls')) if on else attrs)

    s = RE_EACH.sub(each, tpl)
    s = RE_IF.sub(cond, s)
    s = RE_IFC.sub(ifc, s)
    s = RE_CO.sub(lambda m: m.group(1) + (' open' if r.ctx.canvas else '') + m.group(2), s)
    s = RE_HREF.sub(lambda m: _fill_href(r, scope, m), s)
    s = RE_IMG.sub(lambda m: _fill_img(r, scope, prefix, m), s)
    s = RE_ICON.sub(lambda m: _fill_icon(r, scope, m), s)
    s = RE_LINES.sub(lambda m: _fill_lines(r, scope, m), s)
    s = RE_LINKS.sub(lambda m: _fill_links(r, scope, m), s)
    s = RE_TEXT.sub(lambda m: _fill_text(r, scope, prefix, m), s)
    return s


def chrome_tokens(html, r, bid):
    """نشانه‌های سربرگ/پابرگ ⇒ تگ‌های قالبِ جنگو (همان‌هایی که site_header هم می‌نویسد)."""
    from .. import render as R
    if '[[MENU]]' in html:
        links = ('{% for title, href in MENU %}<a href="{{ href }}" class="{% if CURRENT_PATH == href %}on{% endif %}">{{ title }}</a>{% endfor %}'
                 if not r.ctx.has_submenu else R.NAV_TREE)
        html = html.replace('[[MENU]]', links)
    return html.replace('[[TITLE]]', '{{ SITE_TITLE }}').replace('[[ID]]', bid)


__all__ = ['expand', 'chrome_tokens']
