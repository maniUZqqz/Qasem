"""قطعه‌های آدمک‌چوبی (فقط Pillow): بدن، سر، دست و پا، چهره، کلاه، شال، وسیله‌ها، شستِ «👍» و نشانِ لوگو روی سینه.

SOURCE: ported from InstAI (maniUZqqz/Instai) instai/render/stick/parts.py @ 82733b0, adapted for NMarketing brand mascots:
  + part pictures stay in memory (no files), drawn 4x and delivered at 2x design size so a large sticker stays sharp;
  + chest logo tile, chef hat, apron, thumb for the thumbs-up, and marketing / fitness props (dumbbell, clipboard, shopping bag, pan, parcel, tablet, megaphone);
  + the rig is built straight into engine/rig.py's ``Rig`` (the puppet JSON rig of InstAI is not used).

شخصیت رو به راست کشیده می‌شود؛ برای رو به چپ، کلِ شخصیت آینه می‌شود (stage.py).
"""
from __future__ import annotations

from PIL import Image, ImageDraw, ImageOps

from . import spec as S
from .rig import MOUTH_SHAPES, Part, Rig

SS = 4                       # ضریبِ نمونه‌برداریِ بیشتر هنگامِ کشیدن (لبه‌های نرم)
Q = 2                        # تصویرِ هر قطعه با این ضریب از اندازهٔ طراحی تحویل داده می‌شود
DESIGN = (600, 900)
HIP = (300, 540)
ANCHOR = (300, 862)
TORSO, UPPER, FORE, THIGH, SHIN = 240, 118, 108, 160, 150
BODY_CX, BODY_TOP = 110, 40            # محورِ بدن در تصویرِ قطعهٔ بدن
CHEST_TILE = 74                        # اندازهٔ کاشیِ لوگو روی سینه (پیکسلِ طراحی)

_EXPR = {   # حالت ⇒ (ابرو، چشم، نوعِ دهانِ X، شکلِ دهان وقتی صحبت نمی‌کند)
    "neutral": ("flat", "round", "flat", "X"), "happy": ("up", "round", "smile", "X"), "laugh": ("up", "happy", "smile", "D"),
    "sad": ("sad", "down", "frown", "X"), "angry": ("angry", "narrow", "clench", "X"), "scared": ("worry", "wide", "flat", "E"),
    "surprised": ("high", "wide", "flat", "F"), "smirk": ("smirk", "round", "smirk", "X"),
}

#: وسیله‌ای که همیشه صاف (عمودی) در دست می‌ماند؛ «forward» یعنی رو به جلو (بلندگو)
PROP_MODE = {"megaphone": "forward"}


def expression_parts(expression: str) -> tuple[str, str, str, str]:
    return _EXPR.get(expression) or _EXPR["neutral"]


def _canvas(w: int, h: int):
    im = Image.new("RGBA", (w * SS, h * SS), (0, 0, 0, 0))
    return im, ImageDraw.Draw(im)


def _done(im: Image.Image, w: int, h: int) -> Image.Image:
    return im.resize((w * Q, h * Q), Image.LANCZOS)


def _s(pts):
    return [(x * SS, y * SS) for x, y in pts]


def _line(d, pts, width, fill):
    """خطِ شکسته با سرِ گرد و مفصلِ گرد."""
    d.line(_s(pts), fill=fill, width=int(width * SS), joint="curve")
    r = width / 2
    for x, y in (pts[0], pts[-1]):
        d.ellipse([(x - r) * SS, (y - r) * SS, (x + r) * SS, (y + r) * SS], fill=fill)


def _ell(d, box, fill=None, outline=None, width=0):
    d.ellipse([v * SS for v in box], fill=fill, outline=outline, width=int(width * SS))


def _rr(d, box, r, fill=None, outline=None, width=0):
    d.rounded_rectangle([v * SS for v in box], radius=r * SS, fill=fill, outline=outline, width=int(width * SS))


def _poly(d, pts, fill=None, outline=None, width=0):
    d.polygon(_s(pts), fill=fill, outline=outline)
    if outline and width:
        d.line(_s(pts + [pts[0]]), fill=outline, width=int(width * SS), joint="curve")


def _head_dims(style: str) -> tuple[float, float]:
    return {"round": (78, 78), "tall": (68, 90), "wide": (90, 70)}[style]


# ------------------------------------------------------------------ بدن و دست و پا

def _chest_tile(im: Image.Image, d, s: dict, logo: Image.Image, mirror: bool, cy: float) -> None:
    """کاشیِ سفیدِ گوشه‌گرد با لوگوی فروشگاه روی سینه. ``mirror``: وقتی کلِ شخصیت آینه می‌شود، لوگو از قبل آینه می‌شود تا در پایان درست دیده شود."""
    half = CHEST_TILE / 2
    cx = BODY_CX
    _rr(d, (cx - half, cy - half, cx + half, cy + half), 12, (255, 255, 255, 255), S.hex_rgba(s["outline"]), 4)
    inner = int((CHEST_TILE - 14) * SS)
    pic = ImageOps.contain(logo.convert("RGBA"), (inner, inner), Image.LANCZOS)
    if mirror:
        pic = ImageOps.mirror(pic)
    im.alpha_composite(pic, (int((cx) * SS - pic.width / 2), int(cy * SS - pic.height / 2)))


def _body(s: dict, logo: Image.Image | None = None, mirror_logo: bool = False) -> Image.Image:
    w, h = 220, 300
    im, d = _canvas(w, h)
    c, W = S.hex_rgba(s["limb_colour"]), s["line_width"]
    oc = S.hex_rgba(s["outline"])
    top, hip = BODY_TOP, BODY_TOP + TORSO
    cx = BODY_CX
    if s["extra"] == "backpack":                                   # پشتِ تنه
        _rr(d, (cx - 62, top + 14, cx - 6, top + 150), 14, S.hex_rgba(s["extra_colour"]), oc, 5)
        _line(d, [(cx - 10, top + 30), (cx - 8, top + 110)], 8, oc)
    _line(d, [(cx, top), (cx, hip)], W, c)
    if s["extra"] == "apron":                                      # پیش‌بند: از گردن تا بالای زانو
        ac = S.hex_rgba(s["extra_colour"])
        _poly(d, [(cx - 30, top + 30), (cx + 30, top + 30), (cx + 44, top + 214), (cx - 44, top + 214)], ac, oc, 4)
        _line(d, [(cx - 20, top + 30), (cx - 8, top + 4)], 6, oc)
        _line(d, [(cx + 20, top + 30), (cx + 8, top + 4)], 6, oc)
    if s["neck"] == "scarf":
        nc = S.hex_rgba(s["neck_colour"])
        _rr(d, (cx - 24, top - 4, cx + 24, top + 26), 12, nc, oc, 4)
        _poly(d, [(cx - 12, top + 20), (cx - 40, top + 62), (cx - 22, top + 70), (cx - 2, top + 28)], nc, oc, 4)
    elif s["neck"] == "tie":
        nc = S.hex_rgba(s["neck_colour"])
        _poly(d, [(cx - 14, top + 22), (cx + 14, top + 22), (cx + 9, top + 38), (cx + 22, top + 102), (cx, top + 124), (cx - 22, top + 102), (cx - 9, top + 38)],
              nc, oc, 3)      # کراوات: زیرِ جای شانه تا بازوی بالا رفته رویش نیفتد
    elif s["neck"] == "bowtie":
        nc = S.hex_rgba(s["neck_colour"])
        _poly(d, [(cx, top + 14), (cx - 30, top - 2), (cx - 30, top + 30)], nc, oc, 3)
        _poly(d, [(cx, top + 14), (cx + 30, top - 2), (cx + 30, top + 30)], nc, oc, 3)
        _ell(d, (cx - 8, top + 6, cx + 8, top + 22), nc, oc, 3)
    if logo is not None and s.get("logo") == "chest":
        # جای کاشی: بالای سینه (مثلِ یک نشان)؛ زیرِ کراوات یا دنبالهٔ شال می‌نشیند تا آن‌ها را نپوشاند
        _chest_tile(im, d, s, logo, mirror_logo, top + {"tie": 161, "scarf": 141}.get(s["neck"], 72))
    return _done(im, w, h)


def _limb(s: dict, length: float, *, hand: bool = False, foot: bool = False) -> Image.Image:
    w, h = 80, int(length + 36)
    im, d = _canvas(w, h)
    c, W = S.hex_rgba(s["limb_colour"]), s["line_width"]
    x = 40
    y0, y1 = 14, 14 + length
    _line(d, [(x, y0), (x, y1)], W, c)
    if hand:
        _ell(d, (x - 11, y1 - 5, x + 11, y1 + 17), S.hex_rgba(s["head_fill"]), S.hex_rgba(s["outline"]), 4)
    if foot:
        _line(d, [(x, y1), (x + 34, y1 + 2)], W, c)
    return _done(im, w, h)


def _thumb(s: dict) -> Image.Image:
    """شستِ بالا (برای ژستِ «👍»): کپسولِ کوچکِ سفید با خطِ دور، در امتدادِ ساعد."""
    w, h = 60, 80
    im, d = _canvas(w, h)
    oc, fill = S.hex_rgba(s["outline"]), S.hex_rgba(s["head_fill"])
    pts = [(30, 14), (30, 52)]
    _line(d, pts, 21, oc)
    _line(d, pts, 12, fill)
    return _done(im, w, h)


def _prop(s: dict, kind: str | None = None) -> Image.Image | None:
    kind = kind or s["prop"]
    if kind in ("none", "barbell"):                        # هالتر را صحنه بینِ دو دست می‌کشد (stage.py)
        return None
    w, h = 220, 220
    im, d = _canvas(w, h)
    pc, oc = S.hex_rgba(s["prop_colour"]), S.hex_rgba(s["outline"])
    steel, paper = S.hex_rgba("#4b5563"), S.hex_rgba("#f4f1ea")
    cx = 110                                               # نقطهٔ گرفتن = (110، 150)
    if kind == "torch":
        _rr(d, (cx - 12, 70, cx + 12, 160), 8, steel, oc, 4)
        _poly(d, [(cx - 22, 70), (cx + 22, 70), (cx + 36, 30), (cx - 36, 30)], pc, oc, 4)
    elif kind == "phone":
        _rr(d, (cx - 22, 40, cx + 22, 130), 8, S.hex_rgba("#2b3040"), oc, 4)
        _rr(d, (cx - 16, 50, cx + 16, 116), 4, S.hex_rgba("#bfe3ff"))
    elif kind == "key":
        _ell(d, (cx - 22, 30, cx + 22, 74), None, pc, 9)
        _line(d, [(cx, 74), (cx, 150)], 9, pc)
        _line(d, [(cx, 128), (cx + 20, 128)], 8, pc)
        _line(d, [(cx, 144), (cx + 14, 144)], 8, pc)
    elif kind == "bat":
        _poly(d, [(cx - 8, 150), (cx + 8, 150), (cx + 18, 20), (cx - 18, 20)], S.hex_rgba("#b0763c"), oc, 4)
    elif kind == "sign":
        _line(d, [(cx, 70), (cx, 190)], 9, S.hex_rgba("#b0763c"))
        _rr(d, (cx - 56, 10, cx + 56, 80), 8, paper, oc, 5)
    elif kind == "map":
        _poly(d, [(cx - 44, 50), (cx + 44, 40), (cx + 44, 140), (cx - 44, 150)], paper, oc, 4)
        _line(d, [(cx - 26, 80), (cx - 4, 100), (cx + 24, 76)], 5, pc)
    elif kind == "dumbbell":                               # دمبل: میله + دو صفحهٔ بزرگ + دو صفحهٔ کوچک
        _rr(d, (cx - 44, 142, cx + 44, 158), 6, steel, oc, 3)
        for sgn in (-1, 1):
            x0 = cx + sgn * 38
            _rr(d, (min(x0, x0 + sgn * 20), 112, max(x0, x0 + sgn * 20), 188), 8, pc, oc, 4)
            x1 = x0 + sgn * 20
            _rr(d, (min(x1, x1 + sgn * 11), 126, max(x1, x1 + sgn * 11), 174), 5, pc, oc, 4)
    elif kind == "clipboard":                              # برگهٔ برنامه: تخته + برگهٔ سفید + گیره + خط‌ها
        _rr(d, (cx - 42, 28, cx + 42, 168), 8, pc, oc, 4)
        _rr(d, (cx - 33, 48, cx + 33, 158), 4, paper, oc, 3)
        _rr(d, (cx - 18, 20, cx + 18, 42), 5, steel, oc, 3)
        for k in range(5):
            _line(d, [(cx - 22, 66 + k * 18), (cx + 22 - (k % 2) * 12, 66 + k * 18)], 5, S.hex_rgba("#9aa3b2"))
    elif kind == "bag":                                    # کیسهٔ خرید: دستهٔ کمانی + بدنهٔ ذوزنقه
        d.arc([(cx - 26) * SS, 104 * SS, (cx + 26) * SS, 172 * SS], 180, 360, fill=oc, width=7 * SS)
        _poly(d, [(cx - 52, 150), (cx + 52, 150), (cx + 44, 218), (cx - 44, 218)], pc, oc, 4)
        _rr(d, (cx - 40, 168, cx + 40, 182), 4, S.hex_rgba("#ffffff"))
    elif kind == "pan":                                    # تابه: دسته + کاسهٔ تخت با تخم‌مرغ
        _line(d, [(cx, 150), (cx, 96)], 13, steel)
        _ell(d, (cx - 56, 62, cx + 56, 106), steel, oc, 4)
        _ell(d, (cx - 44, 68, cx + 44, 98), S.hex_rgba("#ffffff"))
        _ell(d, (cx - 14, 72, cx + 14, 94), pc)
    elif kind == "box":                                    # بسته: جعبه + نوارِ چسب + برچسب
        _rr(d, (cx - 50, 84, cx + 50, 176), 8, pc, oc, 4)
        _rr(d, (cx - 9, 84, cx + 9, 176), 2, paper)
        _rr(d, (cx + 16, 136, cx + 42, 164), 3, paper, oc, 2)
    elif kind == "tablet":                                 # تبلت: قابِ تیره + صفحهٔ روشن + نوارِ رنگِ برند
        _rr(d, (cx - 38, 40, cx + 38, 160), 10, S.hex_rgba("#2b3040"), oc, 4)
        _rr(d, (cx - 31, 50, cx + 31, 150), 5, S.hex_rgba("#e6f0ff"))
        _rr(d, (cx - 24, 60, cx + 24, 74), 4, pc)
        for k in range(3):
            _line(d, [(cx - 22, 92 + k * 16), (cx + 22 - k * 8, 92 + k * 16)], 4, S.hex_rgba("#9aa3b2"))
    elif kind == "megaphone":                              # بلندگو (دهانه رو به بالا؛ در دست رو به جلو می‌چرخد)
        _poly(d, [(cx - 16, 150), (cx + 16, 150), (cx + 46, 70), (cx - 46, 70)], pc, oc, 4)
        _rr(d, (cx - 52, 58, cx + 52, 76), 6, S.hex_rgba("#ffffff"), oc, 4)
        _rr(d, (cx - 20, 148, cx + 20, 170), 6, steel, oc, 4)
    return _done(im, w, h)


# ------------------------------------------------------------------ سر و چهره

def _head(s: dict) -> Image.Image:
    w, h = 230, 230
    im, d = _canvas(w, h)
    rx, ry = _head_dims(s["head_style"])
    cx, cy = 115, 120
    oc, fill = S.hex_rgba(s["outline"]), S.hex_rgba(s["head_fill"])
    hair = S.hex_rgba(s["hair_colour"])
    if s["hair"] == "ponytail":
        _line(d, [(cx - rx + 8, cy - 10), (cx - rx - 30, cy + 20), (cx - rx - 26, cy + 56)], 20, hair)
    _ell(d, (cx - rx, cy - ry, cx + rx, cy + ry), fill, oc, 6)
    if s["extra"] == "mask":
        _poly(d, [(cx - rx + 6, cy + 4), (cx + rx - 6, cy + 4), (cx + rx - 18, cy + ry - 12), (cx - rx + 18, cy + ry - 12)], S.hex_rgba(s["extra_colour"]), oc, 4)
    top = cy - ry
    if s["hair"] == "tuft":
        _line(d, [(cx - 6, top + 6), (cx - 12, top - 22), (cx + 6, top - 10), (cx + 10, top - 30)], 8, hair)
    elif s["hair"] == "spikes":
        for dx in (-34, -12, 12, 34):
            _poly(d, [(cx + dx - 10, top + 16), (cx + dx, top - 22), (cx + dx + 10, top + 16)], hair, oc, 3)
    elif s["hair"] == "bob":
        _poly(d, [(cx - rx - 2, cy + 10), (cx - rx + 6, top + 8), (cx, top - 8), (cx + rx - 6, top + 8), (cx + rx + 2, cy + 10),
                  (cx + rx - 14, cy + 8), (cx + rx - 22, top + 30), (cx - rx + 22, top + 30), (cx - rx + 14, cy + 8)], hair, oc, 4)
    hat, hc = s["hat"], S.hex_rgba(s["hat_colour"])
    if hat == "cap":
        d.pieslice([(cx - rx - 3) * SS, (top - 24) * SS, (cx + rx + 3) * SS, (top + 74) * SS], 180, 360, fill=hc, outline=oc, width=4 * SS)
        _rr(d, (cx + 8, top + 22, cx + rx + 34, top + 36), 7, hc, oc, 4)
    elif hat == "beanie":
        d.pieslice([(cx - rx - 3) * SS, (top - 30) * SS, (cx + rx + 3) * SS, (top + 70) * SS], 180, 360, fill=hc, outline=oc, width=4 * SS)
        _rr(d, (cx - rx - 4, top + 22, cx + rx + 4, top + 40), 6, hc, oc, 4)
        _ell(d, (cx - 12, top - 44, cx + 12, top - 20), hc, oc, 4)
    elif hat == "headband":
        _rr(d, (cx - rx - 2, top + 28, cx + rx + 2, top + 48), 8, hc, oc, 4)
    elif hat == "tophat":
        _rr(d, (cx - rx - 10, top + 6, cx + rx + 10, top + 24), 6, hc, oc, 4)
        _rr(d, (cx - rx + 14, top - 50, cx + rx - 14, top + 12), 6, hc, oc, 4)
    elif hat == "hood":
        _poly(d, [(cx - rx - 8, cy + 30), (cx - rx + 4, top - 6), (cx, top - 22), (cx + rx - 4, top - 6), (cx + rx + 8, cy + 30),
                  (cx + rx - 14, cy - 8), (cx - rx + 14, cy - 8)], hc, oc, 4)
    elif hat == "chef":                                    # کلاهِ آشپز: سه برآمدگیِ پفی + نوارِ پایین
        for ex0, ey0, ex1, ey1 in ((cx - 50, top - 24, cx - 6, top + 22), (cx - 24, top - 46, cx + 26, top + 8), (cx + 4, top - 26, cx + 50, top + 22)):
            _ell(d, (ex0, ey0, ex1, ey1), hc, oc, 4)
        _rr(d, (cx - rx + 8, top + 10, cx + rx - 8, top + 34), 6, hc, oc, 4)
    return _done(im, w, h)


def _eyes(s: dict, kind: str) -> Image.Image:
    w, h = 160, 56
    im, d = _canvas(w, h)
    oc = S.hex_rgba(s["outline"])
    style = s["eye_style"]
    for cx in (46, 116):
        if kind == "closed" or kind == "happy":
            d.arc([(cx - 17) * SS, (12 if kind == "closed" else 18) * SS, (cx + 17) * SS, (38 if kind == "closed" else 46) * SS],
                  20 if kind == "closed" else 200, 160 if kind == "closed" else 340, fill=oc, width=6 * SS)
            continue
        if style == "dots":
            r = 8 if kind != "wide" else 6
            _ell(d, (cx - r, 28 - r, cx + r, 28 + r), oc)
            continue
        er = {"round": 17, "sleepy": 15}[style]
        ry = er
        py = 28
        if kind == "wide":
            er, ry = 21, 23
        elif kind == "narrow":
            ry = er * 0.55
        elif kind == "down":
            py = 32
        _ell(d, (cx - er, 28 - ry, cx + er, 28 + ry), S.hex_rgba("#ffffff"), oc, 4)
        pr = 7 if kind != "wide" else 4.5
        _ell(d, (cx + 4 - pr, py - pr, cx + 4 + pr, py + pr), oc)
        if style == "sleepy" and kind not in ("wide",):
            d.rectangle([(cx - er - 2) * SS, (28 - ry - 2) * SS, (cx + er + 2) * SS, 26 * SS], fill=S.hex_rgba(s["head_fill"]))
            _line(d, [(cx - er, 26), (cx + er, 26)], 4, oc)
    return _done(im, w, h)


def _brows(s: dict, kind: str) -> Image.Image:
    w, h = 170, 40
    im, d = _canvas(w, h)
    c = S.hex_rgba(s["outline"])
    spec = {   # (ابروی چپ: داخل ⇒ بیرون)، (ابروی راست)
        "flat": ([(22, 22), (58, 22)], [(112, 22), (148, 22)]), "up": ([(22, 18), (58, 14)], [(112, 14), (148, 18)]),
        "sad": ([(22, 12), (58, 22)], [(112, 22), (148, 12)]), "angry": ([(22, 10), (60, 24)], [(110, 24), (148, 10)]),
        "worry": ([(24, 26), (60, 12)], [(110, 12), (146, 26)]), "high": ([(22, 12), (58, 8)], [(112, 8), (148, 12)]),
        "smirk": ([(22, 20), (58, 20)], [(112, 24), (148, 12)]),
    }[kind]
    for pts in spec:
        _line(d, pts, 7, c)
    return _done(im, w, h)


def _mouth(s: dict, shape: str, variant: str = "flat") -> Image.Image:
    w, h = 110, 70
    im, d = _canvas(w, h)
    oc, red, white = S.hex_rgba(s["outline"]), S.hex_rgba("#9b2c3a"), S.hex_rgba("#ffffff")
    cx, cy = 55, 34
    if shape == "X":
        if variant == "smile":
            d.arc([(cx - 28) * SS, (cy - 24) * SS, (cx + 28) * SS, (cy + 14) * SS], 20, 160, fill=oc, width=7 * SS)
        elif variant == "frown":
            d.arc([(cx - 24) * SS, (cy - 2) * SS, (cx + 24) * SS, (cy + 34) * SS], 200, 340, fill=oc, width=7 * SS)
        elif variant == "smirk":
            _line(d, [(cx - 22, cy + 4), (cx + 6, cy + 6), (cx + 24, cy - 8)], 7, oc)
        elif variant == "clench":
            _rr(d, (cx - 24, cy - 8, cx + 24, cy + 10), 5, white, oc, 5)
            _line(d, [(cx - 24, cy + 1), (cx + 24, cy + 1)], 4, oc)
        else:
            _line(d, [(cx - 18, cy), (cx + 18, cy)], 7, oc)
    elif shape == "A":
        _line(d, [(cx - 24, cy), (cx + 24, cy)], 8, oc)
    elif shape == "B":
        _ell(d, (cx - 22, cy - 7, cx + 22, cy + 9), red, oc, 5)
    elif shape == "C":
        _ell(d, (cx - 24, cy - 13, cx + 24, cy + 15), red, oc, 5)
    elif shape == "D":
        _ell(d, (cx - 28, cy - 18, cx + 28, cy + 22), red, oc, 5)
        _rr(d, (cx - 20, cy - 17, cx + 20, cy - 8), 3, white)
    elif shape == "E":
        _ell(d, (cx - 16, cy - 20, cx + 16, cy + 20), red, oc, 5)
    elif shape == "F":
        _ell(d, (cx - 10, cy - 10, cx + 10, cy + 10), red, oc, 5)
    elif shape == "G":
        _ell(d, (cx - 22, cy - 9, cx + 22, cy + 11), red, oc, 5)
        _rr(d, (cx - 17, cy - 8, cx + 17, cy), 3, white)
    elif shape == "H":
        _ell(d, (cx - 23, cy - 12, cx + 23, cy + 14), red, oc, 5)
        _ell(d, (cx - 10, cy, cx + 10, cy + 12), S.hex_rgba("#e0707c"))
    return _done(im, w, h)


def _glasses(s: dict) -> Image.Image:
    w, h = 190, 70
    im, d = _canvas(w, h)
    c = S.hex_rgba(s["extra_colour"])
    for cx in (50, 140):
        _ell(d, (cx - 28, 8, cx + 28, 62), None, c, 7)
    _line(d, [(78, 34), (112, 34)], 7, c)
    return _done(im, w, h)


# ------------------------------------------------------------------ the rig

def _logo_key(logo: Image.Image | None) -> str:
    if logo is None:
        return ""
    import hashlib

    small = logo.convert("RGBA").resize((16, 16))
    return hashlib.sha1(small.tobytes()).hexdigest()[:12]


def build_rig(spec: dict, expression: str = "neutral", *, logo: Image.Image | None = None, mirror_logo: bool = False, prop: str | None = None) -> Rig:
    """اسکلتِ کاملِ شخصیت با چهرهٔ ``expression``. ``prop`` وسیلهٔ این قاب را عوض می‌کند (None = وسیلهٔ خودِ spec)."""
    s = S.normalize(spec)
    if prop is not None and prop in S.PROPS:
        s = {**s, "prop": prop}
    brows, eyes, mouth_x, _shape = expression_parts(expression)
    pics: dict[str, Image.Image] = {"body": _body(s, logo, mirror_logo), "head": _head(s)}
    upper, fore = _limb(s, UPPER), _limb(s, FORE, hand=True)
    pics["arm_l"] = pics["arm_r"] = upper
    pics["forearm_l"] = pics["forearm_r"] = fore
    pics["leg_l"] = pics["leg_r"] = _limb(s, THIGH)
    pics["shin_l"] = pics["shin_r"] = _limb(s, SHIN, foot=True)
    pics["eyes_open"] = _eyes(s, eyes)
    pics["eyes_closed"] = _eyes(s, "closed")
    pics["brows_neutral"] = _brows(s, brows)
    for shape in MOUTH_SHAPES:
        pics[f"mouth_{shape}"] = _mouth(s, shape, mouth_x if shape == "X" else "flat")
    if s["extra"] == "glasses":
        pics["glasses"] = _glasses(s)
    pics["thumb"] = _thumb(s)
    prop_img = _prop(s)
    if prop_img is not None:
        pics["prop"] = prop_img

    def P(name, pivot, pos, z, parent, group=None, state=None) -> Part:
        return Part(name=name, image=pics.get(name), pivot=tuple(pivot), pos=tuple(pos), z=z, parent=parent, group=group, state=state)

    rig = Rig(size=DESIGN, anchor=ANCHOR)
    parts = rig.parts
    parts["leg_l"] = P("leg_l", [40, 14], [HIP[0] - 9, HIP[1]], 5, None)
    parts["leg_r"] = P("leg_r", [40, 14], [HIP[0] + 9, HIP[1]], 6, None)
    parts["shin_l"] = P("shin_l", [40, 14], [40, 14 + THIGH], 5, "leg_l")
    parts["shin_r"] = P("shin_r", [40, 14], [40, 14 + THIGH], 6, "leg_r")
    parts["body"] = P("body", [BODY_CX, BODY_TOP + TORSO], list(HIP), 10, None)
    parts["arm_l"] = P("arm_l", [40, 14], [110, 46], 12, "body")
    parts["arm_r"] = P("arm_r", [40, 14], [110, 46], 30, "body")
    parts["forearm_l"] = P("forearm_l", [40, 14], [40, 14 + UPPER], 12, "arm_l")
    parts["forearm_r"] = P("forearm_r", [40, 14], [40, 14 + UPPER], 30, "arm_r")
    parts["head"] = P("head", [115, 120 + _head_dims(s["head_style"])[1]], [110, 40], 20, "body")
    parts["eyes_open"] = P("eyes_open", [80, 28], [115, 112], 21, "head", "eyes", "open")
    parts["eyes_closed"] = P("eyes_closed", [80, 28], [115, 112], 21, "head", "eyes", "closed")
    parts["brows_neutral"] = P("brows_neutral", [85, 20], [115, 82], 22, "head", "brows", "neutral")
    for shape in MOUTH_SHAPES:
        parts[f"mouth_{shape}"] = P(f"mouth_{shape}", [55, 34], [115, 146], 23, "head", "mouth", shape)
    if "glasses" in pics:
        parts["glasses"] = P("glasses", [95, 35], [115, 112], 24, "head")
    if "prop" in pics:
        parts["prop"] = P("prop", [110, 150], [40, 14 + FORE], 31, "forearm_r")
    parts["thumb"] = P("thumb", [30, 14], [46, 14 + FORE + 4], 32, "forearm_r", "thumb", "up")
    rig.validate()
    return rig


_RIGS: dict[tuple, Rig] = {}
_RIG_LIMIT = 16


def rig_for(spec: dict, expression: str = "neutral", *, logo: Image.Image | None = None, mirror_logo: bool = False, prop: str | None = None) -> Rig:
    """``build_rig`` با کَشِ حافظه (کلید: spec، حالت، لوگو، آینه‌بودن، وسیله). یک قابِ ساختنی چند بار از همان قطعه‌ها استفاده می‌کند."""
    s = S.normalize(spec)
    key = (S.spec_hash(s), expression, _logo_key(logo) if s.get("logo") == "chest" else "", bool(mirror_logo) and s.get("logo") == "chest", prop or "")
    rig = _RIGS.get(key)
    if rig is None:
        rig = build_rig(s, expression, logo=logo, mirror_logo=key[3], prop=prop)
        if len(_RIGS) >= _RIG_LIMIT:
            _RIGS.pop(next(iter(_RIGS)))
        _RIGS[key] = rig
    return rig
