"""مونتاژِ نهایی با FFmpeg: ویدئوی رندرشده + گفتار (هر جمله سرِ زمانش) + موسیقی (زیرِ گفتار آرام می‌شود)
+ نوشته‌ها با محو شدنِ نرم ⇐ MP4 (H.264 + AAC، آمادهٔ اینستاگرام/وب)."""
import os
import re
import subprocess

from . import paths


def _ff():
    return paths.ffmpeg_binary() or 'ffmpeg'


_CFR_ARGS = None


def cfr_args():
    """گزینهٔ «نرخِ فریمِ ثابت» برای همین ffmpeg.

    ffmpeg ≥ 5.1 (و همهٔ ساخت‌های git مثلِ N-127527) «-vsync» را حذف کرده‌اند و «-fps_mode» دارند؛
    نسخه‌های قدیمی (۴.x روی ویندوز/اوبونتو) فقط «-vsync» را می‌فهمند. یک بار نسخه را می‌پرسیم.
    (ffmpeg ِ تازهٔ سرور، ۱۴۰۵/۰۷/۲۳، با «-vsync» هر رندر را در گامِ ساختِ ویدئو می‌انداخت.)
    """
    global _CFR_ARGS
    if _CFR_ARGS is None:
        _CFR_ARGS = ['-vsync', 'cfr']
        try:
            head = subprocess.run([_ff(), '-version'], capture_output=True, text=True, timeout=20).stdout.split('\n', 1)[0]
            m = re.search(r'ffmpeg version\s+n?(\d+)\.(\d+)', head)
            if ' version N-' in head or (m and (int(m.group(1)), int(m.group(2))) >= (5, 1)):
                _CFR_ARGS = ['-fps_mode', 'cfr']
        except Exception:
            pass
    return list(_CFR_ARGS)


def run(cmd):
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError('ffmpeg: ' + (p.stderr or '')[-1500:])
    return p


def voice_track(speech, duration, out_path, rate=48000):
    """speech: [{'file','start','volume'}] ⇐ یک WAV به طولِ ویدئو."""
    items = [s for s in speech if s.get('file') and os.path.isfile(s['file'])]
    cmd = [_ff(), '-v', 'error', '-y', '-f', 'lavfi', '-t', '%.3f' % duration, '-i', 'anullsrc=r=%d:cl=mono' % rate]
    for s in items:
        cmd += ['-i', s['file']]
    if not items:
        run(cmd + ['-ac', '1', out_path])
        return out_path
    parts = []
    for i, s in enumerate(items, start=1):
        ms = int(max(0.0, s['start']) * 1000)
        parts.append('[%d:a]aresample=%d,volume=%.2f,adelay=%d|%d[a%d]' % (i, rate, s.get('volume', 1.0), ms, ms, i))
    mix = ''.join('[a%d]' % i for i in range(1, len(items) + 1))
    fc = ';'.join(parts) + ';[0:a]%samix=inputs=%d:normalize=0:duration=first[out]' % (mix, len(items) + 1)
    run(cmd + ['-filter_complex', fc, '-map', '[out]', '-ac', '1', '-t', '%.3f' % duration, out_path])
    return out_path


def assemble(video_in, out_path, duration, fps, voice_wav=None, music=None, music_volume=0.14,
             overlays=(), interpolate=None, crf=18, poster=True):
    """interpolate: None | 'dup' | 'blend' (برای پیش‌نمایشی که با fps کمتر رندر شده)."""
    cmd = [_ff(), '-v', 'error', '-y', '-i', video_in]
    idx = 1
    a_voice = a_music = None
    if voice_wav:
        cmd += ['-i', voice_wav]
        a_voice = idx
        idx += 1
    if music and os.path.isfile(music):
        cmd += ['-stream_loop', '-1', '-i', music]
        a_music = idx
        idx += 1
    ov_idx = []
    for ov in overlays:
        cmd += ['-loop', '1', '-t', '%.3f' % duration, '-i', ov['file']]
        ov_idx.append((idx, ov))
        idx += 1
    v = '[0:v]'
    chain = []
    if interpolate == 'blend':
        chain.append('%sframerate=fps=%d:interp_start=0:interp_end=255[v0]' % (v, fps))
    else:
        chain.append('%sfps=%d[v0]' % (v, fps))
    cur = '[v0]'
    for n, (i, ov) in enumerate(ov_idx):
        st, en = ov['start'], ov['end']
        fd = min(0.3, max(0.08, (en - st) / 4))
        chain.append('[%d:v]format=rgba,fade=t=in:st=%.3f:d=%.3f:alpha=1,fade=t=out:st=%.3f:d=%.3f:alpha=1[o%d]' % (
            i, st, fd, max(st, en - fd), fd, n))
        chain.append("%s[o%d]overlay=0:0:enable='between(t,%.3f,%.3f)'[v%d]" % (cur, n, st, en, n + 1))
        cur = '[v%d]' % (n + 1)
    chain.append('%sformat=yuv420p[vout]' % cur)
    amap = None
    if a_voice is not None and a_music is not None:
        chain.append('[%d:a]aformat=channel_layouts=stereo,asplit=2[vo1][vo2]' % a_voice)
        chain.append('[%d:a]aformat=channel_layouts=stereo,volume=%.3f,afade=t=out:st=%.3f:d=1.2[mu]' % (
            a_music, music_volume, max(0, duration - 1.2)))
        chain.append('[mu][vo1]sidechaincompress=threshold=0.03:ratio=6:attack=20:release=400[duck]')
        chain.append('[duck][vo2]amix=inputs=2:normalize=0:duration=first[aout]')
        amap = '[aout]'
    elif a_voice is not None:
        chain.append('[%d:a]aformat=channel_layouts=stereo,loudnorm=I=-16:TP=-1.5:LRA=11[aout]' % a_voice)
        amap = '[aout]'
    elif a_music is not None:
        chain.append('[%d:a]aformat=channel_layouts=stereo,volume=%.3f[aout]' % (a_music, max(music_volume, 0.5)))
        amap = '[aout]'
    cmd += ['-filter_complex', ';'.join(chain), '-map', '[vout]']
    if amap:
        cmd += ['-map', amap, '-c:a', 'aac', '-b:a', '192k', '-ar', '48000']
    cmd += ['-c:v', 'libx264', '-preset', 'medium', '-crf', str(crf), '-pix_fmt', 'yuv420p',
            '-t', '%.3f' % duration, '-movflags', '+faststart', out_path]
    run(cmd)
    result = {'video': out_path}
    if poster:
        p = os.path.splitext(out_path)[0] + '-poster.jpg'
        run([_ff(), '-v', 'error', '-y', '-ss', '%.2f' % (duration * 0.35), '-i', out_path, '-frames:v', '1', '-q:v', '3', p])
        result['poster'] = p
    return result


def frames_to_video(frames, fps, out_path, crf=14):
    """فهرستِ فریم‌های PNG (حتی با فاصله، مثلِ 1,3,5) ⇐ ویدئوی میانی با ffmpeg (اگر هست)."""
    out_path = os.path.abspath(out_path)
    frames = [os.path.abspath(f) for f in frames]
    lst = out_path + '.txt'
    step = 1.0 / fps
    with open(lst, 'w', encoding='utf-8') as fh:
        for f in frames:
            fh.write("file '%s'\nduration %.6f\n" % (f.replace("'", "'\\''"), step))
        fh.write("file '%s'\n" % frames[-1].replace("'", "'\\''"))
    run([_ff(), '-v', 'error', '-y', '-f', 'concat', '-safe', '0', '-i', lst] + cfr_args() + ['-r', str(fps),
         '-c:v', 'libx264', '-crf', str(crf), '-preset', 'medium', '-pix_fmt', 'yuv420p', out_path])
    os.remove(lst)
    return out_path
