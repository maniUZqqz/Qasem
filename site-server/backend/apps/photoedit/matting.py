"""جداسازیِ سوژه روی پردازندهٔ سرورِ سایت با مدلِ ONNX ِ آمادهٔ روی همین سرور (بی دانلودِ تازه).

مدل: «RVM MobileNetV3» (Robust Video Matting)، ۱۵ مگابایت، از ``data/up3d/downloads`` (یا مسیرِ ``NM_PHOTO_MATTE_MODEL``) با onnxruntime ِ CPU.
این مدل برای **آدم** آموزش دیده؛ روی کالا فقط وقتی خوب است که کالا با زمینه تفاوتِ روشن داشته باشد (کفش روی میز، لباس روی مانکن). به همین دلیل
خروجی همیشه از «دروازهٔ کیفیت» رد می‌شود و اگر مشکوک بود ``ok=False`` می‌دهیم تا طراح روی عکسِ کامل کار کند. جداسازیِ دقیق = «حذفِ پس‌زمینه»
در سرورِ پردازش (BiRefNet).
"""
from __future__ import annotations

import logging
import os
import threading
from pathlib import Path

import numpy as np
from django.conf import settings
from PIL import Image

logger = logging.getLogger(__name__)

NOTE_FA = ("جداسازی با مدلِ سبکِ روی خودِ سرورِ سایت انجام شد؛ این مدل برای آدم‌ها آموزش دیده و روی کالا فقط وقتی کالا با زمینه تفاوتِ روشن داشته باشد "
           "خوب است. برای لبه‌های دقیق «حذفِ پس‌زمینه» با سرورِ پردازش را بزنید.")
MAX_SIDE = 1024
_lock = threading.Lock()
_sess = None
_sess_path: str | None = None


def model_path() -> Path | None:
    cands = [os.environ.get("NM_PHOTO_MATTE_MODEL", ""),
             str(Path(settings.BASE_DIR).parent / "data" / "up3d" / "downloads" / "rvm_mobilenetv3_fp32.onnx")]
    for c in cands:
        if c and Path(c).is_file() and Path(c).stat().st_size > 1_000_000:
            return Path(c)
    return None


def available() -> bool:
    if model_path() is None:
        return False
    try:
        import onnxruntime  # noqa: F401
    except Exception:  # noqa: BLE001
        return False
    return True


def _session():
    global _sess, _sess_path
    p = model_path()
    if p is None:
        return None
    with _lock:
        if _sess is None or _sess_path != str(p):
            import onnxruntime as ort

            so = ort.SessionOptions()
            so.intra_op_num_threads = 2
            _sess = ort.InferenceSession(str(p), sess_options=so, providers=["CPUExecutionProvider"])
            _sess_path = str(p)
        return _sess


def alpha(img: Image.Image, passes: int = 3) -> np.ndarray | None:
    """⇒ آلفای ۰..۱ هم‌اندازهٔ ``img`` یا None (مدل نبود/خطا). مدل بازگشتی است؛ یک عکس را چند بار می‌دهیم تا حالتش جا بیفتد."""
    s = _session()
    if s is None:
        return None
    try:
        rgb = img.convert("RGB")
        W, H = rgb.size
        k = min(1.0, MAX_SIDE / max(W, H))
        w, h = max(32, int(round(W * k / 2) * 2)), max(32, int(round(H * k / 2) * 2))
        small = rgb.resize((w, h), Image.Resampling.BILINEAR) if (w, h) != (W, H) else rgb
        src = (np.asarray(small, dtype=np.float32) / 255.0).transpose(2, 0, 1)[None]
        ratio = np.array([min(1.0, 384.0 / max(w, h))], dtype=np.float32)
        rec = [np.zeros((1, 1, 1, 1), np.float32) for _ in range(4)]
        pha = None
        for _ in range(max(1, passes)):
            out = s.run(None, {"src": src, "r1i": rec[0], "r2i": rec[1], "r3i": rec[2], "r4i": rec[3], "downsample_ratio": ratio})
            pha = out[1][0, 0]
            rec = [out[2], out[3], out[4], out[5]]
        a = np.clip(pha, 0.0, 1.0).astype(np.float32)
        if a.shape != (H, W):
            a = np.asarray(Image.fromarray((a * 255).astype(np.uint8)).resize((W, H), Image.Resampling.BICUBIC), dtype=np.float32) / 255.0
        return a
    except Exception:  # noqa: BLE001
        logger.exception("photoedit.matting: inference failed")
        return None


def quality(a: np.ndarray) -> tuple[bool, float, str]:
    """دروازهٔ کیفیت ⇒ (قابل‌اعتماد؟، پوشش، دلیل). پوششِ خیلی کم/زیاد، سوژهٔ چسبیده به هر چهار لبه یا آلفای «نیمه‌شفافِ سرگردان» = مشکوک."""
    if a is None:
        return False, 0.0, "مدلِ جداسازی در دسترس نبود"
    cov = float((a > 0.5).mean())
    if cov < 0.03:
        return False, cov, "چیزی شبیهِ سوژه پیدا نشد"
    if cov > 0.85:
        return False, cov, "تقریباً همهٔ عکس سوژه شناخته شد"
    mid = float(((a > 0.15) & (a < 0.85)).mean())
    if mid > 0.2 * max(cov, 0.05) + 0.06:
        return False, cov, "لبهٔ سوژه نامطمئن است (زمینهٔ شلوغ)"
    hh, ww = a.shape
    edges = (a[0, :].mean() > 0.5, a[-1, :].mean() > 0.5, a[:, 0].mean() > 0.5, a[:, -1].mean() > 0.5)
    if all(edges):
        return False, cov, "سوژه به هر چهار لبه چسبیده است"
    return True, cov, ""
