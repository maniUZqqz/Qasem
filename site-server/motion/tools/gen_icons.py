#!/usr/bin/env python3
"""Extracts a fixed, curated list of Lucide icons (ISC licence) into motion/remotion/src/icons.generated.json.

    python motion/tools/gen_icons.py <folder with lucide-static's icons/*.svg> [out.json]

The icon set is data, not a dependency: the engine renders the inner SVG markup with a stroke that follows the style's ink colour.
Source: lucide-static 0.468.0 (https://lucide.dev), licence ISC (+ MIT for the Feather portions) - see motion/remotion/ICONS-LICENSE.txt.
"""
import json
import re
import sys
from pathlib import Path

#: name -> Persian label (what the model and the panel call it)
ICONS = {
    "dumbbell": "دمبل", "heart": "قلب", "heart-pulse": "ضربان", "flame": "شعله", "zap": "انرژی", "trophy": "جام", "target": "هدف",
    "timer": "زمان‌سنج", "clock": "ساعت", "calendar": "تقویم", "circle-check": "تیک", "star": "ستاره", "users": "گروه", "user": "کاربر",
    "phone": "تلفن", "mail": "ایمیل", "map-pin": "مکان", "shopping-cart": "سبد خرید", "gift": "هدیه", "tag": "برچسب", "percent": "درصد",
    "truck": "ارسال", "shield-check": "امنیت", "lock": "قفل", "thumbs-up": "پسندیدن", "sparkles": "درخشش", "rocket": "موشک", "crown": "تاج",
    "bell": "زنگ", "camera": "دوربین", "play": "پخش", "message-circle": "پیام", "send": "ارسال پیام", "globe": "وب", "link": "پیوند",
    "at-sign": "آدرس", "chart-column": "نمودار", "trending-up": "رشد", "apple": "سیب", "utensils": "غذا", "droplet": "آب", "sun": "خورشید",
    "moon": "ماه", "battery-charging": "شارژ", "brain": "مغز", "lightbulb": "ایده", "wallet": "کیف پول", "credit-card": "کارت", "smartphone": "موبایل",
    "laptop": "لپ‌تاپ", "award": "نشان", "medal": "مدال", "activity": "فعالیت", "footprints": "قدم", "scale": "ترازو", "bike": "دوچرخه",
    "mountain": "کوه", "leaf": "برگ", "coffee": "قهوه", "house": "خانه", "settings": "تنظیمات", "search": "جست‌وجو", "download": "دانلود",
    "share-2": "اشتراک", "bookmark": "نشان", "eye": "چشم", "handshake": "همکاری", "badge-check": "تأیید", "gauge": "سرعت", "list-checks": "فهرست",
    "clipboard-list": "برنامه", "bot": "ربات", "wand-sparkles": "جادو", "megaphone": "اعلان", "package": "بسته", "store": "فروشگاه",
    "graduation-cap": "آموزش", "book-open": "کتاب", "video": "ویدیو", "mic": "میکروفون", "music": "موسیقی", "image": "تصویر", "layers": "لایه",
    "palette": "رنگ", "pen-tool": "طراحی", "code": "کد", "check": "علامت تیک", "x": "ضربدر", "arrow-left": "پیکان چپ", "arrow-right": "پیکان راست",
    "arrow-up": "پیکان بالا", "arrow-down": "پیکان پایین", "plus": "به‌اضافه", "minus": "منها", "info": "اطلاعات", "circle-alert": "هشدار",
    "circle-x": "ردّ", "hand-heart": "مهربانی", "salad": "سالاد", "beef": "پروتئین", "egg": "تخم‌مرغ", "wheat": "نان و غلات", "bed": "خواب",
    "sunrise": "صبح", "waves": "شنا", "volleyball": "ورزش", "person-standing": "ایستاده",
}


def main():
    src = Path(sys.argv[1])
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(__file__).resolve().parents[1] / "remotion" / "src" / "icons.generated.json"
    data, missing = {}, []
    for name in ICONS:
        p = src / f"{name}.svg"
        if not p.is_file():
            missing.append(name)
            continue
        txt = p.read_text(encoding="utf-8")
        m = re.search(r"<svg[^>]*>(.*)</svg>", txt, re.S)
        inner = re.sub(r"\s+", " ", m.group(1)).strip() if m else ""
        inner = re.sub(r"<!--.*?-->", "", inner).strip()
        if inner:
            data[name] = inner
    if missing:
        print("missing:", missing, file=sys.stderr)
    out.write_text(json.dumps({"source": "lucide-static 0.468.0", "license": "ISC (Lucide) + MIT (Feather portions)", "labels": {k: ICONS[k] for k in data}, "icons": data},
                              ensure_ascii=False, indent=0) + "\n", encoding="utf-8")
    print(len(data), "icons ->", out)


if __name__ == "__main__":
    main()
