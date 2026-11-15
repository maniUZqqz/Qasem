"""متنِ فارسی روی تصویرِ ماسکوت (حباب، کپشن، برگهٔ مدل) با موتورِ تایپوگرافیِ تامنیل‌ساز.

InstAI draws its bubble/caption text with its own fa_text shaper (the owner's Windows Pillow has no libraqm). NMarketing's server has libraqm and
``apps.thumbs.typo`` (shaping, bidi, automatic fitting, ``*highlight*`` words), so the ported bubble/caption code calls that instead - one text
engine for every picture of the product (see item notes of the port). SOURCE of the layout: instai/render/stick/compose.py ``_bubble`` / ``_caption`` @ 82733b0.
"""
from __future__ import annotations

from PIL import Image


def typo():
    from apps.thumbs import typo as _typo

    return _typo


def _blit(canvas: Image.Image, layer: Image.Image, x: int, y: int) -> None:
    w, h = canvas.size
    sx0, sy0 = max(0, -x), max(0, -y)
    sx1, sy1 = min(layer.width, w - x), min(layer.height, h - y)
    if sx1 <= sx0 or sy1 <= sy0:
        return
    sub = layer.crop((sx0, sy0, sx1, sy1)) if (sx0 or sy0 or sx1 < layer.width or sy1 < layer.height) else layer
    canvas.alpha_composite(sub, (x + sx0, y + sy0))


def block(text: str, box_w: float, box_h: float, *, px: int, fill: str = "#1f2430", hl: str | None = None, font: str = "vazirmatn", weight: int = 800,
          align: str = "auto", max_lines: int = 4, min_px: int = 16, line_gap: float = 1.22, stroke: str | None = None, stroke_w: float = 0.0):
    """متن را در جعبهٔ box_w×box_h جا می‌دهد (تا ``px``)؛ ``None`` اگر متن خالی بود. ``*کلمه*`` پررنگ می‌شود."""
    t = typo()
    style = t.TextStyle(fill=fill, hl=hl, font_key=font, weight=weight, align=align, line_gap=line_gap, stroke=stroke, stroke_w=stroke_w)
    return t.render_text(text, box_w, box_h, style, max_lines=max_lines, min_px=min_px, max_px=px)


def draw_text(canvas: Image.Image, text: str, xy: tuple[float, float], px: int, *, fill: str = "#1f2430", anchor: str = "la", max_w: float | None = None,
              weight: int = 800, font: str = "vazirmatn", max_lines: int = 1, hl: str | None = None) -> tuple[int, int, int, int] | None:
    """متنِ تک‌خطی (یا چندخطی) روی ``canvas`` (RGBA). anchor: la (چپ‌بالا)، ra (راست‌بالا)، ma (وسط‌بالا). ⇒ کادرِ متن."""
    x, y = xy
    box_w = max_w or 1600
    box_h = px * 1.6 * max_lines
    blk = block(text, box_w, box_h, px=px, fill=fill, hl=hl, font=font, weight=weight, max_lines=max_lines, align={"la": "left", "ra": "right", "ma": "center"}.get(anchor, "auto"))
    if blk is None:
        return None
    nw, nh = blk.nominal
    if anchor == "ra":
        rect, ax = (x - nw, y, x, y + nh), "right"
    elif anchor == "ma":
        rect, ax = (x - nw / 2, y, x + nw / 2, y + nh), "center"
    else:
        rect, ax = (x, y, x + nw, y + nh), "left"
    ox, oy = typo().place(blk, rect, ax, "top")
    _blit(canvas, blk.img, ox, oy)
    return int(rect[0]), int(rect[1]), int(rect[2]), int(rect[3])
