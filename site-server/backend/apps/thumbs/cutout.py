"""بُرشِ سوژه (حذفِ پس‌زمینه) برای تامنیل — از همان ابزارهای ادیتورِ عکس، بدونِ مدلِ تازه.

* عکسی که از قبل پس‌زمینهٔ شفاف دارد ⇒ همان.
* وگرنه «RVM» روی خودِ سرورِ سایت (سریع، برای آدم عالی، با «دروازهٔ کیفیت»: اگر برش مشکوک بود، رد می‌شود و عکس بدونِ برش می‌آید).
* دقیق‌تر (مو، کالا، لباس): مدل‌های ``photo.matting`` روی سرورِ پردازش (u2netp / IS-Net / BiRefNet-lite) با صفِ ماندگار.

نتیجهٔ RVM برای هر عکس یک بار کَش می‌شود (``MEDIA_ROOT/thumbs/s<فروشگاه>/cut/a<عکس>.png``).
"""
from __future__ import annotations

import logging
import threading
from pathlib import Path

import numpy as np
from PIL import Image

from apps.photoedit import matting, ops
from apps.photoedit import matting_nodes as mn
from apps.photoedit import services as photo
from apps.photoedit.models import PhotoAsset

from . import primitives as P

logger = logging.getLogger(__name__)

MAX_SIDE = 1600
_lock = threading.Lock()


def cache_path(store, asset: PhotoAsset) -> Path:
    return photo.abs_path(f"thumbs/s{store.pk}/cut/a{asset.pk}.png")


def load_asset(asset: PhotoAsset) -> Image.Image | None:
    p = photo.abs_path(asset.original)
    if not p.is_file():
        return None
    try:
        img = ops.load(p)
    except Exception:  # noqa: BLE001 — فایلِ خراب
        logger.warning("thumbs.cutout: cannot load asset %s", asset.pk)
        return None
    if max(img.size) > MAX_SIDE * 2:
        img.thumbnail((MAX_SIDE * 2, MAX_SIDE * 2), Image.Resampling.LANCZOS)
    return img


def ensure(store, asset: PhotoAsset, *, allow_site: bool = True) -> tuple[Image.Image | None, bool, str]:
    """⇒ (تصویر، بریده‌است؟، یادداشتِ فارسی). برش را (در صورتِ نیاز) روی سایت انجام و کَش می‌کند."""
    img = load_asset(asset)
    if img is None:
        return None, False, "فایلِ عکس پیدا نشد."
    if P.has_cutout(img):
        return img, True, ""
    cp = cache_path(store, asset)
    if cp.is_file():
        try:
            return Image.open(cp).convert("RGBA"), True, ""
        except Exception:  # noqa: BLE001
            cp.unlink(missing_ok=True)
    if not allow_site or not matting.available():
        return img, False, ("مدلِ برشِ سبک روی سایت آماده نیست؛ عکس بدونِ برش آمد." if allow_site else "")
    rgb = img.convert("RGB")
    if max(rgb.size) > MAX_SIDE:
        rgb.thumbnail((MAX_SIDE, MAX_SIDE), Image.Resampling.LANCZOS)
    with _lock:                                          # روی ۲ هستهٔ سرور هم‌زمان یک برش
        a = matting.alpha(rgb)
    ok, _cov, why = matting.quality(a) if a is not None else (False, 0.0, "مدلِ جداسازی در دسترس نبود")
    if not ok:
        return img, False, f"برشِ خودکار مطمئن نبود ({why}). «حذفِ پس‌زمینه» با سرورِ پردازش دقیق‌تر است؛ فعلاً عکس بدونِ برش آمد."
    rgba = np.dstack([np.asarray(rgb), np.clip(a * 255.0 + 0.5, 0, 255).astype(np.uint8)])
    out = Image.fromarray(rgba, "RGBA")
    try:
        cp.parent.mkdir(parents=True, exist_ok=True)
        out.save(cp, "PNG")
    except OSError:
        logger.warning("thumbs.cutout: cannot cache cutout for %s", asset.pk)
    return out, True, ""


def run_site(store, user, asset: PhotoAsset) -> dict:
    """دکمهٔ «حذفِ پس‌زمینه»: برشِ RVM ⇒ عکسِ تازه (شفاف) در کتابخانه. ⇒ {state, asset?, message}."""
    img = load_asset(asset)
    if img is None:
        return {"state": "failed", "message": "فایلِ عکس پیدا نشد."}
    if P.has_cutout(img):
        return {"state": "ready", "asset": photo.asset_dict(asset), "message": "این عکس از قبل پس‌زمینهٔ شفاف دارد."}
    ref = f"thumbcut:{asset.pk}"
    done = PhotoAsset.objects.filter(store=store, source_ref=ref).first()
    if done is not None and photo.abs_path(done.original).is_file():
        return {"state": "ready", "asset": photo.asset_dict(done), "message": "پس‌زمینه برداشته شد."}
    cut, is_cut, note = ensure(store, asset)
    if not is_cut or cut is None:
        return {"state": "failed", "message": note or "برش انجام نشد.", "node_possible": True}
    import io

    buf = io.BytesIO()
    cut.save(buf, "PNG")
    new = photo._asset_from_bytes(store, user, buf.getvalue(), title=f"{asset.title or 'عکس'} — بدونِ پس‌زمینه", source_ref=ref, product=asset.product)
    return {"state": "ready", "asset": photo.asset_dict(new), "message": "پس‌زمینه برداشته شد."}


def node_models(store) -> dict:
    st = mn.status(store)
    return {"models": [m for m in st["models"] if m["where"] == "node"], "node_online": st["node_online"], "node_known": st["node_known"]}
