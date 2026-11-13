"""دوربین: هر شات یک دوربین با قاب‌بندی از manifest (ارتفاعِ قاب، نقطهٔ لنگر، لنز، دیافراگم)
+ حرکت (push_in، pull_out، orbit، crane، handheld، rack_focus…) + دنبال‌کردنِ نرمِ سوژه + برش با نشانگرِ تایم‌لاین."""
import math

import bpy
from mathutils import Vector

from . import anim
from . import keys as K
from .util import ease_inout, empty, link, log

MOVES = ('static', 'push_in', 'pull_out', 'orbit_left', 'orbit_right', 'crane_up', 'crane_down', 'handheld',
         'rack_focus', 'slide_left', 'slide_right',
         # engine 1.3
         'turntable', 'orbit_full', 'arc_left', 'arc_right', 'reveal_pull', 'hero_orbit', 'dolly_zoom', 'drift')


def eased(u, name='smooth'):
    """Natural camera easing (u in 0..1 -> 0..1). smooth = smootherstep (C2: starts and stops without a jolt)."""
    u = max(0.0, min(1.0, u))
    if name == 'linear':
        return u
    if name == 'ease_in':
        return u * u * u
    if name == 'ease_out':
        return 1.0 - (1.0 - u) ** 3
    if name == 'sine':
        return 0.5 - 0.5 * math.cos(math.pi * u)
    if name == 'expo':          # filmic: long soft start, fast middle, soft stop
        if u <= 0.0:
            return 0.0
        if u >= 1.0:
            return 1.0
        return 0.5 * 2.0 ** (20.0 * u - 10.0) if u < 0.5 else 1.0 - 0.5 * 2.0 ** (-20.0 * u + 10.0)
    return anim.smootherstep(u)


def handheld_offsets(t, seed, amount, dist):
    """Natural handheld: slow body sway + drift + a tiny fast tremor. Position in metres; the aim shift scales with the distance
    (0.3 degrees is 3 mm at 0.6 m but 16 mm at 3 m, exactly like a real camera)."""
    a = max(0.0, amount)
    if a <= 0:
        return Vector((0, 0, 0)), Vector((0, 0, 0))
    n = anim.noise1
    pos = Vector((n(t * 0.55, seed) * 0.0045 + n(t * 1.7, seed + 2) * 0.0015 + n(t * 6.3, seed + 9) * 0.0003,
                  n(t * 0.45, seed + 1) * 0.0035 + n(t * 1.3, seed + 3) * 0.0012,
                  n(t * 0.62, seed + 4) * 0.0045 + n(t * 1.9, seed + 5) * 0.0015 + n(t * 7.1, seed + 8) * 0.0003)) * a
    ang = 0.0052 * a
    aim = Vector((n(t * 0.8, seed + 6) * ang * dist + n(t * 2.6, seed + 11) * ang * 0.35 * dist, 0.0,
                  n(t * 0.7, seed + 7) * ang * dist + n(t * 2.9, seed + 12) * ang * 0.35 * dist))
    return pos, aim


def spin_products(ctx):
    """engine 1.3 'turntable' move: the PRODUCT turns on its platform while the lights stay where they are, so the reflections slide over the
    surface exactly like on a real turntable. Runs BEFORE bake: it writes rotation keys into the product (the same mechanism as the editor's
    free placement); the camera then only follows the baked anchor. turn_deg (default 360) and turn_dir (left/right) come from the shot params,
    spin_ease = smooth (soft start and stop) | linear (constant speed)."""
    n = 0
    cur = {}                                          # product id -> its current spin angle (a later spin continues from here: no pop)
    for shot in sorted(ctx.c.get('shots') or [], key=lambda s: s.get('f0', 0)):
        if shot.get('free') or shot.get('move') != 'turntable':
            continue
        subj = shot.get('subject') or {}
        prod = ctx.products.get(subj.get('id')) if subj.get('type') == 'product' else None
        if prod is None:
            continue
        fr = dict(shot.get('framing') or {})
        fr.update(shot.get('params') or {})
        turn = float(fr.get('turn_deg', 360.0)) * (1.0 if fr.get('turn_dir', 'left') == 'left' else -1.0)
        ease = 'linear' if fr.get('spin_ease') == 'linear' else 'smooth'
        rx, ry, rz = prod.base['rot']
        a0 = cur.get(prod.id, rz)
        f0, f1 = float(shot['f0']), float(shot['f1'])
        keep = [k for k in prod.keys if not k.get('_spin') or not (f0 <= k['f'] <= f1)]
        keep.append({'f': f0, 'rot': [rx, ry, a0], 'ease': ease, '_spin': True})
        keep.append({'f': f1, 'rot': [rx, ry, a0 + turn], 'ease': ease, '_spin': True})
        cur[prod.id] = a0 + turn
        prod.keys = sorted(keep, key=lambda k: k['f'])
        n += 1
    if n:
        log('turntable spins', n)
    return n


def _sensor(w, h):
    return 36.0 if h >= w else 24.0


def _free_shot(ctx, shot, coll, sensor, cam_pos):
    """شاتِ دوربینِ آزادِ ویرایشگر: جای دوربین و نقطهٔ نگاه و لنز از کلیدها، فریم به فریم."""
    sc = bpy.context.scene
    keys = shot.get('keys') or []
    f0, f1 = shot['f0'], shot['f1']
    cam_data = bpy.data.cameras.new('cam.' + shot['id'])
    cam_data.lens = float(shot.get('lens') or 35.0)
    cam_data.sensor_fit = 'VERTICAL'
    cam_data.sensor_height = sensor
    cam_data.clip_start = 0.02
    cam_data.clip_end = 80
    cam_data.dof.use_dof = ctx.quality.get('dof', True)
    cam_data.dof.aperture_fstop = float(shot.get('fstop') or 4.0)
    cam_data.dof.aperture_blades = 7
    cam = bpy.data.objects.new('cam.' + shot['id'], cam_data)
    link(cam, coll)
    frames = anim.frames_range(f0, f1)
    locs = [list(K.sample(keys, f, 'pos', [0.0, -3.0, 1.5])) for f in frames]
    aims = [list(K.sample(keys, f, 'target', [0.0, 0.0, 1.2])) for f in frames]
    aim = empty('aim.' + shot['id'], aims[0], 0.05, coll)
    tt = cam.constraints.new('TRACK_TO')
    tt.target = aim
    tt.track_axis = 'TRACK_NEGATIVE_Z'
    tt.up_axis = 'UP_Y'
    cam_data.dof.focus_object = aim         # فوکوس روی نقطهٔ نگاه
    anim.bulk_keys(cam, 'location', frames, locs)
    anim.bulk_keys(aim, 'location', frames, aims)
    if K.has_channel(keys, 'lens'):
        anim.bulk_keys(cam_data, 'lens', frames, [float(K.sample(keys, f, 'lens', cam_data.lens)) for f in frames])
    for f, p in zip(frames, locs):
        cam_pos[f] = Vector(p)
    m = sc.timeline_markers.new('shot.' + shot['id'], frame=f0)
    m.camera = cam
    log('free camera', shot.get('camera'), 'keys=%d frames=%d..%d' % (len(keys), f0, f1))
    return cam


def build(ctx, series):
    """series(kind, id, anchor, frame) ⇐ نقطهٔ جهانیِ لنگرِ سوژه در آن فریم."""
    sc = bpy.context.scene
    coll = ctx.coll('cameras')
    w, h = ctx.c['resolution']
    sensor = _sensor(w, h)
    cam_pos = {}
    cams = []
    for shot in ctx.c['shots']:
        if shot.get('free'):
            cams.append(_free_shot(ctx, shot, coll, sensor, cam_pos))
            continue
        fr = dict(shot['framing'])
        fr.update(shot.get('params') or {})
        rnd = ctx.c.get('render') or {}                      # engine 1.3: look & lens block of the scene
        ease_name = fr.get('ease') or rnd.get('ease') or 'smooth'
        hh_base = float(fr.get('handheld') if fr.get('handheld') is not None else (rnd.get('handheld') or 0.0))
        f0, f1 = shot['f0'], shot['f1']
        subj = shot['subject']
        anchor = fr.get('anchor', 'eyes' if subj['type'] == 'actor' else 'product')
        H = fr.get('height', 0.9)
        lens = fr.get('lens', 50)
        vfov = 2 * math.atan(sensor / 2 / lens)
        dist = (H / 2) / math.tan(vfov / 2)
        az = math.radians(fr.get('azimuth', 0.0))
        el = math.radians(fr.get('elevation', 3.0))
        facing = 0.0
        if subj['type'] == 'actor':
            a = next(x for x in ctx.c['actors'] if x['id'] == subj['id'])
            facing = math.radians(a['mark'].get('facing', 0.0))
        frames = anim.frames_range(f0, f1)
        pts = [series(subj['type'], subj['id'], anchor, f) for f in frames]
        smooth = anim.smooth_series(pts, fr.get('follow_smooth', 0.9))
        p0 = smooth[0]
        center_drop = (0.5 - fr.get('anchor_pos', 0.33)) * H
        move = shot.get('move') or 'static'
        amt = fr.get('move_amount', 1.0)
        follow = fr.get('follow_position', subj['type'] == 'product')
        cam_data = bpy.data.cameras.new('cam.' + shot['id'])
        cam_data.lens = lens
        cam_data.sensor_fit = 'VERTICAL'
        cam_data.sensor_height = sensor
        cam_data.clip_start = 0.02
        cam_data.clip_end = 60
        cam_data.dof.use_dof = bool(ctx.quality.get('dof', True)) and rnd.get('dof') is not False
        fstop = float(rnd.get('fstop') or fr.get('fstop', 2.8))
        cam_data.dof.aperture_fstop = max(0.7, fstop / max(0.2, float(rnd.get('dof_strength') or 1.0)))
        cam_data.dof.aperture_blades = 7
        cam = bpy.data.objects.new('cam.' + shot['id'], cam_data)
        link(cam, coll)
        aim = empty('aim.' + shot['id'], p0, 0.05, coll)
        focus = empty('focus.' + shot['id'], p0, 0.03, coll)
        tt = cam.constraints.new('TRACK_TO')
        tt.target = aim
        tt.track_axis = 'TRACK_NEGATIVE_Z'
        tt.up_axis = 'UP_Y'
        cam_data.dof.focus_object = focus
        locs, aims, focs = [], [], []
        n = max(1, len(frames) - 1)
        seed = ctx.seed(shot['id'])
        rack = fr.get('rack_from')
        lens_keys = []
        for i, f in enumerate(frames):
            u = eased(i / n, ease_name)      # آسانیِ C2: شروع و ایستِ دوربین بی‌تکان
            d = dist
            a, e = az, el
            off = Vector((0, 0, 0))
            if move == 'push_in':
                d = dist * (1.0 - 0.14 * amt * u)
            elif move == 'pull_out':
                d = dist * (0.86 + 0.14 * amt * u)
            elif move == 'orbit_left':
                a = az + math.radians(7 - 16 * amt * u)
            elif move == 'orbit_right':
                a = az + math.radians(-7 + 16 * amt * u)
            elif move == 'crane_up':
                e = el + math.radians(-3 + 9 * amt * u)
                off.z = -0.06 + 0.14 * amt * u
            elif move == 'crane_down':
                e = el + math.radians(6 - 9 * amt * u)
                off.z = 0.08 - 0.14 * amt * u
            elif move in ('slide_left', 'slide_right'):
                sgn = 1 if move == 'slide_right' else -1
                off.x = sgn * (-0.12 + 0.24 * amt * u)
            elif move == 'turntable':
                # the PRODUCT turns on its platform (spin_products); the camera only breathes in a little, like a studio rig
                d = dist * (1.025 - 0.05 * u)
            elif move == 'orbit_full':
                # the camera travels a full circle around the subject; the angular speed is eased at both ends
                a = az + math.radians(float(fr.get('turn_deg', 360.0)) * u * (1 if fr.get('turn_dir', 'left') == 'left' else -1))
            elif move in ('arc_left', 'arc_right'):
                sgn = -1 if move == 'arc_left' else 1
                a = az + sgn * math.radians(float(fr.get('arc_deg', 30.0)) * amt * (2 * u - 1))
                d = dist * (1.06 - 0.12 * u)
            elif move == 'reveal_pull':
                # starts close and low (strong depth of field), pulls back and rises to the hero frame
                d = dist * (0.42 + 0.58 * u)
                a = az + math.radians(-26.0 * amt * (1 - u))
                e = el + math.radians(-9.0 * amt * (1 - u))
            elif move == 'hero_orbit':
                d = dist * (1.12 - 0.2 * u)
                a = az + math.radians(-20.0 * amt + 40.0 * amt * u)
                e = el + math.radians(2.0 * amt * math.sin(math.pi * u))
            elif move == 'dolly_zoom':
                # vertigo: the camera dollies while the lens counter-zooms; the subject keeps its size, the background breathes
                d = dist * (1.38 - 0.7 * u * amt)
                lens_keys.append(lens * d / dist)
            elif move == 'drift':
                a = az + math.radians(5.0 * amt * (u - 0.5))
                d = dist * (1.0 - 0.035 * amt * u)
                off.x = 0.05 * amt * (u - 0.5)
                off.z = 0.015 * amt * math.sin(math.pi * u)
            dirv = Vector((math.sin(a + facing) * math.cos(e), -math.cos(a + facing) * math.cos(e), math.sin(e)))
            base = smooth[i] if follow else p0
            look = smooth[i] - Vector((0, 0, center_drop))
            pos = base - Vector((0, 0, center_drop)) + dirv * d + off
            hh = hh_base + (amt if move == 'handheld' else 0.0)
            if hh > 0:
                dp, da = handheld_offsets(f / ctx.fps, seed, hh, max(0.3, d))
                pos += dp
                look += da
            fpt = series(subj['type'], subj['id'], fr.get('focus', anchor), f)
            if move == 'rack_focus' and rack:
                other = series(rack.split(':')[0], rack.split(':')[1], 'product' if rack.startswith('product') else 'eyes', f)
                fpt = other.lerp(fpt, ease_inout(min(1.0, max(0.0, (u - 0.35) / 0.4))))
            locs.append(pos[:])
            aims.append(look[:])
            focs.append(fpt[:])
            cam_pos[f] = pos.copy()
        anim.bulk_keys(cam, 'location', frames, locs)
        anim.bulk_keys(aim, 'location', frames, aims)
        anim.bulk_keys(focus, 'location', frames, focs)
        if lens_keys and len(lens_keys) == len(frames):
            anim.bulk_keys(cam_data, 'lens', frames, lens_keys)
        m = sc.timeline_markers.new('shot.' + shot['id'], frame=f0)
        m.camera = cam
        cams.append(cam)
    if cams:
        sc.camera = cams[0]
    ctx.camera_pos = cam_pos
    log('cameras', len(cams), 'sensor=%dmm' % sensor)
    return cams
