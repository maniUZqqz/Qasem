# -*- coding: utf-8 -*-
"""کتابخانهٔ رسانهٔ هر پروژه.

فایل‌ها داخلِ خودِ پروژه‌اند (static/site-media/) تا با تولیدِ کد و ZIP و Git همراه پروژه بروند.
نامِ فایل همیشه از روی محتوا ساخته می‌شود؛ نامِ فرستاده‌شده فقط برای نمایش ذخیره می‌شود، پس راهی برای
نوشتن بیرون از پوشه نیست. نوعِ فایل از روی خودِ محتوا سنجیده می‌شود، نه پسوند.
"""
import hashlib
import io
import os
import re

from PIL import Image, ImageOps, UnidentifiedImageError

MAX_IMAGE_BYTES = 12 * 1024 * 1024
MAX_VIDEO_BYTES = 40 * 1024 * 1024
MAX_PROJECT_BYTES = 400 * 1024 * 1024
MAX_PIXELS = 50_000_000
MAX_WIDTH = 1920
VARIANT_WIDTH = 800
MEDIA_DIR = 'static/site-media'
SAFE_NAME = re.compile(r'^[a-f0-9]{16}(-\d{2,4})?\.(webp|jpg|png|gif|mp4|webm)$')
CONTENT_TYPES = {'webp': 'image/webp', 'jpg': 'image/jpeg', 'png': 'image/png', 'gif': 'image/gif',
                 'mp4': 'video/mp4', 'webm': 'video/webm'}


class MediaError(ValueError):
    pass


def _sniff_video(head):
    if len(head) > 12 and head[4:8] == b'ftyp':
        return 'mp4'
    if head[:4] == b'\x1a\x45\xdf\xa3':
        return 'webm'
    return None


def _clean_display_name(name):
    base = os.path.basename(str(name or '').replace('\\', '/'))
    base = re.sub(r'[\x00-\x1f<>:"|?*]', '', base).strip()
    return base[:120] or 'فایل'


def _write(project, name, data):
    folder = os.path.join(str(project.path), MEDIA_DIR)
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, name), 'wb') as fh:
        fh.write(data)
    return '%s/%s' % (MEDIA_DIR, name)


def used_bytes(project):
    from apps.projects.models import MediaAsset
    return sum(MediaAsset.objects.filter(project=project).values_list('size', flat=True))


def save_upload(project, upload, alt=''):
    """⇒ MediaAsset (اگر همین فایل قبلاً آمده باشد همان را برمی‌گرداند)."""
    from apps.projects.models import MediaAsset
    size = getattr(upload, 'size', None)
    if size is None:
        raise MediaError('فایلی نیامد.')
    upload.seek(0)
    head = upload.read(32)
    upload.seek(0)
    video = _sniff_video(head)
    limit = MAX_VIDEO_BYTES if video else MAX_IMAGE_BYTES
    if size > limit:
        raise MediaError('حجمِ فایل زیاد است؛ حداکثر %d مگابایت.' % (limit // (1024 * 1024)))
    if used_bytes(project) + size > MAX_PROJECT_BYTES:
        raise MediaError('فضای رسانهٔ این پروژه پر شده؛ چند فایلِ قدیمی را حذف کن.')
    name = _clean_display_name(getattr(upload, 'name', ''))
    if video:
        data = upload.read()
        sha = hashlib.sha256(data).hexdigest()[:16]
        found = MediaAsset.objects.filter(project=project, sha=sha).first()
        if found:
            return found
        rel = _write(project, '%s.%s' % (sha, video), data)
        return MediaAsset.objects.create(project=project, kind='video', name=name, alt=alt, rel_path=rel, size=len(data), sha=sha)
    return _save_image(project, upload, name, alt)


def _save_image(project, upload, name, alt):
    from apps.projects.models import MediaAsset
    try:
        probe = Image.open(upload)
        fmt = probe.format
        w, h = probe.size
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        raise MediaError('این فایل تصویر یا ویدیوی معتبری نیست. JPG، PNG، WebP، GIF یا MP4 بفرست.')
    if fmt not in ('JPEG', 'PNG', 'WEBP', 'GIF', 'MPO'):
        raise MediaError('این نوع تصویر پذیرفته نمی‌شود. JPG، PNG، WebP یا GIF بفرست.')
    if w * h > MAX_PIXELS:
        raise MediaError('ابعادِ تصویر بیش از اندازه بزرگ است.')
    upload.seek(0)
    if fmt == 'GIF' and getattr(probe, 'is_animated', False):
        data = upload.read()                  # گیفِ متحرک دست‌نخورده می‌ماند
        sha = hashlib.sha256(data).hexdigest()[:16]
        found = MediaAsset.objects.filter(project=project, sha=sha).first()
        if found:
            return found
        rel = _write(project, '%s.gif' % sha, data)
        return MediaAsset.objects.create(project=project, kind='image', name=name, alt=alt, rel_path=rel,
                                         width=w, height=h, size=len(data), sha=sha)
    try:
        img = Image.open(upload)
        img.load()
        img = ImageOps.exif_transpose(img)
    except (OSError, ValueError, SyntaxError):
        raise MediaError('این تصویر خراب است.')
    img = img.convert('RGBA' if img.mode in ('RGBA', 'LA', 'P', 'PA') else 'RGB')
    if img.width > MAX_WIDTH:
        img = img.resize((MAX_WIDTH, round(img.height * MAX_WIDTH / img.width)), Image.LANCZOS)

    def encode(pic):
        buf = io.BytesIO()
        pic.save(buf, 'WEBP', quality=82, method=4)     # بی‌EXIF: موقعیتِ مکانی و … در فایل نمی‌ماند
        return buf.getvalue()

    data = encode(img)
    sha = hashlib.sha256(data).hexdigest()[:16]
    found = MediaAsset.objects.filter(project=project, sha=sha).first()
    if found:
        return found
    rel = _write(project, '%s.webp' % sha, data)
    variants = {}
    total = len(data)
    if img.width > VARIANT_WIDTH + 100:
        small = img.resize((VARIANT_WIDTH, round(img.height * VARIANT_WIDTH / img.width)), Image.LANCZOS)
        sdata = encode(small)
        variants[str(VARIANT_WIDTH)] = _write(project, '%s-%d.webp' % (sha, VARIANT_WIDTH), sdata)
        total += len(sdata)
    return MediaAsset.objects.create(project=project, kind='image', name=name, alt=alt, rel_path=rel, variants=variants,
                                     width=img.width, height=img.height, size=total, sha=sha)


def where_used(project, asset):
    """عنوانِ جاهایی که از این فایل استفاده کرده‌اند."""
    from apps.projects.models import Design, SiteTheme
    needle = '"m:%d"' % asset.pk
    out = []
    import json
    for d in Design.objects.filter(project=project).select_related('page'):
        if needle in json.dumps(d.draft or {}) or needle in json.dumps(d.published or {}):
            out.append(d.page.title if d.page_id else d.get_target_display())
    return out


def delete_asset(asset):
    folder = str(asset.project.path)
    for rel in [asset.rel_path] + list((asset.variants or {}).values()):
        target = os.path.normpath(os.path.join(folder, rel))
        if target.startswith(os.path.join(folder, MEDIA_DIR) + os.sep):
            try:
                os.remove(target)
            except OSError:
                pass
    asset.delete()


def public_path(project, name):
    """مسیرِ واقعیِ فایل برای سروِ عمومی؛ None اگر نامِ مجاز نباشد."""
    if not SAFE_NAME.match(name or ''):
        return None
    full = os.path.join(str(project.path), MEDIA_DIR, name)
    return full if os.path.isfile(full) else None


def asset_json(a):
    return {'id': a.pk, 'ref': 'm:%d' % a.pk, 'kind': a.kind, 'name': a.name, 'alt': a.alt, 'width': a.width, 'height': a.height,
            'size': a.size, 'url': '/api/v1/studio/builder-media/%s/%s' % (a.project.slug, os.path.basename(a.rel_path)),
            'thumb': '/api/v1/studio/builder-media/%s/%s' % (a.project.slug, os.path.basename((a.variants or {}).get(str(VARIANT_WIDTH)) or a.rel_path))}
