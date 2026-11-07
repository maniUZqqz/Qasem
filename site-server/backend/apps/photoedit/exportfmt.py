"""خروجی با قالب‌های دیگر (نوبت ۶): TIFF، GIF، PDF، BMP + PSD لایه‌دار. همه روی سرورِ سایت و بی وابستگیِ تازه.

``convert(img, fmt)`` تصویرِ نهایی را به بایت می‌دهد؛ ``psd_bytes(asset, project)`` از لایه‌های پروژه یک فایلِ لایه‌دار می‌سازد."""
from __future__ import annotations

import io

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
}


#: سقفِ مجموعِ پیکسلِ لایه‌های تصویریِ فایلِ PSD (حدودِ ۱۴۴ مگابایتِ خام)
PSD_MAX_PIXELS = 36_000_000


class ExportError(Exception):
    """خطایی که متنش برای کاربر است."""


def _flat(img: Image.Image, bg=(255, 255, 255)) -> Image.Image:
    if img.mode == "RGBA":
        out = Image.new("RGB", img.size, bg)
        out.paste(img, mask=img.getchannel("A"))
        return out
    return img.convert("RGB")


def convert(img: Image.Image, fmt: str, quality: int = 92) -> bytes:
    """تصویرِ نهایی ⇒ بایتِ قالبِ خواسته (PSD جدا ساخته می‌شود)."""
    fmt = {"jpg": "jpeg", "tif": "tiff"}.get(fmt, fmt)
    if fmt not in FORMATS or fmt == "psd":
        raise ExportError("این قالب پشتیبانی نمی‌شود.")
    buf = io.BytesIO()
    if fmt == "tiff":
        img.convert("RGBA" if img.mode == "RGBA" else "RGB").save(buf, "TIFF", compression="tiff_lzw")
    elif fmt == "pdf":
        _flat(img).save(buf, "PDF", resolution=150.0)
    elif fmt == "gif":
        flat = _flat(img)
        flat.quantize(256, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.FLOYDSTEINBERG).save(buf, "GIF", optimize=True)
    elif fmt == "bmp":
        _flat(img).save(buf, "BMP")
    elif fmt == "png":
        img.save(buf, "PNG", optimize=img.width * img.height < 6_000_000)
    elif fmt == "jpeg":
        _flat(img).save(buf, "JPEG", quality=max(40, min(98, int(quality))), optimize=True, progressive=True)
    else:
        img.save(buf, "WEBP", quality=max(40, min(98, int(quality))), method=4)
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
