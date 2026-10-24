"""دوربین: هر شات یک دوربین با قاب‌بندی از manifest (ارتفاعِ قاب، نقطهٔ لنگر، لنز، دیافراگم)
+ حرکت (push_in، pull_out، orbit، crane، handheld، rack_focus…) + دنبال‌کردنِ نرمِ سوژه + برش با نشانگرِ تایم‌لاین."""
import math

import bpy
from mathutils import Vector

from . import anim
from . import keys as K
from .util import ease_inout, empty, link, log

MOVES = ('static', 'push_in', 'pull_out', 'orbit_left', 'orbit_right', 'crane_up', 'crane_down', 'handheld',
         'rack_focus', 'slide_left', 'slide_right')


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
        cam_data.dof.use_dof = ctx.quality.get('dof', True)
        cam_data.dof.aperture_fstop = fr.get('fstop', 2.8)
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
        for i, f in enumerate(frames):
            u = anim.smootherstep(i / n)      # آسانیِ C2: شروع و ایستِ دوربین بی‌تکان
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
            dirv = Vector((math.sin(a + facing) * math.cos(e), -math.cos(a + facing) * math.cos(e), math.sin(e)))
            base = smooth[i] if follow else p0
            look = smooth[i] - Vector((0, 0, center_drop))
            pos = base - Vector((0, 0, center_drop)) + dirv * d + off
            if move == 'handheld':
                t = f / ctx.fps
                k = 0.006 * amt
                pos += Vector((anim.noise1(t * 1.3, seed) * k, anim.noise1(t * 1.1, seed + 2) * k * 0.6,
                               anim.noise1(t * 1.7, seed + 4) * k))
                look += Vector((anim.noise1(t * 1.6, seed + 6) * k * 0.7, 0, anim.noise1(t * 1.4, seed + 8) * k * 0.7))
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
        m = sc.timeline_markers.new('shot.' + shot['id'], frame=f0)
        m.camera = cam
        cams.append(cam)
    if cams:
        sc.camera = cams[0]
    ctx.camera_pos = cam_pos
    log('cameras', len(cams), 'sensor=%dmm' % sensor)
    return cams
