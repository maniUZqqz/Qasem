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
DEFAULT_WRAP_RATIO = 4.5    # نوشتهٔ تک‌خطی که پهن‌تر از این نسبت (پهنا ÷ ارتفاع) شود خودکار چندخطی می‌شود
MAX_WRAP_LINES = 4


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


def _ink_ratio(mask):
    """نسبتِ پهنا به ارتفاعِ خودِ جوهر (نه کادرِ با حاشیه)."""
    bb = mask.getbbox()
    if not bb:
        return 0.0
    return (bb[2] - bb[0]) / float(max(1, bb[3] - bb[1]))


def _split_lines(words, widths, n):
    """کلمه‌ها (به ترتیبِ منطقی) را به n خط بشکن، طوری که پهن‌ترین خط کم‌ترین باشد (برنامه‌ریزیِ پویا). widths = پهنای هر کلمه (+ فاصله)."""
    m = len(words)
    pre = [0.0]
    for w in widths:
        pre.append(pre[-1] + w)
    inf = float('inf')
    best = [[inf] * (m + 1) for _ in range(n + 1)]       # best[k][i] = کمینهٔ پهن‌ترین خط وقتی i کلمهٔ اول در k خط جا شده‌اند
    cut = [[0] * (m + 1) for _ in range(n + 1)]
    best[0][0] = 0.0
    for k in range(1, n + 1):
        for i in range(k, m + 1):
            for j in range(k - 1, i):
                v = max(best[k - 1][j], pre[i] - pre[j])
                if v < best[k][i]:
                    best[k][i], cut[k][i] = v, j
    out, i = [], m
    for k in range(n, 0, -1):
        j = cut[k][i]
        out.append(' '.join(words[j:i]))
        i = j
    return list(reversed(out))


def wrap_text(text, weight='Black', max_ratio=DEFAULT_WRAP_RATIO, px=160):
    """نوشتهٔ تک‌خطیِ خیلی پهن را به ۲ تا ۴ خطِ متوازن بشکن تا ارتفاعِ حروف (و خوانایی در قابِ عمودی) خوب بماند.
    فقط وقتی کار می‌کند که نوشته «خط تازه» نداشته باشد و حداقل دو کلمه داشته باشد؛ وگرنه همان نوشته برمی‌گردد.
    نسبت از روی مسیرِ واقعیِ شکل‌دهی (Pillow + raqm) سنجیده می‌شود، پس برای فارسی و لاتین و ترکیبشان درست است."""
    text = (text or '').strip()
    if max_ratio is None or max_ratio <= 0 or '\n' in text:
        return text
    words = text.split()
    if len(words) < 2:
        return text
    first = _ink_ratio(text_mask(text, weight, px=px))
    if first <= max_ratio:
        return text
    from PIL import Image, ImageDraw
    fnt = T.font(px, weight)
    probe = ImageDraw.Draw(Image.new('L', (8, 8)))
    space = probe.textlength(' ', font=fnt) or px * 0.25
    widths = [probe.textlength(T.shape(w), font=fnt, **_kwargs(w)) + space for w in words]
    best_text, best_ratio = text, first
    for n in range(2, min(MAX_WRAP_LINES, len(words)) + 1):
        cand = '\n'.join(_split_lines(words, widths, n))
        r = _ink_ratio(text_mask(cand, weight, px=px))
        if r < best_ratio:
            best_text, best_ratio = cand, r
        if r <= max_ratio:
            break
    return best_text


def _smooth_contour(c, sigma):
    """خطِ بسته (N×1×2، پیکسل‌ها) را با هسته‌ٔ گاوسی نرم کن (چرخه‌ای): پله‌های یک‌پیکسلیِ لبه صاف می‌شوند، گوشه‌ها فقط به اندازهٔ σ گرد می‌شوند."""
    import numpy as np
    pts = c[:, 0, :].astype('float64')
    n = len(pts)
    r = int(min(n // 2 - 1, max(1, round(3 * sigma))))
    if n < 8 or r < 1:
        return c
    k = np.exp(-0.5 * (np.arange(-r, r + 1) / float(sigma)) ** 2)
    k /= k.sum()
    pad = np.concatenate([pts[-r:], pts, pts[:r]])
    xs = np.convolve(pad[:, 0], k, mode='valid')
    ys = np.convolve(pad[:, 1], k, mode='valid')
    return np.stack([xs, ys], axis=1).astype('float32').reshape(-1, 1, 2)


def trace(mask, width_m, eps=0.9, min_area=10.0, smooth=0.0):
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
            if smooth > 0:
                c = _smooth_contour(c, smooth)
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
    ratio = _num(params.get('wrap_ratio'), DEFAULT_WRAP_RATIO, 0.0, 12.0)     # 0 = نشکن
    try:
        text = wrap_text(text, weight, ratio)
    except Exception:       # noqa: BLE001 — شکستنِ خودکار اختیاری است؛ نوشته همان تک‌خط می‌ماند
        pass
    key = hashlib.sha1(json.dumps([text, weight, round(width, 4), gap, _font_stamp(weight), 'trace3'], ensure_ascii=False).encode('utf-8')).hexdigest()[:16]
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


SMOOTH_SIDE = 1600          # ضلعِ بلندِ ماسکِ لوگو بعد از بزرگ‌کردن (هم‌پایهٔ یک لوگوی ۵۰۰ پیکسلی تا لبه‌ها پله‌پله نشوند)


def logo_mask(path, max_side=SMOOTH_SIDE, invert=False):
    """تصویرِ لوگو ⇐ (ماسکِ L، تصویرِ RGBA ِ همان اندازه). آلفا اگر معنا دارد، وگرنه فاصله از رنگِ زمینه (گوشه‌ها).

    لوگوهای کوچک (مثلاً ۵۰۰ پیکسل) اگر همان‌طور آستانه‌گیری شوند، لبه‌هاشان پله‌پله می‌شود و ضخامت‌دادن آن پله‌ها را بزرگ نشان می‌دهد.
    پس تصویر اول با Lanczos تا ~۱۶۰۰ پیکسل بزرگ می‌شود، «پوشش» (آلفا یا فاصله از زمینه) به‌صورتِ پیوسته کمی محو می‌شود
    و بعد در ۵۰٪ آستانه‌گیری می‌شود؛ هم‌ارزِ یک لبهٔ زیرپیکسلی و صاف، بی‌آنکه گوشه‌های تیز گِرد شوند."""
    import numpy as np
    from PIL import Image, ImageFilter
    im = Image.open(path)
    im.load()
    im = im.convert('RGBA')
    w0, h0 = im.size
    s = float(max_side) / max(w0, h0)
    if s > 1.0:
        s = min(s, 4.0)
        im = im.resize((max(2, int(round(w0 * s))), max(2, int(round(h0 * s)))), Image.LANCZOS)
    else:
        im.thumbnail((max_side, max_side), Image.LANCZOS)
        s = 1.0
    a = np.array(im)
    alpha = a[:, :, 3]
    if alpha.min() < 200 and (alpha < 200).mean() > 0.02:
        cover = alpha.astype('float32') / 255.0
    else:
        rgb = a[:, :, :3].astype('float32')
        h, w = rgb.shape[:2]
        corners = np.array([rgb[0, 0], rgb[0, w - 1], rgb[h - 1, 0], rgb[h - 1, w - 1]])
        bg = np.median(corners, axis=0)
        dist = np.abs(rgb - bg).sum(axis=2)
        cover = np.clip((dist - 60.0) / 60.0, 0.0, 1.0)         # 0 تا 1، نیمه‌راهش همان آستانهٔ قدیمیِ ۹۰
    if invert:
        cover = 1.0 - cover
    cv = Image.fromarray((cover * 255).astype('uint8'), 'L')
    if s > 1.0:
        cv = cv.filter(ImageFilter.GaussianBlur(radius=max(0.8, 0.45 * s)))
    mask = (np.array(cv) > 127)
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
    # ماسکِ بزرگ‌شده: لبه را نرم کن (σ نسبت به اندازهٔ ماسک) و با تلرانسِ ریز چندضلعی بساز ⇐ منحنی‌ها بی‌پله و بی‌وجه‌های درشت
    out = trace(mask, width, eps=0.8, min_area=max(30.0, mask.size[0] * mask.size[1] * 0.00004), smooth=max(0.8, 0.0028 * max(mask.size)))
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
