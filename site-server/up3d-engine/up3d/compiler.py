"""سندِ صحنه ⇐ برنامهٔ اجرایی (compiled).

خروجی همهٔ زمان‌ها را به فریمِ مطلق تبدیل می‌کند و هر دارایی را با مسیرِ کامل و پارامترهای نهایی می‌آورد،
پس موتورِ اجرا (Blender امروز؛ وب/بازی/Unreal فردا) هیچ تصمیمی نمی‌گیرد و فقط اجرا می‌کند.
"""
from . import COMPILED_FORMAT
from . import lipsync
from . import scene as S
from .assets import Asset

# تنظیمِ دستیِ کیفیت روی یک پروفایل (بخشِ «کیفیت و رندر» ⇐ تنظیماتِ پیشرفتهٔ پنل): فقط همین کلیدها.
QUALITY_LIMITS = {'resolution': (240, 3840), 'samples': (1, 2048), 'frame_step': (1, 4)}
QUALITY_FLAGS = ('denoise', 'motion_blur')


def clean_quality(q):
    """{resolution, samples, frame_step, denoise, motion_blur} ⇐ فقط کلیدهای شناخته‌شده در بازهٔ امن.
    خالی = همان پروفایل. ValueError برای مقدارِ نامعتبر (پیامِ فارسی برای پنل)."""
    out = {}
    if not isinstance(q, dict):
        return out
    for k, (lo, hi) in QUALITY_LIMITS.items():
        v = q.get(k)
        if v in (None, ''):
            continue
        try:
            v = int(float(v))
        except (TypeError, ValueError):
            raise ValueError('«%s» عدد نیست' % k)
        if not lo <= v <= hi:
            raise ValueError('«%s» باید بین %d و %d باشد' % (k, lo, hi))
        out[k] = v
    for k in QUALITY_FLAGS:
        v = q.get(k)
        if v in (None, ''):
            continue
        out[k] = v.strip().lower() in ('1', 'true', 'yes', 'on') if isinstance(v, str) else bool(v)
    return out


def with_overrides(prof, quality=None):
    """پروفایل + تنظیمِ دستی ⇐ پروفایلِ مؤثر (همان نوعِ ورودی: Asset می‌ماند Asset، دیکشنری می‌ماند دیکشنری)."""
    if not quality or not prof:
        return prof
    p = dict(prof)
    if quality.get('resolution'):
        p['resolution'] = {**(p.get('resolution') or {}), 'long': int(quality['resolution'])}
    if quality.get('samples'):
        p['samples'] = int(quality['samples'])
    if quality.get('frame_step'):
        p['frame_step'] = int(quality['frame_step'])
    for k in QUALITY_FLAGS:
        if k in quality:
            p[k] = bool(quality[k])
    return Asset(p) if isinstance(prof, Asset) else p


def quality_scale(prof, quality=None):
    """ضریبِ تقریبیِ زمانِ هر فریم نسبت به پروفایلِ پایه: پیکسل‌ها × نمونه‌ها (فقط Cycles)."""
    if not quality or not prof:
        return 1.0
    eff = with_overrides(prof, quality)
    base_long = float((prof.get('resolution') or {}).get('long') or 640)
    s = (float((eff.get('resolution') or {}).get('long') or base_long) / base_long) ** 2
    if prof.get('engine', 'CYCLES') == 'CYCLES' and prof.get('samples') and eff.get('samples'):
        s *= float(eff['samples']) / float(prof['samples'])
    return max(0.05, s)


def _frame(t, fps):
    return int(round(float(t) * fps)) + 1


def resolution_for(profile, aspect):
    long_side = int((profile or {}).get('resolution', {}).get('long', 640))
    a, b = S.ASPECTS.get(aspect, (9, 16))
    if a >= b:
        w, h = long_side, long_side * b / a
    else:
        w, h = long_side * a / b, long_side
    even = lambda v: max(2, int(round(v / 2.0)) * 2)
    return even(w), even(h)


def _asset_block(asset, params, extra=()):
    out = {k: v for k, v in asset.items() if not k.startswith('_') and k not in ('name', 'description', 'thumbnail')}
    out['folder'] = asset.folder
    out['params'] = params
    for k in extra:
        out[k] = asset.get(k)
    return out


def compile_scene(doc, reg, profile_id=None, audio=None, label_images=None, profile_overrides=None):
    """audio: {speech_id: {'file','offset','duration','visemes':[[t,vis,w]...], 'energy':[...], 'energy_rate'}}
    label_images: {product_id: path_to_png}
    profile_overrides: خروجیِ clean_quality — روی پروفایل می‌نشیند و به compiled می‌رود (موتور فقط اجرا می‌کند)."""
    doc = S.normalize(doc)
    audio = audio or {}
    label_images = label_images or {}
    out = doc['output']
    fps = out['fps']
    dur = out['duration']
    prof = reg.get('render_profile', profile_id or 'preview') or reg.default('render_profile')
    prof = with_overrides(prof, profile_overrides)
    w, h = resolution_for(prof, out['aspect'])
    frame_end = _frame(dur, fps) - 1

    env = reg.get('environment', doc['environment']['id'])
    env_params, _ = reg.resolve_params(env, doc['environment'].get('params'))
    light = reg.get('lighting', doc['lighting'].get('id') or env.get('default_lighting'))
    light_params, _ = reg.resolve_params(light, doc['lighting'].get('params'))

    comp = {
        'format': COMPILED_FORMAT,
        'title': doc['meta'].get('title', ''),
        'fps': fps, 'frame_start': 1, 'frame_end': frame_end, 'duration': dur,
        'aspect': out['aspect'], 'resolution': [w, h],
        'profile': _asset_block(prof, {}),
        'environment': _asset_block(env, env_params, ('marks', 'surfaces')),
        'lighting': _asset_block(light, light_params) if light else None,
        'actors': [], 'products': [], 'actions': [], 'face': {}, 'gaze': {}, 'speech': [], 'shots': [],
    }

    for a in doc['actors']:
        ch = reg.get('character', a['character'])
        params, _ = reg.resolve_params(ch, a.get('params'))
        comp['actors'].append({'id': a['id'], 'mark_id': a['mark'], 'mark': env['marks'][a['mark']],
                               'character': _asset_block(ch, params)})
        comp['face'][a['id']] = {'visemes': [], 'expressions': [], 'speaking': []}
        comp['gaze'][a['id']] = []

    surfaces = list(env['surfaces'])
    for i, p in enumerate(doc['products']):
        pa = reg.get('product', p['asset'])
        params, _ = reg.resolve_params(pa, p.get('params'))
        sid = p.get('surface') if p.get('surface') in env['surfaces'] else surfaces[min(i, len(surfaces) - 1)]
        blk = _asset_block(pa, params, ('dimensions', 'grasp'))
        blk.update({'id': p['id'], 'name': p.get('name', ''), 'surface_id': sid, 'surface': env['surfaces'][sid],
                    'label_image': label_images.get(p['id']) or params.get('label_image')})
        comp['products'].append(blk)

    # حرکت‌ها + نگاهِ خودکارِ هر حرکت
    explicit_gaze = {a['id']: [] for a in doc['actors']}
    for g in doc['gaze']:
        if g.get('actor') in explicit_gaze:
            explicit_gaze[g['actor']].append((g['start'], S.end_of(g)))
    for act in doc['actions']:
        m = reg.get('motion', act['motion'])
        if not m:
            continue
        params, _ = reg.resolve_params(m, act.get('params'))
        f0, f1 = _frame(act['start'], fps), _frame(S.end_of(act), fps)
        comp['actions'].append({
            'id': act['id'], 'actor': act['actor'], 'motion': m.id, 'source': m['source'], 'folder': m.folder,
            'layer': bool(m.get('layer')), 'hands': m.get('hands', {}), 'product_rule': m.get('product', {}),
            't0': act['start'], 't1': S.end_of(act), 'f0': f0, 'f1': max(f1, f0 + 2), 'params': params,
        })
        pid = params.get((m.get('product') or {}).get('param', 'product'))
        for ag in m.get('auto_gaze', []):
            t0 = act['start'] + ag['from'] * act['duration']
            t1 = act['start'] + ag['to'] * act['duration']
            if any(a0 < t1 and t0 < a1 for a0, a1 in explicit_gaze.get(act['actor'], [])):
                continue
            tgt = ag['target']
            if tgt.startswith('$'):
                tgt = params.get(tgt[1:], 'camera')
            if tgt == 'product':
                pid = pid or (doc['products'][0]['id'] if doc['products'] else None)
                if not pid:
                    continue
                tgt = 'product:' + pid
            comp['gaze'][act['actor']].append({'f0': _frame(t0, fps), 'f1': _frame(t1, fps), 'target': tgt, 'auto': True})
        ex = m.get('expression')
        if ex and act['actor'] in comp['face'] and not any(
                e.get('actor') == act['actor'] and e['start'] < S.end_of(act) and act['start'] < S.end_of(e)
                for e in doc['expressions']):
            comp['face'][act['actor']]['expressions'].append({
                'f0': _frame(act['start'] + ex.get('from', 0) * act['duration'], fps),
                'f1': _frame(act['start'] + ex.get('to', 1) * act['duration'], fps),
                'expression': ex['name'], 'intensity': ex.get('intensity', 0.7), 'auto': True})
    for g in doc['gaze']:
        if g.get('actor') in comp['gaze']:
            comp['gaze'][g['actor']].append({'f0': _frame(g['start'], fps), 'f1': _frame(S.end_of(g), fps),
                                             'target': g.get('target', 'camera')})
    for k in comp['gaze']:
        comp['gaze'][k].sort(key=lambda x: x['f0'])

    for e in doc['expressions']:
        if e.get('actor') in comp['face']:
            comp['face'][e['actor']]['expressions'].append({
                'f0': _frame(e['start'], fps), 'f1': _frame(S.end_of(e), fps), 'expression': e.get('expression', 'smile'),
                'intensity': float(e.get('intensity', 0.7))})

    # گفتار ⇐ ویسم‌ها (از صدای واقعی اگر هست؛ وگرنه تخمین از متن برای انیمیک)
    for sp in doc['speech']:
        info = audio.get(sp['id']) or {}
        t0 = sp['start']
        length = info.get('duration') or S.estimate_speech_seconds(sp.get('text', ''))
        vis = info.get('visemes') or lipsync.visemes_from_text(sp.get('text', ''), length)
        energy = info.get('energy') or []
        rate = info.get('energy_rate') or 100.0
        entry = {'id': sp['id'], 'actor': sp.get('actor'), 'text': sp.get('text', ''), 'start': t0,
                 'duration': length, 'f0': _frame(t0, fps), 'f1': _frame(t0 + length, fps),
                 'audio': info.get('file')}
        comp['speech'].append(entry)
        if sp.get('actor') in comp['face']:
            face = comp['face'][sp['actor']]
            face['speaking'].append([entry['f0'], entry['f1']])
            for t, v, wgt in vis:
                face['visemes'].append([round((t0 + t) * fps + 1, 2), v, round(wgt, 3)])
            if energy:
                # پوشِ صدا با نرخِ fps (برای ژستِ هم‌زمان با تکیهٔ کلام)
                step = rate / fps
                env_f = [max(energy[int(i * step):int((i + 1) * step)] or [0]) for i in range(int(len(energy) / step))]
                face.setdefault('energy', []).append({'f0': entry['f0'], 'values': [round(x, 3) for x in env_f]})

    for sh in doc['shots']:
        sa = reg.get('shot', sh['shot'])
        kind = S.subject_kind(doc, sh['subject'])
        params = dict(sa.get('defaults', {}))
        params.update(sh.get('params') or {})
        comp['shots'].append({'id': sh['id'], 'shot': sa.id, 'framing': sa['framing'], 'start': sh['start'],
                              'f0': _frame(sh['start'], fps), 'f1': _frame(S.end_of(sh), fps) - 1,
                              'subject': {'type': kind, 'id': sh['subject']},
                              'move': sh.get('move') or (sa.get('moves') or ['static'])[0], 'params': params})
    if comp['shots']:
        comp['shots'][-1]['f1'] = frame_end
    comp['overlays'] = doc['overlays']
    comp['audio'] = doc['audio']
    return comp
