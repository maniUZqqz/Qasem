"""منبعِ حرکتِ «کلیپ» (mocap: BVH / FBX) — بازهدف‌گیری (retarget) روی هر بازیگر.

manifest ِ یک حرکتِ کلیپی (پوشهٔ motions/<id>/):
    "source": {"type": "clip", "file": "wave.bvh",
               "rig": "auto" | "mpfb_default" | "mixamo" | "cmu",       نقشهٔ نامِ استخوان‌های فایل (engine/rigs/*.json)
               "bone_map": {"<نامِ استخوانِ فایل>": "<نقش>"},             اختیاری؛ نقش‌ها: hips، spine.0، neck.0، head،
                                                                        arm.R.upper/fore/hand/clavicle، leg.L.upper/lower/foot،
                                                                        fingers.R.index.0 …
               "channels": ["spine", "neck", "arms", "fingers"],        پیش‌فرض: بالاتنه (+ "legs"، "root" برای تمام‌بدن)
               "frames": [1, 120], "speed": 1.0, "loop": false, "fit": false}

روش (بی‌نیاز به هم‌نام بودنِ استخوان‌ها یا هم‌شکل بودنِ حالتِ استراحت T / A):
  ۱. فایل وارد می‌شود ⇐ اسکلتِ منبع + اکشن؛ ژستِ هر فریم با FK ِ دستی از روی منحنی‌ها خوانده می‌شود (بی‌ارزیابیِ صحنه)
     و اسکلتِ منبع بعد از نمونه‌برداری پاک می‌شود.
  ۲. جهتِ رو-به-جلوی منبع از روی شانه‌ها پیدا و با بازیگر (رو به -Y) هم‌راستا می‌شود؛ جابه‌جاییِ لگن با نسبتِ طولِ پا.
  ۳. هر استخوانِ هم‌نقش: «جهتِ جهانیِ» استخوانِ منبع ⇐ همان جهت برای استخوانِ بازیگر (هم‌ترازیِ حالتِ استراحت با
     کمترین چرخش) ⇐ FK ِ بازیگر.
  ۴. ستون، گردن، سر، ترقوه، انگشت‌ها، لگن: چرخشِ محلی روی استخوان (لایهٔ کلیپ در rig.realize، با محوشدنِ دو سر).
     دست‌ها: جای مچ از FK ⇐ کانال‌های hand.* (IK؛ پس محصولِ در دست و محدودیتِ طولِ بازو حفظ می‌شود).
     پاها (اگر خواسته شود): جای قوزک ⇐ هدفِ IK ِ پا.
"""
import glob
import json
import math
import os

import bpy
from mathutils import Euler, Matrix, Quaternion, Vector

from . import anim
from .rig import FINGERS, SIDES, resolve_rigmap
from .util import body_frame_align, iter_fcurves, log

ENGINE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_CHANNELS = ('spine', 'neck', 'arms', 'fingers')
_SOURCES = {}


# ───────────────────────── نقشه‌ها

def rigmaps(extra_dirs=()):
    out = {}
    for d in [os.path.join(ENGINE_DIR, 'rigs')] + list(extra_dirs):
        for p in sorted(glob.glob(os.path.join(d, '*.json'))):
            try:
                with open(p, encoding='utf-8') as fh:
                    m = json.load(fh)
            except (OSError, ValueError):
                continue
            if isinstance(m, dict) and m.get('roles'):
                out[m.get('id') or os.path.splitext(os.path.basename(p))[0]] = m
    return out


def role_bones(roles):
    """نقش‌ها ⇐ [(کلید، نامِ استخوان)] — کلیدها: hips، spine.0، neck.0، head، arm.R.upper، fingers.R.index.1 …"""
    out = [('hips', roles['hips'])]
    out += [('spine.%d' % i, b) for i, b in enumerate(roles['spine'])]
    out += [('neck.%d' % i, b) for i, b in enumerate(roles.get('neck') or [])]
    out.append(('head', roles['head']))
    for s in SIDES:
        a = roles['arm.%s' % s]
        out += [('arm.%s.%s' % (s, k), a[k]) for k in ('clavicle', 'upper', 'fore', 'hand') if a.get(k)]
        lg = roles['leg.%s' % s]
        out += [('leg.%s.%s' % (s, k), lg[k]) for k in ('upper', 'lower', 'foot') if lg.get(k)]
        for fn, chain in (roles.get('fingers.%s' % s) or {}).items():
            out += [('fingers.%s.%s.%d' % (s, fn, i), b) for i, b in enumerate(chain)]
    return out


def map_source(bone_names, spec, extra_dirs=()):
    """اسکلتِ فایل ⇐ {کلیدِ نقش: نامِ استخوان}. rig = نامِ نقشه یا auto (بهترین نقشه‌ای که بیشترین نقش را پیدا کند)."""
    maps = rigmaps(extra_dirs)
    want = spec.get('rig') or 'auto'
    if isinstance(spec.get('rigmap'), dict):
        maps = {'inline': spec['rigmap']}
        want = 'inline'
    cands = [want] if want != 'auto' else list(maps)
    best = None
    errors = []
    for name in cands:
        m = maps.get(name)
        if not m:
            errors.append('نقشهٔ «%s» نیست' % name)
            continue
        try:
            res = resolve_rigmap(bone_names, m)
        except ValueError as e:
            errors.append('%s: %s' % (name, e))
            continue
        rb = dict(role_bones(res['roles']))
        if best is None or len(rb) > len(best[1]):
            best = (name, rb)
    if best is None and not spec.get('bone_map'):
        raise ValueError('نامِ استخوان‌های فایلِ کلیپ با هیچ نقشه‌ای نمی‌خواند (rig یا bone_map بدهید). ' + ' | '.join(errors[:3]))
    name, rb = best or ('bone_map', {})
    for src_bone, key in (spec.get('bone_map') or {}).items():
        if src_bone in bone_names:
            rb[key] = src_bone
    return name, rb


# ───────────────────────── منبع

class Source:
    """اسکلتِ واردشده + نمونه‌برداریِ ژست با FK ِ دستی (منحنی‌ها ⇐ ماتریسِ فضای اسکلت)."""

    def __init__(self, path, fps):
        self.path = path
        sc = bpy.context.scene
        sc.render.fps = int(round(fps))
        sc.render.fps_base = 1.0
        before = set(bpy.data.objects)
        ext = os.path.splitext(path)[1].lower()
        if ext == '.bvh':
            bpy.ops.import_anim.bvh(filepath=path, target='ARMATURE', global_scale=1.0, frame_start=1,
                                    use_fps_scale=True, update_scene_fps=False, update_scene_duration=False,
                                    rotate_mode='NATIVE', axis_forward='-Z', axis_up='Y')
        elif ext == '.fbx':
            bpy.ops.import_scene.fbx(filepath=path, use_anim=True, automatic_bone_orientation=True, ignore_leaf_bones=False)
        elif ext in ('.glb', '.gltf'):
            bpy.ops.import_scene.gltf(filepath=path)
        else:
            raise ValueError('قالبِ کلیپ پشتیبانی نمی‌شود: %s (BVH / FBX / GLB)' % ext)
        new = [o for o in bpy.data.objects if o not in before]
        arms = [o for o in new if o.type == 'ARMATURE' and o.animation_data and o.animation_data.action]
        if not arms:
            arms = [o for o in new if o.type == 'ARMATURE']
        if not arms:
            self._cleanup(new)
            raise ValueError('فایلِ کلیپ اسکلت ندارد: %s' % os.path.basename(path))
        arm = max(arms, key=lambda o: len(o.data.bones))
        act = arm.animation_data.action if arm.animation_data else None
        if act is None:
            self._cleanup(new)
            raise ValueError('فایلِ کلیپ انیمیشن ندارد: %s' % os.path.basename(path))
        self.names = [b.name for b in arm.data.bones]
        self.parent = {b.name: (b.parent.name if b.parent else None) for b in arm.data.bones}
        self.order = []

        def walk(b):
            self.order.append(b.name)
            for c in b.children:
                walk(c)
        for b in arm.data.bones:
            if b.parent is None:
                walk(b)
        self.rest = {b.name: b.matrix_local.copy() for b in arm.data.bones}
        self.rel = {n: (self.rest[p].inverted() @ self.rest[n]) if p else self.rest[n].copy()
                    for n, p in self.parent.items()}
        self.modes = {pb.name: pb.rotation_mode for pb in arm.pose.bones}
        self.mw = arm.matrix_world.copy()
        self.curves = {}
        for fc in iter_fcurves(act):
            self.curves[(fc.data_path, fc.array_index)] = fc
        fr = act.frame_range
        self.f0, self.f1 = float(fr[0]), float(fr[1])
        # FK ِ دستی به ماتریس‌های منحنی نیاز دارد؛ اسکلتِ منبع دیگر لازم نیست
        self._cleanup(new)
        self._memo = {}

    @staticmethod
    def _cleanup(objs):
        for o in objs:
            try:
                bpy.data.objects.remove(o, do_unlink=True)
            except (ReferenceError, RuntimeError):
                pass

    def _ev(self, path, i, default):
        fc = self.curves.get((path, i))
        return fc.evaluate(self._f) if fc else default

    def _basis(self, name):
        p = 'pose.bones["%s"].' % bpy.utils.escape_identifier(name)
        loc = Vector([self._ev(p + 'location', i, 0.0) for i in range(3)])
        mode = self.modes.get(name, 'QUATERNION')
        if mode == 'QUATERNION':
            q = Quaternion([self._ev(p + 'rotation_quaternion', i, (1.0, 0.0, 0.0, 0.0)[i]) for i in range(4)])
            q.normalize()
            R = q.to_matrix()
        elif mode == 'AXIS_ANGLE':
            v = [self._ev(p + 'rotation_axis_angle', i, (0.0, 0.0, 1.0, 0.0)[i]) for i in range(4)]
            R = Matrix.Rotation(v[0], 3, Vector(v[1:]).normalized() if Vector(v[1:]).length > 1e-9 else Vector((0, 0, 1)))
        else:
            R = Euler([self._ev(p + 'rotation_euler', i, 0.0) for i in range(3)], mode).to_matrix()
        return Matrix.Translation(loc) @ R.to_4x4()

    def pose(self, f):
        """ماتریسِ هر استخوان در فضای جهان در فریمِ f ِ منبع (عدد اعشاری هم می‌شود)."""
        key = round(f, 3)
        if key in self._memo:
            return self._memo[key]
        self._f = f
        M = {}
        for n in self.order:
            B = self._basis(n)
            p = self.parent[n]
            M[n] = (M[p] @ self.rel[n] @ B) if p else (self.rest[n] @ B)
        out = {n: self.mw @ m for n, m in M.items()}
        if len(self._memo) > 4000:
            self._memo.clear()
        self._memo[key] = out
        return out

    def rest_world(self):
        return {n: self.mw @ m for n, m in self.rest.items()}


def _rot(m):
    return m.to_3x3().normalized()


def _y(m3):
    return Vector((m3[0][1], m3[1][1], m3[2][1])).normalized()


# ───────────────────────── اجرا

def apply(ctx, rig, act):
    src_spec = dict(act.get('source') or {})
    folder = act.get('folder') or ''
    path = src_spec.get('file') or ''
    if path and not os.path.isabs(path):
        path = os.path.join(folder, path)
    if not path or not os.path.isfile(path):
        raise FileNotFoundError('فایلِ کلیپِ حرکتِ «%s» پیدا نشد: %s' % (act.get('motion'), src_spec.get('file')))
    key = (path, os.path.getmtime(path), ctx.fps)
    src = _SOURCES.get(key)
    if src is None:
        src = _SOURCES[key] = Source(path, ctx.fps)
    extra_dirs = [folder] if folder else []
    rig_name, smap = map_source(src.names, src_spec, extra_dirs)
    params = act.get('params') or {}
    channels = set(params.get('channels') or src_spec.get('channels') or DEFAULT_CHANNELS)
    troles = rig.roles
    tmap = dict(role_bones(troles))

    # هم‌ترازیِ کاملِ بدن: بالا (لگن ⇐ سر) ⇐ +Z و جلو ⇐ -Y ِ بازیگر
    rest_w = src.rest_world()

    def rp(key, default):
        return rest_w[smap[key]].translation if smap.get(key) else Vector(default)
    A3 = body_frame_align(rp('hips', (0, 0, 1)), rp('head', (0, 0, 1.7)), rp('arm.R.upper', (-0.2, 0, 1.45)),
                          rp('arm.L.upper', (0.2, 0, 1.45)))

    def src_leg(side):
        u, f = smap.get('leg.%s.upper' % side), smap.get('leg.%s.foot' % side)
        return (rest_w[u].translation - rest_w[f].translation).length if u and f else None
    tl = (rig.L['hipjoint.R'] - rig.L['ankle.R']).length
    sl = src_leg('R') or src_leg('L')
    k_scale = tl / sl if sl and sl > 1e-6 else 1.0

    # جفت‌ها: کلیدِ نقشِ بازیگر ⇐ استخوانِ منبع (ستون/گردن با شمارِ متفاوت ⇐ نزدیک‌ترین نسبی)
    def chain_pairs(prefix):
        tk = sorted([k for k in tmap if k.startswith(prefix + '.')], key=lambda k: int(k.split('.')[-1]))
        sk = sorted([k for k in smap if k.startswith(prefix + '.')], key=lambda k: int(k.split('.')[-1]))
        out = {}
        if not tk or not sk:
            return out
        for i, k in enumerate(tk):
            j = round(i * (len(sk) - 1) / max(1, len(tk) - 1)) if len(tk) > 1 else len(sk) - 1
            out[tmap[k]] = smap[sk[j]]
        return out
    pairs = {}
    pairs.update(chain_pairs('spine'))
    pairs.update(chain_pairs('neck'))
    for k, tb in tmap.items():
        if k.startswith(('spine.', 'neck.')):
            continue
        if k in smap:
            pairs[tb] = smap[k]
    if not pairs:
        raise ValueError('هیچ استخوانِ هم‌نقشی بینِ کلیپ و بازیگر پیدا نشد')

    arm = rig.arm
    tb_all = arm.data.bones
    t_rest = {b.name: b.matrix_local.copy() for b in tb_all}
    t_parent = {b.name: (b.parent.name if b.parent else None) for b in tb_all}
    t_rel = {n: (t_rest[p].inverted() @ t_rest[n]) if p else t_rest[n].copy() for n, p in t_parent.items()}
    t_order = []

    def walk(b):
        t_order.append(b.name)
        for c in b.children:
            walk(c)
    for b in tb_all:
        if b.parent is None:
            walk(b)
    hips_t = troles['hips']
    hips_s = smap.get('hips')
    # هم‌ترازیِ حالتِ استراحت برای هر جفت
    Rs0 = {s: A3 @ _rot(rest_w[s]) for s in set(pairs.values())}
    align = {}
    for tbn, sbn in pairs.items():
        Rt0 = _rot(t_rest[tbn])
        if tbn == hips_t:
            align[tbn] = Rs0[sbn].inverted() @ Rt0
        else:
            C = _y(Rt0).rotation_difference(_y(Rs0[sbn])).to_matrix()
            align[tbn] = Rs0[sbn].inverted() @ C @ Rt0

    f0, f1 = int(act['f0']), int(act['f1'])
    cs = float(src_spec.get('frames', [src.f0, src.f1])[0])
    ce = float(src_spec.get('frames', [src.f0, src.f1])[1])
    span = max(1e-6, ce - cs)
    speed = float(params.get('speed') or src_spec.get('speed') or 1.0)
    loop = bool(params.get('loop', src_spec.get('loop', False)))
    fit = bool(params.get('fit', src_spec.get('fit', False)))
    hips0 = src.pose(cs)[hips_s].translation.copy() if hips_s else None

    def src_frame(f):
        if fit:
            return cs + (f - f0) / max(1, f1 - f0) * span
        x = cs + (f - f0) * speed
        if x > ce:
            x = cs + ((x - cs) % span) if loop and span > 1e-6 else ce
        return x

    bones_out = {}
    hips_off = {}
    feet = {s: {} for s in SIDES} if 'legs' in channels else {}
    hands = {s: {} for s in SIDES}
    want_bones = set()
    if 'spine' in channels:
        want_bones |= set(troles['spine'])
    if 'neck' in channels:
        want_bones |= set(troles.get('neck') or []) | {troles['head']}
    if 'arms' in channels:
        want_bones |= {troles['arm.%s' % s]['clavicle'] for s in SIDES if troles['arm.%s' % s].get('clavicle')}
    if 'fingers' in channels:
        for s in SIDES:
            for chain in (troles.get('fingers.%s' % s) or {}).values():
                want_bones |= set(chain)
    if 'root' in channels:
        want_bones.add(hips_t)
    for f in range(f0, f1 + 1):
        P = src.pose(src_frame(f))
        M = {}
        local = {}
        for n in t_order:
            p = t_parent[n]
            base = (M[p] @ t_rel[n]) if p else t_rest[n].copy()
            if n == hips_t and 'root' in channels and hips_s is not None and hips0 is not None:
                d = A3 @ (P[hips_s].translation - hips0) * k_scale
                base = Matrix.Translation(d) @ base
                hips_off[f] = d[:]
            sbn = pairs.get(n)
            if sbn is not None and (n != hips_t or 'root' in channels):
                R = (A3 @ _rot(P[sbn])) @ align[n]
                Mn = Matrix.Translation(base.translation) @ R.to_4x4()
                local[n] = (base.inverted() @ Mn).to_quaternion()
            else:
                Mn = base
            M[n] = Mn
        for n in want_bones:
            if n in local:
                bones_out.setdefault(n, {})[f] = local[n][:]
        if 'arms' in channels:
            for s in SIDES:
                hb = troles['arm.%s' % s]['hand']
                hands[s][f] = (M[hb].translation.copy(), M[hb].to_quaternion())
        for s in feet:
            fb = troles['leg.%s' % s]['foot']
            feet[s][f] = (M[fb].translation[:], M[fb].to_quaternion()[:])

    fade = max(1.0, min(0.3 * ctx.fps, 0.25 * (f1 - f0)))

    def weight(f, a=f0, b=f1, fd=fade):
        return anim.smootherstep((f - a) / fd) * anim.smootherstep((b - f) / fd) if b > a else 1.0
    rig.clips.append({'f0': f0, 'f1': f1, 'weight': weight, 'bones': bones_out, 'hips_off': hips_off, 'feet': feet,
                      'motion': act.get('motion')})
    # دست‌ها از راهِ IK: کلید در هر فریم (لبه‌ها از جای فعلی نرم وارد/خارج می‌شوند)
    if 'arms' in channels:
        for s in SIDES:
            if ctx.holding(rig.id, s):
                continue                      # دستی که محصول گرفته را کلیپ رها نمی‌کند
            rig.ch['hand.' + s].key(f0, rig.ch['hand.' + s].value(f0))
            rig.ch['handrot.' + s].key(f0, rig.ch['handrot.' + s].value(f0))
            rig.ch['noise.' + s].key(f0, rig.ch['noise.' + s].value(f0))
            rig.ch['noise.' + s].key(f0 + fade, 0.0, 'flat')
            rig.ch['noise.' + s].key(f1 - fade, 0.0, 'flat')
            rig.ch['noise.' + s].key(f1 + 0.4 * ctx.fps, 1.0, 'flat')
            for f in range(int(f0 + fade), f1 + 1):
                loc, q = hands[s][f]
                rig.key_hand(s, f, loc, q)
    if 'neck' in channels:
        hf = rig.ch['head_follow']
        hf.key(f0, hf.value(f0))
        hf.key(f0 + fade, float(src_spec.get('head_follow', 0.35)))
        hf.key(f1 - fade, float(src_spec.get('head_follow', 0.35)))
        hf.key(f1, 0.82)
    log('clip', act.get('motion'), os.path.basename(path), 'rig=%s pairs=%d frames=%d..%d src=%.0f..%.0f scale=%.2f ch=%s' % (
        rig_name, len(pairs), f0, f1, cs, ce, k_scale, ','.join(sorted(channels))))
