"""کارهای سبکِ ادیتورِ عکس روی سرورِ سایت (Pillow + numpy) و اندازه‌گیریِ عکس.

همه روی تصویرِ RGB یا RGBA کار می‌کنند و شفافیت را نگه می‌دارند (مگر خروجیِ JPEG که روی سفید می‌نشیند).
سرورِ سایت کوچک است (۲ هسته، ۳ گیگ): هیچ کاری تمامِ عکس را چند بار در float64 کپی نمی‌کند و اندازه‌گیری روی
نسخهٔ ۸۰۰ پیکسلی است.
"""
from __future__ import annotations

import io
import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps

from services.imaging import text_overlay as tov

from .catalog import SOCIAL_FORMATS

Image.MAX_IMAGE_PIXELS = 80_000_000   # عکسِ ۸۰ مگاپیکسلی هنوز عکس است؛ بیشتر ⇐ بمبِ فشرده‌سازی


class OpError(Exception):
    """خطایی که متنش برای کاربر است."""


# ───────────────────────────── خواندن و نوشتن

def load(path) -> Image.Image:
    try:
        img = Image.open(path)
        img.load()
    except Image.DecompressionBombError as exc:
        raise OpError("عکس خیلی بزرگ است (بیش از ۸۰ مگاپیکسل).") from exc
    except Exception as exc:  # noqa: BLE001
        raise OpError("فایل عکسِ معتبر نیست.") from exc
    img = ImageOps.exif_transpose(img)
    if img.mode in ("RGBA", "LA", "PA") or (img.mode == "P" and "transparency" in img.info):
        img = img.convert("RGBA")
        if img.getextrema()[3][0] >= 255:      # کانالِ آلفا هست ولی همه‌جا کامل ⇒ همان RGB
            img = img.convert("RGB")
    else:
        img = img.convert("RGB")
    return img


def orientation(path) -> int:
    """چرخشِ EXIF (۱ = صاف)."""
    try:
        with Image.open(path) as im:
            return int(im.getexif().get(0x0112, 1) or 1)
    except Exception:  # noqa: BLE001
        return 1


def _rgb(img: Image.Image) -> tuple[Image.Image, Image.Image | None]:
    if img.mode == "RGBA":
        return img.convert("RGB"), img.getchannel("A")
    return img, None


def _with_alpha(rgb: Image.Image, alpha: Image.Image | None) -> Image.Image:
    if alpha is None:
        return rgb
    out = rgb.convert("RGBA")
    out.putalpha(alpha)
    return out


def flatten(img: Image.Image, color=(255, 255, 255)) -> Image.Image:
    if img.mode != "RGBA":
        return img.convert("RGB")
    bg = Image.new("RGB", img.size, color)
    bg.paste(img, mask=img.getchannel("A"))
    return bg


def encode(img: Image.Image, fmt: str = "jpeg", quality: int = 90, max_kb: int = 0) -> tuple[bytes, str]:
    """⇐ (بایت‌ها، قالب). JPEG ِ عکسِ شفاف روی سفید؛ با max_kb کیفیت پله‌پله پایین می‌آید (نه زیرِ ۴۰)."""
    fmt = {"jpg": "jpeg"}.get(fmt, fmt)
    if fmt not in ("jpeg", "png", "webp"):
        fmt = "jpeg"
    q = int(quality)
    while True:
        buf = io.BytesIO()
        if fmt == "jpeg":
            flatten(img).save(buf, "JPEG", quality=q, optimize=True, progressive=True, subsampling=0 if q >= 90 else 2)
        elif fmt == "png":
            img.save(buf, "PNG", optimize=img.width * img.height < 6_000_000)
        else:
            img.save(buf, "WEBP", quality=q, method=4)
        data = buf.getvalue()
        if not max_kb or fmt == "png" or len(data) <= max_kb * 1024 or q <= 40:
            return data, fmt
        q = max(40, q - 8)


def thumbnail(img: Image.Image, side: int) -> Image.Image:
    t = img.copy()
    t.thumbnail((side, side), Image.Resampling.LANCZOS)
    return t


def jpeg_bytes(img: Image.Image, side: int, quality: int = 84) -> bytes:
    t = thumbnail(img, side)
    if t.mode == "RGBA":   # شفاف ⇐ روی شطرنجیِ روشن تا «شفاف» دیده شود
        board = Image.new("RGB", t.size, (255, 255, 255))
        d = ImageDraw.Draw(board)
        s = max(8, side // 40)
        for y in range(0, t.height, s):
            for x in range((y // s) % 2 * s, t.width, 2 * s):
                d.rectangle([x, y, x + s - 1, y + s - 1], fill=(232, 232, 236))
        board.paste(t, mask=t.getchannel("A"))
        t = board
    buf = io.BytesIO()
    t.convert("RGB").save(buf, "JPEG", quality=quality, optimize=True)
    return buf.getvalue()


# ───────────────────────────── اندازه‌گیری

def _small_gray(img: Image.Image, side=800) -> tuple[np.ndarray, np.ndarray, np.ndarray | None]:
    t = thumbnail(img, side)
    rgb, alpha = _rgb(t)
    a = np.asarray(rgb, dtype=np.float32)
    g = a[..., 0] * 0.299 + a[..., 1] * 0.587 + a[..., 2] * 0.114
    return a, g, (np.asarray(alpha, dtype=np.float32) / 255 if alpha is not None else None)


def measure(img: Image.Image) -> dict:
    """اندازه‌هایی که پنل نشان می‌دهد و پیشنهاد از رویشان ساخته می‌شود (۰ تا ۲۵۵ مگر خلافش گفته شود)."""
    a, g, alpha = _small_gray(img)
    keep = alpha > 0.5 if alpha is not None else np.ones(g.shape, bool)
    if keep.sum() < 64:
        keep = np.ones(g.shape, bool)
    gv = g[keep]
    p5, p50, p95 = (float(x) for x in np.percentile(gv, [5, 50, 95]))
    mx, mn = a.max(axis=2), a.min(axis=2)
    sat = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1), 0) * 255
    # رنگ‌زدگی: میانگینِ (قرمز − آبی) و (سبز − بنفش) روی بخش‌های نزدیک به خنثی و میانه‌روشن
    neutral = keep & (sat < 90) & (g > 25) & (g < 230)
    if neutral.sum() > 200:
        r, gg, b = a[..., 0][neutral], a[..., 1][neutral], a[..., 2][neutral]
        cast_rb, cast_g = float(np.mean(r - b)), float(np.mean(gg - (r + b) / 2))
    else:
        cast_rb = cast_g = 0.0
    # تیزی: واریانسِ لاپلاسین؛ نویز: روشِ Immerkær روی همان خاکستری
    lap = 4 * g[1:-1, 1:-1] - g[:-2, 1:-1] - g[2:, 1:-1] - g[1:-1, :-2] - g[1:-1, 2:]
    sharp = float(lap[keep[1:-1, 1:-1]].var()) if keep[1:-1, 1:-1].any() else float(lap.var())
    k = (g[:-2, :-2] - 2 * g[:-2, 1:-1] + g[:-2, 2:] - 2 * g[1:-1, :-2] + 4 * g[1:-1, 1:-1] - 2 * g[1:-1, 2:]
         + g[2:, :-2] - 2 * g[2:, 1:-1] + g[2:, 2:])
    h, w = g.shape
    noise = float(math.sqrt(math.pi / 2) * np.abs(k).sum() / (6 * max(1, (w - 2) * (h - 2))))
    # زمینه: قابِ ۵٪ دورِ عکس
    m = max(2, int(min(h, w) * 0.05))
    border = np.concatenate([g[:m].ravel(), g[-m:].ravel(), g[:, :m].ravel(), g[:, -m:].ravel()])
    return {
        "width": img.width, "height": img.height, "megapixels": round(img.width * img.height / 1e6, 2),
        "has_alpha": img.mode == "RGBA",
        "p5": round(p5, 1), "p50": round(p50, 1), "p95": round(p95, 1), "contrast": round(p95 - p5, 1),
        "clip_hi": round(float((gv >= 250).mean()), 4), "clip_lo": round(float((gv <= 4).mean()), 4),
        "saturation": round(float(sat[keep].mean()), 1),
        "cast_rb": round(cast_rb, 1), "cast_g": round(cast_g, 1),
        "sharpness": round(sharp, 1), "noise": round(noise, 2),
        "border_mean": round(float(border.mean()), 1), "border_std": round(float(border.std()), 1),
    }


def findings(f: dict) -> list[dict]:
    """اندازه‌ها ⇐ جمله‌هایی که صاحبِ فروشگاه می‌فهمد (و پیشنهادِ خودکار از رویشان ساخته می‌شود)."""
    out = []

    def add(what, note, value):
        out.append({"what": what, "note": note, "value": value})

    long_edge = max(f["width"], f["height"])
    if f["p50"] < 80:
        add("dark", f"عکس تیره است (روشناییِ میانه {round(f['p50'])} از ۲۵۵)", f["p50"])
    elif f["p50"] > 200 and f["clip_hi"] > 0.08 and not f.get("has_alpha"):
        add("bright", f"عکس خیلی روشن است ({round(f['clip_hi'] * 100)}٪ سفیدِ سوخته)", f["p50"])
    if f["clip_hi"] > 0.04 and f["p50"] <= 200 and f["border_std"] > 12:
        add("clipped", f"{round(f['clip_hi'] * 100)}٪ عکس سوخته (سفیدِ بی‌جزئیات)", f["clip_hi"])
    if f["contrast"] < 110:
        add("flat", f"عکس کم‌کنتراست و تخت است (فاصلهٔ تیره تا روشن {round(f['contrast'])})", f["contrast"])
    cast = max(abs(f["cast_rb"]), abs(f["cast_g"]) * 1.5)
    if cast > 14:
        tone = "زرد/نارنجی" if f["cast_rb"] > 14 else "آبی" if f["cast_rb"] < -14 else "سبز" if f["cast_g"] > 0 else "ارغوانی"
        add("cast", f"رنگ‌زدگیِ {tone} روی بخش‌های خنثی", round(cast, 1))
    if f["sharpness"] < 60 and long_edge >= 400:
        add("blurry", "عکس کمی تار است", f["sharpness"])
    if f["noise"] > 4.5:
        add("noisy", f"دانه/نویز دارد (حدودِ {f['noise']})", f["noise"])
    if long_edge < 1080:
        add("small", f"عکس کوچک است ({long_edge} پیکسل؛ اینستاگرام ۱۰۸۰ می‌خواهد)", long_edge)
    if long_edge > 4500:
        add("huge", f"عکس خیلی بزرگ است ({long_edge} پیکسل)", long_edge)
    if f["border_std"] < 14 and f["border_mean"] > 150 and not f.get("has_alpha"):
        add("plain_bg", "زمینهٔ ساده و روشن دارد (مناسبِ عکسِ فروشگاهی)", f["border_std"])
    return out


# ───────────────────────────── کارها

def _blend(a: Image.Image, b: Image.Image, strength: float) -> Image.Image:
    s = max(0.0, min(1.0, strength))
    if s >= 0.999:
        return b
    if s <= 0.001:
        return a
    return Image.blend(a, b, s)


def op_auto_tone(img, p, ctx):
    """تعادلِ سفیدیِ ملایم ⇐ کشش ⇐ گامای میانه‌ها؛ همه از روی نسخهٔ کوچک حساب و با جدولِ ۲۵۶تایی روی اصل اعمال
    می‌شود (عکسِ ۱۲ مگاپیکسلی در حافظهٔ اعشاری کپی نمی‌شود)."""
    rgb, alpha = _rgb(img)
    sm, _g, al = _small_gray(img, 600)
    mask = al > 0.5 if al is not None and (al > 0.5).sum() > 64 else np.ones(sm.shape[:2], bool)
    notes = []
    # ۱) تعادلِ سفیدیِ ملایم (دنیای خاکستری روی بخش‌های نزدیک به خنثی و میانه‌روشنِ خودِ اصل)
    gains = np.ones(3, np.float32)
    mx, mn, gray = sm.max(axis=2), sm.min(axis=2), sm.mean(axis=2)
    neutral = mask & ((mx - mn) < 0.35 * np.maximum(mx, 1)) & (gray > 30) & (gray < 235)
    if neutral.sum() > 300:
        means = sm[neutral].mean(axis=0)
        cand = np.clip(means.mean() / np.maximum(means, 1), 0.88, 1.12)
        if np.abs(cand - 1).max() > 0.02:
            gains = cand.astype(np.float32)
            notes.append("رفعِ رنگ‌زدگی")
    # ۲) کشیدنِ روشنایی تا دو سرِ هیستوگرام
    wb = sm * gains
    g2 = (wb[..., 0] * 0.299 + wb[..., 1] * 0.587 + wb[..., 2] * 0.114)[mask]
    lo, hi = (float(x) for x in np.percentile(g2, [0.5, 99.5]))
    scale = 1.0
    if hi - lo > 24:
        scale = min(255.0 / (hi - lo), 2.2)
        lo = max(0.0, min(lo, 60.0))
        if scale > 1.03:
            notes.append(f"دامنهٔ روشنایی ×{scale:.2f}")
    else:
        lo = 0.0
    # ۳) میانه‌های تیره ⇐ گامای روشن‌کننده
    gamma = 1.0
    med = float(np.median(np.clip((wb - lo) * scale, 0, 255).mean(axis=2)[mask]))
    if 20 < med < 105:
        gamma = max(0.62, math.log(0.45) / math.log(max(med, 1) / 255))
        notes.append("روشن کردنِ میانه‌ها")
    v = np.arange(256, dtype=np.float32)
    lut = []
    for c in range(3):
        x = np.clip((v * gains[c] - lo) * scale, 0, 255) / 255
        lut += [int(round(255 * y)) for y in np.power(x, gamma)]
    out = ImageEnhance.Color(rgb.point(lut)).enhance(1.06)
    ctx["notes"].append("نور و رنگِ خودکار: " + ("، ".join(notes) if notes else "تغییرِ چندانی لازم نبود"))
    return _with_alpha(_blend(rgb, out, p["strength"] / 100), alpha)


def op_color(img, p, ctx):
    rgb, alpha = _rgb(img)
    out = rgb
    if p["brightness"]:
        out = ImageEnhance.Brightness(out).enhance(1 + p["brightness"] / 100 * 0.6)
    if p["contrast"]:
        out = ImageEnhance.Contrast(out).enhance(1 + p["contrast"] / 100 * (0.8 if p["contrast"] > 0 else 0.6))
    if p["saturation"]:
        out = ImageEnhance.Color(out).enhance(max(0.0, 1 + p["saturation"] / 100))
    if p["warmth"]:
        w = p["warmth"] / 100 * 0.12
        r, g, b = out.split()
        r = r.point(lambda v: min(255, int(v * (1 + w))))
        b = b.point(lambda v: min(255, int(v * (1 - w))))
        out = Image.merge("RGB", (r, g, b))
    if p["sharpness"]:
        out = out.filter(ImageFilter.UnsharpMask(radius=max(1.0, max(out.size) / 1500), percent=int(p["sharpness"] * 2.2),
                                                 threshold=2))
    return _with_alpha(out, alpha)


def op_look(img, p, ctx):
    rgb, alpha = _rgb(img)
    style = p["style"]
    if style == "bw":
        out = ImageEnhance.Contrast(ImageOps.grayscale(rgb)).enhance(1.12).convert("RGB")
    elif style == "sepia":
        g = ImageEnhance.Contrast(ImageOps.grayscale(rgb)).enhance(1.05)
        out = ImageOps.colorize(g, black=(38, 26, 16), white=(255, 240, 214), mid=(158, 122, 86))
    elif style == "warm":
        out = op_color(rgb, {"brightness": 4, "contrast": 0, "saturation": 8, "warmth": 45, "sharpness": 0}, ctx)
    elif style == "cool":
        out = op_color(rgb, {"brightness": 0, "contrast": 4, "saturation": -4, "warmth": -40, "sharpness": 0}, ctx)
    elif style == "vivid":
        out = ImageEnhance.Contrast(ImageEnhance.Color(rgb).enhance(1.35)).enhance(1.1)
    else:  # fade
        out = ImageEnhance.Color(rgb).enhance(0.82).point(lambda v: int(26 + v * (232 - 26) / 255))
    return _with_alpha(_blend(rgb, out.convert("RGB"), p["strength"] / 100), alpha)


def _inner_rect(w: int, h: int, angle_deg: float) -> tuple[int, int]:
    """بزرگ‌ترین مستطیلِ هم‌راستا داخلِ عکسِ چرخیده (بی گوشهٔ خالی)."""
    a = math.radians(abs(angle_deg))
    if a < 1e-6:
        return w, h
    long_side, short_side = max(w, h), min(w, h)
    sin_a, cos_a = math.sin(a), math.cos(a)
    if short_side <= 2 * sin_a * cos_a * long_side or abs(sin_a - cos_a) < 1e-10:
        x = 0.5 * short_side
        wr, hr = (x / sin_a, x / cos_a) if w >= h else (x / cos_a, x / sin_a)
    else:
        cos_2a = cos_a * cos_a - sin_a * sin_a
        wr, hr = (w * cos_a - h * sin_a) / cos_2a, (h * cos_a - w * sin_a) / cos_2a
    return max(1, int(wr)), max(1, int(hr))


def op_rotate(img, p, ctx):
    turn = int(p["turn"])
    if turn == 90:
        img = img.transpose(Image.Transpose.ROTATE_90)
    elif turn == 180:
        img = img.transpose(Image.Transpose.ROTATE_180)
    elif turn == 270:
        img = img.transpose(Image.Transpose.ROTATE_270)
    if p["straighten"]:
        w, h = img.size
        rot = img.rotate(p["straighten"], resample=Image.Resampling.BICUBIC, expand=False)
        iw, ih = _inner_rect(w, h, p["straighten"])
        left, top = (w - iw) // 2, (h - ih) // 2
        img = rot.crop((left, top, left + iw, top + ih))
    if p["flip_h"]:
        img = ImageOps.mirror(img)
    if p["flip_v"]:
        img = ImageOps.flip(img)
    return img


def _energy_offset(img: Image.Image, crop_w: int, crop_h: int) -> tuple[int, int]:
    """جای پنجرهٔ برش که بیشترین «جزئیات» (یا خودِ کالا اگر شفاف است) را در بر بگیرد."""
    side = 320
    t = thumbnail(img, side)
    sx, sy = t.width / img.width, t.height / img.height
    if t.mode == "RGBA":
        e = np.asarray(t.getchannel("A"), dtype=np.float32)
    else:
        g = np.asarray(ImageOps.grayscale(t), dtype=np.float32)
        gx = np.abs(np.diff(g, axis=1, append=g[:, -1:]))
        gy = np.abs(np.diff(g, axis=0, append=g[-1:, :]))
        e = gx + gy
        # کمی سهمِ وسط (عکاس معمولاً سوژه را وسط می‌گذارد) تا لبه‌ی پرجزئیاتِ پس‌زمینه برنده نشود
        yy, xx = np.mgrid[0:e.shape[0], 0:e.shape[1]]
        cy, cx = (e.shape[0] - 1) / 2, (e.shape[1] - 1) / 2
        e *= 1.0 + 0.6 * np.exp(-(((yy - cy) / (0.45 * e.shape[0])) ** 2 + ((xx - cx) / (0.45 * e.shape[1])) ** 2))
    cw, ch = max(1, int(round(crop_w * sx))), max(1, int(round(crop_h * sy)))
    col, row = e.sum(axis=0), e.sum(axis=1)
    best_x = best_y = 0
    if cw < e.shape[1]:
        c = np.concatenate([[0], np.cumsum(col)])
        wins = c[cw:] - c[:-cw]
        best_x = int(np.argmax(wins))
    if ch < e.shape[0]:
        c = np.concatenate([[0], np.cumsum(row)])
        wins = c[ch:] - c[:-ch]
        best_y = int(np.argmax(wins))
    return int(best_x / sx), int(best_y / sy)


def op_crop_format(img, p, ctx):
    tw, th, label = SOCIAL_FORMATS[p["format"]]
    w, h = img.size
    if p["fit"] == "cover":
        scale = max(tw / w, th / h)
        cw, ch = min(w, int(round(tw / scale))), min(h, int(round(th / scale)))
        focus = p["focus"]
        if focus == "smart":
            x, y = _energy_offset(img, cw, ch)
        else:
            x = {"left": 0, "right": w - cw}.get(focus, (w - cw) // 2)
            y = {"top": 0, "bottom": h - ch}.get(focus, (h - ch) // 2)
        x, y = max(0, min(w - cw, x)), max(0, min(h - ch, y))
        out = img.crop((x, y, x + cw, y + ch)).resize((tw, th), Image.Resampling.LANCZOS)
        if max(tw / w, th / h) > 1.05:
            ctx["notes"].append(f"عکس از {label} کوچک‌تر بود و بزرگ شد (برای کیفیتِ بهتر «بزرگ‌نماییِ هوشمند» را اضافه کنید)")
        return out
    # contain: کلِ عکس دیده می‌شود، دورش پر می‌شود
    scale = min(tw / w, th / h)
    nw, nh = max(1, int(round(w * scale))), max(1, int(round(h * scale)))
    fg = img.resize((nw, nh), Image.Resampling.LANCZOS)
    fill = p["fill"]
    if fill == "blur":
        cover = max(tw / w, th / h)
        bg = flatten(img).resize((max(tw, int(w * cover)), max(th, int(h * cover))), Image.Resampling.BILINEAR)
        left, top = (bg.width - tw) // 2, (bg.height - th) // 2
        bg = bg.crop((left, top, left + tw, top + th))
        small = bg.resize((max(1, tw // 8), max(1, th // 8)), Image.Resampling.BILINEAR)
        bg = small.filter(ImageFilter.GaussianBlur(6)).resize((tw, th), Image.Resampling.BICUBIC)
        bg = ImageEnhance.Brightness(bg).enhance(0.82)
    else:
        color = {"white": "#ffffff", "black": "#000000"}.get(fill, p["fill_color"])
        bg = Image.new("RGB", (tw, th), color)
    # کالای شفاف روی همان زمینه می‌نشیند (قالبِ شبکه‌ها شفافیت نمی‌خواهد)
    bg.paste(fg.convert("RGB"), ((tw - nw) // 2, (th - nh) // 2), fg.getchannel("A") if fg.mode == "RGBA" else None)
    return bg


def op_resize(img, p, ctx):
    long_edge = int(p["long_edge"])
    if max(img.size) <= long_edge:
        ctx["notes"].append("اندازه: عکس از این کوچک‌تر بود و دست نخورد")
        return img
    out = img.copy()
    out.thumbnail((long_edge, long_edge), Image.Resampling.LANCZOS)
    return out


def _font(size: int, bold=True):
    path = tov._find_font(tov.FONT_CANDIDATES_BOLD if bold else tov.FONT_CANDIDATES_REGULAR)
    return ImageFont.truetype(path, max(8, int(size)))


def _wrap(draw, text: str, font, max_w: int) -> list[str]:
    words, lines, cur = text.split(), [], ""
    for word in words:
        trial = (cur + " " + word).strip()
        if not cur or draw.textlength(tov.shape_rtl(trial), font=font, **tov._draw_kwargs()) <= max_w:
            cur = trial
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines[:4]


def _hex(c: str, alpha: int = 255):
    c = c.lstrip("#")
    return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16), alpha


def op_text(img, p, ctx):
    base = img.convert("RGBA")
    w, h = base.size
    layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    size = max(12, int(w * p["size"] / 100))
    main_font, sub_font = _font(size, True), _font(int(size * 0.62), False)
    max_w = int(w * 0.88)
    rows = [(line, main_font) for line in _wrap(d, p["text"], main_font, max_w)] if p["text"] else []
    rows += [(line, sub_font) for line in _wrap(d, p["subtext"], sub_font, max_w)] if p["subtext"] else []
    heights = [f.getbbox("آگ")[3] + int(f.size * 0.35) for _l, f in rows]
    block = sum(heights)
    pad = int(size * 0.6)
    top = {"top": int(h * 0.05) + pad, "center": (h - block) // 2}.get(p["position"], h - int(h * 0.05) - pad - block)
    band = p["band"]
    if band == "gradient":
        pos = p["position"]
        if pos == "top":
            y0, y1 = 0, min(h, top + block + pad * 3)
        elif pos == "bottom":
            y0, y1 = max(0, top - pad * 3), h
        else:
            y0, y1 = max(0, top - pad * 2), min(h, top + block + pad * 2)
        span = max(1, y1 - y0)
        for i in range(span):
            t = i / span
            alpha = 110 if pos == "center" else int(190 * ((1 - t) if pos == "top" else t) ** 1.3)
            d.line([(0, y0 + i), (w, y0 + i)], fill=(0, 0, 0, alpha))
    elif band in ("box", "light"):
        widths = [d.textlength(tov.shape_rtl(line), font=f, **tov._draw_kwargs()) for line, f in rows]
        bw = int(max(widths or [0]) + pad * 2)
        x0 = (w - bw) // 2
        d.rounded_rectangle([x0, top - pad, x0 + bw, top + block + pad // 2], radius=pad,
                            fill=(0, 0, 0, 150) if band == "box" else (255, 255, 255, 200))
    color = _hex(p["color"])
    y = top
    for (line, f), lh in zip(rows, heights):
        shaped = tov.shape_rtl(line)
        tw = d.textlength(shaped, font=f, **tov._draw_kwargs())
        x = (w - tw) / 2
        if band in ("none", "gradient"):
            d.text((x + max(1, size // 28), y + max(1, size // 28)), shaped, font=f, fill=(0, 0, 0, 140), **tov._draw_kwargs())
        d.text((x, y), shaped, font=f, fill=color, **tov._draw_kwargs())
        y += lh
    out = Image.alpha_composite(base, layer)
    return out if img.mode == "RGBA" else out.convert("RGB")


def _place(pos: str, w: int, h: int, lw: int, lh: int, margin: int) -> tuple[int, int]:
    return {
        "br": (w - lw - margin, h - lh - margin), "bl": (margin, h - lh - margin),
        "tr": (w - lw - margin, margin), "tl": (margin, margin),
        "center": ((w - lw) // 2, (h - lh) // 2),
    }.get(pos, (w - lw - margin, h - lh - margin))


def op_logo(img, p, ctx):
    path = ctx["logo_path"](p)
    if not path:
        raise OpError("لوگویی پیدا نشد: در «پروفایل برند» لوگو بگذارید یا عکسی از کتابخانه انتخاب کنید.")
    logo = load(path).convert("RGBA")
    w, h = img.size
    lw = max(8, int(w * p["size"] / 100))
    lh = max(1, int(logo.height * lw / logo.width))
    if lh > h * 0.6:
        lh = int(h * 0.6)
        lw = max(1, int(logo.width * lh / logo.height))
    logo = logo.resize((lw, lh), Image.Resampling.LANCZOS)
    if p["opacity"] < 100:
        logo.putalpha(logo.getchannel("A").point(lambda v: int(v * p["opacity"] / 100)))
    x, y = _place(p["position"], w, h, lw, lh, int(min(w, h) * p["margin"] / 100))
    base = img.convert("RGBA")
    base.alpha_composite(logo, (max(0, x), max(0, y)))
    return base if img.mode == "RGBA" else base.convert("RGB")


def op_watermark(img, p, ctx):
    text = p["text"] or ctx.get("store_name") or "NMarketing"
    w, h = img.size
    size = max(10, int(w * p["size"] / 100))
    font = _font(size, True)
    shaped = tov.shape_rtl(text)
    color = _hex(p["color"], int(255 * p["opacity"] / 100))
    shadow = (0, 0, 0, int(160 * p["opacity"] / 100))
    base = img.convert("RGBA")
    probe = ImageDraw.Draw(base)
    tw = int(probe.textlength(shaped, font=font, **tov._draw_kwargs())) + 4
    th = font.getbbox("آگ")[3] + 6
    stamp = Image.new("RGBA", (tw + 4, th + 4), (0, 0, 0, 0))
    sd = ImageDraw.Draw(stamp)
    sd.text((3, 3), shaped, font=font, fill=shadow, **tov._draw_kwargs())
    sd.text((1, 1), shaped, font=font, fill=color, **tov._draw_kwargs())
    if p["mode"] == "corner":
        x, y = _place(p["position"], w, h, stamp.width, stamp.height, int(min(w, h) * 0.03))
        base.alpha_composite(stamp, (max(0, x), max(0, y)))
    else:
        tile = stamp.rotate(28, expand=True, resample=Image.Resampling.BICUBIC)
        step_x, step_y = int(tile.width * 1.6), int(tile.height * 2.2)
        layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
        for row, yy in enumerate(range(-tile.height // 2, h, max(8, step_y))):
            for xx in range(-tile.width // 2 + (row % 2) * step_x // 2, w, max(8, step_x)):
                layer.paste(tile, (xx, yy), tile)
        base = Image.alpha_composite(base, layer)
    return base if img.mode == "RGBA" else base.convert("RGB")


OPS = {
    "auto_tone": op_auto_tone, "color": op_color, "look": op_look, "rotate": op_rotate,
    "crop_format": op_crop_format, "resize": op_resize, "text": op_text, "logo": op_logo, "watermark": op_watermark,
}


def run(img: Image.Image, ops: list[dict], ctx: dict) -> tuple[Image.Image, dict]:
    """کارهای سرورِ سایت به ترتیب ⇐ (تصویر، تنظیماتِ خروجی). «export» فقط قالب را تعیین می‌کند."""
    ctx.setdefault("notes", [])
    export = None
    for o in ops:
        if o["tool"] == "export":
            export = o["params"]
            continue
        fn = OPS.get(o["tool"])
        if fn is None:
            raise OpError(f"ابزارِ «{o['tool']}» روی سرورِ سایت نیست.")
        img = fn(img, o["params"], ctx)
        if max(img.size) > 12000:
            raise OpError("نتیجه بیش از اندازه بزرگ شد.")
    return img, export or {}


def default_format(img: Image.Image, source_suffix: str) -> str:
    if img.mode == "RGBA":
        return "png"
    return "webp" if source_suffix.lower() == ".webp" else "jpeg"


def save_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".part")
    tmp.write_bytes(data)
    tmp.replace(path)


def same_image(a: Image.Image, b: Image.Image) -> bool:
    if a.size != b.size or a.mode != b.mode:
        return False
    return ImageChops.difference(a.convert("RGB"), b.convert("RGB")).getbbox() is None
