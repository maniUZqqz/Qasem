"""ساختِ تصویر از ماسکوت: پست و استوری با پس‌زمینه، حبابِ گفتار، کپشن، استیکرِ شفاف، برگهٔ مدل و برگهٔ نمونه.

SOURCE: ported from InstAI (maniUZqqz/Instai) instai/render/stick/compose.py (``compose_still``, ``_bubble``, ``_caption``, ``model_sheet``) @ 82733b0, adapted for
NMarketing brand mascots: output sizes of a store (Instagram 4:5 / 1:1, story 9:16 with the platform's avoid zones, 16:9), brand-coloured captions,
bubble/caption text drawn by the thumbnail maker's typography engine (engine/text.py), the transparent sticker, and a Persian model sheet that
carries the store name and the lock version. The video clips of InstAI (puppet renderer + ffmpeg) are NOT ported.

همهٔ تابع‌ها خالص‌اند: ورودی spec/dict و (اختیاری) لوگو، خروجی PIL.Image؛ بدونِ دیتابیس و بدونِ GPU.
"""
from __future__ import annotations

import math

from PIL import Image, ImageDraw

from . import parts, poses, scenes, stage, text
from . import spec as S

INK = (31, 36, 48, 255)
#: اندازه‌های خروجی. figure = جای پیش‌فرضِ شخصیت (height کسری از ارتفاعِ بوم برای جعبهٔ ۹۰۰ پیکسلیِ طراحی)؛ safe = بالا/پایینی که برنامه روی تصویر می‌اندازد.
SIZES: dict[str, dict] = {
    "ig_portrait": {"w": 1080, "h": 1350, "fa": "پستِ اینستاگرام ۴:۵", "aspect": "4:5", "figure": {"height": 0.74, "y": 0.955}, "safe": (0.0, 0.0)},
    "ig_square": {"w": 1080, "h": 1080, "fa": "پستِ مربع ۱:۱", "aspect": "1:1", "figure": {"height": 0.78, "y": 0.965}, "safe": (0.0, 0.0)},
    "story": {"w": 1080, "h": 1920, "fa": "استوری و ریلز ۹:۱۶", "aspect": "9:16", "figure": {"height": 0.62, "y": 0.82}, "safe": (0.13, 0.18), "font": 1.15},
    "wide": {"w": 1920, "h": 1080, "fa": "افقی ۱۶:۹", "aspect": "16:9", "figure": {"height": 0.82, "y": 0.965}, "safe": (0.0, 0.0)},
}
DEFAULT_SIZE = "ig_portrait"
POSITIONS = {"center": 0.5, "left": 0.30, "right": 0.70}
BUBBLE_KINDS = {"say": "گفتار", "think": "فکر", "shout": "فریاد"}


def size_of(key: str | None) -> tuple[int, int]:
    d = SIZES.get(key or DEFAULT_SIZE) or SIZES[DEFAULT_SIZE]
    return d["w"], d["h"]


# ------------------------------------------------------------------ colours

def _rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _lum(c: tuple) -> float:
    def ch(v):
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4

    return 0.2126 * ch(c[0]) + 0.7152 * ch(c[1]) + 0.0722 * ch(c[2])


def contrast(a: tuple, b: tuple) -> float:
    la, lb = _lum(a), _lum(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def _ink_on(bg: tuple) -> str:
    return "#ffffff" if contrast((255, 255, 255), bg) >= contrast((20, 24, 34), bg) else "#141822"


def _accent_on(bg: tuple, brand: list[str]) -> str:
    """رنگِ «کلمهٔ پررنگ» روی ``bg``: رنگِ برندی که کنتراستِ کافی دارد، وگرنه رنگِ متن."""
    for c in brand:
        try:
            if contrast(_rgb(c), bg) >= 3.0:
                return c
        except ValueError:
            continue
    return _ink_on(bg)


# ------------------------------------------------------------------ text overlays

def _bubble(canvas: Image.Image, head: tuple[float, float, float], txt: str, kind: str, brand: list[str], *, font_px: int = 52, min_y: float = 24.0) -> tuple[int, int, int, int] | None:
    """حبابِ گفتار/فکر/فریاد بالای سرِ شخصیت؛ متن با موتورِ تایپوگرافیِ تامنیل‌ساز. ⇒ کادرِ حباب."""
    w, h = canvas.size
    f = min(w, h) / 1080
    hx, hy, hr = head
    max_w = int(w * (0.64 if w > h else 0.72))
    fill = (255, 255, 255, 255)
    accent = _accent_on((255, 255, 255), brand)
    blk = text.block(txt, max_w - 70 * f, font_px * 1.5 * 4, px=max(18, int(font_px * f)), fill="#1f2430", hl=accent, max_lines=4, align="center")
    if blk is None:
        return None
    tw, th = blk.nominal
    pad_x, pad_y = 38 * f, 24 * f
    bw, bh = tw + 2 * pad_x, th + 2 * pad_y
    margin = 24 * f
    bx = min(max(hx - bw * (0.32 if hx > w / 2 else 0.68), margin), w - bw - margin)
    gap = hr * {"shout": 1.35, "think": 1.15}.get(kind, 0.72)
    by = max(min_y, hy - hr - bh - gap)
    by = min(by, h - bh - margin)
    box = (bx, by, bx + bw, by + bh)
    ss = 2
    layer = Image.new("RGBA", (w * ss, h * ss), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    lw = max(2, int(5 * f * ss))

    def S_(pts):
        return [(x * ss, y * ss) for x, y in pts]

    if kind == "shout":
        n, cx, cy = 14, (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
        rx, ry = bw / 2 + 26 * f, bh / 2 + 26 * f
        pts = []
        for i in range(n * 2):
            r = 1.0 if i % 2 == 0 else 0.84
            ang = math.pi * i / n
            pts.append((cx + math.cos(ang) * rx * r, cy + math.sin(ang) * ry * r))
        tint = _rgb(brand[0]) if brand else (232, 162, 43)
        shout_fill = tuple(int(c + (255 - c) * 0.82) for c in tint) + (255,)
        d.polygon(S_(pts), fill=shout_fill)
        d.line(S_(pts + [pts[0]]), fill=INK, width=lw, joint="curve")
    else:
        d.rounded_rectangle([v * ss for v in box], radius=36 * f * ss, fill=fill, outline=INK, width=lw)
        tail_x = min(max(hx, box[0] + 50 * f), box[2] - 50 * f)
        if kind == "think":
            span = max(20.0 * f, hy - hr - 8 * f - box[3])
            for dx, rr in ((0.18, 15), (0.5, 11), (0.80, 7)):
                cxx, cyy = tail_x + (hx - tail_x) * dx, box[3] + span * dx
                rr *= f
                d.ellipse([(cxx - rr) * ss, (cyy - rr) * ss, (cxx + rr) * ss, (cyy + rr) * ss], fill=fill, outline=INK, width=max(2, int(4 * f * ss)))
        else:
            tip = (hx, min(hy - hr - 6 * f, box[3] + 90 * f))
            d.polygon(S_([(tail_x - 24 * f, box[3] - 3 * f), (tail_x + 24 * f, box[3] - 3 * f), tip]), fill=fill)
            d.line(S_([(tail_x - 24 * f, box[3] - 2 * f), tip, (tail_x + 24 * f, box[3] - 2 * f)]), fill=INK, width=lw, joint="curve")
            d.line(S_([(tail_x - 21 * f, box[3] - 3 * f), (tail_x + 21 * f, box[3] - 3 * f)]), fill=fill, width=max(2, int(8 * f * ss)))
    layer = layer.resize((w, h), Image.LANCZOS)
    canvas.alpha_composite(layer)
    ox, oy = text.typo().place(blk, (box[0], box[1], box[2], box[3]), "center", "middle")
    text._blit(canvas, blk.img, ox, oy)
    return int(box[0]), int(box[1]), int(box[2]), int(box[3])


def _caption_layout(size: tuple[int, int], txt: str, position: str, brand: list[str], safe: tuple[float, float], font_px: int = 56) -> dict | None:
    """جای و متنِ نوارِ کپشن (بدونِ کشیدن) تا شخصیت بتواند کنارش جا بگیرد. رنگِ دومِ برند زمینه است؛ متن سفید یا تیره بنا بر کنتراست."""
    w, h = size
    f = min(w, h) / 1080
    bg = _rgb(brand[1]) if len(brand) > 1 else (_rgb(brand[0]) if brand else (22, 63, 117))
    margin = 54 * f
    blk = text.block(txt, w - 2 * margin - 40 * f, font_px * 1.5 * 3, px=max(20, int(font_px * f)), fill=_ink_on(bg), hl=_accent_on(bg, [*brand, "#ffffff"]), max_lines=3, align="center")
    if blk is None:
        return None
    bh = blk.nominal[1] + 56 * f
    top_safe, bottom_safe = safe
    if position == "bottom":
        y1 = h * (1 - bottom_safe)
        y0 = y1 - bh
    else:
        y0 = h * top_safe
        y1 = y0 + bh
    return {"blk": blk, "bg": bg, "y0": y0, "y1": y1, "margin": margin, "position": "bottom" if position == "bottom" else "top"}


def _caption_draw(canvas: Image.Image, lay: dict) -> tuple[int, int, int, int]:
    w, _h = canvas.size
    y0, y1 = lay["y0"], lay["y1"]
    canvas.alpha_composite(Image.new("RGBA", (w, int(y1 - y0)), lay["bg"] + (236,)), (0, int(y0)))
    ox, oy = text.typo().place(lay["blk"], (lay["margin"], y0, w - lay["margin"], y1), "center", "middle")
    text._blit(canvas, lay["blk"].img, ox, oy)
    return 0, int(y0), w, int(y1)


# ------------------------------------------------------------------ stills

def actor_defaults(size_key: str, position: str = "center") -> dict:
    lay = SIZES.get(size_key) or SIZES[DEFAULT_SIZE]
    return {"x": POSITIONS.get(position, 0.5), "y": lay["figure"]["y"], "height": lay["figure"]["height"]}


def compose_still(scene: dict, *, logo: Image.Image | None = None, keep_shots: bool = False) -> tuple[Image.Image, dict]:
    """یک تصویر. scene = {size | (width، height)، background (کلید یا {"color"})، brand [اصلی، دوم]، position، actors[{spec، pose، expression، x، y، height، flip، talk، prop}]،
    bubbles[{actor، text، kind، font}]، caption{text، position، font}}. ⇒ (RGB، info)."""
    size_key = scene.get("size") if scene.get("size") in SIZES else DEFAULT_SIZE
    if scene.get("width") and scene.get("height"):
        w, h, size_key = int(scene["width"]), int(scene["height"]), scene.get("size") or "custom"
    else:
        w, h = size_of(size_key)
    safe = (SIZES.get(size_key) or {}).get("safe", (0.0, 0.0))
    brand = [c for c in (scene.get("brand") or []) if isinstance(c, str)]
    bg = scene.get("background", scenes.DEFAULT_BACKGROUND)
    if isinstance(bg, dict) and bg.get("color"):
        canvas = scenes.solid(bg["color"], w, h).convert("RGBA")
    else:
        canvas = scenes.draw(bg if isinstance(bg, str) else scenes.DEFAULT_BACKGROUND, w, h, brand or None).convert("RGBA")
    actors = list(scene.get("actors") or [])
    cap = scene.get("caption")
    cap_lay = _caption_layout((w, h), str(cap["text"]), str(cap.get("position", "top")), brand, safe, int(cap.get("font", 56))) if cap and str(cap.get("text", "")).strip() else None
    top_ref = h * safe[0]
    top_used, bottom_limit = top_ref, None
    if cap_lay is not None:
        if cap_lay["position"] == "top":
            top_used = cap_lay["y1"]
        else:
            bottom_limit = cap_lay["y0"] - 0.012 * h
    shots: list[stage.ActorShot] = []
    for a in sorted(actors, key=lambda a: float(a.get("y", 0.93))):
        base = actor_defaults(size_key if size_key in SIZES else DEFAULT_SIZE, scene.get("position", "center"))
        explicit = a.get("y") is not None or a.get("height") is not None
        a = {**base, **{k: v for k, v in a.items() if v is not None}}
        if cap_lay is not None and not explicit:           # شخصیت کنارِ نوارِ کپشن جا می‌گیرد، روی آن نمی‌افتد
            feet = min(a["y"] * h, bottom_limit) if bottom_limit is not None else a["y"] * h
            natural = max(1.0, a["y"] * h - top_ref)
            factor = max(0.45, min(1.0, (feet - top_used) / natural))
            a["y"], a["height"] = feet / h, a["height"] * factor
        shot = stage.render_actor(a, w, h, logo=logo, inside=0.02)
        canvas.alpha_composite(shot.layer)
        shots.append(shot)
    info: dict = {"size": [w, h], "poses": [s.pose for s in shots], "props": [s.prop for s in shots], "expressions": [s.expression for s in shots],
                  "figure_bbox": [list(s.bbox) if s.bbox else None for s in shots], "background": bg if isinstance(bg, str) else "color", "bubbles": [], "caption": None}
    min_y = h * safe[0] + 20 * min(w, h) / 1080
    if cap_lay is not None and cap_lay["position"] == "top":
        min_y = max(min_y, cap_lay["y1"] + 16 * min(w, h) / 1080)
    for b in scene.get("bubbles") or []:
        idx = int(b.get("actor", 0))
        if 0 <= idx < len(shots) and str(b.get("text", "")).strip():
            fscale = float((SIZES.get(size_key) or {}).get("font", 1.0))
            box = _bubble(canvas, shots[idx].head, str(b["text"]), str(b.get("kind", "say")) if str(b.get("kind", "say")) in BUBBLE_KINDS else "say", brand,
                          font_px=int(float(b.get("font", 52)) * fscale), min_y=min_y)
            info["bubbles"].append({"actor": idx, "box": list(box) if box else None})
    if cap_lay is not None:
        info["caption"] = list(_caption_draw(canvas, cap_lay))
    if keep_shots:
        info["shots"] = shots
    return canvas.convert("RGB"), info


def figure_layer(actor: dict, w: int, h: int, *, logo: Image.Image | None = None, inside: float | None = None) -> stage.ActorShot:
    """فقط شخصیت روی بومِ شفاف و بدونِ سایه (برای بررسیِ رنگ و برای استیکر)."""
    return stage.render_actor({**actor, "shadow": False}, w, h, logo=logo, shadow=False, inside=inside)


QA_CANVAS = (600, 760)             # بومِ استانداردِ بررسیِ رنگ (هر پیکسلِ طراحی ≈ ۰٫۷۶ پیکسل؛ باریک‌ترین جزء هم چند پیکسلِ تک‌رنگ دارد)


def qa_layer(actor: dict, *, logo: Image.Image | None = None) -> stage.ActorShot:
    """لایهٔ شفافِ همین شخصیت (همین ژست، حالت، وسیله و جهت) روی بومِ استانداردِ بررسیِ رنگ؛ رنگ‌ها به اندازهٔ بومِ نهاییِ پست بستگی ندارند، پس بررسی روی یک اندازهٔ ثابت درست‌تر است."""
    w, h = QA_CANVAS
    a = {k: v for k, v in actor.items() if k in ("spec", "pose", "expression", "flip", "prop", "talk")}
    return figure_layer({**a, "x": 0.5, "y": 0.955, "height": 0.9}, w, h, logo=logo, inside=0.02)


def sticker(spec: dict, *, pose: str = "stand", expression: str = "happy", prop: str | None = None, flip: bool = False, logo: Image.Image | None = None,
            height_px: int = 1500, pad: float = 0.035, crop: str = "full") -> tuple[Image.Image, dict]:
    """استیکرِ PNG با پس‌زمینهٔ شفاف (برای تامنیل، ادیتورِ عکس و ویدیو): فقط شخصیت، بریده‌شده تا لبه‌ها با کمی حاشیه.
    ``crop="bust"``: نیم‌تنه (سر و شانه و بازو)؛ برای تامنیل‌هایی که «چهرهٔ بزرگ» می‌خواهند بهتر از تمام‌قد است."""
    h = int(height_px)
    w = int(h * 1.0)
    shot = figure_layer({"spec": spec, "pose": pose, "expression": expression, "prop": prop, "flip": flip, "x": 0.5, "y": 0.955, "height": 0.97}, w, h, logo=logo)
    box = shot.layer.getchannel("A").point(lambda v: 255 if v > 6 else 0).getbbox()
    if box is None:
        raise ValueError("empty figure")
    if crop == "bust":
        box = (box[0], box[1], box[2], box[1] + int((box[3] - box[1]) * 0.40))
    m = int(max(box[2] - box[0], box[3] - box[1]) * pad)
    box = (max(0, box[0] - m), max(0, box[1] - m), min(w, box[2] + m), min(h, box[3] + m))
    out = shot.layer.crop(box)
    if crop == "bust":                                        # بریدنِ افقی هم تا اطرافِ سرِ شخصیت
        inner = out.getchannel("A").point(lambda v: 255 if v > 6 else 0).getbbox()
        if inner:
            out = out.crop(inner)
    return out, {"pose": shot.pose, "expression": shot.expression, "prop": shot.prop, "crop": crop, "size": list(out.size)}


# ------------------------------------------------------------------ model sheet and contact sheets

def _cell(spec: dict, size: tuple[int, int], *, expression: str = "neutral", pose: str = "stand", flip: bool = False, zoom_head: bool = False,
          logo: Image.Image | None = None, prop: str | None = None) -> Image.Image:
    w, h = size
    if zoom_head:
        px = (w * 0.62) / 156
        a = {"spec": spec, "expression": expression, "pose": pose, "flip": flip, "x": 0.5, "shadow": False, "prop": "none",
             "height": 900 * px / h, "y": (h * 0.46 + (parts.ANCHOR[1] - 224) * px) / h}
    else:
        a = {"spec": spec, "expression": expression, "pose": pose, "flip": flip, "x": 0.5, "y": 0.96, "height": 0.9, "shadow": False, "prop": prop}
    return stage.render_actor(a, w, h, logo=logo, shadow=False).layer


def model_sheet(spec: dict, *, title: str = "", store_name: str = "", version: int | None = None, logo: Image.Image | None = None) -> Image.Image:
    """برگهٔ مدلِ فارسی: نامِ شخصیت، نمای اصلی و آینه‌ای، ۸ حالتِ چهره، ۸ ژستِ بازاریابی، کلیدِ رنگ و جملهٔ هویت. همین برگه را مالک یک بار تأیید می‌کند."""
    s = S.normalize(spec)
    W, H = 2000, 1600
    sheet = Image.new("RGBA", (W, H), (244, 241, 234, 255))
    d = ImageDraw.Draw(sheet)
    d.rectangle([0, 0, W, 110], fill=(31, 36, 48, 255))
    name = title or s["name"] or "؟"
    text.draw_text(sheet, name, (W - 60, 22), 58, fill="#ffffff", anchor="ra", max_w=900)
    text.draw_text(sheet, "برگهٔ مدلِ ماسکوت" + (f" · نسخهٔ {_fa_digits(version)}" if version else ""), (60, 38), 36, fill="#c8cedc", anchor="la", max_w=800)
    if store_name:
        text.draw_text(sheet, store_name, (W // 2, 36), 36, fill="#c8cedc", anchor="ma", max_w=500)

    def label(x, y, txt, px=30, anchor="ma"):
        text.draw_text(sheet, txt, (x, y), px, fill="#3c404c", anchor=anchor, max_w=600)

    for i, flip in enumerate((False, True)):
        x = 60 + i * 410
        d.rectangle([x, 150, x + 380, 710], fill=(255, 255, 255, 255))
        cell = _cell(s, (380, 560), flip=flip, pose="stand", logo=logo, prop="none")
        sheet.alpha_composite(cell, (x, 150))
    label(250, 722, "نمای اصلی")
    label(660, 722, "نمای آینه‌ای")
    kx = 900
    label(kx + 520, 150, "کلیدِ رنگ", 36)
    pal: list[dict] = []
    for c in S.palette(s):                                       # نقش‌های هم‌رنگ یک ردیف می‌شوند
        for q in pal:
            if q["hex"] == c["hex"]:
                q["roles"].append(c["role"])
                break
        else:
            pal.append({**c, "roles": [c["role"]]})
    for i, c in enumerate(pal):
        col, row = i % 2, i // 2
        x0, y0 = kx + col * 520, 210 + row * 118
        d.rounded_rectangle([x0, y0, x0 + 96, y0 + 96], radius=18, fill=_rgb(c["hex"]) + (255,), outline=(31, 36, 48, 255), width=4)
        text.draw_text(sheet, c["hex"].upper(), (x0 + 116, y0 + 6), 32, fill="#1f2430", anchor="la", max_w=300)
        text.draw_text(sheet, f"{' / '.join(S.fa_word(r) for r in c['roles'])} · {S.fa_word(c['name'])}", (x0 + 116, y0 + 50), 28, fill="#5a5e6a", anchor="la", max_w=380, weight=600)
    anchor_y = 210 + ((len(pal) + 1) // 2) * 118 + 24
    label(kx + 520, anchor_y, "قاعدهٔ هویت (برای مدل‌های تصویرساز)", 32)
    blk = text.block(S.anchor_text(s), W - 60 - kx, 190, px=28, fill="#3c404c", font="vazirmatn", weight=500, align="left", max_lines=5)
    if blk is not None:
        ox, oy = text.typo().place(blk, (kx, anchor_y + 56, W - 60, anchor_y + 250), "left", "top")
        text._blit(sheet, blk.img, ox, oy)
    label(W // 2, 780, "حالت‌های چهره", 34)
    ew = (W - 120) // 8
    for i, ex in enumerate(parts._EXPR):
        x = 60 + i * ew
        d.rectangle([x, 826, x + ew - 10, 1066], fill=(255, 255, 255, 255))
        sheet.alpha_composite(_cell(s, (ew - 10, 240), expression=ex, zoom_head=True, logo=logo), (x, 826))
        label(x + (ew - 10) // 2, 1074, S.fa_word(ex), 26)
    label(W // 2, 1124, "ژست‌ها", 34)
    pw = (W - 120) // len(poses.SHEET_POSES)
    for i, pz in enumerate(poses.SHEET_POSES):
        x = 60 + i * pw
        d.rectangle([x, 1172, x + pw - 10, 1512], fill=(255, 255, 255, 255))
        sheet.alpha_composite(_cell(s, (pw - 10, 340), pose=pz, logo=logo), (x, 1172))
        label(x + (pw - 10) // 2, 1520, poses.label_fa(pz), 24)
    text.draw_text(sheet, "شخصیتِ کارتونیِ کشیده‌شده با کد؛ نه آدمِ واقعی. این برگه مرجعِ همهٔ پست‌هاست.", (W - 60, 1562), 24, fill="#7a7e8a", anchor="ra", max_w=1500, weight=500)
    return sheet.convert("RGB")


def _fa_digits(v) -> str:
    return str(v).translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹"))


def contact_poses(spec: dict, pose_list: list[str] | None = None, *, size: str = "ig_square", cell: int = 330, cols: int = 6, brand: list[str] | None = None,
                  background: str = "brand", expression: str = "happy", logo: Image.Image | None = None) -> Image.Image:
    """برگهٔ نمونهٔ ژست‌ها: هر ژست در یک خانه (همان شخصیت، همان رنگ‌ها) با نامِ فارسی."""
    pose_list = list(pose_list or poses.names())
    rows = math.ceil(len(pose_list) / cols)
    lab = 44
    sheet = Image.new("RGBA", (cols * cell + (cols + 1) * 10, rows * (cell + lab) + (rows + 1) * 10), (244, 241, 234, 255))
    for i, pz in enumerate(pose_list):
        img, _ = compose_still({"size": size, "background": background, "brand": brand or [], "actors": [{"spec": spec, "pose": pz, "expression": expression}]}, logo=logo)
        img = img.resize((cell, int(cell * img.height / img.width)), Image.LANCZOS)
        r, c = divmod(i, cols)
        x, y = 10 + c * (cell + 10), 10 + r * (cell + lab + 10)
        sheet.paste(img.crop((0, 0, cell, min(img.height, cell))), (x, y))
        text.draw_text(sheet, poses.label_fa(pz), (x + cell // 2, y + cell + 6), 26, fill="#1f2430", anchor="ma", max_w=cell - 10)
    return sheet.convert("RGB")


def contact_sizes(spec: dict, *, pose: str = "thumbs_up", expression: str = "happy", brand: list[str] | None = None, background: str = "brand", txt: str = "",
                  logo: Image.Image | None = None, height: int = 640) -> Image.Image:
    """همان شخصیت و همان ژست در هر چهار اندازه، کنارِ هم."""
    tiles = []
    for key in SIZES:
        scene = {"size": key, "background": background, "brand": brand or [], "actors": [{"spec": spec, "pose": pose, "expression": expression}]}
        if txt:
            scene["bubbles"] = [{"actor": 0, "text": txt, "kind": "say"}]
        img, _ = compose_still(scene, logo=logo)
        tiles.append((key, img.resize((int(img.width * height / img.height), height), Image.LANCZOS)))
    W = sum(t.width for _, t in tiles) + 10 * (len(tiles) + 1)
    sheet = Image.new("RGBA", (W, height + 70), (244, 241, 234, 255))
    x = 10
    for key, t in tiles:
        sheet.paste(t, (x, 10))
        text.draw_text(sheet, SIZES[key]["fa"], (x + t.width // 2, height + 22), 28, fill="#1f2430", anchor="ma", max_w=t.width - 10)
        x += t.width + 10
    return sheet.convert("RGB")
