"""کارهای چندعکسی (دورِ ۸): شیتِ تماس، ادغامِ HDR، پانوراما، پردازشگرِ چند اندازه، و اجرای اکشن روی یک عکس.

همه روی سرورِ سایت (Pillow + OpenCV) و بی وابستگیِ تازه‌اند؛ سقف‌ها طوری‌اند که هر درخواست زیرِ حدِ ۶۰ ثانیهٔ nginx تمام شود
و حافظهٔ مشترکِ سرور (۴ گیگ) نترکد. نتیجهٔ شیت/HDR/پانوراما/اکشن یک عکسِ تازه در کتابخانه است؛ نتیجهٔ پردازشگر یک فایلِ zip.
"""
from __future__ import annotations

import io
import math
import re
import uuid
import zipfile

import cv2
import numpy as np
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image, ImageOps

from . import layers as layers_mod
from . import ops, services
from .designer import render
from .models import PhotoAsset

MAX_SHEET = 60
MAX_HDR = 7
MAX_PANO = 6
HDR_SIDE = 1800
PANO_SIDE = 1300
MAX_PROC_ASSETS = 8
MAX_PROC_SIZES = 6
PROC_SIDE_MAX = 4096
ACTION_SIDE = 4096


class MultiError(services.PhotoError):
    """خطایی که متنش برای کاربر است."""


def _assets(store, ids, lo: int, hi: int, what: str) -> list[PhotoAsset]:
    try:
        want = [int(i) for i in dict.fromkeys(ids or [])]
    except (TypeError, ValueError):
        raise MultiError("شمارهٔ عکس‌ها درست نیست.") from None
    if len(want) < lo:
        raise MultiError(f"برای {what} دست‌کم {lo} عکس انتخاب کنید.")
    if len(want) > hi:
        raise MultiError(f"برای {what} حداکثر {hi} عکس می‌شود.")
    rows = {a.pk: a for a in PhotoAsset.objects.filter(store=store, pk__in=want)}
    if len(rows) != len(want):
        raise MultiError("بعضی از عکس‌ها در این فروشگاه پیدا نشد.")
    return [rows[i] for i in want]


def _small(asset: PhotoAsset, side: int) -> Image.Image:
    img = services.preview_source(asset)
    img.thumbnail((side, side), Image.Resampling.LANCZOS)
    return img


def _flat(img: Image.Image, bg=(255, 255, 255)) -> Image.Image:
    if img.mode == "RGBA":
        out = Image.new("RGB", img.size, bg)
        out.paste(img, mask=img.getchannel("A"))
        return out
    return img.convert("RGB")


def _store_image(store, user, img: Image.Image, title: str, fmt: str = "jpeg", quality: int = 92) -> PhotoAsset:
    buf = io.BytesIO()
    if fmt == "png":
        img.save(buf, "PNG", optimize=img.width * img.height < 6_000_000)
        name = "result.png"
    else:
        _flat(img).save(buf, "JPEG", quality=quality, optimize=True)
        name = "result.jpg"
    data = buf.getvalue()
    return services.add_upload(store, user, SimpleUploadedFile(name, data, content_type="image/png" if fmt == "png" else "image/jpeg"), title)


def _hex(c: str, default=(255, 255, 255)) -> tuple[int, int, int]:
    return tuple(int(c[i:i + 2], 16) for i in (1, 3, 5)) if isinstance(c, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", c) else default


# ───────────────────────────── شیتِ تماس

def _label_tile(text: str, cell: int, color=(55, 65, 81)) -> Image.Image | None:
    """نامِ عکس با شکل‌دهیِ درستِ فارسی (همان موتورِ متنِ لایه‌ها)."""
    from . import textlayer

    text = (text or "").strip()
    if not text:
        return None
    lay = layers_mod.normalize_layers([{"id": "base", "type": "base"}, {
        "id": "t1", "type": "text", "text": text[:34], "size": 0.07, "color": "#%02x%02x%02x" % color, "font": "vazirmatn", "weight": 500,
        "align": "center", "dir": "auto", "width": 0.94, "stroke": None, "shadow": None, "box": None}])[1]
    r = textlayer.render_text(lay, cell)
    return r[0] if r else None


def contact_sheet(store, user, ids, cols: int = 5, cell: int = 300, labels: bool = True, bg: str = "#ffffff") -> PhotoAsset:
    items = _assets(store, ids, 1, MAX_SHEET, "شیتِ تماس")
    cols = max(1, min(10, int(cols or 5)))
    cols = min(cols, len(items))
    cell = max(100, min(600, int(cell or 300)))
    gap = max(4, cell // 25)
    label_h = int(cell * 0.2) if labels else 0
    rows = math.ceil(len(items) / cols)
    W = gap + cols * (cell + gap)
    H = gap + rows * (cell + label_h + gap)
    if W * H > 36_000_000:
        raise MultiError("شیتِ تماس خیلی بزرگ می‌شود؛ ستون یا اندازهٔ خانه را کم کنید.")
    sheet = Image.new("RGB", (W, H), _hex(bg))
    lum = sum(_hex(bg)) / 3
    lab_color = (55, 65, 81) if lum > 128 else (229, 231, 235)
    for i, a in enumerate(items):
        r, c = divmod(i, cols)
        x0 = gap + c * (cell + gap)
        y0 = gap + r * (cell + label_h + gap)
        try:
            im = _flat(_small(a, cell * 2), _hex(bg))
        except services.PhotoError:
            continue
        im.thumbnail((cell, cell), Image.Resampling.LANCZOS)
        sheet.paste(im, (x0 + (cell - im.width) // 2, y0 + (cell - im.height) // 2))
        if labels:
            tile = _label_tile(a.title, cell, lab_color)
            if tile is not None:
                tile.thumbnail((cell, label_h), Image.Resampling.LANCZOS)
                sheet.paste(tile, (x0 + (cell - tile.width) // 2, y0 + cell + (label_h - tile.height) // 2), tile)
    return _store_image(store, user, sheet, f"شیتِ تماس ({len(items)} عکس)", "jpeg", 90)


# ───────────────────────────── HDR (ادغامِ نوردهی) و پانوراما

def _bgr(img: Image.Image) -> np.ndarray:
    return cv2.cvtColor(np.asarray(_flat(img)), cv2.COLOR_RGB2BGR)


def hdr_merge(store, user, ids) -> PhotoAsset:
    """چند عکسِ هم‌کادر با نوردهیِ متفاوت ⇒ یک عکسِ متعادل (ادغامِ نوردهی Mertens، با ترازِ جزئیِ لرزشِ دست)."""
    items = _assets(store, ids, 2, MAX_HDR, "ادغامِ HDR")
    imgs = [_small(a, HDR_SIDE) for a in items]
    w0, h0 = imgs[0].size
    for im in imgs[1:]:
        if abs(im.width / im.height - w0 / h0) > 0.03:
            raise MultiError("عکس‌های ادغامِ HDR باید یک کادر (یک نسبتِ تصویر) داشته باشند؛ همان صحنه را با نوردهیِ متفاوت بگیرید.")
    imgs = [im if im.size == (w0, h0) else im.resize((w0, h0), Image.Resampling.LANCZOS) for im in imgs]
    arr = [_bgr(im) for im in imgs]
    try:
        cv2.createAlignMTB().process(arr, arr)
        fused = cv2.createMergeMertens().process(arr)
    except cv2.error as exc:
        raise MultiError(f"ادغام ممکن نشد: {str(exc)[:120]}") from exc
    out = np.clip(fused * 255.0 + 0.5, 0, 255).astype(np.uint8)
    img = Image.fromarray(cv2.cvtColor(out, cv2.COLOR_BGR2RGB))
    return _store_image(store, user, img, f"ادغامِ HDR ({len(items)} نوردهی)", "jpeg", 92)


_PANO_ERR = {
    1: "عکس‌ها برای دوختن کافی یا هم‌پوشان نیستند؛ هر دو عکسِ کناری باید ۲۰ تا ۴۰٪ منظرهٔ مشترک داشته باشند.",
    2: "نقطه‌های مشترکِ کافی میانِ عکس‌ها پیدا نشد (منظره خیلی صاف/تکراری است یا هم‌پوشانی کم است).",
    3: "تنظیمِ زاویهٔ دوربین میانِ عکس‌ها جواب نداد؛ عکس‌ها را با ترتیبِ چپ به راست و بی‌حرکتِ زیاد بگیرید.",
}


def _crop_black(a: np.ndarray) -> np.ndarray:
    """حاشیهٔ سیاهِ کنار پانوراما را می‌برد: اول جعبهٔ پیرامونِ نقاطِ روشن، بعد هر لبه‌ای که بیش از ۲٪ سیاه دارد کمی کوتاه می‌شود."""
    g = cv2.cvtColor(a, cv2.COLOR_BGR2GRAY)
    ys, xs = np.where(g > 6)
    if len(xs) == 0:
        return a
    x0, x1, y0, y1 = int(xs.min()), int(xs.max()) + 1, int(ys.min()), int(ys.max()) + 1
    mask = g > 6
    for _ in range(400):
        if x1 - x0 < 8 or y1 - y0 < 8:
            break
        sub = mask[y0:y1, x0:x1]
        top, bot = (~sub[0]).mean(), (~sub[-1]).mean()
        lef, rig = (~sub[:, 0]).mean(), (~sub[:, -1]).mean()
        worst = max(top, bot, lef, rig)
        if worst <= 0.02:
            break
        if worst == top:
            y0 += 1
        elif worst == bot:
            y1 -= 1
        elif worst == lef:
            x0 += 1
        else:
            x1 -= 1
    return a[y0:y1, x0:x1]


def panorama(store, user, ids) -> PhotoAsset:
    items = _assets(store, ids, 2, MAX_PANO, "پانوراما")
    arr = [_bgr(_small(a, PANO_SIDE)) for a in items]
    try:
        st = cv2.Stitcher_create(cv2.Stitcher_PANORAMA)
        code, pano = st.stitch(arr)
    except cv2.error as exc:
        raise MultiError(f"دوختنِ پانوراما ممکن نشد: {str(exc)[:120]}") from exc
    if code != 0 or pano is None:
        raise MultiError(_PANO_ERR.get(int(code), "دوختنِ پانوراما موفق نبود."))
    pano = _crop_black(pano)
    img = Image.fromarray(cv2.cvtColor(pano, cv2.COLOR_BGR2RGB))
    return _store_image(store, user, img, f"پانوراما ({len(items)} عکس)", "jpeg", 92)


# ───────────────────────────── پردازشگرِ تصویر (چند اندازه)

PROC_FORMATS = {"jpeg": ("jpg", "JPEG"), "png": ("png", "PNG"), "webp": ("webp", "WEBP")}


def _fit(img: Image.Image, w: int, h: int, how: str, no_upscale: bool) -> Image.Image:
    sw, sh = img.size
    if how == "cover" and w > 0 and h > 0:
        k = max(w / sw, h / sh)
        if no_upscale:
            k = min(k, 1.0)
        r = img.resize((max(1, round(sw * k)), max(1, round(sh * k))), Image.Resampling.LANCZOS)
        cw, ch = min(w, r.width), min(h, r.height)
        return r.crop(((r.width - cw) // 2, (r.height - ch) // 2, (r.width - cw) // 2 + cw, (r.height - ch) // 2 + ch))
    if how == "width" and w > 0:
        k = w / sw
    elif how == "height" and h > 0:
        k = h / sh
    else:
        k = min(w / sw if w > 0 else 1e9, h / sh if h > 0 else 1e9)
    if no_upscale:
        k = min(k, 1.0)
    return img.resize((max(1, round(sw * k)), max(1, round(sh * k))), Image.Resampling.LANCZOS)


def processor_zip(store, ids, sizes: list[dict], fmt: str = "jpeg", quality: int = 90, how: str = "contain", no_upscale: bool = True) -> tuple[bytes, int]:
    """هر عکس در هر اندازه ⇒ یک فایل در zip. sizes = [{w, h}] (۰ = آزاد). ⇒ (بایت‌های zip، تعدادِ فایل)."""
    items = _assets(store, ids, 1, MAX_PROC_ASSETS, "پردازشگرِ تصویر")
    if fmt not in PROC_FORMATS:
        raise MultiError("قالبِ خروجی باید JPEG، PNG یا WebP باشد.")
    if how not in ("contain", "cover", "width", "height"):
        raise MultiError("روشِ جاگذاری درست نیست.")
    clean = []
    for s in sizes or []:
        try:
            w, h = int(s.get("w") or 0), int(s.get("h") or 0)
        except (TypeError, ValueError, AttributeError):
            raise MultiError("اندازه‌ها درست نیست.") from None
        if not (16 <= max(w, h) <= PROC_SIDE_MAX) or min(w, h) < 0 or (how == "cover" and (w <= 0 or h <= 0)):
            raise MultiError(f"هر اندازه باید بینِ ۱۶ و {PROC_SIDE_MAX} پیکسل باشد" + (" و در «پرکردنِ قاب» هم پهنا هم ارتفاع لازم است." if how == "cover" else "."))
        clean.append((w, h))
    clean = list(dict.fromkeys(clean))
    if not clean:
        raise MultiError("دست‌کم یک اندازه بنویسید.")
    if len(clean) > MAX_PROC_SIZES:
        raise MultiError(f"حداکثر {MAX_PROC_SIZES} اندازه در یک بار.")
    ext, pil = PROC_FORMATS[fmt]
    buf = io.BytesIO()
    n = 0
    seen: set[str] = set()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as z:
        for idx, a in enumerate(items, 1):
            try:
                src = ops.load(services.abs_path(a.original))
            except ops.OpError as exc:
                raise MultiError(f"«{a.title}»: {exc}") from exc
            if fmt == "jpeg":
                src = _flat(src)
            stem = re.sub(r"[^\w\-]+", "-", a.title or "photo", flags=re.UNICODE).strip("-")[:40] or "photo"
            for (w, h) in clean:
                out = _fit(src, w, h, how, no_upscale)
                b = io.BytesIO()
                if pil == "JPEG":
                    out.save(b, "JPEG", quality=max(40, min(98, int(quality))), optimize=True)
                elif pil == "PNG":
                    out.save(b, "PNG", optimize=out.width * out.height < 4_000_000)
                else:
                    out.save(b, "WEBP", quality=max(40, min(98, int(quality))), method=4)
                name = f"{idx:02d}-{stem}-{out.width}x{out.height}.{ext}"
                while name in seen:
                    name = name.replace(f".{ext}", f"-{uuid.uuid4().hex[:3]}.{ext}")
                seen.add(name)
                z.writestr(name, b.getvalue())
                n += 1
            del src
    return buf.getvalue(), n


# ───────────────────────────── اکشن روی یک عکس (سمتِ سرور)

_PORTABLE = {"text", "shape", "adjust"}
_RESERVED = {"layers", "fv", "liquify"}
_NO_PATCH = {"id", "type", "src", "parent", "path"}


def _nid() -> str:
    return "a" + uuid.uuid4().hex[:9]


def apply_ops(state: dict, ops_: list[dict], added: dict) -> dict:
    """همتای پایتونیِ ``applyOps`` ِ مرورگر (pro/actions.ts): set/add/patch/remove روی حالتِ ادیتور."""
    import copy

    s = copy.deepcopy(state)
    for o in ops_:
        kind = o.get("op")
        if kind == "set":
            if o.get("key") not in _RESERVED:
                s[o["key"]] = copy.deepcopy(o.get("value"))
        elif kind == "add":
            lay = copy.deepcopy(o.get("layer") or {})
            is_logo = lay.get("type") == "image" and isinstance(lay.get("src"), dict) and lay["src"].get("kind") == "logo"
            if lay.get("type") not in _PORTABLE and not is_logo:
                continue
            lay["id"] = _nid()
            lay.pop("parent", None)
            added[f"@{len(added)}"] = lay["id"]
            s["layers"].append(lay)
        elif kind == "patch":
            lid = "base" if o.get("ref") == "base" else added.get(o.get("ref"))
            tgt = next((l for l in s["layers"] if l.get("id") == lid), None) if lid else None
            if tgt is None:
                continue
            for k, v in (o.get("set") or {}).items():
                if k not in _NO_PATCH:
                    tgt[k] = copy.deepcopy(v)
        elif kind == "remove":
            lid = added.get(o.get("ref"))
            if lid:
                s["layers"] = [l for l in s["layers"] if l.get("id") != lid]
    return s


def action_state(data: dict) -> dict:
    state = render.default_state()
    added: dict = {}
    for st in (data or {}).get("steps") or []:
        state = apply_ops(state, st.get("ops") or [], added)
    return state


def run_action(store, user, asset: PhotoAsset, data: dict, name: str) -> PhotoAsset:
    """اکشنِ ذخیره‌شده را روی یک عکسِ کتابخانه اجرا می‌کند ⇒ عکسِ تازه (عکسِ اصل دست‌نخورده می‌ماند)."""
    state = action_state(data)
    try:
        src = ops.load(services.abs_path(asset.original))
    except ops.OpError as exc:
        raise MultiError(f"«{asset.title}»: {exc}") from exc
    src.thumbnail((ACTION_SIDE, ACTION_SIDE), Image.Resampling.LANCZOS)
    frame, _n = render.render_frame(asset, state, src=src)
    if render.has_overlays(state):
        ctx = services.server_ctx(store)
        ctx["scale"] = (frame.width / asset.width) if asset.width else 1.0
        norm = layers_mod.normalize_layers(state["layers"], store=store, base="one")
        final = layers_mod.compose(frame, norm, ctx, project=0)
    else:
        final = frame
    o = state.get("out") or {}
    le = int(o.get("long_edge") or 0)
    if le > 0 and max(final.size) > le:
        final = final.copy()
        final.thumbnail((le, le), Image.Resampling.LANCZOS)
    fmt = "png" if (o.get("format") == "png" or final.mode == "RGBA") else "jpeg"
    q = max(40, min(98, int(o.get("quality") or 92)))
    return _store_image(store, user, final, f"{asset.title} — {name}"[:200], fmt, q)
