"""تصویرهای صحنه: مرجعِ متنی (``product:12``، ``photo:7``، ``logo``) ⇒ فایلِ واقعیِ همان فروشگاه.

فقط عکس‌هایی که مالِ همین فروشگاه‌اند باز می‌شوند (عکسِ محصول، کتابخانهٔ ادیتورِ عکس، لوگو)؛ مرجعِ ``file:<مسیر>`` فقط وقتی
``allow_files`` روشن باشد (آزمون و نمونه‌های داخلی). تصویر بزرگ پیش از استفاده کوچک می‌شود تا حافظه‌ی سرورِ سایت (۲ گیگ) نریزد.
"""
from __future__ import annotations

import hashlib
import io
from collections import OrderedDict
from pathlib import Path

from PIL import Image, ImageOps

MAX_SIDE = 6000
Image.MAX_IMAGE_PIXELS = 80_000_000


class ImageSource:
    def __init__(self, store=None, *, allow_files: bool = False, cache_items: int = 24, cache_pixels: int = 16_000_000):
        self.store = store
        self.allow_files = allow_files
        self._cache: OrderedDict = OrderedDict()
        self._cap = cache_items
        self._cap_px = cache_pixels                      # سرورِ سایت ۲ گیگ حافظه دارد؛ کَشِ تصویر به جمعِ پیکسل‌ها محدود است
        self._px = 0
        self.missing: set[str] = set()

    def clear(self) -> None:
        self._cache.clear()
        self._px = 0

    # ---- مسیر ----
    def path(self, ref: str) -> Path | None:
        if not ref or not isinstance(ref, str):
            return None
        kind, _, raw = ref.partition(":")
        try:
            if kind == "product" and self.store is not None:
                from apps.products.models import ProductImage

                pi = ProductImage.objects.filter(pk=int(raw), product__store=self.store).first()
                return Path(pi.image.path) if pi and pi.image else None
            if kind == "photo" and self.store is not None:
                from apps.photoedit import services as photo
                from apps.photoedit.models import PhotoAsset

                a = PhotoAsset.objects.filter(pk=int(raw), store=self.store).first()
                return photo.abs_path(a.original) if a and a.original not in ("", "-") else None
            if ref == "logo" and self.store is not None and getattr(self.store, "logo", None):
                return Path(self.store.logo.path)
            if kind == "file" and self.allow_files:
                p = Path(raw)
                return p if p.is_file() else None
        except (ValueError, OSError, AttributeError):
            return None
        return None

    def open(self, ref: str, max_side: int | None = None) -> Image.Image | None:
        """تصویرِ باز و صاف‌شده (EXIF)، RGB یا RGBA، با ضلعِ بلند ≤ max_side. نبود/خراب ⇒ None."""
        side = min(MAX_SIDE, int(max_side or MAX_SIDE))
        key = (ref, side)
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key]
        p = self.path(ref)
        if p is None or not p.is_file():
            self.missing.add(ref)
            return None
        try:
            with Image.open(p) as im:
                im.load()
                im = ImageOps.exif_transpose(im)
                im = im.convert("RGBA" if (im.mode in ("RGBA", "LA", "P") and _has_alpha(im)) else "RGB")
                if max(im.size) > side:
                    im.thumbnail((side, side), Image.LANCZOS)
        except Exception:  # noqa: BLE001 — فایلِ خراب
            self.missing.add(ref)
            return None
        px = im.width * im.height
        if px <= self._cap_px:
            self._cache[key] = im
            self._px += px
        while self._cache and (len(self._cache) > self._cap or self._px > self._cap_px):
            _, old = self._cache.popitem(last=False)
            self._px -= old.width * old.height
        return im

    def size(self, ref: str) -> tuple[int, int] | None:
        p = self.path(ref)
        if p is None or not p.is_file():
            return None
        try:
            with Image.open(p) as im:
                return im.size
        except Exception:  # noqa: BLE001
            return None

    def fingerprint(self, ref: str) -> str:
        """اثرانگشتِ ریزِ تصویر (برای تشخیصِ عکس‌های هم‌محتوا)."""
        im = self.open(ref, 64)
        if im is None:
            return ""
        g = im.convert("L").resize((8, 8), Image.BILINEAR)
        return hashlib.md5(g.tobytes()).hexdigest()[:12]


def _has_alpha(im: Image.Image) -> bool:
    if im.mode in ("RGBA", "LA"):
        a = im.getchannel("A")
        return a.getextrema()[0] < 255
    if im.mode == "P":
        return "transparency" in im.info
    return False


def fit_rect(iw: int, ih: int, bw: float, bh: float, fit: str, focus) -> tuple[tuple[float, float, float, float], tuple[float, float, float, float]]:
    """⇒ (جعبهٔ برش از تصویر (x0،y0،x1،y1 به پیکسلِ تصویر)، جعبهٔ مقصد (dx،dy،dw،dh) داخلِ جعبهٔ bw×bh).

    cover: همه‌جای جعبه را می‌پوشاند و از تصویر می‌برد (نقطهٔ تمرکز focus). contain: کلِ تصویر در جعبه جا می‌شود (وسط)."""
    if iw <= 0 or ih <= 0 or bw <= 0 or bh <= 0:
        return (0, 0, max(iw, 1), max(ih, 1)), (0, 0, max(bw, 0), max(bh, 0))
    fx, fy = (focus or (0.5, 0.5))[:2]
    if fit == "contain":
        s = min(bw / iw, bh / ih)
        dw, dh = iw * s, ih * s
        return (0, 0, iw, ih), ((bw - dw) / 2, (bh - dh) / 2, dw, dh)
    box_ratio = bw / bh
    img_ratio = iw / ih
    if img_ratio > box_ratio:                        # تصویر پهن‌تر ⇒ از دو طرف می‌بُریم
        cw = ih * box_ratio
        x0 = max(0.0, min(iw - cw, fx * iw - cw / 2))
        return (x0, 0, x0 + cw, ih), (0, 0, bw, bh)
    ch = iw / box_ratio
    y0 = max(0.0, min(ih - ch, fy * ih - ch / 2))
    return (0, y0, iw, y0 + ch), (0, 0, bw, bh)


def jpeg_bytes(im: Image.Image, quality: int = 88, dpi: int | None = None) -> bytes:
    buf = io.BytesIO()
    rgb = im.convert("RGB")
    kw = {"dpi": (dpi, dpi)} if dpi else {}
    rgb.save(buf, "JPEG", quality=quality, optimize=True, progressive=False, **kw)
    return buf.getvalue()
