"""متنِ لایه‌ها: Pillow + raqm (شکل‌دهی و چیدمانِ درستِ فارسی/عربی، دوسویه) با فونتِ وزیرمتن.

``render_text(layer, canvas_w)`` ⇐ (تصویر RGBA ِ بدونِ چرخش، نقطهٔ محور در همان تصویر) — لایه سپس با همان خطِ لولهٔ لایه‌های
تصویری جابه‌جا و چرخانده می‌شود (``layers.place``).

* اندازه‌ها (size، stroke.w، shadow.blur/dx/dy، box.pad/radius) نسبت به اندازهٔ فونت‌اند؛ خودِ اندازهٔ فونت نسبت به پهنای بوم.
* اگر libraqm نباشد، مثلِ ``services.imaging.text_overlay`` با arabic_reshaper + python-bidi شکل داده می‌شود.
* فاصلهٔ حروف: متنِ لاتین ⇐ حرف‌به‌حرف؛ متنِ فارسی ⇐ فقط بینِ کلمه‌ها (اتصالِ حروف هرگز شکسته نمی‌شود).
"""
from __future__ import annotations

import math
import unicodedata
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont, features

from services.imaging import text_overlay as tov

SYSTEM_DIR = Path("/usr/share/fonts/truetype/vazirmatn")
BUNDLED_DIR = Path(tov.FONTS_DIR)
WEIGHT_FILES = {300: "Light", 400: "Regular", 500: "Medium", 600: "SemiBold", 700: "Bold", 800: "ExtraBold"}
HAS_RAQM = features.check("raqm")
MAX_LINES = 40
AUTO_WRAP = 0.94


@lru_cache(maxsize=1)
def font_files() -> dict[int, str]:
    """{وزن: مسیرِ فایل} فقط برای فایل‌هایی که واقعاً روی سرور هستند."""
    out: dict[int, str] = {}
    for weight, name in WEIGHT_FILES.items():
        for d in (SYSTEM_DIR, BUNDLED_DIR):
            p = d / f"Vazirmatn-{name}.ttf"
            if p.is_file():
                out[weight] = str(p)
                break
    return out


def font_path(weight: int) -> str:
    files = font_files()
    if not files:
        raise tov.OverlayError("هیچ فونتِ فارسی روی سرور پیدا نشد.")
    best = min(files, key=lambda w: abs(w - weight))
    return files[best]


def font_path_for(key, weight: int) -> str:
    """مسیرِ فایلِ فونتِ ``key`` (فونتِ ناشناخته یا بی‌فایل ⇒ وزیرمتن)."""
    from . import fontreg

    if isinstance(key, str) and key != fontreg.DEFAULT:
        p = fontreg.path(key, weight)
        if p:
            return p
    return font_path(weight)


@lru_cache(maxsize=64)
def _font(path: str, size: float):
    return ImageFont.truetype(path, max(4.0, size))


def is_rtl_text(text: str) -> bool:
    for ch in text:
        bidi = unicodedata.bidirectional(ch)
        if bidi in ("R", "AL"):
            return True
        if bidi == "L":
            return False
    return False


def _kw(rtl: bool) -> dict:
    if HAS_RAQM:
        return {"direction": "rtl" if rtl else "ltr", "language": "fa" if rtl else "en"}
    return {}


def _shape(text: str, rtl: bool) -> str:
    if HAS_RAQM or not text:
        return text
    if rtl:
        return tov.shape_rtl(text)
    return text


def _len(draw: ImageDraw.ImageDraw, text: str, font, rtl: bool) -> float:
    if not text:
        return 0.0
    return float(draw.textlength(_shape(text, rtl), font=font, **_kw(rtl)))


def wrap_lines(draw, text: str, font, max_w: float) -> list[str]:
    """چیدنِ حریصانهٔ کلمه‌ها در پهنای max_w؛ \\n همیشه خطِ تازه است."""
    out: list[str] = []
    for para in text.split("\n"):
        words = para.split()
        if not words:
            out.append("")
            continue
        rtl = is_rtl_text(para)
        cur = ""
        for w in words:
            trial = (cur + " " + w).strip()
            if not cur or _len(draw, trial, font, rtl) <= max_w:
                cur = trial
            else:
                out.append(cur)
                cur = w
        out.append(cur)
    return out[:MAX_LINES]


def _hex(c: str, alpha: int = 255) -> tuple[int, int, int, int]:
    c = c.lstrip("#")
    return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16), max(0, min(255, int(alpha)))


def _line_pieces(draw, line: str, font, rtl: bool, spacing_px: float):
    """[(متن، x نسبی از ابتدای خط)] و پهنای خط، با فاصلهٔ حروف/کلمه‌ها."""
    if not spacing_px or not line.strip():
        return [(line, 0.0)], _len(draw, line, font, rtl)
    if not rtl:
        pieces, x = [], 0.0
        for ch in line:
            pieces.append((ch, x))
            x += _len(draw, ch, font, False) + spacing_px
        return pieces, max(0.0, x - spacing_px)
    # فارسی: کلمه‌به‌کلمه، از راست به چپ؛ پهنای هر کلمهٔ متصل دست‌نخورده
    words = line.split(" ")
    space = _len(draw, " ", font, True)
    widths = [_len(draw, w, font, True) for w in words]
    total = sum(widths) + (len(words) - 1) * (space + spacing_px)
    pieces, x = [], total
    for w, wd in zip(words, widths):
        pieces.append((w, x - wd))
        x -= wd + space + spacing_px
    return pieces, total


def render_text(layer: dict, canvas_w: int) -> tuple[Image.Image, tuple[float, float]] | None:
    """⇐ (tile RGBA، pivot=(px, py) مرکزِ محتوا). متنِ خالی ⇒ None."""
    text = str(layer.get("text") or "")
    if not text.strip():
        return None
    size_px = max(4.0, float(layer["size"]) * canvas_w)
    path = font_path_for(layer.get("font"), int(layer.get("weight") or 700))
    font = _font(path, size_px)
    probe = ImageDraw.Draw(Image.new("L", (8, 8)))
    width_px = float(layer.get("width") or 0) * canvas_w
    given = layer.get("lines")
    if isinstance(given, list) and given:
        lines = [str(x) for x in given][:MAX_LINES]
    elif width_px > 0:
        lines = wrap_lines(probe, text, font, width_px)
    else:
        # auto width: a line longer than 94% of the canvas width is wrapped (the browser does the same)
        lines = []
        limit = AUTO_WRAP * canvas_w
        for para in text.split("\n"):
            if _len(probe, para, font, is_rtl_text(para)) > limit:
                lines.extend(wrap_lines(probe, para, font, limit))
            else:
                lines.append(para)
        lines = lines[:MAX_LINES]
    spacing_px = float(layer.get("letter_spacing") or 0) * size_px
    forced = layer.get("dir", "auto")
    align = layer.get("align", "center")

    metrics = font.getmetrics()
    asc, desc = float(metrics[0]), float(metrics[1])
    lh = size_px * float(layer.get("line_height") or 1.35)
    base_y_in_line = (lh - (asc + desc)) / 2 + asc

    laid = []
    for line in lines:
        rtl = (forced == "rtl") or (forced == "auto" and is_rtl_text(line))
        pieces, wd = _line_pieces(probe, line, font, rtl, spacing_px)
        laid.append((line, rtl, pieces, wd))
    content_w = max([wd for *_x, wd in laid] + [1.0])
    block_w = max(width_px, content_w) if width_px > 0 else content_w
    block_h = lh * len(laid)

    stroke = layer.get("stroke") or None
    shadow = layer.get("shadow") or None
    box = layer.get("box") or None
    stroke_px = int(round(float(stroke["w"]) * size_px)) if stroke else 0
    pad_box = float(box["pad"]) * size_px if box else 0.0
    sh_blur = float(shadow["blur"]) * size_px if shadow else 0.0
    sh_dx = float(shadow["dx"]) * size_px if shadow else 0.0
    sh_dy = float(shadow["dy"]) * size_px if shadow else 0.0
    margin = int(math.ceil(max(stroke_px + 2, pad_box + 2, abs(sh_dx) + sh_blur * 3 + 2, abs(sh_dy) + sh_blur * 3 + 2)))

    tw = int(math.ceil(block_w + 2 * margin))
    th = int(math.ceil(block_h + 2 * margin))
    if tw * th > 60_000_000:
        raise tov.OverlayError("متن خیلی بزرگ است.")
    ox, oy = float(margin), float(margin)            # گوشهٔ بالا-چپِ بلوکِ محتوا
    tile = Image.new("RGBA", (tw, th), (0, 0, 0, 0))

    if box:
        d = ImageDraw.Draw(tile)
        a = int(255 * float(box["opacity"]))
        d.rounded_rectangle([ox - pad_box, oy - pad_box, ox + block_w + pad_box, oy + block_h + pad_box],
                            radius=float(box["radius"]) * size_px, fill=_hex(box["color"], a))

    fill = _hex(layer["color"])
    text_layer = Image.new("RGBA", (tw, th), (0, 0, 0, 0))
    td = ImageDraw.Draw(text_layer)
    for i, (line, rtl, pieces, wd) in enumerate(laid):
        if not line.strip():
            continue
        if align == "right":
            x0 = block_w - wd
        elif align == "left":
            x0 = 0.0
        else:
            x0 = (block_w - wd) / 2
        y = oy + i * lh + base_y_in_line
        for piece, px in pieces:
            kw = _kw(rtl)
            kw["anchor"] = "ls"
            if stroke_px:
                kw.update(stroke_width=stroke_px, stroke_fill=_hex(stroke["color"]))
            td.text((ox + x0 + px, y), _shape(piece, rtl), font=font, fill=fill, **kw)

    if shadow:
        # سایه = ماسکِ متن (با کنارهٔ استروک) جابه‌جا و محو
        sm = text_layer.getchannel("A")
        sh = Image.new("RGBA", (tw, th), _hex(shadow["color"], 0))
        sh.putalpha(sm.point(lambda v: int(v * float(shadow["opacity"]))))
        sh = sh.transform(sh.size, Image.Transform.AFFINE, (1, 0, -sh_dx, 0, 1, -sh_dy), resample=Image.Resampling.BILINEAR)
        if sh_blur > 0.3:
            r, g, b, a = sh.split()
            a = a.filter(ImageFilter.GaussianBlur(sh_blur))
            sh = Image.merge("RGBA", (r, g, b, a))
        tile = Image.alpha_composite(tile, sh)
    tile = Image.alpha_composite(tile, text_layer)
    return tile, (ox + block_w / 2, oy + block_h / 2)


def layout(layer: dict, canvas_w: int) -> dict:
    """اندازه‌گیریِ بلوکِ متن بدونِ کشیدن (همان چیدمانِ ``render_text``): ⇐ {lines, block_w, block_h, size_px, line_h, widths}
    همه به پیکسلِ بومی با عرضِ ``canvas_w``. برای جاگیری و وارسیِ سرریز در طراحیِ خودکار."""
    text = str(layer.get("text") or "")
    size_px = max(4.0, float(layer["size"]) * canvas_w)
    if not text.strip():
        return {"lines": [], "block_w": 0.0, "block_h": 0.0, "size_px": size_px, "line_h": size_px, "widths": []}
    path = font_path_for(layer.get("font"), int(layer.get("weight") or 700))
    font = _font(path, size_px)
    probe = ImageDraw.Draw(Image.new("L", (8, 8)))
    width_px = float(layer.get("width") or 0) * canvas_w
    given = layer.get("lines")
    if isinstance(given, list) and given:
        lines = [str(x) for x in given][:MAX_LINES]
    elif width_px > 0:
        lines = wrap_lines(probe, text, font, width_px)
    else:
        lines = []
        limit = AUTO_WRAP * canvas_w
        for para in text.split("\n"):
            if _len(probe, para, font, is_rtl_text(para)) > limit:
                lines.extend(wrap_lines(probe, para, font, limit))
            else:
                lines.append(para)
        lines = lines[:MAX_LINES]
    spacing_px = float(layer.get("letter_spacing") or 0) * size_px
    forced = layer.get("dir", "auto")
    widths = []
    for line in lines:
        rtl = (forced == "rtl") or (forced == "auto" and is_rtl_text(line))
        widths.append(_line_pieces(probe, line, font, rtl, spacing_px)[1])
    content_w = max(widths + [1.0])
    block_w = max(width_px, content_w) if width_px > 0 else content_w
    lh = size_px * float(layer.get("line_height") or 1.35)
    return {"lines": lines, "block_w": float(block_w), "block_h": float(lh * len(lines)), "size_px": size_px,
            "line_h": float(lh), "widths": [float(w) for w in widths]}


def tile_pattern(tile: Image.Image, canvas_size: tuple[int, int], angle: float, gap: float) -> Image.Image:
    """تکرارِ چرخیدهٔ یک متن روی کلِ بوم (مثلِ واترمارکِ تکرارشونده)؛ خروجی RGBA ِ هم‌اندازهٔ بوم."""
    w, h = canvas_size
    rot = tile.rotate(-angle, expand=True, resample=Image.Resampling.BICUBIC)
    step_x, step_y = max(8, int(rot.width * gap)), max(8, int(rot.height * gap * 1.35))
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    n = 0
    for row, yy in enumerate(range(-rot.height // 2, h, step_y)):
        for xx in range(-rot.width // 2 + (row % 2) * step_x // 2, w, step_x):
            cx0, cy0 = max(0, -xx), max(0, -yy)
            cx1, cy1 = min(rot.width, w - xx), min(rot.height, h - yy)
            if cx1 > cx0 and cy1 > cy0:
                part = rot.crop((cx0, cy0, cx1, cy1))
                dst = (xx + cx0, yy + cy0)
                region = layer.crop((dst[0], dst[1], dst[0] + part.width, dst[1] + part.height))
                layer.paste(Image.alpha_composite(region, part), dst)
            n += 1
            if n > 4000:
                return layer
    return layer
