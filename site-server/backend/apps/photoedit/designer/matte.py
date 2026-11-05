"""جداکردنِ محصول از زمینه روی سرورِ سایت (بی سرورِ پردازش): GrabCut با شروعِ هوشمند.

* عکسِ شفاف ⇒ همان آلفا.
* زمینهٔ ساده ⇒ ماسکِ «فاصله از رنگِ زمینه» اولِ GrabCut را می‌دهد (سریع و تمیز).
* زمینهٔ شلوغ ⇒ مستطیلِ سوژه (از تحلیل) اولِ GrabCut است؛ کیفیت کم‌تر و ``ok`` ممکن است False شود.

نتیجه ``ok=False`` یعنی «به این جدا کردن اعتماد نکن» (پوشش خیلی کم/زیاد، یا سوژه به هر چهار لبه چسبیده)؛
طراحِ خودکار آن‌وقت محصول را جدا نمی‌کند و بقیهٔ طراحی را روی عکسِ کامل می‌سازد (و همین را به کاربر می‌گوید).
سرورِ پردازش روشن باشد، «حذف پس‌زمینهٔ کیت» (BiRefNet) در حالتِ دستی دقیق‌تر است.
"""
from __future__ import annotations

import cv2
import numpy as np
from PIL import Image

from . import analyze

SIDE = 512


def _fill_holes(m: np.ndarray) -> np.ndarray:
    h, w = m.shape
    ff = m.copy()
    pad = np.zeros((h + 2, w + 2), np.uint8)
    cv2.floodFill(ff, pad, (0, 0), 255)
    holes = cv2.bitwise_not(ff)
    return cv2.bitwise_or(m, holes)


def compute(img: Image.Image, subject_box=None) -> dict:
    """⇒ {ok, method, coverage, mask (uint8 هم‌اندازهٔ img)، reason}."""
    W, H = img.size
    if img.mode == "RGBA":
        a = np.asarray(img.getchannel("A"), dtype=np.uint8)
        if a.min() < 250:
            cov = float((a > 127).mean())
            return {"ok": 0.01 < cov < 0.97, "method": "alpha", "coverage": round(cov, 3), "mask": a,
                    "reason": "" if 0.01 < cov < 0.97 else "شفافیتِ عکس محصولی را مشخص نمی‌کند"}
    rgb, _ = analyze._small(img, SIDE)
    h, w = rgb.shape[:2]
    bg = analyze.border_stats(rgb)
    pm, plain = analyze.plain_mask(rgb, bg)
    gc = np.full((h, w), cv2.GC_PR_BGD, np.uint8)
    if plain:
        cc = analyze._largest_component(pm, 0.01)
        gc[cc > 0] = cv2.GC_PR_FGD
        core = cv2.erode(cc * 255, np.ones((9, 9), np.uint8))
        gc[core > 0] = cv2.GC_FGD
        method = "plain-bg"
    else:
        b = subject_box or [0.1, 0.1, 0.9, 0.9]
        x0, y0 = max(0, int((b[0] - 0.02) * w)), max(0, int((b[1] - 0.02) * h))
        x1, y1 = min(w, int((b[2] + 0.02) * w)), min(h, int((b[3] + 0.02) * h))
        gc[y0:y1, x0:x1] = cv2.GC_PR_FGD
        cx0, cy0 = x0 + (x1 - x0) // 4, y0 + (y1 - y0) // 4
        gc[cy0:y1 - (y1 - y0) // 4, cx0:x1 - (x1 - x0) // 4] = cv2.GC_FGD
        method = "grabcut-box"
    gc[:2, :] = cv2.GC_BGD
    gc[-2:, :] = cv2.GC_BGD
    gc[:, :2] = cv2.GC_BGD
    gc[:, -2:] = cv2.GC_BGD
    try:
        bgd, fgd = np.zeros((1, 65), np.float64), np.zeros((1, 65), np.float64)
        cv2.setRNGSeed(11)
        cv2.grabCut(cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR), gc, None, bgd, fgd, 4, cv2.GC_INIT_WITH_MASK)
    except cv2.error:
        return {"ok": False, "method": method, "coverage": 0.0, "mask": np.zeros((H, W), np.uint8),
                "reason": "الگوریتمِ جداسازی روی این عکس جواب نداد"}
    fg = np.where((gc == cv2.GC_FGD) | (gc == cv2.GC_PR_FGD), 255, 0).astype(np.uint8)
    fg = cv2.morphologyEx(fg, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    fg = analyze._largest_component(fg, 0.005) * 255
    fg = _fill_holes(fg.astype(np.uint8))
    fg = cv2.erode(fg, np.ones((3, 3), np.uint8))          # حلقهٔ نورانیِ لبه (halo) را کم می‌کند
    fg = cv2.GaussianBlur(fg, (0, 0), 1.3)
    cov = float((fg > 127).mean())
    touches = sum(bool((fg[e] > 127).mean() > 0.6) for e in (np.s_[0, :], np.s_[-1, :], np.s_[:, 0], np.s_[:, -1]))
    ok = 0.03 < cov < 0.92 and touches < 3
    reason = "" if ok else ("محصول خیلی کوچک یا خیلی بزرگ پیدا شد" if not 0.03 < cov < 0.92 else "محصول به لبه‌های عکس چسبیده است")
    mask = cv2.resize(fg, (W, H), interpolation=cv2.INTER_LINEAR)
    return {"ok": ok, "method": method, "coverage": round(cov, 3), "mask": mask, "reason": reason}


def cutout_image(img: Image.Image, mask: np.ndarray) -> tuple[Image.Image, tuple[int, int, int, int]]:
    """تصویرِ RGBA ِ محصول، بریده به کادرِ ماسک. ⇒ (تصویر، (x0, y0, x1, y1) پیکسل در img)."""
    ys, xs = np.where(mask > 20)
    if len(xs) == 0:
        raise ValueError("ماسکِ خالی")
    pad = 2
    x0, x1 = max(0, int(xs.min()) - pad), min(img.width, int(xs.max()) + 1 + pad)
    y0, y1 = max(0, int(ys.min()) - pad), min(img.height, int(ys.max()) + 1 + pad)
    rgb = img.convert("RGB").crop((x0, y0, x1, y1))
    a = Image.fromarray(mask[y0:y1, x0:x1], "L")
    if img.mode == "RGBA":
        a = Image.fromarray(np.minimum(np.asarray(a), np.asarray(img.getchannel("A").crop((x0, y0, x1, y1)))), "L")
    out = rgb.convert("RGBA")
    out.putalpha(a)
    return out, (x0, y0, x1, y1)
