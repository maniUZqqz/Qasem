"""پوسترِ تبلیغاتی (و کارتِ پایانیِ ویدیو) با Pillow روی سرورِ سایت.

بهترین عکس ⇐ (اگر سرورِ پردازش روشن است) حذفِ پس‌زمینه با کیتِ ادیتورِ عکس (photo.edit، kit_background) ⇐ روی
زمینهٔ رنگیِ برند؛ وگرنه همان عکس در یک قابِ گرد روی نسخهٔ محوشده و رنگی‌شدهٔ خودش. متن‌ها (نام، ویژگی‌ها، قیمت،
دعوت به خرید) راست‌به‌چپ با فونتِ وزیرمتن، لوگوی فروشگاه در گوشه.
"""
from __future__ import annotations

import logging
import time
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageOps

logger = logging.getLogger(__name__)

SIZES = {"1:1": (1080, 1080), "4:5": (1080, 1350), "9:16": (1080, 1920)}
TEMPLATES = {"clean": "روشن و تمیز", "bold": "تیره و پررنگ", "minimal": "ساده و سفید"}
DEFAULT_BRAND = (124, 58, 237)
CUTOUT_WAIT_S = 150


def _hex(value) -> tuple | None:
    s = str(value or "").strip().lstrip("#")
    if len(s) == 3:
        s = "".join(c * 2 for c in s)
    if len(s) != 6:
        return None
    try:
        return tuple(int(s[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return None


def brand_color(store) -> tuple:
    colors = getattr(store, "colors", None) or {}
    if isinstance(colors, dict):
        for key in ("primary", "brand", "main", "accent", "color"):
            c = _hex(colors.get(key))
            if c:
                return c
    elif isinstance(colors, list):
        for item in colors:
            c = _hex(item)
            if c:
                return c
    return DEFAULT_BRAND


def _mix(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def _font(size: int, bold: bool = True):
    from apps.photoedit.ops import _font as pe_font

    return pe_font(size, bold)


def _shape(text: str) -> str:
    from services.imaging import text_overlay as tov

    return tov.shape_rtl(text)


def _kw() -> dict:
    from services.imaging import text_overlay as tov

    return tov._draw_kwargs()


def _width(draw, text, font) -> float:
    return draw.textlength(_shape(text), font=font, **_kw())


def _line_h(font) -> int:
    return font.getbbox("آگ")[3] + int(font.size * 0.3)


def _wrap(draw, text: str, font, max_w: int, max_lines: int) -> list[str]:
    words, lines, cur = text.split(), [], ""
    for word in words:
        trial = (cur + " " + word).strip()
        if not cur or _width(draw, trial, font) <= max_w:
            cur = trial
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1].rstrip("،.") + "…"
    return lines


def _text_center(draw, y, text, font, fill, W, shadow=None):
    shaped = _shape(text)
    tw = draw.textlength(shaped, font=font, **_kw())
    x = (W - tw) / 2
    if shadow:
        off = max(1, font.size // 22)
        draw.text((x + off, y + off), shaped, font=font, fill=shadow, **_kw())
    draw.text((x, y), shaped, font=font, fill=fill, **_kw())
    return tw


def _cover(img: Image.Image, w: int, h: int) -> Image.Image:
    return ImageOps.fit(img, (w, h), Image.Resampling.LANCZOS)


def _rounded_mask(size, radius) -> Image.Image:
    m = Image.new("L", size, 0)
    ImageDraw.Draw(m).rounded_rectangle([0, 0, size[0] - 1, size[1] - 1], radius=radius, fill=255)
    return m


def _drop_shadow(canvas: Image.Image, box, radius, blur, alpha):
    layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    ImageDraw.Draw(layer).rounded_rectangle(box, radius=radius, fill=(0, 0, 0, alpha))
    canvas.alpha_composite(layer.filter(ImageFilter.GaussianBlur(blur)))


def _trim_alpha(img: Image.Image) -> Image.Image:
    if img.mode != "RGBA":
        return img
    bbox = img.getchannel("A").point(lambda v: 255 if v > 16 else 0).getbbox()
    return img.crop(bbox) if bbox else img


def grade(img: Image.Image) -> Image.Image:
    """اصلاحِ ملایمِ نور و رنگ (همان کاری که در ویدیو با eq انجام می‌شود)."""
    from apps.photoedit import ops

    rgb = img.convert("RGB")
    try:
        f = ops.measure(rgb)
        p50 = f["p50"]
    except Exception:  # noqa: BLE001
        p50 = 128
    if p50 < 105:
        rgb = ImageEnhance.Brightness(rgb).enhance(min(1.35, 1 + (105 - p50) / 220))
    elif p50 > 205:
        rgb = ImageEnhance.Brightness(rgb).enhance(0.95)
    rgb = ImageEnhance.Contrast(rgb).enhance(1.05)
    return ImageEnhance.Color(rgb).enhance(1.08)


def compose(photo: Image.Image, *, size: tuple, template: str, texts: dict, cutout: Image.Image | None = None,
            logo: Image.Image | None = None, brand: tuple = DEFAULT_BRAND, store_name: str = "",
            show_cta: bool = True) -> Image.Image:
    W, H = size
    template = template if template in TEMPLATES else "clean"
    pad = int(W * 0.06)
    photo = grade(photo)
    dark = template == "bold"
    ink = (255, 255, 255) if dark else (28, 24, 40)
    sub_ink = (235, 235, 245) if dark else (70, 64, 90)

    # ── زمینه
    if template == "minimal":
        canvas = Image.new("RGBA", (W, H), (248, 247, 250, 255))
    elif cutout is not None:
        top = _mix(brand, (0, 0, 0), 0.55) if dark else _mix(brand, (255, 255, 255), 0.82)
        bottom = _mix(brand, (0, 0, 0), 0.8) if dark else (255, 255, 255)
        grad = Image.new("RGB", (1, 256))
        for y in range(256):
            grad.putpixel((0, y), _mix(top, bottom, y / 255))
        canvas = grad.resize((W, H), Image.Resampling.BICUBIC).convert("RGBA")
    else:
        bg = _cover(photo, W // 4, H // 4).filter(ImageFilter.GaussianBlur(10)).resize((W, H), Image.Resampling.BICUBIC)
        canvas = bg.convert("RGBA")
        tint = (*_mix(brand, (0, 0, 0), 0.7), 170) if dark else (*_mix(brand, (255, 255, 255), 0.88), 190)
        canvas.alpha_composite(Image.new("RGBA", (W, H), tint))
    draw = ImageDraw.Draw(canvas)

    # ── سربرگ: لوگو یا نامِ فروشگاه
    header = 0
    if logo is not None:
        lg = logo.convert("RGBA")
        lw = int(W * 0.17)
        lh = max(1, int(lg.height * lw / max(1, lg.width)))
        if lh > H * 0.08:
            lh = int(H * 0.08)
            lw = max(1, int(lg.width * lh / max(1, lg.height)))
        lg = lg.resize((lw, lh), Image.Resampling.LANCZOS)
        canvas.alpha_composite(lg, (W - pad - lw, pad))
        header = lh + int(pad * 0.5)
    elif store_name:
        f = _font(int(W * 0.032), True)
        _text_center(draw, pad * 0.7, store_name, f, sub_ink, W)
        header = _line_h(f) + int(pad * 0.4)

    # ── اندازهٔ بلوکِ متن
    square = W == H
    title_f = _font(int(W * (0.062 if square else 0.07)), True)
    feat_f = _font(int(W * (0.032 if square else 0.036)), False)
    price_f = _font(int(W * (0.055 if square else 0.062)), True)
    cta_f = _font(int(W * (0.04 if square else 0.044)), True)
    gap = int(H * 0.018)
    title = (texts.get("title") or "").strip()
    title_lines = _wrap(draw, title, title_f, W - 2 * pad, 2) if title else []
    features = [f.split(":")[-1].strip() for f in (texts.get("features") or []) if str(f).strip()][:3]
    price = (texts.get("price") or "").strip()
    old_price = (texts.get("old_price") or "").strip()
    cta = (texts.get("cta") or "").strip() if show_cta else ""

    def chip_rows(feats):
        rows, cur, cur_w = [], [], 0
        cpad = int(feat_f.size * 0.7)
        for ft in feats:
            ft = ft[:34]
            w = int(_width(draw, ft, feat_f)) + 2 * cpad
            if cur and cur_w + w + cpad > W - 2 * pad:
                rows.append(cur)
                cur, cur_w = [], 0
            cur.append((ft, w))
            cur_w += w + cpad
        if cur:
            rows.append(cur)
        return rows[:2]

    rows = chip_rows(features)
    chip_h = _line_h(feat_f) + int(feat_f.size * 0.5)
    price_h = (_line_h(price_f) + int(price_f.size * 0.5)) if price else 0
    cta_h = (_line_h(cta_f) + int(cta_f.size * 0.9)) if cta else 0

    def text_block_h(rows_):
        h = len(title_lines) * _line_h(title_f)
        if rows_:
            h += gap + len(rows_) * (chip_h + int(gap * 0.5))
        if price:
            h += gap + price_h + (int(_line_h(feat_f) * 0.9) if old_price else 0)
        if cta:
            h += gap + cta_h
        return h

    text_h = text_block_h(rows)
    area_top = pad + header
    area_bottom = H - pad - text_h - gap
    if area_bottom - area_top < H * 0.32 and rows:
        rows = rows[:1] if len(rows) > 1 else []
        text_h = text_block_h(rows)
        area_bottom = H - pad - text_h - gap
    area = (pad, area_top, W - pad, max(area_top + int(H * 0.25), area_bottom))

    # ── محصول
    aw, ah = area[2] - area[0], area[3] - area[1]
    if cutout is not None:
        cut = _trim_alpha(cutout.convert("RGBA"))
        scale = min(aw * 0.92 / cut.width, ah * 0.9 / cut.height)
        cw, ch = max(1, int(cut.width * scale)), max(1, int(cut.height * scale))
        cut = cut.resize((cw, ch), Image.Resampling.LANCZOS)
        cx, cy = area[0] + (aw - cw) // 2, area[1] + (ah - ch) // 2
        shadow = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        sw = int(cw * 0.75)
        ImageDraw.Draw(shadow).ellipse([cx + (cw - sw) // 2, cy + ch - int(ch * 0.04), cx + (cw + sw) // 2,
                                        cy + ch + int(ch * 0.06)], fill=(0, 0, 0, 110))
        canvas.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(max(4, cw // 25))))
        canvas.alpha_composite(cut, (cx, cy))
    else:
        ph = photo.copy()
        ph.thumbnail((aw, ah), Image.Resampling.LANCZOS)
        radius = int(W * 0.035)
        px, py = area[0] + (aw - ph.width) // 2, area[1] + (ah - ph.height) // 2
        _drop_shadow(canvas, [px, py + int(W * 0.01), px + ph.width, py + ph.height + int(W * 0.01)], radius,
                     int(W * 0.02), 120 if not dark else 170)
        if template == "clean":
            border = int(W * 0.012)
            frame = Image.new("RGBA", (ph.width + 2 * border, ph.height + 2 * border), (255, 255, 255, 255))
            canvas.paste(frame, (px - border, py - border), _rounded_mask(frame.size, radius + border))
        canvas.paste(ph.convert("RGBA"), (px, py), _rounded_mask(ph.size, radius))
    draw = ImageDraw.Draw(canvas)

    # ── متن‌ها
    y = area[3] + gap
    shadow = (0, 0, 0, 120) if dark else None
    for line in title_lines:
        _text_center(draw, y, line, title_f, ink, W, shadow)
        y += _line_h(title_f)
    if rows:
        y += gap
        cpad = int(feat_f.size * 0.7)
        for row in rows:
            total = sum(w for _t, w in row) + cpad * (len(row) - 1)
            x = (W + total) / 2          # راست‌به‌چپ: اولین ویژگی سمتِ راست
            for ft, w in row:
                x0 = x - w
                fill = (255, 255, 255, 40) if dark else (*_mix(brand, (255, 255, 255), 0.85), 255)
                draw.rounded_rectangle([x0, y, x, y + chip_h], radius=chip_h // 2, fill=fill)
                shaped = _shape(ft)
                tw = draw.textlength(shaped, font=feat_f, **_kw())
                draw.text((x0 + (w - tw) / 2, y + (chip_h - _line_h(feat_f)) / 2 + feat_f.size * 0.08), shaped,
                          font=feat_f, fill=ink if dark else _mix(brand, (0, 0, 0), 0.45), **_kw())
                x = x0 - cpad
            y += chip_h + int(gap * 0.5)
    if price:
        y += gap
        if old_price:
            f = _font(int(feat_f.size * 0.9), False)
            tw = _text_center(draw, y, old_price, f, sub_ink, W)
            mid = y + _line_h(f) * 0.45
            draw.line([((W - tw) / 2, mid), ((W + tw) / 2, mid)], fill=(220, 38, 38), width=max(2, f.size // 12))
            y += int(_line_h(feat_f) * 0.9)
        pw = int(_width(draw, price, price_f)) + int(price_f.size * 1.2)
        badge = (255, 211, 77) if dark else brand
        draw.rounded_rectangle([(W - pw) / 2, y, (W + pw) / 2, y + price_h], radius=price_h // 3, fill=badge)
        _text_center(draw, y + (price_h - _line_h(price_f)) / 2 + price_f.size * 0.1, price, price_f,
                     (30, 24, 10) if dark else (255, 255, 255), W)
        y += price_h
    if cta:
        y = max(y + gap, H - pad - cta_h)
        cw = int(_width(draw, cta, cta_f)) + int(cta_f.size * 2.2)
        if template == "minimal":
            draw.rounded_rectangle([(W - cw) / 2, y, (W + cw) / 2, y + cta_h], radius=cta_h // 2,
                                   outline=brand, width=max(3, W // 300))
            color = brand
        else:
            draw.rounded_rectangle([(W - cw) / 2, y, (W + cw) / 2, y + cta_h], radius=cta_h // 2,
                                   fill=(255, 255, 255) if dark else _mix(brand, (0, 0, 0), 0.25))
            color = (28, 24, 40) if dark else (255, 255, 255)
        _text_center(draw, y + (cta_h - _line_h(cta_f)) / 2 + cta_f.size * 0.1, cta, cta_f, color, W)
    return canvas.convert("RGB")


# ───────────────────────────── حذفِ پس‌زمینه با سرورِ پردازش

def request_cutout(session, take, user) -> tuple[Image.Image | None, str]:
    """(عکسِ بی‌پس‌زمینه یا None، یادداشت). فقط وقتی سرورِ پردازشِ عکس آنلاین است؛ حداکثر ۱۵۰ ثانیه صبر."""
    from django.core.files import File

    from apps.photoedit import services as ps
    from apps.photoedit.models import PhotoEdit
    from apps.photoedit.tasks import start_edit_task

    from . import media

    cached = (take.checks or {}).get("cutout")
    if cached and media.abs_path(cached).is_file():
        return Image.open(media.abs_path(cached)).convert("RGBA"), "پس‌زمینه با سرورِ پردازش حذف شده بود (همان نسخه)."
    try:
        if not ps.node_status()["online"]:
            return None, "سرورِ پردازش (GPU) خاموش است ⇐ به جای حذفِ پس‌زمینه، زمینهٔ محو و رنگی."
        with open(media.abs_path(take.file), "rb") as fh:
            asset = ps.add_upload(session.store, user, File(fh, name=f"shoot_{session.pk}_{take.shot}.jpg"),
                                  title=f"فیلم‌برداری: {session.product.name}")
        edit = ps.create_edits(session.store, user, [asset.pk], "custom", [
            {"tool": "kit_background", "params": {"method": "auto", "bg": "transparent", "shadow": 0,
                                                  "cleanup": -1}}])[0]
        try:
            start_edit_task.delay(edit.pk)
        except Exception:  # noqa: BLE001 — بی‌بروکر
            start_edit_task(edit.pk)
        deadline = time.monotonic() + CUTOUT_WAIT_S
        while time.monotonic() < deadline:
            edit.refresh_from_db()
            if edit.state == PhotoEdit.State.NODE:
                ps.refresh(edit)
                edit.refresh_from_db()
                if edit.state == PhotoEdit.State.SERVER:
                    ps.run_server_stage(edit)
                    edit.refresh_from_db()
            if edit.state == PhotoEdit.State.READY:
                img = Image.open(ps.abs_path(edit.files["result"]))
                img.load()
                if img.mode != "RGBA":
                    return None, "سرورِ پردازش پس‌زمینهٔ شفاف برنگرداند ⇐ زمینهٔ محو."
                rel = f"{session.dir_rel}/takes/{take.shot}_cut_{take.pk}.png"
                media.abs_path(rel).parent.mkdir(parents=True, exist_ok=True)
                img.save(media.abs_path(rel))
                take.checks = dict(take.checks or {}) | {"cutout": rel}
                take.save(update_fields=["checks", "updated_at"])
                return img.convert("RGBA"), "پس‌زمینه روی سرورِ پردازش (GPU) حذف شد."
            if edit.state in (PhotoEdit.State.FAILED, PhotoEdit.State.CANCELLED):
                return None, "حذفِ پس‌زمینه روی سرورِ پردازش ناموفق بود ⇐ زمینهٔ محو."
            time.sleep(5)
        return None, "سرورِ پردازش دیر جواب داد ⇐ زمینهٔ محو (نسخهٔ بی‌پس‌زمینه بعداً در ادیتورِ عکس هست)."
    except Exception as exc:  # noqa: BLE001
        logger.exception("shoot: cutout for take %s failed", take.pk)
        return None, f"حذفِ پس‌زمینه انجام نشد ({str(exc)[:120]}) ⇐ زمینهٔ محو."


def store_logo(store) -> Image.Image | None:
    logo = getattr(store, "logo", None)
    if not logo:
        return None
    try:
        path = Path(logo.path)
        if path.is_file():
            img = Image.open(path)
            img.load()
            return img
    except Exception:  # noqa: BLE001
        return None
    return None
