"""«بازکردنِ PSD» (دورِ ۸): فایلِ لایه‌دار ⇒ عکسِ تازه در کتابخانه (بومِ شفاف) + پروژهٔ ویرایشگر با هر لایه به‌صورتِ «لایهٔ نقاشی».

* بوم حداکثر ۲۰۴۸ پیکسل در ضلعِ بلند (بزرگ‌تر کوچک می‌شود)؛ هر لایه روی بومِ کامل (مثلِ لایهٔ نقاشی) با نام، شفافیت، حالتِ ترکیب و پنهان‌بودن.
* بی لایه یا لایه‌ها ناخواندنی ⇒ تصویرِ ترکیبیِ فایل به‌عنوانِ عکس (با یادداشت).
"""
from __future__ import annotations

import io
import uuid

import numpy as np
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

from . import services
from .psd_read import PsdDoc, PsdReadError, read_psd_full

MAX_SIDE = 2048


def _png(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, "PNG", compress_level=4)
    return buf.getvalue()


def import_psd(store, user, raw: bytes, title: str = "") -> dict:
    """⇒ {"asset": PhotoAsset، "project": PhotoProject|None، "layers": n، "notes": [...]}"""
    doc: PsdDoc = read_psd_full(raw)
    W, H = doc.size
    name = (title or "فایلِ PSD")[:150]
    k = min(1.0, MAX_SIDE / max(W, H))
    size = (max(1, int(round(W * k))), max(1, int(round(H * k))))
    notes = list(doc.notes)
    if k < 1:
        notes.append(f"بوم از {W}×{H} به {size[0]}×{size[1]} کوچک شد")

    def upload(img: Image.Image, ttl: str):
        return services.add_upload(store, user, SimpleUploadedFile("psd.png", _png(img), content_type="image/png"), ttl)

    if not doc.layers:
        if doc.merged is None:
            raise PsdReadError("در این فایل نه لایه‌ای بود و نه تصویرِ ترکیبی.")
        merged = Image.fromarray(doc.merged, "RGB")
        if size != merged.size:
            merged = merged.resize(size, Image.Resampling.LANCZOS)
        notes.append("لایه‌ای خوانده نشد؛ فقط تصویرِ ترکیبیِ فایل آمد")
        return {"asset": upload(merged, name), "project": None, "layers": 0, "notes": notes}

    asset = upload(Image.new("RGBA", size, (0, 0, 0, 0)), f"{name} (بومِ PSD)")
    base = {"id": "base", "type": "base", "name": "عکس", "visible": True, "locked": False, "opacity": 1, "blend": "normal", "mask": None}
    items, pngs = [], []
    for i, L in enumerate(doc.layers):
        canvas = Image.new("RGBA", size, (0, 0, 0, 0))
        im = Image.fromarray(L.rgba, "RGBA")
        if k < 1:
            nw, nh = max(1, int(round(im.width * k))), max(1, int(round(im.height * k)))
            im = im.resize((nw, nh), Image.Resampling.LANCZOS)
        _paste_clipped(canvas, im, int(round(L.x * k)), int(round(L.y * k)))
        pid = uuid.uuid4().hex[:8]
        pngs.append((pid, _png(canvas)))
        items.append({"id": f"l{i + 1}", "type": "image", "name": L.name, "visible": L.visible, "locked": False, "opacity": L.opacity, "blend": L.blend, "mask": None,
                      "src": {"kind": "paint", "id": pid, "rev": 0}, "cx": 0.5, "cy": 0.5, "w": 1.0, "rot": 0, "flip_h": False, "flip_v": False})
    project = services.create_project(store, asset, name, {"fv": 2, "layers": [base] + items})
    for pid, data in pngs:
        services.save_paint(project, pid, data)
    return {"asset": asset, "project": project, "layers": len(items), "notes": notes}


def _paste_clipped(canvas: Image.Image, im: Image.Image, x: int, y: int) -> None:
    """لایه‌ای که (کامل یا بخشی) بیرونِ بوم است: فقط بخشِ داخل چسبانده می‌شود."""
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(canvas.width, x + im.width), min(canvas.height, y + im.height)
    if x1 <= x0 or y1 <= y0:
        return
    canvas.alpha_composite(im.crop((x0 - x, y0 - y, x1 - x, y1 - y)), (x0, y0))


def merged_array(img: Image.Image) -> np.ndarray:
    return np.asarray(img.convert("RGB"))
