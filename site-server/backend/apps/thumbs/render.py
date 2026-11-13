"""موتورِ ساختِ تامنیل: مشخصات (spec) ⇒ تصویرِ لایه‌ایِ نهایی با Pillow (بدونِ مرورگر، بدونِ Django).

جریان:  ``clean_spec`` ورودیِ کاربر را وارسی می‌کند ⇒ ``render(spec, inputs)`` یک ``Ctx`` می‌سازد (اندازه، حاشیهٔ امن، پالت، متن‌ها) و
تابعِ سبک (``styles.STYLES[key].fn``) لایه‌ها را به ترتیب می‌گذارد: پس‌زمینه ⇒ سوژهٔ بریده ⇒ عنوان ⇒ تزئین ⇒ لوگو ⇒ دانه/وینیت.
هر لایه در گزارش (``RenderResult.layers``) نامی و کادری دارد؛ با ``keep_layers`` خودِ لایه‌ها هم برای «فایل لایه‌دار» نگه داشته می‌شود.

تصویرها (سوژه، پس‌زمینه، لوگو) را فراخواننده آماده می‌دهد (``Inputs``)؛ این ماژول هیچ‌چیز را از دیتابیس نمی‌خواند.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

from PIL import Image, ImageDraw

from . import formats as F
from . import palette as pal_mod
from . import primitives as P
from . import typo
from .formats import Format

MAX_TITLE, MAX_SUB, MAX_SHORT = 110, 140, 40
CONTENT_LIMITS = {"title": MAX_TITLE, "subtitle": MAX_SUB, "kicker": 34, "number": 6, "badge": 26, "tagline": 90, "credits": 260,
                  "cta": 30, "label_a": 24, "label_b": 24}
LOGO_POSITIONS = ("auto", "tl", "tr", "bl", "br", "bc", "tc")
BG_KINDS = ("auto", "gradient", "texture", "photo", "ai")
TEXTURES = ("", "halftone", "rays", "grid", "stripes", "grain")
SUBJECT_MODES = ("auto", "cutout", "photo")
SIDES = ("auto", "left", "right", "center")


class SpecError(ValueError):
    """ورودیِ نامعتبر؛ متنش فارسی و برای کاربر است."""


@dataclass
class Inputs:
    subject: Image.Image | None = None
    subject_is_cutout: bool = False
    subject2: Image.Image | None = None
    subject2_is_cutout: bool = False
    background: Image.Image | None = None
    logo: Image.Image | None = None
    brand_colors: list[str] = field(default_factory=list)
    store_name: str = ""
    heading_font: str = ""            # فونتِ تیترِ «سبکِ برند» ِ فروشگاه (اگر ثبت شده)
    extra: list[Image.Image] = field(default_factory=list)


@dataclass
class RenderResult:
    image: Image.Image
    layers: list[dict]
    warnings: list[str]
    size: tuple[int, int]
    texts: list[dict]
    palette: dict
    kept: list[dict] = field(default_factory=list)


# ───────────────────────────── مشخصات

def default_spec() -> dict:
    return {
        "format": F.DEFAULT_FORMAT, "style": "face_text",
        "content": {k: "" for k in CONTENT_LIMITS},
        "colors": {"mood": "", "primary": "", "secondary": "", "accent": "", "use_brand": True, "variation": 0},
        "font": typo.AUTO_FONT,
        "background": {"kind": "auto", "asset": None, "texture": "", "darken": 0.0, "blur": 0, "job": ""},
        "subject": {"asset": None, "mode": "auto", "side": "auto", "scale": 1.0, "outline": True},
        "subject2": {"asset": None},
        "extra_assets": [],
        "logo": {"show": True, "position": "auto"},
        "accents": {"arrow": True},
        "seed": 1,
        "guides": False,
    }


def _int_or_none(v):
    try:
        return int(v) if v not in (None, "", False) else None
    except (TypeError, ValueError):
        return None


def _num(v, lo, hi, default):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, x))


def clean_spec(raw, styles_registry) -> dict:
    """ورودیِ کاربر ⇒ spec ِ تمیز (کلیدِ ناشناخته دور ریخته می‌شود؛ قالب/سبکِ ناشناخته ⇒ SpecError فارسی)."""
    d = raw if isinstance(raw, dict) else {}
    out = default_spec()
    fk = str(d.get("format") or out["format"])
    if fk not in F.FORMATS:
        raise SpecError("قالبِ ناشناخته است؛ از فهرستِ قالب‌ها یکی را انتخاب کنید.")
    out["format"] = fk
    sk = str(d.get("style") or out["style"])
    if sk not in styles_registry:
        raise SpecError("سبکِ ناشناخته است؛ از فهرستِ سبک‌ها یکی را انتخاب کنید.")
    out["style"] = sk
    c = d.get("content") if isinstance(d.get("content"), dict) else {}
    for k, lim in CONTENT_LIMITS.items():
        v = c.get(k)
        out["content"][k] = typo.clean(v if isinstance(v, (str, int, float)) and not isinstance(v, bool) else "")[:lim]
    col = d.get("colors") if isinstance(d.get("colors"), dict) else {}
    oc = out["colors"]
    oc["mood"] = col.get("mood") if col.get("mood") in pal_mod.MOODS else ""
    for k in ("primary", "secondary", "accent"):
        v = str(col.get(k) or "").strip().lower()
        oc[k] = v if pal_mod.colorx.is_hex(v) else ""
    oc["use_brand"] = bool(col.get("use_brand", True))
    oc["variation"] = int(_num(col.get("variation"), 0, 7, 0))
    f = str(d.get("font") or typo.AUTO_FONT)
    out["font"] = f if f in typo.FONT_CHOICES else typo.AUTO_FONT
    b = d.get("background") if isinstance(d.get("background"), dict) else {}
    ob = out["background"]
    ob["kind"] = b.get("kind") if b.get("kind") in BG_KINDS else "auto"
    ob["asset"] = _int_or_none(b.get("asset"))
    ob["texture"] = b.get("texture") if b.get("texture") in TEXTURES else ""
    ob["darken"] = round(_num(b.get("darken"), 0.0, 0.85, 0.0), 2)
    ob["blur"] = int(_num(b.get("blur"), 0, 40, 0))
    ob["job"] = str(b.get("job") or "")[:40]
    s = d.get("subject") if isinstance(d.get("subject"), dict) else {}
    os_ = out["subject"]
    os_["asset"] = _int_or_none(s.get("asset"))
    os_["mode"] = s.get("mode") if s.get("mode") in SUBJECT_MODES else "auto"
    os_["side"] = s.get("side") if s.get("side") in SIDES else "auto"
    os_["scale"] = round(_num(s.get("scale"), 0.5, 1.4, 1.0), 2)
    os_["outline"] = bool(s.get("outline", True))
    s2 = d.get("subject2") if isinstance(d.get("subject2"), dict) else {}
    out["subject2"]["asset"] = _int_or_none(s2.get("asset"))
    ex = d.get("extra_assets") if isinstance(d.get("extra_assets"), list) else []
    out["extra_assets"] = [i for i in (_int_or_none(x) for x in ex[:4]) if i]
    lg = d.get("logo") if isinstance(d.get("logo"), dict) else {}
    out["logo"]["show"] = bool(lg.get("show", True))
    out["logo"]["position"] = lg.get("position") if lg.get("position") in LOGO_POSITIONS else "auto"
    ac = d.get("accents") if isinstance(d.get("accents"), dict) else {}
    out["accents"]["arrow"] = bool(ac.get("arrow", True))
    out["seed"] = int(_num(d.get("seed"), 0, 99999, 1))
    out["guides"] = bool(d.get("guides", False))
    return out


# ───────────────────────────── بافتِ ترسیم

class Placed:
    """جایی که یک متن/شکل نشست: کادرِ جوهر و جعبهٔ اسمی."""

    def __init__(self, ink, nominal, block=None):
        self.ink, self.nominal, self.block = ink, nominal, block

    @property
    def bottom(self) -> float:
        return self.nominal[3]


class Ctx:
    def __init__(self, fmt: Format, spec: dict, inp: Inputs, size: tuple[int, int], keep: bool = False):
        self.fmt, self.spec, self.inp = fmt, spec, inp
        self.W, self.H = size
        self.k = self.W / 1080.0                       # ضریبِ مقیاس نسبت به پهنای ۱۰۸۰
        self.orient = fmt.orient
        self.comp = P.Composer(size, keep)
        self.warnings: list[str] = []
        self.texts: list[dict] = []
        self.rnd = random.Random(spec.get("seed", 1))
        self.safe = F.safe_rect(fmt, size)
        self.avoid = F.avoid_rects(fmt, size)
        self.content = {k: typo.to_fa_digits(typo.clean(v)) for k, v in spec["content"].items()}
        self.font_key = "lalezar"
        self.pal: pal_mod.Palette = pal_mod.build("vivid")
        self.subject_side = "left"

    # --- اندازه‌ها
    def u(self, v: float) -> float:
        """v پیکسل در بومِ ۱۰۸۰ پهن ⇒ پیکسلِ همین بوم."""
        return v * self.k

    @property
    def size(self):
        return (self.W, self.H)

    def has(self, key: str) -> bool:
        return bool(typo.plain(self.content.get(key, "")))

    def rect(self, x0: float, y0: float, x1: float, y1: float) -> tuple[float, float, float, float]:
        return (x0 * self.W, y0 * self.H, x1 * self.W, y1 * self.H)

    # --- ناحیه‌ها
    def avoid_rect(self, r: tuple[float, float, float, float], min_frac: float = 0.55):
        """r را از ناحیه‌های پرهیز دور می‌کند (بزرگ‌ترین تکه‌ای که می‌ماند)."""
        cur = tuple(r)
        for a in self.avoid:
            if not (cur[0] < a[2] and cur[2] > a[0] and cur[1] < a[3] and cur[3] > a[1]):
                continue
            cands = [(cur[0], cur[1], min(cur[2], a[0]), cur[3]), (max(cur[0], a[2]), cur[1], cur[2], cur[3]),
                     (cur[0], cur[1], cur[2], min(cur[3], a[1])), (cur[0], max(cur[1], a[3]), cur[2], cur[3])]
            cands = [c for c in cands if c[2] - c[0] > 4 and c[3] - c[1] > 4]
            if not cands:
                continue
            best = max(cands, key=lambda c: (c[2] - c[0]) * (c[3] - c[1]))
            if (best[2] - best[0]) * (best[3] - best[1]) >= min_frac * (cur[2] - cur[0]) * (cur[3] - cur[1]):
                cur = best
        return cur

    def clear_of_avoid(self, center: tuple[float, float], radius: float) -> tuple[float, float]:
        """مرکزِ یک نشانِ گرد را از ناحیه‌های پرهیز دور می‌کند (بالا یا پایین، هر کدام نزدیک‌تر)."""
        cx, cy = center
        for _ in range(4):
            hit = next((a for a in self.avoid if cx + radius > a[0] and cx - radius < a[2] and cy + radius > a[1] and cy - radius < a[3]), None)
            if hit is None:
                break
            cy = (hit[1] - radius - 4) if (hit[1] + hit[3]) / 2 > self.H / 2 else (hit[3] + radius + 4)
        return (min(max(cx, radius), self.W - radius), min(max(cy, radius), self.H - radius))

    def zones(self, sub_frac: float = 0.47, text_h: float = 0.40, overlap: float = 0.0) -> dict:
        """⇒ {text, subject, side}: ناحیهٔ متن و ناحیهٔ سوژه (سوژه تا لبهٔ بوم می‌رسد)."""
        x0, y0, x1, y1 = self.safe
        W, H = self.W, self.H
        side = self.subject_side
        if self.orient == "wide":
            sw = (x1 - x0) * sub_frac
            if side == "right":
                subj = (x1 - sw, 0.0, float(W), float(H))
                text = (x0, y0, x1 - sw + overlap * W, y1)
            else:
                subj = (0.0, 0.0, x0 + sw, float(H))
                text = (x0 + sw - overlap * W, y0, x1, y1)
        else:
            th = (y1 - y0) * text_h
            text = (x0, y0, x1, y0 + th)
            subj = (0.0, y0 + th * (0.95 - overlap * 0.4), float(W), float(H))   # سرِ سوژه روی زیرعنوان نیفتد
        return {"text": self.avoid_rect(text), "subject": subj, "side": side}

    # --- لایه‌ها
    def add(self, name, kind, img, xy=(0, 0), **kw):
        return self.comp.add(name, kind, img, xy, **kw)

    def center_add(self, name, kind, img, center, **kw):
        return self.comp.add(name, kind, img, (center[0] - img.width / 2, center[1] - img.height / 2), **kw)

    def text(self, name: str, text: str, rect, st: typo.TextStyle, *, max_lines: int = 3, min_f: float = 0.03, max_f: float = 0.16,
             ax: str = "center", ay: str = "middle", avoid: bool = True, opacity: float = 1.0, blend: str = "normal") -> Placed | None:
        text = typo.clean(text)
        if not typo.plain(text):
            return None
        if avoid:
            rect = self.avoid_rect(rect)
        bw, bh = rect[2] - rect[0], rect[3] - rect[1]
        if bw < 8 or bh < 8:
            return None
        if not st.font_key:
            st.font_key = self.font_key
        blk = typo.render_text(text, bw, bh, st, max_lines=max_lines, min_px=max(8, int(min_f * self.W)), max_px=max(10, int(max_f * self.W)))
        if blk is None:
            return None
        xy = typo.place(blk, rect, ax, ay)
        bbox = self.comp.add(name, "text", blk.img, xy, opacity=opacity, blend=blend)
        nominal = (xy[0] + blk.origin[0], xy[1] + blk.origin[1], xy[0] + blk.origin[0] + blk.nominal[0], xy[1] + blk.origin[1] + blk.nominal[1])
        if bbox:
            self.texts.append({"name": name, "bbox": list(bbox), "px": blk.px, "lines": blk.lines, "text": typo.plain(text)})
        return Placed(bbox, nominal, blk)

    def stack(self, rect, items: list[tuple[str, float]]) -> dict[str, tuple[float, float, float, float]]:
        """rect را به‌طورِ عمودی بینِ مورد‌های «غیرخالی» تقسیم می‌کند (نسبتِ وزن‌ها). ⇒ {کلید: rect}."""
        used = [(k, w) for k, w in items if self.has(k)]
        if not used:
            return {}
        tot = sum(w for _, w in used)
        y = rect[1]
        out = {}
        for k, w in used:
            h = (rect[3] - rect[1]) * w / tot
            out[k] = (rect[0], y, rect[2], y + h)
            y += h
        return out

    def label(self, name: str, text: str, center=None, xy=None, px: float = 40, **kw):
        img = typo.label(text, int(px), **kw)
        if img is None:
            return None
        if center is not None:
            bb = self.center_add(name, "badge", img, center)
        else:
            bb = self.comp.add(name, "badge", img, xy or (0, 0))
        return img, bb

    # --- پس‌زمینه‌ها
    def bg_wants_photo(self) -> bool:
        return self.spec["background"]["kind"] in ("photo", "ai") and self.inp.background is not None

    def bg_photo(self, *, darken: float = 0.0, blur: float = 0.0, tint: str | None = None, saturate: float = 1.0, grade: float = 0.0,
                 vign: float = 0.0, focus=(0.5, 0.5)) -> None:
        bg = P.cover(self.inp.background.convert("RGB"), self.size, focus)
        ub = self.spec["background"]
        dark = max(darken, ub.get("darken", 0.0))
        bl = max(blur, ub.get("blur", 0))
        if bl:
            from PIL import ImageFilter

            bg = bg.filter(ImageFilter.GaussianBlur(self.u(bl)))
        if grade:
            bg = P.grade_teal_orange(bg, grade)
        if saturate != 1.0:
            bg = P.adjust(bg, saturation=saturate)
        if tint:
            bg = P.darken(bg, 0.18, tint)
        if dark:
            bg = P.darken(bg, dark)
        if vign:
            bg = P.vignette(bg, vign)
        self.add("پس‌زمینه (عکس)", "background", bg)

    def scrim(self, rect, strength: float = 0.55, grow: float = 0.05, color: str = "#000000") -> None:
        """سایهٔ نرمِ پشتِ ناحیهٔ متن، وقتی پس‌زمینه عکس است. اگر زیرِ متن شلوغ باشد (عکسی که خودش متن یا جزئیاتِ زیاد دارد)،
        همان ناحیه مثلِ شیشهٔ مات کمی محو هم می‌شود تا عنوان خوانا بماند."""
        import numpy as np
        from PIL import ImageFilter

        x0, y0, x1, y1 = rect
        pad = int(min(self.W, self.H) * grow)
        feather = max(4, int(min(self.W, self.H) * 0.06))
        bw, bh = int(x1 - x0) + 2 * pad, int(y1 - y0) + 2 * pad
        if bw < 16 or bh < 16:
            return
        m = Image.new("L", (bw + 4 * feather, bh + 4 * feather), 0)
        ImageDraw.Draw(m).rectangle([2 * feather, 2 * feather, 2 * feather + bw, 2 * feather + bh], fill=255)
        m = m.filter(ImageFilter.GaussianBlur(feather))
        ox, oy = int(x0) - pad - 2 * feather, int(y0) - pad - 2 * feather
        # میزانِ شلوغی: میانگینِ بزرگیِ گرادیانِ روشنایی در خودِ ناحیه
        box = (max(0, int(x0)), max(0, int(y0)), min(self.W, int(x1)), min(self.H, int(y1)))
        busy = 0.0
        if box[2] - box[0] > 8 and box[3] - box[1] > 8:
            arr = np.asarray(self.comp.canvas.crop(box).convert("L"), dtype=np.float32)
            gy, gx = np.gradient(arr)
            busy = float(np.hypot(gx, gy).mean()) * (1080.0 / max(1, self.W))
        if busy > 4.5:
            strength = min(0.8, strength + 0.18)
            soft = self.comp.canvas.filter(ImageFilter.GaussianBlur(max(2.0, self.W * 0.011)))
            self.comp.canvas.paste(soft, (0, 0), self._full_mask(m, (ox, oy)))
        self.add("سایهٔ پشتِ متن", "fx", P.solid(m.size, color, m, strength), (ox, oy))

    def _full_mask(self, m: Image.Image, xy: tuple[int, int]) -> Image.Image:
        full = Image.new("L", self.size, 0)
        full.paste(m, xy)
        return full

    def bg_gradient(self, angle: float = 35.0, stops=None, name: str = "پس‌زمینه") -> None:
        stops = stops or [(0.0, self.pal.bg1), (1.0, self.pal.bg2)]
        self.add(name, "background", P.gradient(self.size, stops, angle))

    def texture(self, kind: str, color: str | None = None, alpha: float = 0.16, center=None, **kw) -> None:
        col = color or self.pal.text
        if kind == "halftone":
            self.add("بافت (نقطه‌چین)", "texture", P.halftone(self.size, col, alpha, spacing=self.u(kw.get("spacing", 22)), angle=kw.get("angle", 30),
                                                            direction=kw.get("direction", 90)))
        elif kind == "rays":
            self.add("پرتوها", "texture", P.rays(self.size, center or (self.W * 0.5, self.H * 0.5), kw.get("n", 18), col, alpha, kw.get("rot", 0)))
        elif kind == "stripes":
            self.add("بافت (راه‌راه)", "texture", P.stripes(self.size, col, alpha * 0.6, self.u(kw.get("width", 46)), kw.get("angle", 35)))
        elif kind == "grid":
            self.add("بافت (شبکه)", "texture", self._grid(col, alpha))
        elif kind == "grain":
            pass                                     # دانه در پایان روی همهٔ بوم می‌نشیند

    def _grid(self, color: str, alpha: float) -> Image.Image:
        img = Image.new("RGBA", self.size, (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        step = max(8, int(self.u(54)))
        a = int(255 * alpha)
        for x in range(0, self.W, step):
            d.line([(x, 0), (x, self.H)], fill=P.rgba(color, a), width=max(1, int(self.u(1.4))))
        for y in range(0, self.H, step):
            d.line([(0, y), (self.W, y)], fill=P.rgba(color, a), width=max(1, int(self.u(1.4))))
        return img

    def auto_texture(self, default: str, **kw) -> None:
        kind = self.spec["background"]["texture"] or default
        self.texture(kind, **kw)

    # --- سوژه
    def subject_rgba(self, which: int = 1) -> tuple[Image.Image | None, bool]:
        img = self.inp.subject if which == 1 else self.inp.subject2
        cut = self.inp.subject_is_cutout if which == 1 else self.inp.subject2_is_cutout
        if img is None:
            return None, False
        mode = self.spec["subject"]["mode"] if which == 1 else "auto"
        if mode == "photo":
            cut = False
        elif mode == "cutout" and not cut:
            cut = False       # عکسِ بی‌پس‌زمینهٔ بریده‌نشده هم به‌صورتِ عکس می‌آید (برشِ دقیق = API ِ «حذفِ پس‌زمینه»)
        return img, cut

    def put_cutout(self, name: str, img: Image.Image, rect, *, valign: str = "bottom", halign: str = "center", scale: float = 1.0,
                   flip: bool = False, outline: str | None = None, ow: float = 0.0, shadow: bool = True, glow: tuple | None = None,
                   rim: str | None = None, max_w_frac: float = 1.0) -> tuple[int, int, int, int] | None:
        """سوژهٔ بریده را در rect می‌گذارد (اندازه به «جا شدن» با ضریبِ scale)؛ ⇒ کادرِ دیدنی."""
        sub = P.crop_to_alpha(img, pad=0)
        if flip:
            sub = sub.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
        rw, rh = rect[2] - rect[0], rect[3] - rect[1]
        s = scale * self.spec["subject"]["scale"]
        tw, th = rw * max_w_frac * s, rh * s
        src_w = sub.width
        sub = P.contain(sub, tw, th)
        if sub.width / max(1.0, float(src_w)) > 1.9:
            self._warn_once("کیفیتِ عکسِ سوژه برای این اندازه پایین است؛ عکسِ بزرگ‌تر بهتر می‌شود.")
        if ow > 0 or shadow or glow or rim:
            sub, off = P.sticker(sub, ow, outline or "#ffffff", shadow=(self.u(6), self.u(10), self.u(14), "#000000", 0.45) if shadow else None,
                                 glow=glow, rim=rim)
        else:
            off = (0, 0)
        if halign == "left":
            x = rect[0]
        elif halign == "right":
            x = rect[2] - (sub.width - off[0] * 2)
        else:
            x = (rect[0] + rect[2]) / 2 - (sub.width - off[0] * 2) / 2
        y = rect[3] - (sub.height - off[1] * 2) if valign == "bottom" else (rect[1] if valign == "top" else (rect[1] + rect[3]) / 2 - (sub.height - off[1] * 2) / 2)
        return self.comp.add(name, "subject", sub, (x - off[0], y - off[1]))

    def put_photo(self, name: str, img: Image.Image, rect, *, fade: str | None = None, extent: float = 0.35, focus=(0.5, 0.35),
                  radius: float = 0.0, border: str | None = None, bw: float = 0.0, rot: float = 0.0, shadow: bool = False):
        """عکسِ بدونِ بُرش‌خوردنِ سوژه (cover در rect) با محوشدگیِ لبه (fade: top/bottom/left/right) یا کارتِ گوشه‌گرد."""
        rw, rh = int(rect[2] - rect[0]), int(rect[3] - rect[1])
        if rw < 4 or rh < 4:
            return None
        ph = P.cover(img.convert("RGB"), (rw, rh), focus).convert("RGBA")
        mask = Image.new("L", (rw, rh), 255)
        if radius:
            mask = P.rounded_mask((rw, rh), radius)
        if fade:
            ramp = P.edge_ramp((rw, rh), fade, extent, 0.0, 1.0)
            # ramp از fade به داخل صفر می‌شود؛ ما می‌خواهیم لبهٔ fade شفاف باشد
            ramp = ramp.point(lambda v: 255 - v)
            from PIL import ImageChops

            mask = ImageChops.multiply(mask, ramp)
        ph.putalpha(mask)
        if border and bw:
            pad = int(bw)
            frame = Image.new("RGBA", (rw + 2 * pad, rh + 2 * pad), (0, 0, 0, 0))
            fm = P.rounded_mask((rw + 2 * pad, rh + 2 * pad), radius + pad) if radius else Image.new("L", (rw + 2 * pad, rh + 2 * pad), 255)
            frame = Image.alpha_composite(frame, P.solid(frame.size, border, fm))
            frame.alpha_composite(ph, (pad, pad))
            ph = frame
        if shadow:
            m = ph.getchannel("A")
            sh = P.soft_shadow(ph.size, m, self.u(4), self.u(10), self.u(14), "#000000", 0.4)
            canvas = Image.new("RGBA", (ph.width + int(self.u(60)), ph.height + int(self.u(60))), (0, 0, 0, 0))
            o = int(self.u(30))
            canvas.alpha_composite(sh, (o, o))
            canvas.alpha_composite(ph, (o, o))
            ph = canvas
            rect = (rect[0] - o, rect[1] - o, rect[2], rect[3])
        if abs(rot) > 0.01:
            ph = ph.rotate(rot, resample=Image.Resampling.BICUBIC, expand=True)
        cx, cy = (rect[0] + rect[2]) / 2, (rect[1] + rect[3]) / 2
        return self.center_add(name, "photo", ph, (cx, cy))

    def _warn_once(self, msg: str) -> None:
        if msg not in self.warnings:
            self.warnings.append(msg)

    # --- لوگو
    def put_logo(self) -> None:
        lg = self.spec["logo"]
        if not lg["show"] or self.inp.logo is None:
            return
        pos = lg["position"]
        if pos == "auto":
            pos = "tl" if self.orient in ("wide", "square") else "tr"
            # روی ناحیه‌های پرهیز نیفتد
        side = int(self.W * (0.12 if self.orient != "tall" else 0.16))
        img = P.crop_to_alpha(self.inp.logo.convert("RGBA"))
        logo = P.contain(img, side, side * 0.8)
        pad = int(self.u(16))
        tile = Image.new("RGBA", (logo.width + 2 * pad, logo.height + 2 * pad), (0, 0, 0, 0))
        m = P.rounded_mask(tile.size, pad * 1.1)
        tile = Image.alpha_composite(tile, P.solid(tile.size, "#ffffff", m, 0.92))
        tile.alpha_composite(logo, (pad, pad))
        x0, y0, x1, y1 = self.safe
        cx = {"tl": x0, "bl": x0, "tr": x1 - tile.width, "br": x1 - tile.width, "tc": (self.W - tile.width) / 2, "bc": (self.W - tile.width) / 2}[pos]
        cy = {"tl": y0, "tr": y0, "tc": y0, "bl": y1 - tile.height, "br": y1 - tile.height, "bc": y1 - tile.height}[pos]
        box = (cx, cy, cx + tile.width, cy + tile.height)
        for a in self.avoid:                                     # لوگو روی ناحیهٔ پرهیز نیفتد: به گوشهٔ مقابل برود
            if box[0] < a[2] and box[2] > a[0] and box[1] < a[3] and box[3] > a[1]:
                cx = x1 - tile.width if cx < self.W / 2 else x0
                break
        self.comp.add("لوگو", "logo", tile, (cx, cy))

    def finish(self, grain_amount: float = 0.0, vign: float = 0.0) -> None:
        if vign:
            self.comp.replace(P.vignette(self.comp.canvas, vign))
        if grain_amount or self.spec["background"]["texture"] == "grain":
            self.comp.replace(P.grain(self.comp.canvas, grain_amount or 0.03, self.spec.get("seed", 1)))


# ───────────────────────────── اجرا

def draw_guides(img: Image.Image, fmt: Format) -> Image.Image:
    """خطِ راهنمای حاشیهٔ امن (سبز) و ناحیه‌های پرهیز (قرمز) روی یک کپی؛ فقط برای پیش‌نمایش."""
    out = img.convert("RGBA")
    ov = Image.new("RGBA", out.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    x0, y0, x1, y1 = F.safe_rect(fmt, out.size)
    d.rectangle([x0, y0, x1, y1], outline=(34, 197, 94, 230), width=max(2, out.width // 320))
    for a in F.avoid_rects(fmt, out.size):
        d.rectangle(a, fill=(239, 68, 68, 70), outline=(239, 68, 68, 230), width=max(2, out.width // 320))
    return Image.alpha_composite(out, ov).convert("RGB")


def render(spec: dict, inputs: Inputs | None = None, *, scale: float = 1.0, keep_layers: bool = False, guides: bool | None = None
           ) -> RenderResult:
    from . import styles

    inp = inputs or Inputs()
    fmt = F.get(spec["format"])
    sd = styles.STYLES[spec["style"]]
    size = F.scaled(fmt, scale)
    c = Ctx(fmt, spec, inp, size, keep_layers)
    oc = spec["colors"]
    brand = inp.brand_colors if oc.get("use_brand", True) else []
    c.pal = pal_mod.build(oc.get("mood") or sd.mood, brand, {"primary": oc.get("primary"), "secondary": oc.get("secondary"),
                                                              "accent": oc.get("accent")}, int(oc.get("variation") or 0))
    if spec["font"] != typo.AUTO_FONT:
        c.font_key = spec["font"]
    elif oc.get("use_brand", True) and inp.heading_font in typo.FONT_CHOICES:
        c.font_key = inp.heading_font
    else:
        c.font_key = sd.font
    side = spec["subject"]["side"]
    if side == "auto":
        side = "right" if int(oc.get("variation") or 0) % 2 == 1 else "left"      # نسخهٔ B سوژه را آن‌طرف می‌گذارد
    c.subject_side = "left" if side == "center" else side
    sd.fn(c)
    c.put_logo()
    img = c.comp.canvas
    if (guides if guides is not None else spec.get("guides")):
        img = draw_guides(img, fmt)
    return RenderResult(image=img, layers=c.comp.report, warnings=c.warnings, size=size, texts=c.texts, palette=c.pal.public(),
                        kept=c.comp.layers)


def to_jpeg_bytes(img: Image.Image, quality: int = 86, max_kb: int = 0) -> bytes:
    import io

    q = quality
    while True:
        buf = io.BytesIO()
        img.convert("RGB").save(buf, "JPEG", quality=q, optimize=True, progressive=True, subsampling=0 if q >= 88 else 2)
        data = buf.getvalue()
        if not max_kb or len(data) <= max_kb * 1024 or q <= 50:
            return data
        q -= 8
