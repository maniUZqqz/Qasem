"""بسته‌های دارایی (asset packs) — افزودنِ محیط/صحنه، شخص، حرکت، محصول، نور و نمای دوربین بی‌نوشتنِ کد.

بسته = یک فایلِ zip با یک یا چند پوشه که هر کدام manifest.json دارد. دو چیدمان پذیرفته است:
    my_room/manifest.json  (+ room.glb)                 ⇐ نوع از "kind" ِ manifest
    environments/my_room/manifest.json                  ⇐ نوع از نامِ پوشهٔ بالا (چیدمانِ assets/)
pack.json در ریشهٔ zip (اختیاری): {"id": "my_pack", "name": "…", "description": "…"}

نصب: وارسیِ هر manifest با همین قواعد (+ وجودِ فایل‌ها، پسوندهای مجاز، بی‌مسیرِ خطرناک) ⇐
    data/asset-packs/<pack>/<kind-dir>/<id>/  ⇐ دفترِ دارایی‌ها خودش دوباره خوانده می‌شود (فایلِ .stamp).
روشن/خاموش = "enabled" در pack.json (بستهٔ خاموش در دفتر نمی‌آید)؛ حذف = پاک‌کردنِ پوشه.
"""
import json
import os
import re
import shutil
import time
import uuid
import zipfile

from . import paths
from .assets import KINDS, REQUIRED

KIND_ALIASES = {
    'environment': 'environment', 'environments': 'environment', 'scene': 'environment', 'scenes': 'environment',
    'location': 'environment', 'locations': 'environment', 'room': 'environment',
    'character': 'character', 'characters': 'character', 'person': 'character', 'people': 'character',
    'presenter': 'character', 'presenters': 'character', 'actor': 'character', 'actors': 'character',
    'motion': 'motion', 'motions': 'motion', 'animation': 'motion', 'animations': 'motion', 'clip': 'motion', 'clips': 'motion',
    'product': 'product', 'products': 'product',
    'lighting': 'lighting', 'light': 'lighting', 'lights': 'lighting',
    'shot': 'shot', 'shots': 'shot', 'camera': 'shot', 'cameras': 'shot',
}
UPLOAD_KINDS = ('environment', 'character', 'motion', 'product', 'lighting', 'shot')
ALLOWED_EXT = {'.json', '.png', '.jpg', '.jpeg', '.webp', '.tga', '.tif', '.tiff', '.bmp', '.exr', '.hdr', '.ktx2',
               '.glb', '.gltf', '.bin', '.fbx', '.obj', '.mtl', '.blend', '.bvh', '.mp4', '.txt', '.md'}
MODEL_EXT = {'environment': ('.glb', '.gltf', '.fbx', '.obj', '.blend'), 'character': ('.glb', '.gltf', '.fbx', '.blend'),
             'motion': ('.bvh', '.fbx', '.glb', '.gltf'), 'product': ('.glb', '.gltf', '.fbx', '.obj')}
ENV_BUILDERS = ('studio', 'boutique', 'home', 'model_file', 'blend_file')
PRODUCT_BUILDERS = ('perfume_bottle', 'cream_jar', 'box_package', 'can_drink', 'file')
CLIP_CHANNELS = ('spine', 'neck', 'arms', 'fingers', 'legs', 'root')
CAMERA_MOVES = ('static', 'push_in', 'pull_out', 'orbit_left', 'orbit_right', 'crane_up', 'crane_down', 'handheld',
                'rack_focus', 'slide_left', 'slide_right')
BLENDER_HDRI = ('interior', 'studio', 'city', 'courtyard', 'forest', 'night', 'sunrise', 'sunset')
ID_RE = re.compile(r'^[a-z0-9][a-z0-9_\-]{1,63}$')
MAX_FILES = 4000
MAX_UNPACKED = 3 * 1024 ** 3


class PackError(Exception):
    def __init__(self, message, report=None):
        super().__init__(message)
        self.report = report or {}


def packs_dir():
    d = os.path.join(paths.DATA, 'asset-packs')
    os.makedirs(d, exist_ok=True)
    return d


def touch_stamp():
    p = os.path.join(packs_dir(), '.stamp')
    with open(p, 'w') as fh:
        fh.write(str(time.time()))


def slug(text, fallback='pack'):
    s = re.sub(r'[^a-z0-9_\-]+', '-', (text or '').strip().lower()).strip('-_')
    return (s or fallback)[:60]


def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _vec3(v):
    return isinstance(v, (list, tuple)) and len(v) == 3 and all(_num(x) for x in v)


def _file(folder, rel, kind, errors, what='فایل'):
    if not rel or not isinstance(rel, str):
        errors.append('%s تعیین نشده' % what)
        return None
    if os.path.isabs(rel) or '..' in rel.replace('\\', '/').split('/'):
        errors.append('%s باید نسبی و داخلِ همین پوشه باشد: %s' % (what, rel))
        return None
    ext = os.path.splitext(rel)[1].lower()
    if kind in MODEL_EXT and ext not in MODEL_EXT[kind]:
        errors.append('پسوندِ %s «%s» برای این نوع پذیرفته نیست (مجاز: %s)' % (what, ext, ' '.join(MODEL_EXT[kind])))
    if folder is not None and not os.path.isfile(os.path.join(folder, rel)):
        errors.append('%s «%s» در پوشه نیست' % (what, rel))
        return None
    return rel


def bvh_seconds(path):
    """طولِ کلیپِ BVH از سرآیند (Frames × Frame Time)."""
    try:
        frames = ft = None
        with open(path, encoding='utf-8', errors='replace') as fh:
            for line in fh:
                ls = line.strip()
                if ls.startswith('Frames:'):
                    frames = int(ls.split(':')[1])
                elif ls.startswith('Frame Time:'):
                    ft = float(ls.split(':')[1])
                    break
        if frames and ft:
            return frames * ft
    except (OSError, ValueError):
        pass
    return None


def _duration(v, fallback):
    if _num(v):
        v = {'default': float(v)}
    if not isinstance(v, dict):
        v = {'default': fallback}
    d = float(v.get('default') or fallback)
    out = {'min': float(v.get('min', max(0.4, round(d * 0.5, 2)))), 'default': d,
           'max': float(v.get('max', max(d, round(d * 3, 2))))}
    return out


def validate_manifest(data, kind, folder=None, reg=None, folder_name=None):
    """manifest ِ یک دارایی ⇐ (manifestِ کامل‌شده، خطاها، هشدارها). folder=None یعنی وجودِ فایل‌ها وارسی نشود."""
    errors, warnings = [], []
    if not isinstance(data, dict):
        return None, ['manifest باید یک شیء JSON باشد'], []
    m = dict(data)
    kind = KIND_ALIASES.get(str(m.pop('kind', '') or kind or '').lower(), kind)
    if kind not in UPLOAD_KINDS:
        return None, ['نوعِ دارایی نامعلوم است («kind» یکی از: environment، character، motion، product، lighting، shot)'], []
    aid = str(m.get('id') or folder_name or '').strip()
    if not ID_RE.match(aid):
        errors.append('شناسهٔ «%s» نامعتبر است (فقط حروفِ کوچکِ انگلیسی، عدد، _ و -؛ ۲ تا ۶۴ نویسه)' % aid)
    m['id'] = aid
    nm = m.get('name')
    if isinstance(nm, str):
        m['name'] = {'fa': nm, 'en': nm}
    elif not isinstance(nm, dict) or not (nm.get('fa') or nm.get('en')):
        m['name'] = {'fa': aid, 'en': aid}
        warnings.append('نام (name) ندارد؛ شناسه نامِ نمایشی شد')
    if isinstance(m.get('description'), str):
        m['description'] = {'fa': m['description'], 'en': m['description']}
    m.setdefault('version', 1)
    if not m.get('license'):
        warnings.append('مجوز (license) نیامده — مطمئن شوید اجازهٔ استفادهٔ تجاری دارید')

    if kind == 'environment':
        if not m.get('builder'):
            m['builder'] = 'model_file' if m.get('file') else ''
        if m['builder'] not in ENV_BUILDERS:
            errors.append('builder ِ محیط یکی از: %s (برای فایلِ glb/fbx/obj/blend: model_file)' % '، '.join(ENV_BUILDERS))
        if m['builder'] in ('model_file', 'blend_file'):
            _file(folder, m.get('file'), 'environment', errors, 'فایلِ محیط')
            if m['builder'] == 'blend_file' and not str(m.get('file', '')).lower().endswith('.blend'):
                errors.append('blend_file فقط فایلِ .blend می‌گیرد')
        if _num(m.get('scale')) and m['scale'] <= 0:
            errors.append('scale باید مثبت باشد')
        marks = m.get('marks')
        if not marks:
            m['marks'] = {'center': {'pos': [0, 0, 0], 'facing': 0}}
            warnings.append('جایگاهِ بازیگر (marks) نیامده؛ «center» در مبدأ گذاشته شد')
        elif not isinstance(marks, dict) or not all(isinstance(v, dict) and _vec3(v.get('pos')) for v in marks.values()):
            errors.append('marks باید {"نام": {"pos": [x,y,z], "facing": درجه}} باشد')
        surf = m.get('surfaces')
        if not surf:
            furn = (m.get('furniture') or {}).get('table') or {'center': [0, -0.5, 0], 'radius': 0.34, 'height': 0.86}
            m.setdefault('furniture', {})['table'] = furn
            c, z = furn.get('center', [0, -0.5, 0]), float(furn.get('height', 0.86))
            m['surfaces'] = {'table_center': {'pos': [c[0], c[1] + 0.14, z], 'yaw': 0},
                             'table_right': {'pos': [c[0] - 0.15, c[1] + 0.2, z], 'yaw': 0},
                             'table_left': {'pos': [c[0] + 0.15, c[1] + 0.2, z], 'yaw': 0}}
            m.setdefault('add_table', True)
            warnings.append('سطحِ محصول (surfaces) نیامده؛ یک میزِ گرد جلوی جایگاه و سه سطح روی آن اضافه شد')
        elif not isinstance(surf, dict) or not all(isinstance(v, dict) and _vec3(v.get('pos')) for v in surf.values()):
            errors.append('surfaces باید {"نام": {"pos": [x,y,z], "yaw": درجه}} باشد')
        dl = m.get('default_lighting')
        if dl and reg is not None and not reg.get('lighting', dl):
            warnings.append('نورِ پیش‌فرضِ «%s» در کتابخانه نیست؛ soft_beauty به کار می‌رود' % dl)
            m['default_lighting'] = 'soft_beauty'
        m.setdefault('default_lighting', 'soft_beauty')

    elif kind == 'character':
        prov = m.setdefault('provider', 'file' if (m.get('file') or m.get('path')) else 'mpfb')
        if prov == 'file':
            rel = m.get('path') or m.get('file')
            if _file(folder, rel, 'character', errors, 'فایلِ کاراکتر'):
                m['path'] = rel
            rm = m.get('rigmap', 'auto')
            if isinstance(rm, str):
                known = {'auto', 'mpfb_default', 'mixamo'}
                if rm not in known and not (folder and os.path.isfile(os.path.join(folder, rm + '.json'))):
                    errors.append('rigmap «%s» شناخته نیست (auto، mixamo، mpfb_default یا فایلِ <نام>.json کنارِ manifest)' % rm)
            elif isinstance(rm, dict):
                roles = rm.get('roles', rm)
                miss = [k for k in ('hips', 'spine', 'head', 'arm.R', 'arm.L', 'leg.R', 'leg.L') if k not in roles]
                if miss:
                    errors.append('rigmap ِ درونِ manifest این نقش‌ها را ندارد: ' + '، '.join(miss))
            else:
                errors.append('rigmap باید نام یا دیکشنری باشد')
            m['rigmap'] = rm
            if m.get('height_m') is not None and not (_num(m['height_m']) and 0.4 < m['height_m'] < 2.6):
                errors.append('height_m باید قدِ آدم به متر باشد (مثلاً 1.72)')
        elif prov == 'mpfb':
            base = None
            if reg is not None:
                same = [c for c in reg.list('character') if c.get('provider') == 'mpfb' and c.get('gender') == m.get('gender')]
                base = same[0] if same else reg.default('character')
            for k in ('macro', 'skin', 'rig', 'rigmap', 'eyebrows', 'eyelashes', 'hair', 'hair_color', 'eye_color', 'clothes'):
                if k not in m and base is not None and k in base:
                    m[k] = base[k]
            if not isinstance(m.get('macro'), dict):
                errors.append('شخصِ MPFB به «macro» (gender، age، weight، height، …) نیاز دارد')
            elif not all(_num(v) or isinstance(v, dict) for v in m['macro'].values()):
                errors.append('مقدارهای macro باید عدد (۰ تا ۱) باشند')
        else:
            errors.append('provider ِ کاراکتر یکی از: file (glb/fbx/blend) یا mpfb (دستورِ ساخت)')
        if m.get('gender') not in ('female', 'male'):
            warnings.append('gender (female/male) نیامده؛ برای انتخابِ صدا و کارگردانِ AI مفید است')
            m.setdefault('gender', 'female')

    elif kind == 'motion':
        src = m.get('source')
        if isinstance(src, str):
            src = {'type': 'clip', 'file': src}
        if not isinstance(src, dict):
            src = {'type': 'clip', 'file': m.get('file')} if m.get('file') else None
        if not src:
            errors.append('حرکت به «source» نیاز دارد: {"type": "clip", "file": "x.bvh"}')
            src = {}
        src.setdefault('type', 'clip')
        if src['type'] == 'clip':
            rel = _file(folder, src.get('file'), 'motion', errors, 'فایلِ کلیپ')
            rig = src.get('rig', 'auto')
            if isinstance(rig, str) and rig not in ('auto', 'mpfb_default', 'mixamo', 'cmu') and not (
                    folder and os.path.isfile(os.path.join(folder, rig + '.json'))):
                errors.append('rig ِ کلیپ «%s» شناخته نیست (auto، mixamo، cmu، mpfb_default)' % rig)
            src['rig'] = rig
            ch = src.get('channels') or ['spine', 'neck', 'arms', 'fingers']
            bad = [c for c in ch if c not in CLIP_CHANNELS]
            if bad:
                errors.append('channels ِ ناشناخته: %s (مجاز: %s)' % ('، '.join(bad), '، '.join(CLIP_CHANNELS)))
            src['channels'] = [c for c in ch if c in CLIP_CHANNELS]
            if isinstance(src.get('bone_map'), dict) is False and 'bone_map' in src:
                errors.append('bone_map باید {"نامِ استخوانِ فایل": "نقش"} باشد')
            secs = None
            if rel and folder and rel.lower().endswith('.bvh'):
                secs = bvh_seconds(os.path.join(folder, rel))
            if 'duration' not in m:
                if secs is None:
                    warnings.append('مدتِ کلیپ معلوم نیست (duration)؛ ۳ ثانیه فرض شد')
                m['duration'] = _duration(None, round(secs, 2) if secs else 3.0)
        elif src['type'] == 'procedural':
            if src.get('fn') not in ('idle', 'talk', 'wave_hello', 'nod', 'look_at', 'pick_up', 'present', 'rotate_show',
                                     'put_down', 'spray', 'point_at', 'thumbs_up', 'hand_on_chest', 'open_arms'):
                errors.append('حرکتِ رویه‌ای فقط با تابعِ موجود در موتور (source.fn) — برای حرکتِ تازه فایلِ BVH/FBX بدهید')
        else:
            errors.append('source.type یکی از clip یا procedural')
        m['source'] = src
        m['duration'] = _duration(m.get('duration'), 3.0)
        d = m['duration']
        if not (0 < d['min'] <= d['default'] <= d['max'] <= 60):
            errors.append('duration باید 0 < min ≤ default ≤ max ≤ 60 ثانیه باشد')
        m.setdefault('category', 'gesture')
        m.setdefault('hands', {'uses': 'none'})
        m.setdefault('pose', {'start': 'stand', 'end': 'stand'})

    elif kind == 'product':
        if not m.get('builder'):
            m['builder'] = 'file' if m.get('file') else ''
        if m['builder'] not in PRODUCT_BUILDERS:
            errors.append('builder ِ محصول یکی از: %s' % '، '.join(PRODUCT_BUILDERS))
        if m['builder'] == 'file':
            _file(folder, m.get('file'), 'product', errors, 'فایلِ مدلِ محصول')
        dims = m.get('dimensions')
        if not (_vec3(dims) and all(x > 0 for x in dims)):
            errors.append('dimensions = [عرض، عمق، ارتفاع] به متر لازم است (مثلاً [0.07, 0.07, 0.15])')
            dims = [0.08, 0.08, 0.15]
        g = m.get('grasp')
        if not isinstance(g, dict):
            m['grasp'] = {'height': 0.4, 'radius': round(max(dims[0], dims[1]) / 2, 4), 'azimuth': 35, 'tilt': 8,
                          'preset': 'grip', 'curl': 1.0}
            warnings.append('نقطهٔ گرفتن (grasp) نیامده؛ از روی ابعاد ساخته شد')

    elif kind == 'lighting':
        rig = m.get('rig')
        if rig is None:
            m['rig'] = rig = []
        if not isinstance(rig, list) or not all(isinstance(x, dict) for x in rig):
            errors.append('rig ِ نور باید فهرستی از نورها باشد: [{"type": "AREA", "azimuth": -50, "power": 140, …}]')
        else:
            for i, light in enumerate(rig):
                if light.get('type', 'AREA') not in ('AREA', 'SPOT', 'POINT', 'SUN'):
                    errors.append('نورِ %d: type یکی از AREA، SPOT، POINT، SUN' % (i + 1))
                for k in ('azimuth', 'elevation', 'distance', 'power', 'size', 'kelvin'):
                    if k in light and not _num(light[k]):
                        errors.append('نورِ %d: «%s» باید عدد باشد' % (i + 1, k))
        world = m.get('world') or {}
        hdri = world.get('hdri')
        if hdri and hdri not in BLENDER_HDRI:
            _file(folder, hdri, 'lighting', errors, 'فایلِ HDRI')
        if not rig and not hdri:
            errors.append('نور باید دست‌کم یک نور (rig) یا یک HDRI (world.hdri) داشته باشد')

    elif kind == 'shot':
        fr = m.get('framing')
        if not isinstance(fr, dict) or not (_num(fr.get('height')) and fr['height'] > 0) or not (_num(fr.get('lens', 50)) and fr.get('lens', 50) > 0):
            errors.append('framing لازم است: {"height": ارتفاعِ قاب به متر، "lens": میلی‌متر، "anchor": "eyes|chest|waist|full|product"}')
        m.setdefault('subject', 'actor')
        if m['subject'] not in ('actor', 'product'):
            errors.append('subject یکی از actor یا product')
        moves = m.get('moves') or ['static']
        bad = [x for x in moves if x not in CAMERA_MOVES]
        if bad:
            errors.append('حرکتِ دوربینِ ناشناخته: ' + '، '.join(bad))
        m['moves'] = [x for x in moves if x in CAMERA_MOVES] or ['static']

    for f in REQUIRED.get(kind, ()):
        if f not in m:
            errors.append('فیلدِ لازم نیست: %s' % f)
    if reg is not None and aid and reg.get(kind, aid) is not None and not errors:
        warnings.append('شناسهٔ «%s» در کتابخانه هست؛ این بسته جایگزینش می‌شود' % aid)
    return m, errors, warnings


# ───────────────────────── zip

def _safe_members(zf):
    errors = []
    total = 0
    names = []
    for info in zf.infolist():
        n = info.filename.replace('\\', '/')
        if n.endswith('/'):
            continue
        parts = n.split('/')
        if n.startswith('/') or '..' in parts or (len(parts[0]) == 2 and parts[0][1] == ':'):
            errors.append('مسیرِ خطرناک در zip: %s' % n)
            continue
        if parts[-1].startswith('.') or '__MACOSX' in parts:
            continue
        ext = os.path.splitext(n)[1].lower()
        if ext not in ALLOWED_EXT:
            errors.append('نوعِ فایل پذیرفته نیست: %s' % n)
            continue
        total += info.file_size
        names.append((info, n))
    if len(names) > MAX_FILES:
        errors.append('تعدادِ فایل‌ها زیاد است (%d > %d)' % (len(names), MAX_FILES))
    if total > MAX_UNPACKED:
        errors.append('حجمِ بازشده بیش از %d گیگابایت است' % (MAX_UNPACKED // 1024 ** 3))
    return names, total, errors


def _find_assets(root):
    """پوشه‌هایی که manifest.json دارند ⇐ [(kind_hint, folder, rel)]"""
    found = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith('.') and d != '__MACOSX']
        if 'manifest.json' in filenames:
            rel = os.path.relpath(dirpath, root).replace('\\', '/')
            parent = os.path.basename(os.path.dirname(dirpath)) if rel != '.' else ''
            found.append((KIND_ALIASES.get(parent.lower()), dirpath, rel))
            dirnames[:] = []            # پوشهٔ دارایی زیرپوشهٔ دارایی ندارد
    return found


def install_zip(zip_path, pack_id=None, name=None, replace=False, dry_run=False, reg=None, source_name=None):
    """نصبِ بسته از zip. خروجی: گزارش {ok, pack, name, assets:[{kind,id,label,warnings}], errors, warnings}.
    خطا ⇐ PackError با همان گزارش (هیچ چیز نصب نمی‌شود)."""
    report = {'ok': False, 'pack': None, 'name': None, 'assets': [], 'errors': [], 'warnings': [], 'dry_run': dry_run}
    if not zipfile.is_zipfile(zip_path):
        report['errors'].append('فایل zip نیست')
        raise PackError('فایل zip نیست', report)
    base = packs_dir()
    tmp = os.path.join(base, '.tmp-%s' % uuid.uuid4().hex[:10])
    try:
        with zipfile.ZipFile(zip_path) as zf:
            members, total, errs = _safe_members(zf)
            report['errors'] += errs
            if errs:
                raise PackError(errs[0], report)
            os.makedirs(tmp)
            for info, n in members:
                dest = os.path.join(tmp, *n.split('/'))
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                with zf.open(info) as src, open(dest, 'wb') as out:
                    shutil.copyfileobj(src, out, 1024 * 1024)
        meta = {}
        for cand in (os.path.join(tmp, 'pack.json'),):
            if os.path.isfile(cand):
                try:
                    with open(cand, encoding='utf-8') as fh:
                        meta = json.load(fh) or {}
                except ValueError as e:
                    report['errors'].append('pack.json خراب است: %s' % e)
        found = _find_assets(tmp)
        if not found:
            report['errors'].append('هیچ پوشه‌ای با manifest.json در zip نیست')
        seen = set()
        staged = []
        for hint, folder, rel in found:
            try:
                with open(os.path.join(folder, 'manifest.json'), encoding='utf-8-sig') as fh:
                    data = json.load(fh)
            except ValueError as e:
                report['errors'].append('%s/manifest.json: JSON ِ نامعتبر (%s)' % (rel, e))
                continue
            kind = KIND_ALIASES.get(str(data.get('kind', '')).lower()) if isinstance(data, dict) else None
            kind = kind or hint
            m, errs, warns = validate_manifest(data, kind, folder, reg, os.path.basename(folder) if rel != '.' else None)
            label = (m or {}).get('name', {}).get('fa') if m else rel
            if m and (kind, m['id']) in seen:
                errs.append('شناسهٔ تکراری در همین بسته: %s' % m['id'])
            if m:
                seen.add((KIND_ALIASES.get(kind, kind), m['id']))
            report['assets'].append({'kind': KIND_ALIASES.get(kind, kind), 'id': (m or {}).get('id'), 'label': label,
                                     'folder': rel, 'errors': errs, 'warnings': warns})
            report['errors'] += ['%s: %s' % (rel, e) for e in errs]
            if m and not errs:
                staged.append((KIND_ALIASES.get(kind, kind), m, folder))
        pid = slug(pack_id or meta.get('id') or os.path.splitext(source_name or os.path.basename(zip_path))[0])
        report['pack'] = pid
        report['name'] = name or meta.get('name') or pid
        dest = os.path.join(base, pid)
        if os.path.exists(dest) and not replace:
            report['errors'].append('بسته‌ای با شناسهٔ «%s» نصب است (برای جایگزینی گزینهٔ «جایگزین کن» را بزنید)' % pid)
        if report['errors']:
            raise PackError(report['errors'][0], report)
        if dry_run:
            report['ok'] = True
            return report
        # چیدمانِ نهایی: <pack>/<kind-dir>/<id>/ + manifest ِ کامل‌شده
        build = os.path.join(base, '.build-%s' % uuid.uuid4().hex[:10])
        os.makedirs(build)
        size = 0
        for kind, m, folder in staged:
            d = os.path.join(build, KINDS[kind], m['id'])
            shutil.copytree(folder, d)
            with open(os.path.join(d, 'manifest.json'), 'w', encoding='utf-8') as fh:
                json.dump(m, fh, ensure_ascii=False, indent=1)
        for dp, _, fns in os.walk(build):
            size += sum(os.path.getsize(os.path.join(dp, f)) for f in fns)
        info = {'id': pid, 'name': report['name'], 'description': meta.get('description', ''), 'enabled': True,
                'installed': time.strftime('%Y-%m-%d %H:%M:%S'), 'source': source_name or os.path.basename(zip_path),
                'size': size, 'assets': [{'kind': k, 'id': m['id'], 'name': m.get('name')} for k, m, _ in staged]}
        with open(os.path.join(build, 'pack.json'), 'w', encoding='utf-8') as fh:
            json.dump(info, fh, ensure_ascii=False, indent=1)
        if os.path.exists(dest):
            old = dest + '.old-%s' % uuid.uuid4().hex[:6]
            os.rename(dest, old)
            os.rename(build, dest)
            shutil.rmtree(old, ignore_errors=True)
        else:
            os.rename(build, dest)
        touch_stamp()
        report['ok'] = True
        report['size'] = size
        return report
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ───────────────────────── فهرست / روشن-خاموش / حذف

def _pack_path(pack_id):
    if not pack_id or not ID_RE.match(pack_id) and not re.match(r'^[a-z0-9][a-z0-9_\-]{0,63}$', pack_id):
        raise PackError('شناسهٔ بسته نامعتبر است')
    p = os.path.join(packs_dir(), pack_id)
    if not os.path.isdir(p):
        raise PackError('بستهٔ «%s» نیست' % pack_id)
    return p


def read_info(path):
    info = {}
    pj = os.path.join(path, 'pack.json')
    if os.path.isfile(pj):
        try:
            with open(pj, encoding='utf-8') as fh:
                info = json.load(fh) or {}
        except ValueError:
            info = {}
    info.setdefault('id', os.path.basename(path))
    info.setdefault('name', info['id'])
    info.setdefault('enabled', True)
    if 'assets' not in info:
        assets = []
        for kind, sub in KINDS.items():
            d = os.path.join(path, sub)
            if os.path.isdir(d):
                assets += [{'kind': kind, 'id': n} for n in sorted(os.listdir(d))
                           if os.path.isfile(os.path.join(d, n, 'manifest.json'))]
        info['assets'] = assets
    return info


def list_packs(reg=None):
    out = []
    base = packs_dir()
    for n in sorted(os.listdir(base)):
        p = os.path.join(base, n)
        if n.startswith('.') or not os.path.isdir(p):
            continue
        info = read_info(p)
        if reg is not None:
            info['problems'] = [x for x in reg.problems if os.path.normpath(x.get('file', '')).startswith(os.path.normpath(p) + os.sep)]
            for a in info['assets']:
                cur = reg.get(a['kind'], a['id'])
                a['active'] = bool(cur is not None and os.path.normpath(cur.get('_root', '')) == os.path.normpath(p))
        out.append(info)
    return out


def set_enabled(pack_id, enabled):
    p = _pack_path(pack_id)
    info = read_info(p)
    info['enabled'] = bool(enabled)
    with open(os.path.join(p, 'pack.json'), 'w', encoding='utf-8') as fh:
        json.dump(info, fh, ensure_ascii=False, indent=1)
    touch_stamp()
    return info


def delete(pack_id):
    p = _pack_path(pack_id)
    trash = os.path.join(packs_dir(), '.deleted-%s-%s' % (pack_id, uuid.uuid4().hex[:6]))
    os.rename(p, trash)
    shutil.rmtree(trash, ignore_errors=True)
    touch_stamp()
    return True
