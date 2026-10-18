"""نوشته‌های روی تصویر (عنوان، زیرنویسِ گفتار، دعوت به خرید، قیمت، نشان) ⇐ PNG ِ شفافِ هم‌اندازهٔ ویدئو.
مونتاژ (assemble) هر کدام را در بازهٔ زمانی‌اش با محو شدنِ نرم روی ویدئو می‌گذارد."""
import os
import re

from . import fatext as T
from . import scene as S

DEFAULT_STYLE = {
    'title': {'size': 0.052, 'color': '#ffffff', 'stroke': 0.0, 'shadow': True, 'box': None, 'y': 0.09},
    'subtitle': {'size': 0.030, 'color': '#ffffff', 'box': '#000000a0', 'y': 0.80, 'radius': 0.012},
    'cta': {'size': 0.034, 'color': '#1b1408', 'bg': '#f2c14e', 'y': 0.86, 'radius': 0.03},
    'price': {'size': 0.044, 'color': '#ffffff', 'bg': '#c0392b', 'y': 0.70, 'radius': 0.02},
    'badge': {'size': 0.026, 'color': '#1b1408', 'bg': '#ffffffe0', 'y': 0.16, 'radius': 0.02},
}


def _rgba(h):
    if not h:
        return None
    h = h.lstrip('#')
    a = int(h[6:8], 16) if len(h) == 8 else 255
    return T.hex_rgb('#' + h[:6], a)


def render_overlay(item, size, style=None, out_path=None):
    from PIL import Image, ImageDraw, ImageFilter
    w, h = size
    st = dict(DEFAULT_STYLE.get(item.get('type'), DEFAULT_STYLE['title']))
    st.update(((style or {}).get(item.get('type')) or {}))
    im = Image.new('RGBA', (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    fnt = T.font(max(12, int(h * st['size'])), 'Black' if item.get('type') in ('title', 'price') else 'Bold')
    text = item.get('text', '')
    max_w = int(w * 0.84)
    lines = T.wrap(d, text, fnt, max_w)
    lh = int(fnt.size * 1.3)
    block_h = lh * len(lines)
    pos = item.get('position')
    y_frac = {'top': 0.09, 'center': 0.45, 'bottom': 0.82}.get(pos, st.get('y', 0.1))
    top = int(h * y_frac)
    widths = [T.text_size(d, ln, fnt)[0] for ln in lines] or [0]
    pad_x, pad_y = int(fnt.size * 0.7), int(fnt.size * 0.35)
    bg = _rgba(st.get('bg') or st.get('box'))
    if bg:
        bw = max(widths) + pad_x * 2
        x0 = (w - bw) // 2
        rad = int(h * st.get('radius', 0.02))
        sh = Image.new('RGBA', (w, h), (0, 0, 0, 0))
        ImageDraw.Draw(sh).rounded_rectangle([x0, top - pad_y + 6, x0 + bw, top + block_h + pad_y + 6], rad, fill=(0, 0, 0, 90))
        im.alpha_composite(sh.filter(ImageFilter.GaussianBlur(8)))
        d.rounded_rectangle([x0, top - pad_y, x0 + bw, top + block_h + pad_y], rad, fill=bg)
    if st.get('shadow'):
        sh = Image.new('RGBA', (w, h), (0, 0, 0, 0))
        T.draw_centered(ImageDraw.Draw(sh), text, fnt, w / 2, top + 3, (0, 0, 0, 170), max_w, 1.3)
        im.alpha_composite(sh.filter(ImageFilter.GaussianBlur(max(2, fnt.size // 10))))
    T.draw_centered(d, text, fnt, w / 2, top, _rgba(st.get('color', '#ffffff')), max_w, 1.3)
    if out_path:
        im.save(out_path)
    return im


def subtitle_items(speech, max_words=6):
    """زیرنویسِ خودکار از گفتار: جمله‌ها به تکه‌های چندواژه‌ای با زمانِ متناسب."""
    items = []
    for sp in speech:
        words = (sp.get('text') or '').split()
        if not words:
            continue
        chunks = []
        cur = []
        for wd in words:
            cur.append(wd)
            if len(cur) >= max_words or re.search(r'[.!?؟،,]$', wd):
                chunks.append(cur)
                cur = []
        if cur:
            chunks.append(cur)
        total = sum(len(' '.join(c)) for c in chunks) or 1
        t = sp['start']
        dur = sp.get('duration') or S.estimate_speech_seconds(sp.get('text', ''))
        for c in chunks:
            d = dur * len(' '.join(c)) / total
            items.append({'type': 'subtitle', 'text': ' '.join(c), 'start': round(t, 3), 'duration': round(d, 3)})
            t += d
    return items


def build_all(doc, size, out_dir, style=None, include_subtitles=True):
    os.makedirs(out_dir, exist_ok=True)
    items = list(doc.get('overlays', []))
    if include_subtitles and (doc.get('audio') or {}).get('subtitles', True):
        items += subtitle_items(doc.get('speech', []))
    out = []
    for i, it in enumerate(items):
        p = os.path.join(out_dir, 'ov%02d_%s.png' % (i, it.get('type', 'x')))
        render_overlay(it, size, style, p)
        out.append({'file': p, 'start': float(it['start']), 'end': S.end_of(it), 'type': it.get('type')})
    return out
