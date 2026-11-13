"""صفحهٔ نمونهٔ اپلیکیشن برای گوشیِ نمایش (موتورِ ۱٫۳).

اگر مشتری اسکرین‌شاتِ واقعیِ اپ را نداده باشد، قالب‌های «نمایشِ اپلیکیشن» سه صفحهٔ گرافیکیِ تمیز با رنگ‌ها، نام، شعار و جمله‌های **خودِ برند**
می‌سازند (هیچ آمار، قیمت یا امکانی از خودمان نمی‌نویسیم؛ هر نوشته از brief می‌آید). این صفحه‌ها «ماکت»اند، نه تصویرِ واقعیِ محصول؛ هر وقت
اسکرین‌شاتِ واقعی رسید (screen_image…)، همان جایگزین می‌شود.

  make_screens(brand, tagline, lines, primary, secondary, logo=None, count=3, size=(1170, 2532)) ⇐ [مسیرِ PNG ...]   (کش‌شده در data/cache/screens)
"""
import hashlib
import json
import os

from . import fatext as T
from . import paths


def _is_rtl(text):
    from .text3d import is_rtl
    return is_rtl(text)


def _kw(text):
    if not T._has_raqm():
        return {}
    return {'direction': 'rtl', 'language': 'fa'} if _is_rtl(text) else {'direction': 'ltr', 'language': 'en'}


def _size(d, text, fnt):
    box = d.textbbox((0, 0), T.shape(text), font=fnt, **_kw(text))
    return box[2] - box[0], box[3] - box[1], box


def _wrap(d, text, fnt, max_w):
    words = (text or '').split()
    lines, cur = [], ''
    for w in words:
        trial = (cur + ' ' + w).strip()
        if _size(d, trial, fnt)[0] <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def _draw(d, text, fnt, x, y, fill, align='center', max_w=None, gap=1.35):
    """متنِ چندخطی؛ x = وسط (center) یا لبهٔ راست (right). خروجی: y پایانِ متن."""
    lines = _wrap(d, text, fnt, max_w) if max_w else [text]
    for ln in lines:
        w, h, box = _size(d, ln, fnt)
        left = x - w / 2 if align == 'center' else (x - w if align == 'right' else x)
        d.text((left - box[0], y - box[1]), T.shape(ln), font=fnt, fill=fill, **_kw(ln))
        y += int(fnt.size * gap)
    return y


def _shape(im, op, *args, fill, **kw):
    """A translucent shape: ImageDraw replaces pixels on an RGBA image instead of blending, so it is drawn on its own layer and composited."""
    from PIL import Image, ImageDraw
    layer = Image.new('RGBA', im.size, (0, 0, 0, 0))
    getattr(ImageDraw.Draw(layer), op)(*args, fill=fill, **kw)
    im.alpha_composite(layer)


def _gradient(size, c1, c2, angle='diag'):
    from PIL import Image
    w, h = size
    base = Image.new('RGB', (w, h), c1)
    top = Image.new('RGB', (w, h), c2)
    mask = Image.linear_gradient('L').resize((w, h))
    if angle == 'diag':
        mask = mask.rotate(-24, expand=True, resample=Image.BICUBIC).resize((w, h))
    return Image.composite(top, base, mask)


def _shadow_card(im, box, radius, fill, blur=26, offset=14, alpha=60):
    from PIL import Image, ImageDraw, ImageFilter
    w, h = im.size
    sh = Image.new('RGBA', (w, h), (0, 0, 0, 0))
    x0, y0, x1, y1 = box
    ImageDraw.Draw(sh).rounded_rectangle([x0, y0 + offset, x1, y1 + offset], radius, fill=(10, 30, 60, alpha))
    im.alpha_composite(sh.filter(ImageFilter.GaussianBlur(blur)))
    ImageDraw.Draw(im).rounded_rectangle(box, radius, fill=fill)


def _status_bar(d, w, color):
    """نوارِ وضعیتِ ساده (ساعت و باتری به‌شکلِ نشانه، بی‌عدد و بی‌ادعا)."""
    y = int(w * 0.05)
    d.rounded_rectangle([w * 0.78, y, w * 0.87, y + w * 0.032], w * 0.01, outline=color, width=max(2, w // 300))
    d.rounded_rectangle([w * 0.79, y + w * 0.006, w * 0.84, y + w * 0.026], w * 0.006, fill=color)
    for i in range(3):
        d.rectangle([w * (0.70 + i * 0.016), y + w * (0.024 - 0.006 * i), w * (0.71 + i * 0.016), y + w * 0.03], fill=color)


def _logo_tile(im, cx, cy, side, logo, initial, color):
    from PIL import Image, ImageDraw
    d = ImageDraw.Draw(im)
    x0, y0 = cx - side / 2, cy - side / 2
    _shadow_card(im, (x0, y0, x0 + side, y0 + side), side * 0.24, (255, 255, 255, 255), blur=30, offset=18, alpha=70)
    d = ImageDraw.Draw(im)
    if logo and os.path.isfile(logo):
        try:
            lg = Image.open(logo).convert('RGBA')
            lg.thumbnail((int(side * 0.66), int(side * 0.66)), Image.LANCZOS)
            im.alpha_composite(lg, (int(cx - lg.width / 2), int(cy - lg.height / 2)))
            return
        except Exception:      # noqa: BLE001 — لوگوی خراب صفحه را نخواباند
            pass
    f = T.font(int(side * 0.56), 'Black')
    w, h, box = _size(d, initial, f)
    d.text((cx - w / 2 - box[0], cy - h / 2 - box[1]), T.shape(initial), font=f, fill=color, **_kw(initial))


def _splash(brand, tagline, lines, c1, c2, logo, size, cta_label):
    from PIL import Image, ImageDraw
    w, h = size
    im = _gradient(size, c1, c2).convert('RGBA')
    d = ImageDraw.Draw(im, 'RGBA')
    for r, (x, y), a in ((0.55, (0.95, 0.12), 40), (0.42, (0.0, 0.62), 34), (0.3, (0.9, 0.9), 30)):
        _shape(im, 'ellipse', [w * x - w * r, h * y - w * r, w * x + w * r, h * y + w * r], fill=(255, 255, 255, a))
    _status_bar(d, w, (255, 255, 255, 230))
    _logo_tile(im, w / 2, h * 0.32, w * 0.34, logo, (brand or '؟')[:1], c1)
    d = ImageDraw.Draw(im, 'RGBA')
    y = _draw(d, brand, T.font(int(w * 0.13), 'Black'), w / 2, h * 0.46, (255, 255, 255, 255), max_w=w * 0.84)
    if tagline:
        y = _draw(d, tagline, T.font(int(w * 0.052), 'Medium'), w / 2, y + h * 0.012, (255, 255, 255, 220), max_w=w * 0.78)
    bw, bh = w * 0.7, h * 0.07
    x0, y0 = (w - bw) / 2, h * 0.85
    _shadow_card(im, (x0, y0, x0 + bw, y0 + bh), bh / 2, (255, 255, 255, 255), blur=24, offset=12, alpha=55)
    d = ImageDraw.Draw(im, 'RGBA')
    f = T.font(int(w * 0.05), 'Bold')
    tw, th, box = _size(d, cta_label, f)
    d.text((w / 2 - tw / 2 - box[0], y0 + bh / 2 - th / 2 - box[1]), T.shape(cta_label), font=f, fill=c1, **_kw(cta_label))
    return im


def _cards(brand, tagline, lines, c1, c2, logo, size, cta_label):
    from PIL import Image, ImageDraw
    w, h = size
    im = Image.new('RGBA', size, (247, 250, 255, 255))
    d = ImageDraw.Draw(im, 'RGBA')
    d.rounded_rectangle([-w * 0.1, -h * 0.1, w * 1.1, h * 0.215], w * 0.12, fill=T.hex_rgb(c1))
    _status_bar(d, w, (255, 255, 255, 230))
    _draw(d, brand, T.font(int(w * 0.075), 'Black'), w * 0.92, h * 0.095, (255, 255, 255, 255), align='right')
    if tagline:
        _draw(d, tagline, T.font(int(w * 0.04), 'Medium'), w * 0.92, h * 0.145, (255, 255, 255, 210), align='right', max_w=w * 0.8)
    items = [ln for ln in (lines or []) if ln][:3]
    top = h * 0.30
    card_h = h * 0.15
    for i, text in enumerate(items):
        y0 = top + i * (card_h + h * 0.028)
        _shadow_card(im, (w * 0.07, y0, w * 0.93, y0 + card_h), w * 0.045, (255, 255, 255, 255))
        d = ImageDraw.Draw(im, 'RGBA')
        col = T.hex_rgb(c1 if i % 2 == 0 else c2)
        cx, cy, r = w * 0.84, y0 + card_h / 2, w * 0.062
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=col)
        d.line([(cx - r * 0.45, cy), (cx - r * 0.1, cy + r * 0.38), (cx + r * 0.5, cy - r * 0.38)], fill=(255, 255, 255, 255),
               width=max(4, int(w * 0.011)), joint='curve')
        fnt = T.font(int(w * 0.047), 'Bold')
        lines_n = _wrap(d, text, fnt, w * 0.6)
        ty = y0 + card_h / 2 - len(lines_n) * fnt.size * 1.35 / 2 + fnt.size * 0.12
        _draw(d, text, fnt, w * 0.76, ty, (27, 43, 69, 255), align='right', max_w=w * 0.6)
    bw, bh = w * 0.86, h * 0.065
    x0, y0 = (w - bw) / 2, h * 0.86
    d.rounded_rectangle([x0, y0, x0 + bw, y0 + bh], bh / 2, fill=T.hex_rgb(c1))
    f = T.font(int(w * 0.047), 'Bold')
    tw, th, box = _size(d, cta_label, f)
    d.text((w / 2 - tw / 2 - box[0], y0 + bh / 2 - th / 2 - box[1]), T.shape(cta_label), font=f, fill=(255, 255, 255, 255), **_kw(cta_label))
    return im


def _summary(brand, tagline, lines, c1, c2, logo, size, cta_label):
    from PIL import Image, ImageDraw
    w, h = size
    im = _gradient(size, c2, _mix(c2, '#000000', 0.5)).convert('RGBA')
    d = ImageDraw.Draw(im, 'RGBA')
    _shape(im, 'ellipse', [w * 0.62, -h * 0.1, w * 1.25, h * 0.1], fill=(255, 255, 255, 22))
    _status_bar(d, w, (255, 255, 255, 230))
    head = (lines or [brand])[0] if lines else brand
    y = _draw(d, head, T.font(int(w * 0.082), 'Black'), w * 0.92, h * 0.17, (255, 255, 255, 255), align='right', max_w=w * 0.82)
    y += h * 0.03
    for text in [ln for ln in (lines or [])[1:] if ln][:4]:
        _shape(im, 'rounded_rectangle', [w * 0.07, y, w * 0.93, y + h * 0.085], w * 0.035, fill=(255, 255, 255, 34))
        d = ImageDraw.Draw(im, 'RGBA')
        cx, cy, r = w * 0.855, y + h * 0.0425, w * 0.04
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=T.hex_rgb(c1))
        d.line([(cx - r * 0.45, cy), (cx - r * 0.1, cy + r * 0.38), (cx + r * 0.5, cy - r * 0.38)], fill=(255, 255, 255, 255),
               width=max(3, int(w * 0.008)), joint='curve')
        fnt = T.font(int(w * 0.042), 'Medium')
        _draw(d, text, fnt, w * 0.80, y + h * 0.0425 - fnt.size * 0.62, (255, 255, 255, 240), align='right', max_w=w * 0.62, gap=1.2)
        y += h * 0.105
    bw, bh = w * 0.86, h * 0.065
    x0, y0 = (w - bw) / 2, h * 0.86
    d.rounded_rectangle([x0, y0, x0 + bw, y0 + bh], bh / 2, fill=(255, 255, 255, 255))
    f = T.font(int(w * 0.047), 'Bold')
    tw, th, box = _size(d, cta_label, f)
    d.text((w / 2 - tw / 2 - box[0], y0 + bh / 2 - th / 2 - box[1]), T.shape(cta_label), font=f, fill=T.hex_rgb(c2), **_kw(cta_label))
    return im


def _mix(a, b, t):
    ra, rb = T.hex_rgb(a)[:3], T.hex_rgb(b)[:3]
    return tuple(int(x + (y - x) * t) for x, y in zip(ra, rb))


KINDS = (_splash, _cards, _summary)


def make_screens(brand, tagline='', lines=(), primary='#126F85', secondary='#163F75', logo=None, count=3, size=(1170, 2532),
                 cta_label='شروع کنید', out_dir=None):
    """count صفحهٔ نمونه (۱ تا ۴): آغازین، کارت‌ها، جمع‌بندی (و دوباره آغازین)."""
    lines = [str(x).strip() for x in (lines or []) if str(x).strip()]
    out_dir = out_dir or paths.cache_dir('screens')
    key = hashlib.sha1(json.dumps([brand, tagline, lines, primary, secondary, logo, os.path.getmtime(logo) if logo and os.path.isfile(logo) else 0,
                                   list(size), cta_label, 'v2'], ensure_ascii=False).encode('utf-8')).hexdigest()[:14]
    outs = []
    for i in range(max(1, min(4, int(count)))):
        out = os.path.join(out_dir, 'screen-%s-%d.png' % (key, i))
        if not os.path.isfile(out):
            fn = KINDS[i % len(KINDS)]
            if fn is _summary and len(lines) < 2:
                fn = _splash
            if fn is _cards and not lines:
                fn = _splash
            fn(brand or '', tagline or '', lines, primary, secondary, logo, tuple(size), cta_label).convert('RGB').save(out)
        outs.append(out)
    return outs
