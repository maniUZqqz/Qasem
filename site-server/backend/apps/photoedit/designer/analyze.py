"""تحلیلِ قطعیِ عکس برای طراحی (بی هوشِ مصنوعی): روشنایی، پالتِ محصول، زمینه، جای سوژه و جاهای «آرام» برای متن.

ورودی یک تصویرِ PIL (معمولاً همان «بومِ قاب‌شده» که متن رویش می‌نشیند). همهٔ مختصات‌های خروجی کسری از همان تصویرند.
"""
from __future__ import annotations

import cv2
import numpy as np
from PIL import Image

from . import colorx, grid

WORK_SIDE = 320


def _small(img: Image.Image, side: int = WORK_SIDE) -> tuple[np.ndarray, np.ndarray | None]:
    """⇒ (RGB uint8 h×w×3، آلفا یا None) روی نسخهٔ کوچک."""
    im = img.copy()
    im.thumbnail((side, side), Image.Resampling.BILINEAR)
    if im.mode == "RGBA":
        a = np.asarray(im.getchannel("A"), dtype=np.uint8)
        bg = Image.new("RGB", im.size, (255, 255, 255))
        bg.paste(im, mask=im.getchannel("A"))
        return np.asarray(bg), a
    return np.asarray(im.convert("RGB")), None


def _largest_component(mask: np.ndarray, min_frac: float = 0.01) -> np.ndarray:
    n, lab, stats, _ = cv2.connectedComponentsWithStats((mask > 0).astype(np.uint8), connectivity=8)
    if n <= 1:
        return np.zeros_like(mask, dtype=np.uint8)
    areas = stats[1:, cv2.CC_STAT_AREA]
    i = int(np.argmax(areas)) + 1
    if areas[i - 1] < min_frac * mask.size:
        return np.zeros_like(mask, dtype=np.uint8)
    return (lab == i).astype(np.uint8)


def border_stats(rgb: np.ndarray) -> dict:
    h, w = rgb.shape[:2]
    m = max(2, int(min(h, w) * 0.05))
    ring = np.concatenate([rgb[:m].reshape(-1, 3), rgb[-m:].reshape(-1, 3), rgb[:, :m].reshape(-1, 3), rgb[:, -m:].reshape(-1, 3)])
    med = np.median(ring, axis=0)
    dist = np.linalg.norm(ring.astype(np.float32) - med.astype(np.float32), axis=1)
    return {"median": med, "spread": float(np.percentile(dist, 90)), "ring": ring}


def plain_mask(rgb: np.ndarray, bg: dict | None = None) -> tuple[np.ndarray, bool]:
    """ماسکِ «چیزی که زمینه نیست» وقتی زمینه تقریباً یک‌رنگ است؛ ⇒ (ماسک ۰/۲۵۵، آیا زمینه ساده بود)."""
    bg = bg or border_stats(rgb)
    plain = bg["spread"] < 28
    lab = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB).astype(np.float32)
    ref = cv2.cvtColor(np.uint8([[bg["median"]]]), cv2.COLOR_RGB2LAB).astype(np.float32)[0, 0]
    d = np.linalg.norm(lab - ref, axis=2)
    t = max(14.0, float(bg["spread"]) * 1.2 + 8.0)
    m = (d > t).astype(np.uint8) * 255
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8))
    return m, plain


def spectral_saliency(rgb: np.ndarray) -> np.ndarray:
    """سالینسیِ «باقی‌ماندهٔ طیفی» (Hou & Zhang) — ارزان و بی‌مدل. ⇒ float ۰..۱."""
    g = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY).astype(np.float32)
    g = cv2.resize(g, (64, 64), interpolation=cv2.INTER_AREA)
    f = np.fft.fft2(g)
    log_amp = np.log(np.abs(f) + 1e-8)
    phase = np.angle(f)
    resid = log_amp - cv2.blur(log_amp, (3, 3))
    sal = np.abs(np.fft.ifft2(np.exp(resid + 1j * phase))) ** 2
    sal = cv2.GaussianBlur(sal.astype(np.float32), (0, 0), 2.0)
    sal -= sal.min()
    sal /= max(1e-6, sal.max())
    return cv2.resize(sal, (rgb.shape[1], rgb.shape[0]), interpolation=cv2.INTER_LINEAR)


def subject_of(rgb: np.ndarray, alpha: np.ndarray | None) -> dict:
    """جای سوژه: {box: [x0,y0,x1,y1]، area، method: alpha|plain-bg|saliency|center، mask (uint8 یا None)}."""
    h, w = rgb.shape[:2]
    if alpha is not None and alpha.min() < 200 and (alpha > 127).mean() > 0.01:
        m = _largest_component(alpha > 127, 0.005)
        if m.any():
            ys, xs = np.where(m)
            return {"box": [xs.min() / w, ys.min() / h, (xs.max() + 1) / w, (ys.max() + 1) / h], "method": "alpha",
                    "mask": m * 255, "plain": False}
    pm, plain = plain_mask(rgb)
    if plain:
        cc = _largest_component(pm, 0.02)
        frac = float(cc.mean())
        if 0.02 <= frac <= 0.9:
            ys, xs = np.where(cc)
            return {"box": [xs.min() / w, ys.min() / h, (xs.max() + 1) / w, (ys.max() + 1) / h], "method": "plain-bg",
                    "mask": cc * 255, "plain": True}
    sal = spectral_saliency(rgb)
    yy, xx = np.mgrid[0:h, 0:w]
    prior = np.exp(-(((xx / w - 0.5) / 0.45) ** 2 + ((yy / h - 0.5) / 0.45) ** 2))
    s = sal * (0.5 + 0.5 * prior)
    thr = float(s.mean() + 1.2 * s.std())
    cc = _largest_component((s > thr).astype(np.uint8) * 255, 0.015)
    frac = float(cc.mean())
    if 0.015 <= frac <= 0.85:
        ys, xs = np.where(cc)
        return {"box": [xs.min() / w, ys.min() / h, (xs.max() + 1) / w, (ys.max() + 1) / h], "method": "saliency",
                "mask": cc * 255, "plain": plain}
    return {"box": [0.2, 0.2, 0.8, 0.8], "method": "center", "mask": None, "plain": plain}


def region_stats(rgb: np.ndarray, rect) -> dict:
    """آمارِ یک ناحیه (کسری): روشنایی، پراکندگی، لبه‌ها (شلوغی)، و پیکسل‌های نمونه برای کنتراست."""
    h, w = rgb.shape[:2]
    x0, y0 = int(max(0, min(w - 1, rect[0] * w))), int(max(0, min(h - 1, rect[1] * h)))
    x1, y1 = int(max(x0 + 1, min(w, rect[2] * w))), int(max(y0 + 1, min(h, rect[3] * h)))
    part = rgb[y0:y1, x0:x1]
    g = cv2.cvtColor(part, cv2.COLOR_RGB2GRAY).astype(np.float32)
    gx = cv2.Sobel(g, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(g, cv2.CV_32F, 0, 1, ksize=3)
    edge = float(np.mean(np.hypot(gx, gy)) / 255.0)
    return {"luma": float(g.mean() / 255.0), "std": float(g.std() / 255.0), "edge": edge, "pixels": part.reshape(-1, 3)}


def calm_score(st: dict) -> float:
    """۰ (شلوغ) تا ۱ (آرام): پراکندگیِ کم و لبهٔ کم."""
    return float(max(0.0, 1.0 - min(1.0, st["std"] * 3.2 + st["edge"] * 2.4)))


def slot_scores(rgb: np.ndarray, fmt: str, W: int, H: int, subject_box) -> dict:
    """امتیازِ هر «جا» برای نشستنِ متن: آرام‌بودن منهای هم‌پوشانی با سوژه."""
    out = {}
    for name in ("top", "bottom", "middle", "left", "right", "tl", "tr", "bl", "br"):
        r = grid.slot(name, fmt, W, H)
        st = region_stats(rgb, r)
        ov = grid.overlap_area(r, subject_box) / max(1e-9, grid.area(r))
        out[name] = {"rect": [round(v, 4) for v in r], "calm": round(calm_score(st), 3), "luma": round(st["luma"], 3),
                     "subject_overlap": round(ov, 3), "score": round(calm_score(st) - 0.9 * ov, 3)}
    return out


def analyze(img: Image.Image, *, fmt: str = "orig", facts: dict | None = None, findings: list | None = None) -> dict:
    """تحلیلِ کامل ⇒ دیکشنریِ JSON-پذیر (به‌جز mask که با کلیدِ ``_mask`` می‌آید و در JSON نمی‌رود)."""
    W, H = img.size
    rgb, alpha = _small(img)
    h, w = rgb.shape[:2]
    sub = subject_of(rgb, alpha)
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY).astype(np.float32) / 255.0
    p5, p50, p95 = (float(v) for v in np.percentile(gray, [5, 50, 95]))
    mask = sub.pop("mask", None)
    # پالتِ محصول: اگر سوژه جدا شد، فقط پیکسل‌های سوژه (زمینهٔ سفید پالت را خراب نکند)
    if mask is not None and (mask > 0).sum() > 200 and sub["method"] != "center":
        px = rgb[mask > 0]
    else:
        px = rgb.reshape(-1, 3)
    pal = colorx.palette_from_pixels(px, 5)
    dom, accent = colorx.pick_dominant_and_accent(pal)
    bg = border_stats(rgb)
    bg_hex = colorx.rgb_to_hex(bg["median"])
    scores = slot_scores(rgb, fmt, W, H, sub["box"])
    best_slot = max(scores, key=lambda k: scores[k]["score"])
    area = (sub["box"][2] - sub["box"][0]) * (sub["box"][3] - sub["box"][1])
    out = {
        "size": [W, H], "aspect": round(W / max(1, H), 4),
        "orientation": "landscape" if W > H * 1.1 else "portrait" if H > W * 1.1 else "square",
        "brightness": {"p5": round(p5, 3), "p50": round(p50, 3), "p95": round(p95, 3), "mean": round(float(gray.mean()), 3),
                       "contrast": round(p95 - p5, 3)},
        "palette": pal, "dominant": dom, "accent": accent,
        "background": {"plain": bool(sub.get("plain")), "color": bg_hex, "spread": round(bg["spread"], 1),
                       "luma": round(colorx.luminance(bg["median"]), 3)},
        "subject": {"box": [round(v, 4) for v in sub["box"]], "area": round(float(area), 4), "method": sub["method"],
                    "center": [round((sub["box"][0] + sub["box"][2]) / 2, 4), round((sub["box"][1] + sub["box"][3]) / 2, 4)]},
        "slots": scores, "best_text_slot": best_slot, "has_alpha": alpha is not None,
        "findings": [f.get("what") for f in (findings or []) if isinstance(f, dict)],
    }
    out["_mask"] = mask
    return out


def public(an: dict) -> dict:
    """نسخهٔ بی‌ماسک برای JSON/پرامپت."""
    return {k: v for k, v in an.items() if not k.startswith("_")}


def describe_fa(an: dict) -> str:
    """توضیحِ کوتاهِ فارسی از آنچه سنجیده شد (برای نشان‌دادن به کاربر)."""
    pal = "، ".join(p["name"] for p in an["palette"][:3]) or "—"
    bg = "ساده" if an["background"]["plain"] else "شلوغ"
    ori = {"landscape": "افقی", "portrait": "عمودی", "square": "مربع"}[an["orientation"]]
    br = an["brightness"]["p50"]
    light = "تیره" if br < 0.32 else "روشن" if br > 0.62 else "متوسط"
    meth = {"alpha": "از شفافیتِ عکس", "plain-bg": "از روی زمینهٔ ساده", "saliency": "با تشخیصِ برجستگی", "center": "حدسی (وسط)"}[an["subject"]["method"]]
    return f"عکسِ {ori}، {light}؛ زمینه {bg}؛ رنگ‌های اصلی: {pal}؛ جای محصول {meth} پیدا شد."
