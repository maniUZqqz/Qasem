"""هویتِ ماسکوت (شخصیتِ ثابتِ برند) به‌صورتِ داده.

SOURCE: ported from InstAI (maniUZqqz/Instai) instai/render/stick/spec.py @ 82733b0, adapted for NMarketing brand mascots:
  + role-oriented extras (chef hat, apron, chest logo, fitness/shop props) and Persian labels for the UI;
  + the identity is the same idea as in InstAI: the character is DRAWN by code from this spec (colours, head, accessories), so the same
    spec gives the same character in every pose, size and background - by construction, not by hoping an image model remembers.

شخصیت همیشه «اصل» است و یک کارتونِ کشیده‌شده؛ هرگز آدمِ واقعی یا شخصیتِ نام‌دارِ دیگران نیست (کتابخانه فقط رنگ و وسیله می‌دهد).
"""
from __future__ import annotations

import hashlib
from typing import Any

ENGINE_VERSION = 1                       # با هر تغییرِ ظاهریِ موتور بالا برود تا کَشِ قدیمی نخوانده شود

PALETTE_NAMES = {
    "#1f2430": "ink", "#d94a3d": "red", "#2f7fd1": "blue", "#2e9e5b": "green", "#e8a22b": "amber", "#8a4fd1": "violet", "#e0568f": "pink",
    "#1ba0a8": "teal", "#126f85": "teal", "#163f75": "navy", "#f26b21": "orange", "#6b7280": "grey", "#ffffff": "white", "#f4f1ea": "paper", "#b0763c": "brown",
}
LIMB_COLOURS = ["#1f2430", "#d94a3d", "#2f7fd1", "#2e9e5b", "#e8a22b", "#8a4fd1", "#e0568f", "#1ba0a8", "#f26b21"]
HEAD_STYLES = ("round", "tall", "wide")
EYE_STYLES = ("dots", "round", "sleepy")
HATS = ("none", "cap", "beanie", "headband", "tophat", "hood", "chef")
HAIRS = ("none", "tuft", "spikes", "bob", "ponytail")
NECK = ("none", "scarf", "tie", "bowtie")
EXTRAS = ("none", "glasses", "backpack", "mask", "apron")
PROPS = ("none", "torch", "phone", "key", "bat", "sign", "map", "dumbbell", "barbell", "clipboard", "bag", "pan", "box", "tablet", "megaphone")
LOGOS = ("none", "chest")
EXPRESSIONS = ("neutral", "happy", "laugh", "sad", "angry", "scared", "surprised", "smirk")

DEFAULTS: dict[str, Any] = {
    "name": "", "limb_colour": "#1f2430", "head_fill": "#ffffff", "outline": "#1f2430", "line_width": 17,
    "head_style": "round", "eye_style": "round", "hat": "none", "hat_colour": "#d94a3d", "hair": "none", "hair_colour": "#1f2430",
    "neck": "none", "neck_colour": "#d94a3d", "extra": "none", "extra_colour": "#2f7fd1", "prop": "none", "prop_colour": "#e8a22b",
    "logo": "none",
}
CHOICES = {"head_style": HEAD_STYLES, "eye_style": EYE_STYLES, "hat": HATS, "hair": HAIRS, "neck": NECK, "extra": EXTRAS, "prop": PROPS, "logo": LOGOS}
COLOUR_KEYS = ("limb_colour", "head_fill", "outline", "hat_colour", "hair_colour", "neck_colour", "extra_colour", "prop_colour")

#: نامِ فارسیِ گزینه‌ها برای صفحه (کلیدِ دسته ⇒ {گزینه: نام})
CHOICE_LABELS_FA: dict[str, dict[str, str]] = {
    "head_style": {"round": "گرد", "tall": "کشیده", "wide": "پهن"},
    "eye_style": {"dots": "نقطه‌ای", "round": "گرد", "sleepy": "خواب‌آلود"},
    "hat": {"none": "بدونِ کلاه", "cap": "کلاهِ لبه‌دار", "beanie": "کلاهِ بافتنی", "headband": "هدبند", "tophat": "کلاهِ بلند", "hood": "کلاهِ کاپشن", "chef": "کلاهِ آشپز"},
    "hair": {"none": "بدونِ مو", "tuft": "تکه‌مو", "spikes": "موی سیخ‌سیخی", "bob": "موی کوتاهِ گرد", "ponytail": "موی بسته"},
    "neck": {"none": "بدونِ گردن‌آویز", "scarf": "شال", "tie": "کراوات", "bowtie": "پاپیون"},
    "extra": {"none": "بدونِ وسیلهٔ اضافه", "glasses": "عینک", "backpack": "کوله‌پشتی", "mask": "ماسک", "apron": "پیش‌بند"},
    "prop": {"none": "بدونِ وسیله", "torch": "مشعل", "phone": "گوشی", "key": "کلید", "bat": "چماق", "sign": "تابلو", "map": "نقشه", "dumbbell": "دمبل",
             "barbell": "هالتر", "clipboard": "برگهٔ برنامه", "bag": "کیسهٔ خرید", "pan": "تابه", "box": "بسته", "tablet": "تبلت", "megaphone": "بلندگو"},
    "logo": {"none": "بدونِ لوگو", "chest": "لوگوی فروشگاه روی سینه"},
}

# نام‌هایی که برگهٔ مدل چاپ می‌کند (نقش‌های کلیدِ رنگ، نامِ رنگ‌ها، حالت‌های چهره)
FA_WORDS = {
    "limbs": "دست و پا", "head": "سر", "outline": "خط دور", "hat": "کلاه", "hair": "مو", "neck": "شال یا کراوات", "extra": "وسیلهٔ اضافه",
    "ink": "مشکی", "red": "قرمز", "blue": "آبی", "green": "سبز", "amber": "کهربایی", "violet": "بنفش", "pink": "صورتی", "teal": "فیروزه‌ای", "orange": "نارنجی",
    "navy": "سرمه‌ای", "grey": "خاکستری", "white": "سفید", "paper": "کاغذی", "brown": "قهوه‌ای",
    "neutral": "خنثی", "happy": "شاد", "laugh": "خنده", "sad": "غمگین", "angry": "عصبانی", "scared": "ترسیده", "surprised": "متعجب", "smirk": "پوزخند",
}
EXPRESSION_LABELS_FA = {k: FA_WORDS[k] for k in EXPRESSIONS}


def fa_word(key: str) -> str:
    """نامِ فارسیِ کلیدی که برگه چاپ می‌کند؛ کلیدِ ناشناخته همان‌طور که هست."""
    return FA_WORDS.get(key, key)


def _hex(v: Any, default: str) -> str:
    s = str(v or "").strip().lower()
    if len(s) == 4 and s[0] == "#":
        s = "#" + "".join(c * 2 for c in s[1:])
    ok = len(s) == 7 and s[0] == "#" and all(c in "0123456789abcdef" for c in s[1:])
    return s if ok else default


def normalize(data: dict | None, *, name: str = "") -> dict:
    """یک spec کامل و امن: کلیدهای ناشناخته می‌افتند، گزینه‌ها محدود و رنگ‌ها اعتبارسنجی می‌شوند؛ ظاهرِ جاافتاده از روی نام ساخته می‌شود تا
    دو شخصیتِ یک فروشگاه یکسان درنیایند."""
    d = dict(data or {})
    out = dict(DEFAULTS)
    out["name"] = str(d.get("name") or name or "")[:80]
    seed = int(hashlib.sha256((out["name"] or "x").encode("utf-8")).hexdigest()[:8], 16)
    if "limb_colour" not in d:
        out["limb_colour"] = LIMB_COLOURS[seed % len(LIMB_COLOURS)]
    for k in COLOUR_KEYS:
        if k in d:
            out[k] = _hex(d[k], out[k])
    for k, allowed in CHOICES.items():
        if d.get(k) in allowed:
            out[k] = d[k]
    if "hat" not in d and "neck" not in d and "extra" not in d and name:      # ظاهرِ اولِ یک شخصیتِ تازه
        out["neck"] = ("scarf", "tie", "none")[(seed >> 3) % 3]
        out["hat"] = ("none", "cap", "beanie")[(seed >> 5) % 3]
        out["neck_colour"] = LIMB_COLOURS[(seed >> 7) % len(LIMB_COLOURS) or 1] if out["neck"] != "none" else out["neck_colour"]
    try:
        out["line_width"] = max(10, min(26, int(d.get("line_width", out["line_width"]))))
    except (TypeError, ValueError):
        pass
    return out


def hex_rgba(h: str, a: int = 255) -> tuple[int, int, int, int]:
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), a


def colour_name(h: str) -> str:
    """نزدیک‌ترین نامِ رنگ در پالتِ کوچکِ استودیو (برای متنِ هویت و برگهٔ مدل)."""
    r, g, b, _ = hex_rgba(h)
    best, dist = "ink", 10 ** 9
    for k, nm in PALETTE_NAMES.items():
        kr, kg, kb, _ = hex_rgba(k)
        d = (r - kr) ** 2 + (g - kg) ** 2 + (b - kb) ** 2
        if d < dist:
            best, dist = nm, d
    return best


def palette(spec: dict) -> list[dict]:
    """«کلیدِ رنگِ» شخصیت: [{role, hex, name}] برای هر رنگی که واقعاً کشیده می‌شود."""
    s = normalize(spec)
    rows = [("limbs", s["limb_colour"]), ("head", s["head_fill"]), ("outline", s["outline"])]
    if s["hat"] != "none":
        rows.append(("hat", s["hat_colour"]))
    if s["hair"] != "none":
        rows.append(("hair", s["hair_colour"]))
    if s["neck"] != "none":
        rows.append(("neck", s["neck_colour"]))
    if s["extra"] != "none":
        rows.append(("extra", s["extra_colour"]))
    return [{"role": role, "hex": hx, "name": colour_name(hx)} for role, hx in rows]


def _a(word: str) -> str:
    return "an" if word[:1].lower() in "aeiou" else "a"


def anchor_text(spec: dict) -> str:
    """توصیفِ انگلیسیِ هویتِ شخصیت: هر بار با همان کلمه‌ها، برای هر درخواستی که باید همین شخصیت را نشان بدهد (مثلاً مدلِ تصویرسازِ استودیو)."""
    s = normalize(spec)
    limb, head = colour_name(s["limb_colour"]), colour_name(s["head_fill"])
    bits = [f"{_a(limb)} {limb}-limbed stick figure with {_a(head)} {head} {s['head_style']} head, thick {colour_name(s['outline'])} outlines,"
            f" {'dot' if s['eye_style'] == 'dots' else s['eye_style']} eyes"]
    if s["hat"] != "none":
        hat = colour_name(s["hat_colour"])
        bits.append(f"{_a(hat)} {hat} {s['hat']}")
    if s["hair"] != "none":
        bits.append(f"{colour_name(s['hair_colour'])} {s['hair']} hair")
    if s["neck"] != "none":
        neck = colour_name(s["neck_colour"])
        bits.append(f"{_a(neck)} {neck} {s['neck']}")
    if s["extra"] != "none":
        bits.append(f"{s['extra']}")
    return ", ".join(bits)


def spec_hash(spec: dict) -> str:
    s = normalize(spec)
    return hashlib.sha256((repr(sorted(s.items())) + f"|e{ENGINE_VERSION}").encode()).hexdigest()[:12]
