"""مسیرِ قلم (Pen): خمِ بزیه ⇒ چندضلعی ⇒ پوششِ پیکسلی (برای لایهٔ شکلِ ``path`` و برای ماسک).

مدلِ داده (همان که در ``layers.normalize_layers`` وارسی می‌شود)::

    {"closed": true, "pts": [{"x": 0.1, "y": 0.2, "hi": [dx, dy] | null, "ho": [dx, dy] | null}, …]}

* ``x``، ``y``، و آفستِ دسته‌ها (``hi`` = دستهٔ ورودی، ``ho`` = دستهٔ خروجی) به واحدِ «جعبهٔ بوم‌شده» اند: کسری از
  پهنا و ارتفاعِ جعبه‌ای که مسیر در آن است (برای شکل: ``w`` × ``h`` لایه؛ برای ماسک: کلِ بوم W × H). بنابراین جابه‌جایی،
  مقیاس و چرخشِ لایه فقط با ``w``، ``h``، ``cx``، ``cy``، ``rot`` کار می‌کند و نقطه‌ها دست نمی‌خورند.
* پارهٔ مکعبی i ⇒ i+1: ``P0 = pt_i``، ``P1 = pt_i + ho_i``، ``P2 = pt_{i+1} + hi_{i+1}``، ``P3 = pt_{i+1}``؛ در مسیرِ بسته
  پارهٔ آخر ⇒ اول هم هست (با ``ho_last`` و ``hi_first``). دستهٔ ``null`` = صفر؛ اگر هر دو دستهٔ یک پاره صفر باشند، پاره خط است.
* پرکردن همیشه **nonzero winding** است (مثلِ canvas ِ مرورگر). مسیرِ باز برای پر شدن ضمناً بسته فرض می‌شود
  (مثلِ ``ctx.fill()``)، ولی خطِ دورش (stroke) پارهٔ بستن ندارد.

مسطح‌سازی: هر پارهٔ منحنی به ``n = clamp(ceil(L / 1.5), 6, 400)`` پارهٔ مساوی در پارامتر t تقسیم می‌شود که L طولِ چندضلعیِ
کنترل به پیکسل است (خطای معمولاً < ۰٫۱ پیکسل).

پوشش: هر پیکسل ``ss × ss`` (پیش‌فرض ۲×۲) نمونه دارد، نمونه‌ها در مرکزِ زیرپیکسل‌اند ((i+0.5)/ss)، و پوشش = تعدادِ نمونه‌های
درون ÷ ss². خروجی float32 در ۰..۱. خطِ دور با ``cv2.polylines`` (گوشه و سرِ گرد) روی همان شبکهٔ نمونه‌ها رسم می‌شود.
"""
from __future__ import annotations

import math

import cv2
import numpy as np

MAX_POINTS = 200
_CHUNK_SAMPLES = 4_000_000


def _handle(h):
    if isinstance(h, (list, tuple)) and len(h) >= 2:
        return float(h[0]), float(h[1])
    return None


def flatten(path: dict, w_px: float, h_px: float) -> list[tuple[float, float]]:
    """مسیر ⇒ چندضلعی (نقطه‌های (x, y) به پیکسل نسبت به گوشهٔ بالا-چپِ جعبهٔ w_px × h_px).

    مسیرِ بسته: نقطهٔ اول در پایان تکرار نمی‌شود (بسته‌بودن ضمنی است). مسیرِ باز: از نقطهٔ اول تا آخر.
    """
    pts = (path or {}).get("pts") or []
    n = len(pts)
    if n == 0:
        return []
    closed = bool((path or {}).get("closed"))
    out: list[tuple[float, float]] = [(float(pts[0]["x"]) * w_px, float(pts[0]["y"]) * h_px)]
    segs = n if (closed and n > 1) else n - 1
    for i in range(segs):
        a, b = pts[i], pts[(i + 1) % n]
        p0 = (float(a["x"]) * w_px, float(a["y"]) * h_px)
        p3 = (float(b["x"]) * w_px, float(b["y"]) * h_px)
        ho, hi = _handle(a.get("ho")), _handle(b.get("hi"))
        last = closed and i == segs - 1
        if not ho and not hi:
            if not last:
                out.append(p3)
            continue
        p1 = (p0[0] + (ho[0] * w_px if ho else 0.0), p0[1] + (ho[1] * h_px if ho else 0.0))
        p2 = (p3[0] + (hi[0] * w_px if hi else 0.0), p3[1] + (hi[1] * h_px if hi else 0.0))
        length = math.dist(p0, p1) + math.dist(p1, p2) + math.dist(p2, p3)
        steps = max(6, min(400, int(math.ceil(length / 1.5))))
        for s in range(1, steps + 1):
            if last and s == steps:
                break                      # نقطهٔ آخرِ پارهٔ بستن = نقطهٔ اول، تکرار نمی‌شود
            t = s / steps
            u = 1.0 - t
            c0, c1, c2, c3 = u * u * u, 3 * u * u * t, 3 * u * t * t, t * t * t
            out.append((c0 * p0[0] + c1 * p1[0] + c2 * p2[0] + c3 * p3[0],
                        c0 * p0[1] + c1 * p1[1] + c2 * p2[1] + c3 * p3[1]))
    return out


def fill_coverage(poly: list[tuple[float, float]], width: int, height: int, ss: int = 2) -> np.ndarray:
    """چندضلعی (px) ⇒ پوششِ nonzero-winding روی شبکهٔ ``height × width`` ⇒ float32 ۰..۱."""
    return fill_polygons([np.asarray(poly, np.float64)] if len(poly) >= 3 else [], width, height, ss)


def _fill_edges(polys: list[np.ndarray], width: int, height: int, ss: int) -> np.ndarray:
    cov = np.zeros((height, width), np.float32)
    if width < 1 or height < 1:
        return cov
    pts_all = [p * ss for p in polys]
    a = np.concatenate(pts_all, axis=0)
    b = np.concatenate([np.roll(p, -1, axis=0) for p in pts_all], axis=0)
    y0, y1, x0, x1 = a[:, 1], b[:, 1], a[:, 0], b[:, 0]
    keep = y0 != y1
    y0, y1, x0, x1 = y0[keep], y1[keep], x0[keep], x1[keep]
    if len(y0) == 0:
        return cov
    sw, sh = width * ss, height * ss
    direction = np.where(y1 > y0, 1, -1).astype(np.int32)
    ymin, ymax = np.minimum(y0, y1), np.maximum(y0, y1)
    jlo = np.maximum(np.ceil(ymin - 0.5), 0).astype(np.int64)
    jhi = np.minimum(np.ceil(ymax - 0.5) - 1, sh - 1).astype(np.int64)
    counts = np.maximum(jhi - jlo + 1, 0)
    total = int(counts.sum())
    if total == 0:
        return cov
    eidx = np.repeat(np.arange(len(y0)), counts)
    starts = np.cumsum(counts) - counts
    j = jlo[eidx] + (np.arange(total) - np.repeat(starts, counts))
    x = x0[eidx] + (j + 0.5 - y0[eidx]) * ((x1 - x0) / (y1 - y0))[eidx]
    d = direction[eidx]
    order = np.lexsort((x, j))
    j, x, d = j[order], x[order], d[order]
    cs = np.cumsum(d)
    row_first = np.concatenate(([True], j[1:] != j[:-1]))
    first_idx = np.maximum.accumulate(np.where(row_first, np.arange(len(j)), 0))
    before = (cs - d)[first_idx]            # مجموعِ پیچش پیش از شروعِ همین ردیف
    wind = cs - before                      # پیچشِ بعد از عبور از این تقاطع
    same_next = np.concatenate((j[1:] == j[:-1], [False]))
    span = same_next & (wind != 0)
    k = np.nonzero(span)[0]
    if len(k) == 0:
        return cov
    sj = j[k]
    si0 = np.clip(np.ceil(x[k] - 0.5), 0, sw).astype(np.int64)
    si1 = np.clip(np.ceil(x[k + 1] - 0.5), 0, sw).astype(np.int64)
    rows_per_chunk = max(ss, (_CHUNK_SAMPLES // (sw + 1)) // ss * ss)
    for r0 in range(0, sh, rows_per_chunk):
        r1 = min(sh, r0 + rows_per_chunk)
        lo, hi = np.searchsorted(sj, r0, "left"), np.searchsorted(sj, r1, "left")
        if hi <= lo:
            continue
        rr = sj[lo:hi] - r0
        n = (r1 - r0) * (sw + 1)
        diff = (np.bincount(rr * (sw + 1) + si0[lo:hi], minlength=n)
                - np.bincount(rr * (sw + 1) + si1[lo:hi], minlength=n)).reshape(r1 - r0, sw + 1)
        inside = np.cumsum(diff, axis=1)[:, :sw] > 0
        if ss == 1:
            cov[r0:r1] = inside
        else:
            cnt = inside.reshape((r1 - r0) // ss, ss, width, ss).sum(axis=(1, 3), dtype=np.int32)
            cov[r0 // ss:r1 // ss] = cnt.astype(np.float32) / float(ss * ss)
    return cov


def _oriented(pts: np.ndarray) -> np.ndarray:
    """جهتِ چندضلعی را طوری می‌کند که مساحتِ علامت‌دارش مثبت باشد تا اجتماعِ nonzero درست شود."""
    x, y = pts[:, 0], pts[:, 1]
    area = float(np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y))
    return pts if area >= 0 else pts[::-1]


def _circle(cx: float, cy: float, r: float) -> np.ndarray:
    n = max(8, min(48, int(math.ceil(r * 2.0)) + 6))
    th = np.linspace(0.0, 2 * math.pi, n, endpoint=False)
    return np.stack([cx + r * np.cos(th), cy + r * np.sin(th)], axis=1)


def stroke_polygons(poly: list[tuple[float, float]], closed: bool, width_px: float) -> list[np.ndarray]:
    """خطِ دور (گوشه و سرِ گرد) ⇒ فهرستِ چندضلعی‌های هم‌جهت؛ اجتماعشان با nonzero پر می‌شود.

    هر پاره = مستطیل؛ هر گوشه با زاویهٔ > ۰٫۳ رادیان = دایره، وگرنه دو مثلثِ پخ؛ سرهای مسیرِ باز = دایره."""
    h = width_px / 2.0
    pts = [p for i, p in enumerate(poly) if i == 0 or math.dist(p, poly[i - 1]) > 1e-9]
    if closed and len(pts) > 1 and math.dist(pts[0], pts[-1]) <= 1e-9:
        pts.pop()
    n = len(pts)
    if n == 0 or h <= 0:
        return []
    if n == 1:
        return [_circle(pts[0][0], pts[0][1], h)]
    closed = bool(closed) and n > 2
    nseg = n if closed else n - 1
    out: list[np.ndarray] = []
    dirs, norms = [], []
    for i in range(nseg):
        a, b = np.asarray(pts[i]), np.asarray(pts[(i + 1) % n])
        d = (b - a) / max(1e-12, float(np.hypot(*(b - a))))
        nrm = np.array([-d[1], d[0]]) * h
        dirs.append(d)
        norms.append(nrm)
        out.append(_oriented(np.array([a + nrm, b + nrm, b - nrm, a - nrm])))
    verts = range(n) if closed else range(1, n - 1)
    for i in verts:
        d0, d1 = dirs[(i - 1) % nseg], dirs[i % nseg]
        n0, n1 = norms[(i - 1) % nseg], norms[i % nseg]
        v = np.asarray(pts[i])
        turn = math.atan2(d0[0] * d1[1] - d0[1] * d1[0], float(d0 @ d1))
        if abs(turn) > 0.3:
            out.append(_oriented(_circle(v[0], v[1], h)))
        else:
            out.append(_oriented(np.array([v, v + n0, v + n1])))
            out.append(_oriented(np.array([v, v - n0, v - n1])))
    if not closed:
        out.append(_oriented(_circle(pts[0][0], pts[0][1], h)))
        out.append(_oriented(_circle(pts[-1][0], pts[-1][1], h)))
    return out


def fill_polygons(polys, width: int, height: int, ss: int = 2) -> np.ndarray:
    """چند چندضلعی (هرکدام آرایهٔ (n, 2) به px) ⇒ پوششِ nonzero از اجتماعشان؛ float32 ۰..۱."""
    polys = [np.asarray(p, np.float64) for p in polys if len(p) >= 3]
    if not polys:
        return np.zeros((int(height), int(width)), np.float32)
    return _fill_edges(polys, int(width), int(height), max(1, int(ss)))


def stroke_coverage(poly: list[tuple[float, float]], closed: bool, width_px: float, width: int, height: int,
                    ss: int = 2) -> np.ndarray:
    """خطِ دورِ چندضلعی ⇒ float32 ۰..۱ روی شبکهٔ ``height × width`` (همان پوششِ ss × ss)."""
    return fill_polygons(stroke_polygons(poly, closed, width_px), width, height, ss)


def rasterize_mask(path: dict, W: int, H: int, feather_px: float = 0.0, ss: int = 2) -> np.ndarray:
    """مسیرِ قلم ⇒ ماسکِ بوم W × H (float32 ۰..۱)؛ x و y مسیر کسری از W و H اند (جعبه = کلِ بوم).

    ``feather_px`` = سیگمای محوی گاوسی به پیکسل (۰ = لبهٔ تیز، فقط با پوششِ ۲×۲).
    """
    poly = flatten(path, W, H)
    cov = fill_coverage(poly, W, H, ss)
    if feather_px and feather_px > 0:
        cov = cv2.GaussianBlur(cov, (0, 0), float(feather_px), borderType=cv2.BORDER_CONSTANT)
    return np.clip(cov, 0.0, 1.0)
