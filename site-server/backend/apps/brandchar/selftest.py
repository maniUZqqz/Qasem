"""خودآزمونِ قطعیِ شخصیتِ برند (فقط پردازنده؛ بدونِ دیتابیس، بدونِ گره، بدونِ هوش مصنوعی) + دو پیوند به آزمونِ خودکارِ سرورِ پردازش.

``run_engine`` شخصیتِ «مربیِ چغر» (رنگ‌های برندِ چغر و یک لوگوی ساختگی) را در هر چهار سبک × ژست‌ها × چهار اندازه می‌کشد (فقط شخصیت روی بومِ شفاف) و می‌سنجد
خالی نیست و همهٔ رنگ‌های امضا دیده می‌شود. ``node_spec`` / ``check_node_image`` کارِ واقعیِ کوچکِ ``brandchar.render`` را برای گره می‌سازند و خروجی‌اش را می‌سنجند.
"""
from __future__ import annotations

import io
import time

from PIL import Image, ImageStat

from apps.mascot import selftest as MST
from apps.mascot.engine import brand as B

from .engine import doc as D
from .engine import render as R

CHAGHER_COLOURS = MST.CHAGHER_COLOURS
#: ژست‌های نمونهٔ آزمونِ سریع (ژست‌های متنوع: ایستاده، خم، ورزشی، نشسته و روی زمین) — «بررسیِ ثباتِ کامل» ۲۹ ژست را می‌زند
QUICK_POSES = ("stand", "wave", "thumbs_up", "run_a", "curl", "think", "sit", "lying")
SIZE_KEYS = R.SIZE_KEYS


def chagher_doc(style: str = "flat") -> dict:
    from . import services as S

    return S.new_doc("coach", CHAGHER_COLOURS, "مربی چغر", style=style, logo=True)


def run_engine(*, styles: tuple[str, ...] | None = None, pose_list: tuple[str, ...] | None = None, sizes: tuple[str, ...] | None = None, min_px: float = R.MIN_PX) -> dict:
    t0 = time.time()
    styles = tuple(styles or D.STYLES)
    logo = MST.synthetic_logo()
    failed, total = [], 0
    for st in styles:
        res = R.grid(chagher_doc(st), logo=logo, pose_list=list(pose_list or QUICK_POSES), sizes=tuple(sizes or SIZE_KEYS), min_px=min_px)
        total += res["total"]
        failed += [{**f, "style": st} for f in res["failed"]]
    return {"total": total, "passed": total - len(failed), "failed": failed, "seconds": round(time.time() - t0, 2), "styles": len(styles), "poses": len(pose_list or QUICK_POSES),
            "sizes": len(sizes or SIZE_KEYS), "ok": not failed}


def node_spec() -> dict:
    """کارِ نمونهٔ ``brandchar.render`` (docs/selftests/brandchar.md)."""
    from . import ai_render

    doc = chagher_doc("flat")
    logo = MST.synthetic_logo()
    p = ai_render.build_prompt(doc, "illustrated")
    ref = ai_render.reference_png(doc, "stand", "happy", logo)
    return {"payload": {"prompt": p["positive"], "negative_prompt": p["negative"], "mode": "illustrated", "reference": "reference.png", "identity": "auto", "width": 512, "height": 512,
                        "steps": 4, "guidance": 3.5, "denoise": p["denoise"], "seed": 7, "palette": [r["hex"] for r in D.palette(doc)]}, "files": {"reference.png": ref}}


def check_node_image(raw: bytes) -> tuple[bool, str]:
    if not raw or len(raw) < 4000:
        return False, "تصویر خالی یا خیلی کوچک است (%d بایت)" % len(raw or b"")
    try:
        im = Image.open(io.BytesIO(raw)).convert("RGB")
        spread = max(ImageStat.Stat(im).stddev)
    except Exception as exc:  # noqa: BLE001
        return False, "تصویر خوانده نشد: %s" % exc
    if im.width < 256 or spread < 4:
        return False, "تصویر خراب یا یک‌رنگ است (%dx%d، پراکندگی %.1f)" % (im.width, im.height, spread)
    from . import ai_render

    doc = chagher_doc("flat")
    cut = ai_render.key_background(im)
    ref, _ = R.sticker(doc, pose="stand", expression="happy", logo=MST.synthetic_logo(), height_px=500)
    res = ai_render.consistency(doc, cut, ref)
    note = "رنگ‌های امضا %s · هم‌پوشانیِ سیلوئت %s%s" % (res["palette_score"], res["silhouette"], ("؛ هشدار: " + " ".join(res["notes"])) if res["notes"] else "")
    return True, "%dx%d سالم؛ %s" % (im.width, im.height, note)
