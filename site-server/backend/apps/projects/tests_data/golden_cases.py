# -*- coding: utf-8 -*-
"""سه پروژهٔ نمونه که خروجیِ موتورِ تولیدشان با کدِ پیش از ویرایشگرِ دیداری ثبت شده (generator_golden.json).

آزمونِ سازگاری همین‌ها را دوباره می‌سازد و بایت‌به‌بایت مقایسه می‌کند: پروژه‌ای که از ویرایشگرِ دیداری
استفاده نکرده باید دقیقاً همان فایل‌های قبلی را بگیرد.
"""
import datetime
import hashlib
import io
import os
import zipfile
from unittest import mock

from django.utils import timezone

FROZEN = datetime.datetime(2026, 10, 1, 12, 0, tzinfo=datetime.timezone.utc)
SKIP_DIRS = {'.git', '__pycache__'}


def tree_hashes(root):
    out = {}
    for dp, dn, fn in os.walk(str(root)):
        dn[:] = [d for d in dn if d not in SKIP_DIRS]
        for name in fn:
            if name.startswith('.preview') or name.endswith('.pyc'):
                continue
            full = os.path.join(dp, name)
            with open(full, 'rb') as fh:
                out[os.path.relpath(full, str(root)).replace(os.sep, '/')] = hashlib.sha1(fh.read()).hexdigest()
    return out


def _run(project):
    from apps.code_generation.generator import ProjectGenerator
    with mock.patch.object(timezone, 'now', return_value=FROZEN):
        ProjectGenerator(project).run()
    return tree_hashes(project.path)


def case_shop():
    from apps.code_generation import services
    from apps.projects.models import Project
    p = Project.objects.create(name='فروشگاهِ نمونه', slug='golden-shop', brand_color='#126F85')
    services.scaffold_shop(p)
    return _run(p)


def case_custom():
    """پروژهٔ دستی: اپ، مدل، CRUD، نشانیِ ریشه، بدنه/CSS و هدر/فوتر/CSSِ دستی."""
    from apps.code_generation import services
    from apps.projects.models import App, Field, Model, Page, Project, Route, SharedPart, View
    p = Project.objects.create(name='وبلاگ', slug='golden-blog', brand_color='#7c3aed', site_title='وبلاگِ من',
                               extra_requirements='requests>=2.0', custom_settings='FOO = 1')
    app = App.objects.create(project=p, name='blog', url_prefix='blog/', verbose_name_fa='وبلاگ')
    m = Model.objects.create(app=app, name='Post', verbose_name_fa='نوشته', verbose_plural_fa='نوشته‌ها', ordering='-created_at')
    Field.objects.create(model=m, name='title', verbose_name_fa='عنوان', field_type='CharField', max_length=120, order=10)
    Field.objects.create(model=m, name='body', verbose_name_fa='متن', field_type='TextField', blank=True, order=20)
    Field.objects.create(model=m, name='cover', verbose_name_fa='کاور', field_type='ImageField', null=True, blank=True, order=30)
    Field.objects.create(model=m, name='created_at', field_type='DateTimeField', auto_now_add=True, order=40)
    services.add_crud(m)
    v = View.objects.create(app=app, name='about_view', kind='custom',
                            custom_code='def about_view(request):\n    from django.http import HttpResponse\n    return HttpResponse("x")\n')
    Route.objects.create(project=p, app=None, pattern='ping/', name='ping', view=v)
    Page.objects.create(project=p, title='خانه', slug='', kind='home', order=10,
                        body_html='<section class="section"><h1>سلام {{ SITE_TITLE }}</h1></section>', css='h1{color:red}')
    Page.objects.create(project=p, title='درباره', slug='about', kind='static', order=20, in_menu=False)
    SharedPart.objects.create(project=p, kind='header', content='<header>{{ SITE_TITLE }}</header>')
    SharedPart.objects.create(project=p, kind='footer', content='<footer>پا</footer>')
    SharedPart.objects.create(project=p, kind='base_css', content=':root{--brand:#000}')
    return _run(p)


SAMPLE_FILES = {
    'manage.py': "import os, sys\nos.environ.setdefault('DJANGO_SETTINGS_MODULE', 'mysite.settings')\n",
    'mysite/__init__.py': '',
    'mysite/settings.py': "INSTALLED_APPS = [\n    'django.contrib.admin',\n    'shop',\n]\nROOT_URLCONF = 'mysite.urls'\n"
                          "TEMPLATES = []\nSECRET_KEY = 'x'\n",
    'mysite/urls.py': "from django.urls import path, include\nurlpatterns = [\n    path('shop/', include('shop.urls')),\n]\n",
    'shop/__init__.py': '',
    'shop/models.py': "from django.db import models\n\n\nclass Item(models.Model):\n    name = models.CharField(max_length=20)\n",
    'shop/views.py': 'from django.shortcuts import render\n\n\ndef index(request):\n    return render(request, "shop/index.html")\n',
    'shop/urls.py': "from django.urls import path\nfrom . import views\nurlpatterns = [path('', views.index, name='index')]\n",
    'shop/templates/shop/index.html': '{% extends "base.html" %}\n{% block content %}<h1>سلام</h1>{% endblock %}\n',
    'templates/base.html': '<html><body>{% block content %}{% endblock %}</body></html>\n',
}


def case_imported():
    """پروژهٔ واردشده: قالبِ ویرایش‌شده + اپِ تازهٔ استودیو."""
    from apps.project_importer.importer import import_project
    from apps.projects.models import App, Field, Model
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        for rel, body in SAMPLE_FILES.items():
            z.writestr('demo/' + rel, body)
    buf.seek(0)
    buf.name = 'mysite.zip'
    out = import_project('واردشده', 'golden-imported', zip_file=buf)
    p = out[0] if isinstance(out, (tuple, list)) else out
    pg = p.pages.filter(kind='imported').order_by('file_path').first()
    if pg:
        pg.body_html = pg.body_html.replace('سلام', 'درود')
        pg.save()
    app = App.objects.create(project=p, name='extra', url_prefix='extra/', verbose_name_fa='افزوده')
    m = Model.objects.create(app=app, name='Note', verbose_name_fa='یادداشت')
    Field.objects.create(model=m, name='title', field_type='CharField', max_length=50, order=10)
    return _run(p)


CASES = {'shop': case_shop, 'custom': case_custom, 'imported': case_imported}


def build_all():
    return {name: fn() for name, fn in CASES.items()}
