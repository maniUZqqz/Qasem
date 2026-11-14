"""محصول‌ها: ساختِ مدل، برچسب، نقطهٔ گرفتن، و چسباندن به دست.

هر محصول مبدأش وسطِ کفِ خودش است و «جلو»ی آن (جای برچسب) رو به -Y.
«گرفتن» (grasp) در manifest: ارتفاعِ نقطهٔ گرفتن (کسری از قد)، شعاعِ مؤثر، خمِ انگشت‌ها و زاویهٔ دست دورِ محصول.
"""
import math
import os

import bmesh
import bpy
from mathutils import Matrix, Quaternion, Vector

from . import keys as K
from . import materials as M
from .util import empty, iter_fcurves, link, log

BUILDERS = {}


def builder(name):
    def deco(fn):
        BUILDERS[name] = fn
        return fn
    return deco


def _obj(name, mesh, coll, parent=None, mats=()):
    o = bpy.data.objects.new(name, mesh)
    link(o, coll)
    if parent:
        o.parent = parent
    for m in mats:
        o.data.materials.append(m)
    return o


def _rounded_box(name, w, d, h, bevel, coll, parent, mat, z0=0.0, segments=4):
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    for v in bm.verts:
        v.co = Vector((v.co.x * w, v.co.y * d, v.co.z * h + z0 + h / 2))
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    o = _obj(name, me, coll, parent, [mat] if mat else [])
    if bevel > 0:
        b = o.modifiers.new('bevel', 'BEVEL')
        b.width = bevel
        b.segments = segments
        b.limit_method = 'NONE'
    for p in me.polygons:
        p.use_smooth = True
    try:
        o.modifiers.new('wn', 'WEIGHTED_NORMAL')
    except (TypeError, RuntimeError):
        pass
    return o


def _cylinder(name, r, h, coll, parent, mat, z0=0.0, verts=48, bevel=0.0, cap_uv=True):
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False, segments=verts, radius1=r, radius2=r, depth=h,
                          calc_uvs=cap_uv)
    for v in bm.verts:
        v.co.z += z0 + h / 2
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    o = _obj(name, me, coll, parent, [mat] if mat else [])
    for p in me.polygons:
        p.use_smooth = True
    if bevel > 0:
        b = o.modifiers.new('bevel', 'BEVEL')
        b.width = bevel
        b.segments = 3
        b.limit_method = 'ANGLE'
    return o


def _label_plane(name, w, h, z, y, coll, parent, img, curve=0.0):
    bm = bmesh.new()
    nx, ny = (16 if curve else 1), 1
    verts = []
    for j in range(ny + 1):
        row = []
        for i in range(nx + 1):
            u, v = i / nx, j / ny
            x = (u - 0.5) * w
            yy = y
            if curve:
                ang = x / curve
                x = math.sin(ang) * curve
                yy = y + (curve - math.cos(ang) * curve)
            row.append(bm.verts.new((x, yy, z + (v - 0.5) * h)))
        verts.append(row)
    uv = bm.loops.layers.uv.new('UVMap')
    for j in range(ny):
        for i in range(nx):
            f = bm.faces.new((verts[j][i], verts[j][i + 1], verts[j + 1][i + 1], verts[j + 1][i]))
            for loop, (a, b) in zip(f.loops, ((i, j), (i + 1, j), (i + 1, j + 1), (i, j + 1))):
                # جلو رو به -Y است و دوربینِ روبه‌رو +X را سمتِ راستِ تصویر می‌بیند ⇐ u هم‌جهتِ x (برعکس‌کردنش متن را آینه‌ای می‌کرد)
                loop[uv].uv = (a / nx, b / ny)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    mat = M.image(img, rough=0.4, name='label:' + os.path.basename(img), coat=0.2) if img else M.plastic('#f2ede4', 0.5)
    o = _obj(name, me, coll, parent, [mat])
    for p in me.polygons:
        p.use_smooth = True
    return o


def _wrap_uv_cylinder(obj, img_mat, side_mat):
    """رویهٔ کناریِ استوانه ⇐ برچسبِ دورپیچ.

    create_cone بی‌لایهٔ UV هیچ UV ای نمی‌سازد (برچسبِ قوطی هرگز دیده نمی‌شد) ⇐ UV ِ استوانه‌ای را خودمان می‌سازیم:
    وسطِ برچسب (u=0.5) روبه‌روی دوربین (-Y)، u به سمتِ +X (راستِ تصویر) زیاد می‌شود ⇐ متن آینه‌ای نیست؛ درز پشتِ قوطی."""
    me = obj.data
    me.materials.clear()
    me.materials.append(side_mat)
    me.materials.append(img_mat)
    uv = me.uv_layers.get('UVMap') or me.uv_layers.new(name='UVMap')
    for n in (img_mat.node_tree.nodes if img_mat.use_nodes else []):
        if n.type == 'TEX_IMAGE':
            n.extension = 'REPEAT'               # دورپیچ: لبهٔ درز از سرِ دیگرِ تصویر ادامه می‌یابد
    zs = [v.co.z for v in me.vertices]
    z0, z1 = min(zs), max(zs)
    hz = max(1e-6, z1 - z0)
    for p in me.polygons:
        if abs(p.normal.z) < 0.3:
            p.material_index = 1
            us = []
            for li in p.loop_indices:
                co = me.vertices[me.loops[li].vertex_index].co
                us.append(0.5 + math.atan2(co.x, -co.y) / (2 * math.pi))
            if max(us) - min(us) > 0.5:          # چهره‌ای که روی درز است
                us = [u + 1.0 if u < 0.5 else u for u in us]
            for li, u in zip(p.loop_indices, us):
                co = me.vertices[me.loops[li].vertex_index].co
                uv.data[li].uv = (u, (co.z - z0) / hz)


@builder('perfume_bottle')
def perfume_bottle(entry, coll, root):
    p = entry['params']
    w, d, h = entry['dimensions']
    glass = M.glass(p.get('glass_color', '#ffffff'), rough=0.015, name='glass:' + entry['id'], tint=0.25)
    liquid = M.liquid(p.get('liquid_color', '#e8b04a'), name='liquid:' + entry['id'])
    cap_mat = M.metal(p.get('cap_color', '#c9a45c'), 0.18, 'cap:' + entry['id']) if p.get('cap_style', 'metal') == 'metal' \
        else M.plastic(p.get('cap_color', '#1c1c1c'), 0.25, 'cap:' + entry['id'], coat=0.8)
    body_h = h * 0.72
    shape = p.get('shape', 'rect')
    if shape == 'round':
        body = _cylinder('%s.body' % entry['id'], w / 2, body_h, coll, root, glass, 0, 64, 0.004)
        liq = _cylinder('%s.liquid' % entry['id'], w / 2 - 0.004, body_h * p.get('fill', 0.8), coll, root, liquid, 0.004, 48)
    else:
        body = _rounded_box('%s.body' % entry['id'], w, d, body_h, min(w, d) * 0.22, coll, root, glass)
        liq = _rounded_box('%s.liquid' % entry['id'], w - 0.008, d - 0.008, body_h * p.get('fill', 0.8), min(w, d) * 0.18,
                           coll, root, liquid, z0=0.004)
    sol = body.modifiers.new('thick', 'SOLIDIFY')
    sol.thickness = 0.0035
    sol.offset = -1
    _cylinder('%s.collar' % entry['id'], w * 0.13, h * 0.05, coll, root, cap_mat, body_h - 0.001, 32, 0.001)
    cap_h = h - body_h - h * 0.04
    if p.get('cap_shape', 'cube') == 'round':
        _cylinder('%s.cap' % entry['id'], w * 0.24, cap_h, coll, root, cap_mat, body_h + h * 0.04, 48, 0.002)
    else:
        _rounded_box('%s.cap' % entry['id'], w * 0.48, d * 0.8, cap_h, 0.003, coll, root, cap_mat, z0=body_h + h * 0.04)
    lw, lh = w * 0.72, body_h * 0.5
    front_y = -d / 2 - 0.0007 if shape != 'round' else -w / 2 - 0.0007
    _label_plane('%s.label' % entry['id'], lw, lh, body_h * 0.52, front_y, coll, root, entry.get('label_image'),
                 curve=(w / 2 if shape == 'round' else 0.0))


@builder('cream_jar')
def cream_jar(entry, coll, root):
    p = entry['params']
    w, d, h = entry['dimensions']
    r = w / 2
    body_mat = M.glass(p.get('body_color', '#f6eee6'), rough=0.35, name='jar:' + entry['id'], tint=0.9) \
        if p.get('frosted', True) else M.ceramic(p.get('body_color', '#f6eee6'))
    lid = M.metal(p.get('lid_color', '#d8b26a'), 0.22, 'lid:' + entry['id'])
    body_h = h * 0.68
    body = _cylinder('%s.body' % entry['id'], r, body_h, coll, root, body_mat, 0, 64, 0.004)
    if p.get('frosted', True):
        cream = M.plastic(p.get('cream_color', '#fbf6ef'), 0.6, 'cream:' + entry['id'])
        _cylinder('%s.cream' % entry['id'], r - 0.004, body_h * 0.85, coll, root, cream, 0.004, 48)
        s = body.modifiers.new('thick', 'SOLIDIFY')
        s.thickness = 0.004
        s.offset = -1
    _cylinder('%s.lid' % entry['id'], r * 1.02, h - body_h, coll, root, lid, body_h, 64, 0.003)
    if entry.get('label_image'):
        _label_plane('%s.label' % entry['id'], r * 1.6, body_h * 0.55, body_h * 0.5, -r - 0.0008, coll, root,
                     entry['label_image'], curve=r)


@builder('box_package')
def box_package(entry, coll, root):
    p = entry['params']
    w, d, h = entry['dimensions']
    col = M.plastic(p.get('box_color', '#f1e6d6'), 0.45, 'box:' + entry['id'], coat=0.25)
    _rounded_box('%s.body' % entry['id'], w, d, h, 0.0015, coll, root, col, segments=2)
    _label_plane('%s.label' % entry['id'], w * 0.985, h * 0.985, h / 2, -d / 2 - 0.0006, coll, root,
                 entry.get('label_image'))


@builder('can_drink')
def can_drink(entry, coll, root):
    p = entry['params']
    w, d, h = entry['dimensions']
    r = w / 2
    alu = M.metal('#d9d9db', 0.28, 'alu', brushed=True)
    side = M.metal(p.get('can_color', '#b3202a'), 0.35, 'can:' + entry['id'])
    body = _cylinder('%s.body' % entry['id'], r, h * 0.94, coll, root, side, h * 0.03, 64)
    _cylinder('%s.top' % entry['id'], r * 0.93, h * 0.03, coll, root, alu, h * 0.97, 64, 0.002)
    _cylinder('%s.bottom' % entry['id'], r * 0.93, h * 0.03, coll, root, alu, 0, 64, 0.002)
    if entry.get('label_image'):
        img = M.image(entry['label_image'], rough=0.3, name='canlabel:' + entry['id'], coat=0.5)
        _wrap_uv_cylinder(body, img, side)


@builder('file')
def from_file(entry, coll, root):
    """مدلِ آماده (GLB/OBJ/FBX) ⇐ اندازهٔ واقعی و مبدأ روی کف."""
    path = (entry.get('params') or {}).get('model_path')
    if not path and entry.get('file'):            # محصولِ بستهٔ دارایی: فایل کنارِ manifest
        path = entry['file'] if os.path.isabs(entry['file']) else os.path.join(entry.get('folder', ''), entry['file'])
    if not path or not os.path.isfile(path):
        log('product file missing, fallback box')
        return box_package(entry, coll, root)
    before = set(bpy.data.objects)
    ext = os.path.splitext(path)[1].lower()
    if ext in ('.glb', '.gltf'):
        bpy.ops.import_scene.gltf(filepath=path)
    elif ext == '.obj':
        bpy.ops.wm.obj_import(filepath=path)
    elif ext == '.fbx':
        bpy.ops.import_scene.fbx(filepath=path)
    new = [o for o in bpy.data.objects if o not in before]
    meshes = [o for o in new if o.type == 'MESH']
    bpy.context.view_layer.update()
    pts = [o.matrix_world @ Vector(c) for o in meshes for c in o.bound_box]
    lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
    hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
    target_h = entry['dimensions'][2]
    s = target_h / max(1e-6, hi.z - lo.z)
    center = Vector(((lo.x + hi.x) / 2, (lo.y + hi.y) / 2, lo.z))
    for o in new:
        for c in list(o.users_collection):
            c.objects.unlink(o)
        coll.objects.link(o)
        if o.parent is None:
            o.matrix_world = Matrix.Scale(s, 4) @ Matrix.Translation(-center) @ o.matrix_world
            o.parent = root
            o.matrix_parent_inverse = root.matrix_world.inverted()


# ── engine 1.3: phone / app showcase ---------------------------------------------------------------------------------------------------
def _rrect(w, h, r, seg=10):
    """Counter-clockwise rounded-rectangle outline around the origin, as (x, z) pairs."""
    r = max(1e-4, min(r, w / 2 - 1e-4, h / 2 - 1e-4))
    pts = []
    for cx, cz, a0 in ((w / 2 - r, h / 2 - r, 0), (-(w / 2 - r), h / 2 - r, 90), (-(w / 2 - r), -(h / 2 - r), 180),
                       (w / 2 - r, -(h / 2 - r), 270)):
        for i in range(seg + 1):
            a = math.radians(a0 + 90.0 * i / seg)
            pts.append((cx + r * math.cos(a), cz + r * math.sin(a)))
    return pts


def _slab(name, pts, y0, y1, zc, coll, parent, mat, bevel=0.0006, segs=3, xc=0.0):
    """Extruded 2D outline (x, z) between y0 and y1, centred at (xc, zc): phone body, camera plate ..."""
    bm = bmesh.new()
    vs = [bm.verts.new((x + xc, y0, z + zc)) for x, z in pts]
    face = bm.faces.new(vs)
    ret = bmesh.ops.extrude_face_region(bm, geom=[face])
    bmesh.ops.translate(bm, vec=(0, y1 - y0, 0), verts=[e for e in ret['geom'] if isinstance(e, bmesh.types.BMVert)])
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    if bevel > 0:
        bmesh.ops.bevel(bm, geom=list(bm.edges), offset=bevel, segments=segs, profile=0.5, affect='EDGES')
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    for p in me.polygons:
        p.use_smooth = abs(p.normal.y) < 0.9           # caps stay flat, rims and bevels are smooth
    return _obj(name, me, coll, parent, [mat])


def _face(name, pts, y, zc, facing, coll, parent, mat, uv=True):
    """A flat n-gon at height y (facing -1 looks towards -Y, +1 towards +Y) with 0..1 UVs over its bounding box."""
    bm = bmesh.new()
    vs = [bm.verts.new((x, y, z + zc)) for x, z in pts]
    f = bm.faces.new(vs)
    if (f.normal.y > 0) != (facing > 0):
        f.normal_flip()
    if uv:
        layer = bm.loops.layers.uv.new('UVMap')
        xs, zs = [p[0] for p in pts], [p[1] for p in pts]
        x0, x1, z0, z1 = min(xs), max(xs), min(zs), max(zs)
        for loop in f.loops:
            loop[layer].uv = ((loop.vert.co.x - x0) / (x1 - x0), (loop.vert.co.z - zc - z0) / (z1 - z0))
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    for p in me.polygons:
        p.use_smooth = False
    return _obj(name, me, coll, parent, [mat])


def _cyl_y(name, r, y0, y1, x, z, coll, parent, mat, verts=40):
    """Cylinder whose axis is Y (lens rings on the back of the phone)."""
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, segments=verts, radius1=r, radius2=r, depth=abs(y1 - y0))
    bmesh.ops.rotate(bm, verts=bm.verts, cent=(0, 0, 0), matrix=Matrix.Rotation(math.pi / 2, 3, 'X'))
    for v in bm.verts:
        v.co += Vector((x, (y0 + y1) / 2, z))
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    for p in me.polygons:
        p.use_smooth = True
    return _obj(name, me, coll, parent, [mat])


def _screen_material(img_path, brightness, aspect, name, base='#0a0d12', glare=0.1):
    """Display: black glass with a clear coat and the app image as emission, cover-fitted to the screen aspect.

    glare 0..1 = how mirror-like the glass is. A full mirror coat (1.0) shows every studio softbox as a white sheet across the screen on the
    angled phone shots and washes the app out; a product shot wants the glass to read as glass (a soft sheen, the sharp edge highlights on the
    frame) while the app stays bright and saturated. Default 0.1: a low, slightly rough coat and a lower specular level; the brightness (default 2.0) keeps the app vivid."""
    g = max(0.0, min(1.0, float(glare)))
    m, nt, p = M._new(name)
    p.inputs['Base Color'].default_value = M.hex_to_linear(base)
    p.inputs['Roughness'].default_value = 0.06 + 0.16 * (1.0 - g)
    p.inputs['Coat Weight'].default_value = 0.12 + 0.88 * g
    p.inputs['Coat Roughness'].default_value = 0.02 + 0.12 * (1.0 - g)
    try:
        p.inputs['Specular IOR Level'].default_value = 0.2 + 0.3 * g
    except KeyError:
        pass
    if img_path and os.path.isfile(img_path):
        tc = M._node(nt, 'ShaderNodeTexCoord', (-1000, 0))
        mp = M._node(nt, 'ShaderNodeMapping', (-800, 0))
        tx = M._node(nt, 'ShaderNodeTexImage', (-560, 0))
        tx.image = bpy.data.images.load(img_path, check_existing=True)
        tx.extension = 'CLIP'
        ia = tx.image.size[0] / float(max(1, tx.image.size[1]))
        su, sv = min(1.0, aspect / ia), min(1.0, ia / aspect)
        mp.inputs['Scale'].default_value = (su, sv, 1.0)
        mp.inputs['Location'].default_value = ((1 - su) / 2, (1 - sv) / 2, 0.0)
        nt.links.new(tc.outputs['UV'], mp.inputs['Vector'])
        nt.links.new(mp.outputs['Vector'], tx.inputs['Vector'])
        nt.links.new(tx.outputs['Color'], p.inputs['Emission Color'])
        p.inputs['Emission Strength'].default_value = brightness
    return m


@builder('phone')
def phone(entry, coll, root):
    """A modern phone: rounded titanium frame, glass back with a camera bump, display showing the app image. Front = -Y."""
    p = entry['params']
    w, d, h = entry['dimensions']
    r = w * 0.155
    eid = entry['id']
    frame = M.finish(p.get('frame_finish', 'titanium'), (p.get('frame_color') or None) if p.get('use_frame_color') else None)
    back = M.plastic(p.get('back_color', '#2a2d33'), 0.16, 'phone_back:' + eid, coat=0.9)
    glass = M.glass('#05070a', 0.03, 1.5, 'phone_glass', tint=1.0)
    _slab('%s.body' % eid, _rrect(w, h, r), -d / 2, d / 2, h / 2, coll, root, frame, 0.0007)
    _face('%s.bezel' % eid, _rrect(w - 0.0012, h - 0.0012, r - 0.0006), -d / 2 - 0.00018, h / 2, -1, coll, root,
          M.plastic('#050608', 0.05, 'phone_bezel', coat=1.0), uv=False)
    bz = 0.0021
    sw, sh = w - 2 * bz, h - 2 * bz
    spts = _rrect(sw, sh, r - bz * 0.7)
    fps = float(entry.get('_fps') or 24)
    f0, f1 = float(entry.get('_f0') or 1), float(entry.get('_f1') or 1)
    imgs = [p.get(k) for k in ('screen_image', 'screen_image_2', 'screen_image_3', 'screen_image_4') if p.get(k)]
    imgs = [i for i in imgs if os.path.isfile(str(i))]
    planes = []
    for k, img in enumerate(imgs or [None]):
        mat = _screen_material(img, float(p.get('screen_brightness', 2.0)), sw / sh, 'screen:%s:%d' % (eid, k),
                               p.get('screen_off_color', '#0a0d12'), float(p.get('screen_glare', 0.1)))
        planes.append(_face('%s.screen%d' % (eid, k), spts, -d / 2 - 0.0003 - k * 0.00002, h / 2, -1, coll, root, mat))
    if len(planes) > 1:           # several app screens: a hard cut every `screen_interval` seconds (constant keys, looping)
        step = max(8, int(round(float(p.get('screen_interval', 2.6)) * fps)))
        for k, pl in enumerate(planes):
            for j in range(int((f1 - f0) // step) + 2):
                pl.hide_render = (j % len(planes)) != k
                pl.keyframe_insert('hide_render', frame=int(f0 + j * step))
            for fc in iter_fcurves(pl.animation_data.action):
                for kp in fc.keyframe_points:
                    kp.interpolation = 'CONSTANT'
    if p.get('island', True):
        _face('%s.island' % eid, _rrect(w * 0.25, h * 0.0125, h * 0.0062), -d / 2 - 0.00042, h - bz - h * 0.016, -1, coll, root,
              M.plastic('#020203', 0.05, 'phone_island', coat=1.0), uv=False)
    _face('%s.back' % eid, _rrect(w - 0.0012, h - 0.0012, r - 0.0006), d / 2 + 0.00018, h / 2, 1, coll, root, back, uv=False)
    if p.get('camera_bump', True):
        cx, cz = w / 2 - 0.0215, h - 0.0215
        _slab('%s.bump' % eid, _rrect(0.0285, 0.0285, 0.0075), d / 2, d / 2 + 0.0011, cz, coll, root, back, 0.0004, xc=cx)
        for i, (dx, dz) in enumerate(((-0.0058, 0.0058), (-0.0058, -0.0058), (0.0058, 0.0))):
            _cyl_y('%s.ring%d' % (eid, i), 0.0047, d / 2 + 0.0009, d / 2 + 0.0017, cx + dx, cz + dz, coll, root, frame, 40)
            _cyl_y('%s.lens%d' % (eid, i), 0.0037, d / 2 + 0.0016, d / 2 + 0.0019, cx + dx, cz + dz, coll, root, glass, 36)
    for i, (x, z0, hh) in enumerate(((-w / 2, h * 0.64, 0.0145), (-w / 2, h * 0.5, 0.0085), (w / 2, h * 0.56, 0.0215))):
        b = _rounded_box('%s.btn%d' % (eid, i), 0.0009, 0.0026, hh, 0.0004, coll, root, frame, z0=z0, segments=2)
        b.location.x = x + (0.0002 if x > 0 else -0.0002)


# ── engine 1.3: 3D text and logo (Persian shaping happens on the site, here only the outlines are extruded) ------------------------------
def _outline_mesh(name, outline, depth, bevel, coll, parent, mat):
    """Outline polygons (x, z in metres, holes included) -> an extruded, bevelled mesh standing in the XZ plane (front = -Y)."""
    cu = bpy.data.curves.new(name + '.crv', 'CURVE')
    cu.dimensions = '2D'
    cu.fill_mode = 'BOTH'
    cu.extrude = depth / 2.0
    for pl in outline['polys']:
        pts = pl['pts']
        sp = cu.splines.new('POLY')
        sp.points.add(len(pts) - 1)
        for i, (x, z) in enumerate(pts):
            sp.points[i].co = (x, z, 0.0, 1.0)
        sp.use_cyclic_u = True
    tmp = bpy.data.objects.new(name + '.tmp', cu)
    bpy.context.scene.collection.objects.link(tmp)
    bpy.context.view_layer.update()
    me = bpy.data.meshes.new_from_object(tmp.evaluated_get(bpy.context.evaluated_depsgraph_get()))
    bpy.data.objects.remove(tmp, do_unlink=True)
    bpy.data.curves.remove(cu)
    o = _obj(name, me, coll, parent, [mat])
    o.rotation_euler = (math.pi / 2, 0, 0)
    for p in me.polygons:
        p.use_smooth = True
    if bevel > 0:
        b = o.modifiers.new('bevel', 'BEVEL')
        b.width = bevel
        b.segments = 3
        b.limit_method = 'ANGLE'
        b.angle_limit = math.radians(38)
    try:
        o.modifiers.new('wn', 'WEIGHTED_NORMAL')
    except (TypeError, RuntimeError):
        pass
    return o


def _flat_image(name, w, h, y, img, coll, parent, mat=None):
    """An alpha-cut picture plane facing -Y (the coloured logo on the front of a logo, or the fallback for a text without outlines)."""
    mat = mat or M.image(img, rough=0.35, name='face:' + os.path.basename(img), coat=0.15, alpha=True)
    return _face(name, [(w / 2, 0.0), (w / 2, h), (-w / 2, h), (-w / 2, 0.0)], y, 0.0, -1, coll, parent, mat)


def _outline_product(entry, coll, root, default_finish):
    p = entry['params']
    o = entry.get('outline')
    depth = float(p.get('depth_m', 0.05))
    face = p.get('face_image')
    fin = M.finish(p.get('finish') or default_finish, (p.get('color') or None) if p.get('use_color') else None, float(p.get('glow', 6.0)))
    if o:
        _outline_mesh('%s.shape' % entry['id'], o, depth, float(p.get('bevel_m', 0.004)), coll, root, fin)
        if face and os.path.isfile(str(face)) and p.get('face', 'image') == 'image':
            _flat_image('%s.face' % entry['id'], o['w'], o['h'], -depth / 2 - 0.0004, face, coll, root)
    elif face and os.path.isfile(str(face)):
        w, d, h = entry['dimensions']
        _flat_image('%s.flat' % entry['id'], w, h, 0.0, face, coll, root,
                    M.emission((p.get('color') if p.get('use_color') else None) or '#ffffff', float(p.get('glow', 2.0)), 'flat:' + entry['id'])
                    if p.get('finish') == 'neon' else None)
    else:
        log('3D text/logo without outline or picture: nothing to build for', entry['id'])


@builder('text3d')
def text3d(entry, coll, root):
    _outline_product(entry, coll, root, 'gold')


@builder('logo3d')
def logo3d(entry, coll, root):
    _outline_product(entry, coll, root, 'white_gloss')


@builder('primitive')
def primitive(entry, coll, root):
    """A single PBR showcase object (engine 1.3): sphere / bevelled cube / cylinder / torus / capsule with a named finish. Origin = middle of the
    bottom, so it stands on the platform like every other product."""
    p = entry['params']
    s = max(0.02, float(p.get('size_m', 0.12)))
    shape = p.get('shape', 'sphere')
    rough = p.get('roughness')
    rough = None if rough is None or float(rough) < 0 else float(rough)
    mat = M.finish(p.get('finish', 'gold'), (p.get('color') or None) if p.get('use_color') else None, float(p.get('glow', 6.0)), rough)
    bm = bmesh.new()
    if shape == 'cube' or shape == 'rounded_cube':
        bmesh.ops.create_cube(bm, size=s * 0.86)
        for v in bm.verts:
            v.co.z += s * 0.43
    elif shape == 'cylinder':
        bmesh.ops.create_cone(bm, cap_ends=True, segments=64, radius1=s * 0.38, radius2=s * 0.38, depth=s)
        for v in bm.verts:
            v.co.z += s / 2
    elif shape == 'torus':
        R, r = s * 0.34, s * 0.13
        rings = []
        for i in range(64):
            a = 2 * math.pi * i / 64
            ring = []
            for j in range(24):
                b = 2 * math.pi * j / 24
                x = (R + r * math.cos(b)) * math.cos(a)
                y = (R + r * math.cos(b)) * math.sin(a)
                ring.append(bm.verts.new((x, y, r * math.sin(b) + r)))
            rings.append(ring)
        for i in range(64):
            for j in range(24):
                bm.faces.new((rings[i][j], rings[(i + 1) % 64][j], rings[(i + 1) % 64][(j + 1) % 24], rings[i][(j + 1) % 24]))
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    elif shape == 'capsule':
        R, L = s * 0.24, s * 0.52
        bmesh.ops.create_uvsphere(bm, u_segments=48, v_segments=24, radius=R)
        for v in bm.verts:
            v.co.z += (L / 2 + R) if v.co.z >= 0 else (R - L / 2)
            v.co.z += 0.0
    else:
        bmesh.ops.create_uvsphere(bm, u_segments=64, v_segments=32, radius=s / 2)
        for v in bm.verts:
            v.co.z += s / 2
    me = bpy.data.meshes.new('%s.shape' % entry['id'])
    bm.to_mesh(me)
    bm.free()
    for pl in me.polygons:
        pl.use_smooth = True
    o = _obj('%s.shape' % entry['id'], me, coll, root, [mat])
    if shape in ('cube', 'rounded_cube'):
        b = o.modifiers.new('bevel', 'BEVEL')
        b.width = s * 0.07
        b.segments = 5
        b.limit_method = 'NONE'
        for pl in me.polygons:
            pl.use_smooth = True
    elif shape == 'cylinder':
        b = o.modifiers.new('bevel', 'BEVEL')
        b.width = s * 0.02
        b.segments = 3
        b.limit_method = 'ANGLE'
    try:
        o.modifiers.new('wn', 'WEIGHTED_NORMAL')
    except (TypeError, RuntimeError):
        pass
    return o


class Product:
    def __init__(self, ctx, entry):
        self.ctx = ctx
        self.entry = entry
        self.id = entry['id']
        self.dims = entry['dimensions']
        self.grasp = entry['grasp']
        coll = ctx.coll('product.' + self.id)
        sp = entry['surface']
        self.root = empty('%s.root' % self.id, sp['pos'], 0.02, coll)
        self.root.rotation_mode = 'QUATERNION'
        if sp.get('rot'):       # جای آزادِ ویرایشگر: چرخشِ کامل
            self.root.rotation_quaternion = K.matrix((0, 0, 0), sp['rot']).to_quaternion()
        else:
            self.root.rotation_quaternion = Quaternion((0, 0, 1), math.radians(sp.get('yaw', 0.0)))
        if entry.get('scale'):
            self.root.scale = entry['scale']
        self.keys = entry.get('keys') or []
        self.base = {'pos': list(sp['pos']), 'rot': list(sp.get('rot') or (0.0, 0.0, sp.get('yaw', 0.0))),
                     'scale': list(entry.get('scale') or (1.0, 1.0, 1.0))}
        fn = BUILDERS.get(entry.get('builder'), box_package)
        fn(dict(entry, _fps=ctx.fps, _f0=ctx.f_start, _f1=ctx.f_end), coll, self.root)
        bpy.context.view_layer.update()
        self.rest_world = self.root.matrix_world.copy()
        self.place_world = self.rest_world.copy()     # جای فعلی روی سطح (بعد از «گذاشتن» عوض می‌شود)
        self.surface = sp
        self.surface_id = entry.get('surface_id')
        self.holds = []          # [{'actor','side','f_grasp','f_release','gp','release_world'}]
        self.baked = {}          # frame -> Matrix (world)

    # موقعیت‌های مهم (جهان)
    def grasp_center_world(self, mat=None):
        mat = mat or self.rest_world
        return mat @ Vector((0, 0, self.dims[2] * self.grasp.get('height', 0.4)))

    def center_world(self, frame=None):
        mat = self.baked.get(frame, self.rest_world) if frame is not None else self.rest_world
        return mat @ Vector((0, 0, self.dims[2] * 0.5))

    def keyed_world(self, frame):
        """جای محصول از کلیدهای ویرایشگر در این فریم (وقتی در دست نیست)."""
        pos, rot, scl = K.transform(self.base, self.keys, frame)
        return K.matrix(pos, rot, scl)

    def matrix_at(self, frame):
        if frame in self.baked:
            return self.baked[frame]
        ks = sorted(k for k in self.baked if k <= frame)
        return self.baked[ks[-1]] if ks else self.rest_world


def build_prop(ctx, entry):
    """شیءِ تزئینیِ ویرایشگرِ آزاد: هر شکلِ محصول (یا مدلِ فایل) با جای/چرخش/اندازهٔ دلخواه و کلید."""
    coll = ctx.coll('prop.' + entry['id'])
    tr = entry.get('transform') or {}
    root = empty('%s.root' % entry['id'], tr.get('pos') or (0, 0, 0), 0.02, coll)
    root.rotation_mode = 'XYZ'
    root.rotation_euler = [math.radians(a) for a in (tr.get('rot') or (0, 0, 0))]
    root.scale = tr.get('scale') or (1, 1, 1)
    entry = dict(entry, _fps=ctx.fps, _f0=ctx.f_start, _f1=ctx.f_end)
    entry.setdefault('params', {})
    fn = BUILDERS.get(entry.get('builder'), box_package)
    fn(entry, coll, root)
    K.key_object(ctx, root, tr, entry.get('keys'))
    log('prop', entry['id'], entry.get('asset'), 'keys=%d' % len(entry.get('keys') or []))
    return root


def grasp_pose(rig, side, product, prod_world=None):
    """مچ کجا و با چه جهتی باشد تا محصول در prod_world گرفته شود (فضای بازیگر).
    خروجی: (wrist_pos, wrist_quat, G) — G = تبدیلِ محصول نسبت به مچ (ثابت در تمامِ نگه‌داشتن)."""
    g = product.grasp
    pw = prod_world or product.rest_world
    pa = rig.root.matrix_world.inverted() @ pw          # محصول در فضای بازیگر
    C = pa @ Vector((0, 0, product.dims[2] * g.get('height', 0.4)))
    az = math.radians(g.get('azimuth', 35))
    sgn = -1.0 if side == 'R' else 1.0
    d = Vector((sgn * math.cos(az), math.sin(az), 0))           # از محورِ محصول به سمتِ دست
    p = -d                                                       # کفِ دست رو به محصول
    f = p.cross(Vector((0, 0, 1))) if side == 'R' else Vector((0, 0, 1)).cross(p)
    tilt = math.radians(g.get('tilt', 8))                        # انگشت‌ها کمی رو به پایین (طبیعی‌تر)
    f = (f * math.cos(tilt) + Vector((0, 0, -1)) * math.sin(tilt)).normalized()
    q = rig.hand_rot(side, f, p)
    palm = C + d * (g.get('radius', 0.03) + g.get('gap', 0.006))
    wrist = rig.wrist_for_palm(side, palm, q)
    W = Matrix.LocRotScale(wrist, q, Vector((1, 1, 1)))
    G = W.inverted() @ pa
    return {'wrist': wrist, 'q': q, 'G': G, 'C': C, 'd': d, 'palm': palm}


def wrist_for_product(rig, G, prod_actor):
    """محصول باید در prod_actor (ماتریسِ فضای بازیگر) باشد ⇐ مچ کجا؟"""
    W = prod_actor @ G.inverted()
    loc, rot, _ = W.decompose()
    return loc, rot


def product_pose(pos, yaw_deg=0.0, tilt_deg=0.0, roll_deg=0.0, base_offset=0.0):
    """ماتریسِ محصول در فضای بازیگر: pos = نقطهٔ گرفتن، چرخش رو به دوربین (-Y) + کجی."""
    R = (Quaternion((0, 0, 1), math.radians(yaw_deg)) @ Quaternion((1, 0, 0), math.radians(-tilt_deg))
         @ Quaternion((0, 1, 0), math.radians(roll_deg)))
    return Matrix.LocRotScale(Vector(pos) - R @ Vector((0, 0, base_offset)), R, Vector((1, 1, 1)))
