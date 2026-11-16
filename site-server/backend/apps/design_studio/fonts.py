"""فونت‌های فارسیِ استودیوی طراحی: همان فونت‌های ادیتورِ عکس (همه SIL OFL 1.1) + مجوزِ هر کدام.

``resolve(key, weight)`` ⇒ مسیرِ فایل (فونتِ ناشناخته ⇒ وزیرمتن). ``catalogue()`` برای پنل و ``license_files(keys)`` برای بسته‌های تحویل
(راهنما: «هنگام تحویلِ سورس فونت‌ها را هم بفرست، به شرطی که مجوز اجازه بدهد» — همه OFL هستند و همراهِ متنِ مجوز می‌روند).
"""
from __future__ import annotations

from pathlib import Path

from apps.photoedit import fontreg, textlayer

HERE = Path(__file__).resolve().parent
LICENSE_DIR = HERE / "licenses"

#: کلید ⇒ مشخصات. «source» همان مبدأِ ثبت‌شده در apps/photoedit/fonts/README-fa.md است.
FONT_INFO = {
    "vazirmatn": {"title": "وزیرمتن", "family": "Vazirmatn", "role": "both", "license": "SIL OFL 1.1",
                  "copyright": "Copyright 2015 The Vazirmatn Project Authors", "source": "github.com/rastikerdar/vazirmatn",
                  "license_file": "Vazirmatn-OFL.txt", "note": "متنِ اصلیِ پیش‌فرض؛ خوانا برای متنِ بلند"},
    "estedad": {"title": "استعداد", "family": "Estedad", "role": "both", "license": "SIL OFL 1.1",
                "copyright": "Copyright 2022 The Estedad Project Authors", "source": "github.com/aminabedi68/Estedad",
                "license_file": "Estedad-OFL.txt", "note": "مدرن و تمیز؛ تیتر و متن"},
    "lalezar": {"title": "لاله‌زار", "family": "Lalezar", "role": "display", "license": "SIL OFL 1.1",
                "copyright": "Copyright 2015 The Lalezar Project Authors", "source": "github.com/BornaIz/Lalezar",
                "license_file": "Lalezar-OFL.txt", "note": "تیترِ درشتِ پرجلوه (یک وزن)"},
    "shabnam": {"title": "شبنم", "family": "Shabnam", "role": "text", "license": "SIL OFL 1.1",
                "copyright": "Copyright (c) 2015 Saber Rastikerdar", "source": "github.com/rastikerdar/shabnam-font",
                "license_file": "Shabnam-LICENSE.txt", "note": "ساده و خوانا برای متنِ ریز"},
    "sahel": {"title": "ساحل", "family": "Sahel", "role": "both", "license": "SIL OFL 1.1",
              "copyright": "Copyright (c) 2016 Saber Rastikerdar", "source": "github.com/rastikerdar/sahel-font",
              "license_file": "Sahel-LICENSE.txt", "note": "گرم و گرد"},
    "samim": {"title": "صمیم", "family": "Samim", "role": "text", "license": "SIL OFL 1.1",
              "copyright": "Copyright (c) 2015 Saber Rastikerdar", "source": "github.com/rastikerdar/samim-font",
              "license_file": "Samim-LICENSE.txt", "note": "رسمی و آرام"},
}
DEFAULT = "vazirmatn"
WEIGHTS = (300, 400, 500, 600, 700, 800)


def available() -> list[str]:
    out = []
    for key in FONT_INFO:
        if key == "vazirmatn":
            if textlayer.font_files():
                out.append(key)
        elif fontreg.path(key, 400):
            out.append(key)
    return out


def known(key) -> bool:
    return isinstance(key, str) and key in available()


def clean(key, fallback: str = DEFAULT) -> str:
    return key if known(key) else fallback


def resolve(key: str, weight: int = 400) -> str:
    """مسیرِ فایلِ ttf برای نزدیک‌ترین وزن؛ فونتِ ناشناخته ⇒ وزیرمتن."""
    return textlayer.font_path_for(key if key != DEFAULT else None, int(weight or 400))


def weights_of(key: str) -> list[int]:
    if key == "vazirmatn":
        return sorted(textlayer.font_files())
    return fontreg.weights(key) if known(key) else []


def catalogue() -> list[dict]:
    rows = []
    for key in available():
        i = FONT_INFO[key]
        rows.append({"key": key, "title": i["title"], "family": i["family"], "role": i["role"], "license": i["license"],
                     "copyright": i["copyright"], "source": i["source"], "note": i["note"], "weights": weights_of(key),
                     "css": f"/api/v1/design/fonts/{key}/{{weight}}.ttf"})
    return rows


def license_text(key: str) -> str:
    """متنِ مجوزِ فونت (کنارِ فایل‌های برنامه یا در licenses/)؛ هرگز خالی برنمی‌گردد."""
    i = FONT_INFO.get(key)
    if not i:
        return ""
    for d in (LICENSE_DIR, Path(fontreg.FONT_DIR)):
        p = d / i["license_file"]
        if p.is_file():
            return p.read_text(encoding="utf-8", errors="replace")
    return (f"{i['copyright']} ({i['source']})\n\nThis Font Software is licensed under the SIL Open Font License, Version 1.1.\n"
            "https://openfontlicense.org\n")


def license_files(keys) -> dict[str, bytes]:
    """{نامِ فایل در بسته: بایت} برای فونت‌های به‌کاررفته (فایل‌های ttf + متنِ مجوز)."""
    out: dict[str, bytes] = {}
    for key in sorted(set(k for k in keys if known(k))):
        i = FONT_INFO[key]
        out[f"licenses/{i['license_file']}"] = license_text(key).encode("utf-8")
        for w in weights_of(key):
            p = Path(resolve(key, w))
            if p.is_file():
                out[f"fonts/{p.name}"] = p.read_bytes()
    return out
