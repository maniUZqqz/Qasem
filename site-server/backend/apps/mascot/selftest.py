"""خودآزمونِ قطعیِ ماسکوت (فقط پردازنده؛ بدونِ دیتابیس، بدونِ سرورِ پردازش، بدونِ هوش مصنوعی).

``grid`` برای N ژست × ۴ اندازه (هر اندازه با چیدمانِ واقعیِ خودش)، فقط شخصیت را روی بومِ شفاف می‌کشد و می‌سنجد: خالی نیست و همهٔ رنگ‌های امضا (کلیدِ رنگ) دیده می‌شوند.
``run`` همین را برای ماسکوتِ «مربیِ چغر» (رنگ‌های برندِ چغر و یک لوگوی ساختگی) می‌زند؛ آزمونِ خودکارِ سرورِ پردازش (apps.compute.selftests.mascot)،
فرمانِ ``manage.py mascot_selftest`` و دکمهٔ «بررسیِ ثبات» همین تابع را به کار می‌برند.
"""
from __future__ import annotations

import time

from PIL import Image, ImageDraw

from .engine import brand as B
from .engine import compose, poses, qa
from .engine import spec as S

#: رنگ‌های برندِ چغر (docs/chagher/brand-facts-fa.md §۵)
CHAGHER_COLOURS = ["#126F85", "#163F75"]
SIZE_KEYS = tuple(compose.SIZES)


def synthetic_logo() -> Image.Image:
    """لوگوی ساختگیِ آزمون (دو متوازی‌الاضلاعِ رنگی) تا آزمون به فایلِ فروشگاه نیاز نداشته باشد."""
    logo = Image.new("RGBA", (200, 200), (0, 0, 0, 0))
    d = ImageDraw.Draw(logo)
    d.polygon([(30, 150), (90, 30), (120, 30), (60, 150)], fill="#126f85")
    d.polygon([(100, 150), (160, 30), (190, 30), (130, 150)], fill="#163f75")
    return logo


MIN_PX = 0.5           # کوچک‌ترین مقیاسِ تصویرِ آزمون: پیکسلِ بوم در هر پیکسلِ طراحی (زیرِ این، باریک‌ترین جزءها دیگر پیکسلِ تک‌رنگ ندارند)


def canvas_for(size: str, min_px: float = MIN_PX) -> tuple[int, int]:
    """کوچک‌ترین بومِ این اندازه که شخصیت در آن دست‌کم ``min_px`` مقیاس دارد (بزرگ‌تر از اندازهٔ واقعی نمی‌شود)."""
    w0, h0 = compose.size_of(size)
    frac = compose.SIZES[size]["figure"]["height"]
    h = min(h0, max(160, round(min_px * 900 / frac)))
    return max(120, round(h * w0 / h0)), h


def grid(spec: dict, *, logo: Image.Image | None = None, pose_list: list[str] | None = None, sizes: tuple[str, ...] | None = None, min_px: float = MIN_PX,
         expression: str = "happy") -> dict:
    """هر ژست × هر اندازه (با همان چیدمانِ واقعیِ آن اندازه، کوچک‌شده تا ``min_px``). ⇒ {total، passed، failed[{pose، size، notes}]، seconds، poses، sizes}."""
    t0 = time.time()
    s = S.normalize(spec)
    pal = S.palette(s)
    pose_list = list(pose_list or poses.names())
    sizes = tuple(sizes or SIZE_KEYS)
    failed, total = [], 0
    for size in sizes:
        w, h = canvas_for(size, min_px)
        base = compose.actor_defaults(size)
        for pz in pose_list:
            total += 1
            shot = compose.figure_layer({"spec": s, "pose": pz, "expression": expression, **base}, w, h, logo=logo, inside=0.02)
            res = qa.check_figure(shot.layer, pal)
            if not res["ok"]:
                failed.append({"pose": pz, "size": size, "notes": [qa.note_fa(n) for n in res["notes"]]})
    return {"total": total, "passed": total - len(failed), "failed": failed, "seconds": round(time.time() - t0, 2), "poses": len(pose_list), "sizes": len(sizes), "ok": not failed}


def run(*, pose_list: list[str] | None = None, sizes: tuple[str, ...] | None = None, min_px: float = MIN_PX) -> dict:
    spec = B.spec_from_brand("coach", CHAGHER_COLOURS, "مربی چغر", logo=True)
    return grid(spec, logo=synthetic_logo(), pose_list=pose_list, sizes=sizes, min_px=min_px)
