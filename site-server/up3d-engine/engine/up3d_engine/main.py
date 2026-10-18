"""نقطهٔ ورودِ موتور: برنامهٔ اجرایی (compiled.json) ⇐ صحنهٔ کامل ⇐ رندر / عکس / خروجیِ سه‌بعدی.

حالت‌ها:
  render   فریم‌ها (PNG) + گزارشِ کیفیت
  still    یک فریم (پوستر، بندانگشتی)
  contact  چند فریمِ نمونه (برای وارسیِ سریع)
  export   GLB / FBX / USD / BLEND (وب، بازی، نرم‌افزارهای سه‌بعدی)
  encode   فریم‌ها ⇐ MP4 (بی‌نیاز به ffmpeg روی کارگر)
"""
import argparse
import json
import os
import sys
import time
import traceback

import bpy

from . import bake, camera, characters, environments, face, lighting, motions, render
from .ctx import Context
from .products import Product
from .rig import SIDES, ActorRig
from .util import info, log, stage


def parse(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument('--mode', default='render')
    ap.add_argument('--compiled')
    ap.add_argument('--out', required=True)
    ap.add_argument('--threads', type=int, default=0)
    ap.add_argument('--frame', type=int, default=0)
    ap.add_argument('--frames', default='')
    ap.add_argument('--format', default='glb')
    ap.add_argument('--count', type=int, default=6)
    ap.add_argument('--fps', type=float, default=24)
    ap.add_argument('--step', type=int, default=1)
    ap.add_argument('--save-blend', action='store_true')
    return ap.parse_args(argv)


def _sync_viewport_colors():
    """رنگِ نمای Workbench (انیمیک) = رنگِ پایهٔ ماده."""
    for m in bpy.data.materials:
        if not m.use_nodes:
            continue
        p = next((n for n in m.node_tree.nodes if n.type == 'BSDF_PRINCIPLED'), None)
        if p and not p.inputs['Base Color'].is_linked:
            c = p.inputs['Base Color'].default_value
            m.diffuse_color = (c[0], c[1], c[2], 1.0)
            m.roughness = p.inputs['Roughness'].default_value if not p.inputs['Roughness'].is_linked else 0.5
        elif p:
            m.diffuse_color = (0.6, 0.55, 0.5, 1.0)


def _localize(c, base):
    """مسیرها را برای همین ماشین درست می‌کند (کارگرِ دیگر پوشهٔ دارایی‌ها را جای دیگری دارد)."""
    root = os.environ.get('UP3D_ROOT', '')
    kinds = {'environment': 'environments', 'character': 'characters', 'product': 'products', 'lighting': 'lighting'}

    def folder(blk, kind):
        f = blk.get('folder', '')
        if f and os.path.isdir(f):
            return f
        cand = os.path.join(root, 'assets', kinds[kind], blk.get('id', ''))
        return cand if os.path.isdir(cand) else f

    def rel(p):
        if not p:
            return p
        if os.path.isabs(p) and os.path.exists(p):
            return p
        q = os.path.join(base, p)
        return q if os.path.exists(q) else p
    c['environment']['folder'] = folder(c['environment'], 'environment')
    for a in c['actors']:
        a['character']['folder'] = folder(a['character'], 'character')
    for p in c['products']:
        p['folder'] = folder(p, 'product')
        p['label_image'] = rel(p.get('label_image'))
        if p['label_image'] and not os.path.isfile(p['label_image']):
            p['label_image'] = None
        if (p.get('params') or {}).get('model_path'):
            p['params']['model_path'] = rel(p['params']['model_path'])
    return c


def build_scene(c, out):
    t0 = time.time()
    bpy.ops.wm.read_factory_settings(use_empty=True)
    ctx = Context(c, out)
    stage('build')
    environments.build(ctx)
    lighting.build(ctx)
    for a in c['actors']:
        spec = dict(a['character'])
        built = characters.build(spec, a['id'], ctx.coll('actor.' + a['id']), ctx.quality)
        ctx.rigs[a['id']] = ActorRig(ctx, a, built)
    for p in c['products']:
        ctx.products[p['id']] = Product(ctx, p)
    info(stage='built', seconds=round(time.time() - t0, 1))

    stage('animate')
    for aid, rig in ctx.rigs.items():
        f = ctx.f_start
        for s in SIDES:
            rig.key_hand(s, f, rig.neutral_pos(s), rig.neutral_rot(s))
            rig.key_fingers(s, f, 'relaxed')
        rig.key_spine(f, 0, 0, 0)
        rig.key_head(f, tilt=0.0, offset=(0, 0, 0))
        ctx.set_energy(aid, c['face'].get(aid, {}).get('energy'))
    for act in sorted(c['actions'], key=lambda a: (a['f0'], a['layer'])):
        rig = ctx.rigs.get(act['actor'])
        if not rig:
            continue
        try:
            motions.apply(ctx, rig, act)
        except Exception as e:      # یک حرکتِ خراب کلِ ویدئو را نخواباند؛ در گزارش می‌آید
            traceback.print_exc()
            ctx.warn('حرکتِ %s (%s) اجرا نشد: %s' % (act['id'], act['motion'], e))
    for aid, rig in ctx.rigs.items():
        fc = c['face'].get(aid, {})
        peaks = face.head_language(ctx, rig, fc)
        rig.realize(ctx.f_start, ctx.f_end)
        if rig.face_meshes:
            ctx.report.setdefault('face', {})[aid] = face.build(ctx, rig, fc, peaks)
    info(stage='animated', seconds=round(time.time() - t0, 1))

    stage('bake')
    bake.run(ctx)
    fn = bake.series_fn(ctx)
    ctx.cameras = camera.build(ctx, fn)
    bake.gaze(ctx, fn)
    _sync_viewport_colors()
    ctx.report['build_seconds'] = round(time.time() - t0, 1)
    ctx.report['events'] = ctx.events
    info(stage='baked', seconds=ctx.report['build_seconds'])
    return ctx


def run(argv):
    args = parse(argv)
    os.makedirs(args.out, exist_ok=True)
    if args.mode == 'encode':
        stage('encode')
        render.encode(os.path.join(args.out, 'frames'), os.path.join(args.out, 'render.mp4'), args.fps, args.step)
        return
    with open(args.compiled, encoding='utf-8') as fh:
        c = json.load(fh)
    c = _localize(c, os.path.dirname(os.path.abspath(args.compiled)))
    ctx = build_scene(c, args.out)
    if args.save_blend:
        bpy.ops.wm.save_as_mainfile(filepath=os.path.join(args.out, 'scene.blend'), copy=True, compress=True)
    if args.mode == 'render':
        stage('render')
        render.setup(ctx, args.threads)
        frames = None
        if args.frames:
            a, b = args.frames.split('-')
            frames = list(range(int(a), int(b) + 1, bpy.context.scene.frame_step))
        render.render_frames(ctx, os.path.join(args.out, 'frames'), frames)
    elif args.mode == 'still':
        stage('render')
        render.setup(ctx, args.threads)
        render.still(ctx, os.path.join(args.out, 'still_%04d.png' % (args.frame or ctx.f_start)), args.frame or ctx.f_start)
    elif args.mode == 'contact':
        stage('render')
        render.setup(ctx, args.threads)
        n = max(1, args.count)
        picks = [int(ctx.f_start + (ctx.f_end - ctx.f_start) * (i + 0.5) / n) for i in range(n)]
        if args.frames:
            picks = [int(x) for x in args.frames.split(',')]
        for i, f in enumerate(picks):
            render.still(ctx, os.path.join(args.out, 'contact_%04d.png' % f), f)
            print('UP3D:PROGRESS %d %d' % (i + 1, len(picks)), flush=True)
    elif args.mode == 'export':
        from . import export
        ext = {'glb': '.glb', 'gltf': '.gltf', 'fbx': '.fbx', 'usd': '.usdc', 'blend': '.blend', 'game_pack': '.glb'}[args.format]
        name = 'scene-game-pack' if args.format == 'game_pack' else 'scene'
        export.export(ctx, args.format, os.path.join(args.out, name + ext))
    render.write_report(ctx, os.path.join(args.out, 'engine_report.json'))
    stage('done')


def entry():
    argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
    try:
        run(argv)
    except Exception:
        traceback.print_exc()
        print('UP3D:ERROR see traceback', flush=True)
        sys.exit(3)
