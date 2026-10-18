# -*- coding: utf-8 -*-
"""وارسیِ ورودی‌های فرم‌های گرافیکی — تا هیچ فرمی کدِ خراب نسازد.

هر تابع یا مقدارِ تمیزشده را برمی‌گرداند یا ValueError با پیامِ فارسی می‌دهد.
"""
import ast
import keyword
import re

from django.conf import global_settings

RESERVED_APPS = {'admin', 'auth', 'contenttypes', 'sessions', 'messages', 'staticfiles', 'config',
                 'apps', 'django', 'static', 'templates', 'media', 'test', 'tests', 'site', 'studio'}
RESERVED_FIELDS = {'id', 'pk', 'objects', 'save', 'delete', 'clean', 'full_clean', 'refresh_from_db',
                   'serializable_value', 'validate_unique', 'check', 'from_db', 'Meta'}


def app_name(v):
    v = (v or '').strip()
    if not re.fullmatch(r'[a-z][a-z0-9_]{1,40}', v):
        raise ValueError('نامِ اپ باید انگلیسی و کوچک باشد (حرف، عدد، _)، مثلاً blog یا user_reviews.')
    if keyword.iskeyword(v) or v in RESERVED_APPS:
        raise ValueError('«%s» نامِ رزرو است؛ نامِ دیگری بگذار.' % v)
    return v


def model_name(v):
    v = (v or '').strip()
    if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,50}', v):
        raise ValueError('نامِ مدل باید انگلیسی باشد، مثلاً Post یا ProductImage.')
    camel = ''.join(w[:1].upper() + w[1:] for w in v.split('_') if w)
    if keyword.iskeyword(camel) or camel in ('Model', 'Meta', 'models'):
        raise ValueError('«%s» نامِ رزرو است.' % camel)
    return camel


def field_name(v):
    v = (v or '').strip()
    if not re.fullmatch(r'[a-z][a-z0-9_]{0,50}', v) or '__' in v or v.endswith('_'):
        raise ValueError('نامِ فیلد باید انگلیسیِ کوچک باشد (مثلاً title یا created_at)، بدونِ __ و بدونِ _ در انتها.')
    if keyword.iskeyword(v) or v in RESERVED_FIELDS:
        raise ValueError('«%s» نامِ رزرو است (id خودکار ساخته می‌شود).' % v)
    return v


def view_name(v):
    v = (v or '').strip()
    if not re.fullmatch(r'[a-z][a-z0-9_]{0,60}', v):
        raise ValueError('نامِ ویو باید انگلیسیِ کوچک باشد، مثلاً post_list.')
    if keyword.iskeyword(v):
        raise ValueError('«%s» نامِ رزرو است.' % v)
    return v


def url_name(v):
    v = (v or '').strip()
    if v and not re.fullmatch(r'[A-Za-z_][\w-]{0,79}', v):
        raise ValueError('نامِ نشانی باید انگلیسی باشد (حرف، عدد، _ یا -).')
    return v


def url_pattern(v):
    """الگوی path() جنگو — همان‌جا با خودِ جنگو امتحان می‌شود."""
    v = (v or '').strip().lstrip('/')
    if re.search(r'[\s\'"\\]', v):
        raise ValueError('الگو نباید فاصله یا کوتیشن داشته باشد.')
    rest = re.sub(r'<(?:(int|str|slug|uuid|path):)?[A-Za-z_]\w*>', '', v)
    if '<' in rest or '>' in rest:
        raise ValueError('بخشِ متغیرِ نشانی باید کامل باشد، مثلاً <int:pk> یا <slug:slug>.')
    from django.core.exceptions import ImproperlyConfigured
    from django.urls import path
    try:
        p = path(v, lambda r: None)
        p.pattern.regex  # noqa — کامپایل
    except (ImproperlyConfigured, Exception) as exc:  # noqa
        raise ValueError('الگوی نشانی درست نیست: %s' % exc)
    return v


def url_prefix(v):
    v = (v or '').strip().strip('/')
    if v and not re.fullmatch(r'[A-Za-z0-9_\-/]+', v):
        raise ValueError('پیشوندِ نشانی فقط حرفِ انگلیسی، عدد، - و / می‌پذیرد.')
    return (v + '/') if v else ''


def page_slug(v):
    v = (v or '').strip().lower().strip('/')
    if v and not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,79}', v):
        raise ValueError('نشانیِ صفحه فقط حرفِ کوچکِ انگلیسی، عدد و - می‌پذیرد.')
    return v


TEXTUAL = {'CharField', 'TextField', 'SlugField', 'EmailField', 'URLField'}
NUMERIC = {'IntegerField', 'PositiveIntegerField', 'BigIntegerField', 'FloatField', 'DecimalField'}


def field_default(v, ftype):
    """پیش‌فرض عیناً در کد می‌نشیند؛ این‌جا به یک عبارتِ پایتونیِ درست تبدیل می‌شود."""
    v = (v or '').strip()
    if not v:
        return ''
    if ftype == 'BooleanField':
        low = v.lower()
        if low in ('true', '1', 'yes', 'بله', 'آری'):
            return 'True'
        if low in ('false', '0', 'no', 'خیر'):
            return 'False'
        raise ValueError('پیش‌فرضِ بله/خیر باید True یا False باشد.')
    if ftype in NUMERIC:
        if re.fullmatch(r'-?\d+(\.\d+)?', v):
            return v
        raise ValueError('پیش‌فرضِ عددی باید عدد باشد.')
    if ftype in ('DateField', 'DateTimeField', 'TimeField'):
        if v in ('timezone.now', 'now'):
            return 'timezone.now'
        raise ValueError('برای تاریخ فقط «timezone.now» یا گزینهٔ «زمانِ ساخت» را بگذار.')
    if ftype == 'UUIDField':
        return 'uuid.uuid4'
    if ftype == 'JSONField':
        return v if v in ('dict', 'list') else 'dict'
    if ftype in TEXTUAL:
        try:
            node = ast.parse(v, mode='eval').body
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                return v
        except SyntaxError:
            pass
        return repr(v)               # متنِ ساده ⇒ رشتهٔ پایتونی
    try:
        ast.parse(v, mode='eval')
    except SyntaxError:
        raise ValueError('پیش‌فرض یک عبارتِ پایتونیِ درست نیست.')
    return v


def python_code(v, what='کد'):
    v = (v or '').replace('\r\n', '\n')
    if not v.strip():
        return ''
    try:
        ast.parse(v)
    except SyntaxError as exc:
        raise ValueError('%s خطای نحوی دارد (خطِ %s): %s' % (what, exc.lineno, exc.msg))
    return v


def dotted_lines(v):
    out = []
    for line in (v or '').splitlines():
        line = line.strip().strip(',').strip('\'"')
        if not line:
            continue
        if not re.fullmatch(r'[A-Za-z_][\w.]*', line):
            raise ValueError('«%s» نامِ اپِ پایتونیِ درست نیست.' % line)
        out.append(line)
    return '\n'.join(out)


def requirement_lines(v):
    out = []
    for line in (v or '').splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        if not re.fullmatch(r'[A-Za-z0-9_.\-\[\]]+\s*([<>=!~]=?\s*[\w.*]+\s*,?\s*)*', line):
            raise ValueError('«%s» شکلِ درستِ یک بستهٔ pip نیست (مثلاً djangorestframework>=3.15).' % line)
        out.append(line)
    return '\n'.join(out)


LANGUAGES = [(c, n) for c, n in global_settings.LANGUAGES]


def language(v):
    v = (v or 'fa').strip()
    if v not in dict(LANGUAGES):
        raise ValueError('زبانِ «%s» را جنگو نمی‌شناسد.' % v)
    return v


def timezone_name(v):
    v = (v or 'Asia/Tehran').strip()
    try:
        import zoneinfo
        if v != 'UTC' and v not in zoneinfo.available_timezones():
            raise ValueError
    except ValueError:
        raise ValueError('منطقهٔ زمانیِ «%s» شناخته نشد (مثلاً Asia/Tehran).' % v)
    return v


def hosts(v):
    items = [x.strip() for x in (v or '*').replace('،', ',').split(',') if x.strip()]
    for h in items:
        if not re.fullmatch(r'[\w.\-*:\[\]]+', h):
            raise ValueError('«%s» میزبانِ درستی نیست.' % h)
    return ','.join(items) or '*'


def color(v):
    v = (v or '').strip()
    if not re.fullmatch(r'#[0-9a-fA-F]{3}([0-9a-fA-F]{3})?', v):
        raise ValueError('رنگ باید به شکلِ #2f6df6 باشد.')
    return v
