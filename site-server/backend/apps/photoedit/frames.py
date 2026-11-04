"""«قاب‌اول» (frame-first): هندسهٔ «سند ⇒ بومِ نهایی» و کوچِ پروژه‌های قدیمی (fv=1) به مدلِ جدید (fv=2).

مدلِ جدید: پروژه ``data.fv = 2``؛ لایه‌ها، ماسک‌ها و ضربه‌های روتوش نسبت به **بومِ نهایی** (= خروجیِ مرحلهٔ «قاب») نوشته
می‌شوند. مرحلهٔ قاب = ``perspective ⇐ rotate (turn/straighten/flip) ⇐ crop_rect ⇐ crop_format`` (همه روی سرورِ سایت).
در مدلِ قدیم (fv=1) لایه‌ها نسبت به خودِ عکس (سند) بودند و هندسه فقط یک نمای بصری روی آن بود.

``frame_geometry`` همان ریاضیِ سرور (و ``Geo`` ِ مرورگر) را با دقتِ پیکسلِ صحیحِ opها تکرار می‌کند و ماتریسِ
هموگرافیِ H (پیکسلِ سند ⇒ پیکسلِ بومِ نهایی؛ مختصاتِ پیوسته، لبهٔ بالا-چپِ پیکسل صفر) را می‌دهد. ``migrate_v1_to_v2`` با
همین H لایه‌ها را جابه‌جا می‌کند.
"""
from __future__ import annotations

import copy
import json
import math
import shutil
from pathlib import Path

import numpy as np
from PIL import Image

from . import catalog, ops

FV = 2
MASK_MAX_SIDE = 2048
#: بیشینهٔ ضلعِ نسخهٔ کوچکی که برای پیدا کردنِ پنجرهٔ «خودکار» (smart) از عکس ساخته می‌شود
ENERGY_SIDE = 1280


class Unconvertible(Exception):
    """داده را نمی‌شود با اطمینان کوچ داد — متن برای کاربر/گزارش است."""


# ───────────────────────────── ماتریس‌ها

def _T(tx: float, ty: float) -> np.ndarray:
    return np.array([[1.0, 0.0, tx], [0.0, 1.0, ty], [0.0, 0.0, 1.0]])


def _S(sx: float, sy: float) -> np.ndarray:
    return np.array([[sx, 0.0, 0.0], [0.0, sy, 0.0], [0.0, 0.0, 1.0]])


def _apply(H: np.ndarray, x: float, y: float) -> tuple[float, float]:
    w = H[2, 0] * x + H[2, 1] * y + H[2, 2]
    if abs(w) < 1e-12:
        raise Unconvertible("نگاشتِ هندسه روی یکی از نقطه‌ها تعریف‌شده نیست (پرسپکتیوِ تباه).")
    return (H[0, 0] * x + H[0, 1] * y + H[0, 2]) / w, (H[1, 0] * x + H[1, 1] * y + H[1, 2]) / w


def _jac(H: np.ndarray, x: float, y: float) -> np.ndarray:
    """ژاکوبینِ H در (x, y): [[du/dx, du/dy], [dv/dx, dv/dy]] (پیکسلِ بوم به ازای پیکسلِ سند)."""
    u, v = _apply(H, x, y)
    w = H[2, 0] * x + H[2, 1] * y + H[2, 2]
    return np.array([[(H[0, 0] - u * H[2, 0]) / w, (H[0, 1] - u * H[2, 1]) / w],
                     [(H[1, 0] - v * H[2, 0]) / w, (H[1, 1] - v * H[2, 1]) / w]])


def _homography(src, dst) -> np.ndarray:
    """چهار نقطه ⇐ هموگرافی (مختصاتِ پیوسته؛ مثلِ cv2.getPerspectiveTransform ولی float64)."""
    A, b = [], []
    for (x, y), (u, v) in zip(src, dst):
        A.append([x, y, 1, 0, 0, 0, -u * x, -u * y])
        b.append(u)
        A.append([0, 0, 0, x, y, 1, -v * x, -v * y])
        b.append(v)
    try:
        h = np.linalg.solve(np.array(A, float), np.array(b, float))
    except np.linalg.LinAlgError as exc:
        raise Unconvertible("چهارضلعیِ پرسپکتیو تباه است.") from exc
    return np.array([[h[0], h[1], h[2]], [h[3], h[4], h[5]], [h[6], h[7], 1.0]])


def _f(v, default: float = 0.0) -> float:
    if isinstance(v, bool):
        return default
    try:
        x = float(v)
    except (TypeError, ValueError):
        return default
    return x if math.isfinite(x) else default


# ───────────────────────────── پارامترهای مرحله‌های هندسه (همان که سرور می‌گیرد)

def _persp_params(state: dict) -> dict | None:
    q = state.get("persp")
    if not isinstance(q, dict):
        return None
    try:
        p = catalog.normalize_params("perspective", q, strict=False)
    except catalog.CatalogError:
        return None
    full = {"tl": [0, 0], "tr": [1, 0], "br": [1, 1], "bl": [0, 1]}
    if all(abs(p[k][0] - full[k][0]) < 1e-4 and abs(p[k][1] - full[k][1]) < 1e-4 for k in full):
        return None
    return p


def _rotate_params(state: dict) -> dict | None:
    turn = int(round(_f(state.get("turn")))) % 360
    p = catalog.normalize_params("rotate", {"turn": str(turn if turn in (0, 90, 180, 270) else 0),
                                            "straighten": state.get("straighten"),
                                            "flip_h": state.get("flipH"), "flip_v": state.get("flipV")}, strict=False)
    if int(p["turn"]) == 0 and not p["straighten"] and not p["flip_h"] and not p["flip_v"]:
        return None
    return p


def _crop_params(state: dict) -> dict | None:
    """همان قراردادِ مرورگر: برشِ کامل ⇒ هیچ؛ وگرنه درصد با یک رقم اعشار (Math.round(v*1000)/10)."""
    c = state.get("crop")
    if not isinstance(c, dict):
        return None
    x, y, w, h = _f(c.get("x"), 0.0), _f(c.get("y"), 0.0), _f(c.get("w"), 1.0), _f(c.get("h"), 1.0)
    if x <= 0.0005 and y <= 0.0005 and w >= 0.9995 and h >= 0.9995:
        return None

    def r(v):
        return math.floor(v * 1000 + 0.5) / 10

    return catalog.normalize_params("crop_rect", {"x": r(x), "y": r(y), "w": r(w), "h": r(h)}, strict=False)


def _social_params(state: dict) -> dict | None:
    tools = state.get("tools")
    cf = tools.get("crop_format") if isinstance(tools, dict) else None
    return cf if isinstance(cf, dict) else None


# ───────────────────────────── مرحله‌ها

def geometry_stage(asset_w: int, asset_h: int, state: dict) -> tuple[np.ndarray, tuple[int, int]]:
    """perspective ⇐ rotate/flip ⇐ crop_rect (همان opهای سرور، با گردکردنِ صحیحِ پیکسل) ⇒ (H، (w, h)) ‌— H: سند ⇒ پس از برش."""
    w, h = int(asset_w), int(asset_h)
    H = np.eye(3)
    pp = _persp_params(state)
    if pp:
        pts = [pp[k] for k in ("tl", "tr", "br", "bl")]
        src = [(x * w, y * h) for x, y in pts]

        def dist(a, b):
            return math.hypot((a[0] - b[0]) * w, (a[1] - b[1]) * h)

        ow = (dist(pts[0], pts[1]) + dist(pts[3], pts[2])) / 2
        oh = (dist(pts[0], pts[3]) + dist(pts[1], pts[2])) / 2
        k = min(1.0, 8000 / max(ow, oh, 1))
        ow, oh = max(8, int(round(ow * k))), max(8, int(round(oh * k)))
        H = _homography(src, [(0, 0), (ow, 0), (ow, oh), (0, oh)]) @ H
        w, h = ow, oh
    rp = _rotate_params(state)
    if rp:
        turn = int(rp["turn"])
        if turn == 90:        # PIL ROTATE_90 = پادساعتگرد: (x, y) ⇒ (y, w − x)
            H = np.array([[0.0, 1.0, 0.0], [-1.0, 0.0, w], [0.0, 0.0, 1.0]]) @ H
            w, h = h, w
        elif turn == 270:     # ROTATE_270 = ساعتگرد: (x, y) ⇒ (h − y, x)
            H = np.array([[0.0, -1.0, h], [1.0, 0.0, 0.0], [0.0, 0.0, 1.0]]) @ H
            w, h = h, w
        elif turn == 180:
            H = np.array([[-1.0, 0.0, w], [0.0, -1.0, h], [0.0, 0.0, 1.0]]) @ H
        if rp["straighten"]:
            a = math.radians(rp["straighten"])
            c, s = math.cos(a), math.sin(a)
            iw, ih = ops._inner_rect(w, h, rp["straighten"])
            left, top = (w - iw) // 2, (h - ih) // 2
            # Image.rotate(angle) پادساعتگرد حولِ مرکز، سپس برشِ مرکزیِ iw×ih
            R = _T(w / 2, h / 2) @ np.array([[c, s, 0.0], [-s, c, 0.0], [0.0, 0.0, 1.0]]) @ _T(-w / 2, -h / 2)
            H = _T(-left, -top) @ R @ H
            w, h = iw, ih
        if rp["flip_h"]:
            H = np.array([[-1.0, 0.0, w], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]) @ H
        if rp["flip_v"]:
            H = np.array([[1.0, 0.0, 0.0], [0.0, -1.0, h], [0.0, 0.0, 1.0]]) @ H
    cp = _crop_params(state)
    if cp:
        x0 = max(0, min(w - 8, int(round(w * cp["x"] / 100))))
        y0 = max(0, min(h - 8, int(round(h * cp["y"] / 100))))
        x1 = max(x0 + 8, min(w, x0 + int(round(w * cp["w"] / 100))))
        y1 = max(y0 + 8, min(h, y0 + int(round(h * cp["h"] / 100))))
        if (x0, y0, x1, y1) != (0, 0, w, h):
            H = _T(-x0, -y0) @ H
            w, h = x1 - x0, y1 - y0
    return H, (w, h)


def social_stage(w: int, h: int, params: dict, energy=None, subject=None) -> tuple[np.ndarray, tuple[int, int], dict]:
    """``crop_format`` روی ورودیِ w×h ⇒ (H، (Wf, Hf)، هندسهٔ ops.crop_format_geometry)."""
    p = catalog.normalize_params("crop_format", params, strict=False)
    geo = ops.crop_format_geometry(p, w, h, energy, subject)
    tw, th = geo["size"]
    if geo["mode"] == "cover":
        x0, y0, x1, y1 = geo["box"]
        H = _S(tw / (x1 - x0), th / (y1 - y0)) @ _T(-x0, -y0)
    elif geo.get("view"):                    # «کالا وسطِ قاب»: جای اعشاریِ عکس در بوم (ممکن است بیرون بزند)
        v = geo["view"]
        H = _T(v["left"], v["top"]) @ _S(v["scale"], v["scale"])
    else:
        nw, nh = geo["fg"]
        left, top = geo["pos"]
        H = _T(left, top) @ _S(nw / w, nh / h)
    return H, (tw, th), geo


def frame_stages(asset_w: int, asset_h: int, state: dict, *, energy=None, subject=None) -> dict:
    """همهٔ مرحله‌های قاب: ``{"H", "size", "geo_H", "geo_size", "social": geo|None}``."""
    Hg, (wg, hg) = geometry_stage(asset_w, asset_h, state)
    cf = _social_params(state)
    if cf is None:
        return {"H": Hg, "size": (wg, hg), "geo_H": Hg, "geo_size": (wg, hg), "social": None}
    Hs, size, geo = social_stage(wg, hg, cf, energy, subject)
    return {"H": Hs @ Hg, "size": size, "geo_H": Hg, "geo_size": (wg, hg), "social": geo}


def frame_geometry(asset_w: int, asset_h: int, state: dict, *, energy=None, subject=None) -> tuple[np.ndarray, tuple[int, int]]:
    """هندسهٔ مرحلهٔ قاب برای عکسی ``asset_w × asset_h`` و حالتِ پروژه (``turn, straighten, flipH, flipV, crop, persp,
    tools.crop_format``) ⇒ ``(H، (Wf, Hf))``: H هموگرافیِ ۳×۳ از پیکسلِ سند به پیکسلِ بومِ نهایی.

    ``energy(cw, ch) ⇐ (x, y)`` فقط برای cover/smart بی پنجره (روی تصویرِ پیش از «قابِ شبکه»)؛ نبودنش ⇐ وسط.
    """
    s = frame_stages(asset_w, asset_h, state, energy=energy, subject=subject)
    return s["H"], s["size"]


def is_trivial(state: dict) -> bool:
    """قاب بی‌اثر است: بی پرسپکتیو/چرخش/قرینه/برش/قابِ شبکه (و بی kit_square) ⇒ لایه‌ها همان‌اند."""
    tools = state.get("tools")
    ks = isinstance(tools, dict) and isinstance(tools.get("kit_square"), dict)
    return (_persp_params(state) is None and _rotate_params(state) is None and _crop_params(state) is None
            and _social_params(state) is None and not ks)


# ───────────────────────────── نگاشتِ لایه‌ها

class _Local:
    __slots__ = ("k", "ang", "mirrored", "J")

    def __init__(self, k, ang, mirrored, J):
        self.k, self.ang, self.mirrored, self.J = k, ang, mirrored, J


class _Map:
    """H + اندازهٔ سند و بوم؛ نقطه‌ها و مقیاسِ محلی."""

    def __init__(self, H, w, h, wf, hf):
        self.H, self.w, self.h, self.wf, self.hf = H, float(w), float(h), float(wf), float(hf)

    def pt(self, fx: float, fy: float) -> tuple[float, float]:
        X, Y = _apply(self.H, fx * self.w, fy * self.h)
        return X / self.wf, Y / self.hf

    def local(self, fx: float, fy: float) -> _Local:
        J = _jac(self.H, fx * self.w, fy * self.h)
        det = float(J[0, 0] * J[1, 1] - J[0, 1] * J[1, 0])
        s = math.sqrt(abs(det))
        if s < 1e-9:
            raise Unconvertible("هندسه در یکی از جاهای لایه‌ها فرومی‌ریزد (مقیاسِ صفر).")
        return _Local(s * self.w / self.wf, math.degrees(math.atan2(J[1, 0], J[0, 0])), det < 0, J)


def _wrap(a: float) -> float:
    return round((a + 180.0) % 360.0 - 180.0, 3)


def _new_rot(rot: float, loc: _Local) -> float:
    """چرخشِ تازه (ساعتگرد، درجه): دورانِ تصویرِ محورِ x؛ با قرینه‌شدن (det < 0) علامتِ چرخشِ خودِ لایه برعکس می‌شود."""
    return _wrap(loc.ang - 180.0 - rot if loc.mirrored else rot + loc.ang)


def _r5(v: float) -> float:
    return round(float(v), 5)


def _xy(v, default):
    if isinstance(v, (list, tuple)) and len(v) >= 2:
        return _f(v[0], default[0]), _f(v[1], default[1])
    return default


def _scale_keys(d, keys, k) -> None:
    if isinstance(d, dict):
        for key in keys:
            if key in d:
                d[key] = _r5(_f(d[key]) * k)


def _scale_fx(fx, k) -> None:
    """fx (سایه/لبه/درخشش): همهٔ طول‌ها کسری از پهنای بوم ⇒ ×k."""
    if not isinstance(fx, dict):
        return
    _scale_keys(fx.get("shadow"), ("blur", "dx", "dy"), k)
    _scale_keys(fx.get("stroke"), ("w",), k)
    _scale_keys(fx.get("glow"), ("blur", "size"), k)


def _map_mask(m, mp: _Map, paint_ids: set) -> dict | None:
    if not isinstance(m, dict):
        return m
    t = m.get("type")
    out = dict(m)
    if t == "paint":
        if m.get("id"):
            paint_ids.add(str(m["id"]))
        return out
    if t == "linear":
        p0 = _xy(m.get("p0"), (0.5, 0.0))
        p1 = _xy(m.get("p1"), (0.5, 1.0))
        out["p0"] = [_r5(v) for v in mp.pt(*p0)]
        out["p1"] = [_r5(v) for v in mp.pt(*p1)]
    elif t == "radial":
        c = _xy(m.get("c"), (0.5, 0.5))
        rx, ry = _f(m.get("rx"), 0.25), _f(m.get("ry"), 0.25)
        loc = mp.local(*c)
        out["c"] = [_r5(v) for v in mp.pt(*c)]
        if abs(loc.ang % 180.0 - 90.0) < 45.0:     # نزدیکِ ۹۰°: محورهای بیضی جابه‌جا می‌شوند
            rx, ry = ry, rx
        out["rx"], out["ry"] = _r5(rx * loc.k), _r5(ry * loc.k)
    return out


def _map_layer(layer: dict, mp: _Map, paint_ids: set) -> dict:
    out = copy.deepcopy(layer)
    t = out.get("type")
    if "mask" in out:
        out["mask"] = _map_mask(out.get("mask"), mp, paint_ids)
    if t in ("image", "text", "shape"):
        cx, cy = _f(out.get("cx"), 0.5), _f(out.get("cy"), 0.5)
        loc = mp.local(cx, cy)
        nx, ny = mp.pt(cx, cy)
        out["cx"], out["cy"] = _r5(nx), _r5(ny)
        out["rot"] = _new_rot(_f(out.get("rot"), 0.0), loc)
        k = loc.k
        if t == "image":
            out["w"] = _r5(_f(out.get("w"), 0.25) * k)
            if loc.mirrored:      # عکسِ لایه هم مثلِ نمای قدیمی قرینه می‌شود (متن نه: خوانا می‌ماند)
                out["flip_h"] = not bool(out.get("flip_h"))
        elif t == "text":
            out["size"] = _r5(_f(out.get("size"), 0.06) * k)
            out["width"] = _r5(_f(out.get("width"), 0.0) * k)
            tile = out.get("tile")
            if isinstance(tile, dict):
                tile["angle"] = round(((_f(tile.get("angle"), 28.0) + loc.ang + 90.0) % 180.0) - 90.0, 3)
            # استروک، سایه و کادرِ متن نسبت به اندازهٔ فونت‌اند ⇒ دست نمی‌خورند
        else:
            out["w"] = _r5(_f(out.get("w"), 0.3) * k)
            out["h"] = _r5(_f(out.get("h"), 0.15) * k)
            _scale_keys(out.get("stroke"), ("w",), k)
        _scale_fx(out.get("fx"), k)
    elif t == "redeye":
        eyes = []
        for e in out.get("eyes") if isinstance(out.get("eyes"), list) else []:
            if not isinstance(e, dict):
                continue
            ex, ey = _f(e.get("x"), 0.5), _f(e.get("y"), 0.5)
            loc = mp.local(ex, ey)
            nx, ny = mp.pt(ex, ey)
            e2 = dict(e)
            e2["x"], e2["y"], e2["r"] = _r5(nx), _r5(ny), _r5(_f(e.get("r"), 0.012) * loc.k)
            eyes.append(e2)
        out["eyes"] = eyes
    elif t == "retouch":
        strokes = []
        for s in out.get("strokes") if isinstance(out.get("strokes"), list) else []:
            if not isinstance(s, dict):
                continue
            pts = [p for p in (s.get("pts") if isinstance(s.get("pts"), list) else [])
                   if isinstance(p, (list, tuple)) and len(p) >= 2]
            if not pts:
                continue
            mx = sum(_f(p[0], 0.5) for p in pts) / len(pts)
            my = sum(_f(p[1], 0.5) for p in pts) / len(pts)
            loc = mp.local(mx, my)
            s2 = dict(s)
            s2["pts"] = [[_r5(v) for v in mp.pt(_f(p[0], 0.5), _f(p[1], 0.5))] for p in pts]
            s2["r"] = _r5(_f(s.get("r"), 0.02) * loc.k)
            # بردارِ منبع (پیکسلِ سند): جای منبعِ مرکزِ ضربه هم از H رد می‌شود (برای نگاشتِ خطی همان J·v است؛ زیرِ پرسپکتیو
            # دقیقاً مرکزِ ضربه را درست می‌گذارد)
            vx, vy = _f(s.get("dx")) * mp.w, _f(s.get("dy")) * mp.h
            x1, y1 = _apply(mp.H, mx * mp.w, my * mp.h)
            x2, y2 = _apply(mp.H, mx * mp.w + vx, my * mp.h + vy)
            s2["dx"], s2["dy"] = _r5((x2 - x1) / mp.wf), _r5((y2 - y1) / mp.hf)
            strokes.append(s2)
        out["strokes"] = strokes
    return out


# ───────────────────────────── ماسک‌های رنگ‌آمیزی

def v1_mask_path(project_dir: Path, mid: str) -> Path:
    return Path(project_dir) / f"v1-mask-{mid}.png"


def _warp_mask(src: Path, H: np.ndarray, w: int, h: int, wf: int, hf: int) -> np.ndarray | None:
    """PNG ِ خاکستریِ ماسکِ قدیمی (نسبی به سند) ⇒ آرایهٔ uint8 نسبی به بومِ نهایی (حداکثر ۲۰۴۸ پیکسل)."""
    import cv2

    try:
        with Image.open(src) as im:
            g = np.asarray(im.convert("L"))
    except Exception:  # noqa: BLE001
        return None
    sh, sw = g.shape
    k = min(1.0, MASK_MAX_SIDE / max(wf, hf))
    mw, mh = max(1, int(round(wf * k))), max(1, int(round(hf * k)))

    def matrix(sw_, sh_):
        return _T(-0.5, -0.5) @ _S(mw / wf, mh / hf) @ H @ _S(w / sw_, h / sh_) @ _T(0.5, 0.5)

    M = matrix(sw, sh)
    J = _jac(M, sw / 2, sh / 2)
    scale = math.sqrt(abs(float(J[0, 0] * J[1, 1] - J[0, 1] * J[1, 0])))
    if 0 < scale < 0.5:    # کوچک‌کردنِ شدید ⇒ اول با AREA کوچک کن تا دندانه نیاید
        f = max(scale * 2, 0.03)
        g = cv2.resize(g, (max(1, int(round(sw * f))), max(1, int(round(sh * f)))), interpolation=cv2.INTER_AREA)
        sh, sw = g.shape
        M = matrix(sw, sh)
    return cv2.warpPerspective(g, M, (mw, mh), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)


def _png_bytes(arr: np.ndarray) -> bytes:
    import io

    buf = io.BytesIO()
    Image.fromarray(arr, "L").save(buf, "PNG", optimize=True)
    return buf.getvalue()


def restore_v1_masks(project_dir: Path, mask_ids) -> int:
    """ماسک‌های بازنویسی‌شده را از ``v1-mask-<id>.png`` برمی‌گرداند (شکستِ ذخیره پس از کوچ)."""
    n = 0
    for mid in mask_ids or []:
        src = v1_mask_path(project_dir, mid)
        if src.is_file():
            ops.save_bytes(Path(project_dir) / f"mask-{mid}.png", src.read_bytes())
            n += 1
    return n


# ───────────────────────────── تبدیلِ kit_square و پنجرهٔ «خودکار»

def _convert_kit_square(data: dict, notes: list) -> bool:
    """``tools.kit_square`` (گره‌ی قدیمی) ⇒ ``tools.crop_format`` {custom، contain، سفید، حاشیه}."""
    tools = data.get("tools")
    if not isinstance(tools, dict) or not isinstance(tools.get("kit_square"), dict):
        return False
    ks = catalog.normalize_params("kit_square", tools.pop("kit_square"), strict=False)
    if isinstance(tools.get("crop_format"), dict):
        notes.append("«قابِ مربعِ فروشگاه» کنار گذاشته شد چون «قالبِ شبکه‌ها» هم روشن بود (قابِ شبکه‌ها آخر اجرا می‌شد)")
        return True
    tools["crop_format"] = catalog.normalize_params(
        "crop_format", {"format": "custom", "size": ks["long_edge"], "fit": "contain", "focus": "center",
                        "fill": "white", "padding": ks["padding"]}, strict=False)
    notes.append("«قابِ مربعِ فروشگاه» به «قالبِ شبکه‌ها ⇐ مربعِ دلخواه، جا دادن، سفید» تبدیل شد")
    return True


def _geometry_image(asset_path: Path, state: dict) -> Image.Image:
    """نسخهٔ کوچکِ عکس پس از پرسپکتیو/چرخش/برش (پیش از قابِ شبکه) — برای پیدا کردنِ پنجرهٔ «خودکار»."""
    img = ops.load(asset_path)
    img.thumbnail((ENERGY_SIDE, ENERGY_SIDE), Image.Resampling.LANCZOS)
    ctx = {"notes": []}
    pp = _persp_params(state)
    if pp:
        img = ops.op_perspective(img, pp, ctx)
    rp = _rotate_params(state)
    if rp:
        img = ops.op_rotate(img, rp, ctx)
    cp = _crop_params(state)
    if cp:
        img = ops.op_crop_rect(img, cp, ctx)
    return img


def _fix_smart_window(data: dict, asset_path, notes: list) -> bool:
    """crop_format با cover + focus=smart و بی window ⇒ پنجرهٔ صریح (روی عکسِ پس از هندسه)، تا پیش‌نمایش = خروجی."""
    cf = _social_params(data)
    if cf is None:
        return False
    p = catalog.normalize_params("crop_format", cf, strict=False)
    if p["fit"] != "cover" or p["focus"] != "smart" or len(p["window"]) == 4:
        return False
    if asset_path is None or not Path(asset_path).is_file():
        raise Unconvertible("فایلِ عکسِ اصل برای پیدا کردنِ جای «سوژه (خودکار)» در دسترس نیست.")
    img = _geometry_image(Path(asset_path), data)
    w, h = img.size
    geo = ops.crop_format_geometry(p, w, h, lambda cw, ch: ops._energy_offset(img, cw, ch))
    x0, y0, x1, y1 = geo["box"]
    p["window"] = catalog.normalize_window([x0 / w, y0 / h, (x1 - x0) / w, (y1 - y0) / h])
    if len(p["window"]) != 4:
        raise Unconvertible("پنجرهٔ «سوژه (خودکار)» معتبر نشد.")
    data["tools"]["crop_format"] = p
    notes.append("جای «سوژه (خودکار)» برای قالبِ شبکه‌ها به‌صورتِ پنجرهٔ صریح ثبت شد")
    return True


# ───────────────────────────── کوچ

def _fv(data) -> int:
    try:
        return int(data.get("fv") or 1) if isinstance(data, dict) else 1
    except (TypeError, ValueError):
        return 1


def _report(**kw) -> dict:
    return {"already": False, "changed": False, "stamped": False, "trivial": False, "notes": [], "layers": 0,
            "masks": 0, "mask_ids": [], "frame": None, "error": ""} | kw


def migrate_v1_to_v2(data, asset_w: int, asset_h: int, project_dir, asset_path=None, *, write_masks: bool = True):
    """داده‌ی پروژهٔ fv=1 ⇒ ``(داده‌ی fv=2، گزارش)``. هرگز استثنا نمی‌اندازد.

    * ``fv ≥ 2`` ⇒ دست‌نخورده (ایدمپوتنت). قابِ بی‌اثر ⇒ فقط ``fv=2`` زده می‌شود.
    * وگرنه با H ِ ``frame_geometry``: ``cx, cy`` از H؛ طول‌هایی که کسری از پهنای بوم‌اند (image.w، shape.w/h/stroke.w،
      text.size/width، fx، radial.rx/ry، r ِ روتوش/چشم) ×k با ``k = مقیاسِ محلی·W/Wf``؛ ``rot`` += چرخشِ محورِ x؛ قرینه ⇒
      flip_h ِ لایه‌های تصویر؛ ماسک‌های linear/radial و ضربه‌های روتوش (pts، r، dx/dy)؛ ماسک‌های رنگ‌آمیزی با
      ``cv2.warpPerspective`` دوباره ساخته می‌شوند (اصل در ``v1-mask-<id>.png``).
    * ``tools.kit_square`` ⇒ ``tools.crop_format`` (custom/contain/white/padding)؛ cover+smart ⇒ ``window`` ِ صریح روی عکسِ
      پس از هندسه (نیازمندِ ``asset_path``).
    * هرجا که با اطمینان نشود ⇒ داده بی‌تغییر، ``fv`` زده نمی‌شود، ``report["error"]`` دلیل را دارد.
    * ``write_masks=False`` (dry-run): فایلی نوشته نمی‌شود.
    """
    if not isinstance(data, dict):
        return data, _report(error="دادهٔ پروژه شیء نیست", notes=["دادهٔ پروژه شیء نیست؛ دست نخورد"])
    if _fv(data) >= FV:
        return data, _report(already=True, stamped=True)
    written: list[str] = []
    try:
        new = copy.deepcopy(data)
        if is_trivial(new):
            new["fv"] = FV
            return new, _report(changed=True, stamped=True, trivial=True)
        W, Hh = int(asset_w or 0), int(asset_h or 0)
        if W < 1 or Hh < 1:
            raise Unconvertible("اندازهٔ عکسِ اصل معلوم نیست.")
        notes: list[str] = []
        _convert_kit_square(new, notes)
        _fix_smart_window(new, asset_path, notes)
        st = frame_stages(W, Hh, new)
        H, (wf, hf) = st["H"], st["size"]
        if st["social"] and st["social"].get("approx"):
            raise Unconvertible("جای «سوژه (خودکار)» معلوم نشد.")
        mp = _Map(H, W, Hh, wf, hf)
        paint_ids: set[str] = set()
        layers = new.get("layers")
        n_layers = 0
        if isinstance(layers, list):
            mapped = []
            for layer in layers:
                if isinstance(layer, dict):
                    mapped.append(_map_layer(layer, mp, paint_ids))
                    n_layers += 1
                else:
                    mapped.append(layer)
            new["layers"] = mapped
            try:
                json.dumps(mapped, allow_nan=False)
            except (ValueError, TypeError) as exc:
                raise Unconvertible("نگاشتِ لایه‌ها عددِ نامعتبر داد (هندسهٔ تباه).") from exc
        # ماسک‌های رنگ‌آمیزی: همه محاسبه می‌شوند، بعد نوشته (تا نیمه‌کاره نماند)
        pdir = Path(project_dir) if project_dir is not None else None
        warped: dict[str, np.ndarray] = {}
        for mid in sorted(paint_ids):
            if pdir is None:
                continue
            cur, old = pdir / f"mask-{mid}.png", v1_mask_path(pdir, mid)
            src = old if old.is_file() else cur
            if not src.is_file():
                notes.append(f"فایلِ ماسکِ «{mid}» پیدا نشد (همان‌طور می‌ماند)")
                continue
            arr = _warp_mask(src, H, W, Hh, wf, hf)
            if arr is None:
                notes.append(f"ماسکِ «{mid}» خوانده نشد (همان‌طور می‌ماند)")
                continue
            warped[mid] = arr
        if write_masks and pdir is not None:
            for mid, arr in warped.items():
                cur, old = pdir / f"mask-{mid}.png", v1_mask_path(pdir, mid)
                if not old.is_file() and cur.is_file():
                    shutil.copyfile(cur, old)
                ops.save_bytes(cur, _png_bytes(arr))
                written.append(mid)
        new["fv"] = FV
        rep = _report(changed=True, stamped=True, notes=notes, layers=n_layers, masks=len(warped),
                      mask_ids=sorted(warped), frame={"size": [wf, hf], "mode": (st["social"] or {}).get("mode")})
        return new, rep
    except Unconvertible as exc:
        _rollback(project_dir, written)
        return data, _report(error=str(exc), notes=[f"کوچِ قاب‌اول انجام نشد: {exc}"])
    except Exception as exc:  # noqa: BLE001 — دادهٔ عجیب هرگز نباید پروژه را بشکند
        _rollback(project_dir, written)
        return data, _report(error=f"{type(exc).__name__}: {exc}", notes=["کوچِ قاب‌اول انجام نشد: دادهٔ پروژه غیرمنتظره است"])


def _rollback(project_dir, written) -> None:
    if project_dir is not None and written:
        try:
            restore_v1_masks(Path(project_dir), written)
        except Exception:  # noqa: BLE001
            pass
