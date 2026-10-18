# -*- coding: utf-8 -*-
"""تحلیلِ ایستای یک پروژهٔ جنگوی موجود (idea.md §۸) — فقط با `ast`، بدونِ اجرای کد.

⚠ امنیت: هیچ خطی از پروژهٔ واردشده import یا exec نمی‌شود. فقط متن خوانده و
   درختِ نحوی ساخته می‌شود. اجرای واقعی (check/migrate/preview) جداست و در
   زیرفرایند با کاربرِ وب انجام می‌شود — کاربر هنگامِ واردکردن هشدارش را می‌بیند.

خروجی: یک dict بزرگ با apps/models/fields/urls/views/templates + warnings/unsupported.
"""
import ast
import os
import re

SKIP_DIRS = {'venv', '.venv', 'env', 'node_modules', '__pycache__', '.git', 'staticfiles',
             'media', 'site-packages', 'migrations', 'dist', 'build'}
KNOWN_FIELDS = {
    'CharField', 'TextField', 'IntegerField', 'PositiveIntegerField', 'BigIntegerField', 'FloatField',
    'DecimalField', 'BooleanField', 'DateField', 'DateTimeField', 'TimeField', 'EmailField', 'URLField',
    'SlugField', 'UUIDField', 'JSONField', 'ImageField', 'FileField', 'ForeignKey', 'ManyToManyField',
    'OneToOneField',
}
MODEL_BASES = {'Model', 'AbstractUser', 'AbstractBaseUser', 'PermissionsMixin', 'MPTTModel', 'TimeStampedModel'}


def _read(path):
    try:
        with open(path, encoding='utf-8', errors='replace') as fh:
            return fh.read()
    except OSError:
        return ''


def _unparse(node):
    try:
        return ast.unparse(node)
    except Exception:  # noqa
        return '…'


def _const(node):
    return node.value if isinstance(node, ast.Constant) else None


def find_manage(root):
    """manage.py را تا عمقِ ۳ پیدا می‌کند ⇒ (پوشهٔ پروژه، ماژولِ تنظیمات)."""
    best = None
    for dp, dn, fn in os.walk(root):
        dn[:] = [d for d in dn if d not in SKIP_DIRS]
        depth = os.path.relpath(dp, root).count(os.sep)
        if 'manage.py' in fn:
            cand = (depth, dp)
            if best is None or cand < best:
                best = cand
        if depth >= 3:
            dn[:] = []
    if not best:
        return None, None
    src = _read(os.path.join(best[1], 'manage.py'))
    m = re.search(r'''DJANGO_SETTINGS_MODULE['"]\s*,\s*['"]([\w.]+)['"]''', src)
    return best[1], (m.group(1) if m else None)


# ──────────────────────────────────────────────── settings
def analyze_settings(project_root, settings_module):
    out = {'installed_apps': [], 'root_urlconf': '', 'template_dirs': [], 'auth_user_model': '',
           'db_engine': '', 'warnings': []}
    if not settings_module:
        out['warnings'].append('ماژولِ تنظیمات از manage.py خوانده نشد.')
        return out
    rel = settings_module.replace('.', '/')
    path = os.path.join(project_root, rel + '.py')
    if not os.path.exists(path):
        alt = os.path.join(project_root, rel, '__init__.py')
        if os.path.exists(alt):
            path = alt
            out['warnings'].append('تنظیمات یک پکیج است (settings/__init__.py) — فقط فایلِ اصلی خوانده شد.')
        else:
            out['warnings'].append('فایلِ تنظیمات پیدا نشد: %s' % rel)
            return out
    try:
        tree = ast.parse(_read(path))
    except SyntaxError as exc:
        out['warnings'].append('تنظیمات قابلِ تجزیه نبود: %s' % exc)
        return out
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AugAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            names = [t.id for t in targets if isinstance(t, ast.Name)]
            if not names:
                continue
            name, val = names[0], node.value
            if name == 'INSTALLED_APPS' and isinstance(val, (ast.List, ast.Tuple)):
                out['installed_apps'] += [e.value for e in val.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)]
            elif name == 'ROOT_URLCONF' and _const(val):
                out['root_urlconf'] = _const(val)
            elif name == 'AUTH_USER_MODEL' and _const(val):
                out['auth_user_model'] = _const(val)
            elif name == 'DATABASES':
                for c in ast.walk(val):
                    if isinstance(c, ast.Constant) and isinstance(c.value, str) and 'django.db.backends' in c.value:
                        out['db_engine'] = c.value.rsplit('.', 1)[-1]
                        break
            elif name == 'TEMPLATES':
                for c in ast.walk(val):
                    if isinstance(c, ast.Constant) and isinstance(c.value, str) and 'templates' in c.value.lower():
                        out['template_dirs'].append(c.value)
    # DIRS به‌شکلِ BASE_DIR / 'templates' هم رایج است
    src = _read(path)
    for m in re.finditer(r'''BASE_DIR\s*/\s*['"]([^'"]+)['"]''', src):
        if 'template' in m.group(1).lower() and m.group(1) not in out['template_dirs']:
            out['template_dirs'].append(m.group(1))
    for m in re.finditer(r'''os\.path\.join\(\s*BASE_DIR\s*,\s*['"]([^'"]+)['"]\s*\)''', src):
        if 'template' in m.group(1).lower() and m.group(1) not in out['template_dirs']:
            out['template_dirs'].append(m.group(1))
    if out['db_engine'] and out['db_engine'] != 'sqlite3':
        out['warnings'].append('دیتابیسِ پروژه %s است؛ برای پیش‌نمایش باید متغیرهای محیطی‌اش را بدهی.' % out['db_engine'])
    if out['auth_user_model']:
        out['warnings'].append('مدلِ کاربرِ سفارشی دارد (%s).' % out['auth_user_model'])
    return out


def _local_apps(project_root, installed):
    """اپ‌هایی که پوشه‌شان داخلِ پروژه است ⇒ [(label, package, rel_dir)]."""
    out = []
    for entry in installed:
        pkg = entry
        if entry.endswith('Config') and '.apps.' in entry:
            pkg = entry.split('.apps.')[0]            # 'shop.apps.ShopConfig' ⇒ 'shop'
        rel = pkg.replace('.', '/')
        if os.path.isdir(os.path.join(project_root, rel)):
            out.append((pkg.rsplit('.', 1)[-1], pkg, rel))
    return out


# ──────────────────────────────────────────────── models.py
def _base_names(cls):
    names = []
    for b in cls.bases:
        if isinstance(b, ast.Attribute):
            names.append(b.attr)
        elif isinstance(b, ast.Name):
            names.append(b.id)
    return names


def _kw(call, key):
    for k in call.keywords:
        if k.arg == key:
            return k.value
    return None


def analyze_models(path, src=None):
    src = src if src is not None else _read(path)
    try:
        tree = ast.parse(src)
    except SyntaxError as exc:
        return [], ['models.py قابلِ تجزیه نبود: %s' % exc]
    models, notes = [], []
    class_names = {n.name for n in tree.body if isinstance(n, ast.ClassDef)}
    for cls in tree.body:
        if not isinstance(cls, ast.ClassDef):
            continue
        bases = _base_names(cls)
        is_model = bool(set(bases) & MODEL_BASES) or any(b in class_names for b in bases)
        if not is_model:
            continue
        m = {'name': cls.name, 'bases': bases, 'fields': [], 'meta': {}, 'abstract': False,
             'raw': ast.get_source_segment(src, cls) or '', 'verbose': '', 'verbose_plural': '', 'ordering': ''}
        for node in cls.body:
            if isinstance(node, ast.ClassDef) and node.name == 'Meta':
                for s in node.body:
                    if isinstance(s, ast.Assign) and s.targets and isinstance(s.targets[0], ast.Name):
                        key = s.targets[0].id
                        if key == 'abstract' and _const(s.value) is True:
                            m['abstract'] = True
                        elif key == 'verbose_name' and _const(s.value):
                            m['verbose'] = str(_const(s.value))
                        elif key == 'verbose_name_plural' and _const(s.value):
                            m['verbose_plural'] = str(_const(s.value))
                        elif key == 'ordering':
                            m['ordering'] = ', '.join(str(_const(e)) for e in getattr(s.value, 'elts', []) if _const(e))
                        else:
                            m['meta'][key] = _unparse(s.value)
                continue
            if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) \
                    and isinstance(node.value, ast.Call):
                fname = node.targets[0].id
                call = node.value
                ftype = call.func.attr if isinstance(call.func, ast.Attribute) else getattr(call.func, 'id', '')
                f = {'name': fname, 'type': ftype if ftype in KNOWN_FIELDS else 'custom',
                     'raw': _unparse(call), 'verbose': '', 'max_length': None, 'null': False, 'blank': False,
                     'unique': False, 'db_index': False, 'default': '', 'related': '', 'on_delete': 'CASCADE',
                     'related_name': '', 'auto_now': False, 'auto_now_add': False, 'max_digits': None,
                     'decimal_places': None, 'choices': ''}
                if ftype not in KNOWN_FIELDS:
                    notes.append('%s.%s: نوعِ %s شناخته نشد — به‌صورتِ کدِ خام نگه داشته شد.' % (cls.name, fname, ftype or '?'))
                if call.args and isinstance(call.args[0], ast.Constant) and isinstance(call.args[0].value, str):
                    if ftype in ('ForeignKey', 'ManyToManyField', 'OneToOneField'):
                        f['related'] = call.args[0].value
                    else:
                        f['verbose'] = call.args[0].value
                elif call.args and ftype in ('ForeignKey', 'ManyToManyField', 'OneToOneField'):
                    f['related'] = _unparse(call.args[0])
                to = _kw(call, 'to')
                if to is not None:
                    f['related'] = _const(to) if _const(to) else _unparse(to)
                for key in ('verbose_name', 'max_length', 'null', 'blank', 'unique', 'db_index',
                            'related_name', 'auto_now', 'auto_now_add', 'max_digits', 'decimal_places'):
                    v = _kw(call, key)
                    if v is not None:
                        c = _const(v)
                        f[{'verbose_name': 'verbose'}.get(key, key)] = c if c is not None else _unparse(v)
                d = _kw(call, 'default')
                if d is not None:
                    f['default'] = _unparse(d)
                od = _kw(call, 'on_delete')
                if od is not None:
                    f['on_delete'] = od.attr if isinstance(od, ast.Attribute) else _unparse(od)
                ch = _kw(call, 'choices')
                if ch is not None:
                    pairs = []
                    if isinstance(ch, (ast.List, ast.Tuple)):
                        for e in ch.elts:
                            if isinstance(e, (ast.Tuple, ast.List)) and len(e.elts) == 2 and _const(e.elts[0]) is not None:
                                pairs.append('%s=%s' % (_const(e.elts[0]), _const(e.elts[1]) or _unparse(e.elts[1])))
                    f['choices'] = '\n'.join(pairs)
                    if not pairs:
                        f['type'] = 'custom'   # choices از یک متغیر می‌آید؛ بازنویسی‌اش امن نیست
                        notes.append('%s.%s: choices از متغیر می‌آید — به‌صورتِ کدِ خام نگه داشته شد.' % (cls.name, fname))
                m['fields'].append(f)
        fields, fnotes = _last_wins(m['fields'], '%s: فیلد' % cls.name)
        m['fields'] = fields
        notes += fnotes
        models.append(m)
    models, mnotes = _last_wins(models, 'مدل')
    return models, notes + mnotes


def _last_wins(items, what):
    """اگر یک نام دو بار تعریف شده، پایتون دومی را نگه می‌دارد؛ ما هم همین‌طور."""
    seen, notes = {}, []
    for it in items:
        if it['name'] in seen:
            notes.append('%s «%s» دو بار تعریف شده؛ تعریفِ آخر (همان که پایتون اجرا می‌کند) نگه داشته شد.'
                         % (what, it['name']))
            del seen[it['name']]
        seen[it['name']] = it
    return list(seen.values()), notes


# ──────────────────────────────────────────────── urls.py / views.py
def analyze_urls(path):
    src = _read(path)
    if not src:
        return [], []
    try:
        tree = ast.parse(src)
    except SyntaxError as exc:
        return [], ['urls.py قابلِ تجزیه نبود: %s' % exc]
    routes, notes = [], []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, 'id', getattr(node.func, 'attr', '')) in ('path', 're_path', 'url'):
            fn = getattr(node.func, 'id', getattr(node.func, 'attr', ''))
            if len(node.args) < 2:
                continue
            pattern = _const(node.args[0])
            if pattern is None:
                pattern = _unparse(node.args[0])
            view = _unparse(node.args[1])
            name = _const(_kw(node, 'name')) if _kw(node, 'name') is not None else ''
            routes.append({'pattern': str(pattern), 'view': view, 'name': name or '', 'kind': fn,
                           'include': view.startswith('include(')})
            if fn != 'path':
                notes.append('%s(%s): الگوی regex — فقط نمایش داده می‌شود.' % (fn, pattern))
    return routes, notes


def analyze_views(path):
    src = _read(path)
    if not src:
        return [], []
    try:
        tree = ast.parse(src)
    except SyntaxError as exc:
        return [], ['views.py قابلِ تجزیه نبود: %s' % exc]
    out = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and not node.name.startswith('_'):
            out.append({'name': node.name, 'kind': 'function', 'bases': [],
                        'raw': ast.get_source_segment(src, node) or ''})
        elif isinstance(node, ast.ClassDef):
            out.append({'name': node.name, 'kind': 'class', 'bases': _base_names(node),
                        'raw': ast.get_source_segment(src, node) or ''})
    return _last_wins(out, 'ویو')


# ──────────────────────────────────────────────── templates
def find_templates(project_root, template_dirs, app_dirs):
    """همهٔ فایل‌های .html داخلِ پوشه‌های قالب (پروژه و اپ‌ها) ⇒ [(rel_path, label)]."""
    found, seen = [], set()
    candidates = [os.path.join(project_root, d.strip('/')) for d in template_dirs]
    candidates += [os.path.join(project_root, 'templates')]
    candidates += [os.path.join(project_root, a, 'templates') for a in app_dirs]
    for base in candidates:
        if not os.path.isdir(base):
            continue
        for dp, dn, fn in os.walk(base):
            dn[:] = [d for d in dn if d not in SKIP_DIRS]
            for name in fn:
                if not name.endswith(('.html', '.htm', '.txt')):
                    continue
                full = os.path.join(dp, name)
                rel = os.path.relpath(full, project_root).replace('\\', '/')
                if rel in seen or os.path.getsize(full) > 400_000:
                    continue
                seen.add(rel)
                found.append(rel)
    found.sort()
    return found


# ──────────────────────────────────────────────── همه با هم
def analyze_project(root):
    project_root, settings_module = find_manage(root)
    report = {'ok': bool(project_root), 'project_root': project_root, 'settings_module': settings_module,
              'apps': [], 'templates': [], 'warnings': [], 'unsupported': [], 'requirements': False}
    if not project_root:
        report['warnings'].append('manage.py پیدا نشد — این یک پروژهٔ جنگو نیست یا عمیق‌تر از ۳ پوشه است.')
        return report
    st = analyze_settings(project_root, settings_module)
    report.update({'settings': st, 'root_urlconf': st['root_urlconf']})
    report['warnings'] += st['warnings']
    report['requirements'] = os.path.exists(os.path.join(project_root, 'requirements.txt'))
    if not report['requirements']:
        report['warnings'].append('requirements.txt ندارد — وابستگی‌ها را باید دستی نصب کنی.')
    local = _local_apps(project_root, st['installed_apps'])
    if not local:
        report['warnings'].append('هیچ اپِ محلی‌ای از INSTALLED_APPS داخلِ پروژه پیدا نشد.')
    app_dirs = []
    for label, pkg, rel in local:
        app_dirs.append(rel)
        base = os.path.join(project_root, rel)
        models, mnotes = analyze_models(os.path.join(base, 'models.py')) if os.path.exists(os.path.join(base, 'models.py')) else ([], [])
        routes, unotes = analyze_urls(os.path.join(base, 'urls.py'))
        views, vnotes = analyze_views(os.path.join(base, 'views.py'))
        report['apps'].append({'label': label, 'package': pkg, 'dir': rel, 'models': models,
                               'routes': routes, 'views': views})
        report['unsupported'] += ['%s: %s' % (label, n) for n in mnotes + unotes + vnotes]
    # نشانی‌های ریشه
    if st['root_urlconf']:
        rpath = os.path.join(project_root, st['root_urlconf'].replace('.', '/') + '.py')
        routes, notes = analyze_urls(rpath)
        report['root_routes'] = routes
        report['unsupported'] += ['ریشه: %s' % n for n in notes]
    else:
        report['root_routes'] = []
    report['templates'] = find_templates(project_root, st['template_dirs'], app_dirs)
    # apps_dir: اگر همهٔ اپ‌ها زیرِ یک پوشه‌اند (مثلاً apps/)
    parents = {os.path.dirname(rel) for _, _, rel in local}
    report['apps_dir'] = parents.pop() if len(parents) == 1 else ''
    return report
