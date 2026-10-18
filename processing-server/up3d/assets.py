"""دفترِ دارایی‌ها.

هر دارایی یک پوشه است: assets/<kind-dir>/<id>/manifest.json (+ تصویرِ بندانگشتی و فایل‌ها).
بستهٔ دارایی (asset pack) همین ساختار را دارد و با UP3D_ASSETS یا data/asset-packs/ اضافه می‌شود؛
اگر شناسه تکراری باشد، بستهٔ بعدی برنده است (ارتقا بی‌تغییرِ کد).
"""
import json
import os

from . import paths

KINDS = {
    'character': 'characters',
    'motion': 'motions',
    'environment': 'environments',
    'product': 'products',
    'lighting': 'lighting',
    'shot': 'shots',
    'render_profile': 'render_profiles',
    'voice': 'voices',
    'overlay_style': 'overlay_styles',
    'music': 'music',
    'template': 'templates',
}

REQUIRED = {
    'character': ('provider',),
    'motion': ('source', 'duration'),
    'environment': ('builder', 'marks', 'surfaces'),
    'product': ('builder', 'dimensions', 'grasp'),
    'lighting': ('rig',),
    'shot': ('framing',),
    'render_profile': ('engine', 'resolution'),
    'voice': ('provider',),
}


class Asset(dict):
    """دیکشنریِ manifest + مسیرِ پوشه."""

    @property
    def id(self):
        return self['id']

    @property
    def kind(self):
        return self['kind']

    @property
    def folder(self):
        return self.get('_folder', '')

    def path(self, rel):
        if not rel:
            return None
        return rel if os.path.isabs(rel) else os.path.normpath(os.path.join(self.folder, rel))

    def label(self, lang='fa'):
        n = self.get('name') or {}
        return n.get(lang) or n.get('en') or self.id

    def public(self, lang='fa'):
        out = {k: v for k, v in self.items() if not k.startswith('_')}
        out['label'] = self.label(lang)
        thumb = self.get('thumbnail') or 'thumbnail.jpg'
        out['has_thumbnail'] = os.path.isfile(self.path(thumb))
        out['has_preview'] = os.path.isfile(self.path('preview.mp4'))
        return out


class Registry:
    def __init__(self, roots=None):
        self.roots = roots if roots is not None else paths.asset_roots()
        self.items = {k: {} for k in KINDS}
        self.problems = []
        self.reload()

    def reload(self):
        self.items = {k: {} for k in KINDS}
        self.problems = []
        for root in self.roots:
            for kind, sub in KINDS.items():
                d = os.path.join(root, sub)
                if not os.path.isdir(d):
                    continue
                for name in sorted(os.listdir(d)):
                    mf = os.path.join(d, name, 'manifest.json')
                    if not os.path.isfile(mf):
                        continue
                    try:
                        with open(mf, encoding='utf-8') as fh:
                            data = json.load(fh)
                    except Exception as e:  # manifest خراب نباید کلِ دفتر را بخواباند
                        self.problems.append({'file': mf, 'error': str(e)})
                        continue
                    data.setdefault('id', name)
                    data['kind'] = kind
                    data['_folder'] = os.path.dirname(mf)
                    data['_root'] = root
                    miss = [f for f in REQUIRED.get(kind, ()) if f not in data]
                    if miss:
                        self.problems.append({'file': mf, 'error': 'فیلدِ لازم نیست: ' + ', '.join(miss)})
                        continue
                    self.items[kind][data['id']] = Asset(data)
        return self

    # ── پرس‌وجو
    def get(self, kind, asset_id):
        return self.items.get(kind, {}).get(asset_id)

    def has(self, kind, asset_id):
        return asset_id in self.items.get(kind, {})

    def list(self, kind, tag=None):
        vals = list(self.items.get(kind, {}).values())
        if tag:
            vals = [a for a in vals if tag in a.get('tags', [])]
        return sorted(vals, key=lambda a: (a.get('order', 100), a.id))

    def ids(self, kind):
        return [a.id for a in self.list(kind)]

    def counts(self):
        return {k: len(v) for k, v in self.items.items()}

    def default(self, kind):
        lst = self.list(kind)
        for a in lst:
            if a.get('default'):
                return a
        return lst[0] if lst else None

    # ── پارامترها
    @staticmethod
    def resolve_params(asset, given=None):
        """پیش‌فرض‌ها + وارسیِ نوع/بازه/فهرست. خروجی: (params, issues)."""
        spec = (asset or {}).get('params', {}) or {}
        given = dict(given or {})
        out, issues = {}, []
        for key, s in spec.items():
            if key in given:
                v = given.pop(key)
            elif 'default' in s:
                v = s['default']
            else:
                if s.get('required'):
                    issues.append('پارامترِ «%s» لازم است' % key)
                continue
            t = s.get('type', 'any')
            try:
                if t == 'number' and v is not None:
                    v = float(v)
                    if 'min' in s and v < s['min']:
                        issues.append('«%s» کمتر از %s است؛ به کمینه برگشت' % (key, s['min']))
                        v = s['min']
                    if 'max' in s and v > s['max']:
                        issues.append('«%s» بیشتر از %s است؛ به بیشینه برگشت' % (key, s['max']))
                        v = s['max']
                elif t == 'int' and v is not None:
                    v = int(v)
                elif t == 'bool':
                    v = bool(v)
                elif t == 'enum' and v not in s.get('values', []):
                    issues.append('«%s»=%r مجاز نیست (مجاز: %s)' % (key, v, ', '.join(map(str, s.get('values', [])))))
                    v = s.get('default', (s.get('values') or [None])[0])
                elif t == 'color' and isinstance(v, str) and not (v.startswith('#') and len(v) in (4, 7)):
                    issues.append('رنگِ «%s» باید ‎#rrggbb‎ باشد' % key)
                    v = s.get('default')
            except (TypeError, ValueError):
                issues.append('نوعِ «%s» نادرست است' % key)
                v = s.get('default')
            out[key] = v
        out.update(given)   # پارامترهای اضافه دست‌نخورده می‌مانند (برای فراهم‌کننده‌های تازه)
        return out, issues

    # ── برای کارگردانِ AI
    def catalog_for_ai(self, lang='fa'):
        """فهرستِ فشرده و خوانا برای پرامپتِ مدلِ زبانی."""
        lines = []

        def row(a, extra=''):
            desc = (a.get('description') or {}).get('en') or (a.get('description') or {}).get(lang) or ''
            return '- %s: %s%s' % (a.id, desc[:160], extra)

        lines.append('## characters')
        for a in self.list('character'):
            lines.append(row(a, ' [gender=%s]' % a.get('gender', '?')))
        lines.append('## environments (surfaces = where products can stand)')
        for a in self.list('environment'):
            lines.append(row(a, ' [marks=%s; surfaces=%s]' % (','.join(a['marks']), ','.join(a['surfaces']))))
        lines.append('## products (builder shapes)')
        for a in self.list('product'):
            lines.append(row(a))
        lines.append('## lighting')
        for a in self.list('lighting'):
            lines.append(row(a))
        lines.append('## shots (camera framings)')
        for a in self.list('shot'):
            lines.append(row(a, ' [subject=%s]' % a.get('subject', 'actor')))
        lines.append('## motions (duration seconds min/default/max; requires -> effect)')
        for a in self.list('motion'):
            d = a['duration']
            req = (a.get('product') or {}).get('requires', '-')
            eff = (a.get('product') or {}).get('effect', '-')
            layer = ' LAYER(can overlap body motions)' if a.get('layer') else ''
            lines.append(row(a, ' [%.1f/%.1f/%.1f; product %s -> %s; hands=%s]%s' % (
                d['min'], d['default'], d['max'], req, eff, (a.get('hands') or {}).get('uses', '-'), layer)))
        lines.append('## voices')
        for a in self.list('voice'):
            lines.append(row(a, ' [gender=%s]' % a.get('gender', '?')))
        return '\n'.join(lines)

    def public(self, kind=None, lang='fa'):
        kinds = [kind] if kind else list(KINDS)
        return {k: [a.public(lang) for a in self.list(k)] for k in kinds}


_REGISTRY = None


def registry(reload=False):
    global _REGISTRY
    if _REGISTRY is None or reload:
        _REGISTRY = Registry()
    return _REGISTRY
