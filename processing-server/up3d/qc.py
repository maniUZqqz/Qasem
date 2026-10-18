"""کنترلِ کیفیتِ خودکار.

دو منبع:
 ۱. گزارشِ موتور (Blender) — اندازه‌گیریِ واقعی روی صحنه: فاصلهٔ دست تا نقطهٔ گرفتن، لغزشِ پا،
    پرشِ مفصل، شمارِ فریم‌ها.
 ۲. خودِ فایلِ ویدئو با ffprobe/ffmpeg — مدت، ابعاد، fps، صدا، فریمِ سیاه، بلندیِ صدا.
"""
import json
import re
import subprocess

from . import paths

LIMITS = {
    'grasp_mm': (15.0, 35.0),        # فاصلهٔ کفِ دست تا نقطهٔ گرفتن هنگامِ نگه‌داشتن (هشدار، خطا)
    'foot_slide_mm': (8.0, 25.0),    # جابه‌جاییِ پای کاشته‌شده
    'joint_jump_deg': (25.0, 60.0),  # بیشترین چرخشِ یک مفصل بینِ دو فریمِ پشتِ‌سرِهم
    'duration_err': (0.15, 0.6),     # اختلافِ مدت با برنامه (ثانیه)
}


def _ffprobe(path):
    probe = paths.ffprobe_binary()
    out = subprocess.run([probe, '-v', 'error', '-print_format', 'json', '-show_format', '-show_streams', path],
                         capture_output=True, text=True)
    return json.loads(out.stdout or '{}')


def _level(value, limits):
    warn, err = limits
    return 'fail' if value > err else ('warn' if value > warn else 'pass')


def check_engine_report(rep):
    checks = []
    if not rep:
        return [{'name': 'engine_report', 'level': 'warn', 'message': 'گزارشِ موتور نرسید'}]
    g = rep.get('grasp_max_mm')
    if g is not None:
        checks.append({'name': 'grasp', 'value': round(g, 1), 'level': _level(g, LIMITS['grasp_mm']),
                       'message': 'بیشترین فاصلهٔ دست تا نقطهٔ گرفتن: %.1f میلی‌متر' % g})
    f = rep.get('foot_slide_max_mm')
    if f is not None:
        checks.append({'name': 'foot_slide', 'value': round(f, 1), 'level': _level(f, LIMITS['foot_slide_mm']),
                       'message': 'بیشترین لغزشِ پا: %.1f میلی‌متر' % f})
    j = rep.get('joint_jump_max_deg')
    if j is not None:
        checks.append({'name': 'joint_jump', 'value': round(j, 1), 'level': _level(j, LIMITS['joint_jump_deg']),
                       'message': 'بیشترین پرشِ مفصل بینِ دو فریم: %.1f درجه (%s)' % (j, rep.get('joint_jump_bone', ''))})
    exp, got = rep.get('frames_expected'), rep.get('frames_rendered')
    if exp is not None:
        lvl = 'pass' if got == exp else 'fail'
        checks.append({'name': 'frames', 'value': got, 'level': lvl, 'message': 'فریم‌ها: %s از %s' % (got, exp)})
    return checks


def check_video(path, expect_duration=None, expect_size=None, expect_audio=True):
    checks = []
    info = _ffprobe(path)
    if not info.get('streams'):
        return [{'name': 'file', 'level': 'fail', 'message': 'فایلِ ویدئو خوانده نشد'}]
    v = next((s for s in info['streams'] if s.get('codec_type') == 'video'), None)
    a = next((s for s in info['streams'] if s.get('codec_type') == 'audio'), None)
    dur = float(info.get('format', {}).get('duration', 0))
    if expect_duration:
        err = abs(dur - expect_duration)
        checks.append({'name': 'duration', 'value': round(dur, 2), 'level': _level(err, LIMITS['duration_err']),
                       'message': 'مدت %.2f ثانیه (برنامه %.2f)' % (dur, expect_duration)})
    if v:
        size = (int(v['width']), int(v['height']))
        ok = (not expect_size) or tuple(expect_size) == size
        checks.append({'name': 'size', 'value': '%dx%d' % size, 'level': 'pass' if ok else 'fail',
                       'message': 'ابعاد %dx%d' % size})
        fr = v.get('avg_frame_rate', '0/1').split('/')
        fps = float(fr[0]) / float(fr[1] or 1) if fr[0] != '0' else 0
        checks.append({'name': 'fps', 'value': round(fps, 2), 'level': 'pass' if fps >= 12 else 'fail',
                       'message': 'fps %.2f' % fps})
    if expect_audio:
        checks.append({'name': 'audio', 'level': 'pass' if a else 'fail', 'message': 'صدا دارد' if a else 'صدا ندارد'})
    # فریمِ سیاه و بلندیِ صدا
    ff = paths.ffmpeg_binary() or 'ffmpeg'
    p = subprocess.run([ff, '-v', 'info', '-i', path, '-vf', 'blackdetect=d=0.25:pix_th=0.06', '-af', 'volumedetect',
                        '-f', 'null', '-'], capture_output=True, text=True)
    blacks = re.findall(r'black_start:([\d.]+) black_end:([\d.]+)', p.stderr)
    checks.append({'name': 'black', 'value': len(blacks), 'level': 'pass' if not blacks else 'fail',
                   'message': 'فریمِ سیاه ندارد' if not blacks else 'فریمِ سیاه: %s' % blacks[:3]})
    m = re.search(r'mean_volume: (-?[\d.]+) dB', p.stderr)
    if a and m:
        mv = float(m.group(1))
        lvl = 'pass' if -30 <= mv <= -8 else 'warn'
        checks.append({'name': 'loudness', 'value': mv, 'level': lvl, 'message': 'بلندیِ میانگینِ صدا %.1f dB' % mv})
    return checks


def summarize(checks):
    worst = 'pass'
    for c in checks:
        if c['level'] == 'fail':
            worst = 'fail'
        elif c['level'] == 'warn' and worst == 'pass':
            worst = 'warn'
    return {'result': worst, 'checks': checks}
