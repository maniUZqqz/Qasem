"""خطِ تولید. دو نیمه دارد تا رندرِ سنگین روی هر کارگری (سرور یا PC با GPU) اجرا شود:

  نیمهٔ پنل (prepare)   سند ⇐ وارسی/ترمیم ⇐ برچسب‌ها ⇐ صدا (TTS) ⇐ لب (ویسم روی صدای واقعی) ⇐ compiled.json
  نیمهٔ کارگر (render)  compiled.json ⇐ Blender ⇐ فریم‌ها ⇐ ویدئوی میانی + گزارشِ موتور
  نیمهٔ پنل (finish)    کنترلِ کیفیت ⇐ مونتاژ (صدا، موسیقی، نوشته‌ها) ⇐ MP4 ⇐ کنترلِ کیفیتِ فایل

وضعیت‌ها: PENDING ⇐ PLANNING ⇐ PLANNED ⇐ SCENE_BUILDING ⇐ RENDERING ⇐ QUALITY_CHECK ⇐ ASSEMBLING ⇐ COMPLETED | FAILED
"""
import glob
import json
import os
import shutil
import time

from . import assemble, blender, compiler, labels, lipsync, overlays, paths, qc, tts
from . import scene as S
from .assets import registry
from .validate import repair, validate

STATES = ('PENDING', 'PLANNING', 'PLANNED', 'SCENE_BUILDING', 'RENDERING', 'QUALITY_CHECK', 'ASSEMBLING',
          'COMPLETED', 'FAILED', 'CANCELLED')


class PipelineError(Exception):
    pass


def _write(path, data):
    with open(path, 'w', encoding='utf-8') as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1, default=str)


def prepare(doc, job_dir, profile_id, tts_settings=None, log=print, reg=None, profile_overrides=None):
    """نیمهٔ پنل. خروجی: مسیرِ compiled.json و خلاصه.
    profile_overrides: تنظیمِ دستیِ کیفیت (compiler.clean_quality) روی پروفایل."""
    reg = reg or registry()
    job_dir = os.path.abspath(job_dir)
    os.makedirs(job_dir, exist_ok=True)
    doc, changes, rep = repair(doc, reg)
    if not rep.ok:
        raise PipelineError('سند ایرادِ ترمیم‌نشدنی دارد: ' + ' | '.join(i['message'] for i in rep.errors[:5]))
    for c in changes:
        log('ترمیم: ' + c)
    _write(os.path.join(job_dir, 'scene.json'), doc)
    inputs = os.path.join(job_dir, 'inputs')
    os.makedirs(inputs, exist_ok=True)
    # برچسبِ محصول‌ها
    label_images = {}
    for p in doc['products']:
        pa = reg.get('product', p['asset'])
        try:
            src = labels.make_label(pa, p)
        except Exception as e:     # برچسب نشد ⇐ محصولِ بی‌برچسب بهتر از ویدئوی خراب است
            log('برچسب ساخته نشد: %s' % e)
            src = None
        if src:
            dst = os.path.join(inputs, 'label-%s.png' % p['id'])
            shutil.copyfile(src, dst)
            label_images[p['id']] = 'inputs/label-%s.png' % p['id']
        mp = (p.get('params') or {}).get('model_path')
        if mp and os.path.isfile(mp):
            dst = os.path.join(inputs, 'model-%s%s' % (p['id'], os.path.splitext(mp)[1]))
            shutil.copyfile(mp, dst)
            p['params']['model_path'] = os.path.relpath(dst, job_dir).replace('\\', '/')
    # اشیای ویرایشگرِ آزاد: مدلِ بارگذاری‌شده و عکسِ برچسب همراهِ کار به کارگر می‌رود
    for x in doc.get('props') or []:
        prm = x.get('params') or {}
        for key, name in (('model_path', 'model'), ('label_image', 'label')):
            src = prm.get(key)
            if src and os.path.isabs(src) and os.path.isfile(src):
                dst = os.path.join(inputs, '%s-%s%s' % (name, x['id'], os.path.splitext(src)[1]))
                shutil.copyfile(src, dst)
                prm[key] = os.path.relpath(dst, job_dir).replace('\\', '/')
    # صدا + لب
    audio = {}
    ff = paths.ffmpeg_binary() or 'ffmpeg'
    for sp in doc['speech']:
        voice = reg.get('voice', sp.get('voice')) or reg.default('voice')
        t0 = time.time()
        out = tts.synthesize(sp['text'], voice, tts_settings, os.path.join(job_dir, 'audio'), sp.get('style'))
        al = lipsync.align_to_audio(sp['text'], out['file'], ffmpeg=ff)
        audio[sp['id']] = {'file': os.path.relpath(out['file'], job_dir).replace(os.sep, '/'),'duration': out['duration'], 'visemes': al['visemes'],
                           'energy': al['energy'], 'energy_rate': al['energy_rate'], 'provider': out['provider']}
        log('صدا: «%s…» %.1fث (%s%s) در %.1fث' % (sp['text'][:24], out['duration'], out['provider'],
                                                  '، کش' if out['cached'] else '', time.time() - t0))
    # اگر صدای واقعی بلندتر از تخمین بود، زمان‌بندی دوباره ترمیم شود
    changed = False
    for sp in doc['speech']:
        real = audio[sp['id']]['duration']
        if abs(real - (sp.get('duration') or 0)) > 0.05:
            sp['duration'] = real
            changed = True
    need = max([sp['start'] + audio[sp['id']]['duration'] + 0.4 for sp in doc['speech']] + [0])
    if need > doc['output']['duration']:
        doc['output']['duration'] = round(min(60.0, need), 2)
        for sh in doc['shots'][-1:]:
            sh['duration'] = round(doc['output']['duration'] - sh['start'], 3)
        log('مدت با صدای واقعی %.1f ثانیه شد' % doc['output']['duration'])
        changed = True
    if changed:
        _write(os.path.join(job_dir, 'scene.json'), doc)
    comp = compiler.compile_scene(doc, reg, profile_id, audio=audio, label_images=label_images,
                                  profile_overrides=profile_overrides)
    ship_pack_assets(comp, job_dir, log)
    if profile_overrides:
        log('تنظیمِ دستیِ کیفیت: ' + '، '.join('%s=%s' % kv for kv in profile_overrides.items()))
    _write(os.path.join(job_dir, 'compiled.json'), comp)
    _write(os.path.join(job_dir, 'audio.json'), {k: {kk: vv for kk, vv in v.items() if kk not in ('energy',)}
                                                 for k, v in audio.items()})
    return {'compiled': os.path.join(job_dir, 'compiled.json'), 'frames': comp['frame_end'], 'fps': comp['fps'],
            'frame_step': comp['profile'].get('frame_step', 1), 'resolution': comp['resolution'],
            'duration': comp['duration'], 'doc': doc}


def ship_pack_assets(comp, job_dir, log=print):
    """دارایی‌های بستهٔ کاربر (data/asset-packs) روی کارگرِ دیگر نیستند ⇐ پوشه‌شان کنارِ کار کپی می‌شود
    (inputs/packs/<kind>/<id>/) و موتور (main._localize) از همان‌جا می‌خواند."""
    base_assets = os.path.normpath(os.path.join(paths.ROOT, 'assets'))
    shipped = {}

    def ship(blk, kind, aid):
        f = blk.get('folder') or ''
        if not f or not os.path.isdir(f):
            return None
        nf = os.path.normpath(f)
        if nf == base_assets or nf.startswith(base_assets + os.sep):
            return None
        key = (kind, aid)
        if key not in shipped:
            rel = 'inputs/packs/%s/%s' % (kind, aid)
            dst = os.path.join(job_dir, *rel.split('/'))
            if os.path.isdir(dst):
                shutil.rmtree(dst)
            shutil.copytree(f, dst, ignore=shutil.ignore_patterns('thumbnail.jpg', 'preview.mp4', '*.blend1', '__pycache__'))
            shipped[key] = rel
        blk['pack_rel'] = shipped[key]
        return shipped[key]
    ship(comp['environment'], 'environments', comp['environment'].get('id'))
    if comp.get('lighting'):
        ship(comp['lighting'], 'lighting', comp['lighting'].get('id'))
    for a in comp['actors']:
        ship(a['character'], 'characters', a['character'].get('id'))
    for p in comp['products']:
        ship(p, 'products', p.get('asset') or p.get('id'))
    for x in comp.get('props') or []:
        ship(x, 'products', x.get('asset') or x.get('id'))
    for act in comp['actions']:
        if (act.get('source') or {}).get('type') == 'clip':
            ship(act, 'motions', act['motion'])
    if shipped:
        log('دارایی‌های بستهٔ کاربر همراهِ کار: ' + '، '.join('%s/%s' % k for k in shipped))
    return shipped


def render(job_dir, on_event=None, should_cancel=None, nice=10, threads=0, log_path=None, mode='render', extra=()):
    """نیمهٔ کارگر: Blender ⇐ فریم‌ها ⇐ render.mp4 (+ engine_report.json)."""
    job_dir = os.path.abspath(job_dir)
    comp = os.path.join(job_dir, 'compiled.json')
    res = blender.run_engine(mode, comp, job_dir, on_event, should_cancel, nice, threads, extra, log_path=log_path)
    if mode != 'render':
        return res
    with open(comp, encoding='utf-8') as fh:
        c = json.load(fh)
    step = int(c['profile'].get('frame_step', 1))
    frames = sorted(glob.glob(os.path.join(job_dir, 'frames', 'f_*.png')))
    if not frames:
        raise PipelineError('هیچ فریمی رندر نشد')
    out = os.path.join(job_dir, 'render.mp4')
    if paths.ffmpeg_binary():
        assemble.frames_to_video(frames, c['fps'] / step, out)
    else:
        blender.run_engine('encode', comp, job_dir, on_event, should_cancel, nice, threads,
                           ['--fps', str(c['fps']), '--step', str(step)], log_path=log_path)
    return res


def finish(job_dir, log=print, reg=None):
    """نیمهٔ پنل: کنترلِ کیفیت + مونتاژ."""
    reg = reg or registry()
    job_dir = os.path.abspath(job_dir)
    with open(os.path.join(job_dir, 'compiled.json'), encoding='utf-8') as fh:
        c = json.load(fh)
    with open(os.path.join(job_dir, 'scene.json'), encoding='utf-8') as fh:
        doc = json.load(fh)
    rep = {}
    rp = os.path.join(job_dir, 'engine_report.json')
    if os.path.isfile(rp):
        with open(rp, encoding='utf-8') as fh:
            rep = json.load(fh)
    checks = qc.check_engine_report(rep)
    w, h = c['resolution']
    ovs = overlays.build_all(doc, (w, h), os.path.join(job_dir, 'overlays'),
                             style=(reg.default('overlay_style') or {}))
    speech = [{'file': os.path.join(job_dir, sp['audio']) if sp.get('audio') else None, 'start': sp['start']}
              for sp in c['speech']]
    missing = [s for s in speech if not (s['file'] and os.path.isfile(s['file']))]
    if missing:
        log('هشدار: %d فایلِ گفتار پیدا نشد' % len(missing))
    voice = assemble.voice_track(speech, c['duration'], os.path.join(job_dir, 'voice.wav')) if speech else None
    music = None
    mus = (doc.get('audio') or {}).get('music')
    if mus:
        ma = reg.get('music', mus)
        music = ma.path(ma.get('file')) if ma else (mus if os.path.isfile(mus) else None)
    step = int(c['profile'].get('frame_step', 1))
    final = os.path.join(job_dir, 'final.mp4')
    res = assemble.assemble(os.path.join(job_dir, 'render.mp4'), final, c['duration'], c['fps'], voice, music,
                            (doc.get('audio') or {}).get('music_volume', 0.14), ovs,
                            interpolate=('dup' if step > 1 else None))
    checks += qc.check_video(final, c['duration'], (w, h), expect_audio=bool(voice or music))
    summary = qc.summarize(checks)
    _write(os.path.join(job_dir, 'qc.json'), summary)
    log('کنترلِ کیفیت: %s' % summary['result'])
    return {'video': final, 'poster': res.get('poster'), 'qc': summary}


def run_local(doc, profile_id='preview', job_dir=None, tts_settings=None, log=print, threads=0):
    """همهٔ خط در یک فرایند (خطِ فرمان و آزمون)."""
    job_dir = os.path.abspath(job_dir or paths.job_dir('local-%d' % int(time.time())))
    info = prepare(doc, job_dir, profile_id, tts_settings, log)
    log('ساختِ صحنه و رندر: %d فریم (گام %d) %sx%s' % (info['frames'], info['frame_step'], *info['resolution']))

    def ev(kind, data):
        if kind == 'progress' and (data['frame'] % 10 == 0 or data['frame'] == data['total']):
            log('  %s/%s  (%.0fث)' % (data['frame'], data['total'], data['elapsed']))
        elif kind == 'stage':
            log('  مرحله: ' + data.get('text', ''))
    render(job_dir, ev, threads=threads, log_path=os.path.join(job_dir, 'engine.log'))
    out = finish(job_dir, log)
    return out
