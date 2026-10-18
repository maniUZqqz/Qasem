"""تنظیمِ رندر از روی «پروفایل» + تشخیصِ خودکارِ GPU + رندرِ فریم‌ها با گزارشِ پیشرفت.

پروفایل‌ها (assets/render_profiles) فقط داده‌اند: انیمیک (Workbench)، پیش‌نمایش، استاندارد، بالا، فوق‌العاده.
روی سیستمِ قوی همان صحنه با پروفایلِ بالاتر کیفیتِ بیشتری می‌دهد (نمونه، وضوح، زیرتقسیم، تاری حرکت…).
"""
import glob
import json
import os
import time

import bpy

from .util import info, log, progress


def detect_gpu(prefer=None):
    try:
        prefs = bpy.context.preferences.addons['cycles'].preferences
    except KeyError:
        return None
    order = [prefer] if prefer else []
    order += ['OPTIX', 'CUDA', 'HIP', 'ONEAPI', 'METAL']
    for kind in order:
        if not kind:
            continue
        try:
            prefs.compute_device_type = kind
            prefs.get_devices()
        except (TypeError, ValueError):
            continue
        devs = [d for d in prefs.devices if d.type == kind]
        if devs:
            for d in prefs.devices:
                d.use = d.type == kind
            return {'type': kind, 'devices': [d.name for d in devs]}
    return None


def setup(ctx, threads=0):
    sc = bpy.context.scene
    prof = ctx.profile
    q = ctx.quality
    w, h = ctx.c['resolution']
    sc.render.resolution_x, sc.render.resolution_y = w, h
    sc.render.resolution_percentage = 100
    sc.render.fps = ctx.fps
    sc.frame_start, sc.frame_end = ctx.f_start, ctx.f_end
    sc.frame_step = int(prof.get('frame_step', 1))
    sc.render.film_transparent = False
    sc.view_settings.view_transform = prof.get('view_transform', 'AgX')
    try:
        sc.view_settings.look = prof.get('look', 'AgX - Medium High Contrast')
    except TypeError:
        pass
    sc.view_settings.exposure = prof.get('exposure', 0.0)
    if threads:
        sc.render.threads_mode = 'FIXED'
        sc.render.threads = threads
    engine = prof.get('engine', 'CYCLES')
    device = {'type': 'CPU'}
    if engine == 'WORKBENCH':
        sc.render.engine = 'BLENDER_WORKBENCH'
        sh = sc.display.shading
        sh.light = 'STUDIO'
        sh.color_type = 'TEXTURE'
        sh.show_shadows = True
        sh.show_cavity = bool(prof.get('cavity', True))
        sh.cavity_type = 'BOTH'
        sh.use_dof = bool(prof.get('workbench_dof', True))
        sc.display.render_aa = prof.get('aa', '8')
        sc.view_settings.view_transform = 'Standard'
    elif engine == 'EEVEE':
        sc.render.engine = 'BLENDER_EEVEE_NEXT' if hasattr(bpy.types, 'SceneEEVEE') else 'BLENDER_EEVEE'
        sc.eevee.taa_render_samples = prof.get('samples', 64)
        sc.eevee.use_raytracing = True
        sc.eevee.use_shadows = True
    else:
        sc.render.engine = 'CYCLES'
        cy = sc.cycles
        gpu = None if prof.get('device') == 'CPU' else detect_gpu(prof.get('gpu_backend'))
        if gpu:
            cy.device = 'GPU'
            device = gpu
        else:
            cy.device = 'CPU'
        cy.samples = int(prof.get('samples', 64))
        cy.use_adaptive_sampling = True
        cy.adaptive_threshold = prof.get('adaptive_threshold', 0.02)
        cy.use_denoising = prof.get('denoise', True)
        if cy.use_denoising:
            try:
                cy.denoiser = 'OPTIX' if device.get('type') == 'OPTIX' else 'OPENIMAGEDENOISE'
            except TypeError:
                pass
            if hasattr(cy, 'denoising_use_gpu'):
                cy.denoising_use_gpu = device.get('type') != 'CPU'
        b = prof.get('bounces', {})
        cy.max_bounces = b.get('total', 8)
        cy.diffuse_bounces = b.get('diffuse', 3)
        cy.glossy_bounces = b.get('glossy', 4)
        cy.transmission_bounces = b.get('transmission', 8)
        cy.volume_bounces = 0
        cy.transparent_max_bounces = b.get('transparent', 12)
        cy.sample_clamp_indirect = prof.get('clamp_indirect', 8.0)
        cy.caustics_reflective = False
        cy.caustics_refractive = False
        cy.use_light_tree = True
        sc.render.use_persistent_data = True
        sc.render.use_motion_blur = bool(prof.get('motion_blur', False))
        sc.render.motion_blur_shutter = prof.get('shutter', 0.4)
        cy.texture_limit_render = prof.get('texture_limit', 'OFF')
    if prof.get('compositor', engine != 'WORKBENCH'):
        _compositor(sc, prof)
    fmt = sc.render.image_settings
    fmt.file_format = 'PNG'
    fmt.color_mode = 'RGB'
    fmt.compression = 15
    sc.render.use_overwrite = False       # ادامهٔ رندرِ نیمه‌کاره بعد از قطعی
    sc.render.use_placeholder = True
    info(engine=sc.render.engine, device=device, resolution=[w, h], samples=prof.get('samples'),
         frame_step=sc.frame_step)
    ctx.report['device'] = device
    return device


def _compositor(sc, prof):
    sc.use_nodes = True
    nt = sc.node_tree
    nt.nodes.clear()
    rl = nt.nodes.new('CompositorNodeRLayers')
    out = nt.nodes.new('CompositorNodeComposite')
    cur = rl.outputs['Image']
    if prof.get('glare', True):
        g = nt.nodes.new('CompositorNodeGlare')
        g.glare_type = 'FOG_GLOW'
        g.quality = 'MEDIUM'
        try:
            g.mix = -0.92
            g.threshold = 1.0
        except AttributeError:
            pass
        nt.links.new(cur, g.inputs['Image'])
        cur = g.outputs['Image']
    if prof.get('lens', True):
        ld = nt.nodes.new('CompositorNodeLensdist')
        try:
            ld.inputs['Dispersion'].default_value = 0.012
            ld.inputs['Distortion'].default_value = -0.004
        except (KeyError, TypeError):
            pass
        nt.links.new(cur, ld.inputs['Image'])
        cur = ld.outputs['Image']
    if prof.get('vignette', 0.25):
        em = nt.nodes.new('CompositorNodeEllipseMask')
        try:
            em.width, em.height = 0.95, 0.95
        except AttributeError:
            pass
        bl = nt.nodes.new('CompositorNodeBlur')
        bl.size_x = bl.size_y = 200
        bl.use_relative = False
        mix = nt.nodes.new('CompositorNodeMixRGB')
        mix.blend_type = 'MULTIPLY'
        mix.inputs['Fac'].default_value = float(prof.get('vignette', 0.25))
        try:
            nt.links.new(em.outputs['Mask'], bl.inputs['Image'])
        except KeyError:
            nt.links.new(em.outputs[0], bl.inputs[0])
        nt.links.new(cur, mix.inputs[1])
        nt.links.new(bl.outputs[0], mix.inputs[2])
        cur = mix.outputs[0]
    nt.links.new(cur, out.inputs['Image'])


def render_frames(ctx, frames_dir, frames=None):
    sc = bpy.context.scene
    os.makedirs(frames_dir, exist_ok=True)
    sc.render.filepath = os.path.join(frames_dir, 'f_')
    todo = frames or list(range(sc.frame_start, sc.frame_end + 1, sc.frame_step))
    total = len(todo)
    times = []
    t_all = time.time()
    for i, f in enumerate(todo):
        path = os.path.join(frames_dir, 'f_%04d.png' % f)
        if os.path.isfile(path) and os.path.getsize(path) > 0:
            progress(i + 1, total)
            continue
        sc.frame_set(f)
        sc.render.filepath = path
        t = time.time()
        bpy.ops.render.render(write_still=True)
        times.append(time.time() - t)
        progress(i + 1, total)
        if i % 5 == 0:
            info(frame=f, sec_per_frame=round(sum(times) / len(times), 2), done=i + 1, total=total)
    ctx.report['frames_expected'] = total
    ctx.report['frames_rendered'] = len([p for p in glob.glob(os.path.join(frames_dir, 'f_*.png')) if os.path.getsize(p) > 0])
    ctx.report['sec_per_frame'] = round(sum(times) / len(times), 2) if times else None
    ctx.report['render_seconds'] = round(time.time() - t_all, 1)
    log('render done', ctx.report['frames_rendered'], '/', total, 'sec/frame', ctx.report['sec_per_frame'])


def still(ctx, path, frame):
    sc = bpy.context.scene
    sc.frame_set(frame)
    sc.render.filepath = path
    sc.render.use_overwrite = True
    bpy.ops.render.render(write_still=True)


def encode(frames_dir, out_path, fps, step=1, crf_quality='HIGH'):
    """فریم‌ها ⇐ MP4 با FFmpeg ِ داخلِ خودِ Blender (کارگرِ ویندوز به ffmpeg نیاز ندارد)."""
    files = sorted(glob.glob(os.path.join(frames_dir, 'f_*.png')))
    if not files:
        raise RuntimeError('فریمی برای ساختِ ویدئو نیست')
    sc = bpy.data.scenes.new('encode')
    bpy.context.window.scene = sc if bpy.context.window else None
    sc.sequence_editor_create()
    se = sc.sequence_editor
    strip = se.sequences.new_image('frames', files[0], channel=1, frame_start=1)
    for f in files[1:]:
        strip.elements.append(os.path.basename(f))
    sc.frame_start, sc.frame_end = 1, len(files)
    sc.render.fps = max(1, int(round(fps / step)))
    import struct
    with open(files[0], 'rb') as fh:
        head = fh.read(24)
    w, h = struct.unpack('>II', head[16:24])
    sc.render.resolution_x, sc.render.resolution_y = w, h
    sc.render.resolution_percentage = 100
    sc.render.image_settings.file_format = 'FFMPEG'
    ff = sc.render.ffmpeg
    ff.format = 'MPEG4'
    ff.codec = 'H264'
    ff.constant_rate_factor = crf_quality
    ff.ffmpeg_preset = 'GOOD'
    sc.render.filepath = out_path
    sc.view_settings.view_transform = 'Standard'
    bpy.ops.render.render(animation=True, scene=sc.name)
    produced = glob.glob(out_path + '*') + ([out_path] if os.path.isfile(out_path) else [])
    if produced and produced[0] != out_path:
        os.replace(produced[0], out_path)
    log('encoded', out_path, len(files), 'frames @', sc.render.fps)
    return out_path


def write_report(ctx, path):
    with open(path, 'w', encoding='utf-8') as fh:
        json.dump(ctx.report, fh, ensure_ascii=False, indent=1, default=str)
