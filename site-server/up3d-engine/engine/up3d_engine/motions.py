"""کتابخانهٔ حرکتِ رویه‌ای.

هر حرکت یک تابع است: (ctx, rig, act) ⇐ کلیدهای معنایی روی کانال‌های ریگ.
اندازه‌ها از «نشانه‌های بدن» (شانه، سینه، طولِ دست…) می‌آید، پس روی هر قد و اندامی درست است.
هر حرکت از «وضعیتِ فعلی» شروع می‌کند (anchor) تا گذارها بی‌پرش باشند.

حرکتِ تازه = یک تابعِ تازه با @motion('id') + پوشهٔ assets/motions/<id>/manifest.json.
منبعِ «کلیپ» (Mocap/BVH) در clips.py همین قرارداد را دارد.
"""
import math

from mathutils import Quaternion, Vector

from . import products as P
from .rig import FINGER_PRESETS, SIDES, SIGN

LIBRARY = {}


def motion(name):
    def deco(fn):
        LIBRARY[name] = fn
        return fn
    return deco


class M:
    """کمکِ زمان‌بندیِ یک حرکت."""

    def __init__(self, ctx, rig, act):
        self.ctx, self.rig, self.act = ctx, rig, act
        self.f0, self.f1 = act['f0'], act['f1']
        self.p = act['params']
        self.fps = ctx.fps

    def F(self, u):
        return self.f0 + (self.f1 - self.f0) * u

    def secs(self):
        return (self.f1 - self.f0) / self.fps

    def anchor(self, *names):
        """کلیدِ «همین الان» در شروعِ حرکت، تا گذار از حالتِ قبلی نرم باشد."""
        f = self.f0
        for n in names:
            ch = self.rig.ch[n]
            if hasattr(ch, 'set_ref'):
                ch.key(f, ch.value(f))
            else:
                ch.key(f, ch.value(f))

    def anchor_side(self, s):
        self.anchor('hand.' + s, 'handrot.' + s, 'fingers.' + s)

    def free(self, s):
        return self.ctx.holding(self.rig.id, s) is None

    def pick_side(self, prefer='R'):
        hand = self.p.get('hand') if self.p.get('hand') in SIDES else prefer
        if self.free(hand):
            return hand
        other = 'L' if hand == 'R' else 'R'
        return other if self.free(other) else hand

    def holding_side(self, pid):
        for s in SIDES:
            if self.ctx.holding(self.rig.id, s) == pid:
                return s
        return None


def _neutral(rig, s, f, mode='auto'):
    rig.key_hand(s, f, rig.neutral_pos(s), rig.neutral_rot(s), mode)
    rig.key_fingers(s, f, 'relaxed', mode)


def _hold_pose(m, s, pid, f, point=None, yaw=None, tilt=0.0, roll=0.0, mode='auto'):
    """محصولِ در دست را به یک ژست ببر (مچ از روی تبدیلِ ثابتِ گرفتن حساب می‌شود)."""
    rig = m.rig
    prod = m.ctx.products[pid]
    L = rig.L
    sg = SIGN[s]
    if point is None:
        point = Vector((sg * 0.12, -0.27, L['chest'].z - 0.11))
    if yaw is None:
        yaw = -sg * 8.0
    T = P.product_pose(point, yaw, tilt, roll, prod.dims[2] * prod.grasp.get('height', 0.4))
    loc, rot = P.wrist_for_product(rig, m.ctx.hold_G[pid], T)
    rig.key_hand(s, f, loc, rot, mode)


# ───────────────────────── پایه

@motion('idle')
def idle(ctx, rig, act):
    """ایستادنِ زنده: دست‌ها آرام به حالتِ رها می‌روند (نه هم‌زمان)، تنه صاف؛ نفس و جابه‌جاییِ وزن
    و ریزحرکتِ دست را لایه‌های rig.realize اضافه می‌کنند."""
    m = M(ctx, rig, act)
    lag = {'R': 0.0, 'L': 0.12}
    for s in SIDES:
        if m.free(s):
            m.anchor_side(s)
            u = min(1.0, (0.7 + lag[s]) / max(0.7, m.secs()))
            _neutral(rig, s, m.F(u))
            _neutral(rig, s, m.F(1.0), 'flat')
    m.anchor('spine')
    rig.key_spine(m.F(min(1.0, 0.45)), 0.0, 0.0, 0.0)


@motion('talk')
def talk(ctx, rig, act):
    """ژستِ هنگامِ حرف‌زدن، هم‌زمان با تکیه‌های صدا.

    دست‌ها به «حالتِ آماده» جلوی شکم می‌آیند (آرنج کنارِ بدن، کفِ دست‌ها رو به هم)، و روی هر تکیه یکی از
    سه ژست: بازکردنِ یک دست (کفِ دست رو به بالا)، بازکردنِ دو دست، یا ژستِ ظریفِ «نیشگون» جلوی سینه.
    هر ژست پیش‌حرکت (کمی عقب)، ضربه، ماندنِ کوتاه با لغزش و برگشت دارد؛ اندازه و زمان از دانهٔ تصادفیِ همین کنش."""
    m = M(ctx, rig, act)
    L = rig.L
    free = [s for s in SIDES if m.free(s)]
    m.anchor('spine', 'head_tilt', 'clav.R', 'clav.L')
    if not free:
        return
    for s in free:
        m.anchor_side(s)
        m.anchor('elbow.' + s)
    fps = m.fps
    peaks = ctx.energy_peaks(rig.id, m.f0 + 0.35 * fps, m.f1 - 0.4 * fps, min_gap=0.6 * fps)
    if not peaks:
        n = max(1, int(m.secs() / 1.15))
        peaks = [m.F((i + 0.65) / (n + 0.45)) for i in range(n)]
    seed = ctx.seed(act['id'])

    def ready(s, k=0.0):
        sg = SIGN[s]
        S = L['shoulder.' + s]
        pos = S + Vector((-sg * 0.06 + sg * 0.015 * k, -0.24 - 0.01 * k, -0.38 + 0.02 * k))
        rot = rig.hand_rot(s, Vector((-sg * 0.45, -1, 0.08)), Vector((-sg * 0.8, -0.1, 0.5)))
        return pos, rot

    ready_f = min(m.F(0.18), m.f0 + 0.5 * fps)
    for i, s in enumerate(free):
        p, q = ready(s)
        rig.key_hand(s, ready_f + i * 2, p, q)
        rig.key_fingers(s, ready_f + i * 2, 'relaxed', index=0.15, middle=0.2)
        rig.ch['elbow.' + s].key(ready_f, 0.15)
    last = {s: ready_f for s in free}
    for i, fb in enumerate(peaks):
        r = (math.sin(seed * 12.9898 + i * 78.233) * 43758.5453) % 1.0      # تکرارپذیر، بی‌random
        amp = 0.65 + 0.35 * ((i * 7 + int(seed * 13)) % 5) / 4.0
        kind = 'both' if len(free) == 2 and r < 0.28 else ('pinch' if r > 0.8 else 'one')
        sides = free if kind == 'both' else [free[i % len(free)] if len(free) > 1 and (i + int(seed * 10)) % 3 else free[0]]
        for s in sides:
            if fb - last[s] < 0.45 * fps:
                continue
            sg = SIGN[s]
            S = L['shoulder.' + s]
            k = 0.6 if kind == 'both' else 1.0
            p0, q0 = ready(s, r)
            if kind == 'pinch':
                out = S + Vector((-sg * 0.03, -0.3, -0.24))
                rot_out = rig.hand_rot(s, Vector((-sg * 0.3, -1, 0.35)), Vector((-sg * 0.7, -0.2, -0.3)))
                fing = 'pinch'
            else:
                out = S + Vector((sg * (0.07 + 0.1 * amp * k), -0.3 - 0.04 * amp, -0.27 + 0.05 * amp * k))
                rot_out = rig.hand_rot(s, Vector((sg * 0.2, -1, 0.05)), Vector((sg * 0.3, -0.25, 1)))
                fing = 'open'
            pre = p0 + Vector((0, 0.015, 0.012))
            rig.key_hand(s, fb - 0.2 * fps, pre, q0)
            rig.key_hand(s, fb, out, rot_out)
            rig.key_fingers(s, fb - 0.04 * fps, fing)
            rig.ch['elbow.' + s].key(fb, 0.35 if kind != 'pinch' else 0.2)
            hold = out + Vector((sg * 0.008, -0.006, -0.01))
            rig.key_hand(s, fb + 0.16 * fps, hold, rot_out)
            back, q1 = ready(s, (r * 3.7) % 1.0)
            rig.key_hand(s, fb + 0.5 * fps, back, q1)
            rig.key_fingers(s, fb + 0.5 * fps, 'relaxed', index=0.14, middle=0.2)
            rig.ch['elbow.' + s].key(fb + 0.5 * fps, 0.15)
            rig.key_clav(s, fb, 2.5 * amp)
            rig.key_clav(s, fb + 0.4 * fps, 0.0)
            last[s] = fb + 0.5 * fps
        sg = SIGN[sides[0]]
        rig.key_spine(fb, 2.0, (0 if kind == 'both' else -sg * 2.5 * amp), 0)
        rig.key_head(fb, tilt=(0 if kind == 'both' else sg * 2.5 * amp))
    end = m.F(1.0)
    rig.key_spine(end, 1.0, 0, 0)
    rig.key_head(end, tilt=0.0)


@motion('wave_hello')
def wave_hello(ctx, rig, act):
    """سلام با دست: پیش‌حرکت، بالا آمدنِ دست (آرنج پایین و بیرون، ساعد تقریباً عمود)، ۴ تابِ ساعد با دامنهٔ
    کم‌شونده، پایین آمدنِ نرم؛ تنه کمی خلافِ دست و سر کمی کج."""
    m = M(ctx, rig, act)
    s = m.pick_side('R')
    sg = SIGN[s]
    L = rig.L
    S = L['shoulder.' + s]
    m.anchor_side(s)
    m.anchor('head_tilt', 'spine', 'elbow.' + s)
    cur, cq = rig.hand_state(s, m.f0)
    rig.key_hand(s, m.F(0.08), cur + Vector((0, 0.015, -0.015)), cq)          # پیش‌حرکت
    up = S + Vector((sg * 0.19, -0.16, 0.13))      # کنارِ سر؛ آرنج پایین‌تر از دست
    fing = Vector((sg * 0.12, -0.12, 1))
    palm = Vector((-sg * 0.1, -1, 0.05))
    mid = S + Vector((sg * 0.07, -0.25, -0.2))      # مسیرِ بالا آمدن از جلوی بدن (نه تابِ بازو به بیرون)
    rig.key_hand(s, m.F(0.2), mid, rig.hand_rot(s, Vector((0, -0.6, 0.8)), Vector((-sg * 0.6, -0.4, -0.3))))
    rig.key_fingers(s, m.F(0.2), 'relaxed', index=0.12)
    rig.ch['elbow.' + s].key(m.F(0.2), 0.1)
    rig.ch['elbow.' + s].key(m.F(0.34), 0.3)
    rig.key_hand(s, m.F(0.34), up, rig.hand_rot(s, fing, palm))
    rig.key_fingers(s, m.F(0.3), 'open', thumb=0.12, index=0.05, middle=0.06, ring=0.09, pinky=0.12)
    n = 4
    for i in range(n):
        u = 0.4 + i * (0.38 / n)
        a = (1.0, 0.9, 0.78, 0.6)[i]
        ang = math.radians(17 * a if i % 2 == 0 else -15 * a)
        f2 = Quaternion((0, -1, 0), ang) @ fing
        dx = -math.sin(ang) * 0.06
        rig.key_hand(s, m.F(u), up + Vector((dx, 0, -0.005 * i)), rig.hand_rot(s, f2, palm))
    rig.key_hand(s, m.F(0.8), up + Vector((0, 0.005, -0.03)), rig.hand_rot(s, fing, palm))
    rig.key_hand(s, m.F(0.92), mid + Vector((0, 0.03, -0.1)),
                 rig.hand_rot(s, Vector((0, -0.5, 0.3)), Vector((-sg * 0.7, -0.3, -0.3))))
    rig.ch['elbow.' + s].key(m.F(0.92), 0.1)
    rig.key_fingers(s, m.F(0.9), 'relaxed')
    rig.ch['elbow.' + s].key(m.F(1.0), 0.25)
    _neutral(rig, s, m.F(1.0) + 6)
    rig.key_head(m.F(0.3), tilt=sg * 4.0)
    rig.key_head(m.F(0.95), tilt=0.0)
    rig.key_spine(m.F(0.32), -1.0, -sg * 3, sg * 1.5)
    rig.key_spine(m.F(1.0), 0, 0, 0)


@motion('nod')
def nod(ctx, rig, act):
    m = M(ctx, rig, act)
    m.anchor('head_off')
    seq = [(0.2, 7), (0.45, -1.5), (0.65, 5), (0.9, 0)]
    for u, deg in seq:
        rig.key_head(m.F(u), offset=(deg, 0, 0))


@motion('look_at')
def look_at(ctx, rig, act):
    """فقط نگاه (در compiler به شیارِ نگاه تبدیل می‌شود) + کمی چرخشِ تنه به سمتِ هدف."""
    m = M(ctx, rig, act)
    tgt = m.p.get('target', 'product')
    if tgt.startswith('product') and ctx.products:
        pid = tgt.split(':', 1)[1] if ':' in tgt else next(iter(ctx.products))
        x = rig.world_to_actor(ctx.products[pid].center_world()).x
        m.anchor('spine')
        rig.key_spine(m.F(0.3), 1.0, 6.0 * max(-1, min(1, x / 0.3)), 0)
        rig.key_spine(m.F(1.0), 0, 0, 0)


# ───────────────────────── تعامل با محصول

@motion('pick_up')
def pick_up(ctx, rig, act):
    m = M(ctx, rig, act)
    pid = m.p['product']
    prod = ctx.products[pid]
    s = m.pick_side(m.p.get('hand') or ('R' if rig.world_to_actor(prod.center_world()).x <= 0.05 else 'L'))
    sg = SIGN[s]
    L = rig.L
    gp = P.grasp_pose(rig, s, prod, prod.place_world)
    wrist, q, G, C = gp['wrist'], gp['q'], gp['G'], gp['C']
    ctx.hold_G[pid] = G
    m.anchor_side(s)
    m.anchor('spine', 'head_tilt', 'noise.' + s)
    reach = (wrist - L['shoulder.' + s]).length
    need = max(0.0, reach - 0.86 * L['arm_len.' + s])
    pitch = 4.0 + math.degrees(math.asin(min(0.6, need / 0.42)))
    yaw = 7.0 * max(-1.0, min(1.0, C.x / 0.3))
    away = Vector((wrist.x - C.x, wrist.y - C.y, 0)).normalized()
    pre = wrist + away * 0.06 + Vector((0, 0, 0.06))
    rig.key_spine(m.F(0.38), pitch * 0.8, yaw, 0)
    rig.key_hand(s, m.F(0.38), pre, q)
    rig.key_fingers(s, m.F(0.38), 'open')
    rig.key_noise(s, m.F(0.3), 0.0)
    rig.key_hand(s, m.F(0.56), wrist, q, 'flat')
    rig.key_spine(m.F(0.56), pitch, yaw, 0)
    rig.key_fingers(s, m.F(0.56), 'open')
    grip = dict(FINGER_PRESETS[prod.grasp.get('preset', 'grip')])
    k = prod.grasp.get('curl', 1.0)
    grip = {f: v * k for f, v in grip.items()}
    f_grasp = m.F(0.66)
    rig.key_hand(s, f_grasp, wrist, q, 'flat')
    rig.key_fingers(s, f_grasp, grip, 'flat')
    ctx.begin_hold(pid, rig.id, s, int(round(f_grasp)), gp)
    lift = wrist + Vector((0, 0, 0.05))
    rig.key_hand(s, m.F(0.74), lift, q)
    rig.key_fingers(s, m.F(0.74), grip)
    rig.key_spine(m.F(0.8), pitch * 0.3, yaw * 0.4, 0)
    rig.key_noise(s, m.F(0.8), 0.6)
    _hold_pose(m, s, pid, m.F(0.95))
    rig.key_fingers(s, m.F(1.0), grip, 'flat')
    rig.key_spine(m.F(1.0), 1.0, 0, 0)


@motion('present')
def present(ctx, rig, act):
    m = M(ctx, rig, act)
    pid = m.p['product']
    s = m.holding_side(pid)
    if not s:
        return
    sg = SIGN[s]
    L = rig.L
    m.anchor_side(s)
    m.anchor('spine', 'head_tilt')
    show = Vector((sg * 0.07, -0.32, L['shoulder.' + s].z - 0.07))
    _hold_pose(m, s, pid, m.F(0.3), show, yaw=-sg * 14, tilt=9)
    _hold_pose(m, s, pid, m.F(0.6), show + Vector((-sg * 0.01, -0.01, 0.01)), yaw=-sg * 4, tilt=8)
    _hold_pose(m, s, pid, m.F(0.88), show + Vector((0, 0, 0.005)), yaw=-sg * 10, tilt=9, mode='flat')
    rig.key_spine(m.F(0.3), 3.0, -sg * 2.0, 0)
    rig.key_head(m.F(0.35), tilt=sg * 3.5)
    rig.key_head(m.F(1.0), tilt=sg * 2.0)
    other = 'L' if s == 'R' else 'R'
    if m.p.get('free_hand', True) and m.free(other):
        so = SIGN[other]
        m.anchor_side(other)
        pt = L['shoulder.' + other] + Vector((-so * 0.04, -0.27, -0.2))
        rot = rig.hand_rot(other, Vector((-so * 0.75, -0.6, 0.15)), Vector((0, -0.25, 1)))
        rig.key_hand(other, m.F(0.4), pt, rot)
        rig.key_fingers(other, m.F(0.4), 'open')
        rig.key_hand(other, m.F(0.85), pt + Vector((0, 0.01, -0.01)), rot)
        _neutral(rig, other, m.F(1.0))


@motion('rotate_show')
def rotate_show(ctx, rig, act):
    m = M(ctx, rig, act)
    pid = m.p['product']
    s = m.holding_side(pid)
    if not s:
        return
    sg = SIGN[s]
    L = rig.L
    m.anchor_side(s)
    center = Vector((sg * 0.03, -0.34, L['shoulder.' + s].z - 0.08))
    for u, yaw, tilt in ((0.2, -sg * 5, 6), (0.45, 38, 10), (0.7, -34, 10), (0.9, -sg * 6, 7)):
        _hold_pose(m, s, pid, m.F(u), center, yaw=yaw, tilt=tilt)


@motion('put_down')
def put_down(ctx, rig, act):
    m = M(ctx, rig, act)
    pid = m.p['product']
    prod = ctx.products[pid]
    s = m.holding_side(pid)
    if not s:
        return
    L = rig.L
    sid = m.p.get('surface') or prod.surface_id
    target_world = ctx.surface_matrix(sid)
    gp = P.grasp_pose(rig, s, prod, target_world)
    G = ctx.hold_G[pid]
    T = rig.root.matrix_world.inverted() @ target_world
    wrist, q = P.wrist_for_product(rig, G, T)
    above = T.copy()
    above.translation.z += 0.06
    wa, qa = P.wrist_for_product(rig, G, above)
    m.anchor_side(s)
    m.anchor('spine', 'noise.' + s)
    reach = (wrist - L['shoulder.' + s]).length
    need = max(0.0, reach - 0.86 * L['arm_len.' + s])
    pitch = 4.0 + math.degrees(math.asin(min(0.6, need / 0.42)))
    yaw = 7.0 * max(-1.0, min(1.0, gp['C'].x / 0.3))
    rig.key_spine(m.F(0.42), pitch * 0.8, yaw, 0)
    rig.key_hand(s, m.F(0.42), wa, qa)
    rig.key_noise(s, m.F(0.4), 0.0)
    f_rel = m.F(0.62)
    rig.key_hand(s, f_rel, wrist, q, 'flat')
    rig.key_spine(m.F(0.62), pitch, yaw, 0)
    grip = rig.ch['fingers.' + s].value(m.f0)
    rig.key_fingers(s, f_rel, {f: v for f, v in zip(('thumb', 'index', 'middle', 'ring', 'pinky'), grip)}, 'flat')
    ctx.end_hold(pid, int(round(f_rel)), target_world, sid)
    rig.key_fingers(s, m.F(0.7), 'open')
    rig.key_hand(s, m.F(0.7), wrist, q, 'flat')
    away = Vector((wrist.x - gp['C'].x, wrist.y - gp['C'].y, 0)).normalized()
    rig.key_hand(s, m.F(0.8), wrist + away * 0.06 + Vector((0, 0, 0.05)), q)
    rig.key_noise(s, m.F(0.85), 1.0)
    rig.key_spine(m.F(0.85), pitch * 0.3, yaw * 0.3, 0)
    _neutral(rig, s, m.F(1.0))
    rig.key_spine(m.F(1.0), 0, 0, 0)


@motion('spray')
def spray(ctx, rig, act):
    """زدنِ عطر روی گردن: بطری کنارِ گردن، دو فشار، سر کمی به کنار."""
    m = M(ctx, rig, act)
    pid = m.p['product']
    s = m.holding_side(pid)
    if not s:
        return
    sg = SIGN[s]
    L = rig.L
    m.anchor_side(s)
    m.anchor('head_tilt', 'spine')
    pt = L['neck'] + Vector((sg * 0.15, -0.15, -0.05))
    neck = L['neck'] + Vector((sg * 0.03, -0.03, 0.0))
    dvec = (neck - pt)
    yaw = math.degrees(math.atan2(-dvec.x, -dvec.y))
    _hold_pose(m, s, pid, m.F(0.3), pt, yaw=yaw, tilt=-8)
    rig.key_head(m.F(0.3), tilt=-sg * 9.0)
    for u in (0.45, 0.62):
        _hold_pose(m, s, pid, m.F(u), pt + Vector((0, 0, -0.008)), yaw=yaw, tilt=-10)
        _hold_pose(m, s, pid, m.F(u + 0.06), pt, yaw=yaw, tilt=-8)
        ctx.events.append({'type': 'spray', 'product': pid, 'frame': int(m.F(u))})
    rig.key_head(m.F(0.8), tilt=-sg * 6.0)
    _hold_pose(m, s, pid, m.F(1.0))
    rig.key_head(m.F(1.0), tilt=0.0)


# ───────────────────────── ژست‌ها

@motion('point_at')
def point_at(ctx, rig, act):
    m = M(ctx, rig, act)
    tgt = m.p.get('target', 'product')
    L = rig.L
    point = None
    if tgt.startswith('product') and ctx.products:
        pid = tgt.split(':', 1)[1] if ':' in tgt else next(iter(ctx.products))
        point = rig.world_to_actor(ctx.products[pid].matrix_at(int(m.f0)) @ Vector((0, 0, ctx.products[pid].dims[2] * 0.6)))
    # دستِ هم‌سمتِ محصول (اشاره از روی بدن غیرطبیعی است)
    prefer = m.p.get('hand') if m.p.get('hand') in SIDES else ('R' if point is not None and point.x < 0 else 'L')
    s = m.pick_side(prefer)
    sg = SIGN[s]
    if point is None:
        point = L['shoulder.' + s] + Vector((sg * 0.05, -1.5, 0.0))
    sh = L['shoulder.' + s]
    d = (point - sh).normalized()
    wrist = sh + d * 0.55 * L['arm_len.' + s] + Vector((sg * 0.05, -0.06, 0.04))
    d = (point - wrist).normalized()
    palm = (Vector((0, 0, -1)) - d * Vector((0, 0, -1)).dot(d)).normalized()
    palm = (palm * 0.7 + Vector((-sg, 0, 0)) * 0.3).normalized()
    m.anchor_side(s)
    m.anchor('elbow.' + s, 'spine')
    cur, cq = rig.hand_state(s, m.f0)
    rig.key_hand(s, m.F(0.1), cur + Vector((0, 0.01, 0.01)), cq)
    rig.ch['elbow.' + s].key(m.F(0.3), 0.4)
    rig.key_hand(s, m.F(0.32), wrist + d * 0.015, rig.hand_rot(s, d, palm))   # کمی جلوتر می‌رود و برمی‌گردد
    rig.key_fingers(s, m.F(0.26), 'point')
    rig.key_hand(s, m.F(0.42), wrist, rig.hand_rot(s, d, palm))
    rig.key_hand(s, m.F(0.75), wrist - d * 0.008, rig.hand_rot(s, d, palm), 'flat')
    rig.key_spine(m.F(0.35), 2.0, -sg * 3.0, 0)
    rig.key_fingers(s, m.F(0.88), 'relaxed')
    rig.ch['elbow.' + s].key(m.F(1.0), 0.25)
    rig.key_spine(m.F(1.0), 0, 0, 0)
    _neutral(rig, s, m.F(1.0))


@motion('thumbs_up')
def thumbs_up(ctx, rig, act):
    m = M(ctx, rig, act)
    s = m.pick_side('R')
    sg = SIGN[s]
    L = rig.L
    m.anchor_side(s)
    m.anchor('elbow.' + s, 'head_tilt')
    pos = L['shoulder.' + s] + Vector((-sg * 0.01, -0.3, -0.17))
    rot = rig.hand_rot(s, Vector((-sg * 0.45, -0.9, 0)), Vector((-sg, 0.2, 0)))
    rig.key_hand(s, m.F(0.28), pos + Vector((0, -0.012, 0.015)), rot)        # کمی جلوتر و بالاتر، بعد می‌نشیند
    rig.key_fingers(s, m.F(0.22), 'thumbs_up')
    rig.ch['elbow.' + s].key(m.F(0.28), 0.2)
    rig.key_hand(s, m.F(0.38), pos, rot)
    rig.key_hand(s, m.F(0.75), pos + Vector((0, -0.006, 0.008)), rot, 'flat')
    rig.key_head(m.F(0.35), tilt=sg * 3.0)
    rig.key_head(m.F(1.0), tilt=0.0)
    rig.key_fingers(s, m.F(0.88), 'relaxed')
    rig.ch['elbow.' + s].key(m.F(1.0), 0.25)
    _neutral(rig, s, m.F(1.0))


@motion('hand_on_chest')
def hand_on_chest(ctx, rig, act):
    m = M(ctx, rig, act)
    s = m.pick_side('R')
    sg = SIGN[s]
    L = rig.L
    m.anchor_side(s)
    m.anchor('head_tilt')
    palm_pt = L['chest'] + Vector((-sg * 0.05, -0.115, 0.02))
    q = rig.hand_rot(s, Vector((-sg * 0.8, 0, 0.5)), Vector((0, 1, 0)))
    w = rig.wrist_for_palm(s, palm_pt, q)
    rig.key_hand(s, m.F(0.3), w + Vector((0, -0.012, 0.006)), q)       # کمی جلوتر می‌رسد و روی سینه می‌نشیند
    rig.key_hand(s, m.F(0.4), w, q)
    rig.key_fingers(s, m.F(0.3), 'relaxed', index=0.05, middle=0.05)
    rig.key_hand(s, m.F(0.68), w + Vector((0, -0.004, -0.004)), q, 'flat')
    rig.key_head(m.F(0.4), tilt=sg * 5.0)
    rig.key_spine(m.F(0.4), 2.5, 0, 0)
    rig.key_head(m.F(1.0), tilt=0.0)
    rig.key_spine(m.F(1.0), 0, 0, 0)
    # برگشتِ آرام‌تر (~۰٫۵ ثانیه، کمی بیش از پایانِ کنش) — پایین‌آمدنِ ۰٫۳ ثانیه‌ای ساعد را تند می‌چرخاند
    _neutral(rig, s, m.F(1.0) + 0.15 * m.fps)


@motion('open_arms')
def open_arms(ctx, rig, act):
    """آغوشِ باز / خوش‌آمد: دست‌ها ۳۵ درجه پایین‌تر از افق و کمی جلو، آرنج نرم، کفِ دست رو به جلو و بالا؛
    سینه باز و کمی عقب، دو دست با چند فریم فاصله (نه قرینهٔ کامل)."""
    m = M(ctx, rig, act)
    L = rig.L
    m.anchor('spine', 'head_tilt')
    for j, s in enumerate(SIDES):
        if not m.free(s):
            continue
        sg = SIGN[s]
        m.anchor_side(s)
        m.anchor('elbow.' + s)
        d = j * 2
        pos = L['shoulder.' + s] + Vector((sg * 0.17, -0.31, -0.25))
        rot = rig.hand_rot(s, Vector((sg * 0.55, -0.8, -0.05)), Vector((sg * 0.05, -0.45, 0.9)))
        rig.key_hand(s, m.F(0.1) + d, rig.hand_state(s, m.f0)[0] + Vector((0, 0.01, -0.01)), None)
        rig.key_hand(s, m.F(0.36) + d, pos + Vector((sg * 0.012, -0.01, 0.015)), rot)
        rig.key_fingers(s, m.F(0.3) + d, 'open', thumb=0.1, ring=0.08, pinky=0.12)
        rig.ch['elbow.' + s].key(m.F(0.36), 0.45)
        rig.key_hand(s, m.F(0.48) + d, pos, rot)
        rig.key_hand(s, m.F(0.74) + d, pos + Vector((-sg * 0.01, 0.005, -0.012)), rot, 'flat')
        rig.key_fingers(s, m.F(0.86) + d, 'relaxed')
        rig.ch['elbow.' + s].key(m.F(1.0), 0.25)
        _neutral(rig, s, m.F(1.0) + d)
    rig.key_spine(m.F(0.36), -3.0, 0, 0)
    rig.key_head(m.F(0.4), tilt=1.5)
    rig.key_spine(m.F(1.0), 0, 0, 0)
    rig.key_head(m.F(1.0), tilt=0.0)


def apply(ctx, rig, act):
    src = act.get('source') or {}
    if src.get('type', 'procedural') == 'procedural':
        fn = LIBRARY.get(src.get('fn') or act['motion'])
        if not fn:
            raise KeyError('حرکتِ رویه‌ایِ «%s» در موتور نیست' % act['motion'])
        return fn(ctx, rig, act)
    if src['type'] == 'clip':
        from . import clips
        return clips.apply(ctx, rig, act)
    raise KeyError('منبعِ حرکتِ ناشناخته: %s' % src.get('type'))
