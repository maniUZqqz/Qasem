"""نوشتنِ متنِ فارسی روی تصویر (چسبیدنِ حروف + راست‌به‌چپ)."""
import os

from . import paths

_RAQM = None


def _has_raqm():
    global _RAQM
    if _RAQM is None:
        try:
            from PIL import features
            _RAQM = bool(features.check('raqm'))
        except Exception:
            _RAQM = False
    return _RAQM


def font(size, weight='Bold'):
    from PIL import ImageFont
    for name in ('Vazirmatn-%s.ttf' % weight, 'Vazirmatn-Bold.ttf', 'Vazirmatn-Regular.ttf'):
        p = os.path.join(paths.fonts_dir(), name)
        if os.path.isfile(p):
            if _has_raqm():
                return ImageFont.truetype(p, size, layout_engine=ImageFont.Layout.RAQM)
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def shape(text):
    """با raqm خودِ Pillow شکل می‌دهد؛ وگرنه arabic_reshaper + bidi."""
    if _has_raqm():
        return text
    try:
        import arabic_reshaper
        from bidi.algorithm import get_display
        return get_display(arabic_reshaper.reshape(text))
    except ImportError:
        return text


def draw_kwargs():
    return {'direction': 'rtl', 'language': 'fa'} if _has_raqm() else {}


def text_size(draw, text, fnt):
    box = draw.textbbox((0, 0), shape(text), font=fnt, **draw_kwargs())
    return box[2] - box[0], box[3] - box[1], box


def wrap(draw, text, fnt, max_w):
    words = (text or '').split()
    lines, cur = [], ''
    for w in words:
        trial = (cur + ' ' + w).strip()
        if text_size(draw, trial, fnt)[0] <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def draw_centered(draw, text, fnt, cx, top, fill, max_w=None, line_gap=1.25, stroke=0, stroke_fill=None):
    lines = wrap(draw, text, fnt, max_w) if max_w else [text]
    y = top
    for ln in lines:
        w, h, box = text_size(draw, ln, fnt)
        draw.text((cx - w / 2 - box[0], y - box[1]), shape(ln), font=fnt, fill=fill,
                  stroke_width=stroke, stroke_fill=stroke_fill, **draw_kwargs())
        y += int(fnt.size * line_gap)
    return y


def hex_rgb(h, alpha=255):
    h = (h or '#ffffff').lstrip('#')
    if len(h) == 3:
        h = ''.join(c * 2 for c in h)
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4)) + (alpha,)
