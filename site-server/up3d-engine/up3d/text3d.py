"""متن و لوگوی سه‌بعدی (موتورِ ۱٫۳).

Blender متنِ فارسی را درست نمی‌چسباند (بی‌شکل‌دهیِ حرف‌ها، راست‌به‌چپ)، پس کارِ «شکل دادن» روی سرور (نیمهٔ پنل) انجام می‌شود:

  متنِ فارسی/لاتین ──Pillow + raqm (همان فونتِ وزیرمتن)──▶ ماسکِ سیاه‌وسفیدِ بزرگ ──OpenCV──▶ خطوطِ بیرونی و سوراخ‌ها (چندضلعی)
  تصویرِ لوگو (PNG/JPG/WebP) ─────────────────────────────▶ ماسک (آلفا، یا فاصله از رنگِ زمینه) ──▶ همان

چندضلعی‌ها (متر، مبدأ = وسطِ پایینِ نوشته، +x راستِ بیننده، +z بالا) با کلیدِ `outline` در compiled.json می‌روند؛ موتورِ Blender
(products.py: سازندهٔ text3d / logo3d) آن‌ها را با ضخامت و پخ (bevel) به مدلِ واقعی تبدیل می‌کند. اگر OpenCV نباشد یا ماسک خالی
باشد، `outline` برابر None می‌ماند و موتور به یک صفحهٔ تختِ تصویری برمی‌گردد (ویدئو هیچ‌وقت نمی‌خوابد).
"""
import hashlib
import json
import os

from . import fatext as T
from . import paths

BUILDERS = ('text3d', 'logo3d')
MAX_POINTS = 14000          # سقفِ نقطه‌های یک شیء (رندر و فایلِ compiled سبک بماند)
MAX_CHARS = 80


def is_rtl(text):
    """آیا نوشته حرفِ عربی/فارسی دارد؟ (جهتِ شکل‌دهی)"""
    for ch in text or '':
        o = ord(ch)
        if 0x0600 <= o <= 0x06FF or 0x0750 <= o <= 0x077F or 0xFB50 <= o <= 0xFDFF or 0xFE70 <= o <= 0xFEFF:
            return True
    return False


def _kwargs(text):
    if T._has_raqm():
        return {'direction': 'rtl', 'language': 'fa'} if is_rtl(text) else {'direction': 'ltr', 'language': 'en'}
    return {}


def text_mask(text, weight='Black', px=420, line_gap=1.2):
    """متن ⇐ تصویرِ L (سفید = جوهر) با حاشیه. چندخطی با «\\n»."""
    from PIL import Image, ImageDraw
    text = (text or '').strip()[:MAX_CHARS * 4]
    lines = [ln.strip() for ln in text.replace('\r', '').split('\n') if ln.strip()] or ['؟']
    fnt = T.font(px, weight)
    probe = ImageDraw.Draw(Image.new('L', (8, 8)))
    boxes = [probe.textbbox((0, 0), T.shape(ln), font=fnt, **_kwargs(ln)) for ln in lines]
    pad = int(px * 0.25)
    w = max(b[2] - b[0] for b in boxes) + pad * 2
    lh = int(px * line_gap)
    h = lh * len(lines) + pad * 2
    im = Image.new('L', (w, h), 0)
    d = ImageDraw.Draw(im)
    for i, (ln, b) in enumerate(zip(lines, boxes)):
        d.text(((w - (b[2] - b[0])) / 2 - b[0], pad + i * lh + (lh - (b[3] - b[1])) / 2 - b[1]), T.shape(ln), font=fnt,
               fill=255, **_kwargs(ln))
    return im


def trace(mask, width_m, eps=0.9, min_area=10.0):
    """ماسکِ L ⇐ {'polys': [{'pts': [[x, z]...], 'hole': bool}], 'w', 'h'} به متر (وسطِ پایین = مبدأ). None اگر ماسک خالی یا OpenCV نیست."""
    try:
        import cv2
        import numpy as np
    except ImportError:
        return None
    m = (np.array(mask.convert('L')) > 127).astype('uint8') * 255
    if m.max() == 0:
        return None
    cnts, hier = cv2.findContours(m, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_NONE)
    if hier is None:
        return None
    polys, total = [], 0
    for _ in range(6):                      # اگر نقطه‌ها زیاد بود، ساده‌تر کن
        polys, total = [], 0
        for i, c in enumerate(cnts):
            if cv2.contourArea(c) < min_area:
                continue
            ap = cv2.approxPolyDP(c, min(eps, max(0.22, 0.0045 * cv2.arcLength(c, True)) * (eps / 0.9)), True)[:, 0, :]
            if len(ap) < 3:
                continue
            polys.append({'pts': ap.astype(float).tolist(), 'hole': bool(hier[0][i][3] != -1)})
            total += len(ap)
        if total <= MAX_POINTS:
            break
        eps *= 1.6
    if not polys:
        return None
    xs = [p[0] for pl in polys for p in pl['pts']]
    ys = [p[1] for pl in polys for p in pl['pts']]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    s = float(width_m) / max(1.0, x1 - x0)
    cx = (x0 + x1) / 2.0
    for pl in polys:
        pl['pts'] = [[round((x - cx) * s, 5), round((y1 - y) * s, 5)] for x, y in pl['pts']]
    return {'polys': polys, 'w': round((x1 - x0) * s, 5), 'h': round((y1 - y0) * s, 5), 'points': total,
            'bbox_px': [x0, y0, x1, y1]}


def _num(v, d, lo, hi):
    try:
        v = float(v)
    except (TypeError, ValueError):
        v = d
    return min(hi, max(lo, v))


def text_outline(params):
    """params: text، weight، width_m، line_gap ⇐ outline (یا None)."""
    text = str(params.get('text') or '').replace('|', '\n').strip()      # «|» = خطِ تازه (ورودیِ ویرایشگر تک‌خطی است)
    if not text:
        return None
    weight = params.get('weight') if params.get('weight') in ('Black', 'Bold', 'Medium', 'Regular') else 'Black'
    width = _num(params.get('width_m'), 0.5, 0.02, 6.0)
    gap = _num(params.get('line_gap'), 1.2, 0.9, 2.0)
    key = hashlib.sha1(json.dumps([text, weight, round(width, 4), gap, _font_stamp(weight), 'trace2'], ensure_ascii=False).encode('utf-8')).hexdigest()[:16]
    cache = os.path.join(paths.cache_dir('text3d'), 'text-%s.json' % key)
    if os.path.isfile(cache):
        try:
            with open(cache, encoding='utf-8') as fh:
                return json.load(fh)
        except (OSError, ValueError):
            pass
    out = trace(text_mask(text, weight, line_gap=gap), width)
    if out:
        with open(cache, 'w', encoding='utf-8') as fh:
            json.dump(out, fh)
    return out


def _font_stamp(weight):
    for name in ('Vazirmatn-%s.ttf' % weight, 'Vazirmatn-Bold.ttf'):
        p = os.path.join(paths.fonts_dir(), name)
        if os.path.isfile(p):
            return [name, os.path.getsize(p)]
    return ['default', 0]


def logo_mask(path, max_side=900, invert=False):
    """تصویرِ لوگو ⇐ (ماسکِ L، تصویرِ RGBA ِ همان اندازه). آلفا اگر معنا دارد، وگرنه فاصله از رنگِ زمینه (گوشه‌ها)."""
    import numpy as np
    from PIL import Image
    im = Image.open(path)
    im.load()
    im = im.convert('RGBA')
    im.thumbnail((max_side, max_side), Image.LANCZOS)
    a = np.array(im)
    alpha = a[:, :, 3]
    if alpha.min() < 200 and (alpha < 200).mean() > 0.02:
        mask = alpha > 127
    else:
        rgb = a[:, :, :3].astype('int32')
        h, w = rgb.shape[:2]
        corners = np.array([rgb[0, 0], rgb[0, w - 1], rgb[h - 1, 0], rgb[h - 1, w - 1]])
        bg = np.median(corners, axis=0)
        mask = np.abs(rgb - bg).sum(axis=2) > 90
    if invert:
        mask = ~mask
    return Image.fromarray((mask * 255).astype('uint8'), 'L'), im


def logo_outline(params, out_dir, uid):
    """params: logo_image، width_m ⇐ (outline یا None، مسیرِ تصویرِ روی سطحِ جلو یا None).
    تصویرِ روی سطحِ جلو = لوگوی رنگی، بریده به همان کادرِ خطوط (تا رنگِ برند حفظ شود)."""
    from PIL import Image
    src = params.get('logo_image')
    if not src or not os.path.isfile(src):
        return None, None
    width = _num(params.get('width_m'), 0.4, 0.02, 6.0)
    mask, rgba = logo_mask(src, invert=bool(params.get('invert')))
    # لبهٔ کم‌رنگ و نویز را کنار بگذار: فقط تکه‌های بزرگ
    out = trace(mask, width, eps=1.1, min_area=max(30.0, mask.size[0] * mask.size[1] * 0.00004))
    if not out:
        return None, None
    x0, y0, x1, y1 = [int(round(v)) for v in out['bbox_px']]
    crop = rgba.crop((max(0, x0), max(0, y0), min(rgba.size[0], x1 + 1), min(rgba.size[1], y1 + 1)))
    mcrop = mask.crop((max(0, x0), max(0, y0), min(rgba.size[0], x1 + 1), min(rgba.size[1], y1 + 1)))
    crop.putalpha(mcrop)
    os.makedirs(out_dir, exist_ok=True)
    face = os.path.join(out_dir, 'logo-%s.png' % uid)
    crop.save(face)
    return out, face


def attach(comp, job_dir, log=print):
    """نیمهٔ پنل: برای هر محصول/شیءِ text3d یا logo3d خطوط را در compiled بگذار و ابعادِ واقعی را بنویس."""
    inputs = os.path.join(job_dir, 'inputs')
    done = 0
    for blk in list(comp.get('products') or []) + list(comp.get('props') or []):
        if blk.get('builder') == 'primitive':      # PBR object: the real height depends on the shape
            s = _num((blk.get('params') or {}).get('size_m'), 0.12, 0.02, 0.5)
            hk = {'rounded_cube': 0.86, 'cube': 0.86, 'torus': 0.26}.get((blk.get('params') or {}).get('shape'), 1.0)
            blk['dimensions'] = [s, s, round(s * hk, 4)]
            continue
        if blk.get('builder') not in BUILDERS:
            continue
        prm = blk.setdefault('params', {})
        try:
            if blk['builder'] == 'text3d':
                o = text_outline(prm)
                face = None
            else:
                o, face = logo_outline(prm, inputs, blk['id'])
        except Exception as e:      # noqa: BLE001 — متنِ خراب ویدئو را نمی‌خواباند
            log('متنِ سه‌بعدیِ «%s» ساخته نشد: %s' % (blk.get('id'), e))
            o, face = None, None
        blk['outline'] = o
        if face:
            prm['face_image'] = 'inputs/' + os.path.basename(face)
        if o:
            depth = _num(prm.get('depth_m'), 0.05, 0.002, 0.5)
            blk['dimensions'] = [o['w'], depth, o['h']]
            done += 1
        else:
            log('هشدار: خطوطِ «%s» ساخته نشد؛ به‌جایش صفحهٔ تخت رندر می‌شود' % blk.get('id'))
            if blk['builder'] == 'text3d' and str(prm.get('text') or '').strip():
                try:        # صفحهٔ تختِ جایگزین: نوشتهٔ سفید روی شفاف
                    from PIL import Image
                    mk = text_mask(prm['text'], prm.get('weight') or 'Black')
                    bb = mk.getbbox() or (0, 0) + mk.size
                    mk = mk.crop(bb)
                    im = Image.new('RGBA', mk.size, (255, 255, 255, 0))
                    im.putalpha(mk)
                    os.makedirs(inputs, exist_ok=True)
                    fp = os.path.join(inputs, 'text-%s.png' % blk['id'])
                    im.save(fp)
                    prm['face_image'] = 'inputs/' + os.path.basename(fp)
                    w = _num(prm.get('width_m'), 0.5, 0.02, 6.0)
                    blk['dimensions'] = [w, 0.01, w * mk.size[1] / float(max(1, mk.size[0]))]
                except Exception as e:      # noqa: BLE001
                    log('صفحهٔ تختِ جایگزین هم ساخته نشد: %s' % e)
    if done:
        log('متن/لوگوی سه‌بعدی: %d شیء' % done)
    return done
