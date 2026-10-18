"""محیط‌ها (رویه‌ای). اندازهٔ میز/پیشخوان از روی «سطح‌ها»ی manifest ساخته می‌شود،
پس جای محصول و ارتفاعِ میز همیشه با هم می‌خوانند.

محیطِ تازه = یک تابع با @env('name') + پوشهٔ assets/environments/<id>/manifest.json.
محیطِ آماده (فایلِ .blend اسکن‌شده) هم با builder = "blend_file" بار می‌شود.
"""
import math
import os
import random

import bmesh
import bpy
from mathutils import Vector

from . import materials as M
from .util import hex_to_linear, link, log

BUILDERS = {}


def env(name):
    def deco(fn):
        BUILDERS[name] = fn
        return fn
    return deco


def _mesh_obj(name, bm, coll, mats=(), smooth=True):
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    o = bpy.data.objects.new(name, me)
    link(o, coll)
    for m in mats:
        me.materials.append(m)
    if smooth:
        for p in me.polygons:
            p.use_smooth = True
    return o


def box(name, center, size, coll, mat, bevel=0.0, segs=3):
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    for v in bm.verts:
        v.co = Vector((v.co.x * size[0] + center[0], v.co.y * size[1] + center[1], v.co.z * size[2] + center[2]))
    o = _mesh_obj(name, bm, coll, [mat], smooth=bevel > 0)
    if bevel:
        b = o.modifiers.new('bevel', 'BEVEL')
        b.width = bevel
        b.segments = segs
    return o


def cylinder(name, center, r, h, coll, mat, verts=48, r2=None, bevel=0.0):
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, segments=verts, radius1=r, radius2=r if r2 is None else r2, depth=h)
    for v in bm.verts:
        v.co += Vector((center[0], center[1], center[2] + h / 2))
    o = _mesh_obj(name, bm, coll, [mat])
    if bevel:
        b = o.modifiers.new('bevel', 'BEVEL')
        b.width = bevel
        b.segments = 3
        b.limit_method = 'ANGLE'
    return o


def plane(name, center, size, coll, mat, rot=(0, 0, 0)):
    bm = bmesh.new()
    bmesh.ops.create_grid(bm, x_segments=1, y_segments=1, size=0.5)
    bmesh.ops.scale(bm, vec=(size[0], size[1], 1), verts=bm.verts)
    o = _mesh_obj(name, bm, coll, [mat], smooth=False)
    o.location = center
    o.rotation_euler = rot
    return o


def cyclorama(name, coll, mat, wall_y=1.2, radius=1.4, width=14.0, height=6.0, front=-6.0):
    prof = [(y, 0.0) for y in (front, front / 2, 0.0, wall_y)]
    for i in range(1, 17):
        a = (math.pi / 2) * i / 16
        prof.append((wall_y + radius * math.sin(a), radius - radius * math.cos(a)))
    prof += [(wall_y + radius, z) for z in (radius + 1.0, height)]
    bm = bmesh.new()
    rows = []
    for x in (-width / 2, 0.0, width / 2):
        rows.append([bm.verts.new((x, y, z)) for y, z in prof])
    for r in range(2):
        for i in range(len(prof) - 1):
            bm.faces.new((rows[r][i], rows[r + 1][i], rows[r + 1][i + 1], rows[r][i + 1]))
    return _mesh_obj(name, bm, coll, [mat])


def _surface_box(surfaces):
    pts = [Vector(s['pos']) for s in surfaces.values()]
    lo = Vector((min(p.x for p in pts), min(p.y for p in pts), 0))
    hi = Vector((max(p.x for p in pts), max(p.y for p in pts), 0))
    z = sum(p.z for p in pts) / len(pts)
    return lo, hi, z


def plant(name, base, coll, height=1.2, pot_color='#d9d2c5', leaf_color='#2f5d34', seed=3):
    rnd = random.Random(seed)
    cylinder(name + '.pot', base, 0.16, 0.36, coll, M.ceramic(pot_color), 40, r2=0.2, bevel=0.01)
    cylinder(name + '.soil', (base[0], base[1], base[2] + 0.33), 0.185, 0.02, coll, M.plastic('#3a2a1e', 0.9, 'soil'))
    lm = M.leaf(leaf_color)
    stem = M.plastic('#4a6b3a', 0.6, 'stem')
    for i in range(18):
        ang = rnd.uniform(0, 2 * math.pi)
        tilt = rnd.uniform(0.25, 0.9)
        L = height * rnd.uniform(0.45, 0.85)
        start = Vector((base[0], base[1], base[2] + 0.34))
        d = Vector((math.cos(ang) * math.sin(tilt), math.sin(ang) * math.sin(tilt), math.cos(tilt)))
        tip = start + d * L
        bm = bmesh.new()
        w = rnd.uniform(0.07, 0.12)
        side = d.cross(Vector((0, 0, 1))).normalized() if abs(d.z) < 0.99 else Vector((1, 0, 0))
        n = 6
        prev = None
        for k in range(n + 1):
            u = k / n
            c = start + d * L * (0.35 + 0.65 * u) + Vector((0, 0, -0.18 * L * u * u))
            ww = w * math.sin(math.pi * min(1, u * 1.05)) + 0.004
            a, b = bm.verts.new(c - side * ww), bm.verts.new(c + side * ww)
            if prev:
                bm.faces.new((prev[0], prev[1], b, a))
            prev = (a, b)
        o = _mesh_obj('%s.leaf%d' % (name, i), bm, coll, [lm])
        o.modifiers.new('solid', 'SOLIDIFY').thickness = 0.002
        bm2 = bmesh.new()
        bmesh.ops.create_cone(bm2, cap_ends=False, segments=6, radius1=0.006, radius2=0.004, depth=L * 0.4)
        for v in bm2.verts:
            v.co.z += L * 0.2
        so = _mesh_obj('%s.stem%d' % (name, i), bm2, coll, [stem])
        so.location = start
        so.rotation_mode = 'QUATERNION'
        so.rotation_quaternion = d.to_track_quat('Z', 'Y')


def vase(name, base, coll, color='#efe9e0', h=0.24):
    cylinder(name + '.body', base, 0.06, h, coll, M.ceramic(color), 48, r2=0.035, bevel=0.004)
    lm = M.leaf('#47703f')
    for i in range(5):
        ang = i * 1.3
        bm = bmesh.new()
        L = 0.28 + 0.05 * (i % 2)
        prev = None
        start = Vector((base[0], base[1], base[2] + h))
        d = Vector((math.cos(ang) * 0.35, math.sin(ang) * 0.35, 1)).normalized()
        side = Vector((-d.y, d.x, 0)).normalized()
        for k in range(6):
            u = k / 5
            c = start + d * L * u + Vector((0, 0, -0.08 * u * u))
            ww = 0.035 * math.sin(math.pi * u) + 0.002
            a, b = bm.verts.new(c - side * ww), bm.verts.new(c + side * ww)
            if prev:
                bm.faces.new((prev[0], prev[1], b, a))
            prev = (a, b)
        _mesh_obj('%s.leaf%d' % (name, i), bm, coll, [lm]).modifiers.new('s', 'SOLIDIFY').thickness = 0.0015


def table_round(name, furn, coll, top_mat, leg_mat):
    """میزِ گرد از روی furniture.table (مرکز، شعاع، ارتفاع) — سطح‌ها روی همین میز تعریف شده‌اند."""
    c, r, z = Vector(furn['center']), furn['radius'], furn['height']
    cylinder(name + '.top', (c.x, c.y, z - 0.03), r, 0.03, coll, top_mat, 96, bevel=0.006)
    cylinder(name + '.stem', (c.x, c.y, 0.02), 0.045, z - 0.05, coll, leg_mat, 32)
    cylinder(name + '.base', (c.x, c.y, 0.0), 0.24, 0.02, coll, leg_mat, 64, bevel=0.004)
    return c, r, z


def counter(name, furn, coll, top_mat, body_mat):
    c, (w, depth), z = Vector(furn['center']), furn['size'], furn['height']
    box(name + '.top', (c.x, c.y, z - 0.02), (w, depth, 0.04), coll, top_mat, 0.004)
    box(name + '.body', (c.x, c.y + 0.03, (z - 0.04) / 2), (w - 0.04, depth - 0.08, z - 0.04), coll, body_mat, 0.004)
    return c, w, z


# ───────────────────────── محیط‌ها

@env('studio')
def studio(ctx, e, coll):
    p = e['params']
    bg = M.plaster(p.get('backdrop_color', '#d8cfc6'), 0.85, 'backdrop')
    cyclorama('cyc', coll, bg, wall_y=p.get('wall_distance', 1.4))
    style = p.get('table', 'round_marble')
    furn = e['furniture']['table']
    if style == 'round_marble':
        table_round('table', furn, coll, M.marble(), M.metal('#b8975a', 0.25, 'brass'))
    elif style == 'wood':
        table_round('table', furn, coll, M.wood('#7a5234', 2.5), M.metal('#2b2b2b', 0.4, 'blackmetal'))
    else:
        c = furn['center']
        box('plinth', (c[0], c[1], furn['height'] / 2), (furn['radius'] * 2.2, furn['radius'] * 1.3, furn['height']), coll,
            M.ceramic('#f4f1ec'), 0.01)
    if p.get('decor', True):
        c, r, z = furn['center'], furn['radius'], furn['height']
        vase('vase', (c[0] + r * 0.62, c[1] - r * 0.05 + 0.08, z), coll)
        for i, (x, h, col) in enumerate(((-1.25, 1.0, '#c9b8a6'), (1.35, 0.7, '#b9a796'), (1.0, 0.45, '#d7c7b5'))):
            cylinder('prop%d' % i, (x, 1.6, 0), 0.22, h, coll, M.plaster(col, 0.8, 'prop%d' % i), 64, bevel=0.02)
    return {'floor_z': 0.0}


@env('boutique')
def boutique(ctx, e, coll):
    p = e['params']
    floor = M.wood(p.get('floor_color', '#8a6a4e'), 1.2, 0.35, 'floor_wood')
    plane('floor', (0, 0, 0), (12, 12), coll, floor)
    wall = M.plaster(p.get('wall_color', '#e9dfd2'), 0.9, 'wall')
    plane('backwall', (0, 2.0, 2.0), (12, 4), coll, wall, (math.pi / 2, 0, 0))
    plane('sidewall_l', (3.2, 0, 2.0), (12, 4), coll, wall, (math.pi / 2, 0, math.pi / 2))
    plane('sidewall_r', (-3.2, 0, 2.0), (12, 4), coll, wall, (math.pi / 2, 0, -math.pi / 2))
    shelf = M.wood(p.get('shelf_color', '#6e4a2f'), 3.0, 0.4, 'shelf_wood')
    led = M.emission('#ffe2b8', 6.0, 'led')
    rnd = random.Random(7)
    palette = ['#c84b4b', '#2f4f6f', '#e2c290', '#3c6e57', '#efe6da', '#7a4e8c', '#d98b3a', '#1f1f1f']
    for row, zz in enumerate((0.85, 1.3, 1.75)):
        box('shelf%d' % row, (0, 1.82, zz), (3.4, 0.32, 0.035), coll, shelf, 0.004)
        box('led%d' % row, (0, 1.72, zz - 0.022), (3.3, 0.01, 0.006), coll, led)
        x = -1.6
        while x < 1.6:
            kind = rnd.random()
            col = rnd.choice(palette)
            if kind < 0.5:
                w, h = rnd.uniform(0.06, 0.12), rnd.uniform(0.1, 0.24)
                box('item', (x + w / 2, 1.82 + rnd.uniform(-0.04, 0.04), zz + 0.0175 + h / 2), (w, rnd.uniform(0.05, 0.1), h),
                    coll, M.plastic(col, 0.4, 'item' + col, coat=0.3), 0.002)
            else:
                w, h = rnd.uniform(0.035, 0.06), rnd.uniform(0.1, 0.2)
                cylinder('bottle', (x + w, 1.82, zz + 0.0175), w, h, coll, M.glass(col, 0.05, name='shelfglass' + col, tint=0.7), 24)
                w *= 2
            x += w + rnd.uniform(0.03, 0.08)
    counter('counter', e['furniture']['counter'], coll, M.marble('#f1eee9', '#9b958d', 0.1), M.wood('#5a3b26', 3.0, 0.45, 'counter_wood'))
    lamp = M.emission('#ffd9a0', 25.0, 'lamp')
    for x in (-0.55, 0.55):
        cylinder('pendant_cord', (x, -0.3, 1.95), 0.004, 1.2, coll, M.metal('#222222', 0.5, 'cord'), 8)
        cylinder('pendant', (x, -0.3, 1.75), 0.11, 0.2, coll, M.metal('#b8975a', 0.3, 'brass'), 32, r2=0.03)
        cylinder('bulb', (x, -0.3, 1.74), 0.05, 0.03, coll, lamp, 24)
    plant('plant_l', (1.9, 1.4, 0), coll, 1.4, seed=5)
    plant('plant_r', (-2.1, 1.3, 0), coll, 1.1, seed=9)
    return {'floor_z': 0.0}


@env('home')
def home(ctx, e, coll):
    p = e['params']
    plane('floor', (0, 0, 0), (12, 12), coll, M.wood(p.get('floor_color', '#a07850'), 1.5, 0.38, 'oak'))
    wall = M.plaster(p.get('wall_color', '#efe9e1'), 0.9, 'wall')
    plane('backwall', (0, 2.4, 1.5), (10, 3), coll, wall, (math.pi / 2, 0, 0))
    plane('sidewall', (2.6, 0, 1.5), (10, 3), coll, wall, (math.pi / 2, 0, math.pi / 2))
    # پنجرهٔ دیوارِ راست (نورِ روز)
    wx = -2.6
    plane('wall_r_low', (wx, 0.2, 0.4), (4.4, 0.8), coll, wall, (math.pi / 2, 0, -math.pi / 2))
    plane('wall_r_high', (wx, 0.2, 2.75), (4.4, 0.5), coll, wall, (math.pi / 2, 0, -math.pi / 2))
    sky = M.emission('#dfeeff', p.get('window_brightness', 6.0), 'sky')
    plane('window_sky', (wx - 0.4, 0.2, 1.65), (3.0, 1.7), coll, sky, (math.pi / 2, 0, -math.pi / 2))
    frame = M.plastic('#f6f4f0', 0.4, 'frame')
    for z in (0.8, 2.5):
        box('wframe', (wx, 0.2, z), (0.08, 3.0, 0.05), coll, frame)
    for y in (-1.3, 0.2, 1.7):
        box('wframe_v', (wx, y, 1.65), (0.08, 0.05, 1.75), coll, frame)
    # کاناپه پشتِ سر
    fab = M.fabric(p.get('sofa_color', '#8f8475'), 0.6, 'sofa')
    box('sofa_base', (0, 1.85, 0.22), (2.2, 0.9, 0.36), coll, fab, 0.05)
    box('sofa_back', (0, 2.2, 0.55), (2.2, 0.22, 0.6), coll, fab, 0.06)
    for x in (-1.0, 1.0):
        box('sofa_arm', (x, 1.85, 0.38), (0.2, 0.9, 0.5), coll, fab, 0.06)
    for i, x in enumerate((-0.55, 0.0, 0.55)):
        box('cushion%d' % i, (x, 1.75, 0.5), (0.5, 0.5, 0.18), coll,
            M.fabric(('#c9b79c', '#7d8b74', '#d9cbb8')[i], 0.7, 'cushion%d' % i), 0.07)
    plane('rug', (0, 0.8, 0.003), (3.0, 2.0), coll, M.fabric('#b9a58c', 0.3, 'rug'))
    art = M.concrete('#b9a48e')
    box('art', (0.6, 2.38, 1.55), (0.9, 0.03, 0.6), coll, art, 0.004)
    box('art_frame', (0.6, 2.39, 1.55), (0.96, 0.02, 0.66), coll, M.metal('#1d1d1d', 0.5, 'artframe'))
    plant('plant', (1.9, 1.6, 0), coll, 1.3, seed=11)
    # میز جلو (جزیرهٔ آشپزخانه/میزِ کنار)
    counter('island', e['furniture']['counter'], coll, M.wood('#b98d5f', 2.0, 0.3, 'island_top'), M.plaster('#f2efea', 0.6, 'island_body'))
    lamp = M.emission('#ffe1b0', 15.0, 'lamp')
    cylinder('floorlamp_pole', (1.4, 1.9, 0), 0.012, 1.55, coll, M.metal('#1f1f1f', 0.4, 'lamp_pole'), 12)
    cylinder('floorlamp_shade', (1.4, 1.9, 1.45), 0.18, 0.25, coll, M.fabric('#efe4d0', 0.2, 'shade'), 32, r2=0.13)
    cylinder('floorlamp_bulb', (1.4, 1.9, 1.5), 0.05, 0.05, coll, lamp, 16)
    return {'floor_z': 0.0, 'window': (wx, 0.2, 1.65)}


@env('blend_file')
def blend_file(ctx, e, coll):
    path = os.path.join(e['folder'], e['params'].get('file') or e.get('file', 'scene.blend'))
    with bpy.data.libraries.load(path, link=False) as (src, dst):
        dst.objects = list(src.objects)
    for o in dst.objects:
        if o and o.type != 'CAMERA':
            coll.objects.link(o)
    return {'floor_z': 0.0}


def build(ctx):
    e = ctx.c['environment']
    coll = ctx.coll('environment')
    M.TEXTURE_ROOTS[:] = [os.path.join(os.environ.get('UP3D_ROOT', ''), 'assets', 'textures')]
    fn = BUILDERS.get(e['builder'])
    if not fn:
        raise KeyError('سازندهٔ محیطِ «%s» نیست' % e['builder'])
    info = fn(ctx, e, coll) or {}
    log('environment', e['id'], 'objects=%d' % len(coll.objects))
    return info
