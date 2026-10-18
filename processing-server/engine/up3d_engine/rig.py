"""ریگِ کنترلیِ بازیگر.

روی اسکلتِ کاراکتر (هر اسکلتی که نقشهٔ نقش داشته باشد) یک لایهٔ کنترلِ معنایی می‌سازد:
  - هدفِ IK برای مچِ هر دست (موقعیت + جهت) و هر پا (پاها روی زمین می‌مانند)
  - هدفِ نگاه برای سر (Damped Track) و چشم‌ها (تماسِ چشمی با دوربین)
  - کانال‌های نرم: ستونِ فقرات، لگن، سرشانه، کجیِ سر، خمِ انگشت‌ها
همهٔ مختصات «فضای بازیگر» است: مبدأ = جای ایستادن روی زمین، رو به -Y، راستِ بازیگر = -X.
اندازه‌ها از خودِ اسکلت خوانده می‌شود (قد، طولِ دست…) پس حرکت‌ها برای هر اندام درست می‌نشینند.
"""
import math

import bpy
from mathutils import Euler, Matrix, Quaternion, Vector

from . import anim
from .anim import Channel, QuatChannel
from .util import basis, empty, log

SIDES = ('R', 'L')
SIGN = {'R': -1.0, 'L': 1.0}
FINGERS = ('thumb', 'index', 'middle', 'ring', 'pinky')
FINGER_PRESETS = {
    'relaxed': {'thumb': 0.15, 'index': 0.18, 'middle': 0.24, 'ring': 0.3, 'pinky': 0.34},
    'open': {'thumb': 0.0, 'index': 0.02, 'middle': 0.03, 'ring': 0.04, 'pinky': 0.05},
    'grip': {'thumb': 0.55, 'index': 0.62, 'middle': 0.68, 'ring': 0.72, 'pinky': 0.75},
    'pinch': {'thumb': 0.45, 'index': 0.5, 'middle': 0.42, 'ring': 0.5, 'pinky': 0.55},
    'point': {'thumb': 0.5, 'index': 0.0, 'middle': 0.85, 'ring': 0.9, 'pinky': 0.9},
    'fist': {'thumb': 0.7, 'index': 0.95, 'middle': 0.95, 'ring': 0.95, 'pinky': 0.95},
    'thumbs_up': {'thumb': -0.1, 'index': 0.95, 'middle': 0.95, 'ring': 0.95, 'pinky': 0.95},
    'spread': {'thumb': -0.05, 'index': 0.0, 'middle': 0.0, 'ring': 0.02, 'pinky': 0.03},
}
CURL_MAX = (0.9, 1.4, 1.0)      # بیشترین خمِ هر بندِ انگشت (رادیان) در curl=1


class ActorRig:
    def __init__(self, ctx, actor, built):
        self.ctx = ctx
        self.id = actor['id']
        self.arm = built['armature']
        self.body = built['body']
        self.meshes = built['meshes']
        self.face_meshes = built['face_meshes']
        self.map = built['rigmap']
        self.roles = self.map['roles']
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
            L['palm_center.' + s] = (B(f['middle'][0]).head_local + B(a['hand']).head_local) * 0.5
        L['hips'] = B(r['hips']).head_local.copy()
        L['chest'] = B(r['spine'][-1]).head_local.copy()
        L['neck'] = B(r['neck'][0]).head_local.copy()
        L['head'] = B(r['head']).head_local.copy()
        L['top'] = B(r['head']).tail_local.copy()
        eyes = [B(e).head_local for e in r['eyes']]
        L['eyes'] = (eyes[0] + eyes[1]) * 0.5
        L['height'] = L['top'].z + 0.04
        L['face'] = L['eyes'] + Vector((0, -0.02, -0.03))
        self.L = L
        # پایهٔ دستِ در حالتِ استراحت (برای تبدیلِ «جهتِ انگشت/کفِ دست» به چرخشِ مچ)
        self.hand_rest = {}
        for s in SIDES:
            a, f = r['arm.%s' % s], r['fingers.%s' % s]
            h = B(a['hand']).head_local
            f0 = (B(f['middle'][0]).head_local - h).normalized()
            i0 = (B(f['index'][0]).head_local - B(f['pinky'][0]).head_local).normalized()
            p0 = i0.cross(f0) if s == 'R' else f0.cross(i0)
            Rw = B(a['hand']).matrix_local.to_3x3()
            B0 = basis(f0, p0)
            pc = L['palm_center.' + s] + (p0 - f0 * p0.dot(f0)).normalized() * 0.012
            self.hand_rest[s] = {'B0': B0, 'Rw': Rw, 'palm_off': Rw.transposed() @ (pc - h), 'p0': p0, 'f0': f0}

    # ───────── وضعیتِ پایه
    def neutral_pos(self, s):
        L = self.L
        return L['shoulder.' + s] + Vector((SIGN[s] * 0.035, -0.045, -0.9 * L['arm_len.' + s]))

    def neutral_rot(self, s):
        return self.hand_rot(s, Vector((0, -0.15, -1)), Vector((-SIGN[s], 0.1, 0)))

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
            pole = empty('%s.elbow.%s' % (self.id, s), self.L['elbow.' + s] + Vector((SIGN[s] * 0.4, 0.3, -0.3)),
                         0.03, coll, self.root)
            self.t['hand.' + s], self.t['pole.' + s] = tg, pole
            ik = self.pb[a['fore_twist']].constraints.new('IK')
            ik.target, ik.pole_target = tg, pole
            ik.chain_count = 4
            ik.use_tail = True
            ik.use_stretch = False
            for b in (a['upper_twist'], a['fore_twist']):
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
            ik2.chain_count = 4
            ik2.use_tail = True
            ik2.use_stretch = False
            for b in (lg['upper_twist'], lg['lower_twist']):
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
        dt.track_axis = r.get('head_forward_axis', 'TRACK_Z')
        dt.influence = 0.82
        self.t['head_dt'] = dt
        for e in r['eyes']:
            c = self.pb[e].constraints.new('DAMPED_TRACK')
            c.target = self.t['look_eyes']
            c.track_axis = r.get('eye_forward_axis', 'TRACK_Y')
        for pbn in self.pb:
            pbn.rotation_mode = 'QUATERNION'

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
            for fname in FINGERS:
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
    def _breath(self, frame):
        t = frame / self.ctx.fps
        b = math.sin(t * 2 * math.pi / 4.2 + self.ctx.seed(self.id))
        return b

    def _sway(self, frame):
        t = frame / self.ctx.fps
        sd = self.ctx.seed(self.id)
        return (anim.noise1(t * 0.35, sd) * 0.012, anim.noise1(t * 0.3, sd + 3) * 0.006, anim.noise1(t * 0.22, sd + 5) * 1.5)

    # ───────── ثبت در Blender
    def realize(self, f0, f1):
        """همهٔ کانال‌ها ⇐ کلیدهای فریم‌به‌فریم روی هدف‌ها و استخوان‌ها."""
        frames = anim.frames_range(f0, f1)
        r = self.roles
        fps = self.ctx.fps
        sd = self.ctx.seed(self.id)
        for s in SIDES:
            pos_ch, rot_ch, nz = self.ch['hand.' + s], self.ch['handrot.' + s], self.ch['noise.' + s]
            locs, rots, prev = [], [], None
            for f in frames:
                p = Vector(pos_ch.value(f))
                g = max(0.0, min(1.0, nz.value(f)[0]))
                t = f / fps
                p += Vector((anim.noise1(t * 0.9, sd + (1 if s == 'R' else 2)) * 0.004,
                             anim.noise1(t * 0.8, sd + 7) * 0.004,
                             anim.noise1(t * 0.7, sd + 9) * 0.005 + self._breath(f) * 0.002)) * g
                q = rot_ch.value(f)
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
            anim.bulk_keys(self.t['hand.' + s], 'location', frames, locs)
            anim.bulk_keys(self.t['hand.' + s], 'rotation_quaternion', frames, rots)
            # انگشت‌ها
            fch = self.ch['fingers.' + s]
            fm = r['fingers.%s' % s]
            per_bone = {}
            for f in frames:
                vals = fch.value(f)
                for fi, fname in enumerate(FINGERS):
                    axis, sign = self.curl[s][fname]
                    c = vals[fi]
                    for bi, b in enumerate(fm[fname]):
                        ang = c * CURL_MAX[bi] * sign * (0.8 if fname == 'thumb' else 1.0)
                        per_bone.setdefault(b, []).append(Quaternion(axis, ang)[:])
            for b, qs in per_bone.items():
                anim.bulk_keys(self.arm, 'pose.bones["%s"].rotation_quaternion' % b, frames, qs)
        # ستونِ فقرات + نفس
        spine = r['spine']
        wts = r.get('spine_weights') or [1.0 / len(spine)] * len(spine)
        sp_q = {b: [] for b in spine}
        clav = {s: [] for s in SIDES}
        hips_loc, hips_rot, tilt_q = [], [], []
        sw_bones = {b: self.bone(b).matrix_local.to_3x3() for b in spine}
        hip_m = self.bone(r['hips']).matrix_local.to_3x3()
        head_m = self.bone(r['head']).matrix_local.to_3x3()
        clav_m = {s: self.bone(r['arm.%s' % s]['clavicle']).matrix_local.to_3x3() for s in SIDES}
        for f in frames:
            pitch, yaw, roll = self.ch['spine'].value(f)
            br = self._breath(f)
            pitch += br * 0.6
            sx, sy, syaw = self._sway(f)
            for b, w in zip(spine, wts):
                Rw = (Euler((math.radians(pitch * w), math.radians(-roll * w + sx * 40 * w), math.radians(yaw * w)), 'ZXY')
                      .to_matrix())
                M = sw_bones[b]
                sp_q[b].append((M.transposed() @ Rw @ M).to_quaternion()[:])
            ox, oy, oz, hyaw = self.ch['hips'].value(f)
            off = Vector((ox + sx, oy + sy, oz + br * 0.0015))
            hips_loc.append((hip_m.transposed() @ off)[:])
            Rh = Euler((0, 0, math.radians(hyaw + syaw)), 'XYZ').to_matrix()
            hips_rot.append((hip_m.transposed() @ Rh @ hip_m).to_quaternion()[:])
            for s in SIDES:
                deg = self.ch['clav.' + s].value(f)[0] + br * 0.8
                ang = math.radians(deg) * (1 if s == 'R' else -1)
                Rc = Matrix.Rotation(ang, 3, 'Y')
                clav[s].append((clav_m[s].transposed() @ Rc @ clav_m[s]).to_quaternion()[:])
            tl = self.ch['head_tilt'].value(f)[0]
            Rt = Matrix.Rotation(math.radians(-tl), 3, 'Y')
            tilt_q.append((head_m.transposed() @ Rt @ head_m).to_quaternion()[:])
        for b in spine:
            anim.bulk_keys(self.arm, 'pose.bones["%s"].rotation_quaternion' % b, frames, sp_q[b])
        anim.bulk_keys(self.arm, 'pose.bones["%s"].location' % r['hips'], frames, hips_loc)
        anim.bulk_keys(self.arm, 'pose.bones["%s"].rotation_quaternion' % r['hips'], frames, hips_rot)
        anim.bulk_keys(self.arm, 'pose.bones["%s"].rotation_quaternion' % r['head'], frames, tilt_q)
        for s in SIDES:
            anim.bulk_keys(self.arm, 'pose.bones["%s"].rotation_quaternion' % r['arm.%s' % s]['clavicle'], frames, clav[s])
        anim.bulk_keys(self.t['head_dt'].id_data, 'pose.bones["%s"].constraints["%s"].influence' % (r['head'], self.t['head_dt'].name),
                       frames, [self.ch['head_follow'].value(f)[0] for f in frames])

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
