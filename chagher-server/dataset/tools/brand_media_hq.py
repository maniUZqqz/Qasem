# -*- coding: utf-8 -*-
"""نسخهٔ باکیفیتِ مدیا + لوگوی چغر (جایگزینِ brand_media.py).

چه فرقی با نسخهٔ قبل دارد:
  · بزرگ‌نمایی ۲ برابر با LANCZOS (۱۸۰ → ۳۶۰) و کمی شارپ ⇒ لبه‌ها نرم‌تر و خواناتر.
  · پالتِ رنگِ مشترک برای همهٔ فریم‌ها (قبلاً هر فریم پالتِ خودش را داشت ⇒ نویز و لرزشِ رنگ).
  · لوگو دو برابر بزرگ‌تر و تیزتر؛ نوشتهٔ CHAGHER با سایهٔ ملایم به‌جای نوارِ سفیدِ محو.
  · عکس‌ها ۵۱۲ پیکسل با کیفیتِ ۹۲.
اجرا:  python brand_media_hq.py [تعداد]      (بدون عدد = همه)
خروجی: media_hq/gif/<id>.gif  و  media_hq/thumb/<id>.jpg
"""
import io, json, os, sys
from PIL import Image, ImageSequence, ImageDraw, ImageFont, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, '..', 'exercises-dataset')
LOGO = os.path.join(HERE, '..', 'chagher-logo.webp')
OUT_GIF = os.path.join(HERE, 'media_hq', 'gif')
OUT_THUMB = os.path.join(HERE, 'media_hq', 'thumb')
DATA = os.path.join(SRC, 'data', 'exercises.json')

SCALE = 2            # ۱۸۰ → ۳۶۰
THUMB_SIZE = 512
LOGO_W = 64          # روی تصویرِ ۳۶۰
PAD = 10
TEXT = 'CHAGHER'


def load_font(size):
    for p in (r'C:\Windows\Fonts\segoeuib.ttf', r'C:\Windows\Fonts\arialbd.ttf',
              r'C:\Windows\Fonts\calibrib.ttf', r'C:\Windows\Fonts\arial.ttf'):
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                pass
    return ImageFont.load_default()


_badges = {}


def badge_for(size):
    """لایهٔ لوگو+نام، هم‌اندازهٔ تصویر (کش‌شده)."""
    if size in _badges:
        return _badges[size]
    w, h = size
    lw = max(28, int(LOGO_W * w / 360))
    font = load_font(max(12, int(20 * w / 360)))
    layer = Image.new('RGBA', (w, h), (0, 0, 0, 0))

    logo = Image.open(LOGO).convert('RGBA')
    logo = logo.resize((lw, max(1, round(logo.height * lw / logo.width))), Image.LANCZOS)

    d = ImageDraw.Draw(layer)
    tw = d.textlength(TEXT, font=font)
    th = font.size
    bx = PAD
    by = h - PAD - max(logo.height, th)

    # بدونِ کادر: پس‌زمینهٔ گیف‌ها سفید است و کادر فقط کثیفش می‌کرد. خواناییِ متن با سایهٔ خودِ حروف.

    layer.alpha_composite(logo, (bx, by))
    ty = by + (max(logo.height, th) - th) // 2
    d.text((bx + lw + 8, ty), TEXT, font=font, fill=(0, 0, 0, 70))          # سایهٔ متن
    d.text((bx + lw + 7, ty - 1), TEXT, font=font, fill=(20, 20, 20, 255))  # خودِ متن
    _badges[size] = layer
    return layer


def upscale(img, factor=SCALE):
    w, h = img.size
    big = img.resize((w * factor, h * factor), Image.LANCZOS)
    return big.filter(ImageFilter.UnsharpMask(radius=1.2, percent=55, threshold=3))


def brand_gif(src, dst):
    im = Image.open(src)
    frames_rgb = []
    for fr in ImageSequence.Iterator(im):
        f = upscale(fr.convert('RGB'))
        f = f.convert('RGBA')
        f.alpha_composite(badge_for(f.size))
        frames_rgb.append(f.convert('RGB'))

    # یک پالتِ مشترک از همهٔ فریم‌ها ⇒ رنگ بینِ فریم‌ها نمی‌لرزد
    w, h = frames_rgb[0].size
    strip = Image.new('RGB', (w, h * len(frames_rgb)))
    for i, f in enumerate(frames_rgb):
        strip.paste(f, (0, i * h))
    pal = strip.quantize(colors=255, method=Image.MEDIANCUT, dither=Image.NONE)

    frames_p = [f.quantize(palette=pal, dither=Image.NONE) for f in frames_rgb]
    frames_p[0].save(dst, save_all=True, append_images=frames_p[1:],
                     loop=im.info.get('loop', 0), duration=im.info.get('duration', 60),
                     optimize=True, disposal=2)
    return len(frames_p)


def brand_jpg(src, dst):
    im = Image.open(src).convert('RGB')
    if im.width < THUMB_SIZE:
        im = im.resize((THUMB_SIZE, THUMB_SIZE), Image.LANCZOS)
        im = im.filter(ImageFilter.UnsharpMask(radius=1.4, percent=60, threshold=3))
    im = im.convert('RGBA')
    im.alpha_composite(badge_for(im.size))
    im.convert('RGB').save(dst, quality=92, subsampling=0, optimize=True)


def main():
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    os.makedirs(OUT_GIF, exist_ok=True)
    os.makedirs(OUT_THUMB, exist_ok=True)
    data = json.load(io.open(DATA, encoding='utf-8'))
    if limit:
        data = data[:limit]
    done = failed = 0
    for i, x in enumerate(data, 1):
        gid = x['id']
        g_src = os.path.join(SRC, x['gif_url'].replace('/', os.sep))
        t_src = os.path.join(SRC, x['image'].replace('/', os.sep))
        g_dst = os.path.join(OUT_GIF, gid + '.gif')
        t_dst = os.path.join(OUT_THUMB, gid + '.jpg')
        try:
            if os.path.exists(g_src) and not os.path.exists(g_dst):
                brand_gif(g_src, g_dst)
            if os.path.exists(t_src) and not os.path.exists(t_dst):
                brand_jpg(t_src, t_dst)
            done += 1
        except Exception as e:
            failed += 1
            print('خطا', gid, e, flush=True)
        if i % 50 == 0:
            print('%d/%d' % (i, len(data)), flush=True)
    print('تمام — %d انجام، %d خطا' % (done, failed))


if __name__ == '__main__':
    main()
