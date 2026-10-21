"""ریگِ کنترلیِ بازیگر.

روی اسکلتِ کاراکتر (هر اسکلتی که نقشهٔ نقش داشته باشد) یک لایهٔ کنترلِ معنایی می‌سازد:
  - هدفِ IK برای مچِ هر دست (موقعیت + جهت) و هر پا (پاها روی زمین می‌مانند)
  - هدفِ نگاه برای سر (Damped Track) و چشم‌ها (تماسِ چشمی با دوربین)
  - کانال‌های نرم: ستونِ فقرات، لگن، سرشانه، کجیِ سر، خمِ انگشت‌ها
همهٔ مختصات «فضای بازیگر» است: مبدأ = جای ایستادن روی زمین، رو به -Y، راستِ بازیگر = -X.
اندازه‌ها از خودِ اسکلت خوانده می‌شود (قد، طولِ دست…) پس حرکت‌ها برای هر اندام درست می‌نشینند.
"""
import math
import re

import bpy
from mathutils import Euler, Matrix, Quaternion, Vector

from . import anim
from .anim import Channel, QuatChannel
from .util import basis, empty, log

SIDES = ('R', 'L')
SIGN = {'R': -1.0, 'L': 1.0}
FINGERS = ('thumb', 'index', 'middle', 'ring', 'pinky')
FINGER_PRESETS = {
    # دستِ رها: انگشت‌ها پله‌پله خمیده‌تر (اشاره کمتر، کوچک بیشتر) — نه صاف و هم‌شکل
    'relaxed': {'thumb': 0.2, 'index': 0.24, 'middle': 0.31, 'ring': 0.38, 'pinky': 0.45},
    'open': {'thumb': 0.0, 'index': 0.02, 'middle': 0.03, 'ring': 0.04, 'pinky': 0.05},
    'grip': {'thumb': 0.55, 'index': 0.62, 'middle': 0.68, 'ring': 0.72, 'pinky': 0.75},
    'pinch': {'thumb': 0.45, 'index': 0.5, 'middle': 0.42, 'ring': 0.5, 'pinky': 0.55},
    'point': {'thumb': 0.5, 'index': 0.0, 'middle': 0.85, 'ring': 0.9, 'pinky': 0.9},
    'fist': {'thumb': 0.7, 'index': 0.95, 'middle': 0.95, 'ring': 0.95, 'pinky': 0.95},
    'thumbs_up': {'thumb': -0.1, 'index': 0.95, 'middle': 0.95, 'ring': 0.95, 'pinky': 0.95},
    'spread': {'thumb': -0.05, 'index': 0.0, 'middle': 0.0, 'ring': 0.02, 'pinky': 0.03},
}
CURL_MAX = (0.9, 1.4, 1.0)      # بیشترین خمِ هر بندِ انگشت (رادیان) در curl=1


def _norm(name):
    n = str(name).split(':')[-1].split('|')[-1].lower()
    return re.sub(r'[^a-z0-9]', '', n)


REQUIRED_ROLES = ('hips', 'spine', 'head', 'arm.R.upper', 'arm.R.fore', 'arm.R.hand', 'arm.L.upper', 'arm.L.fore',
                  'arm.L.hand', 'leg.R.upper', 'leg.R.lower', 'leg.R.foot', 'leg.L.upper', 'leg.L.lower', 'leg.L.foot')


class BoneResolver:
    """نامِ استخوانِ نقشه ⇐ نامِ واقعی در این اسکلت: دقیق، بی‌پیشوند (mixamorig: / Armature|)، یا پسوندِ یکتا."""

    def __init__(self, names):
        self.names = list(names)
        self.exact = set(self.names)
        self.by_norm = {}
        for n in self.names:
            self.by_norm.setdefault(_norm(n), []).append(n)

    def __call__(self, name):
        if not name:
            return None
        if name in self.exact:
            return name
        k = _norm(name)
        hit = self.by_norm.get(k)
        if hit and len(hit) == 1:
            return hit[0]
        if len(k) >= 4:
            cand = [n for nk, ns in self.by_norm.items() for n in ns if nk.endswith(k) or k.endswith(nk) and len(nk) >= 4]
            if len(cand) == 1:
                return cand[0]
        return None


def resolve_rigmap(bone_names, rigmap):
    """نقشهٔ نقش‌ها ⇐ نام‌های واقعی + پیش‌فرضِ نقش‌های اختیاری. استخوانِ اختیاریِ نبود ⇐ حذف؛ لازمِ نبود ⇐ خطا."""
    res = BoneResolver(bone_names)
    roles = dict(rigmap.get('roles') or {})
    out = dict(roles)
    missing = []

    def one(v, path, required=False):
        r = res(v) if isinstance(v, str) else None
        if r is None and required:
            missing.append('%s (%s)' % (path, v))
        return r

    out['hips'] = one(roles.get('hips'), 'hips', True)
    out['head'] = one(roles.get('head'), 'head', True)
    out['spine'] = [x for x in (one(b, 'spine') for b in roles.get('spine') or []) if x]
    if not out['spine']:
        missing.append('spine')
    if roles.get('spine_weights') and len(roles['spine_weights']) != len(out['spine']):
        out.pop('spine_weights', None)
    out['neck'] = [x for x in (one(b, 'neck') for b in roles.get('neck') or []) if x]
    out['eyes'] = [x for x in (one(b, 'eyes') for b in roles.get('eyes') or []) if x]
    if len(out['eyes']) != 2:
        out['eyes'] = []
    out['jaw'] = one(roles.get('jaw'), 'jaw')
    for s in SIDES:
        a = dict(roles.get('arm.%s' % s) or {})
        arm = {k: one(a.get(k), 'arm.%s.%s' % (s, k), k in ('upper', 'fore', 'hand')) for k in
               ('clavicle', 'upper', 'upper_twist', 'fore', 'fore_twist', 'hand')}
        arm['upper_twist'] = arm['upper_twist'] or arm['upper']
        arm['fore_twist'] = arm['fore_twist'] or arm['fore']
        out['arm.%s' % s] = arm
        lgr = dict(roles.get('leg.%s' % s) or {})
        leg = {k: one(lgr.get(k), 'leg.%s.%s' % (s, k), k in ('upper', 'lower', 'foot')) for k in
               ('upper', 'upper_twist', 'lower', 'lower_twist', 'foot')}
        leg['upper_twist'] = leg['upper_twist'] or leg['upper']
        leg['lower_twist'] = leg['lower_twist'] or leg['lower']
        out['leg.%s' % s] = leg
        fr = dict(roles.get('fingers.%s' % s) or {})
        fingers = {}
        for fn in FINGERS:
            chain = [x for x in (one(b, 'fingers') for b in fr.get(fn) or []) if x]
            if chain:
                fingers[fn] = chain[:3]
        out['fingers.%s' % s] = fingers if len(fingers) == len(FINGERS) else {}
    if missing:
        raise ValueError('نقشهٔ استخوان با این اسکلت نمی‌خواند؛ پیدا نشد: ' + '، '.join(missing[:12]))
    m = dict(rigmap)
    m['roles'] = out
    return m


class ActorRig:
    def __init__(self, ctx, actor, built):
        self.ctx = ctx
        self.id = actor['id']
        self.arm = built['armature']
        self.body = built['body']
        self.meshes = built['meshes']
        self.face_meshes = built['face_meshes']
        self.map = resolve_rigmap([b.name for b in built['armature'].data.bones], built['rigmap'])
        self.roles = self.map['roles']
        self.clips = []          # لایه‌های کلیپِ mocap (clips.py): [{'f0','f1','fade','bones':{name:{f:quat}}, ...}]
        coll = ctx.coll(self.id)
        mark = actor['mark']
        self.root = empty('%s.root' % self.id, mark['pos'], 0.3, coll)
        self.root.rotation_mode = 'XYZ'
        self.root.rotation_euler = (0, 0, math.radians(mark.get('facing', 0.0)))
        self.arm.parent = self.root
        self.arm.matrix_parent_inverse = Matrix.Identity(4)
        self.arm.location = (0, 0, 0)
        self.arm.rotation_euler = (0, 0, 0)
        bpy.context.view_layer.update()
        self.pb = self.arm.pose.bones
        self._landmarks()
        self.ch = {
            'spine': Channel(3), 'hips': Channel(4), 'head_tilt': Channel(1), 'head_off': Channel(3),
            'head_follow': Channel(1, [0.82]), 'clav.R': Channel(1), 'clav.L': Channel(1),
            'noise.R': Channel(1, [1.0]), 'noise.L': Channel(1, [1.0]),
            # آرنج چقدر به بیرون باز شود (۰ = چسبیده به پهلو، ۱ = کاملاً بیرون) — جهتِ قطبِ IK از این و جای دست
            'elbow.R': Channel(1, [0.25]), 'elbow.L': Channel(1, [0.25]),
        }
        for s in SIDES:
            self.ch['hand.%s' % s] = Channel(3, self.neutral_pos(s)[:])
            self.ch['handrot.%s' % s] = QuatChannel(self.neutral_rot(s))
            self.ch['fingers.%s' % s] = Channel(5, [FINGER_PRESETS['relaxed'][f] for f in FINGERS])
        self._build_targets(coll)
        self._calibrate()

    # ───────── اندازه‌ها
    def bone(self, name):
        return self.arm.data.bones[name]

    def _landmarks(self):
        r = self.roles
        B = self.bone
        L = {}
        for s in SIDES:
            a = r['arm.%s' % s]
            L['shoulder.' + s] = B(a['upper']).head_local.copy()
            L['elbow.' + s] = B(a['fore']).head_local.copy()
            L['wrist.' + s] = B(a['hand']).head_local.copy()
            L['arm_len.' + s] = (L['elbow.' + s] - L['shoulder.' + s]).length + (L['wrist.' + s] - L['elbow.' + s]).length
            lg = r['leg.%s' % s]
            L['hipjoint.' + s] = B(lg['upper']).head_local.copy()
            L['knee.' + s] = B(lg['lower']).head_local.copy()
            L['ankle.' + s] = B(lg['foot']).head_local.copy()
            f = r['fingers.%s' % s]
            hb = B(a['hand'])
            if f:
                L['palm_center.' + s] = (B(f['middle'][0]).head_local + hb.head_local) * 0.5
            else:
                L['palm_center.' + s] = hb.head_local + (hb.tail_local - hb.head_local) * 0.55
        L['hips'] = B(r['hips']).head_local.copy()
        L['chest'] = B(r['spine'][-1]).head_local.copy()
        L['neck'] = B(r['neck'][0]).head_local.copy() if r['neck'] else B(r['head']).head_local.copy()
        L['head'] = B(r['head']).head_local.copy()
        L['top'] = B(r['head']).tail_local.copy()
        if r['eyes']:
            eyes = [B(e).head_local for e in r['eyes']]
            L['eyes'] = (eyes[0] + eyes[1]) * 0.5
        else:       # اسکلتِ بی‌استخوانِ چشم (Mixamo): میانهٔ سر، کمی جلوتر
            hb = B(r['head'])
            L['eyes'] = hb.head_local + (hb.tail_local - hb.head_local) * 0.45 + Vector((0, -0.08, 0))
        L['height'] = L['top'].z + 0.04
        L['face'] = L['eyes'] + Vector((0, -0.02, -0.03))
        self.L = L
        # پایهٔ دستِ در حالتِ استراحت (برای تبدیلِ «جهتِ انگشت/کفِ دست» به چرخشِ مچ)
        self.hand_rest = {}
        for s in SIDES:
            a, f = r['arm.%s' % s], r['fingers.%s' % s]
            h = B(a['hand']).head_local
            if f:
                f0 = (B(f['middle'][0]).head_local - h).normalized()
                i0 = (B(f['index'][0]).head_local - B(f['pinky'][0]).head_local).normalized()
            else:
                f0 = (B(a['hand']).tail_local - h).normalized()
                i0 = (Vector((0, -1, 0)) - f0 * Vector((0, -1, 0)).dot(f0)).normalized()
            p0 = i0.cross(f0) if s == 'R' else f0.cross(i0)
            Rw = B(a['hand']).matrix_local.to_3x3()
            B0 = basis(f0, p0)
            pc = L['palm_center.' + s] + (p0 - f0 * p0.dot(f0)).normalized() * 0.012
            self.hand_rest[s] = {'B0': B0, 'Rw': Rw, 'palm_off': Rw.transposed() @ (pc - h), 'p0': p0, 'f0': f0}

    # ───────── وضعیتِ پایه
    def neutral_pos(self, s):
        """دستِ رها کنارِ بدن: بازو تقریباً کشیده، آرنج کمی خم و رو به عقب، دست کمی جلوی ران
        (قبلاً ۹۰٪ ِ طولِ دست بود و قطبِ کناری آرنج را بیرون می‌زد ⇐ حالتِ «دست به کمر»)."""
        L = self.L
        return L['shoulder.' + s] + Vector((SIGN[s] * 0.045, -0.055, -0.955 * L['arm_len.' + s]))

    def neutral_rot(self, s):
        # کفِ دست رو به ران و کمی رو به عقب، انگشت‌ها پایین و کمی جلو
        return self.hand_rot(s, Vector((-SIGN[s] * 0.05, -0.2, -1)), Vector((-SIGN[s], 0.35, 0)))

    def pole_for(self, s, hand, out=0.25):
        """جای قطبِ IK ِ آرنج برای این جای دست: همیشه «پایین و عقب و کمی بیرون» نسبت به خطِ شانه-مچ.
        فقط مؤلفهٔ عمود بر بازو اثر دارد ⇐ دستِ آویزان: آرنج رو به عقب؛ دستِ جلوی سینه: آرنج رو به پایین؛
        دستِ بالا (سلام): آرنج پایین و بیرون — نه افقی و کناری."""
        sh = self.L['shoulder.' + s]
        k = Vector((SIGN[s] * (0.12 + 0.5 * out), 0.55, -0.8)).normalized()
        return (sh + Vector(hand)) * 0.5 + k * 0.45

    def hand_rot(self, s, fingers, palm):
        """جهتِ انگشت‌ها و کفِ دست (فضای بازیگر) ⇐ کواترنیونِ هدفِ مچ."""
        hr = self.hand_rest[s]
        R = basis(fingers, palm) @ hr['B0'].transposed()
        return (R @ hr['Rw']).to_quaternion()

    def wrist_for_palm(self, s, palm_center, q):
        """مچ کجا باشد تا مرکزِ کفِ دست روی palm_center بنشیند."""
        return Vector(palm_center) - q.to_matrix() @ self.hand_rest[s]['palm_off']

    # ───────── ساختِ هدف‌ها و قیدها
    def _build_targets(self, coll):
        r = self.roles
        self.t = {}
        for s in SIDES:
            a = r['arm.%s' % s]
            tg = empty('%s.hand.%s' % (self.id, s), self.L['wrist.' + s], 0.04, coll, self.root, 'SPHERE')
            tg.rotation_quaternion = self.bone(a['hand']).matrix_local.to_quaternion()
            pole = empty('%s.elbow.%s' % (self.id, s), self.pole_for(s, self.neutral_pos(s)),
                         0.03, coll, self.root)
            self.t['hand.' + s], self.t['pole.' + s] = tg, pole
            ik = self.pb[a['fore_twist']].constraints.new('IK')
            ik.target, ik.pole_target = tg, pole
            ik.chain_count = self._chain(a['fore_twist'], a['upper'])
            ik.use_tail = True
            ik.use_stretch = False
            for b in {a['upper_twist'], a['fore_twist']} - {a['upper'], a['fore']}:
                pbn = self.pb[b]
                pbn.lock_ik_x = pbn.lock_ik_y = pbn.lock_ik_z = True
            cr = self.pb[a['hand']].constraints.new('COPY_ROTATION')
            cr.target = tg
            self.t['ik.' + s] = ik
            lg = r['leg.%s' % s]
            ft = empty('%s.foot.%s' % (self.id, s), self.L['ankle.' + s], 0.04, coll, self.root, 'CUBE')
            ft.rotation_quaternion = self.bone(lg['foot']).matrix_local.to_quaternion()
            kp = empty('%s.knee.%s' % (self.id, s), self.L['knee.' + s] + Vector((SIGN[s] * 0.05, -0.6, 0)), 0.03, coll,
                       self.root)
            self.t['foot.' + s], self.t['kpole.' + s] = ft, kp
            ik2 = self.pb[lg['lower_twist']].constraints.new('IK')
            ik2.target, ik2.pole_target = ft, kp
            ik2.chain_count = self._chain(lg['lower_twist'], lg['upper'])
            ik2.use_tail = True
            ik2.use_stretch = False
            for b in {lg['upper_twist'], lg['lower_twist']} - {lg['upper'], lg['lower']}:
                pbn = self.pb[b]
                pbn.lock_ik_x = pbn.lock_ik_y = pbn.lock_ik_z = True
            cr2 = self.pb[lg['foot']].constraints.new('COPY_ROTATION')
            cr2.target = ft
            self.t['ik2.' + s] = ik2
        eye_pos = self.root.matrix_world @ (self.L['eyes'] + Vector((0, -2.0, 0)))
        self.t['look_head'] = empty('%s.look_head' % self.id, eye_pos, 0.06, coll)
        self.t['look_eyes'] = empty('%s.look_eyes' % self.id, eye_pos, 0.04, coll)
        dt = self.pb[r['head']].constraints.new('DAMPED_TRACK')
        dt.target = self.t['look_head']
        ax = r.get('head_forward_axis') or 'auto'
        dt.track_axis = self._axis_toward(r['head'], Vector((0, -1, 0))) if ax == 'auto' else ax
        dt.influence = 0.82
        self.t['head_dt'] = dt
        for e in r['eyes']:
            c = self.pb[e].constraints.new('DAMPED_TRACK')
            c.target = self.t['look_eyes']
            ax = r.get('eye_forward_axis') or 'auto'
            c.track_axis = self._axis_toward(e, Vector((0, -1, 0))) if ax == 'auto' else ax
        for pbn in self.pb:
            pbn.rotation_mode = 'QUATERNION'

    def _chain(self, tip, base):
        """تعدادِ استخوان‌های زنجیرهٔ IK از tip تا base (با هر تعداد استخوانِ پیچش در میان)."""
        n, b = 1, self.bone(tip)
        while b is not None and b.name != base and n < 8:
            b = b.parent
            n += 1
        return n if b is not None and b.name == base else 2

    def _axis_toward(self, bone_name, direction):
        """کدام محورِ محلیِ استخوان در حالتِ استراحت بیشتر رو به direction است ⇐ TRACK_* برای Damped Track."""
        M = self.bone(bone_name).matrix_local.to_3x3()
        best = None
        for i, nm in enumerate('XYZ'):
            col = Vector((M[0][i], M[1][i], M[2][i]))
            for sign, pre in ((1, 'TRACK_'), (-1, 'TRACK_NEGATIVE_')):
                d = col.dot(direction) * sign
                if best is None or d > best[0]:
                    best = (d, pre + nm)
        return best[1]

    def eyes_point(self):
        """میانهٔ چشم‌ها در فضای جهان (بعد از ارزیابیِ ژست)."""
        mw = self.arm.matrix_world
        r = self.roles
        if r['eyes']:
            e = [mw @ self.pb[x].head for x in r['eyes']]
            return (e[0] + e[1]) / 2
        hb = self.pb[r['head']]
        rest = self.bone(r['head'])
        off = rest.matrix_local.inverted() @ self.L['eyes']
        return mw @ (hb.matrix @ off)

    def _world(self, bone_name, tail=False):
        pb = self.pb[bone_name]
        return self.arm.matrix_world @ (pb.tail if tail else pb.head)

    def _calibrate(self):
        """زاویهٔ قطبِ IK و جهتِ خمِ انگشت‌ها را خودکار از روی اسکلت پیدا می‌کند (برای هر اسکلت درست است)."""
        vl = bpy.context.view_layer
        r = self.roles
        for s in SIDES:
            self.t['hand.' + s].location = self.neutral_pos(s)
            self.t['hand.' + s].rotation_quaternion = self.neutral_rot(s)
        for key, joint, pole in [('ik.%s' % s, r['arm.%s' % s]['fore'], 'pole.%s' % s) for s in SIDES] + \
                                [('ik2.%s' % s, r['leg.%s' % s]['lower'], 'kpole.%s' % s) for s in SIDES]:
            c = self.t[key]
            best = None
            for deg in range(-180, 180, 10):
                c.pole_angle = math.radians(deg)
                vl.update()
                d = (self._world(joint) - self.t[pole].matrix_world.translation).length
                if best is None or d < best[0]:
                    best = (d, deg)
            for deg in range(best[1] - 9, best[1] + 10, 3):
                c.pole_angle = math.radians(deg)
                vl.update()
                d = (self._world(joint) - self.t[pole].matrix_world.translation).length
                if d < best[0]:
                    best = (d, deg)
            c.pole_angle = math.radians(best[1])
        vl.update()
        # خمِ انگشت: محوری که نوکِ انگشت را به سمتِ کفِ دست می‌برد
        self.curl = {}
        for s in SIDES:
            fm = r['fingers.%s' % s]
            p_world = (self.root.matrix_world.to_3x3() @ self.hand_rest[s]['p0']).normalized()
            palm_pt = self.arm.matrix_world @ (self.L['palm_center.' + s] + self.hand_rest[s]['p0'] * 0.03)
            self.curl[s] = {}
            for fname in (FINGERS if fm else ()):
                chain = fm[fname]
                best = None
                for axis in ((1, 0, 0), (0, 0, 1)):
                    for sign in (1, -1):
                        tip0 = self._world(chain[-1], True)
                        for b in chain:
                            self.pb[b].rotation_quaternion = Quaternion(axis, 0.35 * sign)
                        vl.update()
                        tip1 = self._world(chain[-1], True)
                        for b in chain:
                            self.pb[b].rotation_quaternion = Quaternion()
                        vl.update()
                        score = (tip1 - tip0).dot(p_world) + ((tip0 - palm_pt).length - (tip1 - palm_pt).length)
                        if fname != 'thumb' and axis != (1, 0, 0):
                            score -= 1.0     # چهار انگشت فقط روی محورِ X خم می‌شوند
                        if best is None or score > best[0]:
                            best = (score, axis, sign)
                self.curl[s][fname] = (Vector(best[1]), best[2])
        log('rig', self.id, 'poles', [round(math.degrees(self.t[k].pole_angle)) for k in ('ik.R', 'ik.L', 'ik2.R', 'ik2.L')],
            'curl', {s: {f: (tuple(v[0]), v[1]) for f, v in self.curl[s].items()} for s in SIDES})

    # ───────── API ِ حرکت‌ها (همه در فضای بازیگر، زمان = فریم)
    def key_hand(self, s, frame, pos=None, rot=None, mode='auto'):
        if pos is not None:
            self.ch['hand.' + s].key(frame, Vector(pos)[:], mode)
        if rot is not None:
            self.ch['handrot.' + s].key(frame, rot, mode)

    def key_fingers(self, s, frame, preset='relaxed', mode='auto', **override):
        vals = dict(FINGER_PRESETS.get(preset, FINGER_PRESETS['relaxed']) if isinstance(preset, str) else preset)
        vals.update(override)
        self.ch['fingers.' + s].key(frame, [vals[f] for f in FINGERS], mode)

    def key_spine(self, frame, pitch=0.0, yaw=0.0, roll=0.0, mode='auto'):
        self.ch['spine'].key(frame, (pitch, yaw, roll), mode)

    def key_hips(self, frame, offset=(0, 0, 0), yaw=0.0, mode='auto'):
        self.ch['hips'].key(frame, (offset[0], offset[1], offset[2], yaw), mode)

    def key_head(self, frame, tilt=None, offset=None, follow=None, mode='auto'):
        if tilt is not None:
            self.ch['head_tilt'].key(frame, tilt, mode)
        if offset is not None:
            self.ch['head_off'].key(frame, offset, mode)
        if follow is not None:
            self.ch['head_follow'].key(frame, follow, mode)

    def key_clav(self, s, frame, deg, mode='auto'):
        self.ch['clav.' + s].key(frame, deg, mode)

    def key_noise(self, s, frame, amount):
        self.ch['noise.' + s].key(frame, amount, 'flat')

    def hand_state(self, s, frame):
        """موقعیت و چرخشِ هدفِ دست در یک فریم (از روی کلیدهای تا این‌جا)."""
        return Vector(self.ch['hand.' + s].value(frame)), self.ch['handrot.' + s].value(frame)

    # ───────── لایه‌های افزودنی (زندگی)
    def _speaking(self):
        return [tuple(x) for x in (self.ctx.c.get('face', {}).get(self.id, {}) or {}).get('speaking', [])]

    def _breath(self, frame):
        """نفس: دورهٔ ۳٫۶ تا ۴٫۶ ثانیه (نه کاملاً منظم) + دمِ کوتاه پیش از شروعِ هر جملهٔ گفتار."""
        fps = self.ctx.fps
        t = frame / fps
        sd = self.ctx.seed(self.id)
        phase = 2 * math.pi * (t / 4.1 + 0.06 * anim.noise1(t * 0.13, sd + 11)) + sd
        b = math.sin(phase)
        for a, _ in self._speaking():
            ta = a / fps
            if ta - 0.55 <= t <= ta + 0.2:
                u = anim.smootherstep((t - (ta - 0.55)) / 0.35) * (1 - anim.smootherstep((t - ta) / 0.2))
                b = b * (1 - u) + 1.25 * u
        return b

    def _sway(self, frame):
        t = frame / self.ctx.fps
        sd = self.ctx.seed(self.id)
        return (anim.noise1(t * 0.35, sd) * 0.006, anim.noise1(t * 0.3, sd + 3) * 0.005, anim.noise1(t * 0.22, sd + 5) * 1.2)

    # ───────── ثبت در Blender
    def realize(self, f0, f1):
        """همهٔ کانال‌ها ⇐ کلیدهای فریم‌به‌فریم روی هدف‌ها و استخوان‌ها.

        روی کلیدهای معنایی چند لایهٔ «زنده» می‌نشیند تا حرکت رباتی نباشد:
          - فنرِ مرتبهٔ دو روی جای دست (تأخیرِ کوچک، ادامهٔ حرکت، نشستنِ نرم) — هنگامِ تماس با محصول خاموش
          - چرخشِ مچ کمی دیرتر از جای دست؛ انگشت‌ها دیرتر از مچ و هنگامِ حرکتِ تند کمی رهاتر
          - قطبِ آرنج فریم‌به‌فریم از جای دست (آرنجِ طبیعی به‌جای بیرون‌زده)
          - تنه با دست همراه می‌شود: دستِ بالا ⇐ شانه بالا؛ دستِ جلو ⇐ چرخشِ تنه به همان سو
          - جابه‌جاییِ وزن (کنتراپوستو)، زانوی نرم، نفس با دمِ پیش از گفتار"""
        frames = anim.frames_range(f0, f1)
        r = self.roles
        fps = self.ctx.fps
        sd = self.ctx.seed(self.id)
        L = self.L
        hand_locs = {}
        bone_q = {}              # نامِ استخوان ⇐ کواترنیونِ محلی برای هر فریم (بعد از لایهٔ کلیپ نوشته می‌شود)
        for s in SIDES:
            sg = SIGN[s]
            pos_ch, rot_ch, nz = self.ch['hand.' + s], self.ch['handrot.' + s], self.ch['noise.' + s]
            exact = [Vector(pos_ch.value(f)) for f in frames]
            gs = [max(0.0, min(1.0, nz.value(f)[0])) for f in frames]
            spring = anim.spring_follow(exact, fps, freq=3.1, zeta=0.72)
            q_exact, prev = [], None
            for f in frames:
                q = rot_ch.value(f)
                if prev is not None and prev.dot(q) < 0:
                    q = -q
                q_exact.append(q)
                prev = q
            q_lag = anim.quat_lag(q_exact, fps, 0.055)
            locs, rots, prev = [], [], None
            for i, f in enumerate(frames):
                g = gs[i]
                p = exact[i].lerp(spring[i], g)
                t = f / fps
                p += Vector((anim.noise1(t * 0.9, sd + (1 if s == 'R' else 2)) * 0.005,
                             anim.noise1(t * 0.8, sd + 7) * 0.005,
                             anim.noise1(t * 0.7, sd + 9) * 0.006 + self._breath(f) * 0.002)) * g
                # دست هرگز تا تهِ طولِ بازو کشیده نشود (IK در بازوی کاملاً صاف آرنج را ناگهان برمی‌گرداند)
                sh = L['shoulder.' + s]
                reach = (p - sh).length
                lim_r = 0.965 * L['arm_len.' + s]
                if reach > lim_r and g > 0:        # فقط دستِ آزاد؛ هنگامِ تماس (g=0) تنه خم شده و IK خودش می‌رسد
                    p = p.lerp(sh + (p - sh) * (lim_r / reach), g)
                q = q_exact[i].slerp(q_lag[i], g)
                # ریزچرخشِ مچ (دستِ زنده هیچ‌وقت کاملاً ثابت نیست)
                wob = Quaternion(Vector((anim.noise1(t * 0.6, sd + 21), anim.noise1(t * 0.5, sd + 23),
                                         anim.noise1(t * 0.55, sd + 25))).normalized(),
                                 math.radians(1.6) * g)
                q = q @ wob
                if prev is not None and prev.dot(q) < 0:
                    q = -q
                # محدودکنندهٔ سرعت: مچِ انسان بیش از ~۳۶۰ درجه بر ثانیه نمی‌چرخد و دست بیش از ~۲ متر بر ثانیه جابه‌جا نمی‌شود
                if prev is not None:
                    ang = prev.rotation_difference(q).angle
                    lim = math.radians(360.0) / fps
                    if ang > lim:
                        q = prev.slerp(q, lim / ang)
                    d = p - Vector(locs[-1])
                    lim_p = 2.0 / fps
                    if d.length > lim_p:
                        p = Vector(locs[-1]) + d * (lim_p / d.length)
                prev = q
                locs.append(p[:])
                rots.append(q[:])
            hand_locs[s] = [Vector(x) for x in locs]
            anim.bulk_keys(self.t['hand.' + s], 'location', frames, locs)
            anim.bulk_keys(self.t['hand.' + s], 'rotation_quaternion', frames, rots)
            # قطبِ آرنج از جای واقعیِ دست
            ech = self.ch['elbow.' + s]
            anim.bulk_keys(self.t['pole.' + s], 'location', frames,
                           [self.pole_for(s, hand_locs[s][i], ech.value(f)[0])[:] for i, f in enumerate(frames)])
            # انگشت‌ها: دیرتر از دست + رهاتر هنگامِ حرکتِ تند + ریزتغییرِ جدا برای هر انگشت
            fch = self.ch['fingers.' + s]
            raw = [fch.value(f) for f in frames]
            lagged = anim.lag(raw, fps, 0.075)
            relaxed = [FINGER_PRESETS['relaxed'][fn] for fn in FINGERS]
            fm = r['fingers.%s' % s]
            per_bone = {}
            if not fm:
                continue
            for i, f in enumerate(frames):
                g = gs[i]
                spd = (hand_locs[s][i] - hand_locs[s][i - 1]).length * fps if i else 0.0
                drag = min(1.0, spd / 1.4) * 0.35 * g
                t = f / fps
                vals = []
                for fi, fname in enumerate(FINGERS):
                    v = raw[i][fi] * (1 - g) + lagged[i][fi] * g   # هنگامِ گرفتن دقیق، در بقیه با تأخیر
                    v = v + (relaxed[fi] - v) * drag
                    v += anim.noise1(t * 0.45, sd + 31 + fi * 3) * 0.025 * g
                    vals.append(v)
                for fi, fname in enumerate(FINGERS):
                    axis, sign = self.curl[s][fname]
                    c = vals[fi]
                    for bi, b in enumerate(fm[fname]):
                        ang = c * CURL_MAX[bi] * sign * (0.8 if fname == 'thumb' else 1.0)
                        per_bone.setdefault(b, []).append(Quaternion(axis, ang)[:])
            bone_q.update(per_bone)
        # همراهیِ تنه با دست‌ها
        couple = []
        for i, f in enumerate(frames):
            raise_ = {}
            fwd = {}
            for s in SIDES:
                h = hand_locs[s][i]
                S = L['shoulder.' + s]
                raise_[s] = anim.smootherstep((h.z - (S.z - 0.14)) / 0.32)
                fwd[s] = anim.smootherstep((S.y - h.y - 0.2) / 0.3)
            couple.append((raise_, fwd))
        stance = anim.stance_series(frames, fps, sd)
        # ستونِ فقرات + نفس + وزن
        spine = r['spine']
        wts = r.get('spine_weights') or [1.0 / len(spine)] * len(spine)
        sp_q = {b: [] for b in spine}
        clav = {s: [] for s in SIDES}
        hips_loc, hips_rot, tilt_q = [], [], []
        sw_bones = {b: self.bone(b).matrix_local.to_3x3() for b in spine}
        hip_m = self.bone(r['hips']).matrix_local.to_3x3()
        head_m = self.bone(r['head']).matrix_local.to_3x3()
        clav_m = {s: self.bone(r['arm.%s' % s]['clavicle']).matrix_local.to_3x3() for s in SIDES
                  if r['arm.%s' % s]['clavicle']}
        for i, f in enumerate(frames):
            raise_, fwd = couple[i]
            w = stance[i]
            pitch, yaw, roll = self.ch['spine'].value(f)
            br = self._breath(f)
            pitch += br * 0.6
            yaw += 4.5 * (fwd['R'] - fwd['L'])
            roll += 1.6 * (raise_['L'] - raise_['R']) - 1.5 * w     # تنه کمی خلافِ دستِ بالا و خلافِ کجیِ لگن
            sx, sy, syaw = self._sway(f)
            for b, wt in zip(spine, wts):
                Rw = (Euler((math.radians(pitch * wt), math.radians(-roll * wt + sx * 40 * wt), math.radians(yaw * wt)), 'ZXY')
                      .to_matrix())
                M = sw_bones[b]
                sp_q[b].append((M.transposed() @ Rw @ M).to_quaternion()[:])
            ox, oy, oz, hyaw = self.ch['hips'].value(f)
            # لگن روی پای تکیه‌گاه: کمی به همان سو، سمتِ پای آزاد پایین‌تر، زانوها کمی نرم
            off = Vector((ox + sx + 0.017 * w, oy + sy, oz + br * 0.0015 - 0.005 - 0.004 * abs(w)))
            hips_loc.append((hip_m.transposed() @ off)[:])
            Rh = Euler((0, math.radians(-2.2 * w), math.radians(hyaw + syaw + 1.2 * w)), 'XYZ').to_matrix()
            hips_rot.append((hip_m.transposed() @ Rh @ hip_m).to_quaternion()[:])
            for s in clav_m:
                deg = self.ch['clav.' + s].value(f)[0] + br * 0.8 + 10.0 * raise_[s] + 2.0 * fwd[s]
                ang = math.radians(deg) * (1 if s == 'R' else -1)
                Rc = Matrix.Rotation(ang, 3, 'Y')
                clav[s].append((clav_m[s].transposed() @ Rc @ clav_m[s]).to_quaternion()[:])
            tl = self.ch['head_tilt'].value(f)[0] + 0.8 * w
            Rt = Matrix.Rotation(math.radians(-tl), 3, 'Y')
            tilt_q.append((head_m.transposed() @ Rt @ head_m).to_quaternion()[:])
        bone_q.update(sp_q)
        bone_q[r['head']] = tilt_q
        bone_q[r['hips']] = hips_rot
        for s in clav_m:
            bone_q[r['arm.%s' % s]['clavicle']] = clav[s]
        feet = self._clip_layers(frames, bone_q, hips_loc, hip_m)
        for b, qs in bone_q.items():
            anim.bulk_keys(self.arm, 'pose.bones["%s"].rotation_quaternion' % b, frames, qs)
        anim.bulk_keys(self.arm, 'pose.bones["%s"].location' % r['hips'], frames, hips_loc)
        for s, (fl, fr_) in feet.items():
            anim.bulk_keys(self.t['foot.' + s], 'location', frames, fl)
            anim.bulk_keys(self.t['foot.' + s], 'rotation_quaternion', frames, fr_)
        anim.bulk_keys(self.t['head_dt'].id_data, 'pose.bones["%s"].constraints["%s"].influence' % (r['head'], self.t['head_dt'].name),
                       frames, [self.ch['head_follow'].value(f)[0] for f in frames])

    def _clip_layers(self, frames, bone_q, hips_loc, hip_m):
        """لایهٔ کلیپ‌های mocap: چرخشِ محلیِ استخوان‌ها (ستون، گردن، ترقوه، انگشت‌ها، لگن) با وزنِ محوشونده
        روی خروجیِ رویه‌ای می‌نشیند؛ جای پاها (اگر کلیپ پا دارد) به هدف‌های IK ِ پا می‌رود."""
        feet = {}
        if not self.clips:
            return feet
        idx = {f: i for i, f in enumerate(frames)}
        for cl in self.clips:
            for f in range(int(cl['f0']), int(cl['f1']) + 1):
                i = idx.get(f)
                if i is None:
                    continue
                w = cl['weight'](f)
                if w <= 0:
                    continue
                for b, ser in cl['bones'].items():
                    q = ser.get(f)
                    if q is None:
                        continue
                    base = bone_q.get(b)
                    if base is None:
                        base = bone_q[b] = [(1.0, 0.0, 0.0, 0.0)] * len(frames)
                    q0 = Quaternion(base[i])
                    q1 = Quaternion(q)
                    if q0.dot(q1) < 0:
                        q1 = -q1
                    base[i] = q0.slerp(q1, w)[:]
                off = cl.get('hips_off', {}).get(f)
                if off is not None:
                    cur = Vector(hips_loc[i])
                    hips_loc[i] = cur.lerp(hip_m.transposed() @ Vector(off) + cur, w)[:]
                for s, ser in (cl.get('feet') or {}).items():
                    if s not in feet:
                        rest_l = self.L['ankle.' + s]
                        rest_q = self.bone(self.roles['leg.%s' % s]['foot']).matrix_local.to_quaternion()
                        feet[s] = ([rest_l[:]] * len(frames), [rest_q[:]] * len(frames))
                    v = ser.get(f)
                    if v is None:
                        continue
                    loc, q = v
                    fl, fq = feet[s]
                    fl[i] = Vector(fl[i]).lerp(Vector(loc), w)[:]
                    q0 = Quaternion(fq[i])
                    q1 = Quaternion(q)
                    if q0.dot(q1) < 0:
                        q1 = -q1
                    fq[i] = q0.slerp(q1, w)[:]
        for s in list(feet):
            fl, fq = feet[s]
            feet[s] = ([tuple(x) for x in fl], [tuple(x) for x in fq])
        return feet

    # ───────── اندازه‌گیری
    def wrist_matrix_world(self, s):
        pb = self.pb[self.roles['arm.%s' % s]['hand']]
        return self.arm.matrix_world @ pb.matrix

    def foot_world(self, s):
        return self._world(self.roles['leg.%s' % s]['foot'])

    def head_world(self):
        return self._world(self.roles['head'])

    def point_world(self, local):
        return self.root.matrix_world @ Vector(local)

    def world_to_actor(self, p):
        return self.root.matrix_world.inverted() @ Vector(p)

    def rot_world_to_actor(self, q):
        return self.root.matrix_world.to_quaternion().inverted() @ q

    def hide_meshes(self, hide=True):
        for o in self.meshes:
            o.hide_viewport = hide
