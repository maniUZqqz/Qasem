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


def export(ctx, fmt, path):
    stage('export')
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
