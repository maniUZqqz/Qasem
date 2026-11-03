"""افکتِ لایه (سایه، درخشش، خطِ دور) ⇒ داخلِ خودِ تایلِ لایه «پخته» می‌شود، پیش از حالتِ ترکیب، پیدایی و ماسک.

``bake(tile, pivot, fx, W)`` ورودی: تایلِ RGBA ِ لایه **در مقیاسِ پیکسلِ بوم** (برای لایهٔ تصویر: عکس به اندازهٔ بومیِ لایه
تغییر اندازه داده می‌شود تا طول‌های افکت پیکسلِ بوم باشند)، نقطهٔ محور و ``fx``. خروجی: تایلِ تازه با حاشیه + محورِ جابه‌جاشده.

قرارداد (مرورگر باید همین را بسازد)::

    fx = {"shadow": null | {"color", "opacity", "blur", "dx", "dy"},
          "stroke": null | {"color", "w", "opacity"},
          "glow":   null | {"color", "opacity", "blur", "size"}}

* همهٔ طول‌ها کسری از **پهنای بوم W** اند؛ پیکسل = طول × W.
* ترتیبِ رسم از پایین به بالا: سایه، درخشش، خطِ دور، پیکسل‌های لایه (هر کدام با «over» ِ معمولیِ آلفا).
* ``A`` = کانالِ آلفای تایلِ لایه (۰..۱؛ شاملِ پیدایی و ماسکِ لایه **نیست** — آن‌ها بعدتر می‌آیند).
* سایه: آلفای ``A`` به اندازهٔ (dx·W، dy·W) جابه‌جا (دوخطی، کسری مجاز؛ dx مثبت = راست، dy مثبت = پایین؛ **در قابِ خودِ لایه**، پس
  با چرخشِ لایه می‌چرخد و با قرینهٔ لایه قرینه نمی‌شود) ⇒ محوِ گاوسی با σ = blur·W px ⇒ × opacity، رنگِ ثابت.
* درخشش: ``dilate(A, size·W)`` ⇒ محوِ گاوسی با σ = blur·W ⇒ × opacity، رنگِ ثابت.
* خطِ دورِ بیرونی: ``dilate(A, w·W)`` ⇒ × opacity، رنگِ ثابت (زیرِ پیکسل‌های لایه رسم می‌شود).
* dilate = بیشینه روی «دیسک» (cv2 ِ MORPH_ELLIPSE با قطرِ ۲r+1 که r = ⌊طول به px + ۰٫۵⌋؛ r = ۰ ⇒ بی‌اثر). نیم‌پهنای ردیفِ dy در این هسته
  ``round(√(r²−dy²))`` است (کمی چهارگوش‌تر از دیسکِ ریاضی). r > ۱۲ ⇒ ⌈r/۱۲⌉ گامِ متوازن پشتِ هم (جمعِ مینکوفسکیِ هسته‌ها).
* حاشیهٔ تایل = ceil(max(|dx|,|dy|)·W + ۴σ + ۲) برای سایه، (size·W + ۴σ + ۲) درخشش، (w·W + ۲) خطِ دور؛ بیشینهٔ این‌ها.
* همهٔ نقشه‌های افکت بعد از ضربِ opacity به uint8 گرد می‌شوند؛ ترکیب با float32 و خروجی uint8 (آلفای مستقیم).
"""
from __future__ import annotations

import math

import cv2
import numpy as np
from PIL import Image

STEP = 12                   # بیشینهٔ شعاعِ هر گامِ dilate
STRIP_PIXELS = 2_000_000


def _rgb(hex_color: str) -> np.ndarray:
    return np.array([int(hex_color[i:i + 2], 16) for i in (1, 3, 5)], np.float32) / 255.0


def effective(fx) -> dict:
    """فقط افکت‌هایی که واقعاً چیزی می‌کشند (opacity > 0؛ برای خطِ دور w > 0 هم)."""
    if not isinstance(fx, dict):
        return {}
    out = {}
    if fx.get("shadow") and fx["shadow"]["opacity"] > 0:
        out["shadow"] = fx["shadow"]
    if fx.get("glow") and fx["glow"]["opacity"] > 0:
        out["glow"] = fx["glow"]
    if fx.get("stroke") and fx["stroke"]["opacity"] > 0 and fx["stroke"]["w"] > 0:
        out["stroke"] = fx["stroke"]
    return out


def active(fx) -> bool:
    return bool(effective(fx))


def margin(fx: dict, W: float) -> int:
    """حاشیهٔ پیکسلی که تایل باید از هر چهار طرف بگیرد."""
    m = 0.0
    e = effective(fx)
    sh, st, gl = e.get("shadow"), e.get("stroke"), e.get("glow")
    if sh:
        m = max(m, max(abs(sh["dx"]), abs(sh["dy"])) * W + 4 * sh["blur"] * W + 2)
    if gl:
        m = max(m, gl["size"] * W + 4 * gl["blur"] * W + 2)
    if st:
        m = max(m, st["w"] * W + 2)
    return int(math.ceil(m))


def dilate_disc(a: np.ndarray, r_px: float) -> np.ndarray:
    """بیشینه روی دیسکِ شعاعِ r_px (uint8 ۲بعدی)؛ r_px < ۰٫۵ ⇒ همان آرایه. r > ۱۲ ⇒ چند گامِ متوازنِ ≤ ۱۲ (دقتِ دیسک ≥ ۹۸٪)."""
    r = int(math.floor(r_px + 0.5))
    out = a
    n = max(1, int(math.ceil(r / STEP))) if r > 0 else 0
    left = r
    for i in range(n):
        s = int(round(left / (n - i)))
        left -= s
        if s <= 0:
            continue
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * s + 1, 2 * s + 1))
        out = cv2.dilate(out, k)
    return out


def _u8(f: np.ndarray, gain: float) -> np.ndarray:
    return np.clip(np.rint(f * gain), 0, 255).astype(np.uint8)


def _blur(f: np.ndarray, sigma: float) -> np.ndarray:
    """محوِ گاوسی با σ پیکسل؛ σ ≥ ۸ روی نسخهٔ ۱/k (k = ⌊σ/4⌋) حساب و دوخطی برگردانده می‌شود (خطا < ۱٫۵٪، ده‌ها برابر سریع‌تر)."""
    if sigma <= 0.05:
        return f
    k = int(sigma // 4)
    if k >= 2:
        h, w = f.shape
        small = cv2.resize(f, (-(-w // k), -(-h // k)), interpolation=cv2.INTER_AREA)
        small = cv2.GaussianBlur(small, (0, 0), sigma / k, borderType=cv2.BORDER_CONSTANT)
        return cv2.resize(small, (w, h), interpolation=cv2.INTER_LINEAR)
    return cv2.GaussianBlur(f, (0, 0), sigma, borderType=cv2.BORDER_CONSTANT)


def maps(alpha: np.ndarray, fx: dict, W: float) -> list[tuple[np.ndarray, np.ndarray]]:
    """[(رنگِ ۰..۱ (۳)، نقشهٔ آلفای uint8)] از پایین به بالا (سایه، درخشش، خطِ دور)؛ alpha = uint8 ِ دارای حاشیه."""
    out: list[tuple[np.ndarray, np.ndarray]] = []
    h, w = alpha.shape
    sh, gl, st = fx.get("shadow"), fx.get("glow"), fx.get("stroke")
    if sh and sh["opacity"] > 0:
        f = alpha.astype(np.float32)
        dx, dy = float(sh["dx"]) * W, float(sh["dy"]) * W
        if abs(dx) > 1e-6 or abs(dy) > 1e-6:
            f = cv2.warpAffine(f, np.float32([[1, 0, dx], [0, 1, dy]]), (w, h), flags=cv2.INTER_LINEAR,
                               borderMode=cv2.BORDER_CONSTANT, borderValue=0)
        f = _blur(f, float(sh["blur"]) * W)
        out.append((_rgb(sh["color"]), _u8(f, float(sh["opacity"]))))
        del f
    if gl and gl["opacity"] > 0:
        d = dilate_disc(alpha, float(gl["size"]) * W)
        f = _blur(d.astype(np.float32), float(gl["blur"]) * W)
        out.append((_rgb(gl["color"]), _u8(f, float(gl["opacity"]))))
        del f, d
    if st and st["w"] > 0 and st["opacity"] > 0:
        d = dilate_disc(alpha, float(st["w"]) * W)
        out.append((_rgb(st["color"]), _u8(d.astype(np.float32), float(st["opacity"]))))
        del d
    return out


def bake(tile: Image.Image, pivot: tuple[float, float], fx: dict | None, W: float) -> tuple[Image.Image, tuple[float, float]]:
    """تایلِ RGBA + افکت ⇒ (تایلِ تازه، محورِ جابه‌جاشده). fx خالی ⇒ همان ورودی."""
    if not active(fx):
        return tile, pivot
    m = margin(fx, W)
    rgba = np.asarray(tile.convert("RGBA"))
    h, w = rgba.shape[:2]
    H2, W2 = h + 2 * m, w + 2 * m
    alpha = np.zeros((H2, W2), np.uint8)
    alpha[m:m + h, m:m + w] = rgba[..., 3]
    layers_ = maps(alpha, fx, W)
    del alpha
    out = np.empty((H2, W2, 4), np.uint8)
    step = max(1, STRIP_PIXELS // W2)
    for a in range(0, H2, step):
        b = min(H2, a + step)
        pm = np.zeros((b - a, W2, 3), np.float32)        # رنگِ پیش‌ضرب‌شده
        ac = np.zeros((b - a, W2), np.float32)
        for color, amap in layers_:
            al = amap[a:b].astype(np.float32) / 255.0
            pm = pm * (1.0 - al)[..., None] + color * al[..., None]
            ac = al + ac * (1.0 - al)
        r0, r1 = max(a, m), min(b, m + h)
        if r1 > r0:
            seg = rgba[r0 - m:r1 - m]
            la = seg[..., 3].astype(np.float32) / 255.0
            lc = seg[..., :3].astype(np.float32) / 255.0
            sl = (slice(r0 - a, r1 - a), slice(m, m + w))
            pm[sl] = lc * la[..., None] + pm[sl] * (1.0 - la)[..., None]
            ac[sl] = la + ac[sl] * (1.0 - la)
        rgb = np.where(ac[..., None] > 1e-6, pm / np.maximum(ac[..., None], 1e-6), 0.0)
        out[a:b, :, :3] = np.clip(np.rint(rgb * 255.0), 0, 255).astype(np.uint8)
        out[a:b, :, 3] = np.clip(np.rint(ac * 255.0), 0, 255).astype(np.uint8)
    return Image.fromarray(out, "RGBA"), (pivot[0] + m, pivot[1] + m)
