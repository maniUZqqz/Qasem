# خواندن و نوشتنِ WAV و تغییرِ نرخِ نمونه فقط با numpy (بی soundfile و scipy).
import io
import struct

import numpy as np


def read_wav(src):
    """مسیر یا بایت ⇒ (صدای تک‌کاناله float32، نرخ). PCMِ ۸/۱۶/۲۴/۳۲ بیتی و float32/64."""
    data = src if isinstance(src, (bytes, bytearray)) else open(src, "rb").read()
    if data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise ValueError("فایل WAV نیست")
    pos, fmt, raw = 12, None, None
    while pos + 8 <= len(data):
        cid, size = data[pos:pos + 4], struct.unpack("<I", data[pos + 4:pos + 8])[0]
        body = data[pos + 8:pos + 8 + size]
        if cid == b"fmt ":
            tag, ch, sr, _, _, bits = struct.unpack("<HHIIHH", body[:16])
            if tag == 0xFFFE and len(body) >= 26:          # WAVE_FORMAT_EXTENSIBLE
                tag = struct.unpack("<H", body[24:26])[0]
            fmt = (tag, ch, sr, bits)
        elif cid == b"data":
            raw = body
        pos += 8 + size + (size & 1)
    if fmt is None or raw is None:
        raise ValueError("WAV ناقص است")
    tag, ch, sr, bits = fmt
    w = bits // 8
    raw = raw[:len(raw) - len(raw) % (w * ch)]
    if tag == 3:
        a = np.frombuffer(raw, "<f4" if bits == 32 else "<f8").astype(np.float32)
    elif tag == 1 and bits == 8:
        a = (np.frombuffer(raw, np.uint8).astype(np.float32) - 128) / 128
    elif tag == 1 and bits == 16:
        a = np.frombuffer(raw, "<i2").astype(np.float32) / 32768
    elif tag == 1 and bits == 24:
        b = np.frombuffer(raw, np.uint8).reshape(-1, 3).astype(np.int32)
        v = b[:, 0] | (b[:, 1] << 8) | (b[:, 2] << 16)
        a = (np.where(v >= 1 << 23, v - (1 << 24), v)).astype(np.float32) / (1 << 23)
    elif tag == 1 and bits == 32:
        a = np.frombuffer(raw, "<i4").astype(np.float32) / 2 ** 31
    else:
        raise ValueError(f"قالبِ WAV پشتیبانی نمی‌شود (نوع {tag}، {bits} بیت)")
    return a.reshape(-1, ch).mean(axis=1).astype(np.float32), sr


def resample(a, sr_in, sr_out):
    """تغییرِ نرخ با FFT (برای صدای گفتار دقیق و بی‌نیاز از scipy)."""
    if sr_in == sr_out or len(a) == 0:
        return a.astype(np.float32)
    n = len(a)
    m = int(round(n * sr_out / sr_in))
    pad = int(0.05 * sr_in)                                  # لبه‌ها موج برنگردند
    x = np.concatenate([np.zeros(pad, np.float32), a, np.zeros(pad, np.float32)])
    X = np.fft.rfft(x)
    mp = int(round(len(x) * sr_out / sr_in))
    Y = np.zeros(mp // 2 + 1, np.complex128)
    k = min(len(X), len(Y))
    Y[:k] = X[:k]
    y = np.fft.irfft(Y, mp) * (mp / len(x))
    s = int(round(pad * sr_out / sr_in))
    return y[s:s + m].astype(np.float32)


def load(path_or_bytes, sr):
    a, r = read_wav(path_or_bytes)
    return resample(a, r, sr)


def to_wav_bytes(a, sr, channels=1):
    """float32 (تک‌کاناله، یا [کانال، نمونه]) ⇒ WAVِ ۱۶بیتی."""
    a = np.asarray(a, np.float32)
    if a.ndim == 2:
        channels = a.shape[0]
        a = a.T.reshape(-1)
    pcm = np.rint(np.clip(a, -1, 1) * 32767).astype("<i2").tobytes()
    buf = io.BytesIO()
    buf.write(b"RIFF" + struct.pack("<I", 36 + len(pcm)) + b"WAVE")
    buf.write(b"fmt " + struct.pack("<IHHIIHH", 16, 1, channels, sr, sr * 2 * channels, 2 * channels, 16))
    buf.write(b"data" + struct.pack("<I", len(pcm)) + pcm)
    return buf.getvalue()


def write_wav(path, a, sr):
    with open(path, "wb") as f:
        f.write(to_wav_bytes(a, sr))
