"""سندِ صحنه — قراردادِ مشترک.

هوشِ مصنوعی، کدِ پایتون (sdk)، ویرایشگرِ گرافیکیِ پنل و API همه همین سند را می‌سازند/ویرایش می‌کنند.
ساختار «تخت» است: هر نوع رویداد یک شیار (track) جدا در خطِ زمان:

  actions     حرکتِ بدن (از کتابخانهٔ حرکت)      speech      گفتار (متن ⇐ TTS ⇐ لب)
  expressions حالتِ چهره                          gaze        نگاه
  shots       دوربین                               overlays    نوشته/CTA/قیمت روی تصویر

زمان‌ها ثانیه‌اند؛ تبدیل به فریم فقط در compiler.
"""
import copy
import re

from . import SCENE_FORMAT

ASPECTS = {'9:16': (9, 16), '16:9': (16, 9), '1:1': (1, 1), '4:5': (4, 5)}
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
    for i, p in enumerate(doc['products']):
        p.setdefault('id', 'p%d' % (i + 1))
        p.setdefault('params', {})
        p.setdefault('name', '')
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
