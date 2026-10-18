"""مسیرها. همه از ریشهٔ پروژه یا متغیرهای محیطی؛ روی لینوکس و ویندوز یکسان."""
import os
import shutil
import sys

ROOT = os.environ.get('UP3D_ROOT') or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.environ.get('UP3D_DATA') or os.path.join(ROOT, 'data')
ENGINE = os.path.join(ROOT, 'engine')
VENDOR = os.path.join(ROOT, 'vendor')


def asset_roots():
    """ریشه‌های دارایی: assets/ پروژه + بسته‌های اضافه (UP3D_ASSETS با جداکنندهٔ سیستم)."""
    roots = [os.path.join(ROOT, 'assets')]
    extra = os.environ.get('UP3D_ASSETS', '')
    roots += [p for p in extra.split(os.pathsep) if p.strip()]
    user_pack = os.path.join(DATA, 'asset-packs')
    if os.path.isdir(user_pack):
        roots += [os.path.join(user_pack, d) for d in sorted(os.listdir(user_pack))
                  if os.path.isdir(os.path.join(user_pack, d))]
    return [r for r in roots if os.path.isdir(r)]


def blender_binary():
    cand = [os.environ.get('UP3D_BLENDER', '')]
    if sys.platform.startswith('win'):
        cand += [os.path.join(VENDOR, 'blender', 'blender.exe')]
        pf = os.environ.get('ProgramFiles', r'C:\Program Files')
        base = os.path.join(pf, 'Blender Foundation')
        if os.path.isdir(base):
            for d in sorted(os.listdir(base), reverse=True):
                cand.append(os.path.join(base, d, 'blender.exe'))
    else:
        cand += [os.path.join(VENDOR, 'blender', 'blender'), shutil.which('blender') or '']
    for c in cand:
        if c and os.path.isfile(c):
            return c
    return None


def blender_user_resources():
    """پوشهٔ کاربرِ Blender که افزونهٔ MPFB و دارایی‌هایش در آن است (قابلِ حمل)."""
    return os.environ.get('UP3D_BLENDER_USER') or os.path.join(VENDOR, 'blender-user')


def ffmpeg_binary():
    if os.environ.get('UP3D_FFMPEG'):
        return os.environ['UP3D_FFMPEG']
    local = os.path.join(VENDOR, 'ffmpeg', 'ffmpeg.exe' if sys.platform.startswith('win') else 'ffmpeg')
    if os.path.isfile(local):
        return local
    return shutil.which('ffmpeg')


def ffprobe_binary():
    ff = ffmpeg_binary()
    if ff:
        d, b = os.path.split(ff)
        cand = os.path.join(d, b.replace('ffmpeg', 'ffprobe'))
        if os.path.isfile(cand):
            return cand
    return shutil.which('ffprobe') or 'ffprobe'


def fonts_dir():
    return os.path.join(ROOT, 'assets', 'fonts')


def job_dir(job_id):
    d = os.path.join(DATA, 'jobs', str(job_id))
    os.makedirs(d, exist_ok=True)
    return d


def cache_dir(kind):
    d = os.path.join(DATA, 'cache', kind)
    os.makedirs(d, exist_ok=True)
    return d
