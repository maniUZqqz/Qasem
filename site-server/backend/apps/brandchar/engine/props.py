"""وسیله‌های دستِ شخصیتِ برداری (دمبل، برگهٔ برنامه، گوشی، ...). هر وسیله در قابِ «مشت» کشیده می‌شود: مبدأ = جای گرفتنِ دست، بالا = ‎−y، جلو = ‎+x.

``draw(kind, colour, ink, k)`` ⇒ لیستِ گره‌های ``vector``. ``k`` مقیاسِ وسیله است (چیبی کمی کوچک‌تر). رنگ‌ها از سند می‌آیند: ``colour`` رنگِ وسیله، ``ink`` رنگِ خط.
"""
from __future__ import annotations

from . import vector as V

STEEL = "#6b7280"
PAPER = "#f4f1ea"
DARK = "#1f2430"
WOOD = "#b0763c"


def _p(cmds, fill=None, stroke=None, sw=0.0, op=1.0, cap="round"):
    return V.P(cmds, fill=fill, stroke=stroke, sw=sw, op=op, cap=cap)


def draw(kind: str, colour: str, ink: str, k: float = 1.0, *, ow: float = 0.0) -> list:
    """گره‌های وسیله. ``ow`` پهنای خطِ دورِ سبک (۰ = بدونِ خط)."""
    ou = ink if ow > 0 else None

    def sh(cmds, fill, w=None):
        return _p(cmds, fill=fill, stroke=ou, sw=(ow if w is None else w) if ou else 0.0)

    g = V.G()
    if kind == "dumbbell":
        g.add(sh(V.capsule(-40, 0, 40, 0, 11), STEEL))
        for sx in (-1, 1):
            g.add(sh(V.rrect(sx * 40 - 11 + (0 if sx > 0 else 0), -28, 22, 56, 7), colour))
            g.add(sh(V.rrect(sx * 40 + (9 if sx > 0 else -21), -19, 12, 38, 5), colour))
    elif kind == "clipboard":
        g.add(sh(V.rrect(-30, -92, 60, 88, 8), WOOD))
        g.add(sh(V.rrect(-24, -82, 48, 72, 4), PAPER, 0))
        for i, y in enumerate((-70, -56, -42, -28)):
            g.add(_p(V.poly([(-16, y), (16 - (i % 2) * 8, y)], False), stroke=colour, sw=4.5))
        g.add(sh(V.rrect(-12, -98, 24, 14, 5), STEEL))
    elif kind == "phone":
        g.add(sh(V.rrect(-17, -62, 34, 66, 7), DARK))
        g.add(_p(V.rrect(-13, -56, 26, 50, 3), fill=colour))
        g.add(_p(V.circle(0, -2, 2.2), fill="#8a8f9c"))
    elif kind == "tablet":
        g.add(sh(V.rrect(-34, -84, 68, 88, 8), DARK))
        g.add(_p(V.rrect(-29, -78, 58, 76, 3), fill=PAPER))
        g.add(_p(V.rrect(-24, -72, 48, 20, 3), fill=colour))
        g.add(_p(V.poly([(-24, -42), (22, -42)], False), stroke=colour, sw=4))
        g.add(_p(V.poly([(-24, -30), (10, -30)], False), stroke=colour, sw=4))
    elif kind == "key":
        g.add(sh(V.circle(0, -52, 17), colour))
        g.add(_p(V.circle(0, -52, 7), fill=PAPER))
        g.add(sh(V.capsule(0, -38, 0, 18, 9), colour))
        g.add(sh(V.rrect(0, -2, 18, 8, 3), colour))
        g.add(sh(V.rrect(0, 10, 13, 8, 3), colour))
    elif kind == "bat":
        g.add(sh(V.capsule(0, 12, 0, -120, 11, 24), WOOD))
        g.add(_p(V.poly([(-9, -34), (9, -34)], False), stroke=colour, sw=7, cap="butt"))
    elif kind == "sign":
        g.add(sh(V.capsule(0, 22, 0, -118, 8), WOOD))
        g.add(sh(V.rrect(-52, -172, 104, 62, 9), colour))
        g.add(_p(V.rrect(-44, -164, 88, 46, 5), fill=PAPER))
        g.add(_p(V.poly([(-30, -150), (30, -150)], False), stroke=colour, sw=6))
        g.add(_p(V.poly([(-30, -134), (14, -134)], False), stroke=colour, sw=6))
    elif kind == "map":
        g.add(sh(V.rrect(-34, -84, 68, 84, 5), PAPER))
        g.add(_p(V.poly([(-34, -56), (34, -56)], False), stroke="#d6cfc0", sw=2.5))
        g.add(_p(V.poly([(0, -84), (0, 0)], False), stroke="#d6cfc0", sw=2.5))
        g.add(_p(V.curve([(-26, -20), (-8, -40), (8, -26), (24, -66)]), stroke=colour, sw=4.5))
        g.add(_p(V.circle(24, -66, 6), fill=colour))
        g.add(sh(V.capsule(-34, -84, -34, 0, 12), colour))
    elif kind == "bag":
        g.add(_p(V.curve([(-18, -62), (-16, -92), (16, -92), (18, -62)]), stroke=ink if ow > 0 else DARK, sw=6))
        g.add(sh(V.rounded_poly([(-36, -62), (36, -62), (30, 8), (-30, 8)], 8), colour))
        g.add(_p(V.poly([(-36, -62), (36, -62)], False), stroke="#ffffff", sw=5, op=0.55, cap="butt"))
    elif kind == "pan":
        g.add(sh(V.capsule(0, 6, 78, 6, 12), "#3a3f4c"))
        g.add(sh(V.ellipse(-8, -2, 44, 14), colour))
        g.add(_p(V.ellipse(-8, -6, 36, 8), fill="#2b2f3a"))
    elif kind == "box":
        g.add(sh(V.rrect(-38, -70, 76, 70, 6), WOOD))
        g.add(_p(V.rrect(-9, -70, 18, 70, 0), fill=colour, op=0.9))
        g.add(_p(V.poly([(-38, -50), (38, -50)], False), stroke="#8a5a2c", sw=3))
    elif kind == "megaphone":
        g.add(sh(V.rounded_poly([(-10, -22), (-10, 6), (46, 34), (46, -50)], 6), colour))
        g.add(sh(V.ellipse(46, -8, 11, 42), "#ffffff"))
        g.add(sh(V.rrect(-24, -16, 20, 24, 5), DARK))
    elif kind == "torch":
        g.add(sh(V.capsule(0, 14, 0, -62, 12, 18), WOOD))
        g.add(sh(V.curve([(-18, -62), (-24, -86), (0, -112), (22, -86), (18, -62)], closed=True), "#e8a22b"))
        g.add(_p(V.curve([(-9, -66), (-10, -82), (0, -98), (10, -82), (9, -66)], closed=True), fill="#ffe08a"))
    else:                                       # none/ناشناخته
        return []
    if k != 1.0:
        g.m = V.mscale(k)
    return [g]
