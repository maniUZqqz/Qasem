"""محصول‌ها: ساختِ مدل، برچسب، نقطهٔ گرفتن، و چسباندن به دست.

هر محصول مبدأش وسطِ کفِ خودش است و «جلو»ی آن (جای برچسب) رو به -Y.
«گرفتن» (grasp) در manifest: ارتفاعِ نقطهٔ گرفتن (کسری از قد)، شعاعِ مؤثر، خمِ انگشت‌ها و زاویهٔ دست دورِ محصول.
"""
import math
import os

import bmesh
import bpy
from mathutils import Matrix, Quaternion, Vector

from . import materials as M
from .util import empty, link, log

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
                loop[uv].uv = (1 - a / nx, b / ny)   # جلو رو به -Y ⇐ برعکسِ x
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    mat = M.image(img, rough=0.4, name='label:' + os.path.basename(img), coat=0.2) if img else M.plastic('#f2ede4', 0.5)
    o = _obj(name, me, coll, parent, [mat])
    for p in me.polygons:
        p.use_smooth = True
    return o


def _wrap_uv_cylinder(obj, img_mat, side_mat):
    """رویهٔ کناریِ استوانه ⇐ برچسبِ دورپیچ."""
    me = obj.data
    me.materials.clear()
    me.materials.append(side_mat)
    me.materials.append(img_mat)
    for p in me.polygons:
        if abs(p.normal.z) < 0.3:
            p.material_index = 1


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
    path = entry['params'].get('model_path')
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
        self.root.rotation_quaternion = Quaternion((0, 0, 1), math.radians(sp.get('yaw', 0.0)))
        fn = BUILDERS.get(entry.get('builder'), box_package)
        fn(entry, coll, self.root)
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

    def matrix_at(self, frame):
        if frame in self.baked:
            return self.baked[frame]
        ks = sorted(k for k in self.baked if k <= frame)
        return self.baked[ks[-1]] if ks else self.rest_world


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
