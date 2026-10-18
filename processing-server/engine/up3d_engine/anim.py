"""هستهٔ انیمیشن: کانال‌های نرم + نوشتنِ سریعِ کلیدها.

هر حرکت فقط «کلیدهای معنایی» می‌گذارد (دستِ راست این‌جا، این زمان). کانال بینِ کلیدها با
Hermite ِ مکعبیِ مهارشده (auto-clamped) نرم می‌شود: بی‌پرش، بی‌فراتر رفتن از هدف، و جایی که دو کلیدِ
برابر هست واقعاً ساکن می‌ماند. چرخش‌ها (کواترنیون) در فضای لگاریتمی نرم می‌شوند.
لایه‌های افزودنی (نفس، جابه‌جاییِ وزن، لرزشِ ریزِ دست) هنگامِ نمونه‌برداری جمع می‌شوند.
"""
import math

import bpy
from mathutils import Quaternion, Vector

from .util import iter_fcurves


def _hermite(p0, p1, m0, m1, t):
    t2, t3 = t * t, t * t * t
    return (2 * t3 - 3 * t2 + 1) * p0 + (t3 - 2 * t2 + t) * m0 + (-2 * t3 + 3 * t2) * p1 + (t3 - t2) * m1


class Channel:
    """کانالِ عددی یا برداری (فهرستی از عددها)."""

    def __init__(self, dim=1, default=None):
        self.dim = dim
        self.keys = []          # [(frame, [values], mode)]
        self.default = list(default) if default is not None else [0.0] * dim

    def key(self, frame, value, mode='auto'):
        v = [float(value)] if self.dim == 1 and not hasattr(value, '__len__') else [float(x) for x in value]
        self.keys = [k for k in self.keys if abs(k[0] - frame) > 1e-4]
        self.keys.append((float(frame), v, mode))
        self.keys.sort(key=lambda k: k[0])

    def clear_range(self, f0, f1):
        self.keys = [k for k in self.keys if not (f0 < k[0] < f1)]

    def last_before(self, frame):
        prev = [k for k in self.keys if k[0] <= frame + 1e-6]
        return prev[-1] if prev else None

    def value(self, frame):
        ks = self.keys
        if not ks:
            return list(self.default)
        if frame <= ks[0][0]:
            return list(ks[0][1])
        if frame >= ks[-1][0]:
            return list(ks[-1][1])
        i = 0
        while ks[i + 1][0] < frame:
            i += 1
        k0, k1 = ks[i], ks[i + 1]
        dt = k1[0] - k0[0]
        t = (frame - k0[0]) / dt
        out = []
        for c in range(self.dim):
            m0 = self._tangent(i, c) * dt
            m1 = self._tangent(i + 1, c) * dt
            out.append(_hermite(k0[1][c], k1[1][c], m0, m1, t))
        return out

    def _tangent(self, i, c):
        ks = self.keys
        if ks[i][2] == 'flat' or i == 0 or i == len(ks) - 1:
            return 0.0
        a, b, d = ks[i - 1][1][c], ks[i][1][c], ks[i + 1][1][c]
        if (b - a) * (d - b) <= 0:        # کمینه/بیشینهٔ محلی یا نگه‌داشتن ⇒ ایست
            return 0.0
        m = (d - a) / (ks[i + 1][0] - ks[i - 1][0])
        # مهار: شیب از ۳ برابرِ شیبِ هر طرف بیشتر نشود (فراتر نرفتن از هدف)
        s0 = (b - a) / (ks[i][0] - ks[i - 1][0])
        s1 = (d - b) / (ks[i + 1][0] - ks[i][0])
        lim = 3 * min(abs(s0), abs(s1))
        return max(-lim, min(lim, m))


class QuatChannel:
    """چرخش: نرم‌سازی در فضای لگاریتمیِ نسبت به یک مرجع."""

    def __init__(self, default=None):
        self.ref = Quaternion(default) if default is not None else Quaternion()
        self.ch = Channel(3)
        self.default = Quaternion(self.ref)

    def set_ref(self, q):
        self.ref = Quaternion(q)
        self.default = Quaternion(q)

    def key(self, frame, q, mode='auto'):
        d = self.ref.inverted() @ Quaternion(q)
        if d.w < 0:
            d = Quaternion((-d.w, -d.x, -d.y, -d.z))
        axis, ang = d.to_axis_angle()
        self.ch.key(frame, (axis * ang)[:], mode)

    def value(self, frame):
        if not self.ch.keys:
            return Quaternion(self.default)
        v = Vector(self.ch.value(frame))
        ang = v.length
        d = Quaternion() if ang < 1e-9 else Quaternion(v / ang, ang)
        return self.ref @ d

    @property
    def keys(self):
        return self.ch.keys

    def last_before(self, frame):
        k = self.ch.last_before(frame)
        if not k:
            return None
        v = Vector(k[1])
        ang = v.length
        return self.ref @ (Quaternion() if ang < 1e-9 else Quaternion(v / ang, ang))


# ───────────────────────── نوشتنِ کلیدها

def ensure_action(id_data, name):
    ad = id_data.animation_data or id_data.animation_data_create()
    if ad.action is None:
        ad.action = bpy.data.actions.new(name)
    return ad.action


def _fcurve(id_data, action, data_path, index):
    if hasattr(action, 'fcurve_ensure_for_datablock'):
        return action.fcurve_ensure_for_datablock(id_data, data_path, index=index)
    fc = action.fcurves.find(data_path, index=index)
    return fc or action.fcurves.new(data_path, index=index)


def bulk_keys(id_data, data_path, frames, values, name=None, interp='LINEAR'):
    """values: برای هر فریم یک عدد یا یک بردار. همهٔ کلیدها با یک فراخوانی (سریع)."""
    if not frames:
        return
    action = ensure_action(id_data, name or (id_data.name + 'Action'))
    dim = len(values[0]) if hasattr(values[0], '__len__') else 1
    for c in range(dim):
        fc = _fcurve(id_data, action, data_path, c)
        fc.keyframe_points.clear()
        fc.keyframe_points.add(len(frames))
        co = []
        for f, v in zip(frames, values):
            co += [float(f), float(v[c] if dim > 1 else v)]
        fc.keyframe_points.foreach_set('co', co)
        mode = {'CONSTANT': 0, 'LINEAR': 1, 'BEZIER': 2}[interp]
        fc.keyframe_points.foreach_set('interpolation', [mode] * len(frames))
        fc.update()


def clear_animation(id_data):
    if id_data.animation_data:
        id_data.animation_data_clear()


def frames_range(f0, f1, step=1):
    return list(range(int(f0), int(f1) + 1, max(1, int(step))))


def smooth_series(values, strength=0.5):
    """هموارسازیِ نمایی دوطرفه (برای دنبال‌کردنِ نرمِ دوربین)."""
    if not values:
        return values
    out = [Vector(v) for v in values]
    a = max(0.0, min(0.98, strength))
    for i in range(1, len(out)):
        out[i] = out[i - 1] * a + out[i] * (1 - a)
    for i in range(len(out) - 2, -1, -1):
        out[i] = out[i + 1] * a + out[i] * (1 - a)
    return out


def noise1(t, seed=0.0):
    """نویزِ نرمِ یک‌بعدی (جمعِ سینوس‌های ناهم‌دوره) — بی‌وابستگی و تکرارپذیر."""
    return (math.sin(t * 1.13 + seed * 7.1) * 0.5 + math.sin(t * 2.37 + seed * 3.3) * 0.3 +
            math.sin(t * 4.91 + seed * 1.7) * 0.2)
