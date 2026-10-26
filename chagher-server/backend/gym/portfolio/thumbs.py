# -*- coding: utf-8 -*-
"""نسخهٔ کوچکِ عکس‌ها (WebP) — یک‌بار ساخته و در media/thumbs نگه داشته می‌شود.

چرا: عکس‌های آپلودی چند صد کیلوبایت تا چند مگ‌اند ولی روی کارت ۳۰۰ پیکسل
دیده می‌شوند. نامِ فایلِ کوچک از نام + زمانِ تغییرِ اصل ساخته می‌شود، پس عوض‌کردنِ
عکس خودبه‌خود نسخهٔ تازه می‌دهد (nginx برای /media/ کشِ ۳۰روزه دارد).
هر خطایی ⇒ همان نشانیِ اصل؛ صفحه هرگز به‌خاطرِ عکس نمی‌شکند.
"""
import hashlib
import logging
import os

from django.conf import settings

logger = logging.getLogger(__name__)


def _make(src, dst, width, height, crop):
    from PIL import Image, ImageOps
    with Image.open(src) as im:
        im = ImageOps.exif_transpose(im)
        if im.mode not in ('RGB', 'RGBA'):
            im = im.convert('RGBA' if ('A' in im.getbands() or im.mode == 'P') else 'RGB')
        if crop and height:
            im = ImageOps.fit(im, (width, height), Image.LANCZOS)
        else:
            im.thumbnail((width, height or 10000), Image.LANCZOS)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        tmp = '%s.%d.tmp' % (dst, os.getpid())
        im.save(tmp, 'WEBP', quality=82, method=4)
        os.replace(tmp, dst)


def thumbnail(field_file, width, height=None, crop=False, as_path=False):
    """نشانی (یا مسیرِ دیسکِ) نسخهٔ کوچک؛ اگر نشد، اصل. بی‌فایل ⇒ ''."""
    if not field_file:
        return ''
    try:
        src = field_file.path
        st = os.stat(src)
    except Exception:
        return '' if as_path else _safe_url(field_file)
    key = hashlib.sha1(('%s|%s|%s|%s|%s' % (field_file.name, st.st_mtime_ns, width, height, crop))
                       .encode('utf-8')).hexdigest()[:20]
    rel = 'thumbs/%dx%d%s/%s.webp' % (width, height or 0, 'c' if crop else '', key)
    dst = os.path.join(settings.MEDIA_ROOT, rel)
    if not os.path.exists(dst):
        try:
            _make(src, dst, width, height, crop)
        except Exception as exc:
            logger.warning('thumbnail failed for %s: %s', field_file.name, exc)
            return src if as_path else _safe_url(field_file)
    return dst if as_path else settings.MEDIA_URL + rel


def _safe_url(field_file):
    try:
        return field_file.url
    except Exception:
        return ''
