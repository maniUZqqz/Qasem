"""خروجیِ سه‌بعدی برای «بازی/وب/نرم‌افزارِ دیگر»: GLB (وب، Unity، Godot، Unreal)، FBX، USD، BLEND.

قیدهای IK و نگاه پیش از خروجی «پخته» می‌شوند تا هر موتوری همان حرکت را بی‌قید پخش کند.
بستهٔ بازی (game_pack): کاراکتر + هر حرکت به‌صورتِ یک انیمیشنِ جدا (clip) با نامِ همان حرکت.
"""
import os

import bpy

from .util import log, stage


def _bake_constraints(ctx):
    sc = bpy.context.scene
    for rig in ctx.rigs.values():
        bpy.ops.object.select_all(action='DESELECT')
        bpy.context.view_layer.objects.active = rig.arm
        rig.arm.select_set(True)
        bpy.ops.object.mode_set(mode='POSE')
        bpy.ops.pose.select_all(action='SELECT')
        bpy.ops.nla.bake(frame_start=sc.frame_start, frame_end=sc.frame_end, only_selected=False, visual_keying=True,
                         clear_constraints=True, use_current_action=True, bake_types={'POSE'})
        bpy.ops.object.mode_set(mode='OBJECT')
    for cam in ctx.cameras:
        bpy.ops.object.select_all(action='DESELECT')
        bpy.context.view_layer.objects.active = cam
        cam.select_set(True)
        bpy.ops.nla.bake(frame_start=sc.frame_start, frame_end=sc.frame_end, only_selected=True, visual_keying=True,
                         clear_constraints=True, use_current_action=True, bake_types={'OBJECT'})


def _drop_helpers(ctx):
    for rig in ctx.rigs.values():
        for o in list(rig.t.values()):
            if isinstance(o, bpy.types.Object):
                bpy.data.objects.remove(o, do_unlink=True)


def game_pack(ctx, path):
    """کاراکتر + هر حرکت یک کلیپِ جدا (مسیرِ NLA) ⇐ GLB برای موتورهای بازی.
    shape key های چهره (۱۵ ویسم + ۵۲ واحدِ ARKit) در فایل می‌مانند تا موتورِ بازی خودش لب و حالت را بگرداند."""
    rig = next(iter(ctx.rigs.values()))
    arm = rig.arm
    act = arm.animation_data.action
    clips = [(a['motion'], a['f0'], a['f1']) for a in ctx.c['actions'] if a['actor'] == rig.id]
    ad = arm.animation_data
    ad.action = None
    used = {}
    for name, f0, f1 in clips:
        n = used.get(name, 0)
        used[name] = n + 1
        tname = name if not n else '%s_%d' % (name, n + 1)
        tr = ad.nla_tracks.new()
        tr.name = tname
        st = tr.strips.new(tname, int(f0), act)
        st.action_frame_start = float(f0)
        st.action_frame_end = float(f1)
    bpy.ops.object.select_all(action='DESELECT')
    arm.select_set(True)
    for o in rig.meshes:
        o.select_set(True)
        if o.data.shape_keys and o.data.shape_keys.animation_data:
            o.data.shape_keys.animation_data_clear()   # لب‌خوانیِ همین ویدئو مالِ بسته نیست
    bpy.context.view_layer.objects.active = arm
    kw = dict(filepath=path, export_format='GLB', use_selection=True, export_animations=True, export_apply=True,
              export_morph=True, export_yup=True, export_image_format='JPEG', export_force_sampling=True)
    try:
        bpy.ops.export_scene.gltf(export_animation_mode='NLA_TRACKS', **kw)
    except TypeError:
        bpy.ops.export_scene.gltf(export_nla_strips=True, **kw)
    log('game pack', path, 'clips=%d' % len(clips))
    return path


def preview_glb(ctx, path, max_px=512):
    """GLB ِ سبکِ یک دارایی برای نمای ویرایشگرِ پنل (بی‌انیمیشن، بی‌اسکلت، بافت ≤ ۵۱۲px):
    محیط ⇐ مجموعهٔ environment؛ محصول ⇐ product.* (مبدأ = کفِ محصول)؛ آدم ⇐ actor.* در ژستِ ایستادهٔ طبیعی
    (مش با اسکلت «پخته» می‌شود). مختصاتِ GLB همان Blender است با export_yup (ویرایشگر برمی‌گرداند)."""
    from mathutils import Matrix
    sc = bpy.context.scene
    kind = (ctx.c.get('preview') or {}).get('kind') or 'environment'
    prefixes = {'environment': ('environment',), 'product': ('product.',), 'character': ('actor.',)}.get(kind, ('environment',))
    sc.frame_set(min(ctx.f_end, ctx.f_start + 12))
    dg = bpy.context.evaluated_depsgraph_get()
    origin = Matrix.Identity(4)
    if kind == 'product' and ctx.products:
        origin = next(iter(ctx.products.values())).root.matrix_world.inverted()

    def wanted(o):
        if o.type not in ('MESH', 'CURVE', 'SURFACE', 'META', 'FONT') or o.hide_render:
            return False
        return any(c.name == p or c.name.startswith(p) for c in o.users_collection for p in prefixes)
    src = [o for o in sc.objects if wanted(o)]
    out = bpy.data.collections.new('preview_out')
    sc.collection.children.link(out)
    made = []
    for o in src:
        try:
            me = bpy.data.meshes.new_from_object(o.evaluated_get(dg), preserve_all_data_layers=False, depsgraph=dg)
        except RuntimeError:
            continue
        if not me or not len(me.vertices):
            continue
        n = bpy.data.objects.new(o.name + '.pv', me)
        n.matrix_world = origin @ o.matrix_world
        out.objects.link(n)
        made.append(n)
    for img in bpy.data.images:
        try:
            w, h = img.size[:]
            if max(w, h) > max_px:
                k = max_px / float(max(w, h))
                img.scale(max(1, int(w * k)), max(1, int(h * k)))
        except Exception:       # noqa: BLE001 — تصویرِ بی‌پیکسل/تولیدی
            pass
    bpy.ops.object.select_all(action='DESELECT')
    for n in made:
        n.select_set(True)
    if made:
        bpy.context.view_layer.objects.active = made[0]
    os.makedirs(os.path.dirname(path), exist_ok=True)
    kw = dict(filepath=path, export_format='GLB', use_selection=True, export_animations=False, export_apply=False,
              export_cameras=False, export_lights=False, export_yup=True, export_image_format='JPEG',
              export_skins=False, export_morph=False)
    try:
        bpy.ops.export_scene.gltf(**kw)
    except TypeError:
        kw.pop('export_skins', None)
        bpy.ops.export_scene.gltf(**kw)
    log('preview glb', kind, path, 'objects=%d' % len(made), os.path.getsize(path) if os.path.isfile(path) else '')
    return path


def export(ctx, fmt, path):
    stage('export')
    if fmt == 'preview_glb':
        return preview_glb(ctx, path)
    _bake_constraints(ctx)
    _drop_helpers(ctx)
    if fmt == 'game_pack':
        return game_pack(ctx, path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if fmt in ('glb', 'gltf'):
        kw = dict(filepath=path, export_format='GLB' if fmt == 'glb' else 'GLTF_SEPARATE', use_selection=False,
                  export_animations=True, export_frame_range=True, export_force_sampling=True, export_apply=True,
                  export_cameras=True, export_lights=False, export_morph=True, export_morph_animation=True,
                  export_yup=True, export_image_format='JPEG')
        try:
            bpy.ops.export_scene.gltf(export_animation_mode='SCENE', **kw)
        except TypeError:
            bpy.ops.export_scene.gltf(**kw)
    elif fmt == 'fbx':
        bpy.ops.export_scene.fbx(filepath=path, use_selection=False, bake_anim=True, add_leaf_bones=False,
                                 path_mode='COPY', embed_textures=True)
    elif fmt == 'usd':
        bpy.ops.wm.usd_export(filepath=path, export_animation=True)
    elif fmt == 'blend':
        bpy.ops.wm.save_as_mainfile(filepath=path, copy=True, compress=True)
    else:
        raise ValueError('قالبِ خروجیِ ناشناخته: %s' % fmt)
    log('exported', fmt, path, os.path.getsize(path) if os.path.isfile(path) else '')
    return path
