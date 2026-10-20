# -*- coding: utf-8 -*-
"""مهرِ برندِ چغر روی تصویرهای آپلودی.

خواستِ مالک (۱۴۰۵/۰۷/۱۵): «وقتی در جنگو آموزشِ حرکت آپلود می‌کنم، خودش لوگو و
اسم را مثلِ بقیه روی تصویر بیندازد.» دیتاستِ اولیه این مهر را داشت؛ هر چیزی که
از این به بعد دستی اضافه شود هم باید همان شکلی باشد، وگرنه کتابخانه دوتکه
به‌نظر می‌رسد.

نکته‌های مهمِ پیاده‌سازی:
  · گیف **متحرک** است؛ باید فریم‌به‌فریم مهر بخورد و زمان‌بندی و حلقه‌اش حفظ شود.
    یک‌باره مهرزدن، انیمیشن را از بین می‌برد.
  · مهر فقط هنگامِ **آپلودِ تازه** زده می‌شود (در ادمین، وقتی فایل عوض شده).
    وگرنه هر بار ذخیره، یک مهرِ تازه روی مهرِ قبلی می‌نشست.
  · اگر هر چیزی خطا بدهد، فایلِ اصلی دست‌نخورده برمی‌گردد — آپلود نباید
    به‌خاطرِ زیباسازی شکست بخورد.
"""
import io
import logging
import os

from django.conf import settings

logger = logging.getLogger(__name__)

LOGO_CANDIDATES = [
    os.path.join(settings.BASE_DIR, 'pdf_generator', 'assets', 'chegher_logo.png'),
    '/www/wwwroot/Cheghar/dataset/chagher-logo.webp',
]
FONT_CANDIDATES = [
    '/usr/share/fonts/truetype/lato/Lato-Bold.ttf',
    '/usr/share/fonts/truetype/lato/Lato-Heavy.ttf',
    '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
]

BRAND_TEXT = 'CHAGHER'
BAND_RATIO = 0.13          # ارتفاعِ نوارِ سفیدِ پایین، نسبت به ارتفاعِ تصویر
MIN_BAND = 34
TEXT_COLOR = (31, 39, 51)
BAND_COLOR = (255, 255, 255)


def _first_existing(paths):
    for p in paths:
        if p and os.path.exists(p):
            return p
    return None


def _load_font(size):
    from PIL import ImageFont
    path = _first_existing(FONT_CANDIDATES)
    if path:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            pass
    return ImageFont.load_default()


def _build_band(width, band_h):
    """نوارِ سفیدِ پایین با لوگو و نامِ برند — یک‌بار ساخته و روی همهٔ فریم‌ها می‌نشیند."""
    from PIL import Image, ImageDraw

    band = Image.new('RGBA', (width, band_h), BAND_COLOR + (255,))
    draw = ImageDraw.Draw(band)

    pad = max(8, int(band_h * 0.22))
    x = pad

    logo_path = _first_existing(LOGO_CANDIDATES)
    if logo_path:
        try:
            logo = Image.open(logo_path).convert('RGBA')
            lh = int(band_h * 0.56)
            lw = max(1, int(logo.width * lh / logo.height))
            logo = logo.resize((lw, lh), Image.LANCZOS)
            band.alpha_composite(logo, (x, (band_h - lh) // 2))
            x += lw + pad
        except Exception as exc:
            logger.warning('لوگوی مهر بار نشد: %s', exc)

    font = _load_font(max(11, int(band_h * 0.42)))
    try:
        bbox = draw.textbbox((0, 0), BRAND_TEXT, font=font)
        th = bbox[3] - bbox[1]
        ty = (band_h - th) // 2 - bbox[1]
    except Exception:
        ty = band_h // 4
    draw.text((x, ty), BRAND_TEXT, font=font, fill=TEXT_COLOR + (255,))
    return band


def _stamp_frame(frame, band):
    """یک فریم + نوار ⇒ تصویرِ بلندتر با نوارِ برند در پایین."""
    from PIL import Image
    frame = frame.convert('RGBA')
    out = Image.new('RGBA', (frame.width, frame.height + band.height), (255, 255, 255, 255))
    out.paste(frame, (0, 0))
    out.alpha_composite(band, (0, frame.height))
    return out


def stamp(data, filename=''):
    """بایت‌های تصویر ⇒ بایت‌های مهرخورده. هر خطایی ⇒ همان ورودیِ دست‌نخورده."""
    try:
        from PIL import Image, ImageSequence
    except Exception:
        return data, filename

    try:
        src = Image.open(io.BytesIO(data))
        is_gif = (src.format or '').upper() == 'GIF' and getattr(src, 'n_frames', 1) > 1
        band_h = max(MIN_BAND, int(src.height * BAND_RATIO))
        band = _build_band(src.width, band_h)
        out = io.BytesIO()

        if is_gif:
            # ⚠ فریم‌به‌فریم، وگرنه انیمیشن می‌میرد
            frames = []
            durations = []
            for f in ImageSequence.Iterator(src):
                durations.append(f.info.get('duration', src.info.get('duration', 80)))
                frames.append(_stamp_frame(f, band).convert('P', palette=Image.ADAPTIVE, colors=255))
            frames[0].save(
                out, format='GIF', save_all=True, append_images=frames[1:],
                duration=durations or 80, loop=src.info.get('loop', 0),
                disposal=2, optimize=True,
            )
            return out.getvalue(), filename

        stamped = _stamp_frame(src, band)
        ext = os.path.splitext(filename or '')[1].lower()
        if ext == '.png':
            stamped.save(out, format='PNG', optimize=True)
        else:
            stamped.convert('RGB').save(out, format='JPEG', quality=88,
                                        optimize=True, progressive=True)
            if ext not in ('.jpg', '.jpeg'):
                filename = os.path.splitext(filename or 'image')[0] + '.jpg'
        return out.getvalue(), filename
    except Exception as exc:
        logger.warning('مهرِ برند زده نشد (%s): %s', filename, exc)
        return data, filename


def stamp_field(file_field):
    """یک FileField/ImageField را در جا مهر می‌زند. True اگر عوض شد."""
    if not file_field:
        return False
    try:
        file_field.open('rb')
        data = file_field.read()
    except Exception as exc:
        logger.warning('فایل خوانده نشد: %s', exc)
        return False
    name = os.path.basename(file_field.name or '')
    new_data, new_name = stamp(data, name)
    if new_data is data:
        return False
    from django.core.files.base import ContentFile
    file_field.save(new_name or name, ContentFile(new_data), save=False)
    return True
