"""سندِ صحنه — قراردادِ مشترک.

هوشِ مصنوعی، کدِ پایتون (sdk)، ویرایشگرِ گرافیکیِ پنل و API همه همین سند را می‌سازند/ویرایش می‌کنند.
ساختار «تخت» است: هر نوع رویداد یک شیار (track) جدا در خطِ زمان:

  actions     حرکتِ بدن (از کتابخانهٔ حرکت)      speech      گفتار (متن ⇐ TTS ⇐ لب)
  expressions حالتِ چهره                          gaze        نگاه
  shots       دوربین                               overlays    نوشته/CTA/قیمت روی تصویر

زمان‌ها ثانیه‌اند؛ تبدیل به فریم فقط در compiler.

ویرایشگرِ آزاد (پنل ⇐ «ویرایشگرِ صحنه») فیلدهای اختیاریِ زیر را اضافه می‌کند؛ سندِ بی‌آن‌ها همان رفتارِ قبلی را دارد:
  actors[i] / products[i] .transform = {pos:[x,y,z] متر، rot:[درجه XYZ]، scale:[..]}   جای آزاد (به‌جای mark/surface)
  actors[i] / products[i] / props[i] / lights[i] .keys = [{t, pos, rot, scale, ease}]    کلیدهای حرکت
  props    = [{id, asset (شکلِ محصول), name, params, transform, keys}]                     اشیای تزئینیِ صحنه
  lights   = [{id, type: point|spot|area|sun, color, power, size, cone, blend, transform, keys}]
  cameras  = [{id, name, lens, fstop, keys: [{t, pos, target, lens, ease}]}]              دوربینِ آزاد
  shots[i].camera = "<id ِ دوربینِ آزاد>"  ⇐ این شات با کلیدهای همان دوربین (نه نمای آماده)
مختصات مثلِ Blender: متر، Z بالا، بازیگر رو به -Y.
"""
import copy
import re

from . import SCENE_FORMAT
from .keys import EASES

ASPECTS = {'9:16': (9, 16), '16:9': (16, 9), '1:1': (1, 1), '4:5': (4, 5)}
LIGHT_TYPES = ('point', 'spot', 'area', 'sun')
LIGHT_POWER = {'point': 150.0, 'spot': 300.0, 'area': 120.0, 'sun': 3.0}
TRACKS = ('actions', 'speech', 'expressions', 'gaze', 'shots', 'overlays')
TRACK_PREFIX = {'actions': 'a', 'speech': 'd', 'expressions': 'e', 'gaze': 'g', 'shots': 's', 'overlays': 'o'}
EXPRESSIONS = ('neutral', 'smile', 'big_smile', 'surprised', 'thinking', 'confident', 'warm', 'wink')
OVERLAY_TYPES = ('title', 'subtitle', 'cta', 'price', 'badge', 'logo')

# سرعتِ تقریبیِ گفتارِ فارسیِ TTS (نویسه در ثانیه) — برای وارسی پیش از ساختِ صدا
FA_CHARS_PER_SEC = 13.0


def new_scene(title='', duration=12.0, aspect='9:16', fps=24, language='fa'):
    return {
        'format': SCENE_FORMAT,
        'meta': {'title': title, 'language': language, 'source': 'code', 'brief': {}},
        'output': {'aspect': aspect, 'fps': fps, 'duration': float(duration)},
        'environment': {'id': '', 'params': {}},
        'lighting': {'id': '', 'params': {}},
        'actors': [],
        'products': [],
        'actions': [], 'speech': [], 'expressions': [], 'gaze': [], 'shots': [], 'overlays': [],
        'audio': {'music': None, 'music_volume': 0.14, 'subtitles': True, 'voice_volume': 1.0},
    }


def end_of(item):
    return float(item.get('start', 0)) + float(item.get('duration', 0))


def _num(v, default=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _vec(v, default):
    if not isinstance(v, (list, tuple)) or len(v) < 3:
        return list(default)
    return [round(_num(x, d), 4) for x, d in zip(v[:3], default)]


def norm_transform(tr):
    """transform ِ ویرایشگر ⇐ شکلِ کامل و عددی؛ None اگر دیکشنری نیست."""
    if not isinstance(tr, dict):
        return None
    return {'pos': _vec(tr.get('pos'), (0.0, 0.0, 0.0)), 'rot': _vec(tr.get('rot'), (0.0, 0.0, 0.0)),
            'scale': [max(0.001, x) for x in _vec(tr.get('scale'), (1.0, 1.0, 1.0))]}


def norm_keys(keys, channels=('pos', 'rot', 'scale')):
    """کلیدها: مرتب بر حسبِ زمان، یک کلید در هر زمان (آخری برنده)، فقط کانال‌های شناخته، ease ِ مجاز."""
    out = {}
    for k in keys or []:
        if not isinstance(k, dict):
            continue
        t = round(max(0.0, _num(k.get('t'))), 3)
        nk = {'t': t, 'ease': k.get('ease') if k.get('ease') in EASES else 'smooth'}
        for ch in channels:
            if k.get(ch) is None:
                continue
            if ch == 'lens':
                nk[ch] = round(min(300.0, max(8.0, _num(k[ch], 35.0))), 2)
            elif ch == 'scale':
                nk[ch] = [max(0.001, x) for x in _vec(k[ch], (1.0, 1.0, 1.0))]
            else:
                nk[ch] = _vec(k[ch], (0.0, 0.0, 0.0))
        if len(nk) > 2:
            out[t] = nk
    return [out[t] for t in sorted(out)]


def _norm_free(obj, channels=('pos', 'rot', 'scale')):
    if 'transform' in obj:
        tr = norm_transform(obj.get('transform'))
        if tr:
            obj['transform'] = tr
        else:
            obj.pop('transform', None)
    if 'keys' in obj:
        obj['keys'] = norm_keys(obj.get('keys'), channels)
        if not obj['keys']:
            obj.pop('keys')


def _unique_ids(items, prefix, used):
    for i, it in enumerate(items):
        if not it.get('id') or it['id'] in used:
            n = i + 1
            while '%s%d' % (prefix, n) in used:
                n += 1
            it['id'] = '%s%d' % (prefix, n)
        used.add(it['id'])


def has_editor_features(doc):
    """سند از قابلیت‌های ویرایشگرِ آزاد استفاده می‌کند؟ (کارگرِ قدیمی آن‌ها را نمی‌فهمد)"""
    doc = doc or {}
    if doc.get('props') or doc.get('lights') or doc.get('cameras'):
        return True
    for x in (doc.get('actors') or []) + (doc.get('products') or []):
        if x.get('transform') or x.get('keys'):
            return True
    return any(s.get('camera') for s in doc.get('shots') or [])


def estimate_speech_seconds(text):
    clean = re.sub(r'\s+', ' ', text or '').strip()
    pauses = len(re.findall(r'[.!?؟،,;:]', clean)) * 0.25
    return len(clean) / FA_CHARS_PER_SEC + pauses + 0.2


def from_nested_plan(plan):
    """قالبِ تودرتوی «شات ⇐ حرکت‌ها/دیالوگ» (شکلِ نوشته‌شده در ایده) را به سندِ تخت تبدیل می‌کند."""
    if 'shots' not in plan or not plan['shots'] or 'actions' not in plan['shots'][0]:
        return plan
    proj = plan.get('project', {})
    doc = new_scene(duration=proj.get('duration_seconds', 12), aspect=proj.get('aspect_ratio', '9:16'),
                    fps=proj.get('fps', 24))
    ch = (plan.get('character') or {}).get('asset_id')
    if ch:
        doc['actors'].append({'id': 'host', 'character': ch, 'mark': 'center'})
    env = (plan.get('environment') or {}).get('asset_id')
    if env:
        doc['environment']['id'] = env
    pr = plan.get('product') or {}
    if pr.get('asset_id'):
        doc['products'].append({'id': 'p1', 'asset': pr['asset_id'], 'name': pr.get('name', ''),
                                'params': {'label_image': pr.get('label_image')}})
    for s in plan['shots']:
        st, en = _num(s.get('start')), _num(s.get('end'))
        doc['shots'].append({'shot': s.get('camera', 'medium'), 'start': st, 'duration': max(0.5, en - st),
                             'subject': 'host'})
        for a in s.get('actions', []):
            a0, a1 = _num(a.get('start'), st), _num(a.get('end'), en)
            doc['actions'].append({'actor': 'host', 'motion': a.get('motion'), 'start': a0,
                                   'duration': max(0.3, a1 - a0), 'params': a.get('params', {})})
        if s.get('dialogue'):
            doc['speech'].append({'actor': 'host', 'text': s['dialogue'], 'start': st + 0.2})
    return doc


def normalize(doc):
    """تکمیلِ پیش‌فرض‌ها، شناسه‌ها و نوعِ عددها؛ سند را تغییر نمی‌دهد، نسخهٔ تازه برمی‌گرداند."""
    doc = from_nested_plan(copy.deepcopy(doc or {}))
    base = new_scene()
    for k, v in base.items():
        if k not in doc or doc[k] is None:
            doc[k] = copy.deepcopy(v)
    doc['format'] = SCENE_FORMAT
    out = doc['output']
    out['fps'] = int(_num(out.get('fps'), 24)) or 24
    out['duration'] = round(_num(out.get('duration'), 12.0), 3)
    if out.get('aspect') not in ASPECTS:
        out['aspect'] = '9:16'
    for k in ('environment', 'lighting'):
        if isinstance(doc[k], str):
            doc[k] = {'id': doc[k], 'params': {}}
        doc[k].setdefault('params', {})
    for i, a in enumerate(doc['actors']):
        a.setdefault('id', 'actor%d' % (i + 1))
        a.setdefault('mark', 'center')
        a.setdefault('params', {})
        _norm_free(a)
    for i, p in enumerate(doc['products']):
        p.setdefault('id', 'p%d' % (i + 1))
        p.setdefault('params', {})
        p.setdefault('name', '')
        _norm_free(p)
    # ویرایشگرِ آزاد: اشیای تزئینی، نورهای اضافه، دوربین‌های آزاد (فقط اگر در سند هستند)
    used = {x['id'] for x in doc['actors'] + doc['products']}
    if doc.get('props') is not None:
        doc['props'] = [x for x in doc['props'] if isinstance(x, dict) and x.get('asset')]
        _unique_ids(doc['props'], 'prop', used)
        for x in doc['props']:
            x.setdefault('params', {})
            x.setdefault('name', '')
            x['transform'] = norm_transform(x.get('transform')) or norm_transform({})
            _norm_free(x)
    if doc.get('lights') is not None:
        doc['lights'] = [x for x in doc['lights'] if isinstance(x, dict)]
        _unique_ids(doc['lights'], 'light', used)
        for x in doc['lights']:
            if x.get('type') not in LIGHT_TYPES:
                x['type'] = 'point'
            x['color'] = x.get('color') if isinstance(x.get('color'), str) and x['color'].startswith('#') else '#ffffff'
            x['power'] = round(max(0.0, _num(x.get('power'), LIGHT_POWER[x['type']])), 3)
            x['size'] = round(min(20.0, max(0.01, _num(x.get('size'), 0.5))), 3)
            x['cone'] = round(min(175.0, max(1.0, _num(x.get('cone'), 45.0))), 2)
            x['blend'] = round(min(1.0, max(0.0, _num(x.get('blend'), 0.3))), 3)
            x['transform'] = norm_transform(x.get('transform')) or norm_transform({'pos': [0, -1.5, 2.2]})
            _norm_free(x)
    if doc.get('cameras') is not None:
        doc['cameras'] = [x for x in doc['cameras'] if isinstance(x, dict)]
        _unique_ids(doc['cameras'], 'cam', used)
        for x in doc['cameras']:
            x.setdefault('name', '')
            x['lens'] = round(min(300.0, max(8.0, _num(x.get('lens'), 35.0))), 2)
            x['fstop'] = round(min(32.0, max(0.7, _num(x.get('fstop'), 4.0))), 2)
            x['keys'] = norm_keys(x.get('keys'), ('pos', 'target', 'lens'))
    for track in TRACKS:
        items = doc.get(track) or []
        used = set()
        for it in items:
            it['start'] = round(max(0.0, _num(it.get('start'))), 3)
            if 'end' in it and 'duration' not in it:
                it['duration'] = _num(it.pop('end')) - it['start']
            it.pop('end', None)
            if track != 'speech' or 'duration' in it:
                it['duration'] = round(max(0.0, _num(it.get('duration'), 1.0)), 3)
            if track in ('actions', 'shots'):
                it.setdefault('params', {})
            if not it.get('id') or it['id'] in used:
                n = 1
                while '%s%d' % (TRACK_PREFIX[track], n) in used:
                    n += 1
                it['id'] = '%s%d' % (TRACK_PREFIX[track], n)
            used.add(it['id'])
        items.sort(key=lambda x: (x.get('start', 0), x.get('id', '')))
        doc[track] = items
    for sp in doc['speech']:
        if not sp.get('duration'):
            sp['duration'] = round(estimate_speech_seconds(sp.get('text', '')), 2)
    doc['audio'] = {**base['audio'], **(doc.get('audio') or {})}
    return doc


def subject_kind(doc, sid):
    if any(a['id'] == sid for a in doc.get('actors', [])):
        return 'actor'
    if any(p['id'] == sid for p in doc.get('products', [])):
        return 'product'
    return None


def summary(doc):
    """خلاصهٔ یک‌خطی برای فهرست‌ها."""
    o = doc.get('output', {})
    return '%s · %ss · %s · %d حرکت · %d شات · %d جمله' % (
        o.get('aspect'), o.get('duration'), doc.get('environment', {}).get('id', '?'),
        len(doc.get('actions', [])), len(doc.get('shots', [])), len(doc.get('speech', [])))
