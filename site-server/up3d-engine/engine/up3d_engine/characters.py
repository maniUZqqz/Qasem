"""فراهم‌کننده‌های کاراکتر.

  mpfb  انسانِ MakeHuman/MPFB2 از «دستورِ ساخت» (جنسیت، سن، اندام، پوست، مو، لباس) — CC0
  file  هر کاراکترِ اسکلت‌دارِ آماده (.blend / .glb / .fbx) + فایلِ نقشهٔ استخوان (engine/rigs/*.json)
        ⇐ راهِ ارتقا به کاراکترِ اسکن‌شده/ممتاز بی‌تغییرِ بقیهٔ موتور.

خروجیِ هر فراهم‌کننده یکسان است: {'armature', 'body', 'meshes', 'rigmap', 'face_meshes'}
"""
import json
import os

import bpy

from .util import hex_to_linear, log

ENGINE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_MPFB_READY = False


def load_rigmap(name):
    with open(os.path.join(ENGINE_DIR, 'rigs', name + '.json'), encoding='utf-8') as fh:
        return json.load(fh)


def _move_to(objs, coll):
    for o in objs:
        for c in list(o.users_collection):
            c.objects.unlink(o)
        coll.objects.link(o)


def _mpfb():
    global _MPFB_READY
    if not _MPFB_READY:
        bpy.ops.preferences.addon_enable(module='bl_ext.user_default.mpfb')
        _MPFB_READY = True
    from bl_ext.user_default.mpfb.services.humanservice import HumanService
    from bl_ext.user_default.mpfb.services.locationservice import LocationService
    from bl_ext.user_default.mpfb.services.faceservice import FaceService
    return HumanService, LocationService, FaceService


def build(spec, actor_id, coll, quality):
    prov = spec.get('provider', 'mpfb')
    if prov == 'mpfb':
        return build_mpfb(spec, actor_id, coll, quality)
    if prov == 'file':
        return build_file(spec, actor_id, coll, quality)
    raise ValueError('فراهم‌کنندهٔ کاراکترِ ناشناخته: %s' % prov)


def build_mpfb(spec, actor_id, coll, quality):
    HumanService, LocationService, FaceService = _mpfb()
    params = spec.get('params', {})
    ud = LocationService.get_user_data()
    J = lambda rel: rel if os.path.isabs(rel) else os.path.join(ud, rel)   # noqa: E731
    macro = dict(spec['macro'])
    macro.setdefault('race', {'african': 0.33, 'asian': 0.33, 'caucasian': 0.34})
    for k in ('cupsize', 'firmness', 'muscle', 'weight', 'height', 'proportions', 'age', 'gender'):
        macro.setdefault(k, 0.5)
    for k, v in (params.get('macro') or {}).items():
        macro[k] = v
    base = HumanService.create_human(macro_detail_dict=macro)
    rig = HumanService.add_builtin_rig(base, spec.get('rig', 'default'))
    skin = params.get('skin') or spec['skin']
    HumanService.set_character_skin(J(skin), base, skin_type=spec.get('skin_type', 'ENHANCED_SSS'))
    subd_assets = 1 if quality.get('subdiv', 1) > 0 else 0
    parts = [('Eyes', spec.get('eyes', 'eyes/high-poly/high-poly.mhclo')),
             ('Eyebrows', spec.get('eyebrows', 'eyebrows/eyebrow001/eyebrow001.mhclo')),
             ('Eyelashes', spec.get('eyelashes', 'eyelashes/eyelashes01/eyelashes01.mhclo')),
             ('Teeth', 'teeth/teeth_base/teeth_base.mhclo'), ('Tongue', 'tongue/tongue01/tongue01.mhclo')]
    hair = params.get('hair') or spec.get('hair')
    if hair:
        parts.append(('Hair', hair))
    outfit = params.get('outfit')
    clothes = (spec.get('outfits') or {}).get(outfit) if outfit else None
    for c in (clothes or spec.get('clothes', [])):
        parts.append(('Clothes', c))
    for typ, rel in parts:
        try:
            HumanService.add_mhclo_asset(J(rel), base, asset_type=typ,
                                         subdiv_levels=(0 if typ in ('Eyelashes', 'Eyebrows') else (1 if typ == 'Hair' and quality.get('subdiv', 0) >= 1 else (0 if typ == 'Hair' else subd_assets))),
                                         material_type=('PROCEDURAL_EYES' if typ == 'Eyes' and quality.get('procedural_eyes', True)
                                                        else 'MAKESKIN'))
        except Exception as e:   # یک لباسِ خراب کلِ کاراکتر را نخواباند
            log('ASSET-FAIL', rel, e)
    if quality.get('face', True):
        try:
            FaceService.load_targets(base, load_microsoft_visemes=False, load_meta_visemes=True, load_arkit_faceunits=True)
            FaceService.interpolate_targets(base)
        except Exception as e:
            log('FACE-FAIL', e)
    children = [o for o in rig.children_recursive if o.type == 'MESH']
    for o in children:
        o.name = '%s.%s' % (actor_id, o.name.replace('Human.', ''))
        if any(k in o.name for k in ('hair', 'long0', 'bob', 'short0', 'ponytail', 'braid', 'afro')):
            for poly in o.data.polygons:
                poly.use_smooth = True
            _tint_hair(o, params.get('hair_color') or spec.get('hair_color'))
    base.name = '%s.body' % actor_id
    rig.name = '%s.rig' % actor_id
    if quality.get('subdiv', 1) > 0:
        sd = base.modifiers.new('subd', 'SUBSURF')
        sd.levels = 0
        sd.render_levels = int(quality.get('subdiv', 1))
    _enhance_skin(base, float(spec.get('skin_detail', 1.0)) * float(quality.get('skin_detail', 1.0)))
    eye = params.get('eye_color') or spec.get('eye_color')
    if eye:
        for o in children:
            if 'high-poly' in o.name or 'low-poly' in o.name:
                _eye_color(o, eye)
    _move_to([rig] + list(rig.children_recursive), coll)
    face_meshes = [o for o in [base] + children if o.data.shape_keys and len(o.data.shape_keys.key_blocks) > 1]
    log('character', actor_id, 'meshes=%d face_meshes=%d' % (len(children), len(face_meshes)))
    return {'armature': rig, 'body': base, 'meshes': [base] + [o for o in children if o != base],
            'rigmap': load_rigmap(spec.get('rigmap', 'mpfb_default')), 'face_meshes': face_meshes}


def _tint_hair(obj, color):
    """رنگِ مو: فام و اشباع از رنگِ هدف، روشنایی از بافتِ خودِ مو (تا تارها و سایه‌ها بمانند)؛ بی‌براقیِ پلاستیکی."""
    if not color:
        return
    h = color.lstrip('#')
    r, g, b = [int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4)]
    lum = 0.2126 * r + 0.7152 * g + 0.0722 * b
    value = max(0.3, min(1.4, lum / 0.42))
    c = hex_to_linear(color)
    mx = max(c[:3]) or 1.0
    hue_col = (c[0] / mx, c[1] / mx, c[2] / mx, 1.0)
    for slot in obj.material_slots:
        m = slot.material
        if not m or not m.use_nodes:
            continue
        nt = m.node_tree
        for p in [n for n in nt.nodes if n.type == 'BSDF_PRINCIPLED']:
            lk = p.inputs['Base Color'].links
            if lk:
                src = lk[0].from_socket
                mix = nt.nodes.new('ShaderNodeMix')
                mix.data_type = 'RGBA'
                mix.blend_type = 'COLOR'
                [s for s in mix.inputs if s.name == 'Factor' and s.type == 'VALUE'][0].default_value = 0.85
                nt.links.new(src, [s for s in mix.inputs if s.name == 'A' and s.type == 'RGBA'][0])
                [s for s in mix.inputs if s.name == 'B' and s.type == 'RGBA'][0].default_value = hue_col
                hsv = nt.nodes.new('ShaderNodeHueSaturation')
                hsv.inputs['Value'].default_value = value
                nt.links.new([s for s in mix.outputs if s.name == 'Result' and s.type == 'RGBA'][0], hsv.inputs['Color'])
                nt.links.new(hsv.outputs['Color'], p.inputs['Base Color'])
            else:
                p.inputs['Base Color'].default_value = c
            p.inputs['Roughness'].default_value = 0.55
            if 'Specular IOR Level' in p.inputs:
                p.inputs['Specular IOR Level'].default_value = 0.3
            if 'Sheen Weight' in p.inputs:
                p.inputs['Sheen Weight'].default_value = 0.0


def _enhance_skin(body, strength):
    """منافذ و ناهمواریِ ریزِ پوست (پوستِ MakeHuman فقط بافتِ رنگ دارد)."""
    if strength <= 0:
        return
    done = 0
    for slot in body.material_slots:
        m = slot.material
        if not m or not m.use_nodes:
            continue
        nt = m.node_tree
        targets = [n for n in nt.nodes if 'Normal' in n.inputs and not n.inputs['Normal'].is_linked
                   and n.type in ('BSDF_PRINCIPLED', 'GROUP', 'SUBSURFACE_SCATTERING')]
        if not targets:
            continue
        tc = nt.nodes.new('ShaderNodeTexCoord')
        vor = nt.nodes.new('ShaderNodeTexVoronoi')
        vor.inputs['Scale'].default_value = 1100.0
        noi = nt.nodes.new('ShaderNodeTexNoise')
        noi.inputs['Scale'].default_value = 160.0
        noi.inputs['Detail'].default_value = 6.0
        add = nt.nodes.new('ShaderNodeMath')
        add.operation = 'ADD'
        nt.links.new(tc.outputs['UV'], vor.inputs['Vector'])
        nt.links.new(tc.outputs['UV'], noi.inputs['Vector'])
        nt.links.new(vor.outputs['Distance'], add.inputs[0])
        nt.links.new(noi.outputs['Fac'], add.inputs[1])
        bump = nt.nodes.new('ShaderNodeBump')
        bump.inputs['Strength'].default_value = 0.05 * strength
        bump.inputs['Distance'].default_value = 0.002
        nt.links.new(add.outputs[0], bump.inputs['Height'])
        for t in targets:
            nt.links.new(bump.outputs['Normal'], t.inputs['Normal'])
        done += 1
    log('skin-detail', body.name, 'materials=%d' % done)


def _eye_color(obj, color):
    c = hex_to_linear(color)
    for slot in obj.material_slots:
        m = slot.material
        if not m or not m.use_nodes:
            continue
        for n in m.node_tree.nodes:
            for s in n.inputs:
                if s.type == 'RGBA' and 'iris' in s.name.lower() and not s.is_linked:
                    s.default_value = c


# ───────────────────────── کاراکترِ فایل

def build_file(spec, actor_id, coll, quality):
    path = spec['path'] if os.path.isabs(spec['path']) else os.path.join(spec['folder'], spec['path'])
    before = set(bpy.data.objects)
    ext = os.path.splitext(path)[1].lower()
    if ext == '.blend':
        with bpy.data.libraries.load(path, link=False) as (src, dst):
            dst.objects = list(src.objects)
        for o in dst.objects:
            if o:
                coll.objects.link(o)
    elif ext in ('.glb', '.gltf'):
        bpy.ops.import_scene.gltf(filepath=path)
    elif ext == '.fbx':
        bpy.ops.import_scene.fbx(filepath=path, automatic_bone_orientation=True)
    else:
        raise ValueError('قالبِ فایلِ کاراکتر پشتیبانی نمی‌شود: %s' % ext)
    new = [o for o in bpy.data.objects if o not in before]
    arm = next((o for o in new if o.type == 'ARMATURE'), None)
    if not arm:
        raise ValueError('فایلِ کاراکتر اسکلت ندارد')
    meshes = [o for o in new if o.type == 'MESH']
    body = max(meshes, key=lambda o: len(o.data.vertices)) if meshes else None
    _move_to(new, coll)
    arm.name = '%s.rig' % actor_id
    face_meshes = [o for o in meshes if o.data.shape_keys and len(o.data.shape_keys.key_blocks) > 1]
    rigmap = load_rigmap(spec.get('rigmap', 'mpfb_default'))
    if spec.get('face'):
        rigmap = dict(rigmap)
        rigmap['face'] = spec['face']
    return {'armature': arm, 'body': body, 'meshes': meshes, 'rigmap': rigmap, 'face_meshes': face_meshes}
