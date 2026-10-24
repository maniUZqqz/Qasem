"""کلیدهای ویرایشگرِ آزاد (ویرایشگرِ صحنهٔ پنل) — ریاضیِ مشترکِ نمونه‌برداری.

هر کلید: {"t": ثانیه, "pos": [x,y,z], "rot": [درجه XYZ], "scale": [sx,sy,sz], "target": [..], "lens": mm, "ease": ...}
هر کلید فقط کانال‌هایی را دارد که دارد؛ نمونه‌برداریِ هر کانال فقط از کلیدهای همان کانال است.
«ease» ِ هر کلید نوعِ گذار از همین کلید تا کلیدِ بعدی است:
  smooth   آرام شروع و آرام پایان (پیش‌فرض)      linear  یکنواخت
  ease_in  آرام شروع                              ease_out  آرام پایان
  step     ثابت تا کلیدِ بعد (پرش)                auto  منحنیِ پیوسته از میانِ کلیدها (Catmull-Rom)

همین ریاضی عیناً در موتورِ Blender (engine/up3d_engine/keys.py) و پیش‌نمایشِ مرورگر
(frontend/.../up3d/scene/anim.ts) هست تا آن‌چه در ویرایشگر دیده می‌شود همان باشد که رندر می‌شود.
"""
EASES = ('smooth', 'linear', 'ease_in', 'ease_out', 'step', 'auto')
VEC_CHANNELS = ('pos', 'rot', 'scale', 'target')


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
    # smooth: مکعبیِ آرام-آرام
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


def sample(keys, time, channel, default=None, tkey='t'):
    """مقدارِ یک کانال در زمانِ time (ثانیه، یا فریم اگر tkey='f')."""
    ks = [k for k in keys or () if k.get(channel) is not None]
    if not ks:
        return default
    if time <= ks[0][tkey]:
        return ks[0][channel]
    if time >= ks[-1][tkey]:
        return ks[-1][channel]
    i = 0
    while i + 1 < len(ks) - 1 and ks[i + 1][tkey] <= time:
        i += 1
    a, b = ks[i], ks[i + 1]
    span = float(b[tkey] - a[tkey]) or 1e-9
    u = (time - a[tkey]) / span
    kind = a.get('ease') or 'smooth'
    if kind == 'auto':
        p0 = ks[i - 1][channel] if i > 0 else a[channel]
        p3 = ks[i + 2][channel] if i + 2 < len(ks) else b[channel]
        return _catmull(p0, a[channel], b[channel], p3, u)
    return _lerp(a[channel], b[channel], ease(kind, u))


def transform_at(obj, time, tkey='t'):
    """جای شیء در زمانِ time: از کلیدها (اگر هست) وگرنه transform ِ ثابت؛ None اگر هیچ‌کدام نیست."""
    tr = obj.get('transform')
    keys = obj.get('keys') or []
    if not tr and not keys:
        return None
    base = {'pos': [0.0, 0.0, 0.0], 'rot': [0.0, 0.0, 0.0], 'scale': [1.0, 1.0, 1.0]}
    if tr:
        base.update({k: list(tr[k]) for k in ('pos', 'rot', 'scale') if tr.get(k) is not None})
    return {ch: list(sample(keys, time, ch, base[ch], tkey)) for ch in ('pos', 'rot', 'scale')}
