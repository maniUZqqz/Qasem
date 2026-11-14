"""«مرجع» برای ایده‌پردازیِ تامنیل: یک تصویرِ نمونه (پینِ پینترست، پوسترِ فیلم، یا هر عکسی که شما می‌پسندید) ⇒ رنگ، حال‌وهوا، چیدمان ⇒ ایده‌هایی که با همان حس ساخته می‌شوند.

سه راهِ آوردنِ مرجع (هیچ‌کدام وارد خروجیِ تامنیل نمی‌شود؛ فقط «تحلیل» می‌شود):

* ``upload``  عکسی که خودتان بارگذاری می‌کنید.
* ``url``     نشانیِ یک عکس، یا نشانیِ صفحه‌ای مثلِ **پینِ پینترست** (تصویرِ pin از ``og:image`` ِ همان صفحه خوانده می‌شود؛ همان چیزی که پیش‌نمایشِ پیوند نشان می‌دهد).
* ``commons`` جست‌وجوی **پوسترهای فیلمِ آزاد** در ویکی‌مدیا کامنز؛ فقط پرونده‌هایی که مجوزشان آزاد است (مالکیتِ عمومی، CC0، CC BY، CC BY-SA)
  پیشنهاد می‌شوند و نامِ پدیدآور و مجوز کنارِ هر نتیجه ثبت می‌شود.

پینترست API ِ عمومیِ جست‌وجو ندارد و ورودِ بی‌حساب را نمی‌پذیرد؛ برای همین «جست‌وجوی پینترست» نداریم و صادقانه همین را در پنل می‌گوییم.

تحلیل کاملاً محلی و قطعی است (Pillow + numpy؛ بدونِ هوش مصنوعی و بدونِ GPU):
    palette   پنج رنگِ غالب با سهم + رنگِ اصلی/دوم/تأکید
    mood      یکی از ``palette.MOODS`` (تیره، روشن، سینمایی، نئونی، لوکس، گرم، سرد، پرانرژی)
    layout    سوژه در کدام سمت است، جای خالیِ متن کجاست
    styles    سه سبکِ پیشنهادی از ``styles.STYLES`` با دلیلِ فارسی
نتیجه زیرِ ``MEDIA_ROOT/thumbs/s<فروشگاه>/refs/`` (یک jpg کوچک + یک json) نگه داشته می‌شود تا مودبردِ شما بماند؛ پاک‌کردنش یک کلیک است.
"""
from __future__ import annotations

import colorsys
import io
import json
import logging
import re
import shutil
import uuid
from html import unescape
from pathlib import Path
from urllib.parse import quote, urljoin, urlsplit

import numpy as np
from django.conf import settings
from PIL import Image, ImageOps

from services import safenet

from . import formats as F
from . import palette as pal
from .styles import STYLES

logger = logging.getLogger(__name__)

MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_PAGE_BYTES = 3 * 1024 * 1024
MAX_REFS_PER_STORE = 40
KEEP_PX = 640                      # بزرگ‌ترین ضلعِ پیش‌نمایشِ نگه‌داشته‌شده
COMMONS_API = "https://commons.wikimedia.org/w/api.php"
SOURCES = {"upload": "بارگذاری", "url": "نشانیِ اینترنتی", "pinterest": "پینترست", "commons": "پوسترِ آزاد (ویکی‌مدیا کامنز)"}
PINTEREST_HOSTS = ("pinterest.com", "pin.it", "pinterest.co.uk", "pinterest.fr", "pinterest.de", "pinterest.ca", "pinterest.es", "pinterest.it")


class RefError(ValueError):
    """پیامِ فارسیِ قابلِ نمایش. ``extra`` (اختیاری) به پاسخِ API می‌رود: مثلاً ``image_url`` تا مرورگرِ کاربر خودش عکس را بگیرد."""

    def __init__(self, message, extra: dict | None = None):
        super().__init__(message)
        self.extra = extra or {}


# ───────────────────────────── رنگ

def _name_fa(h: float, s: float, l: float) -> str:
    if l < 0.12:
        return "مشکی"
    if l > 0.92 and s < 0.3:
        return "سفید"
    if s < 0.12:
        return "خاکستری" if 0.25 < l < 0.75 else ("سفیدِ مایل به طوسی" if l >= 0.75 else "ذغالی")
    deg = h * 360
    tone = "روشن" if l > 0.68 else "تیره" if l < 0.28 else ""
    if deg < 15 or deg >= 345:
        base = "قرمز"
    elif deg < 40:
        base = "نارنجی" if l > 0.35 else "قهوه‌ای"
    elif deg < 65:
        base = "زرد" if s > 0.5 else "کرم"
    elif deg < 160:
        base = "سبز"
    elif deg < 200:
        base = "فیروزه‌ای"
    elif deg < 255:
        base = "آبی"
    elif deg < 290:
        base = "بنفش"
    else:
        base = "صورتی"
    return (base + " " + tone).strip()


def _name_en(h: float, s: float, l: float) -> str:
    if l < 0.12:
        return "black"
    if l > 0.92 and s < 0.3:
        return "white"
    if s < 0.12:
        return "gray"
    deg = h * 360
    if deg < 15 or deg >= 345:
        base = "red"
    elif deg < 40:
        base = "orange" if l > 0.35 else "brown"
    elif deg < 65:
        base = "yellow" if s > 0.5 else "cream"
    elif deg < 160:
        base = "green"
    elif deg < 200:
        base = "teal"
    elif deg < 255:
        base = "blue"
    elif deg < 290:
        base = "purple"
    else:
        base = "pink"
    return ("deep " + base) if l < 0.28 else ("light " + base) if l > 0.68 else base


def _hex(rgb) -> str:
    return "#%02x%02x%02x" % tuple(int(max(0, min(255, round(c)))) for c in rgb)


def _hls(rgb):
    r, g, b = (c / 255.0 for c in rgb)
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    return h, s, l


def _dist(a, b) -> float:
    return float(sum((x - y) ** 2 for x, y in zip(a, b)) ** 0.5)


# ───────────────────────────── تحلیل

def _palette_of(small: Image.Image) -> list[dict]:
    q = small.quantize(colors=8, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
    raw = q.getpalette() or []
    total = float(small.size[0] * small.size[1]) or 1.0
    rows: list[tuple[float, tuple]] = []
    for count, idx in q.getcolors() or []:
        rgb = tuple(raw[idx * 3: idx * 3 + 3])
        if len(rgb) == 3:
            rows.append((count / total, rgb))
    rows.sort(key=lambda r: -r[0])
    merged: list[list] = []
    for share, rgb in rows:                       # رنگ‌های نزدیک به هم یکی می‌شوند
        for m in merged:
            if _dist(m[1], rgb) < 38:
                m[0] += share
                break
        else:
            merged.append([share, rgb])
    merged.sort(key=lambda r: -r[0])
    out = []
    for share, rgb in merged[:5]:
        h, s, l = _hls(rgb)
        out.append({"hex": _hex(rgb), "share": round(share, 3), "name": _name_fa(h, s, l), "name_en": _name_en(h, s, l),
                    "_h": h, "_s": s, "_l": l})
    return out


def _pick_roles(colors: list[dict]) -> dict:
    """اصلی = پررنگ‌ترینِ پرحضور؛ دوم = رنگی که فامش فرق دارد؛ تأکید = رنگی و روشن (حتی اگر کم‌حضور)."""
    chroma = [c for c in colors if c["_s"] > 0.22 and 0.12 < c["_l"] < 0.9]
    primary = max(chroma, key=lambda c: c["share"] * (0.4 + c["_s"]), default=None)
    secondary = None
    if primary:
        for c in sorted(chroma, key=lambda c: -c["share"]):
            dh = min(abs(c["_h"] - primary["_h"]), 1 - abs(c["_h"] - primary["_h"])) * 360
            if c is not primary and dh >= 25:
                secondary = c
                break
        if secondary is None:
            others = [c for c in colors if c is not primary]
            secondary = others[0] if others else None
    accent = max((c for c in chroma if c["_s"] > 0.45 and c["_l"] > 0.4), key=lambda c: c["_s"] * c["_l"], default=None)
    return {"primary": primary, "secondary": secondary, "accent": accent}


def _mood_of(lum: float, sat: float, colors: list[dict], roles: dict) -> str:
    prim = roles.get("primary")
    hue = (prim["_h"] * 360) if prim else None
    teal = any(c["_s"] > 0.3 and 165 <= c["_h"] * 360 <= 215 for c in colors)
    orange = any(c["_s"] > 0.35 and 12 <= c["_h"] * 360 <= 45 for c in colors)
    if lum < 0.3 and sat > 0.55 and hue is not None and (270 <= hue <= 340 or 170 <= hue <= 200) and any(c["_s"] > 0.8 for c in colors):
        return "neon"
    if lum < 0.34 and hue is not None and 35 <= hue <= 55 and sat < 0.5:
        return "luxury"
    if teal and orange and lum < 0.55:
        return "cinema"
    if lum < 0.28:
        return "dark"
    if lum > 0.68 and sat < 0.45:
        return "light"
    if sat > 0.55 and lum >= 0.34:
        return "vivid"
    if hue is not None and (hue < 70 or hue >= 340):
        return "warm"
    if hue is not None and 170 <= hue <= 270:
        return "cool"
    return "vivid" if sat > 0.4 else ("light" if lum > 0.55 else "dark")


def _grid_means(a: np.ndarray, rows: int, cols: int) -> np.ndarray:
    h, w = a.shape
    out = np.zeros((rows, cols), dtype=np.float32)
    for r in range(rows):
        for c in range(cols):
            out[r, c] = a[r * h // rows:(r + 1) * h // rows, c * w // cols:(c + 1) * w // cols].mean()
    return out


def _saliency(rgb: np.ndarray) -> np.ndarray:
    """«چه چیزی از پس‌زمینه جداست؟»: فاصلهٔ هر نقطه از رنگِ میانهٔ قابِ بیرونیِ تصویر (۰ تا ۱)."""
    h, w, _ = rgb.shape
    m = max(2, int(min(h, w) * 0.08))
    frame = np.concatenate([rgb[:m].reshape(-1, 3), rgb[-m:].reshape(-1, 3), rgb[:, :m].reshape(-1, 3), rgb[:, -m:].reshape(-1, 3)])
    bg = np.median(frame, axis=0)
    dist = np.sqrt(((rgb - bg) ** 2).sum(axis=2)) / 441.7
    top = float(dist.max()) or 1.0
    return dist / top


def _layout_of(gray: np.ndarray, rgb: np.ndarray) -> dict:
    gy, gx = np.abs(np.diff(gray, axis=0, prepend=gray[:1])), np.abs(np.diff(gray, axis=1, prepend=gray[:, :1]))
    busy = gx + gy
    busy = busy / (float(busy.max()) or 1.0)
    focus = 0.6 * _saliency(rgb) + 0.4 * busy
    g = _grid_means(focus, 3, 3)
    cols = g.mean(axis=0)                                   # چپ، وسط، راست
    rows_ = g.mean(axis=1)                                  # بالا، وسط، پایین
    total = float(g.sum()) or 1.0
    top = float(cols.max() / (cols.mean() or 1.0))
    if cols[0] > cols[1] * 1.12 and cols[0] > cols[2] * 1.12:
        side = "left"
    elif cols[2] > cols[1] * 1.12 and cols[2] > cols[0] * 1.12:
        side = "right"
    else:
        side = "center"
    # «جای خالیِ متن»: آرام‌ترین بخش (کم‌ترین حضورِ سوژه) بین بالا، پایین و کنارِ مخالفِ سوژه
    calm = {"top": float(rows_[0]), "bottom": float(rows_[2])}
    if side == "left":
        calm["right"] = float(cols[2])
    elif side == "right":
        calm["left"] = float(cols[0])
    text_zone = min(calm, key=lambda k: calm[k])
    cy, cx = np.unravel_index(int(np.argmax(g)), g.shape)
    return {"subject_side": side, "text_zone": text_zone, "focus": [round((cx + 0.5) / 3, 2), round((cy + 0.5) / 3, 2)],
            "concentration": round(min(1.0, top / 1.6), 2), "busy": round(float(busy.mean()), 3), "calm": round(min(calm.values()) / (float(g.mean()) or 1.0), 2),
            "share_center": round(float(g[1, 1] / total), 2)}


def format_hint(w: int, h: int, source: str = "") -> str:
    r = w / float(h or 1)
    if r >= 1.5:
        return "youtube"
    if r >= 1.2:
        return "youtube"
    if 0.9 <= r < 1.2:
        return "ig_square"
    if 0.7 <= r < 0.9:
        return "ig_portrait"
    if 0.5 <= r < 0.7:
        return "poster" if source == "commons" else "pinterest"
    return "story"


def analyze(img: Image.Image, *, source: str = "upload") -> dict:
    """تصویر ⇒ {size, aspect, format_hint, palette[], roles, mood, brightness, saturation, contrast, layout, styles[]}."""
    im = ImageOps.exif_transpose(img).convert("RGB")
    w, h = im.size
    small = im.copy()
    small.thumbnail((160, 160))
    arr = np.asarray(small, dtype=np.float32)
    lum_map = (0.2126 * arr[..., 0] + 0.7152 * arr[..., 1] + 0.0722 * arr[..., 2]) / 255.0
    mx, mn = arr.max(axis=2), arr.min(axis=2)
    sat_map = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1e-6), 0.0)
    colors = _palette_of(small)
    roles = _pick_roles(colors)
    lum, sat = float(lum_map.mean()), float(sat_map.mean())
    mood = _mood_of(lum, sat, colors, roles)
    layout = _layout_of(lum_map, arr)
    out = {
        "size": [w, h], "aspect": round(w / float(h or 1), 3), "format_hint": format_hint(w, h, source),
        "palette": [{k: v for k, v in c.items() if not k.startswith("_")} for c in colors],
        "roles": {k: (v["hex"] if v else "") for k, v in roles.items()},
        "mood": mood, "mood_fa": pal.MOOD_FA.get(mood, mood), "brightness": round(lum, 2), "saturation": round(sat, 2),
        "contrast": round(float(lum_map.std()), 2), "layout": layout,
    }
    out["styles"] = suggest_styles(out)
    out["summary"] = summary_fa(out)
    return out


# ───────────────────────────── سبک‌های پیشنهادی

def suggest_styles(a: dict, limit: int = 3) -> list[dict]:
    """امتیازِ هر سبک: هم‌حال‌وهوا، هم‌نسبتِ تصویر، نیازِ سوژه، و چند قاعدهٔ شناخته‌شده؛ ⇒ ``limit`` سبکِ برتر با دلیل."""
    mood, aspect, lay = a["mood"], a["aspect"], a["layout"]
    fmt = a["format_hint"]
    scored: list[tuple[float, str, list[str]]] = []
    for key, st in STYLES.items():
        score, why = 0.0, []
        if st.mood == mood:
            score += 3
            why.append("هم‌حال‌وهواست")
        if fmt in st.formats:
            score += 2
            why.append(f"برای «{F.FORMATS[fmt].title}» ساخته شده")
        tall = aspect < 0.8
        if tall and st.formats and st.formats[0] in ("pinterest", "poster", "ig_portrait", "story"):
            score += 1
        if not tall and aspect >= 1.3 and st.formats and st.formats[0] in ("youtube", "aparat", "telegram"):
            score += 1
        conc = lay["concentration"]
        if st.subject == "recommended" and conc >= 0.55:
            score += 1
            why.append("سوژهٔ مشخصی دارد")
        if st.subject == "none" and conc < 0.4:
            score += 0.6
        if key == "cinema_poster" and mood in ("cinema", "dark") and tall:
            score += 2
        if key == "pinterest_collage" and mood in ("light", "warm") and tall:
            score += 1.5
        if key == "minimal_luxury" and mood in ("luxury", "dark") and lay["busy"] < 0.12:
            score += 2
        if key == "magazine_cover" and mood in ("light", "vivid") and tall and conc >= 0.5:
            score += 1.5
        if key == "neon" and mood == "neon":
            score += 2
        if key == "retro_poster" and mood in ("warm",) and a["saturation"] > 0.35:
            score += 1.5
        if key == "quote_card" and lay["busy"] < 0.07:
            score += 1.5
        scored.append((score, key, why))
    scored.sort(key=lambda r: (-r[0], r[1]))
    return [{"key": k, "title": STYLES[k].title, "score": round(s, 1), "why": "، ".join(w) or "نزدیک‌ترین به چیدمانِ مرجع"} for s, k, w in scored[:limit]]


_SIDE_FA = {"left": "چپ", "right": "راست", "center": "وسطِ کادر"}
_ZONE_FA = {"top": "بالا", "bottom": "پایین", "left": "سمتِ چپ", "right": "سمتِ راست"}


def summary_fa(a: dict) -> str:
    cols = [c for c in a["palette"] if c["share"] >= 0.06][:3] or a["palette"][:2]
    names = "، ".join(dict.fromkeys(c["name"] for c in cols))
    lay = a["layout"]
    side = lay["subject_side"]
    where = "سوژه در وسطِ کادر است" if side == "center" else f"سوژه بیشتر سمتِ {_SIDE_FA[side]} است"
    best = a["styles"][0]["title"] if a.get("styles") else ""
    return (f"حال‌وهوا: {a['mood_fa']}. رنگ‌های غالب: {names}. {where} و بهترین جای متن {_ZONE_FA.get(lay['text_zone'], 'بخشِ آرام')} است."
            + (f" نزدیک‌ترین سبک: «{best}»." if best else ""))


# ───────────────────────────── گرفتنِ تصویر

_META = re.compile(r"<meta\b[^>]*>", re.I)
_ATTR = re.compile(r"""([a-zA-Z:_-]+)\s*=\s*("([^"]*)"|'([^']*)')""")


def page_images(html: str, base_url: str) -> dict:
    """``og:image`` / ``twitter:image`` / ``og:title`` از یک صفحه (همانی که پیش‌نمایشِ پیوند می‌خواند)."""
    found: dict[str, str] = {}
    for tag in _META.findall(html or ""):
        attrs = {m.group(1).lower(): unescape(m.group(3) if m.group(3) is not None else m.group(4) or "") for m in _ATTR.finditer(tag)}
        key = (attrs.get("property") or attrs.get("name") or "").lower()
        if key in ("og:image", "og:image:url", "og:image:secure_url", "twitter:image", "twitter:image:src", "og:title", "twitter:title", "og:description") \
                and attrs.get("content") and key not in found:
            found[key] = attrs["content"].strip()
    image = found.get("og:image") or found.get("og:image:secure_url") or found.get("og:image:url") or found.get("twitter:image") or found.get("twitter:image:src") or ""
    if not image:
        m = re.search(r"""<link\b[^>]*rel=["']image_src["'][^>]*href=["']([^"']+)""", html or "", re.I)
        image = unescape(m.group(1)) if m else ""
    if image:
        image = urljoin(base_url, image)
        # پینترست: ‎/236x/ ‎/474x/ ⇒ ‎/736x/ (نسخهٔ بزرگ‌تر؛ برای تحلیلِ رنگ کافی)
        image = re.sub(r"(i\.pinimg\.com)/(?:\d{2,4}x|\d+x\d+)/", r"\1/736x/", image)
    return {"image": image, "title": (found.get("og:title") or found.get("twitter:title") or "")[:200], "description": (found.get("og:description") or "")[:300]}


def is_pinterest(url: str) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    return any(host == h or host.endswith("." + h) for h in PINTEREST_HOSTS)


def _open_image(data: bytes) -> Image.Image:
    try:
        im = Image.open(io.BytesIO(data))
        im.load()
    except Exception as exc:  # noqa: BLE001
        raise RefError("این فایل عکسِ قابل‌خواندن نیست (JPEG، PNG، WebP).") from exc
    if min(im.size) < 40:
        raise RefError("عکس خیلی کوچک است.")
    return im


def fetch_url(url: str, *, fetch=None) -> tuple[Image.Image, dict]:
    """نشانیِ عکس یا صفحه ⇒ (تصویر، {title, source, page_url, image_url}). ``fetch`` برای آزمون تزریق می‌شود."""
    get = fetch or safenet.get
    url = (url or "").strip()
    if not url:
        raise RefError("نشانی را بچسبانید.")
    if not re.match(r"^https?://", url, re.I):
        url = "https://" + url
    try:
        first = get(url, max_bytes=MAX_PAGE_BYTES, accept="text/html,image/*;q=0.9,*/*;q=0.5")
    except safenet.FetchError as exc:
        raise RefError(exc.message) from exc
    ctype = (first.content_type or "").lower()
    meta = {"title": "", "source": "pinterest" if is_pinterest(url) else "url", "page_url": safenet.redact(url), "image_url": ""}
    if ctype.startswith("image/") or (first.body[:4] in (b"\xff\xd8\xff\xe0", b"\xff\xd8\xff\xe1", b"\x89PNG") and "html" not in ctype):
        meta["image_url"] = safenet.redact(url)
        if len(first.body) > MAX_IMAGE_BYTES:
            raise RefError("عکس بزرگ‌تر از ۸ مگابایت است.")
        return _open_image(first.body), meta
    info = page_images(first.text, first.url)
    if info["image"] and meta["source"] == "pinterest" and "pinimg.com/" in info["image"] and "/images/" in info["image"] and "/736x/" not in info["image"]:
        info["image"] = ""                    # پینی که پیدا نشد/عمومی نیست: پینترست عکسِ عمومیِ اشتراکِ خودش (facebook_share_image.png) را برمی‌گرداند
    if not info["image"]:
        raise RefError("در این صفحه عکسِ قابل‌استفاده‌ای پیدا نشد؛ اگر پینترست است، خودِ پین را باز کنید و نشانیِ همان صفحه را بدهید.")
    meta["title"] = info["title"]
    try:
        img = get(info["image"], max_bytes=MAX_IMAGE_BYTES, accept="image/*,*/*;q=0.5")
    except safenet.FetchError as exc:
        extra = {"image_url": safenet.redact(info["image"]), "title": info["title"], "source": meta["source"], "page_url": meta["page_url"]}
        if "pinimg.com" in (urlsplit(info["image"]).hostname or ""):
            # CDN ِ عکس‌های پینترست از ایران فیلتر است (DNS به نشانیِ داخلیِ فیلترینگ می‌رسد)؛ مرورگرِ کاربر (اگر VPN دارد) می‌تواند بگیرد
            raise RefError("عکسِ پینترست از سرورِ ما (در ایران) باز نمی‌شود. اگر مرورگرتان به پینترست دسترسی دارد خودش آن را می‌گیرد؛ وگرنه عکس را ذخیره کنید و از «عکسِ خودم» بارگذاری کنید.", extra) from exc
        raise RefError("عکسِ صفحه گرفته نشد: " + exc.message, extra) from exc
    meta["image_url"] = safenet.redact(info["image"])
    return _open_image(img.body), meta


# ───────────────────────────── پوسترهای آزاد (ویکی‌مدیا کامنز)

def _plain(html: str) -> str:
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", html or ""))).strip()


def license_is_free(short: str, nonfree: str = "") -> bool:
    """مجوزِ آزاد: مالکیتِ عمومی، CC0، CC BY، CC BY-SA. غیرتجاری (NC)، بدونِ اشتقاق (ND)، «استفادهٔ منصفانه» و پرونده‌های non-free رد می‌شوند."""
    s = (short or "").strip().lower()
    if not s or str(nonfree).lower() in ("true", "1", "yes"):
        return False
    if re.search(r"\b(nc|nd)\b", s) or any(w in s for w in ("non-commercial", "noncommercial", "fair use", "non-free", "nonfree")):
        return False
    return s.startswith(("public domain", "cc0", "cc by", "cc-by", "pd", "no restrictions", "attribution"))


def search_commons(query: str, *, limit: int = 12, fetch=None) -> list[dict]:
    """جست‌وجوی پوستر در ویکی‌مدیا کامنز؛ فقط پرونده‌های با مجوزِ آزاد. ⇒ [{id, title, thumb_url, page_url, author, license, width, height}]."""
    get = fetch or safenet.get
    q = re.sub(r"\s+", " ", (query or "").strip())[:80]
    if len(q) < 2:
        raise RefError("چیزی بنویسید (مثلاً «film noir poster» یا «sport poster»).")
    if not re.search(r"poster", q, re.I):
        q += " poster"
    url = (f"{COMMONS_API}?action=query&generator=search&gsrsearch={quote(q + ' filetype:bitmap')}&gsrnamespace=6&gsrlimit={max(1, min(30, limit * 2))}"
           "&prop=imageinfo&iiprop=url|size|mime|extmetadata&iiurlwidth=640&format=json&formatversion=2")
    try:
        res = get(url, max_bytes=2_000_000, accept="application/json")
        data = json.loads(res.text)
    except safenet.FetchError as exc:
        raise RefError("جست‌وجو در ویکی‌مدیا ممکن نشد: " + exc.message) from exc
    except ValueError as exc:
        raise RefError("جوابِ ویکی‌مدیا خوانده نشد.") from exc
    out: list[dict] = []
    for page in (data.get("query") or {}).get("pages") or []:
        ii = (page.get("imageinfo") or [{}])[0]
        em = ii.get("extmetadata") or {}
        lic = (em.get("LicenseShortName") or {}).get("value", "")
        if not ii.get("thumburl") or not license_is_free(lic, (em.get("NonFree") or {}).get("value", "")):
            continue
        if str(ii.get("mime", "")).split("/")[0] != "image" or ii.get("mime") in ("image/svg+xml", "image/gif"):
            continue
        out.append({
            "id": page.get("pageid"), "title": re.sub(r"^File:", "", page.get("title", "")).rsplit(".", 1)[0][:120],
            "thumb_url": ii["thumburl"], "page_url": ii.get("descriptionurl", ""), "author": _plain((em.get("Artist") or {}).get("value", ""))[:100],
            "license": lic[:40], "license_url": (em.get("LicenseUrl") or {}).get("value", ""), "width": ii.get("width"), "height": ii.get("height"),
        })
        if len(out) >= limit:
            break
    return out


def fetch_commons(thumb_url: str, *, fetch=None) -> Image.Image:
    host = (urlsplit(thumb_url).hostname or "").lower()
    if not (host.endswith("wikimedia.org") or host.endswith("wikipedia.org")):
        raise RefError("فقط تصویرهای ویکی‌مدیا پذیرفته می‌شود.")
    try:
        res = (fetch or safenet.get)(thumb_url, max_bytes=MAX_IMAGE_BYTES, accept="image/*")
    except safenet.FetchError as exc:
        raise RefError("تصویر گرفته نشد: " + exc.message) from exc
    return _open_image(res.body)


# ───────────────────────────── نگهداری (فایل، بدونِ مهاجرتِ پایگاه‌داده)

def _root(store_id) -> Path:
    return Path(settings.MEDIA_ROOT) / "thumbs" / f"s{int(store_id)}" / "refs"


def _media_rel(store_id, rid: str) -> str:
    return f"thumbs/s{int(store_id)}/refs/{rid}.jpg"


def _valid_id(rid: str) -> bool:
    return bool(re.fullmatch(r"[0-9a-f]{12}", rid or ""))


def _row(store_id, rid: str, meta: dict) -> dict:
    out = dict(meta)
    out["id"] = rid
    out["image"] = settings.MEDIA_URL.rstrip("/") + "/" + _media_rel(store_id, rid)
    out["source_label"] = SOURCES.get(meta.get("source", ""), meta.get("source", ""))
    return out


def save(store_id, img: Image.Image, *, source: str, title: str = "", extra: dict | None = None) -> dict:
    """تحلیل + ذخیره (jpg کوچک + json). ⇒ ردیفِ مرجع."""
    root = _root(store_id)
    root.mkdir(parents=True, exist_ok=True)
    have = sorted(root.glob("*.json"), key=lambda p: p.stat().st_mtime)
    for old in have[: max(0, len(have) - (MAX_REFS_PER_STORE - 1))]:            # سقف: قدیمی‌ترین‌ها می‌روند
        old.with_suffix(".jpg").unlink(missing_ok=True)
        old.unlink(missing_ok=True)
    rid = uuid.uuid4().hex[:12]
    analysis = analyze(img, source=source)
    keep = ImageOps.exif_transpose(img).convert("RGB")
    keep.thumbnail((KEEP_PX, KEEP_PX))
    tmp = root / f"{rid}.tmp"
    keep.save(tmp, "JPEG", quality=84, optimize=True)
    tmp.replace(root / f"{rid}.jpg")
    meta = {"source": source, "title": (title or "")[:160], "analysis": analysis, "created": _now()}
    meta.update({k: v for k, v in (extra or {}).items() if k in ("page_url", "image_url", "author", "license", "license_url")})
    (root / f"{rid}.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    return _row(store_id, rid, meta)


def _now() -> str:
    from django.utils import timezone

    return timezone.now().isoformat(timespec="seconds")


def get(store_id, rid: str) -> dict | None:
    if not _valid_id(rid):
        return None
    p = _root(store_id) / f"{rid}.json"
    if not p.is_file():
        return None
    try:
        return _row(store_id, rid, json.loads(p.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return None


def listing(store_id) -> list[dict]:
    root = _root(store_id)
    if not root.is_dir():
        return []
    rows = []
    for p in sorted(root.glob("*.json"), key=lambda q: q.stat().st_mtime, reverse=True):
        r = get(store_id, p.stem)
        if r:
            rows.append(r)
    return rows


def delete(store_id, rid: str) -> bool:
    if not _valid_id(rid):
        return False
    root = _root(store_id)
    hit = False
    for ext in (".json", ".jpg"):
        p = root / f"{rid}{ext}"
        if p.is_file():
            p.unlink()
            hit = True
    return hit


def purge_store(store_id) -> None:
    shutil.rmtree(_root(store_id), ignore_errors=True)


# ───────────────────────────── ایده از روی مرجع

_ZONE_EN = {"top": "the top", "bottom": "the bottom", "left": "the left side", "right": "the right side"}
_SIDE_EN = {"left": "on the left", "right": "on the right", "center": "in the center"}
_MOOD_EN = {"vivid": "vibrant energetic", "dark": "dark moody", "light": "bright clean airy", "cinema": "cinematic teal and orange", "neon": "neon glow",
            "luxury": "luxury gold and black", "warm": "warm sunny", "cool": "cool modern"}


def background_prompt(a: dict) -> str:
    """دستورِ انگلیسیِ پس‌زمینه برای ComfyUI از روی تحلیلِ مرجع (بدونِ متن، بدونِ آدم و لوگو)."""
    names = [c["name_en"] for c in a["palette"] if c["share"] >= 0.07][:3] or [c["name_en"] for c in a["palette"][:2]]
    lay = a["layout"]
    bits = [f"{_MOOD_EN.get(a['mood'], 'modern')} abstract background", "color palette of " + ", ".join(names),
            f"visual weight {_SIDE_EN.get(lay['subject_side'], 'in the center')}", f"calm empty space at {_ZONE_EN.get(lay['text_zone'], 'the bottom')} for a headline"]
    return ", ".join(bits) + ", no text, no people, no logos, no watermark"


def _colors_patch(a: dict, mode: str) -> dict:
    roles = a.get("roles") or {}
    if mode == "reference" and roles.get("primary"):
        return {"mood": a["mood"], "primary": roles.get("primary", ""), "secondary": roles.get("secondary", ""), "accent": roles.get("accent", ""), "use_brand": False}
    return {"mood": a["mood"], "use_brand": True}


def restyle(ideas: list[dict], ref: dict, *, fmt: str, palette_mode: str = "brand") -> list[dict]:
    """ایده‌های متنی (از ideation) را با سبک، رنگ، سمتِ سوژه و دستورِ پس‌زمینهٔ مرجع «دوباره می‌پوشاند»؛ متن‌ها دست‌نخورده می‌مانند."""
    a = ref["analysis"]
    styles = [s["key"] for s in a["styles"] if s["key"] in STYLES] or ["face_text"]
    colors = _colors_patch(a, palette_mode)
    side = a["layout"]["subject_side"]
    out = []
    for i, idea in enumerate(ideas):
        key = styles[i % len(styles)]
        st = STYLES[key]
        d = dict(idea)
        d.update({"style": key, "style_title": st.title, "mood": a["mood"], "needs_second": st.needs_second, "bg_prompt_en": background_prompt(a),
                  "reference": {"id": ref["id"], "title": ref.get("title", ""), "source": ref.get("source", ""), "source_label": ref.get("source_label", ""),
                                "mood_fa": a["mood_fa"], "image": ref["image"]},
                  "source": d.get("source", "rules")})
        d["concept"] = (f"{(idea.get('concept') or '').rstrip('.')}؛ با حال‌وهوای مرجع: {a['mood_fa']}، "
                        f"سوژه {_SIDE_FA.get(side, 'وسط')}، جای متن {_ZONE_FA.get(a['layout']['text_zone'], 'پایین')}.")[:260]
        patch = dict(d.get("spec_patch") or {})
        patch.update({"style": key, "format": fmt, "colors": colors, "subject": {"side": side if side in ("left", "right", "center") else "auto"}})
        d["spec_patch"] = patch
        out.append(d)
    return out
