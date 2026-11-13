"""تنظیمِ رندر از روی «پروفایل» + تشخیصِ خودکارِ GPU + رندرِ فریم‌ها با گزارشِ پیشرفت.

پروفایل‌ها (assets/render_profiles) فقط داده‌اند: انیمیک (Workbench)، پیش‌نمایش، استاندارد، بالا، فوق‌العاده.
روی سیستمِ قوی همان صحنه با پروفایلِ بالاتر کیفیتِ بیشتری می‌دهد (نمونه، وضوح، زیرتقسیم، تاری حرکت…).
"""
import glob
import json
import os
import time
import traceback

import bpy

from .util import info, log, progress


def detect_gpu(prefer=None):
    """The best Cycles GPU backend: OptiX first, then CUDA (then HIP / oneAPI / Metal). UP3D_GPU_BACKEND (OPTIX / CUDA / CPU) forces one
    (the worker sets it when it has to fall back); only GPUs are enabled, never the CPU (it would only slow the GPU down)."""
    forced = (os.environ.get('UP3D_GPU_BACKEND') or '').upper()
    if forced == 'CPU':
        return None
    try:
        prefs = bpy.context.preferences.addons['cycles'].preferences
    except KeyError:
        return None
    order = [forced or prefer] if (forced or prefer) else []
    order += ['OPTIX', 'CUDA', 'HIP', 'ONEAPI', 'METAL']
    tried = set()
    for kind in order:
        if not kind or kind in tried:
            continue
        tried.add(kind)
        try:
            prefs.compute_device_type = kind
            if hasattr(prefs, 'refresh_devices'):
                prefs.refresh_devices()
            prefs.get_devices()
        except (TypeError, ValueError, RuntimeError):
            continue
        devs = [d for d in prefs.devices if d.type == kind]
        if devs:
            for d in prefs.devices:
                d.use = d.type == kind
            return {'type': kind, 'devices': [d.name for d in devs]}
    return None


#: scene "look" key -> the AgX looks to try, best first ("AgX - " + name is how Blender 4.x names them; the enum is dynamic, so assign and see)
LOOK_WORDS = {'agx': ('Medium High Contrast',), 'agx_soft': ('Low Contrast', 'Medium Low Contrast'), 'agx_contrast': ('High Contrast',),
              'agx_punchy': ('Punchy',), 'agx_golden': ('Medium High Contrast',), 'agx_bw': ('Greyscale',)}
#: looks that add a colour grade in the compositor (Blender 4.5 has no "Golden" look any more): warm highlights, a touch of lift
GRADES = {'agx_golden': 'warm'}


def _try_look(vs, word):
    for name in ('AgX - ' + word, word):
        try:
            vs.look = name
            return name
        except (TypeError, ValueError):
            continue
    return None


def apply_look(sc, look_key, prof_look, exposure):
    """AgX colour management with a named look. Returns the settings that really got applied (they go into the engine report)."""
    vs = sc.view_settings
    for vt in ('AgX', 'Filmic', 'Standard'):
        try:
            vs.view_transform = vt
            break
        except TypeError:
            continue
    words = list(LOOK_WORDS.get(look_key) or ())
    if prof_look:
        words.append(str(prof_look).replace('AgX - ', ''))
    words.append('Medium High Contrast')
    for w in words:
        if _try_look(vs, w):
            break
    vs.exposure = float(exposure or 0.0)
    return {'view': vs.view_transform, 'look': vs.look, 'exposure': vs.exposure, 'grade': GRADES.get(look_key)}


def configure_denoise(cy, device, prof):
    """OptiX denoiser on an OptiX GPU, OpenImageDenoise otherwise (also on the GPU); albedo + normal guide passes, accurate prefilter."""
    cy.use_denoising = bool(prof.get('denoise', True))
    if not cy.use_denoising:
        return 'off'
    want = 'OPTIX' if device.get('type') == 'OPTIX' else 'OPENIMAGEDENOISE'
    for name in (want, 'OPENIMAGEDENOISE'):
        try:
            cy.denoiser = name
            break
        except TypeError:
            continue
    for attr, val in (('denoising_input_passes', 'RGB_ALBEDO_NORMAL'), ('denoising_prefilter', 'ACCURATE'),
                      ('denoising_use_gpu', device.get('type') != 'CPU')):
        try:
            setattr(cy, attr, val)
        except (TypeError, AttributeError):
            pass
    return cy.denoiser


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
    rnd = ctx.c.get('render') or {}               # engine 1.3: look & lens block of the scene document
    prof = dict(prof)
    for k in ('motion_blur', 'shutter', 'vignette'):
        if rnd.get(k) is not None:
            prof[k] = rnd[k]
    if rnd.get('bloom') is not None:
        prof['bloom'] = rnd['bloom']
        prof['glare'] = rnd['bloom'] > 0
    ctx.report['look'] = apply_look(sc, rnd.get('look'), prof.get('look'), (prof.get('exposure') or 0.0) + (rnd.get('exposure') or 0.0))
    prof['grade'] = ctx.report['look'].get('grade')
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
        if not gpu and prof.get('device') != 'CPU' and os.environ.get('UP3D_REQUIRE_GPU') == '1':
            raise RuntimeError('این رندر روی GPU باید اجرا شود ولی Cycles هیچ دستگاهِ OptiX/CUDA نمی‌بیند (درایور NVIDIA را بررسی کنید)')
        if gpu:
            cy.device = 'GPU'
            device = gpu
        else:
            cy.device = 'CPU'
        cy.samples = int(prof.get('samples', 64))
        cy.use_adaptive_sampling = True
        cy.adaptive_threshold = prof.get('adaptive_threshold', 0.02)
        ctx.report['denoiser'] = configure_denoise(cy, device, prof)
        for attr, val in (('use_auto_tile', True), ('tile_size', 2048)):
            try:
                setattr(cy, attr, val)
            except (TypeError, AttributeError):
                pass
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
        bl = prof.get('bloom')
        thr = 1.0 if bl is None else 1.0 - 0.3 * min(1.0, float(bl))
        strength = 0.08 if bl is None else min(1.0, 0.04 + float(bl) * 0.2)      # Blender 4.5: «Strength» is the share of glow added
        try:
            g.mix = -0.92 if bl is None else max(-0.97, -0.9 + float(bl) * 0.3)      # Blender 4.4 and older
            g.threshold = thr
        except AttributeError:
            pass
        for name, val in (('Threshold', thr), ('Strength', strength), ('Size', 0.5), ('Smoothness', 0.1)):
            try:
                g.inputs[name].default_value = val
            except (KeyError, TypeError):
                pass
        nt.links.new(cur, g.inputs['Image'])
        cur = g.outputs['Image']
    if prof.get('grade') == 'warm':
        cb = nt.nodes.new('CompositorNodeColorBalance')
        try:
            cb.correction_method = 'LIFT_GAMMA_GAIN'
            cb.gain = (1.1, 1.0, 0.82)
            cb.gamma = (1.03, 1.0, 0.93)
            cb.lift = (1.0, 0.99, 0.97)
        except (AttributeError, TypeError, ValueError):
            pass
        try:
            nt.links.new(cur, cb.inputs['Image'])
            cur = cb.outputs['Image']
        except (KeyError, TypeError):
            nt.nodes.remove(cb)
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


def _fallback_device(ctx, err):
    """A GPU backend failed (OptiX kernel / driver trouble): OptiX -> CUDA with the OpenImageDenoise denoiser -> CPU (only when allowed).
    Returns True when the render can be retried."""
    sc = bpy.context.scene
    dev = ctx.report.get('device') or {}
    ctx.report.setdefault('fallbacks', []).append({'from': dev.get('type'), 'error': str(err)[:300]})
    if sc.render.engine != 'CYCLES' or dev.get('type') in (None, 'CPU'):
        return False
    if dev.get('type') == 'OPTIX':
        nxt = detect_gpu('CUDA') if os.environ.get('UP3D_GPU_BACKEND', '').upper() != 'OPTIX' else None
        if nxt and nxt['type'] == 'CUDA':
            sc.cycles.device = 'GPU'
            ctx.report['device'] = nxt
            ctx.report['denoiser'] = configure_denoise(sc.cycles, nxt, ctx.profile)
            info(device=nxt, fallback='OPTIX->CUDA')
            return True
    if os.environ.get('UP3D_REQUIRE_GPU') == '1':
        return False
    sc.cycles.device = 'CPU'
    ctx.report['device'] = {'type': 'CPU', 'note': 'GPU failed: %s' % str(err)[:120]}
    ctx.report['denoiser'] = configure_denoise(sc.cycles, {'type': 'CPU'}, ctx.profile)
    info(device=ctx.report['device'], fallback='GPU->CPU')
    return True


def render_one(ctx, path):
    """One frame, with the GPU fallback chain (a failed frame is retried on the next backend, never silently dropped)."""
    last = None
    for _ in range(3):
        try:
            bpy.ops.render.render(write_still=True)
            if os.path.isfile(path) and os.path.getsize(path) > 0:
                return
            last = 'no output file was written'
        except RuntimeError as e:
            last = e
            traceback.print_exc()
        if not _fallback_device(ctx, last):
            break
    raise RuntimeError('رندرِ فریم شکست خورد: %s' % last)


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
        render_one(ctx, path)
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
    render_one(ctx, path)


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
