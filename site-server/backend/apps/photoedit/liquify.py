"""مایع‌سازی (Liquify): نقشهٔ جابه‌جاییِ ``liquify.bin`` ⇒ عکسِ پایه.

فایلِ نقشه (در پوشهٔ پروژه)::

    "LQF1" | uint16 gw | uint16 gh | gw·gh·2 عددِ int16 (dx، dy پیاپی؛ ردیف‌به‌ردیف، ردیفِ بالا اول) — همه little-endian

مقدارِ v ⇒ آفستِ ``v / 32767 · 0.25`` در مختصاتِ **نرمال‌شدهٔ عکس** (dx کسری از پهنا، dy کسری از ارتفاع). معنا::

    out(u, v) = src(u + dx(u, v), v + dy(u, v))

* شبکه با قرارداد «مرکزِ سلول» روی عکس کشیده می‌شود (مثلِ بافتِ WebGL با LINEAR و clamp): گرهٔ (i, j) در
  ((i+0.5)/gw، (j+0.5)/gh) است و نمونه‌برداریِ دوخطی با تکرارِ لبه (cv2.resize ِ INTER_LINEAR همین را می‌کند).
* پیکسلِ خروجی (x, y) از مختصاتِ پیکسلیِ ``(x + dx·W, y + dy·H)`` ِ منبع می‌خواند (مرکزِ پیکسل = عددِ درست در cv2)، با تکرارِ لبه
  (BORDER_REPLICATE) بیرونِ عکس. ``quality="fast"`` ⇒ INTER_LINEAR (پیش‌نمایش)، ``"final"`` ⇒ INTER_CUBIC (خروجی).
* نقشهٔ صفر ⇒ همان عکس (بی‌هیچ بازنمونه‌برداری). RGBA ⇒ رنگ پیش‌ضرب‌شده، نمونه‌برداری، دوباره مستقیم.
* فقط روی عکسِ پایه، بعد از develop و **پیش از** مرحلهٔ قاب (در فضای عکس).

قلم‌های ساده (``brush_*``) برای آزمون و بازپخشِ سمتِ سرور اند؛ مرورگر قلم‌های خودش را دارد.
"""
from __future__ import annotations

import struct
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

MAGIC = b"LQF1"
MAX_BYTES = 2 * 1024 * 1024
MAX_OFFSET = 0.25
MAX_GRID = 1024
STRIP_PIXELS = 1_500_000


class LiquifyError(ValueError):
    """نقشهٔ مایع‌سازیِ نامعتبر — متنش برای کاربر است."""


def _check_header(head: bytes, size: int) -> tuple[int, int]:
    if size > MAX_BYTES:
        raise LiquifyError("نقشهٔ مایع‌سازی بزرگ‌تر از ۲ مگابایت است.")
    if size < 8 or head[:4] != MAGIC:
        raise LiquifyError("فایلِ مایع‌سازی نامعتبر است (نشانهٔ LQF1 نیست).")
    gw, gh = struct.unpack("<HH", head[4:8])
    if not (2 <= gw <= MAX_GRID and 2 <= gh <= MAX_GRID):
        raise LiquifyError("اندازهٔ شبکهٔ مایع‌سازی نامعتبر است.")
    if size != 8 + gw * gh * 4:
        raise LiquifyError("اندازهٔ فایلِ مایع‌سازی با شبکه نمی‌خواند.")
    return gw, gh


def parse_header(raw: bytes) -> tuple[int, int]:
    """بایت‌های فایل ⇒ (gw, gh)؛ هدر و اندازه را کامل وارسی می‌کند."""
    return _check_header(bytes(raw[:8]), len(raw))


def peek(path) -> tuple[int, int]:
    """(gw, gh) از روی هدرِ فایل بی‌خواندنِ کلِ آن؛ فایل نامعتبر ⇒ LiquifyError."""
    p = Path(path)
    size = p.stat().st_size
    with p.open("rb") as fh:
        return _check_header(fh.read(8), size)


def decode(raw: bytes) -> np.ndarray:
    """بایت‌ها ⇒ آفست‌های نرمال float32 با شکلِ (gh, gw, 2) (dx، dy)."""
    gw, gh = parse_header(raw)
    v = np.frombuffer(raw, dtype="<i2", offset=8, count=gw * gh * 2).reshape(gh, gw, 2)
    return v.astype(np.float32) * np.float32(MAX_OFFSET / 32767.0)


def encode(field: np.ndarray) -> bytes:
    """آفست‌های نرمال (gh, gw, 2) ⇒ بایت‌های فایل (کلمپ به ±۰٫۲۵ و گرد به نزدیک‌ترین int16)."""
    f = np.asarray(field, np.float32)
    if f.ndim != 3 or f.shape[2] != 2:
        raise LiquifyError("شکلِ نقشه باید (gh, gw, 2) باشد.")
    gh, gw = f.shape[:2]
    if not (2 <= gw <= MAX_GRID and 2 <= gh <= MAX_GRID):
        raise LiquifyError("اندازهٔ شبکهٔ مایع‌سازی نامعتبر است.")
    v = np.clip(np.rint(f / np.float32(MAX_OFFSET) * 32767.0), -32767, 32767).astype("<i2")
    return MAGIC + struct.pack("<HH", gw, gh) + v.tobytes()


def load_field(path) -> np.ndarray:
    return decode(Path(path).read_bytes())


def save_field(path, field: np.ndarray) -> None:
    data = encode(field)
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".part")
    tmp.write_bytes(data)
    tmp.replace(p)


def zeros(gw: int, gh: int) -> np.ndarray:
    return np.zeros((gh, gw, 2), np.float32)


def is_identity(field: np.ndarray) -> bool:
    return not np.any(field)


def _axis_weights(n_out: int, n_in: int):
    """وزن‌های دوخطیِ بزرگ‌کردنِ یک محور (قرارداد مرکزِ سلول، تکرارِ لبه) — همان cv2.resize."""
    src = (np.arange(n_out, dtype=np.float64) + 0.5) * (n_in / n_out) - 0.5
    i0 = np.floor(src).astype(np.int64)
    t = (src - i0).astype(np.float32)
    return np.clip(i0, 0, n_in - 1), np.clip(i0 + 1, 0, n_in - 1), t


def upsample_rows(field: np.ndarray, W: int, H: int, y0: int, y1: int) -> np.ndarray:
    """ردیف‌های [y0, y1) از نقشهٔ بزرگ‌شده به W × H ⇒ float32 (y1−y0, W, 2) (آفستِ نرمال)."""
    gh, gw = field.shape[:2]
    xi0, xi1, xt = _axis_weights(W, gw)
    yi0, yi1, yt = _axis_weights(H, gh)
    yi0, yi1, yt = yi0[y0:y1], yi1[y0:y1], yt[y0:y1]
    need = np.unique(np.concatenate([yi0, yi1]))
    sub = field[need]
    cols = sub[:, xi0, :] * (1.0 - xt)[None, :, None] + sub[:, xi1, :] * xt[None, :, None]
    a, b = np.searchsorted(need, yi0), np.searchsorted(need, yi1)
    return cols[a] * (1.0 - yt)[:, None, None] + cols[b] * yt[:, None, None]


def upsample(field: np.ndarray, W: int, H: int) -> np.ndarray:
    return upsample_rows(field, W, H, 0, H)


def apply(img, field: np.ndarray, quality: str = "fast"):
    """عکس (PIL یا آرایهٔ uint8 ِ h×w×3|4) + نقشه ⇒ همان نوع. بدونِ جابه‌جایی ⇒ همان ورودی."""
    is_pil = isinstance(img, Image.Image)
    if is_pil:
        mode = img.mode if img.mode in ("RGB", "RGBA") else ("RGBA" if "A" in img.mode else "RGB")
        arr = np.asarray(img if img.mode == mode else img.convert(mode))
    else:
        arr = np.asarray(img)
        mode = "RGBA" if arr.shape[2] == 4 else "RGB"
    if field is None or is_identity(field):
        return img
    h, w = arr.shape[:2]
    interp = cv2.INTER_CUBIC if quality == "final" else cv2.INTER_LINEAR
    src = np.ascontiguousarray(arr)
    premult = False
    if mode == "RGBA" and int(src[..., 3].min()) < 255:
        a = src[..., 3:4].astype(np.float32) / 255.0
        src = np.concatenate([np.rint(src[..., :3] * a).astype(np.uint8), src[..., 3:4]], axis=2)
        premult = True
    out = np.empty_like(src)
    xs = np.arange(w, dtype=np.float32)[None, :]
    step = max(1, STRIP_PIXELS // max(1, w))
    for y0 in range(0, h, step):
        y1 = min(h, y0 + step)
        f = upsample_rows(field, w, h, y0, y1)
        mapx = xs + f[..., 0] * np.float32(w)
        mapy = np.arange(y0, y1, dtype=np.float32)[:, None] + f[..., 1] * np.float32(h)
        out[y0:y1] = cv2.remap(src, mapx.astype(np.float32), mapy.astype(np.float32), interp,
                               borderMode=cv2.BORDER_REPLICATE)
    if premult:
        al = out[..., 3:4].astype(np.float32)
        rgb = np.where(al > 0, out[..., :3].astype(np.float32) * 255.0 / np.maximum(al, 1.0), 0.0)
        out[..., :3] = np.clip(np.rint(rgb), 0, 255).astype(np.uint8)
    return Image.fromarray(out, mode) if is_pil else out


# ───────────────────────────── قلم‌های ساده روی میدانِ float (آزمون / بازپخشِ سرور)

def _falloff(d: np.ndarray, radius: float) -> np.ndarray:
    t = np.clip(d / max(1e-9, radius), 0.0, 1.0)
    return 1.0 - t * t * (3.0 - 2.0 * t)


def _grid_xy(field: np.ndarray):
    gh, gw = field.shape[:2]
    xs = (np.arange(gw, dtype=np.float32) + 0.5) / gw
    ys = (np.arange(gh, dtype=np.float32) + 0.5) / gh
    return xs[None, :], ys[:, None]


def brush_forward(field: np.ndarray, cx: float, cy: float, radius: float, dx: float, dy: float, strength: float = 1.0) -> None:
    """کشیدن: محتوای زیرِ قلم به اندازهٔ (dx, dy) نرمال حرکت می‌کند ⇒ آفست −(dx, dy)·falloff (درجا)."""
    xs, ys = _grid_xy(field)
    f = _falloff(np.hypot(xs - cx, ys - cy), radius) * strength
    field[..., 0] -= dx * f
    field[..., 1] -= dy * f


def brush_bloat(field: np.ndarray, cx: float, cy: float, radius: float, strength: float = 0.1) -> None:
    """باد کردن: خروجی از نقطه‌ای نزدیک‌تر به مرکز می‌خواند ⇒ آفست (c − p)·strength·falloff."""
    xs, ys = _grid_xy(field)
    f = _falloff(np.hypot(xs - cx, ys - cy), radius) * strength
    field[..., 0] += (cx - xs) * f
    field[..., 1] += (cy - ys) * f


def brush_pucker(field: np.ndarray, cx: float, cy: float, radius: float, strength: float = 0.1) -> None:
    """جمع کردن: وارونهٔ bloat."""
    brush_bloat(field, cx, cy, radius, -strength)


def brush_reconstruct(field: np.ndarray, cx: float, cy: float, radius: float, strength: float = 1.0) -> None:
    """بازسازی: آفست به سمتِ صفر می‌رود ⇒ field ·= 1 − strength·falloff."""
    xs, ys = _grid_xy(field)
    f = _falloff(np.hypot(xs - cx, ys - cy), radius) * strength
    field *= (1.0 - np.clip(f, 0.0, 1.0))[..., None]
