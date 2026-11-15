#!/usr/bin/env python3
"""Extracts a fixed, curated list of Twemoji graphics (CC-BY 4.0) into motion/remotion/src/emoji.generated.json.

    python motion/tools/gen_emoji.py <folder with @twemoji/svg's *.svg> [out.json]

The emoji set is data, not a dependency, and it is drawn as vector art (not as a font): the same pictures come out on the site's Chrome, on the
node's Windows Chrome and in every re-render (a colour-emoji font would look different on each machine).
Source: @twemoji/svg 15.0.0 (jdecked's Twemoji; packaging MIT), graphics (c) Twitter, Inc and other contributors, licence CC-BY 4.0
(https://creativecommons.org/licenses/by/4.0/) - the attribution is in motion/remotion/ICONS-LICENSE.txt and docs/motion/README-fa.md.
"""
import json
import re
import sys
from pathlib import Path

#: name -> (twemoji file, Persian label)
EMOJI = {
    "fire": ("1f525", "آتش"), "muscle": ("1f4aa", "عضله"), "check": ("2705", "تیکِ سبز"), "star": ("2b50", "ستاره"), "target": ("1f3af", "هدف"),
    "trophy": ("1f3c6", "جام"), "heart": ("2764", "قلب"), "clap": ("1f44f", "تشویق"), "rocket": ("1f680", "موشک"), "bolt": ("26a1", "برق"),
    "hundred": ("1f4af", "صد"), "party": ("1f389", "جشن"), "sparkles": ("2728", "درخشش"), "thumbs-up": ("1f44d", "لایک"), "smile": ("1f60a", "لبخند"),
    "heart-eyes": ("1f60d", "عاشقانه"), "brain": ("1f9e0", "مغز"), "apple": ("1f34e", "سیب"), "salad": ("1f957", "سالاد"), "drop": ("1f4a7", "قطره"),
    "runner": ("1f3c3", "دونده"), "stopwatch": ("23f1", "زمان‌سنج"), "calendar": ("1f4c5", "تقویم"), "gift": ("1f381", "هدیه"), "money": ("1f4b0", "پول"),
    "bell": ("1f514", "زنگ"), "megaphone": ("1f4e3", "اعلان"), "phone": ("1f4f1", "موبایل"), "gem": ("1f48e", "الماس"), "crown": ("1f451", "تاج"),
    "medal": ("1f947", "مدالِ طلا"), "bulb": ("1f4a1", "ایده"), "handshake": ("1f91d", "دست‌دادن"), "eyes": ("1f440", "چشم‌ها"), "point-down": ("1f447", "پایین"),
    "sleep": ("1f634", "خواب"), "sun": ("2600", "خورشید"), "moon": ("1f319", "ماه"), "lifter": ("1f3cb", "وزنه‌بردار"), "cyclist": ("1f6b4", "دوچرخه‌سوار"),
    "green-heart": ("1f49a", "قلبِ سبز"), "chart-up": ("1f4c8", "رشد"), "warning": ("26a0", "هشدار"), "cross": ("274c", "ضربدر"), "tick": ("2714", "علامتِ تیک"),
    "pray": ("1f64f", "قدردانی"), "wave": ("1f44b", "سلام"), "cool": ("1f60e", "خوش‌تیپ"), "wow": ("1f929", "شگفت‌زده"), "thinking": ("1f914", "فکر"),
    "sweat": ("1f605", "عرق"), "clipboard": ("1f4cb", "برنامه"), "memo": ("1f4dd", "یادداشت"), "link": ("1f517", "پیوند"), "lock": ("1f512", "قفل"),
    "shield": ("1f6e1", "سپر"), "package": ("1f4e6", "بسته"), "truck": ("1f69a", "ارسال"), "cart": ("1f6d2", "سبد خرید"), "tag": ("1f3f7", "برچسب"),
    "flexed-bicep": ("1f4aa", "بازو"), "tada": ("1f38a", "کنفتی"), "hourglass": ("23f3", "ساعتِ شنی"), "robot": ("1f916", "ربات"), "camera": ("1f4f7", "دوربین"),
}


def main():
    src = Path(sys.argv[1])
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(__file__).resolve().parents[1] / "remotion" / "src" / "emoji.generated.json"
    data, labels, missing, seen = {}, {}, [], {}
    for name, (code, fa) in EMOJI.items():
        if code in seen:                                   # one picture, one name
            continue
        p = src / f"{code}.svg"
        if not p.is_file():
            missing.append(name)
            continue
        m = re.search(r"<svg[^>]*>(.*)</svg>", p.read_text(encoding="utf-8"), re.S)
        inner = re.sub(r"\s+", " ", m.group(1)).strip() if m else ""
        if inner:
            data[name], labels[name], seen[code] = inner, fa, name
    if missing:
        print("missing:", missing, file=sys.stderr)
    out.write_text(json.dumps({"source": "@twemoji/svg 15.0.0 (jdecked Twemoji)", "license": "CC-BY 4.0 (graphics, Twitter Inc and other contributors); MIT (npm packaging)",
                               "viewBox": "0 0 36 36", "labels": labels, "emoji": data}, ensure_ascii=False, indent=0) + "\n", encoding="utf-8")
    print(len(data), "emoji ->", out, out.stat().st_size, "bytes")


if __name__ == "__main__":
    main()
