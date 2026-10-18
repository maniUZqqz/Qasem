"""چهره: هماهنگیِ لب (ویسم‌ها)، حالتِ چهره، پلک‌زدن، ابرو و حرکتِ سرِ هم‌زمان با گفتار.

همه روی shape key های صورت (۱۵ ویسم + ۵۲ واحدِ ARKit) کار می‌کند؛ کاراکترِ دیگر فقط نقشهٔ نام می‌خواهد
(بخشِ face در فایلِ rigs/*.json).
"""
import math

from . import anim
from .util import log

OPEN = {'aa': 0.30, 'O': 0.22, 'E': 0.14, 'I': 0.08, 'U': 0.1}
MOUTH_KEYS = ('mouthSmileLeft', 'mouthSmileRight', 'mouthPressLeft', 'mouthPressRight', 'mouthRollLower')


def _ramp(f, a, b, fade):
    if f < a or f > b:
        return 0.0
    up = min(1.0, (f - a) / fade) if fade > 0 else 1.0
    dn = min(1.0, (b - f) / fade) if fade > 0 else 1.0
    u = min(up, dn)
    return u * u * (3 - 2 * u)


def head_language(ctx, rig, face):
    """هنگامِ حرف‌زدن: سرِ کمی تکان‌خورنده و ابروی بالا روی تکیه‌ها (پیش از realize)."""
    peaks = []
    for a, b in face.get('speaking', []):
        peaks += ctx.energy_peaks(rig.id, a + 4, b - 4, min_gap=int(ctx.fps * 0.7), thresh=0.6)
    for i, f in enumerate(peaks):
        amp = 1.5 + (i % 3) * 0.8
        base = rig.ch['head_off'].value(f - 6)
        rig.key_head(f - 5, offset=base)
        rig.key_head(f, offset=(base[0] + amp, base[1] + (0.6 if i % 2 else -0.6), base[2]))
        rig.key_head(f + 7, offset=base)
    return peaks


def build(ctx, rig, face, peaks):
    fmap = rig.map.get('face') or {}
    vis_map = fmap.get('visemes', {})
    exprs = fmap.get('expressions', {})
    frames = anim.frames_range(ctx.f_start, ctx.f_end)
    vals = {}

    def add(key, f, v):
        if v:
            vals.setdefault(key, {})
            vals[key][f] = vals[key].get(f, 0.0) + v

    # ── ویسم‌ها (هم‌پوشانیِ مثلثی = هم‌آواییِ طبیعی)
    keys = sorted(face.get('visemes', []), key=lambda k: k[0])
    strength = float(ctx.quality.get('lip_strength', 0.85))
    for i, (fk, vis, w) in enumerate(keys):
        prev_f = keys[i - 1][0] if i > 0 else fk - 3
        next_f = keys[i + 1][0] if i + 1 < len(keys) else fk + 3
        prev_f = max(prev_f, fk - 6)
        next_f = min(next_f, fk + 6)
        sk = vis_map.get(vis)
        for f in range(int(math.floor(prev_f)), int(math.ceil(next_f)) + 1):
            if f < fk:
                u = (f - prev_f) / max(1e-3, fk - prev_f)
            else:
                u = 1 - (f - fk) / max(1e-3, next_f - fk)
            u = max(0.0, min(1.0, u))
            u = u * u * (3 - 2 * u)
            if sk and vis != 'sil':
                add(sk, f, w * u * strength)
            if vis in OPEN and fmap.get('jaw_open'):
                add(fmap['jaw_open'], f, OPEN[vis] * w * u * 0.35)
    speaking = face.get('speaking', [])

    def is_speaking(f):
        return any(a <= f <= b for a, b in speaking)

    # ── حالتِ چهره (پایه: «گرم»، مگر خلافش آمده باشد)
    items = list(face.get('expressions', []))
    if not any(e['f0'] <= ctx.f_start + 2 for e in items):
        items.insert(0, {'f0': ctx.f_start, 'f1': ctx.f_end, 'expression': 'warm', 'intensity': 0.7, 'base': True})
    fade = ctx.fps * 0.35
    for e in items:
        shape = exprs.get(e['expression'], {})
        for f in frames:
            r = _ramp(f, e['f0'], e['f1'], 0 if e.get('base') else fade)
            if not r:
                continue
            k = e.get('intensity', 0.7) * r
            for key, v in shape.items():
                damp = 0.55 if (key in MOUTH_KEYS and is_speaking(f)) else 1.0
                if e.get('base') and any(x['f0'] <= f <= x['f1'] for x in items if not x.get('base')):
                    damp *= 0.2
                add(key, f, v * k * damp)
    # ── ابرو روی تکیه‌های گفتار
    for f in peaks:
        for d in range(-4, 9):
            u = _ramp(f + d, f - 4, f + 8, 4)
            add('browInnerUp', f + d, 0.22 * u)
            add('browOuterUpLeft', f + d, 0.12 * u)
            add('browOuterUpRight', f + d, 0.12 * u)
    # ── پلک: فاصلهٔ تصادفی (تکرارپذیر) ۲ تا ۴٫۵ ثانیه + هنگامِ جابه‌جاییِ بزرگِ نگاه
    blinks = []
    seed = ctx.seed(rig.id)
    f = ctx.f_start + int(ctx.fps * (0.6 + (seed % 1.0)))
    i = 0
    while f < ctx.f_end - 4:
        blinks.append(f)
        i += 1
        gap = 2.2 + 2.3 * ((math.sin(seed * 3.7 + i * 2.1) + 1) / 2)
        f += int(ctx.fps * gap)
    for g in ctx.c['gaze'].get(rig.id, []):
        if not any(abs(g['f0'] - b) < ctx.fps * 0.8 for b in blinks):
            blinks.append(g['f0'])
    for bf in blinks:
        for d, v in ((0, 0.0), (1, 0.55), (2, 1.0), (3, 1.0), (4, 0.6), (5, 0.25), (6, 0.0)):
            for bk in fmap.get('blink', []):
                vals.setdefault(bk, {})
                vals[bk][bf + d] = max(vals[bk].get(bf + d, 0.0), v)
    # ── نوشتن روی همهٔ مش‌هایی که این کلیدها را دارند (بدن، مژه، دندان…)
    written = 0
    for mesh in rig.face_meshes:
        kb = mesh.data.shape_keys.key_blocks
        for key, per in vals.items():
            if key not in kb:
                continue
            series = [max(0.0, min(1.0, per.get(f, 0.0))) for f in frames]
            if max(series) <= 0.001:
                continue
            anim.bulk_keys(mesh.data.shape_keys, 'key_blocks["%s"].value' % key, frames, series)
            written += 1
    log('face', rig.id, 'visemes=%d blinks=%d curves=%d' % (len(keys), len(blinks), written))
    return {'visemes': len(keys), 'blinks': len(blinks), 'curves': written}
