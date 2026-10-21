"""کمک‌های مشترکِ موتور (داخلِ Blender)."""
import json
import math
import sys

import bpy
from mathutils import Matrix, Quaternion, Vector


def stage(name):
    print('UP3D:STAGE %s' % name, flush=True)


def info(**kw):
    print('UP3D:INFO %s' % json.dumps(kw, ensure_ascii=False), flush=True)


def progress(i, n):
    print('UP3D:PROGRESS %d %d' % (i, n), flush=True)


def log(*a):
    print('[up3d]', *a, flush=True)
    sys.stdout.flush()


def ease(u):
    """smoothstep (حرکتِ طبیعی: آهسته شروع، آهسته پایان)."""
    u = max(0.0, min(1.0, u))
    return u * u * (3 - 2 * u)


def ease_inout(u, power=2.0):
    u = max(0.0, min(1.0, u))
    if u < 0.5:
        return 0.5 * (2 * u) ** power
    return 1 - 0.5 * (2 * (1 - u)) ** power


def lerp(a, b, u):
    return a + (b - a) * u


def hex_to_linear(h, alpha=1.0):
    h = (h or '#ffffff').lstrip('#')
    if len(h) == 3:
        h = ''.join(c * 2 for c in h)
    rgb = [int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4)]
    lin = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
    return (lin[0], lin[1], lin[2], alpha)


def kelvin_rgb(k):
    """دمای رنگ ⇐ RGB (تقریبِ Tanner Helland)."""
    t = k / 100.0
    if t <= 66:
        r = 255
        g = 99.4708025861 * math.log(t) - 161.1195681661
        b = 0 if t <= 19 else 138.5177312231 * math.log(t - 10) - 305.0447927307
    else:
        r = 329.698727446 * ((t - 60) ** -0.1332047592)
        g = 288.1221695283 * ((t - 60) ** -0.0755148492)
        b = 255
    c = [max(0, min(255, x)) / 255.0 for x in (r, g, b)]
    return tuple(c)


def look_rot(direction, up=(0, 0, 1)):
    """چرخشی که -Z ِ شیء (دوربین/نور) را به سمتِ direction ببرد."""
    return Vector(direction).to_track_quat('-Z', 'Y')


def basis(f, p):
    """ماتریسِ ۳×۳ از دو بردار (f، p) که بر هم عمود می‌شوند: ستون‌ها f، p، f×p."""
    f = Vector(f).normalized()
    p = (Vector(p) - f * Vector(p).dot(f)).normalized()
    return Matrix((f, p, f.cross(p))).transposed()


def keyframe_obj(obj, frame, loc=None, rot=None, interp=None):
    if loc is not None:
        obj.location = loc
        obj.keyframe_insert('location', frame=frame)
    if rot is not None:
        if obj.rotation_mode != 'QUATERNION':
            obj.rotation_mode = 'QUATERNION'
        obj.rotation_quaternion = rot
        obj.keyframe_insert('rotation_quaternion', frame=frame)


def set_interp(obj, kind='BEZIER', handle='AUTO_CLAMPED', data_path_prefix=None):
    ad = getattr(obj, 'animation_data', None)
    if not ad or not ad.action:
        return
    for fc in iter_fcurves(ad.action):
        if data_path_prefix and not fc.data_path.startswith(data_path_prefix):
            continue
        for kp in fc.keyframe_points:
            kp.interpolation = kind
            if kind == 'BEZIER':
                kp.handle_left_type = handle
                kp.handle_right_type = handle
        fc.update()


def iter_fcurves(action):
    """Blender 4.4+ اکشن‌های لایه‌ای دارد؛ هر دو حالت را پوشش می‌دهد."""
    fcs = getattr(action, 'fcurves', None)
    if fcs is not None and len(fcs):
        for fc in fcs:
            yield fc
        return
    for layer in getattr(action, 'layers', []):
        for strip in layer.strips:
            for bag in getattr(strip, 'channelbags', []):
                for fc in bag.fcurves:
                    yield fc


def add_noise(obj, data_path, index, scale=20.0, strength=0.01, phase=0.0, seed_off=0.0):
    ad = obj.animation_data
    if not ad or not ad.action:
        obj.keyframe_insert(data_path, index=index, frame=1)
        ad = obj.animation_data
    for fc in iter_fcurves(ad.action):
        if fc.data_path == data_path and fc.array_index == index:
            m = fc.modifiers.new('NOISE')
            m.scale = scale
            m.strength = strength
            m.phase = phase + seed_off
            m.blend_type = 'ADD'
            return m
    return None


def link(obj, coll=None):
    (coll or bpy.context.scene.collection).objects.link(obj)
    return obj


def new_collection(name, parent=None):
    c = bpy.data.collections.new(name)
    (parent or bpy.context.scene.collection).children.link(c)
    return c


def empty(name, loc=(0, 0, 0), size=0.05, coll=None, parent=None, kind='PLAIN_AXES'):
    e = bpy.data.objects.new(name, None)
    e.empty_display_type = kind
    e.empty_display_size = size
    link(e, coll)
    if parent:
        e.parent = parent
    e.location = loc
    e.rotation_mode = 'QUATERNION'
    return e


def body_frame_align(hips, head, r_shoulder, l_shoulder):
    """ماتریسِ ۳×۳ که بدنِ یک اسکلت را «ایستاده (بالا = +Z) و رو به -Y» می‌کند.
    بالا = لگن ⇐ سر؛ راست = شانهٔ راست منهای چپ (عمود بر بالا)؛ جلو = بالا × راست.
    (BVH ِ خروجیِ Blender بالا را -Y می‌گذارد، FBX/GLB ِ برخی نرم‌افزارها خوابیده می‌آیند — فقط چرخش دورِ Z کافی نبود.)"""
    up = (Vector(head) - Vector(hips))
    if up.length < 1e-6:
        up = Vector((0, 0, 1))
    up.normalize()
    right = Vector(r_shoulder) - Vector(l_shoulder)
    right = right - up * right.dot(up)
    if right.length < 1e-6:
        right = Vector((-1, 0, 0)) - up * Vector((-1, 0, 0)).dot(up)
    right.normalize()
    fwd = up.cross(right).normalized()
    S = Matrix((right, fwd, up)).transposed()                       # ستون‌ها: راست، جلو، بالا (منبع)
    T = Matrix(((-1, 0, 0), (0, -1, 0), (0, 0, 1))).transposed()    # بازیگر: راست = -X، جلو = -Y، بالا = +Z
    return T @ S.transposed()


def quat_align(prev, q):
    """جلوگیری از چرخشِ ۳۶۰ درجه بینِ دو کلید (هم‌نیم‌کره کردنِ کواترنیون)."""
    if prev is not None and prev.dot(q) < 0:
        return Quaternion((-q.w, -q.x, -q.y, -q.z))
    return q
