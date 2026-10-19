# -*- coding: utf-8 -*-
"""کارهای سطحِ بالا روی پروژه: ساختِ قالبِ استاندارد، تولید، وارسی، نسخه، خروجی."""
import io
import os
import shutil
import subprocess
import time
import zipfile

from django.utils import timezone

from apps.projects.models import App, BuildLog, Field, Model, Page, Project, Route, View
from . import envs, vcs
from .generator import (DEFAULT_BODIES, GenerationError, ProjectGenerator, default_template_body,
                        run_readme, runner_files)


# ──────────────────────────────────────────────────────────────────
def scaffold_shop(project):
    """قالبِ استانداردِ فروشگاه (فازِ ۰۲ در idea.md).

    اپ‌های `catalog`، `orders` و `cart` با مدل‌های پایه و چهار صفحه.
    `cart` مدلی ندارد (روی session است) ولی به‌عنوانِ اپ ثبت می‌شود تا
    موتور بفهمد باید سبد و تسویهٔ واقعی تولید کند.
    """
    if project.apps.exists():
        return False

    catalog = App.objects.create(project=project, name='catalog', url_prefix='catalog/',
                                 verbose_name_fa='کاتالوگ', is_core=True, order=10,
                                 description='محصول، دسته‌بندی و تصویرها')
    orders = App.objects.create(project=project, name='orders', url_prefix='orders/',
                                verbose_name_fa='سفارش‌ها', is_core=True, order=20,
                                description='سفارش و قلم‌های آن')
    App.objects.create(project=project, name='cart', url_prefix='cart/',
                       verbose_name_fa='سبدِ خرید', is_core=True, order=30,
                       description='سبدِ خرید روی session و تسویه‌حساب')

    cat = Model.objects.create(app=catalog, name='Category',
                               verbose_name_fa='دسته', verbose_plural_fa='دسته‌ها', order=10)
    Field.objects.create(model=cat, name='name', verbose_name_fa='نام',
                         field_type='CharField', max_length=120, order=10)
    Field.objects.create(model=cat, name='slug', verbose_name_fa='اسلاگ',
                         field_type='SlugField', max_length=120, unique=True, order=20)

    prod = Model.objects.create(app=catalog, name='Product',
                                verbose_name_fa='محصول', verbose_plural_fa='محصول‌ها', order=20,
                                ordering='-created_at')
    for i, kw in enumerate([
        dict(name='name', verbose_name_fa='نامِ محصول', field_type='CharField', max_length=200),
        dict(name='slug', verbose_name_fa='اسلاگ', field_type='SlugField', max_length=200, unique=True),
        dict(name='description', verbose_name_fa='توضیح', field_type='TextField', blank=True),
        dict(name='price', verbose_name_fa='قیمت (تومان)', field_type='DecimalField', default='0'),
        dict(name='stock', verbose_name_fa='موجودی', field_type='IntegerField', default='0'),
        dict(name='is_active', verbose_name_fa='فعال', field_type='BooleanField', default='True'),
        dict(name='image', verbose_name_fa='تصویر', field_type='ImageField', null=True, blank=True),
        dict(name='category', verbose_name_fa='دسته', field_type='ForeignKey', related_model=cat,
             on_delete='SET_NULL', related_name='products', null=True, blank=True),
        dict(name='created_at', verbose_name_fa='تاریخِ ثبت', field_type='DateTimeField',
             default='timezone.now'),
    ], 1):
        Field.objects.create(model=prod, order=i * 10, **kw)

    order = Model.objects.create(app=orders, name='Order', verbose_name_fa='سفارش',
                                 verbose_plural_fa='سفارش‌ها', order=10, ordering='-created_at')
    for i, kw in enumerate([
        dict(name='customer_name', verbose_name_fa='نامِ مشتری', field_type='CharField', max_length=120),
        dict(name='phone', verbose_name_fa='تلفن', field_type='CharField', max_length=20),
        dict(name='address', verbose_name_fa='نشانی', field_type='TextField', blank=True),
        dict(name='total', verbose_name_fa='جمعِ کل', field_type='DecimalField', default='0'),
        dict(name='is_paid', verbose_name_fa='پرداخت شده', field_type='BooleanField', default='False'),
        dict(name='created_at', verbose_name_fa='تاریخ', field_type='DateTimeField',
             default='timezone.now'),
    ], 1):
        Field.objects.create(model=order, order=i * 10, **kw)

    item = Model.objects.create(app=orders, name='OrderItem', verbose_name_fa='قلمِ سفارش',
                                verbose_plural_fa='قلم‌های سفارش', order=20)
    for i, kw in enumerate([
        dict(name='order', verbose_name_fa='سفارش', field_type='ForeignKey', related_model=order,
             on_delete='CASCADE', related_name='items'),
        dict(name='product', verbose_name_fa='محصول', field_type='ForeignKey', related_model=prod,
             on_delete='PROTECT', related_name='order_items'),
        dict(name='quantity', verbose_name_fa='تعداد', field_type='IntegerField', default='1'),
        dict(name='unit_price', verbose_name_fa='قیمتِ واحد', field_type='DecimalField', default='0'),
    ], 1):
        Field.objects.create(model=item, order=i * 10, **kw)

    pages = [
        ('صفحهٔ اصلی', '', 'home', 10),
        ('محصولات', 'products', 'product_list', 20),
        ('سبد خرید', 'cart', 'cart', 30),
        ('تسویه‌حساب', 'checkout', 'checkout', 40),
    ]
    for title, slug, kind, order_ in pages:
        Page.objects.create(project=project, title=title, slug=slug, kind=kind,
                            order=order_, body_html=DEFAULT_BODIES[kind],
                            in_menu=(kind in ('home', 'product_list')))
    return True


# ──────────────────────────────────────────────── ویوِ استاندارد + نشانیِ خودکار
ROUTE_SUGGEST = {'list': ('{m}/', '{m}_list'), 'detail': ('{m}/<int:pk>/', '{m}_detail'),
                 'create': ('{m}/new/', '{m}_create'), 'update': ('{m}/<int:pk>/edit/', '{m}_update'),
                 'delete': ('{m}/<int:pk>/delete/', '{m}_delete'), 'template': ('{v}/', '{v}'),
                 'custom': ('{v}/', '{v}')}
CRUD_ORDER = ['list', 'detail', 'create', 'update', 'delete']


def _suggest_route(view):
    pat, nm = ROUTE_SUGGEST[view.kind]
    m = view.model.snake if view.model_id else view.name
    return pat.format(m=m, v=view.name), nm.format(m=m, v=view.name)


def add_view(app, name, kind, model=None, with_route=True, **extra):
    """ویو + نشانیِ پیشنهادی + بدنهٔ پیش‌فرضِ قالب — همه با هم، تا «یک کلیک» کافی باشد."""
    v = View.objects.create(app=app, name=name, kind=kind, model=model,
                            order=app.views.count() * 10 + 10, **extra)
    if with_route:
        pat, nm = _suggest_route(v)
        if not Route.objects.filter(project=app.project, app=app, pattern=pat).exists():
            if Route.objects.filter(project=app.project, name=nm).exists():
                nm = '%s_%s' % (app.name, nm)
            Route.objects.create(project=app.project, app=app, pattern=pat, name=nm, view=v,
                                 order=app.routes.count() * 10 + 10)
    if not v.template_body and v.needs_template:
        v.template_body = default_template_body(v)
        v.save(update_fields=['template_body'])
    return v


def add_crud(model, kinds=None):
    """پنج ویوِ فهرست/جزئیات/ساخت/ویرایش/حذف + نشانی‌ها برای یک مدل — یک کلیک.

    اول همهٔ ویوها و نشانی‌ها ساخته می‌شوند، بعد قالب‌ها؛ تا قالبِ «فهرست» لینکِ
    «جزئیات» و «تازه» را بشناسد.
    """
    app = model.app
    made = []
    for kind in (kinds or CRUD_ORDER):
        name = '%s_%s' % (model.snake, kind)
        if View.objects.filter(app=app, name=name).exists():
            continue
        v = View.objects.create(app=app, name=name, kind=kind, model=model,
                                description='%s — %s' % (model.verbose_name_fa or model.name,
                                                         dict(View.KIND)[kind].split(' (')[0]),
                                paginate_by=12 if kind == 'list' else None,
                                order=app.views.count() * 10 + 10)
        pat, nm = _suggest_route(v)
        if Route.objects.filter(project=app.project, name=nm).exists():
            nm = '%s_%s' % (app.name, nm)
        Route.objects.create(project=app.project, app=app, pattern=pat, name=nm, view=v,
                             order=app.routes.count() * 10 + 10)
        made.append(v)
    for v in made:
        v.template_body = default_template_body(v)
        v.save(update_fields=['template_body'])
    return made


# ──────────────────────────────────────────────────────────────────
def generate(project, message=None):
    """تولیدِ کد + وارسی + commit. خروجی: (ok, summary, detail)"""
    try:
        gen = ProjectGenerator(project)
        written = gen.run()
    except GenerationError as exc:
        project.status = Project.STATUS_ERROR
        project.last_error = str(exc)
        project.save(update_fields=['status', 'last_error'])
        BuildLog.objects.create(project=project, ok=False, summary='تولید نشد', detail=str(exc))
        return False, 'تولید نشد', str(exc)

    ok, detail = run_checks(project)
    if gen.warnings:
        detail = 'هشدارها:\n' + '\n'.join('· ' + w for w in gen.warnings) + '\n\n' + detail
    commit = vcs.commit(project, (message or 'تولیدِ کد') + ('' if ok else ' (وارسی خطا داد)'))
    if commit:
        detail = 'نسخهٔ %s ثبت شد:\n%s\n\n%s' % (commit['sha'], commit['stat'], detail)
    project.status = Project.STATUS_GENERATED if ok else Project.STATUS_ERROR
    project.last_error = '' if ok else detail[-3000:]
    project.generated_at = timezone.now()
    project.save(update_fields=['status', 'last_error', 'generated_at'])
    summary = '%d فایل نوشته شد' % len(written) + (' · نسخهٔ %s' % commit['sha'] if commit else '')
    BuildLog.objects.create(project=project, ok=ok, summary=summary, detail=detail,
                            files_written=len(written))
    return ok, summary, detail


def _env(project):
    root = str(project.path)
    return dict(os.environ, PYTHONPATH=root, DJANGO_SETTINGS_MODULE=project.settings_module_name,
                DJANGO_ALLOWED_HOSTS='*', DJANGO_DEBUG='True', STUDIO_MOUNTED='False')


def _run(project, args, timeout):
    return subprocess.run([envs.python_for(project)] + args, cwd=str(project.path), env=_env(project),
                          capture_output=True, text=True, timeout=timeout, encoding='utf-8', errors='replace')


def run_checks(project):
    """`manage.py check` و `makemigrations --dry-run` روی پروژهٔ تولیدشده."""
    out = []
    for args, label in ((['manage.py', 'check'], 'check'),
                        (['manage.py', 'makemigrations', '--dry-run'], 'makemigrations')):
        try:
            r = _run(project, args, 180)
        except Exception as exc:  # noqa
            return False, '%s: %s' % (label, exc)
        out.append('$ %s\n%s%s' % (' '.join(args), r.stdout, r.stderr))
        if r.returncode != 0:
            return False, '\n'.join(out)
    return True, '\n'.join(out)


def migrate(project):
    out = []
    for args in (['manage.py', 'makemigrations'], ['manage.py', 'migrate', '--noinput']):
        r = _run(project, args, 300)
        out.append('$ %s\n%s%s' % (' '.join(args), r.stdout, r.stderr))
        if r.returncode != 0:
            return False, '\n'.join(out)
    vcs.commit(project, 'مهاجرت (migrations)')
    return True, '\n'.join(out)


EXPORT_SKIP_DIRS = {'venv', '.venv', '__pycache__', 'staticfiles', 'node_modules'}
EXPORT_SKIP_FILES = {'.admin-password.txt'}
DEFAULT_REQUIREMENTS = 'Django>=4.2,<5.1\nPillow>=10.0\n'


def export_zip(project, with_git=False):
    """ZIPِ کاملِ پروژه. اگر run.bat / run.sh / scripts/ensure_admin.py / requirements.txt در پوشه
    نبود (پروژهٔ قدیمی یا واردشده) همان‌جا به ZIP اضافه می‌شود تا خروجی همیشه یک‌کلیکه اجرا شود."""
    root = str(project.path)
    buf = io.BytesIO()
    skip = set(EXPORT_SKIP_DIRS) | (set() if with_git else {'.git'})
    present = set()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
        for dp, dn, fn in os.walk(root):
            dn[:] = [d for d in dn if d not in skip]
            for name in fn:
                if name.endswith(('.pyc', '.sqlite3')) or name.startswith(('.preview', '.studio-')) \
                        or name in EXPORT_SKIP_FILES:
                    continue
                full = os.path.join(dp, name)
                rel = os.path.relpath(full, root).replace(os.sep, '/')
                present.add(rel)
                z.write(full, project.slug + '/' + rel)

        extras = runner_files(project.name, project.settings_module_name)
        if 'run.bat' not in present:
            extras['README-RUN.md'] = (run_readme(project.name), 0)
        if 'requirements.txt' not in present:
            extras['requirements.txt'] = (DEFAULT_REQUIREMENTS, 0)
        stamp = time.localtime()[:6]
        for rel, (body, mode) in extras.items():
            if rel in present:
                continue
            info = zipfile.ZipInfo(project.slug + '/' + rel, date_time=stamp)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = ((mode or 0o644) & 0xFFFF) << 16
            z.writestr(info, body.encode('utf-8'))
    buf.seek(0)
    return buf


def force_rmtree(path):
    """حذفِ کاملِ پوشه — در ویندوز فایل‌های فقط‌خواندنیِ .git را هم (ignore_errors آن‌ها را بی‌صدا جا می‌گذاشت)."""
    import stat

    def _retry(func, p, _exc):
        try:
            os.chmod(p, stat.S_IWRITE)
            func(p)
        except OSError:
            pass
    if os.path.exists(path):
        shutil.rmtree(path, onerror=_retry)


def delete_workspace(project):
    force_rmtree(str(project.path))
