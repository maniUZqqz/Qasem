"""خواندنِ فایلِ لایه‌دار (PSD، نسخهٔ ۱) برای «بازکردنِ PSD» (دورِ ۸) — بدونِ وابستگیِ تازه.

پشتیبانی: RGB و خاکستری، ۸ و ۱۶ بیت (۱۶ بیت به ۸ بیت می‌رود)، کانال‌های خام / RLE (PackBits) / ZIP / ZIP با پیش‌بینی، آلفای لایه، شفافیت،
حالتِ ترکیب، پنهان‌بودن، نامِ یونیکد (luni). نمی‌خواند: لایهٔ تنظیم، متنِ قابل‌ویرایش، شیءِ هوشمند، سبکِ لایه، ماسکِ لایه (فقط پیکسلِ لایه می‌آید)،
CMYK/Lab، PSB. گروه‌ها صاف می‌شوند (فرزندان می‌مانند). هر چیزِ نخوانده در ``notes`` گزارش می‌شود.
"""
from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass, field

import numpy as np

from .psd import KEY_BLENDS

MAX_LAYERS = 80
MAX_CANVAS_PIXELS = 100_000_000
MAX_LAYER_PIXELS_TOTAL = 160_000_000


class PsdReadError(ValueError):
    """پیامِ فارسی برای کاربر."""


@dataclass
class PsdLayerIn:
    name: str
    x: int
    y: int
    rgba: np.ndarray            # (h, w, 4) uint8
    opacity: float = 1.0
    blend: str = "normal"
    visible: bool = True


@dataclass
class PsdDoc:
    size: tuple[int, int]
    layers: list[PsdLayerIn]
    merged: np.ndarray | None        # (H, W, 3) uint8
    notes: list[str] = field(default_factory=list)


def unpackbits(data: bytes, expected: int) -> bytes:
    """PackBits ⇒ دقیقاً ``expected`` بایت (کم ⇒ صفر)؛ بسته‌های خراب خطا نمی‌دهند."""
    out = bytearray()
    i, n = 0, len(data)
    while i < n and len(out) < expected:
        c = data[i]
        i += 1
        if c < 128:
            out += data[i:i + c + 1]
            i += c + 1
        elif c > 128:
            if i < n:
                out += data[i:i + 1] * (257 - c)
            i += 1
    if len(out) < expected:
        out += bytes(expected - len(out))
    return bytes(out[:expected])


def _plane(raw: bytes, p: int, h: int, w: int, depth: int, comp: int, end: int) -> tuple[np.ndarray, int]:
    """یک کانال ⇒ آرایهٔ uint8 (h, w) و جایگاهِ بعدی. raw[p:] با نشانِ فشرده‌سازیِ ۲ بایتی شروع نمی‌شود (p بعد از آن است)."""
    bpp = 2 if depth == 16 else 1
    row_bytes = w * bpp
    if comp == 0:
        buf = raw[p:p + h * row_bytes]
        p += h * row_bytes
    elif comp == 1:
        counts = struct.unpack(f">{h}H", raw[p:p + 2 * h])
        p += 2 * h
        rows = []
        for c in counts:
            rows.append(unpackbits(raw[p:p + c], row_bytes))
            p += c
        buf = b"".join(rows)
    elif comp in (2, 3):
        buf = zlib.decompress(raw[p:end])
        p = end
        if comp == 3:
            a = np.frombuffer(buf, np.uint8 if bpp == 1 else ">u2").reshape(h, w).copy()
            a = np.cumsum(a, axis=1, dtype=a.dtype)
            buf = a.tobytes()
    else:
        raise PsdReadError("نوعِ فشرده‌سازیِ فایل پشتیبانی نمی‌شود.")
    if len(buf) < h * row_bytes:
        buf = buf + bytes(h * row_bytes - len(buf))
    a = np.frombuffer(buf[:h * row_bytes], np.uint8 if bpp == 1 else ">u2").reshape(h, w)
    if bpp == 2:
        a = (a.astype(np.uint32) >> 8).astype(np.uint8)
    return a, p


def _unicode_name(extra: bytes) -> str | None:
    i = extra.find(b"8BIMluni")
    if i < 0:
        return None
    try:
        ln = struct.unpack(">I", extra[i + 8:i + 12])[0]
        k = struct.unpack(">I", extra[i + 12:i + 16])[0]
        return extra[i + 16:i + 16 + k * 2].decode("utf-16-be").rstrip("\x00") or None
    except (struct.error, UnicodeDecodeError):
        return None


def _section_kind(extra: bytes) -> int:
    """lsct: ۰ لایهٔ معمولی، ۱/۲ آغازِ گروه (باز/بسته)، ۳ پایانِ گروه."""
    i = extra.find(b"8BIMlsct")
    if i < 0:
        return 0
    try:
        return struct.unpack(">I", extra[i + 12:i + 16])[0]
    except struct.error:
        return 0


def read_psd_full(raw: bytes) -> PsdDoc:
    if raw[:4] != b"8BPS":
        raise PsdReadError("این فایل PSD نیست.")
    try:
        ver, _r, nch, H, W, depth, mode = struct.unpack(">H6sHIIHH", raw[4:26])
    except struct.error as exc:
        raise PsdReadError("سرِ فایلِ PSD خراب است.") from exc
    if ver == 2:
        raise PsdReadError("فایل‌های بزرگِ PSB پشتیبانی نمی‌شوند.")
    if ver != 1:
        raise PsdReadError("نسخهٔ فایل پشتیبانی نمی‌شود.")
    if depth not in (8, 16) or mode not in (1, 3):
        raise PsdReadError("فقط PSD ِ RGB یا خاکستری با ۸ یا ۱۶ بیت باز می‌شود (CMYK و Lab نه).")
    if W * H > MAX_CANVAS_PIXELS or W < 1 or H < 1:
        raise PsdReadError("اندازهٔ بومِ PSD خیلی بزرگ است.")
    notes: list[str] = []
    p = 26
    n, = struct.unpack(">I", raw[p:p + 4])
    p += 4 + n                                               # color mode data
    n, = struct.unpack(">I", raw[p:p + 4])
    p += 4 + n                                               # image resources
    sec_len, = struct.unpack(">I", raw[p:p + 4])
    p += 4
    sec_end = p + sec_len
    layers: list[PsdLayerIn] = []
    skipped = 0
    if sec_len:
        info_len, = struct.unpack(">I", raw[p:p + 4])
        q = p + 4
        if info_len:
            cnt, = struct.unpack(">h", raw[q:q + 2])
            q += 2
            cnt = abs(cnt)
            if cnt > 400:
                raise PsdReadError("تعدادِ لایه‌ها خیلی زیاد است.")
            recs = []
            for _ in range(cnt):
                top, left, bottom, right = struct.unpack(">iiii", raw[q:q + 16])
                q += 16
                nc, = struct.unpack(">H", raw[q:q + 2])
                q += 2
                chs = []
                for _c in range(nc):
                    cid, ln = struct.unpack(">hI", raw[q:q + 6])
                    q += 6
                    chs.append((cid, ln))
                if raw[q:q + 4] != b"8BIM":
                    raise PsdReadError("ساختارِ لایه‌ها خوانده نشد.")
                key = raw[q + 4:q + 8]
                opacity, _clip, flags, _fill = struct.unpack(">BBBB", raw[q + 8:q + 12])
                q += 12
                elen, = struct.unpack(">I", raw[q:q + 4])
                q += 4
                extra = raw[q:q + elen]
                q += elen
                recs.append({"rect": (left, top, right, bottom), "chs": chs, "key": key, "opacity": opacity, "flags": flags, "extra": extra})
            total_px = 0
            for r in recs:
                l, t, rr, b = r["rect"]
                w, h = max(0, rr - l), max(0, b - t)
                kind = _section_kind(r["extra"])
                name = _unicode_name(r["extra"])
                if not name:
                    try:
                        e = r["extra"]
                        o = 4 + struct.unpack(">I", e[:4])[0]
                        o += 4 + struct.unpack(">I", e[o:o + 4])[0]
                        ln = e[o]
                        name = e[o + 1:o + 1 + ln].decode("latin-1")
                    except (struct.error, IndexError):
                        name = ""
                planes: dict[int, np.ndarray] = {}
                for cid, ln in r["chs"]:
                    end = q + ln
                    if w * h == 0 or ln < 2:
                        q = end
                        continue
                    comp, = struct.unpack(">H", raw[q:q + 2])
                    if cid in (-1, 0, 1, 2) and (kind == 0) and len(layers) < MAX_LAYERS and total_px + w * h <= MAX_LAYER_PIXELS_TOTAL:
                        try:
                            planes[cid], _ = _plane(raw, q + 2, h, w, depth, comp, end)
                        except (zlib.error, struct.error, ValueError):
                            pass
                    q = end
                if kind != 0:
                    continue                                           # نشانگرِ گروه
                if not planes or w * h == 0:
                    skipped += 1
                    continue
                total_px += w * h
                if mode == 1:
                    g = planes.get(0)
                    if g is None:
                        skipped += 1
                        continue
                    rgb = np.stack([g, g, g], axis=2)
                else:
                    if not all(c in planes for c in (0, 1, 2)):
                        skipped += 1
                        continue
                    rgb = np.stack([planes[0], planes[1], planes[2]], axis=2)
                a = planes.get(-1)
                a = np.full((h, w), 255, np.uint8) if a is None else a
                layers.append(PsdLayerIn(name=(name or f"لایه {len(layers) + 1}")[:60], x=l, y=t, rgba=np.dstack([rgb, a]),
                                         opacity=round(r["opacity"] / 255.0, 3), blend=KEY_BLENDS.get(r["key"], "normal"), visible=not (r["flags"] & 2)))
        if skipped:
            notes.append(f"{skipped} لایه (تنظیم، متنِ قابل‌ویرایش، شیءِ هوشمند یا خالی) پیکسل نداشت و نیامد")
        if len(layers) >= MAX_LAYERS:
            notes.append(f"فقط {MAX_LAYERS} لایهٔ اول آمد")
    # تصویرِ ترکیبی (پایانِ بخشِ لایه‌ها)
    merged = None
    try:
        q = sec_end
        comp, = struct.unpack(">H", raw[q:q + 2])
        q += 2
        planes = []
        nplanes = 3 if mode == 3 else 1
        if comp == 1:                                          # RLE: ابتدا شمارنده‌های همهٔ ردیف‌های همهٔ کانال‌ها
            allc = struct.unpack(f">{nch * H}H", raw[q:q + 2 * nch * H])
            q += 2 * nch * H
            for c in range(nplanes):
                rows = []
                for rrow in range(H):
                    ln = allc[c * H + rrow]
                    rows.append(unpackbits(raw[q:q + ln], W * (2 if depth == 16 else 1)))
                    q += ln
                buf = b"".join(rows)
                a = np.frombuffer(buf, np.uint8 if depth == 8 else ">u2").reshape(H, W)
                planes.append((a.astype(np.uint32) >> 8).astype(np.uint8) if depth == 16 else a)
        elif comp == 0:
            sz = W * H * (2 if depth == 16 else 1)
            for c in range(nplanes):
                a = np.frombuffer(raw[q + c * sz:q + (c + 1) * sz], np.uint8 if depth == 8 else ">u2").reshape(H, W)
                planes.append((a.astype(np.uint32) >> 8).astype(np.uint8) if depth == 16 else a)
        if planes:
            merged = np.stack(planes if mode == 3 else [planes[0]] * 3, axis=2)
    except (struct.error, ValueError):
        merged = None
    return PsdDoc((W, H), layers, merged, notes)
