"""خروجی با قالب‌های دیگر (نوبت ۶ و ۸): TIFF، GIF، PDF، BMP + PSD لایه‌دار + SVGِ شکل‌ها. همه روی سرورِ سایت و بی وابستگیِ تازه.

``convert(img, fmt, quality, mode)`` تصویرِ نهایی را به بایت می‌دهد؛ ``psd_bytes(asset, project)`` از لایه‌های پروژه یک فایلِ لایه‌دار می‌سازد.

حالت‌های رنگ (``mode``، دورِ ۸):

* ``rgb`` — همان همیشه (پروفایلِ sRGB داخلِ فایل می‌نشیند).
* ``gray`` — سیاه‌وسفیدِ ۸بیتی (PNG، TIFF، JPEG، WebP، BMP، PDF).
* ``cmyk`` — CMYK با تبدیلِ ساده (استخراجِ سیاه، بی پروفایلِ چاپخانه) برای TIFF، JPEG، PDF؛ چاپخانه معمولاً RGB را خودش با پروفایلِ ماشین تبدیل می‌کند.
* ``indexed`` — ۲۵۶ رنگِ پالت‌دار (PNG، GIF، BMP، TIFF).
* ``rgb16`` — ۱۶بیتی در هر کانال (PNG، TIFF): ترکیبِ ما ۸بیتی است؛ این قالب برای تحویل به نرم‌افزارهایی است که ۱۶بیت می‌خواهند (دقتِ بیشتری ساخته نمی‌شود).
* ``lab`` — CIE L*a*b* (TIFF).
"""
from __future__ import annotations

import io
import struct
import zlib

import numpy as np
from PIL import Image

from . import layers as layers_mod
from . import psd as psd_mod

#: قالب ⇒ (پسوند، نوعِ محتوا، عنوانِ فارسی)
FORMATS = {
    "psd": ("psd", "image/vnd.adobe.photoshop", "فایلِ لایه‌دار (PSD)"),
    "tiff": ("tif", "image/tiff", "TIFF"),
    "pdf": ("pdf", "application/pdf", "PDF"),
    "gif": ("gif", "image/gif", "GIF"),
    "bmp": ("bmp", "image/bmp", "BMP"),
    "png": ("png", "image/png", "PNG"),
    "jpeg": ("jpg", "image/jpeg", "JPEG"),
    "webp": ("webp", "image/webp", "WebP"),
    "svg": ("svg", "image/svg+xml", "SVG (فقط شکل‌ها)"),
}


#: سقفِ مجموعِ پیکسلِ لایه‌های تصویریِ فایلِ PSD (حدودِ ۱۴۴ مگابایتِ خام)
PSD_MAX_PIXELS = 36_000_000


class ExportError(Exception):
    """خطایی که متنش برای کاربر است."""


#: حالتِ رنگ ⇒ (عنوانِ فارسی، قالب‌های مجاز)
MODES = {
    "rgb": ("رنگی (RGB)", ("tiff", "pdf", "gif", "bmp", "png", "jpeg", "webp")),
    "gray": ("سیاه‌وسفید (۸ بیت)", ("tiff", "pdf", "bmp", "png", "jpeg", "webp")),
    "cmyk": ("CMYK (تبدیلِ ساده)", ("tiff", "pdf", "jpeg")),
    "indexed": ("۲۵۶ رنگ (پالت)", ("tiff", "gif", "bmp", "png")),
    "rgb16": ("۱۶ بیت در هر کانال", ("tiff", "png")),
    "lab": ("Lab", ("tiff",)),
}

#: سقفِ پیکسل برای ۱۶بیتی (هر کانال ۲ بایت؛ سرورِ مشترک حافظهٔ کم دارد)
RGB16_MAX_PIXELS = 24_000_000

_SRGB_ICC: bytes | None = None


def srgb_profile() -> bytes | None:
    """پروفایلِ sRGB (LittleCMS؛ ~۵۰۰ بایت) برای جاسازی در فایل؛ اگر ImageCms نبود None."""
    global _SRGB_ICC
    if _SRGB_ICC is None:
        try:
            from PIL import ImageCms

            _SRGB_ICC = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
        except Exception:  # noqa: BLE001 — اختیاری
            _SRGB_ICC = b""
    return _SRGB_ICC or None


def rgb_to_cmyk(img: Image.Image) -> Image.Image:
    """RGB ⇒ CMYK با استخراجِ کاملِ سیاه (K = ۱ − max(R,G,B)؛ C = (۱−R−K)/(۱−K) …). بی پروفایلِ چاپ: رنگ‌ها «ساده» تبدیل می‌شوند."""
    a = np.asarray(_flat(img), np.float32) / 255.0
    k = 1.0 - a.max(axis=2)
    d = np.maximum(1.0 - k, 1e-6)
    c = (1.0 - a[..., 0] - k) / d
    m = (1.0 - a[..., 1] - k) / d
    y = (1.0 - a[..., 2] - k) / d
    out = np.clip(np.stack([c, m, y, k], axis=2) * 255.0 + 0.5, 0, 255).astype(np.uint8)
    return Image.fromarray(out, "CMYK")


def _png_chunk(tag: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)


def png16_bytes(img: Image.Image) -> bytes:
    """PNG با ۱۶ بیت در هر کانال (RGB یا RGBA)؛ هر نمونهٔ ۸بیتیِ v ⇒ v·۲۵۷ (یعنی بایتِ بالا و پایین هر دو v) — بی نیاز به ماتریسِ بزرگ."""
    if img.width * img.height > RGB16_MAX_PIXELS:
        raise ExportError(f"برای خروجیِ ۱۶ بیتی تصویر خیلی بزرگ است (سقف {RGB16_MAX_PIXELS // 1_000_000} مگاپیکسل).")
    im = img.convert("RGBA" if img.mode == "RGBA" else "RGB")
    arr = np.asarray(im)
    h, w, ch = arr.shape
    ctype = 6 if ch == 4 else 2
    comp = zlib.compressobj(6)
    parts = []
    step = max(1, 2_000_000 // max(1, w * ch * 2))
    for y0 in range(0, h, step):
        chunk = np.repeat(arr[y0:y0 + step], 2, axis=2).reshape(-1, w * ch * 2)
        rows = np.concatenate([np.zeros((chunk.shape[0], 1), np.uint8), chunk], axis=1)
        parts.append(comp.compress(rows.tobytes()))
    parts.append(comp.flush())
    icc = srgb_profile()
    out = [b"\x89PNG\r\n\x1a\n", _png_chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 16, ctype, 0, 0, 0)), _png_chunk(b"sRGB", b"\x00")]
    if icc is None:
        out.pop()
    out += [_png_chunk(b"IDAT", b"".join(parts)), _png_chunk(b"IEND", b"")]
    return b"".join(out)


def tiff16_bytes(img: Image.Image) -> bytes:
    """TIFF بی‌افتِ ۱۶بیتی (RGB یا RGBA، فشرده‌سازیِ Deflate، big-endian)."""
    if img.width * img.height > RGB16_MAX_PIXELS:
        raise ExportError(f"برای خروجیِ ۱۶ بیتی تصویر خیلی بزرگ است (سقف {RGB16_MAX_PIXELS // 1_000_000} مگاپیکسل).")
    im = img.convert("RGBA" if img.mode == "RGBA" else "RGB")
    arr = np.asarray(im)
    h, w, ch = arr.shape
    rows_per = max(1, min(h, 2_000_000 // max(1, w * ch * 2)))
    strips = []
    for y0 in range(0, h, rows_per):
        chunk = np.repeat(arr[y0:y0 + rows_per], 2, axis=2)
        strips.append(zlib.compress(chunk.tobytes(), 6))
    n = len(strips)
    body = bytearray()
    offsets = []
    pos = 8
    for s in strips:
        offsets.append(pos)
        body += s
        pos += len(s)
        if pos % 2:
            body += b"\x00"
            pos += 1
    extra = bytearray()                                     # آرایه‌های بزرگ‌تر از ۴ بایت بعد از نوارها
    def put(data: bytes) -> int:
        nonlocal pos
        at = pos
        extra.extend(data)
        pos += len(data)
        return at
    bps = put(struct.pack(">" + "H" * ch, *([16] * ch)))
    so = offsets[0] if n == 1 else put(struct.pack(">" + "I" * n, *offsets))
    sc = len(strips[0]) if n == 1 else put(struct.pack(">" + "I" * n, *[len(s) for s in strips]))
    ifd_at = pos if pos % 2 == 0 else pos + 1
    if ifd_at != pos:
        extra += b"\x00"
    SHORT, LONG = 3, 4
    entries = [
        (256, LONG, 1, w), (257, LONG, 1, h), (258, SHORT, ch, bps), (259, SHORT, 1, 8), (262, SHORT, 1, 2),
        (273, LONG, n, so), (277, SHORT, 1, ch), (278, LONG, 1, rows_per), (279, LONG, n, sc), (284, SHORT, 1, 1),
    ]
    if ch == 4:
        entries.append((338, SHORT, 1, 2))
    ifd = struct.pack(">H", len(entries))
    for tag, typ, cnt, val in entries:
        if typ == SHORT and cnt == 1:
            ifd += struct.pack(">HHIHH", tag, typ, cnt, val, 0)
        else:
            ifd += struct.pack(">HHII", tag, typ, cnt, val)
    ifd += struct.pack(">I", 0)
    return b"MM\x00\x2a" + struct.pack(">I", ifd_at) + bytes(body) + bytes(extra) + ifd


def _mode_save(img: Image.Image, fmt: str, quality: int, mode: str) -> bytes:
    """حالت‌های غیرِ RGB؛ ترکیب‌های نامجاز ⇒ ExportError با پیامِ فارسی."""
    title, allowed = MODES[mode]
    if fmt not in allowed:
        ok = "، ".join(FORMATS[f][2] for f in allowed)
        raise ExportError(f"حالتِ «{title}» فقط برای این قالب‌ها هست: {ok}.")
    buf = io.BytesIO()
    if mode == "rgb16":
        return png16_bytes(img) if fmt == "png" else tiff16_bytes(img)
    if mode == "gray":
        keep_alpha = img.mode == "RGBA" and fmt in ("png", "tiff", "webp")
        g = img.convert("LA") if keep_alpha else _flat(img).convert("L")
        if fmt == "png":
            g.save(buf, "PNG", optimize=True)
        elif fmt == "tiff":
            g.save(buf, "TIFF", compression="tiff_lzw")
        elif fmt == "jpeg":
            g.save(buf, "JPEG", quality=max(40, min(98, int(quality))), optimize=True)
        elif fmt == "webp":
            g.convert("RGBA" if keep_alpha else "L").save(buf, "WEBP", quality=max(40, min(98, int(quality))), method=4)
        elif fmt == "bmp":
            g.save(buf, "BMP")
        else:
            g.save(buf, "PDF", resolution=150.0)
        return buf.getvalue()
    if mode == "cmyk":
        c = rgb_to_cmyk(img)
        if fmt == "tiff":
            c.save(buf, "TIFF", compression="tiff_lzw")
        elif fmt == "jpeg":
            c.save(buf, "JPEG", quality=max(40, min(98, int(quality))), optimize=True)
        else:
            c.save(buf, "PDF", resolution=150.0)
        return buf.getvalue()
    if mode == "indexed":
        flat = _flat(img)
        p = flat.quantize(256, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.FLOYDSTEINBERG)
        if fmt == "png":
            p.save(buf, "PNG", optimize=True)
        elif fmt == "gif":
            p.save(buf, "GIF", optimize=True)
        elif fmt == "bmp":
            p.save(buf, "BMP")
        else:
            p.save(buf, "TIFF", compression="tiff_lzw")
        return buf.getvalue()
    # lab
    from PIL import ImageCms

    srgb = ImageCms.createProfile("sRGB")
    lab = ImageCms.createProfile("LAB")
    out = ImageCms.profileToProfile(_flat(img), srgb, lab, outputMode="LAB")
    out.save(buf, "TIFF", compression="tiff_lzw")
    return buf.getvalue()


def _flat(img: Image.Image, bg=(255, 255, 255)) -> Image.Image:
    if img.mode == "RGBA":
        out = Image.new("RGB", img.size, bg)
        out.paste(img, mask=img.getchannel("A"))
        return out
    return img.convert("RGB")


def convert(img: Image.Image, fmt: str, quality: int = 92, mode: str = "rgb") -> bytes:
    """تصویرِ نهایی ⇒ بایتِ قالبِ خواسته (PSD جدا ساخته می‌شود). ``mode``: rgb|gray|cmyk|indexed|rgb16|lab (به توضیحِ بالای ماژول)."""
    fmt = {"jpg": "jpeg", "tif": "tiff"}.get(fmt, fmt)
    if fmt not in FORMATS or fmt in ("psd", "svg"):
        raise ExportError("این قالب پشتیبانی نمی‌شود.")
    if mode not in MODES:
        raise ExportError("حالتِ رنگ ناشناخته است.")
    if mode != "rgb":
        return _mode_save(img, fmt, quality, mode)
    icc = srgb_profile()
    kw = {"icc_profile": icc} if icc else {}
    buf = io.BytesIO()
    if fmt == "tiff":
        img.convert("RGBA" if img.mode == "RGBA" else "RGB").save(buf, "TIFF", compression="tiff_lzw", **kw)
    elif fmt == "pdf":
        _flat(img).save(buf, "PDF", resolution=150.0)
    elif fmt == "gif":
        flat = _flat(img)
        flat.quantize(256, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.FLOYDSTEINBERG).save(buf, "GIF", optimize=True)
    elif fmt == "bmp":
        _flat(img).save(buf, "BMP")
    elif fmt == "png":
        img.save(buf, "PNG", optimize=img.width * img.height < 6_000_000, **kw)
    elif fmt == "jpeg":
        _flat(img).save(buf, "JPEG", quality=max(40, min(98, int(quality))), optimize=True, progressive=True, **kw)
    else:
        img.save(buf, "WEBP", quality=max(40, min(98, int(quality))), method=4, **kw)
    return buf.getvalue()


def psd_bytes(final: Image.Image, frame: Image.Image, state_layers: list[dict], ctx: dict, project: int, base_name: str = "عکس") -> tuple[bytes, list[str]]:
    """فایلِ لایه‌دار: هر لایهٔ تصویر/نقاشی/متن/شکل و عکسِ پایه جدا؛ تصویرِ ترکیبیِ نهایی (با تنظیم‌ها) در بخشِ merged. ⇒ (بایت‌ها، یادداشت‌ها)."""
    norm = layers_mod.normalize_layers(state_layers, base="one")
    W, H = frame.size
    # سقفِ حافظه: هر لایهٔ عکس/نقاشی/پایه یک بومِ کاملِ RGBA خام می‌شود؛ سرورِ مشترک چند گیگ بیشتر ندارد
    big = sum(1 for l in norm if l["type"] in ("base", "image"))
    if W * H * max(1, big) > PSD_MAX_PIXELS:
        mp = W * H * max(1, big) / 1e6
        raise ExportError(f"این پروژه برای فایلِ لایه‌دار خیلی بزرگ است (حدود {mp:.0f} مگاپیکسلِ لایه؛ سقف {PSD_MAX_PIXELS // 1_000_000}). اندازهٔ بوم یا تعدادِ لایه‌های تصویری را کم کنید یا خروجیِ PNG/TIFF بگیرید.")
    rasters = layers_mod.layer_rasters(frame, norm, ctx, project=project)
    plan = []
    for r in rasters:
        l = r["layer"]
        im = Image.fromarray(r["tile"], "RGBA")
        name = base_name if l["type"] == "base" else str(l.get("name") or "لایه")
        plan.append(psd_mod.PsdLayer(name=name, img=im, x=int(r["x0"]), y=int(r["y0"]), opacity=float(l.get("opacity", 1)), blend=str(l.get("blend", "normal")),
                                     visible=bool(l.get("visible", True))))
    notes = []
    skipped = [l for l in norm if l["type"] in ("adjust", "retouch", "redeye")]
    if skipped:
        notes.append(f"{len(skipped)} لایهٔ تنظیم/روتوش/قرمزیِ چشم در فایلِ لایه‌دار به‌صورتِ لایه نمی‌آید (اثرشان در تصویرِ ترکیبیِ فایل هست)")
    if any(l["type"] == "group" for l in norm):
        notes.append("گروه‌ها در فایلِ لایه‌دار صاف شده‌اند")
    if any(l.get("clip") for l in norm):
        notes.append("«برش به لایهٔ زیرین» در فایلِ لایه‌دار به‌صورتِ ویژگی نیست")
    return psd_mod.write_psd((W, H), final, plan), notes


# ───────────────────────────── SVG (دورِ ۸): فقط شکل‌ها و مسیرها (برداری)؛ عکس، متن و تنظیم‌ها در SVG نمی‌آیند

_SVG_BLEND = {"multiply": "multiply", "screen": "screen", "overlay": "overlay", "soft-light": "soft-light", "hard-light": "hard-light", "darken": "darken",
              "lighten": "lighten", "color-dodge": "color-dodge", "color-burn": "color-burn", "difference": "difference", "exclusion": "exclusion",
              "hue": "hue", "saturation": "saturation", "color": "color", "luminosity": "luminosity"}


def _num(v: float) -> str:
    s = f"{v:.2f}".rstrip("0").rstrip(".")
    return s or "0"


def _svg_path_d(path: dict, x0: float, y0: float, w: float, h: float) -> str:
    """مسیرِ قلم (واحدِ جعبه) ⇒ ویژگیِ d با منحنیِ مکعبی؛ x0,y0 = گوشهٔ جعبه به پیکسل، w,h = اندازهٔ جعبه به پیکسل."""
    pts = path.get("pts") or []
    if len(pts) < 2:
        return ""

    def P(p, key=None):
        dx, dy = (0.0, 0.0)
        hv = p.get(key) if key else None
        if isinstance(hv, (list, tuple)) and len(hv) >= 2:
            dx, dy = float(hv[0]), float(hv[1])
        return x0 + (float(p["x"]) + dx) * w, y0 + (float(p["y"]) + dy) * h

    out = ["M" + " ".join(_num(c) for c in P(pts[0]))]
    n = len(pts)
    closed = bool(path.get("closed"))
    for i in range(n if closed else n - 1):
        a, b = pts[i], pts[(i + 1) % n]
        if not a.get("ho") and not b.get("hi"):
            out.append("L" + " ".join(_num(c) for c in P(b)))
        else:
            c1, c2 = P(a, "ho") if a.get("ho") else P(a), P(b, "hi") if b.get("hi") else P(b)
            out.append("C" + " ".join(_num(c) for c in (*c1, *c2, *P(b))))
    if closed:
        out.append("Z")
    return "".join(out)


def svg_bytes(state_layers: list[dict], width: int, height: int) -> tuple[bytes, list[str]]:
    """لایه‌های شکلِ دیده‌شده ⇒ SVGِ برداری روی بومِ width×height. ⇒ (بایت‌ها، یادداشت‌ها). بدونِ شکل ⇒ ExportError."""
    from xml.sax.saxutils import escape

    norm = layers_mod.normalize_layers(state_layers, base="one")
    shapes = [l for l in norm if l["type"] == "shape" and l.get("visible", True)]
    if not shapes:
        raise ExportError("برای خروجیِ SVG دست‌کم یک لایهٔ شکل لازم است (مستطیل، بیضی، خط یا شکلِ آماده). عکس و متن در SVG نمی‌آیند.")
    defs, body = [], []
    for i, l in enumerate(shapes):
        W, H = float(width), float(height)
        cx, cy = l["cx"] * W, l["cy"] * H
        w, h = l["w"] * W, l["h"] * W
        fill_attr, stroke_attr = 'fill="none"', ""
        f = l.get("fill")
        if f and l["shape"] != "line":
            if f["type"] == "gradient":
                gid = f"g{i}"
                import math

                a = math.radians(float(f.get("angle", 0)))
                dx, dy = math.cos(a) / 2, math.sin(a) / 2
                defs.append(f'<linearGradient id="{gid}" x1="{_num(0.5 - dx)}" y1="{_num(0.5 - dy)}" x2="{_num(0.5 + dx)}" y2="{_num(0.5 + dy)}">'
                            f'<stop offset="0" stop-color="{f["c0"]}"/><stop offset="1" stop-color="{f["c1"]}"/></linearGradient>')
                fill_attr = f'fill="url(#{gid})"'
            else:
                fill_attr = f'fill="{f["color"]}" fill-opacity="{_num(float(f["opacity"]))}"'
        st = l.get("stroke")
        if st:
            stroke_attr = f' stroke="{st["color"]}" stroke-width="{_num(float(st["w"]) * W)}" stroke-linejoin="round" stroke-linecap="round"'
        extra = ""
        if float(l.get("opacity", 1)) < 0.999:
            extra += f' opacity="{_num(float(l["opacity"]))}"'
        if l.get("blend") in _SVG_BLEND:
            extra += f' style="mix-blend-mode:{_SVG_BLEND[l["blend"]]}"'
        tr = f' transform="rotate({_num(float(l.get("rot", 0)))} {_num(cx)} {_num(cy)})"' if abs(float(l.get("rot", 0))) > 0.01 else ""
        name = escape(str(l.get("name") or "شکل"), {'"': "&quot;"})
        x0, y0 = cx - w / 2, cy - h / 2
        if l["shape"] == "rect":
            rad = float(l.get("radius", 0)) * min(w, h) / 2
            elem = f'<rect x="{_num(x0)}" y="{_num(y0)}" width="{_num(w)}" height="{_num(h)}"' + (f' rx="{_num(rad)}"' if rad > 0.5 else "")
        elif l["shape"] == "ellipse":
            elem = f'<ellipse cx="{_num(cx)}" cy="{_num(cy)}" rx="{_num(w / 2)}" ry="{_num(h / 2)}"'
        elif l["shape"] == "line":
            elem = f'<line x1="{_num(x0)}" y1="{_num(cy)}" x2="{_num(x0 + w)}" y2="{_num(cy)}"'
            if not st:
                stroke_attr = ' stroke="#000000" stroke-width="2"'
        else:
            d = _svg_path_d(l.get("path") or {}, x0, y0, w, h)
            if not d:
                continue
            elem = f'<path d="{d}"'
        body.append(f'<g id="layer{i + 1}" data-name="{name}"{tr}{extra}>{elem} {fill_attr}{stroke_attr}/></g>')
    notes = []
    skipped = [l for l in norm if l["type"] in ("image", "text", "adjust", "retouch", "redeye") and l.get("visible", True)]
    if skipped:
        notes.append(f"{len(skipped)} لایهٔ تصویر/متن/تنظیم در SVG نیامد (فقط شکل‌ها برداری‌اند)")
    if any(l.get("fx") and any((l["fx"] or {}).values()) for l in shapes):
        notes.append("سایه، درخشش و دورخطِ لایه در SVG نیامد")
    svg = (f'<?xml version="1.0" encoding="UTF-8"?>\n<svg xmlns="http://www.w3.org/2000/svg" width="{int(width)}" height="{int(height)}" viewBox="0 0 {int(width)} {int(height)}">'
           + (f"<defs>{''.join(defs)}</defs>" if defs else "") + "".join(body) + "</svg>\n")
    return svg.encode("utf-8"), notes
