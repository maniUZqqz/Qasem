# -*- coding: utf-8 -*-
"""نقطه‌های اتصال به موتورِ تولید.

⚠ اصلِ سازگاری: تا وقتی پروژه‌ای از ویرایشگرِ دیداری منتشر نکرده (`SiteTheme.active`)، همهٔ این توابع هیچ
کاری نمی‌کنند و خروجی بایت‌به‌بایت همان قبلی است (آزمونِ tests_builder_compat این را می‌سنجد).
"""
import os
import shutil

from . import theme as theme_mod

CDN_LINK = '<link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/rastikerdar/vazirmatn@v33.003/Vazirmatn-font-face.css">\n  '
BLOCKS_LINK = '<link rel="stylesheet" href="{% static \'css/base.css\' %}">\n  <link rel="stylesheet" href="{% static \'css/blocks.css\' %}">'
BASE_LINK = '<link rel="stylesheet" href="{% static \'css/base.css\' %}">'

SITE_DATA_TPL = '''# -*- coding: utf-8 -*-
"""دادهٔ بلوک‌های پویا (فهرست و جزئیات) — ساختهٔ استودیو؛ دستی ویرایش نکن.

در قالب‌ها: {%% for item in DATA.catalog.Product.by_price_desc|slice:":6" %%} …
فقط مدل‌های فهرست‌شدهٔ پایین در دسترس‌اند؛ مدلی که فیلدِ is_active دارد فقط ردیف‌های فعالش را نشان می‌دهد.
"""
from django.apps import apps

MODELS = %(models)s


class Records:
    """یک کوئریِ تنبل: تا تکرار نشود به دیتابیس نمی‌رود."""

    def __init__(self, app, name, request, order=None):
        self._app, self._name, self._request, self._order = app, name, request, order

    def _qs(self):
        model = apps.get_model(self._app, self._name)
        names = {f.name for f in model._meta.fields}
        qs = model.objects.all()
        if 'is_active' in names:
            qs = qs.filter(is_active=True)
        fks = [f.name for f in model._meta.fields if f.many_to_one or f.one_to_one]
        if fks:
            qs = qs.select_related(*fks)
        if self._order:
            qs = qs.order_by(self._order)
        return qs

    def __iter__(self):
        return iter(self._qs())

    def __len__(self):
        return self._qs().count()

    def __bool__(self):
        return self._qs().exists()

    def __getitem__(self, key):
        if isinstance(key, (slice, int)):
            return self._qs()[key]
        raise TypeError(key)

    def __getattr__(self, name):
        if name.startswith('by_'):
            field = name[3:]
            desc = field.endswith('_desc')
            field = field[:-5] if desc else field
            model = apps.get_model(self._app, self._name)
            if field == 'id' or field in {f.name for f in model._meta.fields}:
                return Records(self._app, self._name, self._request, ('-' if desc else '') + field)
        raise AttributeError(name)

    @property
    def current(self):
        """ردیفِ جاری: از ?id=… در نشانی؛ اگر نبود، تازه‌ترین ردیف."""
        rid = (self._request.GET.get('id') or '').strip() if self._request is not None else ''
        qs = self._qs()
        if rid:
            return qs.filter(pk=rid).first() if rid.isdigit() else None
        return qs.order_by('-pk').first()


def data(request):
    return {'DATA': {app: {name: Records(app, name, request) for name in names} for app, names in MODELS.items()}}
'''


def active(project):
    from apps.projects.models import SiteTheme
    if project.is_imported:
        return False
    return SiteTheme.objects.filter(project=project, active=True).exists()


def extra_context_processor(project):
    return "        'config.site_data.data',\n" if active(project) else ''


def settings_tail(project):
    """پایتونِ قدیمی WebP را نمی‌شناسد و سرورِ فایل نوعِ غلط می‌فرستد."""
    if not active(project):
        return ''
    return ("\n# ── نوعِ فایلِ تصویرهای سایت ──\nimport mimetypes\nmimetypes.add_type('image/webp', '.webp')\n")


def patch_base(project, text):
    if not active(project):
        return text
    return text.replace(CDN_LINK, '').replace(BASE_LINK, BLOCKS_LINK)


def menu_items(project):
    """[(عنوان، نشانی)] از مدیرِ منو؛ اگر هنوز چیده نشده، صفحه‌های «در منو»."""
    from apps.projects.models import Page, SiteTheme
    pages = {p.pk: p for p in Page.objects.filter(project=project)}
    t = SiteTheme.objects.filter(project=project).first()
    rows = (t.menu_published if t and t.menu_published else None)
    return items_from(rows, pages)


def items_from(rows, pages):
    if not rows:
        return [(p.title, '/%s/' % p.slug if p.slug else '/') for p in pages.values() if p.in_menu]
    out = []
    for row in rows:
        if row.get('page'):
            p = pages.get(row['page'])
            if p is None:
                continue                  # صفحه حذف شده ⇐ در منو نمی‌ماند
            out.append((row.get('label') or p.title, '/%s/' % p.slug if p.slug else '/'))
        elif row.get('url'):
            out.append((row.get('label') or row['url'], row['url']))
    return out


def menu_code(project, quote):
    """متنِ لیستِ MENU برای config/context.py؛ None یعنی همان رفتارِ قدیمی."""
    if not active(project):
        return None
    return ', '.join('(%s, %s)' % (quote(t), quote(h)) for t, h in menu_items(project))


def preview_css(project):
    """پیش‌نمایشِ حالتِ کد و پیشنهادِ AI باید همان ظاهرِ بلوک‌ها را نشان بدهد؛ پروژهٔ قدیمی چیزی نمی‌گیرد."""
    if not active(project):
        return ''
    from apps.projects.models import Design, SiteTheme
    t = SiteTheme.objects.filter(project=project).first()
    data = theme_mod.clean_theme(t.published if t else None, project)
    chrome = '\n'.join(d.published_css for d in Design.objects.filter(project=project, target__in=('header', 'footer')) if d.published_css)
    return '\n' + theme_mod.blocks_css(data, '/api/v1/studio/builder-fonts/', chrome)


def after_run(gen):
    """فایل‌های مخصوصِ پروژهٔ دیداری. روی پروژهٔ قدیمی هیچ کاری نمی‌کند."""
    project = gen.p
    if not active(project):
        return
    from apps.projects.models import Design, Model, SiteTheme
    t = SiteTheme.objects.filter(project=project).first()
    data = theme_mod.clean_theme(t.published if t else None, project)
    chrome = '\n'.join(d.published_css for d in Design.objects.filter(project=project, target__in=('header', 'footer')) if d.published_css)
    gen._safe_write('static/css/blocks.css', theme_mod.blocks_css(data, '../fonts/', chrome))
    _, used = theme_mod.font_faces(data)
    folder = gen._target('static/fonts')
    os.makedirs(folder, exist_ok=True)
    for key in used:
        for name, _rng in theme_mod.FONTS[key]['files']:
            shutil.copyfile(os.path.join(theme_mod.FONT_DIR, name), os.path.join(folder, name))
            gen.written.append('static/fonts/%s' % name)
    models = {}
    for m in Model.objects.filter(app__project=project).select_related('app'):
        if m.app.name == 'site_forms' or (m.app.is_core and m.app.name == 'orders'):
            continue                      # دادهٔ خصوصی هرگز در قالب‌ها در دسترس نیست
        models.setdefault(m.app.name, []).append(m.name)
    gen._safe_write('config/site_data.py', SITE_DATA_TPL % {'models': repr(models)})
