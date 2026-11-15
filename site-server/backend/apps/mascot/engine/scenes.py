"""پس‌زمینه‌های ماسکوت: ۴ صحنهٔ بازاریابی (پیشخوانِ فروشگاه، سالنِ باشگاه، میزِ آشپزخانه، رنگِ برند) + ۱۳ صحنهٔ آمادهٔ InstAI. فقط Pillow؛
همیشه یکسان (کلید و اندازهٔ یکسان ⇒ پیکسلِ یکسان).

SOURCE: the 13 story backgrounds are ported from InstAI (maniUZqqz/Instai) instai/render/stick/scenes.py @ 82733b0 (plain, cell, corridor, yard, street, forest,
room, rooftop, desert, cave, lab, sewer, bridge), adapted for NMarketing: the four marketing scenes are new and take the store's brand colours
(``brand`` = [primary, secondary]); ``pick(text)`` also understands shop/gym/kitchen words in Persian and English.

``pick(text)`` از روی یک عبارتِ مکان (فارسی یا انگلیسی) پس‌زمینه را انتخاب می‌کند.
"""
from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageOps

INK = (31, 36, 48)
DEFAULT_BRAND = ("#126f85", "#163f75")          # فقط وقتی فروشگاه رنگی ندارد

BACKGROUNDS: dict[str, dict] = {
    # ---- بازاریابی (تازه در NM؛ رنگ‌های برند را می‌گیرند)
    "counter": {"fa": "پیشخوانِ فروشگاه", "en": "Shop counter", "group": "marketing", "brand": True,
                "words": ("shop", "store", "counter", "market", "فروشگاه", "مغازه", "پیشخوان", "بازار", "خرید")},
    "gym": {"fa": "سالنِ باشگاه", "en": "Gym floor", "group": "marketing", "brand": True,
            "words": ("gym", "fitness", "workout", "training", "باشگاه", "تمرین", "ورزش", "بدنسازی")},
    "kitchen": {"fa": "میزِ آشپزخانه", "en": "Kitchen table", "group": "marketing", "brand": True,
                "words": ("kitchen", "cook", "food", "cafe", "آشپزخانه", "غذا", "آشپز", "کافه", "رستوران")},
    "brand": {"fa": "رنگِ برند", "en": "Brand colour", "group": "marketing", "brand": True,
              "words": ("brand", "colour", "color", "برند", "رنگ")},
    # ---- صحنه‌های آمادهٔ InstAI
    "plain": {"fa": "ساده", "en": "Plain", "group": "scene", "words": ("plain", "void", "empty", "white", "ساده", "خالی")},
    "cell": {"fa": "سلول زندان", "en": "Prison cell", "group": "scene", "words": ("cell", "prison", "jail", "inmate", "سلول", "زندان", "بازداشت")},
    "corridor": {"fa": "راهرو", "en": "Corridor", "group": "scene", "words": ("corridor", "hall", "hallway", "راهرو", "سالن")},
    "yard": {"fa": "حیاط", "en": "Yard", "group": "scene", "words": ("yard", "courtyard", "fence", "حیاط", "محوطه", "حصار")},
    "street": {"fa": "خیابان شبانه", "en": "Night street", "group": "scene", "words": ("street", "city", "road", "town", "خیابان", "شهر", "کوچه", "جاده")},
    "forest": {"fa": "جنگل", "en": "Forest", "group": "scene", "words": ("forest", "wood", "jungle", "trees", "جنگل", "درخت")},
    "room": {"fa": "اتاق", "en": "Room", "group": "scene", "words": ("room", "house", "home", "bedroom", "apartment", "اتاق", "خانه")},
    "rooftop": {"fa": "پشت‌بام", "en": "Rooftop", "group": "scene", "words": ("roof", "rooftop", "tower", "پشت بام", "پشت‌بام", "بام", "برج")},
    "desert": {"fa": "بیابان", "en": "Desert", "group": "scene", "words": ("desert", "dunes", "sand", "wasteland", "بیابان", "کویر", "صحرا")},
    "cave": {"fa": "غار", "en": "Cave", "group": "scene", "words": ("cave", "tunnel", "mine", "underground", "غار", "تونل", "معدن")},
    "lab": {"fa": "آزمایشگاه", "en": "Laboratory", "group": "scene", "words": ("lab", "laboratory", "science", "آزمایشگاه", "علمی")},
    "sewer": {"fa": "فاضلاب", "en": "Sewer", "group": "scene", "words": ("sewer", "drain", "pipe", "فاضلاب", "لوله", "کانال")},
    "bridge": {"fa": "پل", "en": "Bridge", "group": "scene", "words": ("bridge", "river", "پل", "رودخانه")},
}
DEFAULT_BACKGROUND = "brand"


def keys() -> list[str]:
    return list(BACKGROUNDS)


def marketing_keys() -> list[str]:
    return [k for k, v in BACKGROUNDS.items() if v["group"] == "marketing"]


def pick(text: str, default: str = DEFAULT_BACKGROUND) -> str:
    low = (text or "").lower()
    best, hit = default, 0
    for k, v in BACKGROUNDS.items():
        n = sum(1 for w in v["words"] if w in low)
        if n > hit:
            best, hit = k, n
    return best


def _hex(h: str) -> tuple[int, int, int]:
    h = (h or "").lstrip("#")
    try:
        return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    except ValueError:
        return 18, 111, 133


def _mix(a: tuple, b: tuple, t: float) -> tuple[int, int, int]:
    return tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(3))  # type: ignore[return-value]


def _darker(c: tuple, t: float = 0.25) -> tuple[int, int, int]:
    return _mix(c, (0, 0, 0), t)


def _lighter(c: tuple, t: float = 0.6) -> tuple[int, int, int]:
    return _mix(c, (255, 255, 255), t)


def _grad(w: int, h: int, top: tuple, bottom: tuple) -> Image.Image:
    return ImageOps.colorize(Image.linear_gradient("L").resize((w, h)), top, bottom).convert("RGB")


def _rect(d, box, fill, outline=None, width=0):
    d.rectangle(box, fill=fill, outline=outline, width=width)


def _bars(d, x0, y0, x1, y1, n, col=(70, 78, 96), width=14):
    for i in range(n + 1):
        x = x0 + (x1 - x0) * i / n
        d.rectangle([x - width / 2, y0, x + width / 2, y1], fill=col)
    d.rectangle([x0 - width / 2, y0, x1 + width / 2, y0 + width], fill=col)
    d.rectangle([x0 - width / 2, y1 - width, x1 + width / 2, y1], fill=col)


def _stars(d, w, h, n=34, until=0.5):
    for i in range(n):
        x = (i * 9973 % 1000) / 1000 * w
        y = ((i * 7919) % 1000) / 1000 * h * until
        r = 2 + (i % 3)
        d.ellipse([x - r, y - r, x + r, y + r], fill=(235, 238, 255))


def _floor(d, w, h, y, col):
    d.rectangle([0, y, w, h], fill=col)


def _draw_story(key: str, w: int, h: int) -> Image.Image:
    key = key if key in BACKGROUNDS else "plain"
    ground = int(h * 0.80)            # where the characters' feet stand (renderer y = 0.93 of the height sits a little below this)
    if key == "plain":
        return _grad(w, h, (244, 241, 234), (226, 222, 212))
    if key == "cell":
        im = Image.new("RGB", (w, h), (120, 124, 132))
        d = ImageDraw.Draw(im)
        for y in range(0, ground, 90):
            d.line([0, y, w, y], fill=(104, 108, 116), width=3)
        for x in range(0, w, 150):
            d.line([x, 0, x, ground], fill=(110, 114, 122), width=2)
        _floor(d, w, h, ground, (84, 88, 96))
        d.rectangle([0, ground, w, ground + 8], fill=(60, 64, 72))
        _rect(d, (int(w * 0.62), int(h * 0.12), int(w * 0.9), int(h * 0.34)), (150, 195, 235), INK, 8)          # barred window
        _bars(d, int(w * 0.64), int(h * 0.12), int(w * 0.88), int(h * 0.34), 4, (52, 58, 74), 9)
        _rect(d, (int(w * 0.04), int(h * 0.58), int(w * 0.40), int(h * 0.66)), (176, 118, 60), INK, 6)           # bunk bed
        _rect(d, (int(w * 0.04), int(h * 0.50), int(w * 0.40), int(h * 0.57)), (150, 98, 52), INK, 6)
        _rect(d, (int(w * 0.05), int(h * 0.57), int(w * 0.08), ground), (60, 64, 72))
        _rect(d, (int(w * 0.36), int(h * 0.57), int(w * 0.39), ground), (60, 64, 72))
        return im
    if key == "corridor":
        im = Image.new("RGB", (w, h), (150, 154, 160))
        d = ImageDraw.Draw(im)
        cx, vy = w // 2, int(h * 0.42)
        d.polygon([(0, 0), (w, 0), (cx + 150, vy - 120), (cx - 150, vy - 120)], fill=(96, 100, 108))
        d.polygon([(0, h), (w, h), (cx + 150, vy + 120), (cx - 150, vy + 120)], fill=(112, 116, 124))
        d.polygon([(0, 0), (cx - 150, vy - 120), (cx - 150, vy + 120), (0, h)], fill=(132, 136, 144))
        d.polygon([(w, 0), (cx + 150, vy - 120), (cx + 150, vy + 120), (w, h)], fill=(124, 128, 136))
        d.rectangle([cx - 150, vy - 120, cx + 150, vy + 120], fill=(60, 64, 74))
        for xo in (-1, 1):                                                                                       # cell doors in perspective
            for k in range(3):
                x0 = cx + xo * (200 + k * 90)
                d.polygon([(x0, vy - 90 + k * 10), (x0 + xo * 40, vy - 100 + k * 8), (x0 + xo * 40, vy + 110 - k * 6), (x0, vy + 100)], fill=(76, 84, 104), outline=INK)
        d.ellipse([cx - 60, 40, cx + 60, 100], fill=(255, 242, 180))
        return im
    if key == "yard":
        im = _grad(w, h, (156, 196, 232), (222, 232, 238))
        d = ImageDraw.Draw(im)
        d.ellipse([w * 0.70, h * 0.07, w * 0.70 + 150, h * 0.07 + 150], fill=(255, 246, 200))
        _rect(d, (0, int(h * 0.38), w, int(h * 0.62)), (160, 150, 140))                                          # prison wall
        for x in range(0, w, 120):
            d.line([x, int(h * 0.38), x, int(h * 0.62)], fill=(140, 130, 120), width=3)
        for x in range(0, w, 60):                                                                                # fence
            d.line([x, int(h * 0.50), x + 30, int(h * 0.74)], fill=(88, 96, 110), width=3)
            d.line([x + 30, int(h * 0.50), x, int(h * 0.74)], fill=(88, 96, 110), width=3)
        d.rectangle([0, int(h * 0.49), w, int(h * 0.51)], fill=INK)
        d.rectangle([0, int(h * 0.74), w, int(h * 0.755)], fill=INK)
        _floor(d, w, h, int(h * 0.755), (186, 170, 140))
        _rect(d, (int(w * 0.80), int(h * 0.22), int(w * 0.96), int(h * 0.40)), (120, 112, 104), INK, 6)
        _rect(d, (int(w * 0.78), int(h * 0.19), int(w * 0.98), int(h * 0.225)), (80, 74, 70), INK, 6)
        return im
    if key == "street":
        im = _grad(w, h, (24, 28, 56), (68, 64, 104))
        d = ImageDraw.Draw(im)
        _stars(d, w, h, 40, 0.4)
        d.ellipse([w * 0.74, h * 0.06, w * 0.74 + 130, h * 0.06 + 130], fill=(250, 246, 214))
        for i, (x0, bw, bh) in enumerate([(0, 210, 620), (190, 260, 480), (430, 200, 700), (610, 280, 540), (860, 240, 640)]):
            y0 = ground - bh
            d.rectangle([x0, y0, x0 + bw, ground], fill=(40 + i * 4, 44 + i * 4, 66 + i * 4))
            for wy in range(y0 + 40, ground - 40, 70):
                for wx in range(x0 + 24, x0 + bw - 30, 54):
                    on = ((wx * 7 + wy * 13 + i) % 5) < 2
                    d.rectangle([wx, wy, wx + 26, wy + 36], fill=(255, 214, 120) if on else (30, 34, 52))
        _floor(d, w, h, ground, (52, 54, 66))
        d.rectangle([0, ground, w, ground + 10], fill=(90, 92, 108))
        for x in range(0, w, 220):
            d.rectangle([x + 40, int(h * 0.88), x + 130, int(h * 0.89)], fill=(210, 206, 150))
        d.rectangle([int(w * 0.84), int(h * 0.50), int(w * 0.845), ground], fill=(30, 32, 40))                   # street lamp
        d.ellipse([int(w * 0.815), int(h * 0.47), int(w * 0.87), int(h * 0.51)], fill=(255, 238, 170))
        return im
    if key == "forest":
        im = _grad(w, h, (176, 214, 196), (222, 238, 214))
        d = ImageDraw.Draw(im)
        for layer, (col, base, hh) in enumerate([((130, 176, 150), 0.74, 0.34), ((86, 140, 110), 0.78, 0.40), ((52, 104, 78), 0.82, 0.48)]):
            for k in range(7):
                x = (k * 190 + layer * 70) % (w + 100) - 40
                tw = 40 + layer * 14
                d.rectangle([x - tw // 2, int(h * (base - hh * 0.0)) - 40, x + tw // 2, int(h * base) + 30], fill=(96, 72, 52))
                d.polygon([(x - 130, int(h * (base - 0.08))), (x + 130, int(h * (base - 0.08))), (x, int(h * (base - hh)))], fill=col)
                d.polygon([(x - 100, int(h * (base - 0.22))), (x + 100, int(h * (base - 0.22))), (x, int(h * (base - hh - 0.1)))], fill=col)
        _floor(d, w, h, int(h * 0.80), (86, 130, 82))
        return im
    if key == "room":
        im = Image.new("RGB", (w, h), (226, 214, 196))
        d = ImageDraw.Draw(im)
        _floor(d, w, h, ground, (176, 132, 92))
        d.rectangle([0, ground - 10, w, ground], fill=(150, 110, 76))
        _rect(d, (int(w * 0.56), int(h * 0.14), int(w * 0.92), int(h * 0.42)), (170, 214, 240), INK, 8)         # window
        d.line([int(w * 0.74), int(h * 0.14), int(w * 0.74), int(h * 0.42)], fill=INK, width=8)
        d.line([int(w * 0.56), int(h * 0.28), int(w * 0.92), int(h * 0.28)], fill=INK, width=8)
        _rect(d, (int(w * 0.05), int(h * 0.30), int(w * 0.30), int(h * 0.55)), (200, 150, 110), INK, 6)         # picture / shelf
        _rect(d, (int(w * 0.08), int(h * 0.34), int(w * 0.27), int(h * 0.51)), (120, 170, 150))
        _rect(d, (int(w * 0.05), int(h * 0.64), int(w * 0.34), ground), (150, 100, 70), INK, 6)                 # table
        return im
    if key == "rooftop":
        im = _grad(w, h, (255, 160, 110), (255, 220, 170))
        d = ImageDraw.Draw(im)
        d.ellipse([w * 0.30, h * 0.30, w * 0.30 + 280, h * 0.30 + 280], fill=(255, 246, 200))
        for i, (x0, bw, bh) in enumerate([(0, 180, 380), (150, 220, 260), (380, 160, 420), (520, 240, 300), (740, 200, 460), (900, 200, 340)]):
            d.rectangle([x0, int(h * 0.62) - bh // 2, x0 + bw, h], fill=(120 - i * 6, 84 - i * 4, 104 - i * 3))
        _floor(d, w, h, ground, (96, 92, 100))
        d.rectangle([0, ground - 30, w, ground], fill=(130, 126, 134))
        for x in range(20, w, 90):
            d.rectangle([x, ground - 90, x + 14, ground - 30], fill=(110, 106, 116))
        d.rectangle([0, ground - 96, w, ground - 82], fill=(110, 106, 116))
        return im
    if key == "desert":
        im = _grad(w, h, (250, 214, 150), (255, 240, 200))
        d = ImageDraw.Draw(im)
        d.ellipse([w * 0.66, h * 0.08, w * 0.66 + 190, h * 0.08 + 190], fill=(255, 250, 220))
        for off, col, amp in ((0.66, (232, 190, 120), 70), (0.72, (222, 170, 98), 90), (0.80, (206, 150, 84), 60)):
            pts = [(0, h)]
            for x in range(0, w + 40, 40):
                pts.append((x, int(h * off - amp * math.sin(x / 190.0 + off * 9))))
            pts.append((w, h))
            d.polygon(pts, fill=col)
        return im
    if key == "cave":
        im = _grad(w, h, (34, 30, 44), (66, 58, 78))
        d = ImageDraw.Draw(im)
        for x in range(0, w, 120):
            hh = 120 + (x * 37 % 190)
            d.polygon([(x, 0), (x + 120, 0), (x + 60, hh)], fill=(54, 48, 66))
        _floor(d, w, h, ground, (46, 42, 56))
        for x in range(60, w, 260):
            d.polygon([(x, ground), (x + 70, ground), (x + 36, ground - 90)], fill=(70, 64, 84))
        d.ellipse([w * 0.36, h * 0.18, w * 0.64, h * 0.30], fill=(255, 214, 120))
        return im
    if key == "lab":
        im = Image.new("RGB", (w, h), (214, 232, 238))
        d = ImageDraw.Draw(im)
        _floor(d, w, h, ground, (176, 196, 206))
        for x in range(0, w, 135):
            d.line([x, 0, x, ground], fill=(198, 218, 226), width=3)
        _rect(d, (int(w * 0.05), int(h * 0.55), int(w * 0.50), ground), (240, 244, 246), INK, 6)                  # bench
        for k, col in enumerate(((220, 90, 100), (90, 180, 120), (110, 150, 230))):                                # flasks
            x = int(w * (0.10 + 0.12 * k))
            d.polygon([(x + 20, int(h * 0.44)), (x + 52, int(h * 0.44)), (x + 74, int(h * 0.55)), (x - 2, int(h * 0.55))], fill=col, outline=INK)
        _rect(d, (int(w * 0.60), int(h * 0.14), int(w * 0.94), int(h * 0.50)), (30, 40, 56), INK, 8)             # screen
        d.line([int(w * 0.63), int(h * 0.40), int(w * 0.72), int(h * 0.30), int(w * 0.80), int(h * 0.36), int(w * 0.90), int(h * 0.20)], fill=(120, 240, 170), width=7)
        return im
    if key == "sewer":
        im = _grad(w, h, (52, 74, 66), (88, 110, 92))
        d = ImageDraw.Draw(im)
        for y in range(0, ground, 80):
            d.line([0, y, w, y], fill=(64, 88, 78), width=3)
        d.ellipse([w * 0.58, h * 0.20, w * 0.58 + 300, h * 0.20 + 300], fill=(30, 44, 40), outline=(100, 120, 112), width=10)   # big pipe
        _floor(d, w, h, ground, (60, 100, 90))
        for y in range(ground + 20, h, 60):
            d.line([0, y, w, y + 6], fill=(78, 124, 112), width=4)
        return im
    if key == "bridge":
        im = _grad(w, h, (170, 208, 240), (236, 244, 250))
        d = ImageDraw.Draw(im)
        _floor(d, w, h, int(h * 0.80), (70, 120, 170))
        d.rectangle([0, int(h * 0.66), w, int(h * 0.70)], fill=(96, 92, 100))
        d.rectangle([0, int(h * 0.70), w, int(h * 0.80)], fill=(70, 120, 170))
        for x in range(60, w, 150):
            d.rectangle([x, int(h * 0.70), x + 40, int(h * 0.80)], fill=(110, 106, 116))
            d.line([x + 20, int(h * 0.56), x + 20, int(h * 0.66)], fill=(60, 56, 64), width=8)
        d.line([0, int(h * 0.56), w, int(h * 0.56)], fill=(60, 56, 64), width=8)
        return im
    return _grad(w, h, (244, 241, 234), (226, 222, 212))



# ------------------------------------------------------------------ صحنه‌های بازاریابیِ NM (۲ برابر کشیده و کوچک می‌شوند تا لبه‌ها نرم باشند)

def _draw_marketing(key: str, w: int, h: int, brand: tuple[str, str]) -> Image.Image:
    W, H = w * 2, h * 2
    p, s = _hex(brand[0]), _hex(brand[1])
    u = max(2, int(round(min(W, H) / 330)))               # واحدِ ضخامتِ خط

    def X(f: float) -> int:
        return int(f * W)

    def Y(f: float) -> int:
        return int(f * H)

    ground = Y(0.80)
    if key == "brand":
        im = _grad(W, H, _lighter(p, 0.90), _lighter(p, 0.76))
        d = ImageDraw.Draw(im)
        r = int(min(W, H) * 0.30)
        d.ellipse([X(0.86) - r, Y(0.16) - r, X(0.86) + r, Y(0.16) + r], fill=_lighter(p, 0.70))
        r2 = int(min(W, H) * 0.20)
        d.ellipse([X(0.06) - r2, Y(0.60) - r2, X(0.06) + r2, Y(0.60) + r2], fill=_lighter(s, 0.82))
        d.polygon([(0, Y(0.30)), (W, Y(0.14)), (W, Y(0.22)), (0, Y(0.38))], fill=_lighter(p, 0.84))
        d.polygon([(0, Y(0.40)), (W, Y(0.24)), (W, Y(0.27)), (0, Y(0.43))], fill=_lighter(s, 0.78))
        for i in range(5):
            for j in range(3):
                cx, cy = X(0.08 + i * 0.045), Y(0.08 + j * 0.03)
                d.ellipse([cx - u, cy - u, cx + u, cy + u], fill=_lighter(p, 0.55))
        d.rectangle([0, ground, W, H], fill=_lighter(p, 0.62))
        d.rectangle([0, ground, W, ground + u * 3], fill=_lighter(p, 0.45))
    elif key == "counter":
        im = _grad(W, H, (250, 247, 241), (236, 231, 221))
        d = ImageDraw.Draw(im)
        band = W // 12                                                                                        # سایبانِ راه‌راه
        for i in range(12):
            col = p if i % 2 == 0 else (255, 255, 255)
            d.rectangle([i * band, 0, (i + 1) * band, Y(0.075)], fill=col)
            d.pieslice([i * band, Y(0.075) - band // 2, (i + 1) * band, Y(0.075) + band // 2], 0, 180, fill=col)
        for ys in (0.30, 0.45):                                                                               # دو قفسه با کالا
            y0 = Y(ys)
            d.rectangle([X(0.05), y0, X(0.95), y0 + Y(0.014)], fill=(176, 132, 92))
            d.rectangle([X(0.05), y0 + Y(0.014), X(0.95), y0 + Y(0.020)], fill=(140, 100, 68))
            cols = (p, _lighter(p, 0.5), s, (232, 162, 43), (244, 241, 234), _lighter(s, 0.5))
            x = X(0.07)
            n = 0
            while x < X(0.90):
                bw = X(0.035 + (n * 7 % 3) * 0.012)
                bh = Y(0.045 + (n * 5 % 4) * 0.014)
                d.rounded_rectangle([x, y0 - bh, x + bw, y0], radius=u * 2, fill=cols[n % len(cols)], outline=INK, width=u)
                x += bw + X(0.012)
                n += 1
        d.rounded_rectangle([X(0.60), Y(0.10), X(0.93), Y(0.205)], radius=u * 4, fill=s, outline=INK, width=u)   # تابلو (بدونِ نوشته)
        d.rounded_rectangle([X(0.64), Y(0.13), X(0.89), Y(0.145)], radius=u * 2, fill=_lighter(s, 0.7))
        d.rounded_rectangle([X(0.64), Y(0.165), X(0.80), Y(0.178)], radius=u * 2, fill=_lighter(s, 0.5))
        d.rectangle([0, ground, W, H], fill=(214, 204, 188))                                                  # کف
        for k in range(0, W, X(0.12)):
            d.line([k, ground, k - X(0.06), H], fill=(200, 190, 174), width=u)
        d.rectangle([0, Y(0.635), W, ground], fill=s)                                                         # پیشخوان
        d.rectangle([0, Y(0.615), W, Y(0.64)], fill=_lighter(s, 0.45))
        for k in range(1, 6):
            d.line([X(k / 6), Y(0.645), X(k / 6), ground], fill=_darker(s, 0.2), width=u)
        d.rounded_rectangle([X(0.07), Y(0.53), X(0.25), Y(0.615)], radius=u * 3, fill=(60, 68, 84), outline=INK, width=u)   # صندوق
        d.rectangle([X(0.09), Y(0.54), X(0.23), Y(0.565)], fill=(190, 227, 255))
        for k in range(4):
            d.rectangle([X(0.10 + k * 0.032), Y(0.575), X(0.12 + k * 0.032), Y(0.595)], fill=(150, 158, 174))
        for k, cx in enumerate((0.72, 0.84)):                                                                 # کیسه‌های خرید روی پیشخوان
            bw, bh = X(0.07), Y(0.085)
            d.polygon([(X(cx), Y(0.615) - bh), (X(cx) + bw, Y(0.615) - bh), (X(cx) + bw - u * 4, Y(0.615)), (X(cx) + u * 4, Y(0.615))],
                      fill=p if k == 0 else (232, 162, 43), outline=INK)
            d.arc([X(cx) + bw // 4, Y(0.615) - bh - Y(0.025), X(cx) + 3 * bw // 4, Y(0.615) - bh + Y(0.02)], 180, 360, fill=INK, width=u)
    elif key == "gym":
        im = _grad(W, H, (232, 238, 246), (208, 218, 230))
        d = ImageDraw.Draw(im)
        d.rectangle([0, Y(0.43), W, Y(0.465)], fill=p)                                                        # نوارِ رنگِ برند روی دیوار
        d.rectangle([0, Y(0.47), W, Y(0.482)], fill=s)
        d.rounded_rectangle([X(0.05), Y(0.10), X(0.60), Y(0.55)], radius=u * 3, fill=(206, 230, 244), outline=(140, 160, 184), width=u * 2)
        mw, mh = X(0.55) - X(0.05), Y(0.45)
        mirror = _grad(mw - u * 6, mh - u * 6, (214, 236, 248), (176, 208, 232))
        im.paste(mirror, (X(0.05) + u * 3, Y(0.10) + u * 3))
        d.polygon([(X(0.14), Y(0.10)), (X(0.22), Y(0.10)), (X(0.12), Y(0.55)), (X(0.04) + X(0.05), Y(0.55))], fill=(236, 246, 252))
        d.polygon([(X(0.30), Y(0.10)), (X(0.33), Y(0.10)), (X(0.23), Y(0.55)), (X(0.20), Y(0.55))], fill=(236, 246, 252))
        d.rectangle([X(0.66), Y(0.50), X(0.95), Y(0.515)], fill=(70, 78, 94))                                 # قفسهٔ دمبل
        d.rectangle([X(0.66), Y(0.62), X(0.95), Y(0.635)], fill=(70, 78, 94))
        for row, y0 in enumerate((Y(0.50), Y(0.62))):
            for k in range(5):
                cx = X(0.70 + k * 0.05)
                hh = int(Y(0.032) * (1 + 0.2 * k))
                d.rounded_rectangle([cx - X(0.018), y0 - hh, cx - X(0.006), y0], radius=u, fill=p if row == 0 else s, outline=INK, width=u)
                d.rounded_rectangle([cx + X(0.006), y0 - hh, cx + X(0.018), y0], radius=u, fill=p if row == 0 else s, outline=INK, width=u)
                d.rectangle([cx - X(0.006), y0 - hh // 2 - u, cx + X(0.006), y0 - hh // 2 + u], fill=(70, 78, 94))
        d.rectangle([X(0.665), Y(0.515), X(0.675), ground], fill=(70, 78, 94))
        d.rectangle([X(0.935), Y(0.515), X(0.945), ground], fill=(70, 78, 94))
        d.rectangle([0, ground, W, H], fill=(96, 104, 118))                                                   # کفِ لاستیکی
        for k in range(0, H - ground, Y(0.05)):
            d.line([0, ground + k, W, ground + k], fill=(112, 120, 134), width=u)
        d.rectangle([0, ground, W, ground + u * 3], fill=(70, 78, 94))
        cx, cy, r = X(0.88), Y(0.735), int(min(W, H) * 0.075)                                                 # صفحهٔ هالتر تکیه‌داده
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(52, 58, 72), outline=INK, width=u)
        d.ellipse([cx - int(r * 0.72), cy - int(r * 0.72), cx + int(r * 0.72), cy + int(r * 0.72)], outline=p, width=u * 3)
        d.ellipse([cx - int(r * 0.2), cy - int(r * 0.2), cx + int(r * 0.2), cy + int(r * 0.2)], fill=(214, 220, 230))
    else:   # kitchen
        im = Image.new("RGB", (W, H), (246, 240, 229))
        d = ImageDraw.Draw(im)
        step = X(0.06)
        for k in range(0, W, step):                                                                           # کاشیِ دیوار
            d.line([k, 0, k, Y(0.60)], fill=(232, 224, 208), width=u)
        for k in range(0, Y(0.60), step):
            d.line([0, k, W, k], fill=(232, 224, 208), width=u)
        d.rounded_rectangle([X(0.04), Y(0.07), X(0.50), Y(0.29)], radius=u * 3, fill=_lighter(p, 0.6), outline=_darker(p, 0.4), width=u)   # کابینتِ بالا
        d.line([X(0.27), Y(0.07), X(0.27), Y(0.29)], fill=_darker(p, 0.4), width=u)
        d.rounded_rectangle([X(0.245), Y(0.17), X(0.255), Y(0.23)], radius=u, fill=_darker(p, 0.4))
        d.rounded_rectangle([X(0.285), Y(0.17), X(0.295), Y(0.23)], radius=u, fill=_darker(p, 0.4))
        d.rectangle([X(0.60), Y(0.09), X(0.93), Y(0.40)], fill=(180, 140, 100))                               # پنجره
        win = _grad(X(0.93) - X(0.60) - u * 8, Y(0.40) - Y(0.09) - u * 8, (170, 214, 240), (226, 240, 248))
        im.paste(win, (X(0.60) + u * 4, Y(0.09) + u * 4))
        d.line([X(0.765), Y(0.09), X(0.765), Y(0.40)], fill=(180, 140, 100), width=u * 3)
        d.line([X(0.60), Y(0.245), X(0.93), Y(0.245)], fill=(180, 140, 100), width=u * 3)
        d.rectangle([0, Y(0.585), W, Y(0.62)], fill=(206, 196, 180))                                          # لبهٔ کانتر
        d.rectangle([0, ground, W, H], fill=(214, 204, 188))                                                  # کف
        for k in range(0, W, X(0.10)):
            d.line([k, ground, k - X(0.05), H], fill=(200, 190, 174), width=u)
        d.rounded_rectangle([X(0.02), Y(0.665), X(0.98), Y(0.705)], radius=u * 3, fill=(196, 146, 100), outline=_darker((196, 146, 100), 0.4), width=u)   # میز
        d.rectangle([X(0.07), Y(0.705), X(0.10), ground + Y(0.02)], fill=(160, 112, 72))
        d.rectangle([X(0.90), Y(0.705), X(0.93), ground + Y(0.02)], fill=(160, 112, 72))
        d.pieslice([X(0.12), Y(0.60), X(0.30), Y(0.70)], 0, 180, fill=p, outline=INK, width=u)               # کاسه
        d.ellipse([X(0.12), Y(0.645), X(0.30), Y(0.665)], fill=_lighter(p, 0.8), outline=INK, width=u)
        for k, col in enumerate(((217, 74, 61), (242, 107, 33), (232, 162, 43))):                             # میوه
            cx = X(0.16 + k * 0.045)
            d.ellipse([cx - X(0.018), Y(0.625), cx + X(0.018), Y(0.625) + X(0.036)], fill=col, outline=INK, width=u)
        d.rounded_rectangle([X(0.62), Y(0.652), X(0.84), Y(0.668)], radius=u * 2, fill=(222, 190, 140), outline=INK, width=u)   # تختهٔ برش
        for k, col in enumerate(((46, 158, 91), (217, 74, 61), (46, 158, 91), (232, 162, 43))):
            cx = X(0.65 + k * 0.045)
            d.ellipse([cx - X(0.012), Y(0.628), cx + X(0.012), Y(0.652)], fill=col, outline=INK, width=u)
    return im.resize((w, h), Image.LANCZOS).convert("RGB")


def draw(key: str, w: int = 1080, h: int = 1350, brand: tuple[str, str] | list[str] | None = None) -> Image.Image:
    """پس‌زمینهٔ ``key`` با اندازهٔ w×h. ``brand`` = (رنگِ اصلی، رنگِ دوم) برای صحنه‌های بازاریابی؛ کلیدِ ناشناخته ⇒ رنگِ برند."""
    key = key if key in BACKGROUNDS else DEFAULT_BACKGROUND
    b = list(brand or ())
    colours = (b[0] if len(b) > 0 else DEFAULT_BRAND[0], b[1] if len(b) > 1 else (b[0] if b else DEFAULT_BRAND[1]))
    if BACKGROUNDS[key]["group"] == "marketing":
        return _draw_marketing(key, w, h, colours)
    return _draw_story(key, w, h)


def solid(color: str, w: int, h: int) -> Image.Image:
    return Image.new("RGB", (w, h), _hex(color))


def render_file(key: str, folder: Path, w: int, h: int, brand=None) -> Path:
    """پس‌زمینه به‌صورتِ فایلِ PNG (کَش با کلیدِ نام، اندازه و رنگِ برند)."""
    import hashlib

    folder.mkdir(parents=True, exist_ok=True)
    tag = hashlib.sha1("|".join(brand or ()).encode()).hexdigest()[:6] if brand else "x"
    p = folder / f"bg_{key}_{w}x{h}_{tag}.png"
    if not p.exists():
        draw(key, w, h, brand).save(p)
    return p
