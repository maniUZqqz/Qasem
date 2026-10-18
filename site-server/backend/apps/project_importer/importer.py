# -*- coding: utf-8 -*-
"""واردکردنِ پروژهٔ جنگوی موجود: ZIP ⇒ Workspace ⇒ تحلیل ⇒ متادیتای استودیو + گزارشِ سازگاری.

امنیتِ ZIP (idea.md §۸): مسیرِ مطلق و `..` رد می‌شوند، لینکِ نمادین باز نمی‌شود،
سقفِ تعدادِ فایل و حجمِ بازشده دارد. پروژه در فرایندِ استودیو اجرا نمی‌شود.
"""
import json
import os
import re
import shutil
import stat
import zipfile

from django.conf import settings
from django.db import transaction

from apps.code_generation.services import force_rmtree
from apps.projects.models import App, Field, Model, Page, Project, Route, View
from .analyzer import analyze_project
from .models import ImportReport

MAX_FILES = 20000
MAX_TEMPLATES = 400
MAX_BYTES = 600 * 1024 * 1024
TOP_LEVEL_SKIP = ('venv/', '.venv/', 'node_modules/', '__pycache__/', 'staticfiles/')


class ImportError_(Exception):
    pass


def _safe_members(zf):
    total = 0
    members = []
    for info in zf.infolist():
        name = info.filename.replace('\\', '/')
        if name.startswith('/') or name.startswith('../') or '/../' in name or ':' in name.split('/')[0]:
            raise ImportError_('فایلِ ZIP مسیرِ ناامن دارد: %s' % name)
        if any(seg in ('venv', '.venv', 'node_modules', '__pycache__', 'staticfiles', '.git') for seg in name.split('/')[:-1]):
            continue
        if name.endswith('.pyc'):
            continue
        mode = (info.external_attr >> 16) & 0xFFFF
        if stat.S_ISLNK(mode):
            continue
        total += info.file_size
        if total > MAX_BYTES:
            raise ImportError_('حجمِ بازشدهٔ ZIP از حد (%d MB) بیشتر است.' % (MAX_BYTES // 1024 // 1024))
        members.append(info)
        if len(members) > MAX_FILES:
            raise ImportError_('ZIP بیش از %d فایل دارد.' % MAX_FILES)
    return members


def extract_zip(fileobj, dest):
    """ZIP را امن باز می‌کند؛ اگر همه‌چیز داخلِ یک پوشهٔ بالایی بود، همان یک پله بالا می‌آید."""
    os.makedirs(dest, exist_ok=True)
    with zipfile.ZipFile(fileobj) as zf:
        members = _safe_members(zf)
        for info in members:
            zf.extract(info, dest)
    entries = [e for e in os.listdir(dest) if not e.startswith('__MACOSX')]
    if len(entries) == 1 and os.path.isdir(os.path.join(dest, entries[0])) and \
            not os.path.exists(os.path.join(dest, 'manage.py')):
        inner = os.path.join(dest, entries[0])
        for e in os.listdir(inner):
            shutil.move(os.path.join(inner, e), os.path.join(dest, e))
        force_rmtree(inner)
    return dest


def import_project(name, slug, zip_file=None, server_path=None):
    """⇒ (project, report)"""
    p = Project(name=name, slug=slug or '', source=Project.SOURCE_IMPORTED, status=Project.STATUS_DRAFT)
    p.save()
    dest = str(p.path)
    try:
        if zip_file is not None:
            extract_zip(zip_file, dest)
        elif server_path:
            sp = os.path.realpath(server_path)
            roots = [os.path.realpath(r) for r in getattr(settings, 'IMPORT_SERVER_ROOTS', [])]
            if not any(sp == r or sp.startswith(r + os.sep) for r in roots):
                raise ImportError_('فقط از این پوشه‌ها می‌شود وارد کرد: %s' % '، '.join(roots or ['—']))
            if sp.startswith(os.path.realpath(str(settings.WORKSPACES_ROOT))):
                raise ImportError_('پوشهٔ پروژه‌های خودِ استودیو را نمی‌شود دوباره وارد کرد.')
            if not os.path.isdir(sp):
                raise ImportError_('پوشهٔ روی سرور پیدا نشد: %s' % sp)
            if os.path.exists(dest):
                os.rmdir(dest) if not os.listdir(dest) else None
            shutil.copytree(sp, dest, symlinks=True,
                            ignore=shutil.ignore_patterns('venv', '.venv', 'env', 'node_modules', '__pycache__',
                                                          '*.pyc', 'staticfiles', '.git', '*.rar', '*.zip',
                                                          '*.log', '.preview.*', '.studio-*'))
        else:
            raise ImportError_('نه ZIP داده شد نه مسیرِ سرور.')
        data = analyze_project(dest)
        if not data['ok']:
            raise ImportError_('؛ '.join(data['warnings']))
        if len(data['templates']) > MAX_TEMPLATES:
            data['warnings'].append('%d قالب پیدا شد؛ فقط %d تای اول برای ویرایش آمد.'
                                    % (len(data['templates']), MAX_TEMPLATES))
        with transaction.atomic():
            _materialize(p, data)
        from apps.code_generation import vcs
        vcs.commit(p, 'واردکردنِ پروژه (نسخهٔ اصلی)')
        report = ImportReport.objects.create(
            project=p, level=2 if data['apps'] else 1, data=json.dumps(_slim(data), ensure_ascii=False),
            warnings='\n'.join(data['warnings']), unsupported='\n'.join(data['unsupported']))
        return p, report
    except Exception as exc:  # noqa — هر خطایی: نه پروژهٔ نیمه‌کاره بماند نه پوشه
        force_rmtree(dest)
        Project.objects.filter(pk=p.pk).delete()
        if isinstance(exc, (ImportError_, zipfile.BadZipFile, OSError)):
            raise ImportError_(str(exc))
        raise ImportError_('تحلیل به خطا خورد: %r' % exc)


def _slim(data):
    """نسخهٔ سبک برای ذخیره (بدونِ کدِ خام)."""
    out = {k: v for k, v in data.items() if k != 'apps'}
    out['apps'] = []
    for a in data['apps']:
        out['apps'].append({
            'label': a['label'], 'package': a['package'], 'dir': a['dir'],
            'models': [{'name': m['name'], 'fields': len(m['fields']), 'abstract': m['abstract']} for m in a['models']],
            'routes': a['routes'], 'views': [{'name': v['name'], 'kind': v['kind'], 'bases': v['bases']} for v in a['views']],
        })
    return out


def _materialize(p, data):
    """تحلیل ⇒ ردیف‌های استودیو (همه unmanaged؛ فقط نمایش و ویرایشِ محدود)."""
    # ریشهٔ پروژه ممکن است یک پله پایین‌تر از workspace باشد (ZIP با پوشهٔ بالایی)
    root = data['project_root']
    if os.path.abspath(root) != os.path.abspath(str(p.path)):
        for e in os.listdir(root):
            shutil.move(os.path.join(root, e), os.path.join(str(p.path), e))
    p.settings_module = data['settings_module'] or ''
    p.urls_module = data.get('root_urlconf') or ''
    p.apps_dir = data.get('apps_dir') or ''
    p.site_title = p.name
    p.save()

    prefixes = {}
    for r in data.get('root_routes') or []:
        m = re.match(r'''include\(\s*['"]([\w.]+)\.urls['"]''', r['view'])
        if m:
            prefixes.setdefault(m.group(1), r['pattern'])
    model_index = {}
    for i, a in enumerate(data['apps'], 1):
        app = App.objects.create(project=p, name=a['label'], verbose_name_fa=a['label'], managed=False,
                                 path=a['dir'], order=i * 10,
                                 url_prefix=(prefixes.get(a['package']) or '')[:80])
        for j, m in enumerate(a['models'], 1):
            mdl = Model.objects.create(app=app, name=m['name'], verbose_name_fa=m['verbose'] or m['name'],
                                       verbose_plural_fa=m['verbose_plural'], ordering=m['ordering'],
                                       managed=False, raw_code=m['raw'], order=j * 10,
                                       in_admin=False)
            model_index[(a['label'], m['name'])] = mdl
            model_index[m['name']] = model_index.get(m['name']) or mdl
            for k, f in enumerate(m['fields'], 1):
                Field.objects.create(
                    model=mdl, name=f['name'], verbose_name_fa=str(f['verbose'] or ''), field_type=f['type'],
                    max_length=f['max_length'] if isinstance(f['max_length'], int) else None,
                    max_digits=f['max_digits'] if isinstance(f['max_digits'], int) else None,
                    decimal_places=f['decimal_places'] if isinstance(f['decimal_places'], int) else None,
                    null=f['null'] is True, blank=f['blank'] is True, unique=f['unique'] is True,
                    db_index=f['db_index'] is True, auto_now=f['auto_now'] is True, auto_now_add=f['auto_now_add'] is True,
                    default=str(f['default'] or '')[:120], choices=f['choices'],
                    related_ref=str(f['related'] or '')[:120],
                    on_delete=f['on_delete'] if f['on_delete'] in dict(Field.ON_DELETE) else 'CASCADE',
                    related_name=str(f['related_name'] or '')[:60], raw_code=(f['raw'] or '')[:400], order=k * 10)
        for j, v in enumerate(a['views'], 1):
            View.objects.create(app=app, name=v['name'][:60], kind='custom', managed=False,
                                custom_code=v['raw'], description=('کلاس: %s' % ', '.join(v['bases'])) if v['bases'] else 'تابع',
                                order=j * 10)
        for j, r in enumerate(a['routes'], 1):
            Route.objects.create(project=p, app=app, pattern=r['pattern'][:200], name=(r['name'] or '')[:80],
                                 view_text=r['view'][:200], managed=False, order=j * 10)
    # رابطه‌های داخلیِ پروژه را به مدلِ واقعی وصل کن
    for fld in Field.objects.filter(model__app__project=p, field_type__in=list(Field.RELATIONAL)):
        ref = fld.related_ref
        target = None
        if '.' in ref and not ref.startswith('settings.'):
            target = model_index.get(tuple(ref.split('.', 1)))
        elif ref and ref not in ('self',):
            target = model_index.get(ref.strip("'\""))
        if target:
            fld.related_model = target
            fld.save(update_fields=['related_model'])
    for j, r in enumerate(data.get('root_routes') or [], 1):
        Route.objects.create(project=p, app=None, pattern=r['pattern'][:200], name=(r['name'] or '')[:80],
                             view_text=r['view'][:200], managed=False, order=j * 10)
    # قالب‌ها ⇒ صفحه‌های واردشده (کلِ فایل)
    from apps.code_generation.generator import sha
    for j, rel in enumerate(data['templates'][:MAX_TEMPLATES], 1):
        full = os.path.join(str(p.path), rel)
        try:
            with open(full, encoding='utf-8', errors='replace') as fh:
                content = fh.read()
        except OSError:
            continue
        Page.objects.create(project=p, title=rel[-120:], slug=('t-%d' % j), kind='imported', body_html=content,
                            in_menu=False, file_path=rel, synced_hash=sha(content), order=j * 10)
    p.status = Project.STATUS_GENERATED
    p.save(update_fields=['status'])


def reload_page_from_disk(page):
    """فایلِ روی دیسک ⇒ body (وقتی بیرون از استودیو عوض شده)."""
    from apps.code_generation.generator import sha
    full = os.path.join(str(page.project.path), page.file_path)
    with open(full, encoding='utf-8', errors='replace') as fh:
        content = fh.read()
    page.body_html = content
    page.synced_hash = sha(content)
    page.save(update_fields=['body_html', 'synced_hash'])
    return page


def disk_drift(page):
    """آیا فایلِ روی دیسک با آخرین نسخهٔ هماهنگ‌شده فرق دارد؟ (idea.md §۵.۳ تشخیصِ تعارض)"""
    from apps.code_generation.generator import sha
    if not page.file_path:
        return False
    full = os.path.join(str(page.project.path), page.file_path)
    try:
        with open(full, encoding='utf-8', errors='replace') as fh:
            return sha(fh.read()) != page.synced_hash
    except OSError:
        return False
