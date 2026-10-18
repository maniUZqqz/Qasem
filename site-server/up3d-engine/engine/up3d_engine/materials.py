"""کتابخانهٔ موادِ PBR.

دو منبع:
  ۱. رویه‌ای (بی‌نیاز به فایل): چوب، مرمر، پارچه، گچ، بتن، فلز، شیشه، مایع، سرامیک، پلاستیک، برگ، نورِ تابان.
  ۲. بستهٔ بافتِ واقعی (ارتقا): پوشهٔ assets/textures/<id>/ با نام‌گذاریِ ambientCG/PolyHaven
     (*_Color، *_Roughness، *_NormalGL، *_Displacement) — اگر باشد خودکار جایگزینِ رویه‌ای می‌شود.
"""
import os

import bpy

from .util import hex_to_linear

_CACHE = {}
TEXTURE_ROOTS = []


def _new(name):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    p = nt.nodes.get('Principled BSDF')
    return m, nt, p


def _node(nt, kind, loc=(0, 0), **inputs):
    n = nt.nodes.new(kind)
    n.location = loc
    for k, v in inputs.items():
        if k in n.inputs:
            n.inputs[k].default_value = v
        else:
            setattr(n, k, v)
    return n


def _sock(sockets, name, typ):
    """گرهٔ Mix چند سوکتِ هم‌نام دارد (برای هر نوعِ داده)؛ با نوع پیدا کن."""
    for s in sockets:
        if s.name == name and s.type == typ:
            return s
    return sockets[name]


def _bump(nt, p, height_socket, strength=0.1, distance=0.01):
    b = _node(nt, 'ShaderNodeBump', (-250, -400), Strength=strength, Distance=distance)
    nt.links.new(height_socket, b.inputs['Height'])
    nt.links.new(b.outputs['Normal'], p.inputs['Normal'])
    return b


def _cached(key, fn):
    m = _CACHE.get(key)
    if m is None or m.name not in bpy.data.materials:
        m = fn()
        _CACHE[key] = m
    return m


def texture_set(tex_id, scale=1.0):
    """بستهٔ بافتِ PBR از روی پوشه؛ None اگر نیست."""
    for root in TEXTURE_ROOTS:
        d = os.path.join(root, tex_id)
        if not os.path.isdir(d):
            continue
        files = {f.lower(): os.path.join(d, f) for f in os.listdir(d)}

        def find(*keys):
            for f, path in files.items():
                if any(k in f for k in keys) and f.endswith(('.jpg', '.png', '.jpeg', '.exr', '.tif')):
                    return path
            return None
        col = find('_color', '_diff', 'albedo', 'basecolor')
        if not col:
            continue

        def make():
            m, nt, p = _new('tex:' + tex_id)
            tc = _node(nt, 'ShaderNodeTexCoord', (-1100, 0))
            mp = _node(nt, 'ShaderNodeMapping', (-900, 0))
            mp.inputs['Scale'].default_value = (scale, scale, scale)
            nt.links.new(tc.outputs['UV'], mp.inputs['Vector'])

            def img(path, loc, non_color=False):
                n = _node(nt, 'ShaderNodeTexImage', loc)
                n.image = bpy.data.images.load(path, check_existing=True)
                if non_color:
                    n.image.colorspace_settings.name = 'Non-Color'
                nt.links.new(mp.outputs['Vector'], n.inputs['Vector'])
                return n
            nt.links.new(img(col, (-600, 300)).outputs['Color'], p.inputs['Base Color'])
            r = find('_rough')
            if r:
                nt.links.new(img(r, (-600, 0), True).outputs['Color'], p.inputs['Roughness'])
            nm = find('_normalgl', '_nor_gl', '_normal')
            if nm:
                nmap = _node(nt, 'ShaderNodeNormalMap', (-250, -300))
                nt.links.new(img(nm, (-600, -300), True).outputs['Color'], nmap.inputs['Color'])
                nt.links.new(nmap.outputs['Normal'], p.inputs['Normal'])
            mt = find('_metal')
            if mt:
                nt.links.new(img(mt, (-600, -600), True).outputs['Color'], p.inputs['Metallic'])
            return m
        return _cached(('tex', tex_id, scale), make)
    return None


def plaster(color='#e8e1d8', rough=0.88, name='plaster'):
    def make():
        m, nt, p = _new(name)
        p.inputs['Base Color'].default_value = hex_to_linear(color)
        p.inputs['Roughness'].default_value = rough
        n = _node(nt, 'ShaderNodeTexNoise', (-600, -300), Scale=40.0, Detail=8.0)
        _bump(nt, p, n.outputs['Fac'], 0.06, 0.004)
        return m
    return _cached(('plaster', color, rough, name), make)


def concrete(color='#9a958e'):
    def make():
        m, nt, p = _new('concrete')
        n = _node(nt, 'ShaderNodeTexNoise', (-700, 100), Scale=6.0, Detail=10.0, Roughness=0.6)
        ramp = _node(nt, 'ShaderNodeValToRGB', (-450, 100))
        c = hex_to_linear(color)
        ramp.color_ramp.elements[0].color = (c[0] * 0.8, c[1] * 0.8, c[2] * 0.8, 1)
        ramp.color_ramp.elements[1].color = (min(1, c[0] * 1.15), min(1, c[1] * 1.15), min(1, c[2] * 1.15), 1)
        nt.links.new(n.outputs['Fac'], ramp.inputs['Fac'])
        nt.links.new(ramp.outputs['Color'], p.inputs['Base Color'])
        p.inputs['Roughness'].default_value = 0.8
        _bump(nt, p, n.outputs['Fac'], 0.15, 0.01)
        return m
    return _cached(('concrete', color), make)


def wood(color='#6b4226', scale=3.0, rough=0.42, name='wood'):
    def make():
        m, nt, p = _new(name)
        tc = _node(nt, 'ShaderNodeTexCoord', (-1200, 0))
        mp = _node(nt, 'ShaderNodeMapping', (-1000, 0))
        mp.inputs['Scale'].default_value = (scale, scale * 8, scale)
        nt.links.new(tc.outputs['Object'], mp.inputs['Vector'])
        wave = _node(nt, 'ShaderNodeTexWave', (-780, 150), wave_type='RINGS', Scale=2.5, Distortion=6.0, Detail=3.0)
        noise = _node(nt, 'ShaderNodeTexNoise', (-780, -150), Scale=18.0, Detail=6.0)
        nt.links.new(mp.outputs['Vector'], wave.inputs['Vector'])
        nt.links.new(mp.outputs['Vector'], noise.inputs['Vector'])
        mix = _node(nt, 'ShaderNodeMix', (-560, 100), data_type='FLOAT')
        mix.inputs['Factor'].default_value = 0.35
        nt.links.new(wave.outputs['Fac'], mix.inputs['A'])
        nt.links.new(noise.outputs['Fac'], mix.inputs['B'])
        ramp = _node(nt, 'ShaderNodeValToRGB', (-360, 100))
        c = hex_to_linear(color)
        ramp.color_ramp.elements[0].color = (c[0] * 0.55, c[1] * 0.55, c[2] * 0.55, 1)
        ramp.color_ramp.elements[1].color = (min(1, c[0] * 1.35), min(1, c[1] * 1.3), min(1, c[2] * 1.25), 1)
        nt.links.new(mix.outputs['Result'], ramp.inputs['Fac'])
        nt.links.new(ramp.outputs['Color'], p.inputs['Base Color'])
        rr = _node(nt, 'ShaderNodeMapRange', (-360, -200))
        rr.inputs['To Min'].default_value = rough - 0.08
        rr.inputs['To Max'].default_value = rough + 0.12
        nt.links.new(noise.outputs['Fac'], rr.inputs['Value'])
        nt.links.new(rr.outputs['Result'], p.inputs['Roughness'])
        _bump(nt, p, mix.outputs['Result'], 0.08, 0.003)
        return m
    return _cached(('wood', color, scale, rough, name), make)


def marble(color='#efece6', vein='#8a8580', rough=0.12):
    def make():
        m, nt, p = _new('marble')
        tc = _node(nt, 'ShaderNodeTexCoord', (-1100, 0))
        noise = _node(nt, 'ShaderNodeTexNoise', (-850, 0), Scale=2.2, Detail=12.0, Roughness=0.65, Distortion=1.5)
        nt.links.new(tc.outputs['Object'], noise.inputs['Vector'])
        wave = _node(nt, 'ShaderNodeTexWave', (-650, 0), Scale=1.3, Distortion=14.0, Detail=6.0)
        nt.links.new(noise.outputs['Color'], wave.inputs['Vector'])
        ramp = _node(nt, 'ShaderNodeValToRGB', (-420, 0))
        ramp.color_ramp.elements[0].position = 0.0
        ramp.color_ramp.elements[0].color = hex_to_linear(vein)
        ramp.color_ramp.elements[1].position = 0.12
        ramp.color_ramp.elements[1].color = hex_to_linear(color)
        nt.links.new(wave.outputs['Fac'], ramp.inputs['Fac'])
        nt.links.new(ramp.outputs['Color'], p.inputs['Base Color'])
        p.inputs['Roughness'].default_value = rough
        p.inputs['Coat Weight'].default_value = 0.3
        p.inputs['Subsurface Weight'].default_value = 0.05
        return m
    return _cached(('marble', color, vein, rough), make)


def fabric(color='#7a6a5a', sheen=0.6, name='fabric'):
    def make():
        m, nt, p = _new(name)
        p.inputs['Base Color'].default_value = hex_to_linear(color)
        p.inputs['Roughness'].default_value = 0.92
        p.inputs['Sheen Weight'].default_value = sheen
        p.inputs['Sheen Roughness'].default_value = 0.4
        tc = _node(nt, 'ShaderNodeTexCoord', (-900, -300))
        wave = _node(nt, 'ShaderNodeTexWave', (-650, -300), Scale=180.0, Distortion=0.5)
        nt.links.new(tc.outputs['Object'], wave.inputs['Vector'])
        _bump(nt, p, wave.outputs['Fac'], 0.12, 0.002)
        return m
    return _cached(('fabric', color, sheen, name), make)


def metal(color='#c9a45c', rough=0.25, name='metal', brushed=False):
    def make():
        m, nt, p = _new(name)
        p.inputs['Base Color'].default_value = hex_to_linear(color)
        p.inputs['Metallic'].default_value = 1.0
        p.inputs['Roughness'].default_value = rough
        if brushed:
            p.inputs['Anisotropic'].default_value = 0.6
        return m
    return _cached(('metal', color, rough, name, brushed), make)


def glass(color='#ffffff', rough=0.02, ior=1.48, name='glass', tint=1.0):
    def make():
        m, nt, p = _new(name)
        c = hex_to_linear(color)
        p.inputs['Base Color'].default_value = (1 - (1 - c[0]) * tint, 1 - (1 - c[1]) * tint, 1 - (1 - c[2]) * tint, 1)
        p.inputs['Roughness'].default_value = rough
        p.inputs['IOR'].default_value = ior
        p.inputs['Transmission Weight'].default_value = 1.0
        m.surface_render_method = 'DITHERED'
        return m
    return _cached(('glass', color, rough, ior, name, tint), make)


def liquid(color='#e8a33a', name='liquid'):
    def make():
        m, nt, p = _new(name)
        p.inputs['Base Color'].default_value = hex_to_linear(color)
        p.inputs['Roughness'].default_value = 0.0
        p.inputs['IOR'].default_value = 1.36
        p.inputs['Transmission Weight'].default_value = 1.0
        vol = nt.nodes.new('ShaderNodeVolumeAbsorption')
        vol.inputs['Color'].default_value = hex_to_linear(color)
        vol.inputs['Density'].default_value = 25.0
        nt.links.new(vol.outputs['Volume'], nt.nodes['Material Output'].inputs['Volume'])
        return m
    return _cached(('liquid', color, name), make)


def plastic(color='#ffffff', rough=0.35, name='plastic', coat=0.0):
    def make():
        m, nt, p = _new(name)
        p.inputs['Base Color'].default_value = hex_to_linear(color)
        p.inputs['Roughness'].default_value = rough
        p.inputs['Coat Weight'].default_value = coat
        return m
    return _cached(('plastic', color, rough, name, coat), make)


def ceramic(color='#f3efe9'):
    return plastic(color, 0.18, 'ceramic', coat=0.6)


def leaf(color='#2f5d34'):
    def make():
        m, nt, p = _new('leaf')
        p.inputs['Base Color'].default_value = hex_to_linear(color)
        p.inputs['Roughness'].default_value = 0.5
        p.inputs['Subsurface Weight'].default_value = 0.3
        p.inputs['Subsurface Radius'].default_value = (0.2, 0.6, 0.1)
        n = _node(nt, 'ShaderNodeTexNoise', (-600, 200), Scale=12.0)
        mix = _node(nt, 'ShaderNodeMix', (-350, 200), data_type='RGBA')
        c = hex_to_linear(color)
        _sock(mix.inputs, 'A', 'RGBA').default_value = c
        _sock(mix.inputs, 'B', 'RGBA').default_value = (c[0] * 1.6, c[1] * 1.4, c[2] * 0.8, 1)
        nt.links.new(n.outputs['Fac'], _sock(mix.inputs, 'Factor', 'VALUE'))
        nt.links.new(_sock(mix.outputs, 'Result', 'RGBA'), p.inputs['Base Color'])
        return m
    return _cached(('leaf', color), make)


def emission(color='#fff3dd', strength=8.0, name='emit'):
    def make():
        m, nt, p = _new(name)
        p.inputs['Base Color'].default_value = hex_to_linear(color)
        p.inputs['Emission Color'].default_value = hex_to_linear(color)
        p.inputs['Emission Strength'].default_value = strength
        return m
    return _cached(('emit', color, strength, name), make)


def image(path, rough=0.35, name='image', coat=0.0, alpha=False):
    def make():
        m, nt, p = _new(name)
        n = _node(nt, 'ShaderNodeTexImage', (-500, 200))
        n.image = bpy.data.images.load(path, check_existing=True)
        n.extension = 'CLIP'
        nt.links.new(n.outputs['Color'], p.inputs['Base Color'])
        if alpha:
            nt.links.new(n.outputs['Alpha'], p.inputs['Alpha'])
        p.inputs['Roughness'].default_value = rough
        p.inputs['Coat Weight'].default_value = coat
        return m
    return _cached(('image', path, rough, name, coat, alpha), make)


def by_spec(spec, default=None):
    """{'type': 'wood', 'color': '#..', 'texture': 'WoodFloor041'} ⇐ ماده. بافتِ واقعی اگر هست برنده است."""
    if not spec:
        return default
    if isinstance(spec, str):
        spec = {'type': spec}
    if spec.get('texture'):
        t = texture_set(spec['texture'], spec.get('scale', 1.0))
        if t:
            return t
    t = spec.get('type', 'plaster')
    kw = {k: v for k, v in spec.items() if k not in ('type', 'texture', 'scale')}
    fn = {'plaster': plaster, 'wood': wood, 'marble': marble, 'fabric': fabric, 'metal': metal, 'glass': glass,
          'plastic': plastic, 'ceramic': ceramic, 'leaf': leaf, 'emission': emission, 'concrete': concrete,
          'liquid': liquid}.get(t, plaster)
    try:
        return fn(**kw)
    except TypeError:
        return fn()
