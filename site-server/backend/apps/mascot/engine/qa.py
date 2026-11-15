"""بررسیِ ثباتِ ماسکوت («کلیدِ رنگ»): آیا هر رنگِ امضای شخصیت در تصویر دیده می‌شود؟

SOURCE: ported from InstAI (maniUZqqz/Instai) instai/identity/check.py (``signature_colours``, ``colour_shares``, ``check_image``) @ 82733b0, adapted for NMarketing
brand mascots: the check runs on the FIGURE layer (transparent background) instead of the finished picture, so a background of the same colour
cannot hide a missing colour (the documented limit of the InstAI version); every figure pixel is assigned to its NEAREST palette colour (two near colours such as a
navy limb and a teal headband do not "find" each other's pixels); the structure/vision layers of InstAI (sheet embedding, Ollama vision) are not ported.

یک بررسی «پرچم» است نه عمل: نتیجه در رکوردِ رندر نوشته می‌شود و صفحه نشانش می‌دهد.
"""
from __future__ import annotations

import numpy as np
from PIL import Image

PALETTE_OK = 0.67             # سهمِ رنگ‌های امضا که باید دیده شوند
SIGNATURE_MIN_SAT = 40        # رنگِ نزدیک به خاکستری (کاغذ سفید، جوهرِ مشکی) «امضا» نیست
MIN_SHARE = 0.0008            # هر رنگِ امضا دست‌کم این سهم از پیکسل‌های درونِ لکه‌های تک‌رنگِ شخصیت را بگیرد
MIN_PIXELS = 4                # و دست‌کم این‌قدر پیکسل
NEAR_TOL = 30                 # فاصلهٔ RGB تا رنگِ نزدیک‌ترین پالت (درونِ لکه‌ها رنگ دقیق است)
FLAT_TOL = 6                  # همسایه‌ها تا این اختلافِ کانال هم‌رنگ حساب می‌شوند
MIN_FIGURE_SHARE = 0.004      # شخصیت دست‌کم این سهم از بوم را بپوشاند (وگرنه «قاب خالی» است)
ANALYSE_SIDE = 480            # بعد از بریدن تا کادرِ شخصیت؛ پس اندازهٔ بومِ پست روی نتیجه اثر ندارد


def _rgb(hx: str) -> tuple[int, int, int]:
    h = hx.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def signature_colours(palette: list[dict]) -> list[dict]:
    """رنگ‌های هویت‌ساز: نه سفیدِ تقریبی، نه مشکیِ تقریبی، نه خاکستری؛ یکتا بر پایهٔ hex (نقش‌ها یکی می‌شوند)."""
    out, seen = [], set()
    for p in palette or []:
        try:
            r, g, b = _rgb(p["hex"])
        except (KeyError, ValueError, IndexError):
            continue
        if max(r, g, b) - min(r, g, b) < SIGNATURE_MIN_SAT or p["hex"] in seen:
            continue
        seen.add(p["hex"])
        roles = [q.get("role", "") for q in palette if q.get("hex") == p["hex"]]
        out.append({**p, "roles": roles})
    return out


def _flat_mask(arr: np.ndarray) -> np.ndarray:
    """پیکسل‌های «درونِ لکهٔ تک‌رنگ»: کاملاً پررنگ و هم‌رنگِ چهار همسایه. لبه‌های نرم‌شده (آمیزهٔ دو رنگ، یا رنگ و شفاف) بیرون می‌مانند؛ وگرنه آمیزهٔ فیروزه‌ای و خطِ دور
    می‌توانست «سرمه‌ای» به‌نظر بیاید و رنگِ گمشده را پنهان کند."""
    rgb = arr[..., :3].astype(np.int16)
    solid = arr[..., 3] >= 250
    h, w = solid.shape
    flat = solid.copy()
    if w > 1:
        okx = (np.abs(rgb[:, 1:] - rgb[:, :-1]).max(axis=2) <= FLAT_TOL) & solid[:, 1:] & solid[:, :-1]
        flat[:, 1:] &= okx
        flat[:, :-1] &= okx
    if h > 1:
        oky = (np.abs(rgb[1:, :] - rgb[:-1, :]).max(axis=2) <= FLAT_TOL) & solid[1:, :] & solid[:-1, :]
        flat[1:, :] &= oky
        flat[:-1, :] &= oky
    return flat


def colour_shares(layer: Image.Image, palette: list[dict]) -> tuple[list[dict], int, float]:
    """برای هر رنگِ پالت: شمارِ پیکسل‌های درونِ لکه‌های تک‌رنگِ شخصیت که نزدیک‌ترین رنگشان همان است. ⇒ (ردیف‌ها، شمارِ کلِ آن پیکسل‌ها، سهمِ شخصیت از بوم)"""
    im = layer.convert("RGBA")
    alpha = np.asarray(im.getchannel("A"))
    figure_share = float((alpha >= 250).sum()) / max(1, alpha.size)
    box = im.getchannel("A").point(lambda v: 255 if v >= 250 else 0).getbbox()
    if box is not None:
        im = im.crop(box)
    if max(im.size) > ANALYSE_SIDE:
        im.thumbnail((ANALYSE_SIDE, ANALYSE_SIDE), Image.BOX)
    arr = np.asarray(im)
    flat = _flat_mask(arr)
    px = arr[flat][:, :3].astype(np.int32)
    total = int(px.shape[0])
    if total == 0:
        return [{"role": p.get("role", ""), "hex": p["hex"], "name": p.get("name", ""), "count": 0, "share": 0.0, "found": False} for p in palette], 0, figure_share
    cols = np.array([_rgb(p["hex"]) for p in palette], dtype=np.int32)
    d2 = ((px[:, None, :] - cols[None, :, :]) ** 2).sum(axis=2)
    nearest = d2.argmin(axis=1)
    near_ok = d2[np.arange(total), nearest] <= NEAR_TOL * NEAR_TOL
    counts = np.bincount(nearest[near_ok], minlength=len(palette))
    rows = []
    for i, p in enumerate(palette):
        n = int(counts[i])
        share = n / total
        rows.append({"role": p.get("role", ""), "hex": p["hex"], "name": p.get("name", ""), "count": n, "share": round(share, 5), "found": n >= MIN_PIXELS and share >= MIN_SHARE})
    return rows, total, figure_share


def check_figure(layer: Image.Image, palette: list[dict]) -> dict:
    """{ok, palette_score, colours[], notes[{code، ...}]، figure_share}. ``layer`` = لایهٔ RGBA شخصیت (بدونِ پس‌زمینه)."""
    sig = signature_colours(palette)
    # همهٔ پالت (سفید، خطِ دور هم) در تخصیصِ «نزدیک‌ترین» شرکت می‌کنند تا رنگِ امضا پیکسلِ همسایه‌اش را ندزدد
    allp = {p["hex"]: p for p in palette}
    for s in sig:
        allp[s["hex"]] = s
    rows_all, total, figure_share = colour_shares(layer, list(allp.values()))
    by_hex = {r["hex"]: r for r in rows_all}
    notes: list[dict] = []
    colours = []
    for s in sig:
        r = dict(by_hex.get(s["hex"]) or {"hex": s["hex"], "share": 0.0, "found": False, "count": 0})
        r["role"], r["roles"], r["name"] = s.get("role", ""), s.get("roles", []), s.get("name", "")
        colours.append(r)
        if not r["found"]:
            notes.append({"code": "colour_missing", "role": r["role"], "name": r["name"], "hex": r["hex"]})
    score = round(sum(1 for c in colours if c["found"]) / len(colours), 3) if colours else None
    blank = figure_share < MIN_FIGURE_SHARE
    if blank:
        notes.append({"code": "figure_blank", "share": round(figure_share, 5)})
    ok = (score is None or score >= PALETTE_OK) and not blank
    return {"ok": bool(ok), "palette_score": score, "colours": colours, "notes": notes, "figure_share": round(figure_share, 5),
            "thresholds": {"palette": PALETTE_OK, "min_share": MIN_SHARE, "min_figure_share": MIN_FIGURE_SHARE}, "scope": "figure"}


def note_fa(n: dict) -> str:
    """یادداشتِ فارسی برای صفحه."""
    if n.get("code") == "colour_missing":
        return f"رنگِ «{n.get('name') or n.get('hex')}» ({n.get('role')}) در تصویر دیده نمی‌شود."
    if n.get("code") == "figure_blank":
        return "شخصیت در تصویر دیده نمی‌شود (قاب خالی یا بیرون از کادر)."
    return str(n.get("code", ""))
