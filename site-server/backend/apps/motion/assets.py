"""تصویرهای ویدیوی موشن: لوگو، عکسِ محصول، اسکرین‌شات.

منبع‌ها (ref) فقط از خودِ فروشگاه‌اند: بارگذاریِ موشن (`upload:ID`)، عکسِ محصول (`pimg:ID`)، ادیتورِ عکس (`photo:ID`)، تصویرِ ساخته‌شده
(`gimg:ID`) و لوگوی فروشگاه (`store-logo`). هر کدام کوچک می‌شود (ضلعِ بلند ≤ ۱۴۰۰) و برای رندر به بایت/فایل برمی‌گردد.
"""
from __future__ import annotations

import base64
import hashlib
import io
import logging
import re
from pathlib import Path

from django.conf import settings

from .models import MotionAsset

logger = logging.getLogger(__name__)

MAX_SIDE = 1400
MAX_UPLOAD_MB = 12
MAX_BYTES_AFTER = 2_500_000
ALLOWED_EXT = (".png", ".jpg", ".jpeg", ".webp")


class AssetError(ValueError):
    pass


def media_root() -> Path:
    return Path(settings.MEDIA_ROOT)


def media_url(rel: str) -> str:
    return settings.MEDIA_URL.rstrip("/") + "/" + str(rel).lstrip("/")


def _open(data: bytes):
    from PIL import Image

    try:
        im = Image.open(io.BytesIO(data))
        im.load()
    except Exception as exc:  # noqa: BLE001
        raise AssetError("فایل تصویرِ معتبر نیست.") from exc
    return im


def shrink(data: bytes) -> tuple[bytes, str, int, int, bool]:
    """(بایتِ کوچک‌شده, پسوند, عرض, ارتفاع, آلفا دارد؟). PNG با شفافیت می‌ماند؛ بقیه JPEG ۸۸."""
    from PIL import Image, ImageOps

    im = _open(data)
    im = ImageOps.exif_transpose(im)
    alpha = im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info)
    w, h = im.size
    if max(w, h) > MAX_SIDE:
        k = MAX_SIDE / max(w, h)
        im = im.resize((max(1, round(w * k)), max(1, round(h * k))), Image.LANCZOS)
    buf = io.BytesIO()
    if alpha:
        im.convert("RGBA").save(buf, "PNG", optimize=True)
        ext = ".png"
    else:
        im.convert("RGB").save(buf, "JPEG", quality=88, optimize=True)
        ext = ".jpg"
    out = buf.getvalue()
    q = 80
    while len(out) > MAX_BYTES_AFTER and not alpha and q > 40:
        buf = io.BytesIO()
        im.convert("RGB").save(buf, "JPEG", quality=q, optimize=True)
        out, q = buf.getvalue(), q - 10
    if len(out) > MAX_BYTES_AFTER * 2:
        raise AssetError("تصویر پس از کوچک‌کردن هم خیلی بزرگ است.")
    return out, ext, im.size[0], im.size[1], alpha


def add_upload(store, file_obj, title: str = "") -> MotionAsset:
    name = getattr(file_obj, "name", "") or "image"
    if Path(name).suffix.lower() not in ALLOWED_EXT:
        raise AssetError("فقط تصویرِ PNG، JPG یا WebP.")
    size = getattr(file_obj, "size", 0) or 0
    if size > MAX_UPLOAD_MB * 1024 * 1024:
        raise AssetError(f"حجمِ تصویر از {MAX_UPLOAD_MB} مگابایت بیشتر است.")
    data = file_obj.read()
    out, ext, w, h, alpha = shrink(data)
    sha = hashlib.sha1(out).hexdigest()
    rel = f"motion/assets/{store.pk}/{sha[:16]}{ext}"
    path = media_root() / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(out)
    row = MotionAsset.objects.filter(store=store, sha1=sha).first()
    if row:
        return row
    return MotionAsset.objects.create(store=store, title=(title or Path(name).stem)[:200], path=rel, width=w, height=h, has_alpha=alpha, sha1=sha)


def asset_dict(a: MotionAsset) -> dict:
    return {"id": a.pk, "ref": f"upload:{a.pk}", "title": a.title, "url": media_url(a.path), "width": a.width, "height": a.height, "alpha": a.has_alpha}


_PATH_OK = re.compile(r"^[\w./\-؀-ۿ ]+$")


def _safe_media_path(rel: str) -> Path | None:
    rel = str(rel or "").lstrip("/")
    if not rel or ".." in rel.split("/") or not _PATH_OK.match(rel):
        return None
    p = media_root() / rel
    try:
        p.resolve().relative_to(media_root().resolve())
    except ValueError:
        return None
    return p if p.is_file() else None


def _field_path(field) -> Path | None:
    try:
        if field and getattr(field, "name", ""):
            return _safe_media_path(field.name)
    except Exception:  # noqa: BLE001
        return None
    return None


def locate(store, ref: str) -> Path:
    """ref ⇒ فایلِ تصویر روی دیسک؛ فقط متعلق به همین فروشگاه."""
    head, _, tail = (ref or "").partition(":")
    if ref == "store-logo":
        p = _field_path(getattr(store, "logo", None))
        if p:
            return p
        raise AssetError("فروشگاه لوگو ندارد.")
    if not tail.isdigit():
        raise AssetError("منبعِ تصویر معتبر نیست.")
    pk = int(tail)
    p: Path | None = None
    if head == "upload":
        a = MotionAsset.objects.filter(pk=pk, store=store).first()
        p = _safe_media_path(a.path) if a else None
    elif head == "pimg":
        from apps.products.models import ProductImage

        pi = ProductImage.objects.filter(pk=pk, product__store=store).first()
        p = _field_path(pi.image) if pi else None
    elif head == "gimg":
        from apps.content.models import GeneratedImage

        gi = GeneratedImage.objects.filter(pk=pk, store=store).first()
        p = _field_path(gi.image) if gi else None
    elif head == "photo":
        from apps.photoedit.models import PhotoAsset

        a = PhotoAsset.objects.filter(pk=pk, store=store).first()
        p = _safe_media_path(a.original) if a else None
    if p is None:
        raise AssetError(f"تصویرِ «{ref}» پیدا نشد.")
    return p


def load(store, ref: str) -> tuple[bytes, str]:
    """(بایتِ کوچک‌شده, پسوند)."""
    if ref.startswith("data:image/"):
        m = re.match(r"^data:image/(png|jpeg|webp);base64,(.+)$", ref)
        if not m:
            raise AssetError("تصویرِ data: معتبر نیست.")
        data = base64.b64decode(m.group(2), validate=False)
    else:
        data = locate(store, ref).read_bytes()
    out, ext, _w, _h, _a = shrink(data)
    return out, ext


def data_uri(store, ref: str) -> str:
    out, ext = load(store, ref)
    mime = "image/png" if ext == ".png" else "image/jpeg"
    return f"data:{mime};base64,{base64.b64encode(out).decode()}"


def store_defaults(store) -> dict:
    """نامِ فروشگاه، رنگ‌های برند و لوگو برای پیش‌فرضِ ویدیو."""
    colors: list[str] = []
    raw = getattr(store, "colors", None)
    if isinstance(raw, dict):
        vals = list(raw.values())
    elif isinstance(raw, list):
        vals = raw
    else:
        vals = []
    for v in vals:
        if isinstance(v, str) and re.fullmatch(r"#?[0-9a-fA-F]{6}", v.strip()):
            colors.append(v if v.startswith("#") else "#" + v)
    logo = None
    try:
        if _field_path(getattr(store, "logo", None)):
            logo = "store-logo"
    except Exception:  # noqa: BLE001
        logo = None
    return {"name": store.name, "colors": colors[:3], "logo": logo,
            "logo_url": media_url(store.logo.name) if logo else None}
