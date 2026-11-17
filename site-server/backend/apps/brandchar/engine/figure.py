"""شخصیتِ برداری: همان اسکلت و همان ۲۹ ژستِ ماسکوت، با تنِ پوشیده، چهرهٔ کامل و سه سبکِ کشیدن (تخت، چیبی، استیکرِ خط‌دور).

اسکلت (``apps.mascot.engine.rig`` و ``poses``) از ماسکوت می‌آید؛ فقط طول‌ها و ریخت فرق دارد. اندام‌ها خط‌های ضخیمِ گردِ عبوری از مفصل‌ها هستند (دو لایه: خطِ دور ⇒ رنگ)
تا مفصل‌ها درز نداشته باشند؛ سر، تن و وسیله گروه‌هایی با ماتریسِ خودِ جزء‌اند. شخصیت رو به راست کشیده می‌شود؛ ``flip`` کلِ بوم را آینه می‌کند و لوگوی روی سینه از پیش
آینه می‌شود تا هرگز وارونه دیده نشود.

``build`` ⇒ ``Built`` (گرافِ صحنه + جای سر و دست‌ها)؛ ``render_actor`` همان امضای ``apps.mascot.engine.stage.render_actor`` را دارد (پس پس‌زمینه‌ها، حباب، کپشن و
اندازه‌های پست همه مشترک‌اند)؛ ``to_svg`` همان صحنه را متنِ SVG می‌کند.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from PIL import Image, ImageDraw, ImageOps

from apps.mascot.engine import parts as mparts
from apps.mascot.engine import poses
from apps.mascot.engine import rig as g
from apps.mascot.engine import stage

from . import doc as D
from . import props
from . import vector as V

DESIGN = (600, 900)
GROUND = 862.0
CX = 300.0
HEAD_OVERLAP = 8.0


# ------------------------------------------------------------------ پارامترهای سبک

@dataclass(frozen=True)
class St:
    key: str
    head_rx: float
    head_ry: float
    torso: float
    upper: float
    fore: float
    thigh: float
    shin: float
    arm_w: float
    leg_w: float
    sh_w: float            # نیم‌پهنای شانه (نمای نیم‌رخ)
    hip_w: float           # نیم‌پهنای باسن
    hand_r: float
    foot_len: float
    foot_h: float
    ow: float              # پهنای خطِ دور (۰ = بدونِ خط)
    border: float          # حاشیهٔ سفیدِ بریده (فقط استیکر)
    prop_k: float
    eye_k: float
    face_y: float          # جای چشم‌ها (کسری از نیم‌ارتفاعِ سر)
    outline_mode: str      # none | ink | tint
    fit: float = 1.0       # ضریبِ بزرگ‌نماییِ نهایی (تا قدِ شخصیت‌ها در کادر هم‌اندازهٔ آدمک‌چوبی شود)


STYLE: dict[str, St] = {
    "flat": St("flat", 88, 84, 192, 100, 92, 126, 118, 32, 44, 58, 50, 18, 58, 32, 0.0, 0.0, 1.0, 1.15, 0.04, "none", 1.14),
    "chibi": St("chibi", 124, 116, 136, 88, 78, 84, 78, 34, 44, 58, 52, 22, 58, 36, 4.2, 0.0, 0.85, 1.3, 0.12, "tint", 1.22),
    "sticker": St("sticker", 90, 86, 188, 98, 88, 122, 114, 32, 42, 56, 48, 18, 56, 32, 6.5, 15.0, 1.0, 1.15, 0.05, "ink", 1.12),
}
BODY_K = {"slim": (0.86, 0.9), "regular": (1.0, 1.0), "athletic": (1.2, 1.08), "round": (1.22, 1.16)}
HEAD_K = {"round": (1.0, 1.0), "tall": (0.9, 1.16), "wide": (1.18, 0.9), "square": (1.04, 0.96)}
AIRBORNE = {"cheer": 34.0}
ARMS_UP = {"cheer", "hands_up", "surrender", "lift", "shock"}       # دست‌های بالا پشتِ سر می‌روند تا روی صورت نیفتند


def shade(hx: str, f: float) -> str:
    """رنگ را تیره (f<1) یا روشن (f>1) می‌کند."""
    h = hx.lstrip("#")
    r, gg, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    if f <= 1:
        r, gg, b = (int(c * f) for c in (r, gg, b))
    else:
        t = f - 1
        r, gg, b = (int(c + (255 - c) * t) for c in (r, gg, b))
    return "#%02x%02x%02x" % (max(0, min(255, r)), max(0, min(255, gg)), max(0, min(255, b)))


@dataclass
class Built:
    root: V.G
    head: tuple[float, float, float]                 # مرکز و شعاعِ سر در مختصاتِ طراحی (پس از زمین‌گذاری)
    hands: tuple[tuple[float, float], tuple[float, float]]
    prop: str
    pose: str
    expression: str
    palette_ok: list = field(default_factory=list)
    frames: dict = field(default_factory=dict)       # ماتریسِ هر جزء (قبل از زمین‌گذاری)
    anchors: dict = field(default_factory=dict)      # قابِ جایگیریِ لایه‌های دستی در مختصاتِ نهایی: world/head/body/hand ⇒ ماتریس
    ground_dy: float = 0.0


class _B:
    """سازندهٔ شکل‌ها با خطِ دورِ همان سبک."""

    def __init__(self, st: St, ink: str):
        self.st, self.ink = st, ink

    def sh(self, cmds, fill, *, ow: float | None = None, stroke: str | None = None, op: float = 1.0) -> V.P:
        w = self.st.ow if ow is None else ow
        if w <= 0 or fill is None and stroke is None:
            return V.P(cmds, fill=fill, op=op)
        col = stroke or (self.ink if self.st.outline_mode == "ink" else shade(fill or "#808080", 0.55))
        return V.P(cmds, fill=fill, stroke=col, sw=w, op=op, join="round")

    def line(self, pts, colour, w, *, cap="round", closed=False) -> V.P:
        return V.P(V.poly(pts, closed), stroke=colour, sw=w, cap=cap, join="round")


# ------------------------------------------------------------------ اسکلت

SHOULDER_K = 0.78            # محورِ شانه = این کسر از نیم‌پهنای شانه به بیرون؛ قبلاً هر دو بازو از وسطِ سینه می‌آمدند و آستین زیرِ چانه می‌نشست


def _rig(st: St, hip_y: float, shoulder_dx: float = 4.0) -> g.Rig:
    rig = g.Rig(size=DESIGN, anchor=(CX, GROUND))

    def part(name, pos, parent, z):
        rig.parts[name] = g.Part(name=name, image=None, pivot=(0.0, 0.0), pos=pos, z=z, parent=parent)

    hip = (CX, hip_y)
    part("body", hip, None, 10)
    part("leg_l", (hip[0] - 9, hip[1]), None, 5)
    part("leg_r", (hip[0] + 9, hip[1]), None, 6)
    part("shin_l", (0, st.thigh), "leg_l", 5)
    part("shin_r", (0, st.thigh), "leg_r", 6)
    part("arm_l", (-shoulder_dx, -st.torso + 14), "body", 12)
    part("arm_r", (shoulder_dx, -st.torso + 14), "body", 30)
    part("forearm_l", (0, st.upper), "arm_l", 12)
    part("forearm_r", (0, st.upper), "arm_r", 30)
    part("head", (0, -st.torso + 2), "body", 20)
    rig.validate()
    return rig


#: ژست‌هایی که برای سبک‌های برداری (تنِ پوشیده و سرِ بزرگ‌تر) دوباره تنظیم شده‌اند؛ آدمک‌چوبی همان جدولِ ماسکوت را می‌رود.
#: «wave»: بازو به‌سمتِ بیرون و ساعد به بالا، کنارِ سر (قبلاً از روی صورت می‌گذشت)؛ «lift»: بازوها بلندتر می‌شوند تا هالتر بالای سر برسد.
VECTOR_POSES: dict[str, dict[str, dict]] = {
    "flat": {"wave": {"arm_r": {"rot": -104}, "forearm_r": {"rot": -76}, "head": {"rot": 4}}},
    "sticker": {"wave": {"arm_r": {"rot": -104}, "forearm_r": {"rot": -76}, "head": {"rot": 4}}},
    "chibi": {"wave": {"arm_r": {"rot": -97, "sy": 1.32}, "forearm_r": {"rot": -83}, "head": {"rot": 4}},
              "lift": {"arm_l": {"rot": 168, "sy": 1.62}, "forearm_l": {"rot": 10}, "arm_r": {"rot": -168, "sy": 1.62}, "forearm_r": {"rot": -10}, "leg_l": {"rot": 7}, "leg_r": {"rot": -7}}},
}


def _pose_tuples(pose: str, k: float, style: str = "flat") -> dict:
    out = stage.pose_tuples(pose)
    over = VECTOR_POSES.get(style, {}).get(pose)
    if over:
        out = dict(out)
        for part_name, vals in over.items():
            dx, dy, rot, sx, sy = out.get(part_name, (0.0, 0.0, 0.0, 1.0, 1.0))
            out[part_name] = (vals.get("dx", dx), vals.get("dy", dy), vals.get("rot", rot), vals.get("sx", sx), vals.get("sy", sy))
    return {n: (dx * k, dy * k, rot, sx, sy) for n, (dx, dy, rot, sx, sy) in out.items()}


# ------------------------------------------------------------------ سر و چهره

def _head_nodes(B: _B, d: dict, st: St, expression: str, rx: float, ry: float, back: list, front: list) -> None:
    """همهٔ اجزای سر در مختصاتِ «مرکزِ سر» (۰،۰)؛ ``back`` پشتِ سر، ``front`` روی سر."""
    ink = d["outline"]
    skin = d["skin"]
    brow_kind, eye_kind, mouth_kind, _shape = mparts.expression_parts(expression)
    fx = rx * 0.06                                                      # کمی به سمتِ جلو (راست)
    ey = ry * st.face_y
    ex = rx * (0.40 if st.key != "chibi" else 0.43)
    er = (rx * 0.085 if st.key != "chibi" else rx * 0.14) * 1.0
    # --- موی پشتی
    hc, hk = d["hair_colour"], d["hair"]
    if hk in ("ponytail", "bun", "long", "bob", "curly", "short", "spikes", "tuft", "buzz"):
        pass
    if hk == "ponytail":
        back.append(B.sh(V.curve([(-rx * 0.78, -ry * 0.45), (-rx * 1.35, -ry * 0.1), (-rx * 1.25, ry * 0.7), (-rx * 0.95, ry * 1.0)]), None, stroke=hc, ow=ry * 0.34))
    if hk == "long":
        back.append(B.sh(V.rounded_poly([(-rx * 1.05, -ry * 0.3), (rx * 0.2, -ry * 0.9), (rx * 0.7, ry * 0.2), (rx * 0.35, ry * 1.55), (-rx * 1.0, ry * 1.55)], rx * 0.3), hc))
    if hk == "bob":
        back.append(B.sh(V.rrect(-rx * 1.12, -ry * 0.55, rx * 2.0, ry * 1.55, rx * 0.55), hc))
    # --- سر
    head_cmds = V.ellipse(0, 0, rx, ry) if d["head_style"] != "square" else V.rrect(-rx, -ry, rx * 2, ry * 2, min(rx, ry) * 0.62)
    front.append(B.sh(head_cmds, skin))
    front.append(B.sh(V.ellipse(-rx * 0.96, ry * 0.12, rx * 0.12, ry * 0.17), skin))        # گوش
    if d["blush"] or st.key == "chibi":
        for sx in (-1, 1):
            front.append(V.P(V.ellipse(fx + sx * rx * 0.62, ey + ry * 0.36, rx * 0.15, ry * 0.095), fill="#ef7f86", op=0.55 if d["blush"] else 0.4))
    if d["freckles"]:
        for sx in (-1, 1):
            for dx, dy in ((-0.06, 0.0), (0.04, 0.07), (0.1, -0.03)):
                front.append(V.P(V.circle(fx + sx * rx * (0.46 + dx), ey + ry * (0.26 + dy), rx * 0.022), fill=shade(skin, 0.68)))
    # --- چشم‌ها
    eyes_k = d["eye_style"]
    if eye_kind in ("happy",):
        eyes_k = "happy"
    for i, sx in enumerate((-1, 1)):
        x, y = fx + sx * ex, ey
        kind = eyes_k
        if kind == "wink" and sx == 1:
            kind = "happy"
        elif kind == "wink":
            kind = "dots"
        if eye_kind == "narrow":
            front.append(V.P(V.ellipse(x, y, er * 1.5, er * 0.62), fill=ink))
        elif eye_kind == "down":
            front.append(V.P(V.ellipse(x, y + er * 0.2, er * 1.1, er * 1.0), fill=ink))
        elif eye_kind == "wide":
            front.append(V.P(V.ellipse(x, y, er * 1.75, er * 1.9), fill="#ffffff", stroke=ink, sw=max(2.5, er * 0.3)))
            front.append(V.P(V.circle(x + er * 0.15, y, er * 0.75), fill=ink))
        elif kind == "happy":
            front.append(V.P(V.curve([(x - er * 1.5, y + er * 0.6), (x, y - er * 1.0), (x + er * 1.5, y + er * 0.6)]), stroke=ink, sw=max(3.5, er * 0.5), cap="round"))
        elif kind == "dots":
            front.append(V.P(V.circle(x, y, er * 0.95), fill=ink))
        elif kind == "sleepy":
            front.append(V.P(V.ellipse(x, y, er * 1.35, er * 1.0), fill="#ffffff", stroke=ink, sw=max(2.2, er * 0.28)))
            front.append(V.P(V.poly([(x - er * 1.5, y - er * 0.1), (x + er * 1.5, y - er * 0.1)], False), stroke=ink, sw=max(3.5, er * 0.5), cap="round"))
            front.append(V.P(V.circle(x + er * 0.1, y + er * 0.35, er * 0.5), fill=ink))
        elif kind == "big":
            front.append(V.P(V.ellipse(x, y, er * 1.55, er * 1.95), fill=ink))
            front.append(V.P(V.circle(x + er * 0.42, y - er * 0.7, er * 0.55), fill="#ffffff"))
            front.append(V.P(V.circle(x - er * 0.45, y + er * 0.75, er * 0.28), fill="#ffffff"))
        else:                                                # round
            front.append(V.P(V.circle(x, y, er * 1.25), fill=ink))
            front.append(V.P(V.circle(x + er * 0.38, y - er * 0.4, er * 0.4), fill="#ffffff"))
    # --- ابرو
    if d["brows"] != "none":
        bw = {"normal": 4.6, "thick": 7.2, "thin": 3.0}[d["brows"]] * (rx / 74)
        by = ey - ry * (0.30 if st.key != "chibi" else 0.34)
        # (پایینِ سوی چهره، پایینِ سوی بیرون، بالا‌بردن به کسری از ry): «درون» = نزدیک به وسطِ صورت
        inner_dy, outer_dy, lift = {"flat": (0, 0, 0.0), "up": (0, 0, -0.05), "sad": (-6, 3, 0.0), "angry": (6, -4, 0.0), "worry": (-7, 3, 0.0), "high": (0, 0, -0.11),
                                    "smirk": (0, 0, 0.0)}.get(brow_kind, (0, 0, 0.0))
        for sx in (-1, 1):
            x_in, x_out = fx + sx * ex - sx * er * 1.6, fx + sx * ex + sx * er * 1.6
            y_in, y_out = by + lift * ry + inner_dy * (rx / 74), by + lift * ry + outer_dy * (rx / 74)
            if brow_kind == "smirk" and sx == 1:
                y_in, y_out = y_in - 5, y_out - 5
            front.append(V.P(V.poly([(x_in, y_in), (x_out, y_out)], False), stroke=shade(hc, 0.9) if hk != "none" else ink, sw=bw, cap="round"))
    # --- بینی
    if d["nose"] == "dot":
        front.append(V.P(V.circle(fx + rx * 0.06, ey + ry * 0.3, rx * 0.04), fill=shade(skin, 0.62)))
    elif d["nose"] == "button":
        front.append(V.P(V.ellipse(fx + rx * 0.06, ey + ry * 0.32, rx * 0.075, ry * 0.06), fill=shade(skin, 0.8), stroke=shade(skin, 0.58), sw=2.2))
    # --- دهان
    my = ey + ry * (0.56 if st.key != "chibi" else 0.5)
    mw = rx * (0.25 if st.key != "chibi" else 0.17)
    mcol = shade(ink, 1.0)
    if d["extra"] != "mask":
        if expression == "laugh":
            front.append(V.P(V.curve([(fx - mw * 1.25, my - 2), (fx, my + mw * 1.5), (fx + mw * 1.25, my - 2)], closed=True), fill="#5a2230", stroke=ink, sw=max(2.5, rx * 0.04)))
            front.append(V.P(V.curve([(fx - mw * 0.7, my + mw * 0.9), (fx, my + mw * 0.55), (fx + mw * 0.7, my + mw * 0.9)], closed=True), fill="#e8707a"))
        elif expression == "surprised":
            front.append(V.P(V.ellipse(fx, my + 4, mw * 0.6, mw * 0.85), fill="#5a2230", stroke=ink, sw=max(2.5, rx * 0.04)))
        elif expression == "scared":
            front.append(V.P(V.curve([(fx - mw, my + 6), (fx - mw * 0.4, my - 3), (fx + mw * 0.4, my + 5), (fx + mw, my - 2)]), stroke=mcol, sw=max(3, rx * 0.05)))
        elif mouth_kind == "smile":
            front.append(V.P(V.curve([(fx - mw, my - 2), (fx, my + mw * 0.8), (fx + mw, my - 2)]), stroke=mcol, sw=max(3.2, rx * 0.05)))
        elif mouth_kind == "frown":
            front.append(V.P(V.curve([(fx - mw, my + 6), (fx, my - mw * 0.35), (fx + mw, my + 6)]), stroke=mcol, sw=max(3.2, rx * 0.05)))
        elif mouth_kind == "clench":
            front.append(V.P(V.rrect(fx - mw, my - 3, mw * 2, 11, 4), fill="#ffffff", stroke=ink, sw=max(2.5, rx * 0.04)))
            front.append(V.P(V.poly([(fx, my - 3), (fx, my + 8)], False), stroke=ink, sw=2))
        elif mouth_kind == "smirk":
            front.append(V.P(V.curve([(fx - mw * 0.7, my + 2), (fx + mw * 0.1, my + 4), (fx + mw * 1.1, my - 5)]), stroke=mcol, sw=max(3.2, rx * 0.05)))
        else:
            front.append(V.P(V.poly([(fx - mw * 0.7, my + 1), (fx + mw * 0.7, my + 1)], False), stroke=mcol, sw=max(3.2, rx * 0.05)))
        if d["beard"]:
            for i in range(14):
                a = math.pi * (0.08 + 0.84 * i / 13)
                front.append(V.P(V.circle(fx + math.cos(a) * rx * 0.72, ry * 0.2 + math.sin(a) * ry * 0.72, 1.7), fill=shade(skin, 0.55), op=0.7))
    else:                                                       # ماسک
        front.append(B.sh(V.rounded_poly([(fx - rx * 0.62, ey + ry * 0.22), (fx + rx * 0.7, ey + ry * 0.22), (fx + rx * 0.55, ey + ry * 0.85), (fx - rx * 0.55, ey + ry * 0.85)], 8), d["extra_colour"]))
        for sx in (-1, 1):
            front.append(V.P(V.poly([(fx + sx * rx * 0.62, ey + ry * 0.3), (fx + sx * rx * 0.98, ey + ry * 0.12)], False), stroke=d["extra_colour"], sw=3))
    # --- مو (جلو)
    if hk in ("tuft", "short", "buzz", "spikes", "bob", "ponytail", "bun", "curly", "long"):
        top = -ry
        if hk == "buzz":
            front.append(V.P(V.curve([(-rx * 0.97, -ry * 0.28), (-rx * 0.8, -ry * 0.85), (0, -ry * 1.02), (rx * 0.8, -ry * 0.85), (rx * 0.97, -ry * 0.28), (rx * 0.6, -ry * 0.55), (0, -ry * 0.68), (-rx * 0.6, -ry * 0.55)], closed=True), fill=hc, op=0.92))
        elif hk in ("short", "ponytail", "bun"):
            front.append(B.sh(V.curve([(-rx * 1.0, -ry * 0.1), (-rx * 0.95, -ry * 0.82), (0, -ry * 1.12), (rx * 0.95, -ry * 0.8), (rx * 1.02, -ry * 0.12), (rx * 0.6, -ry * 0.58), (rx * 0.05, -ry * 0.72), (-rx * 0.5, -ry * 0.6)], closed=True), hc))
            if hk == "bun":
                front.append(B.sh(V.circle(-rx * 0.15, top - ry * 0.22, rx * 0.3), hc))
        elif hk == "bob":
            front.append(B.sh(V.curve([(-rx * 1.1, ry * 0.5), (-rx * 1.12, -ry * 0.85), (0, -ry * 1.18), (rx * 1.08, -ry * 0.85), (rx * 1.04, ry * 0.2), (rx * 0.62, -ry * 0.5), (0, -ry * 0.62), (-rx * 0.5, -ry * 0.5)], closed=True), hc))
        elif hk == "long":
            front.append(B.sh(V.curve([(-rx * 1.06, ry * 0.9), (-rx * 1.1, -ry * 0.85), (0, -ry * 1.16), (rx * 1.0, -ry * 0.85), (rx * 1.0, ry * 0.05), (rx * 0.55, -ry * 0.5), (0, -ry * 0.64), (-rx * 0.5, -ry * 0.5)], closed=True), hc))
        elif hk == "spikes":
            pts = [(-rx * 0.95, -ry * 0.3)]
            for i in range(6):
                a = math.radians(-168 + i * 31)
                pts += [(math.cos(a) * rx * 1.28, math.sin(a) * ry * 1.38), (math.cos(a + math.radians(15)) * rx * 0.92, math.sin(a + math.radians(15)) * ry * 0.88)]
            pts.append((rx * 0.95, -ry * 0.3))
            front.append(B.sh(V.poly(pts), hc))
        elif hk == "curly":
            for i in range(7):
                a = math.radians(-165 + i * 25)
                front.append(B.sh(V.circle(math.cos(a) * rx * 0.88, math.sin(a) * ry * 0.92, rx * 0.26), hc))
            front.append(B.sh(V.curve([(-rx * 0.8, -ry * 0.4), (0, -ry * 0.78), (rx * 0.8, -ry * 0.4), (rx * 0.5, -ry * 0.3), (0, -ry * 0.45), (-rx * 0.5, -ry * 0.3)], closed=True), hc, ow=0))
        elif hk == "tuft":
            front.append(B.sh(V.curve([(-rx * 0.18, -ry * 0.98), (-rx * 0.1, -ry * 1.42), (rx * 0.3, -ry * 1.12), (rx * 0.1, -ry * 0.96)], closed=True), hc))
    # --- عینک
    if d["extra"] == "glasses":
        gr = rx * 0.27 if st.key != "chibi" else rx * 0.3
        for sx in (-1, 1):
            front.append(V.P(V.circle(fx + sx * ex, ey, gr), fill="#ffffff", op=0.18, stroke=d["extra_colour"], sw=max(3.2, rx * 0.05)))
        front.append(V.P(V.poly([(fx - ex + gr, ey), (fx + ex - gr, ey)], False), stroke=d["extra_colour"], sw=max(3, rx * 0.045)))
        front.append(V.P(V.poly([(fx - ex - gr, ey), (-rx * 0.98, ey - ry * 0.05)], False), stroke=d["extra_colour"], sw=max(3, rx * 0.045)))
    # --- کلاه
    _hat(B, d, st, rx, ry, front, back)


def _hat(B: _B, d: dict, st: St, rx: float, ry: float, front: list, back: list) -> None:
    hat, c = d["hat"], d["hat_colour"]
    if hat == "none":
        return
    if hat == "cap":
        front.append(B.sh(V.curve([(-rx * 1.04, -ry * 0.22), (-rx * 0.95, -ry * 1.0), (0, -ry * 1.22), (rx * 0.95, -ry * 1.0), (rx * 1.04, -ry * 0.22)], closed=True), c))
        front.append(B.sh(V.rounded_poly([(rx * 0.2, -ry * 0.3), (rx * 1.58, -ry * 0.24), (rx * 1.56, -ry * 0.1), (rx * 0.2, -ry * 0.1)], 6), shade(c, 0.82)))
        front.append(V.P(V.circle(0, -ry * 1.22, rx * 0.07), fill=shade(c, 0.8)))
    elif hat == "beanie":
        front.append(B.sh(V.curve([(-rx * 1.0, -ry * 0.28), (-rx * 0.96, -ry * 1.0), (0, -ry * 1.3), (rx * 0.96, -ry * 1.0), (rx * 1.0, -ry * 0.28)], closed=True), c))
        front.append(B.sh(V.rrect(-rx * 1.06, -ry * 0.44, rx * 2.12, ry * 0.24, ry * 0.1), shade(c, 0.85)))
        front.append(B.sh(V.circle(0, -ry * 1.34, rx * 0.17), "#ffffff" if c.lower() != "#ffffff" else shade(c, 0.9)))
    elif hat == "headband":
        front.append(V.P(V.curve([(-rx * 1.0, -ry * 0.34), (0, -ry * 0.5), (rx * 1.0, -ry * 0.34)]), stroke=shade(c, 0.5) if B.st.ow > 0 else None, sw=ry * 0.27 + B.st.ow * 1.6, cap="butt") if B.st.ow > 0 else None)
        front.append(V.P(V.curve([(-rx * 1.0, -ry * 0.34), (0, -ry * 0.5), (rx * 1.0, -ry * 0.34)]), stroke=c, sw=ry * 0.27, cap="butt"))
        front.append(B.sh(V.rounded_poly([(-rx * 1.0, -ry * 0.34), (-rx * 1.34, -ry * 0.55), (-rx * 1.3, -ry * 0.12)], 3), c))
    elif hat == "tophat":
        front.append(B.sh(V.rrect(-rx * 0.62, -ry * 1.7, rx * 1.24, ry * 1.2, 7), c))
        front.append(B.sh(V.rrect(-rx * 1.1, -ry * 0.62, rx * 2.2, ry * 0.2, 6), c))
        front.append(V.P(V.rrect(-rx * 0.62, -ry * 0.82, rx * 1.24, ry * 0.15, 0), fill=d["top2"]))
    elif hat == "hood":
        front.append(V.P(V.ellipse(0, -ry * 0.02, rx * 1.1, ry * 1.1), stroke=B.ink if B.st.ow > 0 else None, sw=ry * 0.42 + B.st.ow * 1.6) if B.st.ow > 0 else None)
        front.append(V.P(V.ellipse(0, -ry * 0.02, rx * 1.1, ry * 1.1), stroke=c, sw=ry * 0.42))
    elif hat == "chef":
        for cx, cy, r in ((-rx * 0.56, -ry * 1.22, rx * 0.42), (rx * 0.56, -ry * 1.22, rx * 0.42), (0, -ry * 1.44, rx * 0.5)):
            front.append(B.sh(V.circle(cx, cy, r), c))
        front.append(B.sh(V.rrect(-rx * 0.98, -ry * 1.28, rx * 1.96, ry * 0.76, 10), c))
        front.append(V.P(V.poly([(-rx * 0.98, -ry * 0.62), (rx * 0.98, -ry * 0.62)], False), stroke=shade(c, 0.8), sw=3))


# ------------------------------------------------------------------ تن و لباس

def _torso(B: _B, d: dict, st: St, bk: tuple[float, float], logo: Image.Image | None, flip: bool, *, front_nodes: list, back_nodes: list) -> V.G:
    """تن در قابِ بدن: مبدأ = وسطِ باسن، بالا = ‎−y. ``back_nodes`` (کوله، کلاهِ هودی) پشتِ بدن و ``front_nodes`` (پیش‌بند، لوگو) روی آن می‌ایند."""
    T = st.torso
    sw, hw = st.sh_w * bk[0], st.hip_w * bk[0]
    grp = V.G(name="body")
    top, top2 = d["top"], d["top2"]
    outfit = d["outfit"]
    base = {"suit": top, "tank": top}.get(outfit, top)
    skin = d["skin"]
    # کوله و هود پشتِ تن
    if d["extra"] == "backpack":
        grp.add(B.sh(V.rrect(-sw - 36, -T + 24, 54, T * 0.62, 16), d["extra_colour"]))
        grp.add(V.P(V.poly([(-sw - 14, -T + 40), (-sw - 14, -T * 0.55)], False), stroke=shade(d["extra_colour"], 0.7), sw=5, cap="round"))
    if outfit == "hoodie":
        grp.add(B.sh(V.ellipse(-4, -T - 6, sw * 0.9, 24), shade(top, 0.86)))
    cmds = V.rounded_poly([(-sw, -T + 10), (sw, -T + 10), (hw, 0), (-hw, 0)], sw * 0.62)
    grp.add(B.sh(cmds, base))
    # --- لباسِ روی تن
    wid = lambda y: (hw + (sw - hw) * (1 - (-y) / max(1.0, T - 10))) if y <= 0 else hw       # نیم‌پهنا در ارتفاعِ y (۰ = باسن، ‎−T+10 = شانه)
    if outfit == "jersey":
        for y0, h in ((-T * 0.52, 14), (-T * 0.52 + 22, 8)):
            w0, w1 = wid(y0) - 2, wid(y0 + h) - 2
            grp.add(V.P(V.poly([(-w0, y0), (w0, y0), (w1, y0 + h), (-w1, y0 + h)]), fill=top2))
        grp.add(V.P(V.curve([(-sw * 0.5, -T + 12), (0, -T + 30), (sw * 0.5, -T + 12)]), stroke=top2, sw=7))
    elif outfit == "tshirt" or outfit == "tank":
        if outfit == "tshirt":
            grp.add(V.P(V.curve([(-sw * 0.5, -T + 12), (0, -T + 28), (sw * 0.5, -T + 12)]), stroke=shade(top, 0.78), sw=6))
        else:
            grp.add(V.P(V.curve([(-sw * 0.62, -T + 12), (0, -T + 46), (sw * 0.62, -T + 12)]), fill=skin))
    elif outfit == "hoodie":
        grp.add(B.sh(V.rrect(-hw * 0.7, -T * 0.34, hw * 1.4, T * 0.2, 9), shade(top, 0.9), ow=max(0, st.ow * 0.6)))
        for sx in (-1, 1):
            grp.add(V.P(V.poly([(sx * 8, -T + 24), (sx * 9, -T + 62)], False), stroke=top2, sw=4))
    elif outfit == "suit":
        grp.add(V.P(V.poly([(-sw * 0.5, -T + 10), (sw * 0.5, -T + 10), (0, -T * 0.55)]), fill="#ffffff"))
        for sx in (-1, 1):
            grp.add(V.P(V.poly([(sx * sw * 0.55, -T + 10), (sx * sw * 0.1, -T * 0.52), (sx * sw * 0.7, -T * 0.4)]), fill=shade(top, 0.78)))
    elif outfit == "track":
        grp.add(V.P(V.poly([(2, -T + 12), (2, -2)], False), stroke=top2, sw=5))
        grp.add(V.P(V.poly([(-sw * 0.8, -T + 14), (-hw * 0.8, -4)], False), stroke=top2, sw=7, cap="butt"))
    # --- گردن‌آویز
    nk, nc = d["neck"], d["neck_colour"]
    if nk == "scarf":
        grp.add(B.sh(V.rrect(-sw * 0.6, -T + 4, sw * 1.2, 24, 11), nc))
        grp.add(B.sh(V.rounded_poly([(sw * 0.1, -T + 22), (sw * 0.75, -T + 70), (sw * 0.45, -T + 78), (-sw * 0.1, -T + 28)], 4), nc))
    elif nk == "tie":
        grp.add(B.sh(V.poly([(-8, -T + 24), (8, -T + 24), (6, -T + 38), (15, -T * 0.42), (0, -T * 0.34), (-15, -T * 0.42), (-6, -T + 38)]), nc))
    elif nk == "bowtie":
        grp.add(B.sh(V.poly([(0, -T + 22), (-24, -T + 8), (-24, -T + 36)]), nc))
        grp.add(B.sh(V.poly([(0, -T + 22), (24, -T + 8), (24, -T + 36)]), nc))
        grp.add(B.sh(V.circle(0, -T + 22, 6), nc))
    if d["extra"] == "apron":
        a = d["extra_colour"]
        grp.add(B.sh(V.rounded_poly([(-sw * 0.62, -T + 34), (sw * 0.62, -T + 34), (hw * 1.05, -2), (-hw * 1.05, -2)], 8), a))
        grp.add(V.P(V.poly([(-sw * 0.5, -T + 34), (-6, -T + 8)], False), stroke=a, sw=6))
        grp.add(V.P(V.poly([(sw * 0.5, -T + 34), (6, -T + 8)], False), stroke=a, sw=6))
        grp.add(V.P(V.rrect(-hw * 0.5, -T * 0.3, hw, T * 0.14, 6), fill=shade(a, 0.84)))
    if logo is not None and d["logo"] == "chest":
        tile = min(52.0, sw * 1.45)
        tx, ty = sw * 0.34, -T * (0.56 if nk != "tie" else 0.42)
        front_nodes.append(V.P(V.rrect(tx - tile / 2, ty - tile / 2, tile, tile, 9), fill="#ffffff", stroke=d["outline"] if st.ow > 0 else shade(top, 0.78), sw=max(2.5, st.ow * 0.6)))
        pic = ImageOps.mirror(logo.convert("RGBA")) if flip else logo.convert("RGBA")
        front_nodes.append(V.Img(pic, tx - tile / 2 + 6, ty - tile / 2 + 6, tile - 12, tile - 12))
    return grp


# ------------------------------------------------------------------ اندام‌ها

def _limb(B: _B, pts: list, widths: list, cols: list, outline: str | None, st: St) -> list:
    """زنجیرهٔ مفصل‌ها: لایهٔ خطِ دور (پهن‌تر) ⇒ لایهٔ رنگ. ``cols[i]`` رنگِ قطعهٔ i است؛ cols[i] None ⇒ قطعه کشیده نمی‌شود."""
    out = []
    if outline and st.ow > 0:
        for i in range(len(pts) - 1):
            out.append(V.P(V.poly([pts[i], pts[i + 1]], False), stroke=outline, sw=widths[i] + st.ow * 2, cap="round"))
    for i in range(len(pts) - 1):
        if cols[i] is not None:
            out.append(V.P(V.poly([pts[i], pts[i + 1]], False), stroke=cols[i], sw=widths[i], cap="round"))
    return out


def _seg(a: tuple, b: tuple, t0: float, t1: float) -> tuple[tuple, tuple]:
    return (a[0] + (b[0] - a[0]) * t0, a[1] + (b[1] - a[1]) * t0), (a[0] + (b[0] - a[0]) * t1, a[1] + (b[1] - a[1]) * t1)


def _arm_nodes(B: _B, d: dict, st: St, bk: tuple, sh: tuple, el: tuple, wr: tuple, far: bool, show_thumb: bool, thumb_dir: tuple) -> list:
    outfit = d["outfit"]
    skin, top, top2 = d["skin"], d["top"], d["top2"]
    if far:
        skin, top, top2 = shade(skin, 0.9), shade(top, 0.9), shade(top2, 0.9)
    aw = st.arm_w * bk[1]
    outl = d["outline"] if st.outline_mode == "ink" else shade(skin, 0.55)
    nodes: list = []
    segs = [(sh, el, aw), (el, wr, aw * 0.9)]
    if st.ow > 0:                                                               # لایهٔ خطِ دورِ هر دو قطعه، بعد رنگِ پوست (مفصل بی‌درز)
        nodes += [V.P(V.poly([a, b], False), stroke=outl, sw=w + st.ow * 2, cap="round") for a, b, w in segs]
    nodes += [V.P(V.poly([a, b], False), stroke=skin, sw=w, cap="round") for a, b, w in segs]
    long_sleeve = outfit in ("hoodie", "suit", "track")
    if outfit != "tank":                                                       # آستین
        if long_sleeve:
            e2 = _seg(el, wr, 0.0, 0.8)[1]
            nodes.append(V.P(V.poly([sh, el], False), stroke=top, sw=aw * 1.14, cap="round"))
            nodes.append(V.P(V.poly([el, e2], False), stroke=top, sw=aw * 1.02, cap="round"))
            cuff = top2 if outfit in ("track", "hoodie") else shade(top, 0.8)
            nodes.append(V.P(V.poly([_seg(el, wr, 0.7, 0.7)[0], _seg(el, wr, 0.8, 0.8)[0]], False), stroke=cuff, sw=aw * 1.06, cap="butt"))
        else:
            e1 = _seg(sh, el, 0.0, 0.62 if outfit == "tshirt" else 0.5)[1]
            nodes.append(V.P(V.poly([sh, e1], False), stroke=top, sw=aw * 1.16, cap="round"))
            if outfit == "jersey":
                nodes.append(V.P(V.poly([_seg(sh, el, 0.36, 0.36)[0], e1], False), stroke=top2, sw=aw * 1.18, cap="butt"))
    hand_r = st.hand_r * bk[1]
    nodes.append(B.sh(V.circle(wr[0], wr[1], hand_r), skin))
    if show_thumb:
        tx, ty = thumb_dir
        nodes.append(B.sh(V.capsule(wr[0], wr[1], wr[0] + tx * hand_r * 2.3, wr[1] + ty * hand_r * 2.3, hand_r * 0.95), skin))
    return nodes


def _leg_nodes(B: _B, d: dict, st: St, bk: tuple, hp: tuple, kn: tuple, an: tuple, far: bool, shin_m: V.Matrix, ground: list) -> list:
    skin, bot, shoe = d["skin"], d["bottom"], d["shoes"]
    if far:
        skin, bot, shoe = shade(skin, 0.88), shade(bot, 0.86), shade(shoe, 0.86)
    kind = d["bottoms"]
    lw = st.leg_w * bk[1]
    pts = [hp, kn, an]
    widths = [lw, lw * 0.9]
    nodes: list = []
    outl_col = d["outline"] if st.outline_mode == "ink" else shade(bot if kind in ("pants", "joggers") else skin, 0.55)
    if st.ow > 0:
        nodes += [V.P(V.poly([pts[i], pts[i + 1]], False), stroke=outl_col, sw=widths[i] + st.ow * 2, cap="round") for i in range(2)]
    nodes += [V.P(V.poly([pts[i], pts[i + 1]], False), stroke=skin, sw=widths[i], cap="round") for i in range(2)]
    if kind in ("pants", "joggers"):
        nodes.append(V.P(V.poly([hp, kn], False), stroke=bot, sw=lw * 1.08, cap="round"))
        nodes.append(V.P(V.poly([kn, an], False), stroke=bot, sw=widths[1] * 1.06, cap="round"))
        if kind == "joggers":
            nodes.append(V.P(V.poly([_seg(kn, an, 0.8, 0.8)[0], _seg(kn, an, 0.94, 0.94)[0]], False), stroke=d["top2"] if d["top2"] != bot else shade(bot, 1.3), sw=widths[1] * 1.12, cap="butt"))
    elif kind == "shorts":
        nodes.append(V.P(V.poly([hp, _seg(hp, kn, 0, 0.78)[1]], False), stroke=bot, sw=lw * 1.16, cap="butt"))
        nodes.append(V.P(V.circle(hp[0], hp[1], lw * 0.58), fill=bot))
    elif kind == "skirt":
        nodes.append(B.sh(V.rounded_poly([(hp[0] - lw * 1.15, hp[1] - lw * 0.4), (hp[0] + lw * 1.15, hp[1] - lw * 0.4), (hp[0] + lw * 1.75, hp[1] + (kn[1] - hp[1]) * 0.62), (hp[0] - lw * 1.75, hp[1] + (kn[1] - hp[1]) * 0.62)], 10), bot))
    # --- کفش
    sg = V.G(m=shin_m)
    fl, fh = st.foot_len * bk[1], st.foot_h * bk[1]
    L = math.hypot(an[0] - kn[0], an[1] - kn[1])
    if d["shoes_type"] == "bare":
        sg.add(B.sh(V.rrect(-fh * 0.5, L - fh * 0.5, fl + fh * 0.5, fh * 0.8, fh * 0.4), skin))
    else:
        h = fh * (1.22 if d["shoes_type"] == "boots" else 1.0)
        sg.add(B.sh(V.rounded_poly([(-fh * 0.55, L - h * 0.55 - (6 if d["shoes_type"] == "boots" else 0)), (fh * 0.5, L - h * 0.55 - (6 if d["shoes_type"] == "boots" else 0)),
                                    (fl, L + h * 0.12), (fl, L + h * 0.5), (-fh * 0.55, L + h * 0.5)], fh * 0.34), shoe))
        sg.add(V.P(V.poly([(-fh * 0.55, L + h * 0.38), (fl - 1, L + h * 0.38)], False), stroke="#ffffff" if shoe.lower() != "#ffffff" else shade(shoe, 0.8), sw=fh * 0.22, cap="round", op=0.9 if d["shoes_type"] == "sneakers" else 0.0))
    nodes.append(sg)
    ground.append(sg)
    return nodes


# ------------------------------------------------------------------ ساخت

def _hex_gray(v: float) -> str:
    c = max(0, min(255, int(v)))
    return "#%02x%02x%02x" % (c, c, c)


def build(doc: dict, pose: str = "stand", expression: str = "neutral", *, flip: bool = False, prop: str | None = None, logo: Image.Image | None = None,
          style: str | None = None, with_layers: bool = True) -> Built:
    d = D.normalize(doc)
    sk = style or d["style"]
    if sk not in STYLE:
        sk = "flat"
    st = STYLE[sk]
    pose = stage.pose_of(pose)
    expression = expression if expression in D.EXPRESSIONS else "neutral"
    bk = BODY_K[d["body"]]
    hk = HEAD_K[d["head_style"]]
    rx, ry = st.head_rx * hk[0] * (1.0 if st.key == "chibi" else bk[1] ** 0.25), st.head_ry * hk[1]
    st_prop = stage.resolve_prop(D.to_mascot_spec(d), pose, prop)
    k = (st.thigh + st.shin) / 310.0
    hip_y = GROUND - (st.thigh + st.shin) - st.foot_h * 0.5
    rig = _rig(st, hip_y, st.sh_w * bk[0] * SHOULDER_K)
    pose_t = _pose_tuples(pose, k, sk)
    mats = rig.world_matrices(V.IDENT, pose_t)
    B = _B(st, d["outline"])
    root = V.G(name="figure")
    items: list[tuple[float, object]] = []
    ground: list = []

    def at(name: str, x: float = 0.0, y: float = 0.0) -> tuple[float, float]:
        return g.apply(mats[name], x, y)

    # --- پشت: لایه‌های دستیِ «زیرِ شخصیت»
    below: list = []
    above: list = []
    frames = {n: tuple(m) for n, m in mats.items()}
    # --- پاها
    for side in ("l", "r"):
        far = side == "l"
        hp, kn, an = at(f"leg_{side}"), at(f"shin_{side}"), at(f"shin_{side}", 0, st.shin)
        legs = V.G(name=f"leg_{side}")
        for n in _leg_nodes(B, d, st, bk, hp, kn, an, far, tuple(mats[f"shin_{side}"]), ground):
            legs.add(n)
        items.append((5 if far else 6, legs))
    # --- بدن
    back_nodes: list = []
    front_nodes: list = []
    torso = _torso(B, d, st, bk, logo if d["logo"] == "chest" else None, flip, front_nodes=front_nodes, back_nodes=back_nodes)
    torso.m = tuple(mats["body"])
    items.append((10, torso))
    if front_nodes:
        # لوگوی روی سینه: وقتی دستِ نزدیک آویزان است و سینه را می‌پوشاند، نشان روی دست هم دیده می‌شود (z بالاتر)؛ در ژست‌های دیگر روی خودِ تن می‌ماند
        hanging = abs(pose_t.get("arm_r", (0, 0, 0, 1, 1))[2] + pose_t.get("body", (0, 0, 0, 1, 1))[2]) < 40
        badge = V.G(name="chest_logo", m=tuple(mats["body"]))
        for nd in front_nodes:
            badge.add(nd)
        items.append((30.5 if hanging else 10.5, badge))
    ground.append(torso)
    # --- بازوها
    tdir = (0.45, -0.9)
    wr_pts = {}
    for side in ("l", "r"):
        far = side == "l"
        sh, el, wr = at(f"arm_{side}"), at(f"forearm_{side}"), at(f"forearm_{side}", 0, st.fore)
        wr_pts[side] = wr
        thumb = (pose in poses.SHOW_THUMB) and side == "r"
        arm = V.G(name=f"arm_{side}")
        for n in _arm_nodes(B, d, st, bk, sh, el, wr, far, thumb, tdir):
            arm.add(n)
        raised = abs(pose_t.get(f"arm_{side}", (0, 0, 0, 1, 1))[2] + pose_t.get("body", (0, 0, 0, 1, 1))[2]) > 100
        items.append((12 if far else (18 if (st.key == "chibi" or pose in ARMS_UP or raised) else 30), arm))
    # --- سر
    back_h: list = []
    front_h: list = []
    _head_nodes(B, d, st, expression, rx, ry, back_h, front_h)
    hg = V.G(name="head", m=tuple(mats["head"]))
    cyh = -(ry - HEAD_OVERLAP)
    neck_w = min(rx * 0.55, 40.0)
    hg.add(V.P(V.rrect(-neck_w / 2, -14, neck_w, 24, 6), fill=shade(d["skin"], 0.88)))
    inner = V.G(m=V.mtrans(0, cyh))
    for n in back_h + front_h:
        inner.add(n)
    hg.add(inner)
    items.append((20, hg))
    # --- وسیله
    fl = -1.0 if flip else 1.0
    if st_prop and st_prop != "none" and st_prop != "barbell":
        total = sum(pose_t.get(p, (0, 0, 0, 1, 1))[2] for p in ("body", "arm_r", "forearm_r"))
        fwd = stage.PROP_FORWARD.get(st_prop, 0.0)
        wrx, wry = wr_pts["r"]
        rad = math.radians(total)
        pg = V.G(name="prop", m=V.mmul(V.mtrans(wrx + fwd * math.cos(rad) * 0.8, wry - fwd * math.sin(rad) * 0.8), V.mrot(-total + (0.0 if st_prop != "megaphone" else 0.0))))
        for n in props.draw(st_prop, d["prop_colour"], d["outline"], st.prop_k, ow=st.ow * 0.7):
            pg.add(n)
        items.append((31, pg))
    elif st_prop == "barbell":
        lw_, rw_ = wr_pts["l"], wr_pts["r"]
        items.append((31, _barbell(B, d, st, lw_, rw_)))
    # --- لایه‌های دستی
    anchors = {"world": V.IDENT, "head": V.mmul(tuple(mats["head"]), V.mtrans(0, cyh)), "body": tuple(mats["body"]),
               "hand": V.mmul(V.mtrans(*wr_pts["r"]), V.mrot(-sum(pose_t.get(p, (0, 0, 0, 1, 1))[2] for p in ("body", "arm_r", "forearm_r"))))}
    if with_layers and d["layers"]:
        for lay in d["layers"]:
            if lay.get("hidden"):
                continue
            node = layer_node(lay)
            if node is None:
                continue
            holder = V.G(name="layer_" + lay["id"], m=anchors[lay["anchor"]])
            holder.add(node)
            (above if lay["above"] else below).append(holder)
    for n in below:
        root.add(n)
    for _z, n in sorted(items, key=lambda t: t[0]):
        root.add(n)
    for n in above:
        root.add(n)
    # --- زمین‌گذاری: پایین‌ترین نقطهٔ پا/تن روی زمین (جز پرش)
    gb = V.bbox_of(V.G(kids=ground))
    gdy = 0.0
    if gb is not None:
        lift = AIRBORNE.get(pose, 0.0) * k
        gdy = (GROUND - lift) - gb[3]
        root.m = V.mtrans(0, gdy)
    hxy = g.apply(mats["head"], 0, cyh)
    head = (hxy[0], hxy[1] + gdy, max(rx, ry))
    hands = ((wr_pts["l"][0], wr_pts["l"][1] + gdy), (wr_pts["r"][0], wr_pts["r"][1] + gdy))
    if sk == "sticker" and st.border > 0:
        root = V.G(kids=[_halo(root, st.border, d["outline"]), root], name="sticker")
    final = {kk: tuple(round(v, 4) for v in V.mmul(V.mtrans(0, gdy), m)) for kk, m in anchors.items()}
    return Built(root=root, head=head, hands=hands, prop=st_prop, pose=pose, expression=expression, frames=frames, anchors=final, ground_dy=gdy)


def _barbell(B: _B, d: dict, st: St, left: tuple, right: tuple) -> V.G:
    (lx, ly), (rx_, ry_) = left, right
    dx, dy = rx_ - lx, ry_ - ly
    dist = math.hypot(dx, dy) or 1.0
    ux, uy = dx / dist, dy / dist
    nx, ny = -uy, ux
    ext = max(78.0, dist * 0.7)
    a, b = (lx - ux * ext, ly - uy * ext), (rx_ + ux * ext, ry_ + uy * ext)
    grp = V.G(name="barbell")
    grp.add(V.P(V.poly([a, b], False), stroke=d["outline"] if st.ow > 0 else "#4b5563", sw=15 + st.ow * 1.5))
    grp.add(V.P(V.poly([a, b], False), stroke="#6b7280", sw=9))
    for end, sgn in ((a, -1), (b, 1)):
        for off, w, h in ((0, 20, 104), (sgn * -17 * -1 if False else -sgn * 17, 11, 70)):
            cx, cy = end[0] + ux * off, end[1] + uy * off
            pts = [(cx + ux * w / 2 + nx * h / 2, cy + uy * w / 2 + ny * h / 2), (cx - ux * w / 2 + nx * h / 2, cy - uy * w / 2 + ny * h / 2),
                   (cx - ux * w / 2 - nx * h / 2, cy - uy * w / 2 - ny * h / 2), (cx + ux * w / 2 - nx * h / 2, cy + uy * w / 2 - ny * h / 2)]
            grp.add(B.sh(V.rounded_poly(pts, 4), d["prop_colour"], ow=max(st.ow * 0.8, 2.5), stroke=d["outline"]))
    return grp


def _halo(root: V.G, border: float, colour: str = "#ffffff") -> V.G:
    """حاشیهٔ سفیدِ استیکر: همهٔ شکل‌ها با خطِ سفیدِ پهن (و پُرِ سفید) زیرِ شخصیت."""
    def clone(n):
        if isinstance(n, V.P):
            sw = (n.sw if n.stroke else 0.0) + border * 2
            return V.P(n.cmds, fill="#ffffff" if n.fill else None, stroke="#ffffff", sw=sw if (n.fill or n.stroke) else 0.0, cap="round", join="round")
        if isinstance(n, V.G):
            return V.G(kids=[c for c in (clone(k) for k in n.kids) if c is not None], m=n.m, name="")
        if isinstance(n, V.Img):
            return V.P(V.rrect(n.x, n.y, n.w, n.h, 4), fill="#ffffff", stroke="#ffffff", sw=border * 2)
        return None

    h = clone(root)
    h.m = V.IDENT
    return V.G(kids=[h], name="halo", m=root.m)


# ------------------------------------------------------------------ لایه‌های دستی

def layer_node(lay: dict) -> V.G | None:
    """یک لایهٔ دستیِ ادیتور ⇒ گره (در قابِ جزءای که به آن چسبیده)."""
    box = lay["box"]
    fill, stroke, sw = lay.get("fill"), lay.get("stroke"), float(lay.get("sw") or 0)
    shape = lay["shape"]
    cx, cy, w, h = box["cx"], box["cy"], box["w"], box["h"]
    m = V.mmul(V.mtrans(cx, cy), V.mrot(box.get("rot", 0)))
    if lay.get("flip_x"):
        m = V.mmul(m, V.mscale(-1, 1))
    if shape == "rect":
        cmds = V.rrect(-w / 2, -h / 2, w, h, float(lay.get("radius") or 0))
    elif shape == "ellipse":
        cmds = V.ellipse(0, 0, w / 2, h / 2)
    elif shape == "line":
        cmds = V.poly([(-w / 2, 0), (w / 2, 0)], False)
    else:
        path = lay.get("path") or {}
        cmds = V.from_unit_path(path, {"cx": 0, "cy": 0, "w": w, "h": h, "rot": 0})
        if lay.get("flip_x"):
            pass
    if not cmds:
        return None
    node = V.P(cmds, fill=fill if shape != "line" else None, stroke=stroke or (fill if shape == "line" else None), sw=sw or (6.0 if shape == "line" else 0.0), op=float(lay.get("opacity", 1.0)))
    return V.G(kids=[node], m=m, name="")


# ------------------------------------------------------------------ خروجی

VIEW_BOX = (0.0, 0.0, float(DESIGN[0]), float(DESIGN[1]))


def to_svg(built: Built, *, view: tuple | None = None, size: tuple[int, int] | None = None, background: str | None = None, title: str = "", flip: bool = False) -> str:
    root = built.root
    if flip:
        root = V.G(kids=[root], m=(-1.0, 0.0, 0.0, 1.0, float(DESIGN[0]), 0.0))
    return V.to_svg(root, view or VIEW_BOX, size=size, background=background, title=title)


def figure_bbox(built: Built, flip: bool = False) -> tuple[float, float, float, float] | None:
    m = (-1.0, 0.0, 0.0, 1.0, float(DESIGN[0]), 0.0) if flip else V.IDENT
    return V.bbox_of(built.root, m)


def render_actor(actor: dict, w: int, h: int, *, logo: Image.Image | None = None, shadow: bool | None = None, inside: float | None = None) -> stage.ActorShot:
    """همان قراردادِ ``stage.render_actor`` (ماسکوت) برای سبک‌های برداری؛ ⇒ ActorShot."""
    d = D.normalize(actor["spec"])
    expression = actor.get("expression") if actor.get("expression") in D.EXPRESSIONS else "neutral"
    pose = stage.pose_of(actor.get("pose"))
    flip = bool(actor.get("flip"))
    built = build(d, pose, expression, flip=flip, prop=actor.get("prop"), logo=logo)
    fl = -1.0 if flip else 1.0
    px = float(actor.get("height", 0.55)) * h / DESIGN[1]
    sx, sy = float(actor.get("x", 0.5)) * w, float(actor.get("y", 0.93)) * h
    fit = STYLE[d["style"] if d["style"] in STYLE else "flat"].fit
    view = V.mmul(V.mtrans(sx, sy), V.mmul(V.mscale(px * fl * fit, px * fit), V.mtrans(-CX, -GROUND)))
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    use_shadow = actor.get("shadow", True) if shadow is None else shadow
    if use_shadow:
        rw, rh = DESIGN[0] * px * 0.22, DESIGN[1] * px * 0.025
        ImageDraw.Draw(layer).ellipse((sx - rw, sy - rh, sx + rw, sy + rh), fill=(0, 0, 0, 70))
    bb = V.bbox_of(built.root, view)
    dx = dy = 0
    if inside is not None and bb is not None:
        m_ = inside * min(w, h)
        x0, y0, x1, y1 = bb
        dx = m_ - x0 if x0 < m_ else ((w - m_) - x1 if x1 > w - m_ else 0.0)
        dy = (h - m_) - y1 if y1 > h - m_ else 0.0
        if y0 + dy < m_:
            dy = m_ - y0
        dx, dy = int(round(dx)), int(round(dy))
        if dx or dy:
            view = V.mmul(V.mtrans(dx, dy), view)
            bb = V.bbox_of(built.root, view)
    ss = 3 if w * h <= 1_700_000 else 2
    region = None
    if bb is not None:
        pad = 6
        region = (int(bb[0]) - pad, int(bb[1]) - pad, int(math.ceil(bb[2])) + pad, int(math.ceil(bb[3])) + pad)
    fig = V.rasterize(built.root, view, (w, h), ss=ss, region=region)
    layer.alpha_composite(fig)
    hx, hy = V.mapply(view, built.head[0], built.head[1])
    solid = layer.getchannel("A").point(lambda v: 255 if v >= 200 else 0).getbbox()
    return stage.ActorShot(layer=layer, head=(hx, hy, built.head[2] * px * fit), bbox=solid, prop=built.prop, pose=pose, expression=expression)


STYLE_KEYS = tuple(STYLE)


#: «دست تکان‌دادن» برای آدمک‌چوبیِ این بخش (``spec["pose_variant"] == "brand"``): بازو بیرونِ سر و ساعد بالا، نه از رویِ صورت. ماسکوتِ قدیمی همان ژستِ مشترک را دارد.
STICK_POSES: dict[str, dict[str, dict[str, float]]] = {"wave": {"arm_r": {"rot": -112}, "forearm_r": {"rot": -68}, "head": {"rot": 4}}}


def register() -> None:
    """سبک‌های برداری را به ``stage.render_actor`` ِ ماسکوت می‌شناساند (``spec['style']``)؛ آدمک‌چوبی همان مسیرِ قدیمی را می‌رود (با جدولِ ژستِ «brand»)."""
    for key in STYLE_KEYS:
        stage.STYLE_RENDERERS[key] = render_actor
    stage.POSE_VARIANTS["brand"] = STICK_POSES
