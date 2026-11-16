"""سنجشِ ثبات برای تصویرِ هوش مصنوعی (نقاشی‌شده، با شیب و سایه) در برابرِ سندِ قفل‌شده.

بررسیِ رنگِ ماسکوت (``apps.mascot.engine.qa``) روی لکه‌های تک‌رنگِ کدکشیده درست است؛ تصویرِ مدلِ تصویرساز تک‌رنگ نیست. این‌جا هر پیکسلِ مات به نزدیک‌ترین رنگِ پالت می‌رود
و تا فاصلهٔ ``LOOSE_TOL`` به آن رنگ حساب می‌شود؛ دو «پرچم» می‌دهد: رنگ‌های امضا کم‌وبیش دیده شوند و سیلوئتِ کلی به شخصیتِ کدکشیده نزدیک بماند.
نتیجه «پرچم» است نه عمل.
"""
from __future__ import annotations

import numpy as np
from PIL import Image

from apps.mascot.engine.qa import check_figure, note_fa, signature_colours  # noqa: F401 — برای هم‌نامیِ واردکردن

LOOSE_TOL = 62
LOOSE_MIN_SHARE = 0.004
LOOSE_MIN_PIXELS = 40
AI_PALETTE_OK = 0.5
SILHOUETTE_MIN = 0.4
ANALYSE_SIDE = 320


def _rgb(hx: str) -> tuple[int, int, int]:
    h = hx.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def colour_shares_loose(layer: Image.Image, palette: list[dict]) -> tuple[list[dict], int, float]:
    im = layer.convert("RGBA")
    box = im.getchannel("A").point(lambda v: 255 if v >= 128 else 0).getbbox()
    alpha_full = np.asarray(im.getchannel("A"))
    figure_share = float((alpha_full >= 128).sum()) / max(1, alpha_full.size)
    if box is not None:
        im = im.crop(box)
    if max(im.size) > ANALYSE_SIDE:
        im.thumbnail((ANALYSE_SIDE, ANALYSE_SIDE), Image.BOX)
    arr = np.asarray(im)
    px = arr[arr[..., 3] >= 200][:, :3].astype(np.int32)
    total = int(px.shape[0])
    if total == 0:
        return [{"role": p.get("role", ""), "hex": p["hex"], "name": p.get("name", ""), "count": 0, "share": 0.0, "found": False} for p in palette], 0, figure_share
    uniq = {}
    for p in palette:
        uniq.setdefault(p["hex"], p)
    keys = list(uniq)
    cols = np.array([_rgb(k) for k in keys], dtype=np.int32)
    d2 = ((px[:, None, :] - cols[None, :, :]) ** 2).sum(axis=2)
    nearest = d2.argmin(axis=1)
    ok = d2[np.arange(total), nearest] <= LOOSE_TOL * LOOSE_TOL
    counts = np.bincount(nearest[ok], minlength=len(keys))
    by_hex = {k: int(counts[i]) for i, k in enumerate(keys)}
    rows = []
    for p in palette:
        n = by_hex.get(p["hex"], 0)
        share = n / total
        rows.append({"role": p.get("role", ""), "hex": p["hex"], "name": p.get("name", ""), "count": n, "share": round(share, 5), "found": n >= LOOSE_MIN_PIXELS and share >= LOOSE_MIN_SHARE})
    return rows, total, figure_share


def _mask(img: Image.Image, side: int = 128) -> np.ndarray:
    a = img.convert("RGBA").getchannel("A").point(lambda v: 255 if v >= 128 else 0)
    box = a.getbbox()
    if box is None:
        return np.zeros((side, side), bool)
    a = a.crop(box).resize((side, side), Image.BILINEAR)
    return np.asarray(a) >= 128


def silhouette_iou(a: Image.Image, b: Image.Image) -> float:
    """هم‌پوشانیِ دو سیلوئت پس از بریدن تا کادرِ خودشان و هم‌اندازه‌کردن (۰..۱)."""
    ma, mb = _mask(a), _mask(b)
    inter = float((ma & mb).sum())
    union = float((ma | mb).sum())
    return round(inter / union, 3) if union else 0.0
