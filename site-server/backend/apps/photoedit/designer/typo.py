"""تایپوگرافیِ طراحیِ خودکار: مقیاسِ اندازه، جاگیریِ متن بی‌سرریز (فارسیِ راست‌به‌چپ با همان موتورِ سرور)، رقم و قیمتِ فارسی.

اندازه‌ها همه «کسری از پهنای بوم» اند (مثلِ لایه‌های ادیتور). متن با ``textlayer.layout`` اندازه‌گیری می‌شود؛ یعنی
همان Pillow + raqm ای که خروجی را می‌کشد؛ پس «جا شد» یعنی در خروجی هم جا می‌شود.
"""
from __future__ import annotations

import math
import re

from .. import textlayer

#: مقیاسِ مدولار (سوم بزرگ ×۱٫۳۳۳) از اندازهٔ پایهٔ ۳٪ پهنا (≈ ۳۲px در بومِ ۱۰۸۰)
RATIO = 1.333
BASE = 0.030
STEPS = {"caption": 0, "sub": 1, "cta": 1, "badge": 1, "body": 1, "title": 3, "price": 3, "hero": 4, "display": 5}
#: کمترین اندازه‌ای که روی گوشی هنوز خوانا است (کسری از پهنا)؛ زیرش «ریز» حساب می‌شود
MIN_LEGIBLE = 0.024
MIN_KEY_LEGIBLE = 0.032     # متنِ کلیدی (تیتر، قیمت)

_FA = "۰۱۲۳۴۵۶۷۸۹"
_EN = "0123456789"
_TO_FA = str.maketrans(_EN + "٠١٢٣٤٥٦٧٨٩", _FA * 2)
_TO_EN = str.maketrans(_FA + "٠١٢٣٤٥٦٧٨٩", _EN * 2)


def role_size(role: str, scale: float = 1.0) -> float:
    """اندازهٔ نقش در مقیاسِ تایپی (کسری از پهنای بوم)."""
    return round(BASE * (RATIO ** STEPS.get(role, 1)) * scale, 4)


def fa_digits(s: str) -> str:
    return str(s).translate(_TO_FA)


def en_digits(s: str) -> str:
    return str(s).translate(_TO_EN)


def group3(n: int) -> str:
    """۱۲۵۰۰۰۰ ⇒ «۱٬۲۵۰٬۰۰۰» (جداکنندهٔ هزارگانِ فارسی)."""
    return fa_digits(f"{int(n):,}".replace(",", "٬"))


def parse_price(text: str) -> int | None:
    """«۴۵۰ هزار تومان»، «1.2 میلیون»، «450,000»، «۴۵۰٬۰۰۰ ریال» ⇒ تومان (ریال تقسیم بر ۱۰). بی‌عدد ⇒ None."""
    t = en_digits(str(text or "")).replace("٬", "").replace(",", "").replace("٫", ".").replace("،", "")
    m = re.search(r"(\d+(?:\.\d+)?)\s*(هزار|میلیون|میلیارد)?", t)
    if not m:
        return None
    val = float(m.group(1))
    mult = {"هزار": 1_000, "میلیون": 1_000_000, "میلیارد": 1_000_000_000}.get(m.group(2) or "", 1)
    n = val * mult
    if "ریال" in t and "تومان" not in t:
        n /= 10
    n = int(round(n))
    return n if n > 0 else None


def format_price(value, unit: str = "تومان") -> str:
    """عدد یا متن ⇒ «۱٬۲۵۰٬۰۰۰ تومان»؛ نشد ⇒ همان متنِ ورودی با ارقامِ فارسی."""
    n = value if isinstance(value, int) else parse_price(str(value))
    if n is None:
        return fa_digits(str(value or "").strip())
    return f"{group3(n)} {unit}".strip()


def shorten(text: str, max_chars: int) -> tuple[str, bool]:
    """کوتاه‌کردنِ متنِ بلند در مرزِ کلمه با «…» (فارسی: کلمه‌ها از آخر حذف می‌شوند)."""
    t = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(t) <= max_chars:
        return t, False
    words = t.split(" ")
    while words and len(" ".join(words)) + 1 > max_chars:
        words.pop()
    return (" ".join(words) + "…") if words else t[: max(1, max_chars - 1)] + "…", True


def measure(layer: dict, canvas_w: int) -> dict:
    return textlayer.layout(layer, canvas_w)


def fit_text(layer: dict, canvas_w: int, max_w_px: float, max_h_px: float, *, min_size: float = MIN_LEGIBLE,
             max_lines: int = 4, shrink: float = 0.93) -> dict:
    """متنِ ``layer`` را در جعبهٔ max_w×max_h (پیکسل) جا می‌دهد: اول اندازه را کم می‌کند (تا ``min_size``)، اگر باز هم
    جا نشد متن را با «…» کوتاه می‌کند. ``layer["size"]`` و ``layer["width"]`` را عوض می‌کند و ``layer["text"]`` را فقط
    در صورتِ کوتاه‌شدن. ⇐ {fits, shrunk, truncated, size, lines, block_w, block_h, overflow}.

    هیچ کلمه‌ای وسطِ خط شکسته نمی‌شود؛ تک‌کلمهٔ درازتر از جعبه هم فقط با کوچک‌شدنِ اندازه جا می‌شود.
    """
    start = float(layer["size"])
    layer["width"] = round(max_w_px / canvas_w, 4)
    size = start
    truncated = False
    text0 = str(layer.get("text") or "")
    tries = 0
    while True:
        layer["size"] = round(size, 4)
        m = measure(layer, canvas_w)
        widest = max(m["widths"] + [0.0])
        ok = len(m["lines"]) <= max_lines and m["block_h"] <= max_h_px + 0.5 and widest <= max_w_px + 0.5
        if ok:
            break
        tries += 1
        if size > min_size + 1e-6 and tries < 60:
            size = max(min_size, size * shrink)
            continue
        # کوچک‌ترین اندازه هم جا نشد ⇒ کوتاه‌کردنِ متن
        words = str(layer["text"]).split()
        if len(words) <= 1:
            break
        words.pop()
        layer["text"] = " ".join(words).rstrip("،,:;") + "…"
        truncated = True
        if tries > 120:
            break
    m = measure(layer, canvas_w)
    widest = max(m["widths"] + [0.0])
    fits = len(m["lines"]) <= max_lines and m["block_h"] <= max_h_px + 0.5 and widest <= max_w_px + 0.5
    return {"fits": fits, "shrunk": layer["size"] < start - 1e-6, "truncated": truncated and layer["text"] != text0,
            "size": layer["size"], "lines": m["lines"], "block_w": m["block_w"], "block_h": m["block_h"], "overflow": not fits,
            "tight_w": widest}


def tighten_width(layer: dict, canvas_w: int, slack: float = 1.04, cap_px: float | None = None) -> None:
    """پهنای جعبه را به پهنای واقعیِ بلندترین خط (+ کمی جا) می‌رساند — برای کادرِ پشتِ متن که باید به متن بچسبد.
    ``cap_px``: از این بیشتر نمی‌شود (جعبهٔ جا)."""
    m = measure(layer, canvas_w)
    w = max(m["widths"] + [1.0]) * slack
    if cap_px is not None:
        w = min(w, cap_px)
    layer["width"] = round(min(4.0, w / canvas_w), 4)
