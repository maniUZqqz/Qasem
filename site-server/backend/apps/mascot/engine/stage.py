"""کشیدنِ یک شخصیت در یک ژست روی بومِ شفاف (یک قابِ ثابت).

SOURCE: ported from InstAI (maniUZqqz/Instai) instai/render/puppet/renderer.py (``_Actor.draw``, ``_blit``) + instai/render/stick/compose.py
(``_actor_spec``, ``head_xy``) @ 82733b0, adapted for NMarketing brand mascots: one still frame (time 0, camera 1x), the head position is
measured from the rig itself (so bubbles are placed right for every pose, also the new ones), a held prop stays upright / forward whatever the
arm does, the barbell is drawn between the two hands, and the chest logo is mirrored in advance when the figure faces left.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from PIL import Image, ImageDraw

from . import parts, poses
from . import rig as g
from . import spec as S


@dataclass
class ActorShot:
    layer: Image.Image                 # RGBA هم‌اندازهٔ بوم؛ فقط شخصیت (و سایه اگر خواسته شده)
    head: tuple[float, float, float]   # (x، y، شعاع) سرِ شخصیت روی بوم
    bbox: tuple[int, int, int, int] | None   # کادرِ پیکسل‌های پررنگِ شخصیت
    prop: str                          # وسیلهٔ واقعاً کشیده‌شده
    pose: str
    expression: str


def _blit(canvas: Image.Image, layer: Image.Image, x: int, y: int) -> None:
    """alpha_composite با بریدن در همهٔ لبه‌های بوم."""
    w, h = canvas.size
    sx0, sy0 = max(0, -x), max(0, -y)
    sx1, sy1 = min(layer.width, w - x), min(layer.height, h - y)
    if sx1 <= sx0 or sy1 <= sy0:
        return
    sub = layer.crop((sx0, sy0, sx1, sy1)) if (sx0 or sy0 or sx1 < layer.width or sy1 < layer.height) else layer
    canvas.alpha_composite(sub, (x + sx0, y + sy0))


def pose_of(name: str | None) -> str:
    return name if name in poses.POSES else "stand"


def pose_tuples(pose: str) -> dict[str, tuple[float, float, float, float, float]]:
    out = {}
    for part, ch in poses.POSES[pose_of(pose)].items():
        out[part] = (float(ch.get("dx", 0.0)), float(ch.get("dy", 0.0)), float(ch.get("rot", 0.0)), float(ch.get("sx", 1.0)), float(ch.get("sy", 1.0)))
    return out


def resolve_prop(spec: dict, pose: str, requested: str | None) -> str:
    """وسیلهٔ این قاب: ``requested`` (none/key)، یا «auto» = وسیلهٔ ژست (دمبل برای جمع، هالتر برای بالابردن) و در غیر این صورت وسیلهٔ خودِ spec."""
    if requested in S.PROPS:
        return requested
    pose = pose_of(pose)
    if pose in poses.PROP_FOR_POSE:
        return poses.PROP_FOR_POSE[pose]
    return S.normalize(spec)["prop"] if pose in poses.PROP_POSES else "none"


#: وسیله‌هایی که کمی «جلوی» شخصیت (در جهتِ نگاهش) می‌ایستند تا لوگوی روی سینه را نپوشانند (پیکسلِ طراحی)
PROP_FORWARD = {"clipboard": 30.0, "tablet": 30.0, "bag": 28.0, "box": 28.0, "sign": 26.0, "map": 26.0}


def _prop_rotation(pose: dict, prop: str) -> float:
    """وسیله در دست صاف می‌ماند: چرخشِ بدن، بازو و ساعد خنثی می‌شود؛ بلندگو ۹۰ درجه می‌چرخد تا رو به جلو باشد."""
    total = sum(pose.get(p, (0, 0, 0, 1, 1))[2] for p in ("body", "arm_r", "forearm_r"))
    extra = 90.0 if parts.PROP_MODE.get(prop) == "forward" else 0.0
    return -total + extra


def _barbell(layer: Image.Image, left: tuple[float, float], right: tuple[float, float], px: float, plate_hex: str, outline_hex: str) -> None:
    """هالتر: میله از میانِ دو دست و دو جفت صفحه در دو سر؛ با نمونه‌برداریِ ۳ برابر در یک ناحیهٔ کوچک کشیده می‌شود."""
    (lx, ly), (rx, ry) = left, right
    dx, dy = rx - lx, ry - ly
    dist = math.hypot(dx, dy) or 1.0
    ux, uy = (dx / dist, dy / dist) if dist > 1e-6 else (1.0, 0.0)
    nx, ny = -uy, ux
    ext = max(78.0 * px, dist * 0.7)
    ends = ((lx - ux * ext, ly - uy * ext), (rx + ux * ext, ry + uy * ext))
    big_h, small_h = 104 * px, 70 * px
    pad = int(big_h / 2 + 10 * px)
    xs = [ends[0][0], ends[1][0], lx, rx]
    ys = [ends[0][1], ends[1][1], ly, ry]
    x0, y0 = int(min(xs) - pad), int(min(ys) - pad)
    x1, y1 = int(max(xs) + pad), int(max(ys) + pad)
    ss = 3
    reg = Image.new("RGBA", ((x1 - x0) * ss, (y1 - y0) * ss), (0, 0, 0, 0))
    d = ImageDraw.Draw(reg)

    def P(x, y):
        return ((x - x0) * ss, (y - y0) * ss)

    def poly(cx, cy, wp, hp, fill):
        pts = [(cx + ux * wp / 2 + nx * hp / 2, cy + uy * wp / 2 + ny * hp / 2), (cx - ux * wp / 2 + nx * hp / 2, cy - uy * wp / 2 + ny * hp / 2),
               (cx - ux * wp / 2 - nx * hp / 2, cy - uy * wp / 2 - ny * hp / 2), (cx + ux * wp / 2 - nx * hp / 2, cy + uy * wp / 2 - ny * hp / 2)]
        d.polygon([P(*p) for p in pts], fill=fill, outline=S.hex_rgba(outline_hex))
        d.line([P(*p) for p in pts + [pts[0]]], fill=S.hex_rgba(outline_hex), width=max(1, int(3.5 * px * ss)))

    steel = (75, 85, 99, 255)
    d.line([P(*ends[0]), P(*ends[1])], fill=S.hex_rgba(outline_hex), width=max(2, int(15 * px * ss)))
    d.line([P(*ends[0]), P(*ends[1])], fill=steel, width=max(1, int(9 * px * ss)))
    pc = S.hex_rgba(plate_hex)
    for sgn, (ex, ey) in zip((-1, 1), ends):
        poly(ex, ey, 20 * px, big_h, pc)                                                            # صفحهٔ بزرگ: درست روی سرِ میله
        poly(ex - sgn * ux * 17 * px, ey - sgn * uy * 17 * px, 11 * px, small_h, pc)                # صفحهٔ کوچک: کمی به سمتِ دست
    reg = reg.resize((x1 - x0, y1 - y0), Image.LANCZOS)
    _blit(layer, reg, x0, y0)


def render_actor(actor: dict, w: int, h: int, *, logo: Image.Image | None = None, shadow: bool | None = None, inside: float | None = None) -> ActorShot:
    """یک شخصیت را روی یک بومِ شفافِ w×h می‌کشد. actor: {spec، pose، expression، x، y، height، flip، talk، prop، shadow}.
    ``inside`` (کسری از کوچک‌ترین بُعد): اگر شخصیت (مثلاً ژستِ «روی زمین») از کادر بیرون بزند، به‌اندازهٔ لازم جابه‌جا می‌شود تا درونِ کادر با این حاشیه بماند."""
    s = S.normalize(actor["spec"])
    expression = actor.get("expression") if actor.get("expression") in parts._EXPR else "neutral"
    pose = pose_of(actor.get("pose"))
    prop = resolve_prop(s, pose, actor.get("prop"))
    flip = bool(actor.get("flip"))
    rig = parts.rig_for(s, expression, logo=logo, mirror_logo=flip, prop=prop)
    fl = -1.0 if flip else 1.0
    px = float(actor.get("height", 0.55)) * h / rig.size[1]               # پیکسلِ بوم در هر پیکسلِ طراحی
    sx, sy = float(actor.get("x", 0.5)) * w, float(actor.get("y", 0.93)) * h
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    use_shadow = actor.get("shadow", True) if shadow is None else shadow
    if use_shadow:
        rw, rh = rig.size[0] * px * 0.22, rig.size[1] * px * 0.025
        ImageDraw.Draw(layer).ellipse((sx - rw, sy - rh, sx + rw, sy + rh), fill=(0, 0, 0, 70))
    base = g.mul(g.translate(sx, sy), g.mul(g.scale(px * fl, px), g.translate(-rig.anchor[0], -rig.anchor[1])))
    pose_t = pose_tuples(pose)
    if "prop" in rig.parts:
        total = math.radians(sum(pose_t.get(p, (0, 0, 0, 1, 1))[2] for p in ("body", "arm_r", "forearm_r")))
        off = PROP_FORWARD.get(prop, 0.0)                    # جابه‌جاییِ «جلو» در قابِ صفحه ⇒ در قابِ چرخیدهٔ ساعد
        pose_t["prop"] = (off * math.cos(total), -off * math.sin(total), _prop_rotation(pose_t, prop), 1.0, 1.0)
    mats = rig.world_matrices(base, pose_t)
    mouth = parts.expression_parts(expression)[3] if not actor.get("talk") else "C"
    show = ("thumb",) if pose in poses.SHOW_THUMB else ()
    kk = min(px, float(parts.Q))
    scaled: dict[str, Image.Image] = {}
    for part in rig.visible_parts(mouth, "open", None, show):
        im = part.image
        if abs(kk - parts.Q) > 1e-6:
            k = kk / parts.Q
            key = id(im)
            if key not in scaled:
                scaled[key] = im.resize((max(1, int(round(im.width * k))), max(1, int(round(im.height * k)))), Image.LANCZOS)
            im = scaled[key]
        m = g.mul(mats[part.name], g.scale(1.0 / kk))
        x0, y0, x1, y1 = g.bbox(m, im.width, im.height)
        bx, by = math.floor(x0), math.floor(y0)
        bw, bh = math.ceil(x1) - bx + 1, math.ceil(y1) - by + 1
        if bw <= 0 or bh <= 0 or bx > w or by > h or bx + bw < 0 or by + bh < 0 or bw > 4 * w or bh > 4 * h:
            continue
        m2 = g.mul(g.translate(-bx, -by), m)
        piece = im.transform((bw, bh), Image.AFFINE, g.pil_inverse(m2), resample=Image.BICUBIC)
        _blit(layer, piece, bx, by)
    if prop == "barbell":
        hand = (40.0, 14.0 + parts.FORE + 6.0)
        left, right = g.apply(mats["forearm_l"], *hand), g.apply(mats["forearm_r"], *hand)
        _barbell(layer, left, right, px, s["prop_colour"], s["outline"])
    hx, hy = g.apply(mats["head"], 115.0, 120.0)
    radius = parts._head_dims(s["head_style"])[1] * px
    solid = layer.getchannel("A").point(lambda v: 255 if v >= 200 else 0).getbbox()
    if inside is not None and solid is not None:
        m = inside * min(w, h)
        x0, y0, x1, y1 = solid
        dx = m - x0 if x0 < m else ((w - m) - x1 if x1 > w - m else 0.0)
        dy = (h - m) - y1 if y1 > h - m else 0.0
        if y0 + dy < m:
            dy = m - y0
        dx, dy = int(round(dx)), int(round(dy))
        if dx or dy:
            moved = Image.new("RGBA", (w, h), (0, 0, 0, 0))
            moved.paste(layer, (dx, dy))
            layer, hx, hy = moved, hx + dx, hy + dy
            solid = (solid[0] + dx, solid[1] + dy, solid[2] + dx, solid[3] + dy)
    return ActorShot(layer=layer, head=(hx, hy, radius), bbox=solid, prop=prop, pose=pose, expression=expression)
