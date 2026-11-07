"""ابزارهای رنگِ تازه (دورِ ۸): LUT (فایلِ .cube)، «تطبیقِ رنگ با یک عکسِ دیگر»، «انتخابِ آسمان» و «ناحیهٔ تمرکز».

همه با numpy/OpenCV روی سرورِ سایت. روش‌ها «سبک»‌اند و در متنِ رابط هم همین گفته می‌شود:
* LUT: درون‌یابیِ سه‌خطیِ جدولِ ۳بعدی (یا جدولِ ۱بعدی) — همان رفتارِ فایل‌های LUT در نرم‌افزارهای فیلم و عکس.
* تطبیقِ رنگ: انتقالِ میانگین و پراکندگیِ هر کانالِ Lab از عکسِ مرجع (روشِ Reinhard).
* آسمان: آبیِ آسمان + ناحیهٔ روشن و کم‌جزئیاتِ متصل به لبهٔ بالا؛ برای آسمانِ آبی/ابری/غروبِ روشن خوب است، برای آسمانِ شلوغ یا شب نه.
* ناحیهٔ تمرکز: نقشهٔ تیزیِ عکس (واریانسِ لاپلاسین)؛ جاهای تیز = ناحیهٔ تمرکز.
"""
from __future__ import annotations

import io

import cv2
import numpy as np
from PIL import Image

CUBE_MAX_BYTES = 6 * 1024 * 1024
CUBE_MAX_SIZE = 65
LUT_SIDE = 4096


class ColorToolError(Exception):
    """خطایی که متنش برای کاربر است."""


# ───────────────────────────── LUT (.cube)

def parse_cube(data: bytes) -> dict:
    """⇒ {"kind": "3d"|"1d", "size": N, "table": float32 (N,N,N,3) با محورهای [b][g][r] یا (N,3)، "dmin", "dmax"}."""
    if len(data) > CUBE_MAX_BYTES:
        raise ColorToolError("فایلِ LUT بزرگ‌تر از ۶ مگابایت است.")
    try:
        text = data.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        text = data.decode("latin-1")
    size3 = size1 = 0
    dmin, dmax = np.zeros(3, np.float32), np.ones(3, np.float32)
    rows: list[list[float]] = []
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        head = line.split(None, 1)[0].upper()
        if head == "LUT_3D_SIZE":
            size3 = int(line.split()[1])
        elif head == "LUT_1D_SIZE":
            size1 = int(line.split()[1])
        elif head == "DOMAIN_MIN":
            dmin = np.array([float(v) for v in line.split()[1:4]], np.float32)
        elif head == "DOMAIN_MAX":
            dmax = np.array([float(v) for v in line.split()[1:4]], np.float32)
        elif head in ("TITLE", "LUT_3D_INPUT_RANGE", "LUT_1D_INPUT_RANGE"):
            continue
        else:
            parts = line.split()
            if len(parts) == 3:
                try:
                    rows.append([float(p) for p in parts])
                except ValueError as exc:
                    raise ColorToolError("ردیفِ نامعتبر در فایلِ LUT.") from exc
    if not size3 and not size1:
        raise ColorToolError("این فایل LUT نیست (LUT_3D_SIZE یا LUT_1D_SIZE پیدا نشد؛ فقط فرمتِ .cube).")
    if size3:
        if not (2 <= size3 <= CUBE_MAX_SIZE):
            raise ColorToolError(f"اندازهٔ LUT باید بینِ ۲ و {CUBE_MAX_SIZE} باشد.")
        if len(rows) != size3 ** 3:
            raise ColorToolError("تعدادِ ردیف‌های LUT با اندازه‌اش نمی‌خواند.")
        table = np.asarray(rows, np.float32).reshape(size3, size3, size3, 3)   # ترتیبِ فایل: قرمز سریع‌ترین ⇒ محورها [b][g][r]
        return {"kind": "3d", "size": size3, "table": table, "dmin": dmin, "dmax": dmax}
    if not (2 <= size1 <= 65536) or len(rows) != size1:
        raise ColorToolError("جدولِ ۱بعدیِ LUT درست نیست.")
    return {"kind": "1d", "size": size1, "table": np.asarray(rows, np.float32), "dmin": dmin, "dmax": dmax}


def apply_lut(img: Image.Image, lut: dict, strength: float = 1.0) -> Image.Image:
    """LUT روی تصویر (RGB؛ آلفا دست‌نخورده)؛ strength ۰..۱ = آمیزش با اصل."""
    strength = max(0.0, min(1.0, float(strength)))
    alpha = img.getchannel("A") if img.mode == "RGBA" else None
    rgb = np.asarray(img.convert("RGB"))
    h, w, _ = rgb.shape
    out = np.empty_like(rgb)
    table, N = lut["table"], lut["size"]
    dmin, dmax = lut["dmin"], lut["dmax"]
    span = np.maximum(dmax - dmin, 1e-6)
    step = max(1, 1_500_000 // max(1, w))
    for y0 in range(0, h, step):
        px = rgb[y0:y0 + step].astype(np.float32) / 255.0
        px = np.clip((px - dmin) / span, 0.0, 1.0) * (N - 1)
        if lut["kind"] == "1d":
            res = np.empty_like(px)
            xs = np.arange(N, dtype=np.float32)
            for c in range(3):
                res[..., c] = np.interp(px[..., c], xs, table[:, c])
        else:
            r, g, b = px[..., 0], px[..., 1], px[..., 2]
            r0, g0, b0 = np.floor(r).astype(np.int32), np.floor(g).astype(np.int32), np.floor(b).astype(np.int32)
            r1, g1, b1 = np.minimum(r0 + 1, N - 1), np.minimum(g0 + 1, N - 1), np.minimum(b0 + 1, N - 1)
            fr, fg, fb = (r - r0)[..., None], (g - g0)[..., None], (b - b0)[..., None]
            c00 = table[b0, g0, r0] * (1 - fr) + table[b0, g0, r1] * fr
            c01 = table[b0, g1, r0] * (1 - fr) + table[b0, g1, r1] * fr
            c10 = table[b1, g0, r0] * (1 - fr) + table[b1, g0, r1] * fr
            c11 = table[b1, g1, r0] * (1 - fr) + table[b1, g1, r1] * fr
            c0 = c00 * (1 - fg) + c01 * fg
            c1 = c10 * (1 - fg) + c11 * fg
            res = c0 * (1 - fb) + c1 * fb
        mixed = res * strength + (rgb[y0:y0 + step].astype(np.float32) / 255.0) * (1 - strength)
        out[y0:y0 + step] = np.clip(mixed * 255.0 + 0.5, 0, 255).astype(np.uint8)
    res_img = Image.fromarray(out, "RGB")
    if alpha is not None:
        res_img = res_img.convert("RGBA")
        res_img.putalpha(alpha)
    return res_img


# ───────────────────────────── تطبیقِ رنگ (Reinhard)

def match_color(src: Image.Image, ref: Image.Image, strength: float = 1.0, keep_luma: float = 0.0) -> Image.Image:
    """میانگین و پراکندگیِ هر کانالِ Lab ِ ref را به src می‌دهد. keep_luma ۰..۱ = چقدر روشنایی (L) ِ اصل بماند."""
    strength = max(0.0, min(1.0, float(strength)))
    if strength <= 0.0:
        return src.copy()
    alpha = src.getchannel("A") if src.mode == "RGBA" else None
    s = cv2.cvtColor(np.asarray(src.convert("RGB")), cv2.COLOR_RGB2LAB).astype(np.float32)
    r_small = ref.convert("RGB")
    r_small.thumbnail((800, 800), Image.Resampling.LANCZOS)
    r = cv2.cvtColor(np.asarray(r_small), cv2.COLOR_RGB2LAB).astype(np.float32)
    out = s.copy()
    for c in range(3):
        sm, ss = float(s[..., c].mean()), float(s[..., c].std()) or 1.0
        rm, rs = float(r[..., c].mean()), float(r[..., c].std()) or 1.0
        t = (s[..., c] - sm) * (rs / ss) + rm
        k = strength * (1.0 - (keep_luma if c == 0 else 0.0))
        out[..., c] = s[..., c] * (1 - k) + t * k
    out[..., 0] = np.clip(out[..., 0], 0, 255)
    out[..., 1:] = np.clip(out[..., 1:], 0, 255)
    rgb = cv2.cvtColor(out.astype(np.uint8), cv2.COLOR_LAB2RGB)
    res = Image.fromarray(rgb, "RGB")
    if alpha is not None:
        res = res.convert("RGBA")
        res.putalpha(alpha)
    return res


# ───────────────────────────── انتخابِ آسمان و ناحیهٔ تمرکز (ماسک‌های L)

def _mask_png(mask01: np.ndarray) -> bytes:
    buf = io.BytesIO()
    Image.fromarray(np.clip(mask01 * 255.0 + 0.5, 0, 255).astype(np.uint8), "L").save(buf, "PNG")
    return buf.getvalue()


def sky_mask(img: Image.Image) -> np.ndarray:
    """⇒ ماسکِ float 0..1 هم‌اندازهٔ تصویر (≤ ۶۴۰ پیکسل)؛ بدونِ آسمان ⇒ ColorToolError."""
    im = img.convert("RGB")
    im.thumbnail((640, 640), Image.Resampling.LANCZOS)
    a = np.asarray(im)
    h, w, _ = a.shape
    hsv = cv2.cvtColor(a, cv2.COLOR_RGB2HSV)
    hh, ss, vv = hsv[..., 0].astype(np.float32), hsv[..., 1].astype(np.float32), hsv[..., 2].astype(np.float32)
    blue = (hh >= 90) & (hh <= 135) & (ss >= 35) & (vv >= 70)
    gray = cv2.GaussianBlur(cv2.cvtColor(a, cv2.COLOR_RGB2GRAY), (0, 0), 1.2).astype(np.float32)
    gx, gy = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3), cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    grad = cv2.GaussianBlur(np.hypot(gx, gy), (0, 0), 2.0)
    g0 = cv2.cvtColor(a, cv2.COLOR_RGB2GRAY).astype(np.float32)
    mean = cv2.blur(g0, (9, 9))
    std = np.sqrt(np.maximum(cv2.blur(g0 * g0, (9, 9)) - mean * mean, 0.0))      # پراکندگیِ موضعی: آسمان صاف است، برگ و نویز و پارچه نه
    smooth = (grad < 14.0) & (std < 12.0)
    bright = (vv >= 150) & (ss <= 70)                       # ابرِ سفید/خاکستریِ روشن
    # آبی فقط وقتی «آسمان» است که صاف باشد؛ وگرنه آبیِ لباس/آب/نویز را هم می‌گرفت
    cand = ((blue & (grad < 30.0) & (std < 16.0)) | (bright & smooth)).astype(np.uint8)
    cand = cv2.morphologyEx(cand, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8))
    cand = cv2.morphologyEx(cand, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    n, lab, stats, _ = cv2.connectedComponentsWithStats(cand, connectivity=8)
    keep = np.zeros((h, w), np.uint8)
    top = max(2, int(h * 0.18))
    for i in range(1, n):
        x, y, cw, ch, area = stats[i]
        if area < 0.01 * h * w:
            continue
        if y <= top or (lab[:top] == i).any():
            keep[lab == i] = 1
    if keep.mean() < 0.02:
        raise ColorToolError("آسمانی پیدا نشد؛ این روش برای آسمانِ آبی، ابری یا غروبِ روشنِ بالای عکس است.")
    soft = cv2.GaussianBlur(keep.astype(np.float32), (0, 0), 2.2)
    return np.clip(soft * 1.15 - 0.075, 0.0, 1.0)


def focus_mask(img: Image.Image) -> np.ndarray:
    """نقشهٔ تیزی ⇒ ناحیهٔ تمرکز (0..1)؛ عکسِ یکدست/کاملاً تار ⇒ ColorToolError."""
    im = img.convert("RGB")
    im.thumbnail((640, 640), Image.Resampling.LANCZOS)
    g = cv2.cvtColor(np.asarray(im), cv2.COLOR_RGB2GRAY).astype(np.float32)
    lap = cv2.Laplacian(cv2.GaussianBlur(g, (0, 0), 0.8), cv2.CV_32F, ksize=3)
    energy = cv2.GaussianBlur(lap * lap, (0, 0), max(4.0, min(g.shape) / 40.0))
    hi = float(np.percentile(energy, 98))
    lo = float(np.percentile(energy, 40))
    if hi <= 1e-3 or hi < lo * 1.8:
        raise ColorToolError("ناحیهٔ تیزِ مشخصی پیدا نشد (عکس یکدست است یا همه‌جایش به یک اندازه تیز/تار است).")
    m = np.clip((energy - lo) / (hi - lo), 0.0, 1.0)
    m = (m > 0.35).astype(np.uint8)
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    n, lab, stats, _ = cv2.connectedComponentsWithStats(m, connectivity=8)
    keep = np.zeros_like(m)
    area_all = m.shape[0] * m.shape[1]
    for i in range(1, n):
        if stats[i][4] >= 0.01 * area_all:
            keep[lab == i] = 1
    if keep.mean() < 0.01:
        raise ColorToolError("ناحیهٔ تیزِ مشخصی پیدا نشد.")
    if keep.mean() > 0.97:
        raise ColorToolError("تقریباً همهٔ عکس تیز است؛ ناحیهٔ تمرکزِ جداگانه‌ای وجود ندارد.")
    return cv2.GaussianBlur(keep.astype(np.float32), (0, 0), 3.0)


def mask_bytes(kind: str, img: Image.Image) -> bytes:
    fn = {"sky": sky_mask, "focus": focus_mask}.get(kind)
    if fn is None:
        raise ColorToolError("نوعِ انتخاب باید «sky» یا «focus» باشد.")
    return _mask_png(fn(img))
