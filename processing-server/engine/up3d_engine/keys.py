"""کلیدهای ویرایشگرِ آزاد داخلِ Blender: نمونه‌برداری در هر فریم + نوشتنِ کلید روی شیء.

ریاضی عیناً همان up3d/keys.py و پیش‌نمایشِ مرورگر (scene/anim.ts) است — کلیدهای compiled فریمِ مطلق (f) دارند.
هر فریم کلید می‌خورد (LINEAR) تا منحنیِ Blender همان چیزی باشد که در ویرایشگر دیده شد.
"""
import math

from mathutils import Euler, Matrix, Vector

from . import anim

EASES = ('smooth', 'linear', 'ease_in', 'ease_out', 'step', 'auto')


def ease(kind, u):
    u = 0.0 if u < 0.0 else (1.0 if u > 1.0 else u)
    if kind in ('linear', 'auto'):
        return u
    if kind == 'ease_in':
        return u * u * u
    if kind == 'ease_out':
        return 1.0 - (1.0 - u) ** 3
    if kind == 'step':
        return 0.0
    return 4.0 * u * u * u if u < 0.5 else 1.0 - ((-2.0 * u + 2.0) ** 3) / 2.0


def _lerp(a, b, w):
    if isinstance(a, (list, tuple)):
        return [x + (y - x) * w for x, y in zip(a, b)]
    return a + (b - a) * w


def _catmull(p0, p1, p2, p3, u):
    u2, u3 = u * u, u * u * u

    def one(a, b, c, d):
        return 0.5 * (2 * b + (-a + c) * u + (2 * a - 5 * b + 4 * c - d) * u2 + (-a + 3 * b - 3 * c + d) * u3)
    if isinstance(p1, (list, tuple)):
        return [one(a, b, c, d) for a, b, c, d in zip(p0, p1, p2, p3)]
    return one(p0, p1, p2, p3)


def sample(keys, f, channel, default=None):
    ks = [k for k in keys or () if k.get(channel) is not None]
    if not ks:
        return default
    if f <= ks[0]['f']:
        return ks[0][channel]
    if f >= ks[-1]['f']:
        return ks[-1][channel]
    i = 0
    while i + 1 < len(ks) - 1 and ks[i + 1]['f'] <= f:
        i += 1
    a, b = ks[i], ks[i + 1]
    u = (f - a['f']) / (float(b['f'] - a['f']) or 1e-9)
    kind = a.get('ease') or 'smooth'
    if kind == 'auto':
        p0 = ks[i - 1][channel] if i > 0 else a[channel]
        p3 = ks[i + 2][channel] if i + 2 < len(ks) else b[channel]
        return _catmull(p0, a[channel], b[channel], p3, u)
    return _lerp(a[channel], b[channel], ease(kind, u))


def has_channel(keys, channel):
    return any(k.get(channel) is not None for k in keys or ())


def transform(base, keys, f):
    """(pos, rot_deg, scale) در فریم f — کانالِ بی‌کلید از base."""
    base = base or {}
    pos = sample(keys, f, 'pos', base.get('pos') or [0.0, 0.0, 0.0])
    rot = sample(keys, f, 'rot', base.get('rot') or [0.0, 0.0, 0.0])
    scl = sample(keys, f, 'scale', base.get('scale') or [1.0, 1.0, 1.0])
    return pos, rot, scl


def matrix(pos, rot_deg, scale=(1.0, 1.0, 1.0)):
    q = Euler([math.radians(a) for a in rot_deg], 'XYZ').to_quaternion()
    return Matrix.LocRotScale(Vector(pos), q, Vector(scale))


def key_object(ctx, obj, base, keys, upright=False, scale=True):
    """کلیدهای ویرایشگر ⇐ کلید در هر فریم روی location / rotation_euler / scale ِ یک شیء.
    upright: فقط چرخش دورِ Z (آدم‌ها همیشه ایستاده‌اند)."""
    if not keys:
        return
    frames = anim.frames_range(ctx.f_start, ctx.f_end)
    obj.rotation_mode = 'XYZ'
    locs, rots, scls = [], [], []
    prev = None
    for f in frames:
        pos, rot, scl = transform(base, keys, f)
        r = [0.0, 0.0, math.radians(rot[2])] if upright else [math.radians(a) for a in rot]
        if prev is not None:      # بی‌پرشِ ۳۶۰ درجه بینِ دو فریم
            r = [a + round((p - a) / (2 * math.pi)) * 2 * math.pi for a, p in zip(r, prev)]
        prev = r
        locs.append(list(pos))
        rots.append(r)
        scls.append(list(scl))
    if has_channel(keys, 'pos'):
        anim.bulk_keys(obj, 'location', frames, locs)
    if has_channel(keys, 'rot'):
        anim.bulk_keys(obj, 'rotation_euler', frames, rots)
    if scale and has_channel(keys, 'scale'):
        anim.bulk_keys(obj, 'scale', frames, scls)
