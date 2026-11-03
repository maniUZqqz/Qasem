"""«پرکردنِ هوشمند»: برشِ اطرافِ ماسک برای FLUX و چسباندنِ برگشتیِ نتیجه روی پیکسل‌های اصل.

بدونِ Django (فقط Pillow/numpy/cv2). جریان:

    prep = prepare(image_png, mask_png, prompt)       # برشِ اطرافِ ماسک + فایل‌هایی که به گره می‌روند
    ... گره prep.image_png / prep.mask_png را با FLUX پر می‌کند ...
    res = paste_back(prep.crop_size, result_image, full_mask, prep.feather,
                     origin=prep.rect[:2], canvas=prep.canvas, grow=prep.grow_full)
    res.patch      # RGBA: رنگ = نتیجه، آلفا = ماسکِ نرم‌شده (فقط تا جعبهٔ ماسک)
    res.placement  # {"cx", "cy", "w"} کسری از بوم ⇒ لایهٔ تصویری دقیقاً روی همان پیکسل‌های اصل می‌نشیند
"""
from __future__ import annotations

import io
import math
from dataclasses import dataclass, field

import cv2
import numpy as np
from PIL import Image

from .inpaint_graph import grow_for

MAX_SIDE = 2048                  # بزرگ‌ترین ضلعِ تصویرِ ورودی (پیکسل)
MAX_BYTES = 20 * 1024 * 1024     # بزرگ‌ترین فایل
MIN_SIDE = 64
MAX_PROMPT = 500
PAD_FRAC = 0.35                  # حاشیه = ۳۵٪ ِ بزرگ‌ترین ضلعِ جعبهٔ ماسک …
MIN_PAD = 64                     # … دست‌کم ۶۴ پیکسل
MIN_CONTEXT = 512                # برشِ کوچک‌تر از این بافتِ کافی به مدل نمی‌دهد (تا جایی که عکس اجازه بدهد)
MODEL_MAX = 1024                 # بزرگ‌ترین ضلعِ تصویری که به FLUX می‌رود
MODEL_MIN = 512                  # عکسِ خیلی کوچک تا این اندازه بزرگ می‌شود (FLUX روی ۱۴۴ پیکسل خوب نمی‌سازد)
ALIGN = 16                       # ابعادِ ورودیِ FLUX مضرب ِ ۱۶


class InpaintError(Exception):
    """متنش برای کاربر است (فارسی)."""


@dataclass
class Prepared:
    canvas: tuple[int, int]                    # (W, H) ِ تصویرِ ورودی
    bbox: tuple[int, int, int, int]            # جعبهٔ ماسک (x0, y0, x1, y1) — x1/y1 انحصاری
    rect: tuple[int, int, int, int]            # جعبهٔ برش
    size: tuple[int, int]                      # اندازه‌ای که به گره می‌رود (مضرب ۱۶)
    scale: float                               # size[0] / پهنای برش
    image_png: bytes = field(repr=False, default=b"")
    mask_png: bytes = field(repr=False, default=b"")        # ماسکِ نرمِ اندازهٔ مدل (سفید = پر کن)
    full_mask_png: bytes = field(repr=False, default=b"")   # ماسکِ دودویی در اندازهٔ برش (برای چسباندنِ برگشتی)
    feather: float = 3.0                       # σ ِ نرم‌کردنِ لبه، پیکسلِ اندازهٔ برش
    grow: int = 4                              # بزرگ‌کردنِ ماسک در گراف (پیکسلِ اندازهٔ مدل)
    grow_full: int = 4                         # همان، پیکسلِ اندازهٔ برش
    prompt: str = ""
    mask_fraction: float = 0.0

    @property
    def crop_size(self) -> tuple[int, int]:
        return self.rect[2] - self.rect[0], self.rect[3] - self.rect[1]

    def meta(self) -> dict:
        """آنچه در payload ِ کار می‌ماند تا پسان بتوان چسباند."""
        return {"canvas": list(self.canvas), "bbox": list(self.bbox), "rect": list(self.rect), "size": list(self.size),
                "scale": round(self.scale, 5), "feather": round(self.feather, 3), "grow": self.grow,
                "grow_full": self.grow_full, "prompt": self.prompt, "mask_fraction": round(self.mask_fraction, 5)}


@dataclass
class PasteResult:
    patch: Image.Image                         # RGBA، به اندازهٔ bbox
    bbox: tuple[int, int, int, int]            # جای patch روی بوم (پیکسل)
    placement: dict | None                     # {"cx","cy","w"} کسری از بوم (اگر canvas داده شده)
    composite: Image.Image | None = None       # اگر orig_crop تصویر بود: patch روی آن (برای وارسی/پیش‌نمایش)


# ───────────────────────────── خواندنِ ورودی‌ها

def _open(raw: bytes, what: str) -> Image.Image:
    if not raw:
        raise InpaintError(f"{what} خالی است.")
    if len(raw) > MAX_BYTES:
        raise InpaintError(f"{what} بزرگ‌تر از ۲۰ مگابایت است.")
    try:
        im = Image.open(io.BytesIO(raw))
        im.load()
    except Exception as exc:  # noqa: BLE001
        raise InpaintError(f"{what} عکسِ معتبری نیست.") from exc
    if max(im.size) > MAX_SIDE:
        raise InpaintError(f"{what} بزرگ‌تر از ۲۰۴۸ پیکسل است؛ کوچک‌ترش کنید.")
    if min(im.size) < MIN_SIDE:
        raise InpaintError(f"{what} خیلی کوچک است (دست‌کم ۶۴ پیکسل).")
    return im


def load_image(raw: bytes) -> Image.Image:
    """PNG/JPEG ⇐ RGB (شفافیت روی سفید)."""
    im = _open(raw, "تصویر")
    if im.mode in ("RGBA", "LA", "PA") or (im.mode == "P" and "transparency" in im.info):
        rgba = im.convert("RGBA")
        bg = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
        return Image.alpha_composite(bg, rgba).convert("RGB")
    return im.convert("RGB")


def mask_array(im: Image.Image) -> np.ndarray:
    """ماسک ⇐ uint8 ِ خاکستری (۲۵۵ = پر کن). سفید روی شفاف و آلفای تنها هم درست خوانده می‌شود."""
    if im.mode in ("RGBA", "LA", "PA") or (im.mode == "P" and "transparency" in im.info):
        rgba = im.convert("RGBA")
        lum = np.asarray(rgba.convert("L"), dtype=np.uint8)
        alpha = np.asarray(rgba.getchannel("A"), dtype=np.uint8)
        return alpha.copy() if int(lum.max()) == 0 else np.minimum(lum, alpha)
    return np.asarray(im.convert("L"), dtype=np.uint8).copy()


def load_mask(raw: bytes, size: tuple[int, int]) -> np.ndarray:
    im = _open(raw, "ماسک")
    if im.size != tuple(size):
        if abs(im.size[0] / im.size[1] - size[0] / size[1]) / (size[0] / size[1]) > 0.02:
            raise InpaintError("اندازهٔ ماسک با تصویر یکی نیست.")
        im = im.resize(tuple(size), Image.Resampling.BILINEAR)
    return mask_array(im)


def mask_bbox(binary: np.ndarray) -> tuple[int, int, int, int]:
    ys, xs = np.nonzero(binary)
    if xs.size == 0:
        raise InpaintError("ناحیه‌ای انتخاب نشده است؛ با قلم یا انتخاب جایی را که باید پر شود مشخص کنید.")
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


# ───────────────────────────── برش

def _grow_span(lo: int, hi: int, want: int, limit: int) -> tuple[int, int]:
    """بازهٔ [lo, hi) را دست‌کم ``want`` بلند می‌کند (به هر دو سو، داخلِ [0, limit])."""
    want = min(want, limit)
    n = hi - lo
    if n >= want:
        return lo, hi
    need = want - n
    lo2, hi2 = lo - need // 2, hi + (need - need // 2)
    if lo2 < 0:
        hi2 += -lo2
        lo2 = 0
    if hi2 > limit:
        lo2 -= hi2 - limit
        hi2 = limit
    return max(0, lo2), min(limit, hi2)


def _align_span(lo: int, hi: int, limit: int) -> tuple[int, int]:
    n = hi - lo
    target = -(-n // ALIGN) * ALIGN
    if target == n or target > limit:      # به مضربِ ۱۶ نمی‌رسد (عکس خودش مضرب نیست) ⇒ بعداً بازنمونه می‌شود
        return lo, hi
    return _grow_span(lo, hi, target, limit)


def _round_align(v: float) -> int:
    return max(MIN_SIDE, int(round(v / ALIGN)) * ALIGN)


def plan_crop(canvas: tuple[int, int], bbox: tuple[int, int, int, int]):
    """جعبهٔ برش + اندازهٔ ورودیِ مدل + مقیاس. ⇐ (rect, size, scale)."""
    W, H = canvas
    bx0, by0, bx1, by1 = bbox
    pad = max(MIN_PAD, math.ceil(PAD_FRAC * max(bx1 - bx0, by1 - by0)))
    x0, x1 = max(0, bx0 - pad), min(W, bx1 + pad)
    y0, y1 = max(0, by0 - pad), min(H, by1 + pad)
    x0, x1 = _grow_span(x0, x1, MIN_CONTEXT, W)
    y0, y1 = _grow_span(y0, y1, MIN_CONTEXT, H)
    x0, x1 = _align_span(x0, x1, W)
    y0, y1 = _align_span(y0, y1, H)
    cw, ch = x1 - x0, y1 - y0
    long = max(cw, ch)
    scale = MODEL_MAX / long if long > MODEL_MAX else (MODEL_MIN / long if long < MODEL_MIN else 1.0)
    if scale == 1.0 and cw % ALIGN == 0 and ch % ALIGN == 0:
        size = (cw, ch)
    else:
        size = (_round_align(cw * scale), _round_align(ch * scale))
    return (x0, y0, x1, y1), size, size[0] / cw


def default_feather(crop_size: tuple[int, int]) -> float:
    return float(min(12.0, max(2.0, 0.008 * max(crop_size))))


def _png(im: Image.Image) -> bytes:
    buf = io.BytesIO()
    im.save(buf, "PNG", compress_level=3)
    return buf.getvalue()


def prepare(image_png_bytes: bytes, mask_png_bytes: bytes, prompt: str = "") -> Prepared:
    """تصویر + ماسک ⇐ برشِ اطرافِ ماسک و فایل‌هایی که به گره می‌روند. خطای ورودی ⇒ InpaintError (فارسی)."""
    img = load_image(image_png_bytes)
    W, H = img.size
    mask = load_mask(mask_png_bytes, (W, H))
    binary = mask >= 128
    bbox = mask_bbox(binary)
    rect, size, scale = plan_crop((W, H), bbox)
    x0, y0, x1, y1 = rect
    cw, ch = x1 - x0, y1 - y0

    crop = img.crop(rect)
    full = (binary[y0:y1, x0:x1].astype(np.uint8)) * 255
    model_img = crop if size == (cw, ch) else crop.resize(size, Image.Resampling.LANCZOS)

    full_im = Image.fromarray(full)
    if size == (cw, ch):
        hard = full > 0
    else:      # کم‌ترین لکه/قلمِ نازک با بازنمونه‌کردن گم نشود: هر چه کمی سفید شد ⇒ سفید
        hard = np.asarray(full_im.resize(size, Image.Resampling.BILINEAR), dtype=np.uint8) >= 32
    hard_u8 = hard.astype(np.uint8) * 255
    sigma = max(1.0, 0.003 * max(size))
    soft = np.maximum(hard_u8, cv2.GaussianBlur(hard_u8, (0, 0), sigma))      # درونِ ماسک ۲۵۵، بیرونش شیبِ نرم

    return Prepared(
        canvas=(W, H), bbox=bbox, rect=rect, size=size, scale=scale,
        image_png=_png(model_img), mask_png=_png(Image.fromarray(soft)), full_mask_png=_png(full_im),
        feather=default_feather((cw, ch)), grow=grow_for(size), grow_full=max(1, round(grow_for(size) * cw / size[0])),
        prompt=" ".join(str(prompt or "").split())[:MAX_PROMPT], mask_fraction=float(binary.mean()))


# ───────────────────────────── چسباندنِ برگشتی

def placement_for(bbox: tuple[int, int, int, int], canvas: tuple[int, int]) -> dict:
    """جای patch به‌صورتِ کسری از بوم: مرکز (cx, cy) و پهنا (w) — همان قراردادِ لایهٔ تصویری."""
    W, H = canvas
    x0, y0, x1, y1 = bbox
    return {"cx": round((x0 + x1) / 2 / W, 6), "cy": round((y0 + y1) / 2 / H, 6), "w": round((x1 - x0) / W, 6)}


def _size_of(orig_crop) -> tuple[int, int]:
    if hasattr(orig_crop, "size") and not isinstance(orig_crop, (tuple, list)):
        return int(orig_crop.size[0]), int(orig_crop.size[1])
    w, h = orig_crop
    return int(w), int(h)


def paste_back(orig_crop, result_crop: Image.Image, mask, feather: float | None = None, *,
               origin: tuple[int, int] = (0, 0), canvas: tuple[int, int] | None = None, grow: int = 0) -> PasteResult:
    """نتیجهٔ گره را به اندازهٔ برشِ اصل برمی‌گرداند و با لبهٔ گاوسیِ نرم یک patch ِ RGBA می‌سازد.

    ``orig_crop``: برشِ اصل (تصویر) یا فقط اندازه‌اش (پهنا، ارتفاع)؛ ``result_crop``: خروجیِ گره (هر اندازه‌ای — به
    اندازهٔ برش برمی‌گردد)؛ ``mask``: ماسکِ اندازهٔ برش (تصویر یا آرایه، سفید = پرشده)؛ ``grow``: پیکسلِ بزرگ‌شدنِ
    ماسک در گراف (ناحیهٔ بازسازی‌شده از ماسکِ کاربر کمی بزرگ‌تر است)؛ ``origin``: گوشهٔ بالا-چپِ برش روی بوم.
    آلفا = max(ماسکِ نرم‌شده، ماسکِ خودِ کاربر) ⇒ درونِ ماسکِ کاربر کاملاً نتیجه است و بیرونِ patch دست‌نخورده می‌ماند.
    """
    cw, ch = _size_of(orig_crop)
    res = result_crop.convert("RGB")
    if res.size != (cw, ch):
        res = res.resize((cw, ch), Image.Resampling.LANCZOS)
    m = mask_array(mask) if isinstance(mask, Image.Image) else np.asarray(mask, dtype=np.uint8)
    if m.shape != (ch, cw):
        m = np.asarray(Image.fromarray(m).resize((cw, ch), Image.Resampling.BILINEAR), dtype=np.uint8)
    user = np.where(m >= 128, 255, 0).astype(np.uint8)
    if not user.any():
        raise InpaintError("ماسک خالی است.")
    sigma = default_feather((cw, ch)) if feather is None else float(feather)
    grown = user
    if grow and grow > 0:
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * int(grow) + 1, 2 * int(grow) + 1))
        grown = cv2.dilate(user, k)
    soft = cv2.GaussianBlur(grown.astype(np.float32), (0, 0), sigma) if sigma > 0 else grown.astype(np.float32)
    alpha = np.clip(np.maximum(np.rint(soft), user), 0, 255).astype(np.uint8)
    ys, xs = np.nonzero(alpha)
    x0, x1, y0, y1 = int(xs.min()), int(xs.max()) + 1, int(ys.min()), int(ys.max()) + 1
    rgb = np.asarray(res, dtype=np.uint8)
    patch = Image.fromarray(np.dstack([rgb[y0:y1, x0:x1], alpha[y0:y1, x0:x1]]))
    bbox = (origin[0] + x0, origin[1] + y0, origin[0] + x1, origin[1] + y1)
    composite = None
    if isinstance(orig_crop, Image.Image):
        full = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
        full.paste(patch, (x0, y0))
        composite = Image.alpha_composite(orig_crop.convert("RGBA"), full).convert("RGB")
    return PasteResult(patch=patch, bbox=bbox, placement=placement_for(bbox, canvas) if canvas else None,
                       composite=composite)
