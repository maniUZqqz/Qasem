"""برچسبِ محصول: نام، برند، رنگ و عکسِ کاربر ⇐ یک تصویر که روی بدنهٔ مدلِ سه‌بعدی می‌نشیند."""
import hashlib
import json
import os

from . import fatext as T
from . import paths


def make_label(product_asset, product_entry, out_dir=None):
    """product_asset: manifest؛ product_entry: آیتمِ محصول در سند (name, params). خروجی: مسیرِ PNG یا None."""
    from PIL import Image, ImageDraw, ImageFilter
    spec = product_asset.get('label') or {}
    if not spec:
        return None
    params = dict(product_asset.get('params_defaults', {}))
    params.update({k: v for k, v in (product_entry.get('params') or {}).items() if v not in (None, '')})
    name = product_entry.get('name') or params.get('title') or ''
    brand = params.get('brand') or ''
    tagline = params.get('tagline') or ''
    bg = params.get('label_color') or spec.get('background', '#f4efe6')
    fg = params.get('text_color') or spec.get('text', '#2b2118')
    accent = params.get('accent_color') or spec.get('accent', '#b08d57')
    img_path = params.get('label_image')
    w, h = spec.get('px', [1024, 512])
    key = hashlib.sha1(json.dumps([product_asset.id, name, brand, tagline, bg, fg, accent, img_path,
                                   os.path.getmtime(img_path) if img_path and os.path.isfile(img_path) else 0, w, h,
                                   spec.get('style')], ensure_ascii=False).encode('utf-8')).hexdigest()[:16]
    out_dir = out_dir or paths.cache_dir('labels')
    out = os.path.join(out_dir, 'label-%s.png' % key)
    if os.path.isfile(out):
        return out

    im = Image.new('RGBA', (w, h), T.hex_rgb(bg))
    d = ImageDraw.Draw(im)
    style = spec.get('style', 'classic')
    # بافتِ ملایمِ کاغذ
    noise = Image.effect_noise((w, h), 22).filter(ImageFilter.GaussianBlur(0.7)).convert('RGBA')
    im = Image.blend(im, noise, 0.035)
    d = ImageDraw.Draw(im)
    pad = int(min(w, h) * 0.06)
    if style in ('classic', 'perfume', 'jar'):
        d.rectangle([pad, pad, w - pad, h - pad], outline=T.hex_rgb(accent), width=max(2, h // 120))
        d.rectangle([pad * 1.5, pad * 1.5, w - pad * 1.5, h - pad * 1.5], outline=T.hex_rgb(accent, 160), width=1)
    photo_area = None
    if img_path and os.path.isfile(img_path):
        ph = Image.open(img_path).convert('RGBA')
        if style == 'box':
            photo_area = (int(w * 0.08), int(h * 0.08), int(w * 0.92), int(h * 0.62))
        else:
            photo_area = (int(w * 0.62), int(h * 0.18), int(w * 0.9), int(h * 0.82))
        bw, bh = photo_area[2] - photo_area[0], photo_area[3] - photo_area[1]
        ph.thumbnail((bw, bh), Image.LANCZOS)
        im.alpha_composite(ph, (photo_area[0] + (bw - ph.width) // 2, photo_area[1] + (bh - ph.height) // 2))
    text_cx = w * (0.36 if photo_area and style != 'box' else 0.5)
    text_w = w * (0.5 if photo_area and style != 'box' else 0.8)
    top = h * (0.66 if style == 'box' and photo_area else 0.22)
    if brand:
        f = T.font(int(h * 0.09), 'Medium')
        top = T.draw_centered(d, brand, f, text_cx, top, T.hex_rgb(accent), text_w) + h * 0.02
    if name:
        f = T.font(int(h * (0.16 if len(name) < 14 else 0.12)), 'Bold')
        top = T.draw_centered(d, name, f, text_cx, top, T.hex_rgb(fg), text_w) + h * 0.03
    if tagline:
        f = T.font(int(h * 0.07), 'Regular')
        T.draw_centered(d, tagline, f, text_cx, top, T.hex_rgb(fg, 200), text_w)
    im.convert('RGB').save(out, quality=95)
    return out
