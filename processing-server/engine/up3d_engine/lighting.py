"""نورپردازی از روی manifest: هر نور = زاویه نسبت به سوژه و دوربین، فاصله، اندازه، توان، دمای رنگ.
آسمان/محیط با HDRI (پیش‌فرض: HDRI های همراهِ Blender؛ ارتقا: HDRI ِ واقعی در assets/hdri)."""
import math
import os

import bpy
from mathutils import Vector

from .util import empty, hex_to_linear, kelvin_rgb, link, log


def _hdri_path(name, folder=None):
    root = os.environ.get('UP3D_ROOT', '')
    if folder and name:                       # HDRI ِ کنارِ manifest ِ نور (بستهٔ دارایی)
        for cand in (os.path.join(folder, name), os.path.join(folder, name + '.exr'), os.path.join(folder, name + '.hdr')):
            if os.path.isfile(cand):
                return cand
    for cand in (os.path.join(root, 'assets', 'hdri', name), os.path.join(root, 'assets', 'hdri', name + '.exr'),
                 os.path.join(root, 'assets', 'hdri', name + '.hdr')):
        if os.path.isfile(cand):
            return cand
    d = bpy.utils.system_resource('DATAFILES', path='studiolights/world')
    p = os.path.join(d, name if name.endswith('.exr') else name + '.exr')
    return p if os.path.isfile(p) else None


def world(spec):
    sc = bpy.context.scene
    w = bpy.data.worlds.new('world')
    sc.world = w
    w.use_nodes = True
    nt = w.node_tree
    bg = nt.nodes['Background']
    path = _hdri_path(spec.get('hdri', 'interior'), spec.get('_folder'))
    if path:
        tc = nt.nodes.new('ShaderNodeTexCoord')
        mp = nt.nodes.new('ShaderNodeMapping')
        mp.inputs['Rotation'].default_value = (0, 0, math.radians(spec.get('hdri_rotation', 0)))
        env = nt.nodes.new('ShaderNodeTexEnvironment')
        env.image = bpy.data.images.load(path, check_existing=True)
        nt.links.new(tc.outputs['Generated'], mp.inputs['Vector'])
        nt.links.new(mp.outputs['Vector'], env.inputs['Vector'])
        nt.links.new(env.outputs['Color'], bg.inputs['Color'])
    else:
        bg.inputs['Color'].default_value = (0.05, 0.05, 0.05, 1)
    bg.inputs['Strength'].default_value = spec.get('hdri_strength', 0.25)
    # پسِ‌زمینهٔ دیده‌شده جدا از نورِ HDRI (تا آسمانِ HDRI در قاب نیاید)
    if spec.get('background_color'):
        lp = nt.nodes.new('ShaderNodeLightPath')
        mix = nt.nodes.new('ShaderNodeMixShader')
        bg2 = nt.nodes.new('ShaderNodeBackground')
        from .util import hex_to_linear
        bg2.inputs['Color'].default_value = hex_to_linear(spec['background_color'])
        out = nt.nodes['World Output']
        nt.links.new(lp.outputs['Is Camera Ray'], mix.inputs['Fac'])
        nt.links.new(bg.outputs['Background'], mix.inputs[1])
        nt.links.new(bg2.outputs['Background'], mix.inputs[2])
        nt.links.new(mix.outputs['Shader'], out.inputs['Surface'])
    return w


def build(ctx):
    lt = ctx.c.get('lighting') or {}
    rig = lt.get('rig', [])
    params = lt.get('params', {})
    coll = ctx.coll('lighting')
    world({**lt.get('world', {}), **{k: v for k, v in params.items() if k.startswith('hdri')}, '_folder': lt.get('folder')})
    actors = ctx.c['actors']
    if actors:
        mk = actors[0]['mark']
        subj = Vector(mk['pos'])
        facing = math.radians(mk.get('facing', 0.0))
    else:
        sp = next(iter(ctx.c['environment']['surfaces'].values()))
        subj = Vector(sp['pos']) - Vector((0, 0, sp['pos'][2]))
        facing = 0.0
    heights = {'face': 1.5, 'chest': 1.25, 'waist': 1.0, 'product': 0.95, 'backdrop': 1.2, 'floor': 0.0}
    k = float(params.get('intensity', 1.0))
    warmth = float(params.get('warmth', 0.0))
    made = []
    for i, L in enumerate(rig):
        az = math.radians(L.get('azimuth', 0)) + facing
        el = math.radians(L.get('elevation', 30))
        dist = L.get('distance', 2.0)
        tz = heights.get(L.get('target', 'face'), 1.4)
        target = subj + Vector((0, 0, tz))
        if L.get('target') == 'backdrop':
            target = subj + Vector((0, 2.0, 1.2))
        pos = target + Vector((math.sin(az) * math.cos(el), -math.cos(az) * math.cos(el), math.sin(el))) * dist
        if 'position' in L:
            pos = Vector(L['position'])
        kind = L.get('type', 'AREA')
        data = bpy.data.lights.new('L%d_%s' % (i, L.get('name', kind.lower())), kind)
        data.energy = L.get('power', 100) * k
        kel = L.get('kelvin', 5500) - warmth * 900
        data.color = kelvin_rgb(kel)
        if kind == 'AREA':
            data.shape = L.get('shape', 'RECTANGLE')
            data.size = L.get('size', 1.0)
            data.size_y = L.get('size_y', data.size * 1.3)
            if 'spread' in L:
                data.spread = math.radians(L['spread'])
        elif kind == 'SPOT':
            data.spot_size = math.radians(L.get('cone', 45))
            data.spot_blend = L.get('blend', 0.5)
            data.shadow_soft_size = L.get('radius', 0.1)
        elif kind == 'SUN':
            data.angle = math.radians(L.get('angle', 3))
        else:
            data.shadow_soft_size = L.get('radius', 0.1)
        obj = bpy.data.objects.new(data.name, data)
        link(obj, coll)
        obj.location = pos
        d = target - pos
        if kind == 'SUN' and 'direction' in L:
            d = Vector(L['direction'])
        obj.rotation_mode = 'QUATERNION'
        obj.rotation_quaternion = d.to_track_quat('-Z', 'Y')
        obj.visible_camera = False
        made.append(obj)
    log('lighting', lt.get('id'), 'lights=%d' % len(made))
    return made


def build_extra(ctx):
    """نورهای ویرایشگرِ آزاد: نقطه‌ای، نورافکن، سطحی، خورشید — با جای/چرخشِ دلخواه و کلید.
    جهتِ تابش = محورِ -Z ِ شیء (همان قراردادِ Blender و پیش‌نمایشِ ویرایشگر)."""
    from . import keys as K
    made = []
    coll = ctx.coll('lighting')
    kinds = {'point': 'POINT', 'spot': 'SPOT', 'area': 'AREA', 'sun': 'SUN'}
    for L in ctx.c.get('lights') or []:
        kind = kinds.get(L.get('type'), 'POINT')
        data = bpy.data.lights.new('X.%s' % L.get('id'), kind)
        data.energy = float(L.get('power') or 100.0)
        data.color = hex_to_linear(L.get('color') or '#ffffff')[:3]
        size = float(L.get('size') or 0.5)
        if kind == 'AREA':
            data.shape = 'SQUARE'
            data.size = size
        elif kind == 'SPOT':
            data.spot_size = math.radians(float(L.get('cone') or 45.0))
            data.spot_blend = float(L.get('blend') if L.get('blend') is not None else 0.3)
            data.shadow_soft_size = min(size, 1.0) * 0.2
        elif kind == 'SUN':
            data.angle = math.radians(max(0.5, min(20.0, size * 6.0)))
        else:
            data.shadow_soft_size = min(size, 2.0) * 0.2
        obj = bpy.data.objects.new(data.name, data)
        link(obj, coll)
        tr = L.get('transform') or {}
        obj.location = tr.get('pos') or (0, -1.5, 2.2)
        obj.rotation_mode = 'XYZ'
        obj.rotation_euler = [math.radians(a) for a in (tr.get('rot') or (0, 0, 0))]
        obj.visible_camera = False
        K.key_object(ctx, obj, tr, L.get('keys'), scale=False)
        made.append(obj)
    if made:
        log('editor lights', len(made))
    return made
