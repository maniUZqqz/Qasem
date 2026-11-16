"""دادهٔ ساختگیِ آزمون و خودآزمون (هیچ دادهٔ واقعیِ آدم‌ها نیست؛ فقط نام‌های نمونه، عکسِ تولیدشده و قیمتِ نمونه)."""
from __future__ import annotations

import os
import random
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw

from . import brand, catalog_doc, images

CHAGHER_COLORS = ["#126f85", "#163f75", "#dbe6ff", "#f7faff", "#1b2b45"]


def make_images(n: int = 6, size=(1400, 1000), folder: str | None = None) -> list[str]:
    """n عکسِ رنگیِ ساختگی ⇒ مرجع‌های «file:<مسیر>»."""
    d = Path(folder or tempfile.mkdtemp(prefix="nm-design-img-"))
    d.mkdir(parents=True, exist_ok=True)
    rnd = random.Random(7)
    refs = []
    for i in range(n):
        im = Image.new("RGB", size, (rnd.randint(30, 200), rnd.randint(60, 200), rnd.randint(60, 200)))
        dr = ImageDraw.Draw(im)
        for _ in range(18):
            x0, y0 = rnd.randint(0, size[0] - 300), rnd.randint(0, size[1] - 250)
            dr.ellipse([x0, y0, x0 + rnd.randint(60, 300), y0 + rnd.randint(60, 240)], outline=(255, 255, 255), width=5)
        p = d / f"img{i}.jpg"
        im.save(p, quality=86)
        refs.append(f"file:{p}")
    return refs


def products(refs: list[str], n: int = 6) -> list[dict]:
    names = ["برنامهٔ نمونهٔ یک", "بستهٔ نمونهٔ دو", "برنامهٔ تکیِ نمونه", "ابزارِ دستیِ نمونه", "کتابخانهٔ نمونه", "محصولِ ششمِ نمونه"]
    prices = [600000, 300000, 0, None, 250000, 1200000]
    out = []
    for i in range(n):
        out.append({"id": i + 1, "name": names[i % len(names)], "sku": f"SKU-{i + 1}", "short": "توضیحِ کوتاهِ نمونه برای آزمونِ چیدمان؛ بیش از یک خط تا شکستنِ متن دیده شود.",
                    "desc": "توضیحِ کاملِ نمونه. " * 8, "price": prices[i % len(prices)], "compare_at": None, "currency": "IRT", "category": "", "category_id": 0,
                    "images": [refs[i % len(refs)]] if refs else [], "attrs": [["ویژگیِ الف", "مقدارِ نمونه"], ["ویژگیِ ب", "مقدارِ دیگر"]], "tags": [], "brand": "نمونه"})
    return out


def info(name: str = "فروشگاهِ نمونه", colors=None, about: str = "این یک توضیحِ نمونه است.\nبرای آزمونِ صفحهٔ متن.") -> catalog_doc.StoreInfo:
    kit = brand.kit(None, {"colors": colors or CHAGHER_COLORS})
    return catalog_doc.StoreInfo(name=name, kit=kit, contacts=[{"label": "وب‌سایت", "value": "example.ir", "kind": "website"}, {"label": "تلفن", "value": "۰۲۱۰۰۰۰۰۰۰۰", "kind": "phone"}],
                                 has_logo=False, persona={"about": about, "tone": "صمیمی و کوتاه"})


def source() -> images.ImageSource:
    return images.ImageSource(allow_files=True)
