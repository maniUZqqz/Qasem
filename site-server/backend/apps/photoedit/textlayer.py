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


#: متنِ خمیده (warp): هر ستونِ پیکسلِ متن به اندازهٔ dy(u) جابه‌جا و s(u) برابر در راستای عمود کشیده می‌شود (u = −۱..۱ از چپِ بلوک تا راست).
#: همان فرمول در مرورگر (pro/gl/raster.ts › warpParams) ⇒ پیش‌نمایش = خروجی.
WARP_STYLES = ("arc", "wave", "flag", "bulge", "rise")
_WARP_DY = {"arc": 1.4, "wave": 0.7, "flag": 0.6, "rise": 1.0, "bulge": 0.0}
UL_OFFSET, STRIKE_OFFSET, LINE_W = 0.12, -0.28, 0.065


def warp_params(style: str, amount: float, u, size_px: float):
    """⇒ (dy، s) برای ستون‌های u (آرایهٔ numpy)."""
    import numpy as np

    u = np.asarray(u, dtype=np.float64)
    if style == "arc":
        return -amount * size_px * 1.4 * (1 - u * u), np.ones_like(u)
    if style == "wave":
        return amount * size_px * 0.7 * np.sin(math.pi * (u + 1)), np.ones_like(u)
    if style == "flag":
        return amount * size_px * 0.6 * np.sin(1.5 * math.pi * (u + 1)), np.ones_like(u)
    if style == "rise":
        return -amount * size_px * 1.0 * u, np.ones_like(u)
    return np.zeros_like(u), 1 + amount * 0.7 * (1 - u * u)           # bulge


def warp_extra(style: str, amount: float, size_px: float, th: int) -> int:
    """حاشیهٔ عمودیِ اضافه (بالا و پایین، هر کدام) تا متنِ خمیده بریده نشود."""
    e = abs(amount) * _WARP_DY.get(style, 0.0) * size_px
    if style == "bulge":
        e += max(0.0, 0.7 * amount) * th / 2
    return int(math.ceil(e)) + 2


def warp_tile(tile: Image.Image, style: str, amount: float, size_px: float) -> tuple[Image.Image, int]:
    """⇒ (تایلِ خمیده، extra). مرکزِ تایل (محور) ثابت می‌ماند چون حاشیه بالا و پایین یکسان است."""
    import cv2
    import numpy as np

    tw, th = tile.size
    extra = warp_extra(style, amount, size_px, th)
    nh = th + 2 * extra
    x = np.arange(tw, dtype=np.float64)
    u = ((x + 0.5) / tw) * 2 - 1
    dy, s = warp_params(style, amount, u, size_px)
    yo = np.arange(nh, dtype=np.float64)[:, None]
    src_y = th / 2 + (yo + 0.5 - extra - dy[None, :] - th / 2) / s[None, :] - 0.5
    map_x = np.broadcast_to(x[None, :], (nh, tw)).astype(np.float32)
    pm = np.asarray(tile.convert("RGBa"))
    out = cv2.remap(pm, map_x, src_y.astype(np.float32), cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0, 0))
    return Image.fromarray(out, "RGBa").convert("RGBA"), extra


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


def _line_pieces(draw, line: str, font, rtl: bool, spacing_px: float, word_extra: float = 0.0):
    """[(متن، x نسبی از ابتدای خط)] و پهنای خط، با فاصلهٔ حروف/کلمه‌ها. ``word_extra`` فقط به فاصلهٔ میانِ کلمه‌ها اضافه می‌شود (تراز دوطرفه)."""
    if (not spacing_px and not word_extra) or not line.strip():
        return [(line, 0.0)], _len(draw, line, font, rtl)
    if not rtl:
        pieces, x = [], 0.0
        for ch in line:
            pieces.append((ch, x))
            x += _len(draw, ch, font, False) + spacing_px + (word_extra if ch == " " else 0.0)
        return pieces, max(0.0, x - spacing_px)
    # فارسی: کلمه‌به‌کلمه، از راست به چپ؛ پهنای هر کلمهٔ متصل دست‌نخورده
    words = line.split(" ")
    space = _len(draw, " ", font, True)
    widths = [_len(draw, w, font, True) for w in words]
    total = sum(widths) + (len(words) - 1) * (space + spacing_px + word_extra)
    pieces, x = [], total
    for w, wd in zip(words, widths):
        pieces.append((w, x - wd))
        x -= wd + space + spacing_px + word_extra
    return pieces, total


def vertical_lines(text: str) -> list[str]:
    """متنِ عمودی: هر نویسه (با نشانه‌هایش) یک خط؛ فاصله ⇒ خطِ خالی، خطِ تازه ⇒ دو خطِ خالی. همان در مرورگر (raster.ts › verticalLines)."""
    out: list[str] = []
    for ch in text.replace("\r", ""):
        if ch == "\n":
            out.extend(["", ""])
        elif ch.isspace():
            out.append("")
        elif unicodedata.combining(ch) and out and out[-1]:
            out[-1] += ch
        else:
            out.append(ch)
    return out[:MAX_LINES]


def lines_for(layer: dict, text: str, probe, font, canvas_w: int, width_px: float) -> list[str]:
    """خط‌های متن: عمودی ⇒ هر نویسه یک خط؛ lines دادهٔ مرورگر؛ عرضِ ثابت ⇒ شکستن؛ وگرنه عرضِ خودکار (۹۴٪ بوم)."""
    if layer.get("vertical"):
        return vertical_lines(text)
    given = layer.get("lines")
    if isinstance(given, list) and given:
        return [str(x).upper() if layer.get("caps") else str(x) for x in given][:MAX_LINES]
    if width_px > 0:
        return wrap_lines(probe, text, font, width_px)
    lines: list[str] = []
    limit = AUTO_WRAP * canvas_w
    for para in text.split("\n"):
        if _len(probe, para, font, is_rtl_text(para)) > limit:
            lines.extend(wrap_lines(probe, para, font, limit))
        else:
            lines.append(para)
    return lines[:MAX_LINES]


def render_text(layer: dict, canvas_w: int) -> tuple[Image.Image, tuple[float, float]] | None:
    """⇐ (tile RGBA، pivot=(px, py) مرکزِ محتوا). متنِ خالی ⇒ None."""
    text = str(layer.get("text") or "")
    if layer.get("caps"):
        text = text.upper()
    if not text.strip():
        return None
    size_px = max(4.0, float(layer["size"]) * canvas_w)
    path = font_path_for(layer.get("font"), int(layer.get("weight") or 700))
    font = _font(path, size_px)
    probe = ImageDraw.Draw(Image.new("L", (8, 8)))
    width_px = float(layer.get("width") or 0) * canvas_w
    lines = lines_for(layer, text, probe, font, canvas_w, width_px)
    spacing_px = float(layer.get("letter_spacing") or 0) * size_px
    forced = layer.get("dir", "auto")
    align = "center" if layer.get("vertical") else layer.get("align", "center")

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
    # «تراز دوطرفه»: همهٔ خط‌ها جز آخری با پهن‌کردنِ فاصلهٔ کلمه‌ها به پهنای بلوک می‌رسند (فقط با عرضِ ثابت، نه در متنِ عمودی)
    if layer.get("justify") and width_px > 0 and not layer.get("vertical"):
        for i, (line, rtl, pieces, wd) in enumerate(laid[:-1]):
            nw = len(line.split(" "))
            if line.strip() and nw > 1 and wd < block_w:
                pieces, wd = _line_pieces(probe, line, font, rtl, spacing_px, (block_w - wd) / (nw - 1))
                laid[i] = (line, rtl, pieces, wd)
    indent_px = float(layer.get("indent") or 0) * size_px

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
        if i == 0 and indent_px:
            x0 += -indent_px if rtl else indent_px        # تورفتگیِ خطِ اول از لبهٔ شروعِ خواندن
        y = oy + i * lh + base_y_in_line
        for piece, px in pieces:
            kw = _kw(rtl)
            kw["anchor"] = "ls"
            if stroke_px:
                kw.update(stroke_width=stroke_px, stroke_fill=_hex(stroke["color"]))
            td.text((ox + x0 + px, y), _shape(piece, rtl), font=font, fill=fill, **kw)
        if layer.get("underline") or layer.get("strike"):
            lw = max(1, int(round(LINE_W * size_px)))
            xl, xr = int(round(ox + x0)), int(round(ox + x0 + wd))
            if xr > xl:
                if layer.get("underline"):
                    yy = int(round(y + UL_OFFSET * size_px))
                    td.rectangle([xl, yy, xr - 1, yy + lw - 1], fill=fill)
                if layer.get("strike"):
                    yy = int(round(y + STRIKE_OFFSET * size_px))
                    td.rectangle([xl, yy, xr - 1, yy + lw - 1], fill=fill)

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
    pivot = (ox + block_w / 2, oy + block_h / 2)
    wp = layer.get("warp")
    if isinstance(wp, dict) and wp.get("style") in WARP_STYLES and abs(float(wp.get("amount") or 0)) > 0.001:
        tile, extra = warp_tile(tile, wp["style"], float(wp["amount"]), size_px)
        pivot = (pivot[0], pivot[1] + extra)
    tp = layer.get("tpath")
    if isinstance(tp, dict) and len(tp.get("pts") or []) >= 2:
        from . import paths as pathsmod

        tile, pivot = path_tile(tile, pathsmod.flatten(tp, float(canvas_w), float(canvas_w)))
    return tile, pivot


PATH_STEP = 0.5          # گامِ نمونه‌برداریِ طول و ارتفاعِ تایل (پیکسل)؛ همان در مرورگر (raster.ts › pathTile)
PATH_MAX_PIXELS = 36_000_000


def path_tile(tile: Image.Image, poly) -> tuple[Image.Image, tuple[float, float]]:
    """متن روی مسیر: ستونِ x از تایل ⇒ نقطه‌ای از مسیر (متن وسطِ مسیر؛ بیرون از دو سر با امتدادِ مماس) و ردیفِ y ⇒ فاصله روی عمودِ مسیر.
    نقشهٔ معکوس با نمونه‌برداریِ متراکم ساخته می‌شود (هر نمونه به نزدیک‌ترین پیکسل می‌رود)، حفره‌ها با دو گذرِ همسایهٔ ۸تایی پر می‌شوند و
    cv2.remap دوخطی روی تایلِ پیش‌ضرب‌شده نمونه می‌گیرد. ⇒ (تایلِ متقارن حولِ مرکزِ لایه، محور = مرکز). مسیر کوتاه ⇒ همان تایل."""
    import cv2
    import numpy as np

    pts = np.asarray(poly, np.float64)
    if len(pts) < 2:
        return tile, (tile.width / 2, tile.height / 2)
    seg = np.hypot(pts[1:, 0] - pts[:-1, 0], pts[1:, 1] - pts[:-1, 1])
    keep = seg > 1e-9
    if keep.sum() < 1:
        return tile, (tile.width / 2, tile.height / 2)
    cum = np.concatenate([[0.0], np.cumsum(seg)])
    total = float(cum[-1])
    tw, th = tile.size
    if total < 2:
        return tile, (tw / 2, th / 2)
    s0 = (total - tw) / 2.0
    xs = np.arange(0.0, tw + PATH_STEP, PATH_STEP)
    ys = np.arange(0.0, th + PATH_STEP, PATH_STEP)
    pos = s0 + xs
    idx = np.clip(np.searchsorted(cum, pos, side="right") - 1, 0, len(seg) - 1)
    # قطعه‌های هم‌نقطه (طول صفر) از مماس کنار گذاشته می‌شوند
    good = np.flatnonzero(keep)
    idx = good[np.clip(np.searchsorted(good, idx, side="left"), 0, len(good) - 1)]
    tang = (pts[idx + 1] - pts[idx]) / np.maximum(seg[idx], 1e-9)[:, None]
    P = pts[idx] + tang * (pos - cum[idx])[:, None]
    nrm = np.stack([-tang[:, 1], tang[:, 0]], axis=1)
    off = ys - th / 2.0
    D = P[:, None, :] + nrm[:, None, :] * off[None, :, None]
    half_x = int(math.ceil(float(np.abs(D[..., 0]).max()))) + 3
    half_y = int(math.ceil(float(np.abs(D[..., 1]).max()))) + 3
    W2, H2 = 2 * half_x, 2 * half_y
    if W2 * H2 > PATH_MAX_PIXELS:
        raise tov.OverlayError("متن روی مسیر خیلی بزرگ است.")
    ix = np.rint(D[..., 0] + half_x).astype(np.int64)
    iy = np.rint(D[..., 1] + half_y).astype(np.int64)
    ok = (ix >= 0) & (ix < W2) & (iy >= 0) & (iy < H2)
    map_x = np.full((H2, W2), -1.0, np.float32)
    map_y = np.full((H2, W2), -1.0, np.float32)
    sx = np.broadcast_to(xs[:, None], ok.shape).astype(np.float32)
    sy = np.broadcast_to(ys[None, :], ok.shape).astype(np.float32)
    map_x[iy[ok], ix[ok]] = sx[ok]
    map_y[iy[ok], ix[ok]] = sy[ok]
    for _pass in range(2):                                        # حفره‌های بینِ نمونه‌ها (سمتِ بیرونیِ خم)
        valid = map_x >= 0
        nx, ny = map_x.copy(), map_y.copy()
        for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (-1, 1), (1, -1), (1, 1)):
            sh_x = np.roll(map_x, (dy, dx), axis=(0, 1))
            sh_y = np.roll(map_y, (dy, dx), axis=(0, 1))
            take = (nx < 0) & (sh_x >= 0)
            nx[take] = sh_x[take]
            ny[take] = sh_y[take]
        map_x, map_y = nx, ny
        del valid
    a = np.asarray(tile.convert("RGBA")).astype(np.float32)
    a[..., :3] *= a[..., 3:4] / 255.0
    out = cv2.remap(a, map_x, map_y, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0, 0))
    al = out[..., 3:4]
    rgb = np.where(al > 0.5, out[..., :3] / np.maximum(al / 255.0, 1e-3), 0.0)
    res = np.concatenate([np.clip(rgb, 0, 255), np.clip(al, 0, 255)], axis=2)
    return Image.fromarray(np.rint(res).astype(np.uint8), "RGBA"), (float(half_x), float(half_y))


def layout(layer: dict, canvas_w: int) -> dict:
    """اندازه‌گیریِ بلوکِ متن بدونِ کشیدن (همان چیدمانِ ``render_text``): ⇐ {lines, block_w, block_h, size_px, line_h, widths}
    همه به پیکسلِ بومی با عرضِ ``canvas_w``. برای جاگیری و وارسیِ سرریز در طراحیِ خودکار."""
    text = str(layer.get("text") or "")
    if layer.get("caps"):
        text = text.upper()
    size_px = max(4.0, float(layer["size"]) * canvas_w)
    if not text.strip():
        return {"lines": [], "block_w": 0.0, "block_h": 0.0, "size_px": size_px, "line_h": size_px, "widths": []}
    path = font_path_for(layer.get("font"), int(layer.get("weight") or 700))
    font = _font(path, size_px)
    probe = ImageDraw.Draw(Image.new("L", (8, 8)))
    width_px = float(layer.get("width") or 0) * canvas_w
    lines = lines_for(layer, text, probe, font, canvas_w, width_px)
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
