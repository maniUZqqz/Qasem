"""نویسندهٔ فایلِ لایه‌دار (PSD، نسخهٔ ۱، RGB هشت‌بیتی، بی‌فشرده؛ خواندنِ برگشتی خام و ZIP را می‌فهمد) — بدونِ وابستگیِ تازه.

ساختار (Adobe Photoshop File Format Specification):
  Header · Color Mode Data (خالی) · Image Resources (خالی) · Layer and Mask Information · Image Data (تصویرِ ترکیبی)

هر لایه: مستطیلِ خودش، چهار کانال (A, R, G, B)، نامِ یونیکد (بلوکِ ``luni``)، شفافیت، حالتِ ترکیب و پرچمِ پنهان.
نامِ فارسی در رکوردِ Pascal به‌صورتِ ASCII/«?» می‌آید و نامِ درست در ``luni`` است (Photoshop و Photopea از ``luni`` می‌خوانند).
خواندنِ برگشتیِ همین فایل: ``read_psd`` (برای آزمون و «بازکردنِ PSD» در آینده).
"""
from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass

import numpy as np
from PIL import Image

#: حالتِ ترکیبِ ویرایشگر ⇒ کلیدِ ۴حرفیِ PSD
BLEND_KEYS = {
    "normal": b"norm", "multiply": b"mul ", "screen": b"scrn", "overlay": b"over", "soft-light": b"sLit", "hard-light": b"hLit",
    "darken": b"dark", "lighten": b"lite", "color-dodge": b"div ", "color-burn": b"idiv", "difference": b"diff", "exclusion": b"smud",
    "hue": b"hue ", "saturation": b"sat ", "color": b"colr", "luminosity": b"lum ",
}
KEY_BLENDS = {v: k for k, v in BLEND_KEYS.items()}
MAX_SIDE = 30000


@dataclass
class PsdLayer:
    name: str
    img: Image.Image            # RGBA، به اندازهٔ مستطیلِ خودش
    x: int = 0
    y: int = 0
    opacity: float = 1.0
    blend: str = "normal"
    visible: bool = True


def _pad4(b: bytes) -> bytes:
    return b + b"\0" * ((-len(b)) % 4)


def _pascal(name: str) -> bytes:
    raw = name.encode("ascii", "replace")[:255]
    s = bytes([len(raw)]) + raw
    return s + b"\0" * ((-len(s)) % 4)


def _luni(name: str) -> bytes:
    u = name[:250].encode("utf-16-be")
    body = struct.pack(">I", len(u) // 2) + u
    body = _pad4(body)
    return b"8BIM" + b"luni" + struct.pack(">I", len(body)) + body


def _planes(img: Image.Image) -> list[bytes]:
    a = np.asarray(img.convert("RGBA"))
    return [a[..., 3].tobytes(), a[..., 0].tobytes(), a[..., 1].tobytes(), a[..., 2].tobytes()]


def write_psd(size: tuple[int, int], merged: Image.Image, layers: list[PsdLayer]) -> bytes:
    """⇒ بایت‌های PSD. ``layers`` از پایین به بالا؛ ``merged`` تصویرِ ترکیبیِ نهایی (هم‌اندازهٔ size).
    حافظه: تکه‌ها فقط یک بار در یک فهرست می‌مانند و در پایان یک‌جا به هم می‌چسبند (به‌جای چند کپیِ پیاپی)."""
    W, H = size
    if not (1 <= W <= MAX_SIDE and 1 <= H <= MAX_SIDE):
        raise ValueError("اندازهٔ بوم برای PSD معتبر نیست.")
    head = b"8BPS" + struct.pack(">H", 1) + b"\0" * 6 + struct.pack(">HIIHH", 3, H, W, 8, 3)
    head += struct.pack(">I", 0)                      # color mode data
    head += struct.pack(">I", 0)                      # image resources

    recs = bytearray()
    parts: list[bytes] = []
    dlen = 0
    count = 0
    for L in layers:
        im = L.img.convert("RGBA")
        w, h = im.size
        if w <= 0 or h <= 0:
            continue
        count += 1
        # خام (فشرده‌سازیِ ۰): در همهٔ نرم‌افزارها باز می‌شود؛ حجم بیشتر است ولی سازگاری مهم‌تر است
        planes = _planes(im)
        recs += struct.pack(">iiii", L.y, L.x, L.y + h, L.x + w)
        recs += struct.pack(">H", 4)
        for cid, pl in zip((-1, 0, 1, 2), planes):
            recs += struct.pack(">hI", cid, 2 + len(pl))
        recs += b"8BIM" + BLEND_KEYS.get(L.blend, b"norm")
        recs += struct.pack(">BBBB", max(0, min(255, int(round(L.opacity * 255)))), 0, 0 if L.visible else 2, 0)
        extra = struct.pack(">I", 0) + struct.pack(">I", 0) + _pascal(L.name) + _luni(L.name)
        recs += struct.pack(">I", len(extra)) + extra
        for pl in planes:
            parts.append(struct.pack(">H", 0))
            parts.append(pl)
            dlen += 2 + len(pl)
    info_len = 2 + len(recs) + dlen
    pad = b"\0" if info_len % 2 else b""
    info_len += len(pad)
    sec_len = 4 + info_len + 4                         # طولِ اطلاعاتِ لایه + خودِ اطلاعات + «ماسکِ سراسریِ لایه» (خالی)

    rgb = Image.new("RGB", merged.size, (255, 255, 255))
    m = merged.convert("RGBA")
    rgb.paste(m, mask=m.getchannel("A"))
    if rgb.size != (W, H):
        rgb = rgb.resize((W, H), Image.Resampling.LANCZOS)
    a = np.asarray(rgb)
    return b"".join([head, struct.pack(">I", sec_len), struct.pack(">I", info_len), struct.pack(">h", count), bytes(recs), *parts, pad,
                     struct.pack(">I", 0), struct.pack(">H", 0), a[..., 0].tobytes(), a[..., 1].tobytes(), a[..., 2].tobytes()])


# ───────────────────────────── خواندنِ برگشتی (برای آزمون)

def read_psd(raw: bytes) -> dict:
    """PSD ِ خودِ همین نویسنده ⇒ {size, layers:[{name, x, y, w, h, opacity, blend, visible, rgba}], merged}. فقط خام (فشرده‌سازی ۰)."""
    if raw[:4] != b"8BPS":
        raise ValueError("امضای PSD نیست.")
    ver, = struct.unpack(">H", raw[4:6])
    ch, H, W, depth, mode = struct.unpack(">HIIHH", raw[12:26])
    if ver != 1 or depth != 8 or mode != 3:
        raise ValueError("فقط PSD ِ RGB هشت‌بیتی پشتیبانی می‌شود.")
    p = 26
    n, = struct.unpack(">I", raw[p:p + 4]); p += 4 + n          # color mode data
    n, = struct.unpack(">I", raw[p:p + 4]); p += 4 + n          # image resources
    sec_len, = struct.unpack(">I", raw[p:p + 4]); p += 4
    sec_end = p + sec_len
    info_len, = struct.unpack(">I", raw[p:p + 4]); p += 4
    cnt, = struct.unpack(">h", raw[p:p + 2]); p += 2
    cnt = abs(cnt)
    recs = []
    for _ in range(cnt):
        top, left, bottom, right = struct.unpack(">iiii", raw[p:p + 16]); p += 16
        nch, = struct.unpack(">H", raw[p:p + 2]); p += 2
        chs = []
        for _c in range(nch):
            cid, ln = struct.unpack(">hI", raw[p:p + 6]); p += 6
            chs.append((cid, ln))
        assert raw[p:p + 4] == b"8BIM"
        key = raw[p + 4:p + 8]
        opacity, _clip, flags, _fill = struct.unpack(">BBBB", raw[p + 8:p + 12]); p += 12
        elen, = struct.unpack(">I", raw[p:p + 4]); p += 4
        ex = raw[p:p + elen]; p += elen
        q = 4 + struct.unpack(">I", ex[:4])[0]
        q += 4 + struct.unpack(">I", ex[q:q + 4])[0]
        plen = ex[q]
        q += (1 + plen + 3) // 4 * 4
        name = ""
        while q + 12 <= len(ex):
            tag, ln = ex[q + 4:q + 8], struct.unpack(">I", ex[q + 8:q + 12])[0]
            if tag == b"luni":
                k, = struct.unpack(">I", ex[q + 12:q + 16])
                name = ex[q + 16:q + 16 + k * 2].decode("utf-16-be")
            q += 12 + ln
        recs.append({"rect": (left, top, right, bottom), "chs": chs, "key": key, "opacity": opacity, "flags": flags, "name": name})
    layers = []
    for r in recs:
        l, t, rr, b = r["rect"]
        w, h = rr - l, b - t
        planes = {}
        for cid, ln in r["chs"]:
            comp, = struct.unpack(">H", raw[p:p + 2])
            if comp not in (0, 2):
                raise ValueError("فقط داده‌ی خام و ZIP پشتیبانی می‌شود.")
            body = raw[p + 2:p + ln]
            planes[cid] = np.frombuffer(zlib.decompress(body) if comp == 2 else body, np.uint8).reshape(h, w)
            p += ln
        rgba = np.stack([planes[0], planes[1], planes[2], planes[-1]], axis=2) if w and h else np.zeros((0, 0, 4), np.uint8)
        layers.append({"name": r["name"], "x": l, "y": t, "w": w, "h": h, "opacity": r["opacity"] / 255.0, "blend": KEY_BLENDS.get(r["key"], "normal"),
                       "visible": not (r["flags"] & 2), "rgba": rgba})
    p = sec_end
    comp, = struct.unpack(">H", raw[p:p + 2]); p += 2
    plane = W * H
    merged = np.stack([np.frombuffer(raw[p + i * plane:p + (i + 1) * plane], np.uint8).reshape(H, W) for i in range(3)], axis=2) if comp == 0 else None
    return {"size": (W, H), "layers": layers, "merged": merged}
