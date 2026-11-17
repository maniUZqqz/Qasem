# -*- coding: utf-8 -*-
"""درختِ اجزای mv2code (tree_json) ⇒ سندهای سایت‌ساز (بلوک‌های «بخش»، «ستون‌ها»، «تیتر»، «متن»، «دکمه»، «تصویر»، «فرمِ تماس»…).

تابعِ اصلی ``map_tree(tree, image)`` خالص است (بی‌پایگاه‌داده و بی‌شبکه): درخت + تصویرِ اصلی (آرایهٔ RGB، برای خواندنِ رنگِ واقعیِ هر نوار و بریدنِ تصویرها) ⇒
``{"theme", "header", "page", "footer", "menu", "crops", "stats"}``. تصویرها در سند به‌شکلِ ``crop:<کلید>`` می‌آیند و ``services_site.create_draft`` آن‌ها را به رسانهٔ پروژه
می‌برد و به ``m:<شناسه>`` عوض می‌کند. چیزی منتشر نمی‌شود؛ خروجی فقط «پیش‌نویس» است.

قاعده‌ها (همه با درخت‌های واقعی آزموده شده‌اند؛ درخت صاف است، پس چیدمان را از روی هندسه می‌سازیم نه از روی تودرتویی):

* مرجعِ همه‌چیز **هندسه** است: نوار (بخش) = دسته‌ای از اجزا که بینشان فاصلهٔ عمودیِ کمتر از ``BAND_GAP`` است؛ ردیف = اجزایی که روی هم‌قد می‌افتند؛ ردیفِ چندتایی = «ستون‌ها».
* کارتِ باریک (کمتر از ۶۰٪ِ مرجع) = یک ستون با رنگ/گوشهٔ خودش؛ کارتِ پهن = «قابِ درون‌بخش» (ستونِ تک با رنگِ کارت) و محتوایش دوباره با همین قاعده چیده می‌شود.
* رنگِ زمینهٔ هر نوار از خودِ تصویر خوانده می‌شود (پرتکرارترین رنگِ ناحیه بی‌متن‌ها): درختِ mv2code گاهی گرادیانِ بزرگ را از دست می‌دهد و متنِ سفید روی زمینهٔ «سفید» می‌ماند.
* متن: «تیتر» اگر درشت‌تر از متنِ معمولیِ صفحه باشد، وگرنه «متن». اندازه، ضخامت و رنگ از درخت می‌آید؛ چینش از جای قرارگیری (نه از فیلدِ align که برای یک‌خطی‌ها معنا ندارد).
* دکمه ⇒ «دکمه»؛ ورودی‌ها ⇒ «فرمِ تماس» (برچسب = نوشتهٔ داخلِ ورودی)؛ جدول ⇒ «کدِ سفارشی» با یک ‹table› واقعی (متن‌ها escape می‌شوند)؛ عکس و نمادهای درشت ⇒ تکه‌ای از تصویرِ اصلی.
* سربرگ (nav/header) ⇒ سندِ سربرگ (نشان، دکمه، منو)، پابرگ (nav/footer) ⇒ سندِ پابرگ؛ اگر پروژهٔ هدف از قبل دارد ``chrome=False`` می‌دهیم و همه چیز در خودِ صفحه می‌آید.
* هر متن، دقیقاً همان رشته‌ای است که در درخت هست؛ متنِ انگلیسی در صفحهٔ راست‌به‌چپ با نشانهٔ ایزولهٔ LTR (U+2066 … U+2069) می‌آید تا نقطه‌گذاری جابه‌جا نشود.
"""
from __future__ import annotations

import html as _html
import re
from collections import Counter
from typing import Any, Optional

LEAF_ROLES = {"text", "button", "badge", "input", "image", "icon", "table", "control"}
BAND_GAP = 70            # فاصلهٔ عمودیِ (پیکسلِ صفحه با پهنای ۱۲۸۰) که دو نوار را جدا می‌کند
PANEL_RATIO = 0.60       # کارتی که پهن‌تر از این نسبتِ مرجع باشد «قاب» است
MAX_COLS = 4
MAX_NEST = 3
MAX_TEXT = 1900
LRI, PDI = "⁦", "⁩"
_RTL_CHARS = re.compile(r"[֐-ࣿיִ-﷿ﹰ-﻿]")
_LATIN = re.compile(r"[A-Za-z]")


# ───────────────────────────────────────────────────────────────── رنگ
def _hex_to_rgb(h: str):
    h = (h or "").lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    try:
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return (255, 255, 255)


def _rgb_to_hex(c) -> str:
    return "#%02x%02x%02x" % tuple(int(max(0, min(255, round(v)))) for v in c[:3])


def _lum(c) -> float:
    def f(v):
        v = v / 255.0
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = c[:3]
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)


def _contrast(a, b) -> float:
    """نسبتِ تباینِ WCAG بینِ دو رنگ (۱ تا ۲۱)."""
    la, lb = _lum(a), _lum(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def _dist(a, b) -> float:
    return float(max(abs(int(a[i]) - int(b[i])) for i in range(3)))


def _valid_hex(h) -> Optional[str]:
    return h.lower() if isinstance(h, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", h) else None


def _dominant(img, box, exclude=(), pad=6, min_px=40):
    """پرتکرارترین رنگِ ``box`` بی‌آن‌که جعبه‌های ``exclude`` (متن‌ها و عکس‌ها) حساب شوند. ⇒ (r,g,b) یا None."""
    if img is None:
        return None
    import numpy as np
    H, W = img.shape[:2]
    x0, y0 = max(0, int(box[0])), max(0, int(box[1]))
    x1, y1 = min(W, int(box[0] + box[2])), min(H, int(box[1] + box[3]))
    if x1 - x0 < 2 or y1 - y0 < 2:
        return None
    step = max(1, int(((x1 - x0) * (y1 - y0) / 60000) ** 0.5))
    crop = img[y0:y1:step, x0:x1:step]
    mask = np.ones(crop.shape[:2], bool)
    for b in exclude:
        ex0 = max(0, int((b[0] - pad - x0) / step))
        ey0 = max(0, int((b[1] - pad - y0) / step))
        ex1 = max(0, int((b[0] + b[2] + pad - x0) / step) + 1)
        ey1 = max(0, int((b[1] + b[3] + pad - y0) / step) + 1)
        if ex1 > 0 and ey1 > 0:
            mask[ey0:ey1, ex0:ex1] = False
    px = crop[mask]
    if len(px) < min_px:
        px = crop.reshape(-1, 3)
    q = (px // 8).astype(np.int32)
    keys = q[:, 0] * 1024 + q[:, 1] * 32 + q[:, 2]
    vals, counts = np.unique(keys, return_counts=True)
    k = vals[counts.argmax()]
    sel = px[keys == k]
    return tuple(float(v) for v in sel.mean(axis=0))


def _median_color(img, box, exclude=(), pad=6):
    """میانهٔ رنگِ ناحیه (برای زمینه‌های گرادیانی که «پرتکرارترین رنگ» را معنادار نمی‌کنند)."""
    if img is None:
        return None
    import numpy as np
    H, W = img.shape[:2]
    x0, y0 = max(0, int(box[0])), max(0, int(box[1]))
    x1, y1 = min(W, int(box[0] + box[2])), min(H, int(box[1] + box[3]))
    if x1 - x0 < 2 or y1 - y0 < 2:
        return None
    step = max(1, int(((x1 - x0) * (y1 - y0) / 60000) ** 0.5))
    crop = img[y0:y1:step, x0:x1:step]
    mask = np.ones(crop.shape[:2], bool)
    for b in exclude:
        ex0 = max(0, int((b[0] - pad - x0) / step))
        ey0 = max(0, int((b[1] - pad - y0) / step))
        ex1 = max(0, int((b[0] + b[2] + pad - x0) / step) + 1)
        ey1 = max(0, int((b[1] + b[3] + pad - y0) / step) + 1)
        if ex1 > 0 and ey1 > 0:
            mask[ey0:ey1, ex0:ex1] = False
    px = crop[mask]
    if len(px) < 40:
        px = crop.reshape(-1, 3)
    return tuple(float(v) for v in np.median(px, axis=0))


# ───────────────────────────────────────────────────────────────── ابزار هندسه
def _x1(b): return b[0] + b[2]
def _y1(b): return b[1] + b[3]
def _cx(b): return b[0] + b[2] / 2.0
def _cy(b): return b[1] + b[3] / 2.0


def _union(boxes):
    x0 = min(b[0] for b in boxes)
    y0 = min(b[1] for b in boxes)
    x1 = max(_x1(b) for b in boxes)
    y1 = max(_y1(b) for b in boxes)
    return [x0, y0, x1 - x0, y1 - y0]


def _overlap_y(a, b) -> float:
    return max(0.0, min(_y1(a), _y1(b)) - max(a[1], b[1]))


def _inside(inner, outer, tol=3) -> bool:
    return inner[0] >= outer[0] - tol and inner[1] >= outer[1] - tol and _x1(inner) <= _x1(outer) + tol and _y1(inner) <= _y1(outer) + tol


# ───────────────────────────────────────────────────────────────── متن
def _is_rtl_text(s: str) -> bool:
    return bool(_RTL_CHARS.search(s or ""))


def _wrap_ltr(s: str) -> str:
    """متنِ کاملاً انگلیسی در صفحهٔ راست‌به‌چپ: ایزوله می‌شود تا نقطه‌گذاری سرِ جایش بماند."""
    if s and _LATIN.search(s) and not _is_rtl_text(s):
        return LRI + s + PDI
    return s


def _clean_text(s: Any) -> str:
    s = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", str(s or ""))
    return re.sub(r"[ \t\r\n]+", " ", s).strip()[:MAX_TEXT]


def _html_p(text: str) -> str:
    return "<p>%s</p>" % _html.escape(_wrap_ltr(text), quote=False)


# ───────────────────────────────────────────────────────────────── جمع‌آوریِ برگ‌ها
class Item:
    """یک جزءِ قابلِ چیدن: برگ (متن، دکمه، عکس…) یا کارت (با برگ‌های داخلش)."""

    __slots__ = ("kind", "node", "box", "leaves", "children", "order")

    def __init__(self, kind, node, box, leaves=None, children=None):
        self.kind = kind          # leaf | card
        self.node = node
        self.box = list(box)
        self.leaves = leaves or []
        self.children = children or []


def _label_of(node) -> str:
    t = _clean_text(node.get("text"))
    if t:
        return t
    parts = [c for c in (node.get("children") or []) if c.get("role") == "text"]
    parts.sort(key=lambda c: (round(c["box"][1] / 10), -c["box"][0]))
    return _clean_text(" ".join(_clean_text(c.get("text")) for c in parts))


def _button_like(node) -> bool:
    """جعبه‌ای کوچک و رنگی که فقط یکی دو متن دارد (مثل «ورود / ثبت‌نام») یعنی دکمه."""
    if node.get("role") not in ("box", "card"):
        return False
    bx = node["box"]
    kids = node.get("children") or []
    texts = [c for c in kids if c.get("role") == "text"]
    others = [c for c in kids if c.get("role") not in ("text", "divider")]
    if not texts or len(texts) > 3 or others:
        return False
    bg = _valid_hex(node.get("background"))
    if not bg:
        return False
    return bx[3] <= 90 and bx[2] <= 420 and _lum(_hex_to_rgb(bg)) <= 0.8


def _collect(node, out_cards, leaves, dividers, nav_header, nav_footer, depth=0):
    """درخت ⇒ برگ‌ها (با فهرستِ کارت‌های پدرشان). ``nav`` سربرگ/پابرگ جدا می‌شود."""
    role = node.get("role")
    if role == "nav" and node.get("kind") in ("header",) and depth <= 1:
        nav_header.append(node)
        return
    if role == "nav" and node.get("kind") in ("footer",) and depth <= 1:
        nav_footer.append(node)
        return
    if role in ("button", "badge", "input", "table"):
        leaves.append(node)
        return
    if role == "text" or role == "control":
        leaves.append(node)
        return
    if role in ("image", "icon"):
        leaves.append(node)
        return
    if role == "divider":
        dividers.append(node)
        return
    if _button_like(node):
        fake = dict(node)
        fake["role"] = "button"
        fake["text"] = _label_of(node)
        leaves.append(fake)
        return
    for c in node.get("children") or []:
        _collect(c, out_cards, leaves, dividers, nav_header, nav_footer, depth + 1)
    if role in ("card", "section", "box") and node.get("children"):
        out_cards.append(node)


def _contained_leaves(card, leaves):
    cb = card["box"]
    return [lf for lf in leaves if _inside(lf["box"], cb) and lf is not card]


def _build_items(leaves, cards, page_w, _unused=None):
    """برگ‌ها و کارت‌ها ⇒ فهرستِ Item در یک سطح: کارتِ بیرونیِ هر برگ برنده است؛ کارتِ بی‌محتوا نادیده."""
    taken = set()
    items = []
    # بزرگ‌ترین کارت اول: هر برگ به بیرونی‌ترین کارتِ «معنادار» می‌رسد
    for card in sorted(cards, key=lambda n: -(n["box"][2] * n["box"][3])):
        inside = [lf for lf in _contained_leaves(card, leaves) if id(lf) not in taken]
        if len(inside) < 1:
            continue
        # کارتِ فقط‌-نماد/تصویر (بدونِ متن) = «کاشیِ تصویر»؛ خودش تصویر می‌شود
        if all(lf.get("role") in ("icon", "image") for lf in inside) and card["box"][2] >= 0.05 * page_w and card["box"][2] * card["box"][3] < 0.35 * page_w * page_w:
            for lf in inside:
                taken.add(id(lf))
            fake = {"role": "image", "box": card["box"], "tile": True, "radius": card.get("radius"), "id": card.get("id")}
            items.append(Item("leaf", fake, card["box"]))
            continue
        # کارتی که همهٔ محتوایش را کارتِ بزرگ‌تری گرفته، یا خیلی کوچک و تک‌متنی است، خودش یک کارت نیست
        for lf in inside:
            taken.add(id(lf))
        items.append(Item("card", card, card["box"], leaves=inside))
    for lf in leaves:
        if id(lf) not in taken:
            items.append(Item("leaf", lf, lf["box"]))
    return items


# ───────────────────────────────────────────────────────────────── نقشهبردار
class Mapper:
    def __init__(self, tree: dict, image=None, options: Optional[dict] = None):
        self.tree = tree
        self.img = image
        self.opt = options or {}
        self.W = int(tree.get("width") or tree["box"][2])
        self.H = int(tree.get("height") or tree["box"][3])
        self.crops: list = []
        self.warnings: list[str] = []
        self.stats = Counter()
        self._ids = 0
        self.scale = max(0.5, min(2.0, self.W / 1280.0))
        self._prepare_typography()
        self.content_w = _content_width(self)         # پهنای محتوا در سایت‌ساز (همان که پوسته می‌گیرد)

    # ── تایپوگرافیِ صفحه: اندازهٔ معمولی و فهرستِ اندازه‌ها
    def _prepare_typography(self):
        sizes = []
        texts = []

        def walk(n):
            if n.get("role") == "text" and n.get("font"):
                t = _clean_text(n.get("text"))
                if t:
                    texts.append(n)
                    sizes.extend([float(n["font"].get("size") or 16)] * min(40, max(1, len(t))))
            for c in n.get("children") or []:
                walk(c)
        walk(self.tree)
        sizes.sort()
        self.body = sizes[len(sizes) // 2] if sizes else 16.0
        self.body = max(11.0, min(28.0, self.body))
        self.texts = texts
        self.h1_taken = False
        self.forms: list = []
        self.nest = 0           # سایت‌ساز بیش از ۸ سطحِ تودرتو نمی‌پذیرد ⇒ «ستون‌ها» حداکثر سه‌تا در هم
        self.all_cards: list = []

    def new_crop(self, box, kind, alt="", radius=0):
        key = "c%d" % (len(self.crops) + 1)
        b = [max(0, int(round(box[0]))), max(0, int(round(box[1]))), max(2, int(round(box[2]))), max(2, int(round(box[3])))]
        self.crops.append({"key": key, "box": b, "kind": kind, "alt": alt, "radius": radius})
        return "crop:" + key

    def block(self, btype, children=None, style=None, **props):
        from apps.projects.builder.clean import new_block
        self.stats[btype] += 1
        return new_block(btype, children=children, style=style or {}, **props)

    # ── چینش
    def _align_of(self, box, ref) -> str:
        """چینشِ فیزیکی در صفحهٔ راست‌به‌چپِ سایت‌ساز: چپ ⇒ end، راست ⇒ start."""
        rc = _cx(ref)
        c = _cx(box)
        tol = max(8.0, 0.07 * ref[2])
        if abs(c - rc) <= tol:
            return "center"
        return "start" if c > rc else "end"

    # ── یک برگِ متن ⇒ تیتر یا متن
    def text_block(self, node, ref, heading_ok=True):
        text = _clean_text(node.get("text"))
        if not text:
            return None
        font = node.get("font") or {}
        size = float(font.get("size") or self.body)
        weight = int(font.get("weight") or 400)
        color = _valid_hex(font.get("color"))
        lines = node.get("lines") or []
        multi = len(lines) >= 2 or len(text) > 110
        if len(lines) >= 2 and node.get("align") in ("left", "right", "center", "justify"):
            a = {"left": "end", "right": "start", "center": "center", "justify": "start"}[node["align"]]
        else:
            a = self._align_of(node["box"], ref)
        st = {"align": a}
        if color:
            st["color"] = color
        st["size"] = int(max(12, min(96, round(size))))
        ratio = size / self.body
        numeric = bool(re.fullmatch(r"[\d\u06F0-\u06F9\u0660-\u0669\s,.+%\u066A\u066C\u060C/:\-\u2013$\u20ac]+", text))
        is_heading = heading_ok and not numeric and not multi and len(text) <= 110 and (ratio >= 1.8 or (ratio >= 1.3 and weight >= 500) or (ratio >= 1.15 and weight >= 700 and len(text) <= 60))
        if is_heading:
            level = 3
            if ratio >= 2.2 or size >= 2.2 * self.body:
                level = 2
            if not self.h1_taken and ratio >= 2.2:
                level, self.h1_taken = 1, True
            if weight <= 400:
                st["weight"] = "400"
            return self.block("heading", text=_wrap_ltr(text), level=level, style={"d": st})
        if weight >= 700:
            st["weight"] = "800"
        elif weight >= 500:
            st["weight"] = "600"
        return self.block("text", html=_html_p(text), style={"d": st})

    # ── برگ ⇒ بلوک(ها)
    def leaf_blocks(self, node, ref) -> list:
        role = node.get("role")
        if role == "text":
            b = self.text_block(node, ref)
            return [b] if b else []
        if role == "badge":
            node = dict(node)
            node.setdefault("font", {"size": self.body * 0.9, "weight": 600})
            t = _clean_text(node.get("text") or _label_of(node))
            if not t:
                return []
            kid = next((c for c in node.get("children") or [] if c.get("role") == "text"), None)
            tn = dict(kid) if kid else {"font": {"size": self.body * 0.95, "weight": 600}}
            tn.update(text=t, box=node["box"], lines=[])
            b = self.text_block(tn, ref, heading_ok=False)
            return [b] if b else []
        if role == "button":
            label = _label_of(node)
            if not label:
                return []
            bg = _valid_hex(node.get("background"))
            variant = "filled"
            if bg is None or _lum(_hex_to_rgb(bg)) > 0.92 or (node.get("gradient") is None and bg and _dist(_hex_to_rgb(bg), (255, 255, 255)) < 14):
                variant = "outline"
            h = node["box"][3]
            size = "lg" if h >= 56 else ("sm" if h <= 34 else "md")
            return [self.block("button", text=label[:80], link="#", variant=variant, btn_size=size, style={"d": {"align": self._align_of(node["box"], ref)}})]
        if role in ("image", "icon"):
            w = node["box"][2]
            if w < 0.06 * self.W and not node.get("tile"):
                self.stats["icons_skipped"] += 1        # گلیف‌های ریز (نقطهٔ فهرست، آیکنِ کنارِ متن) تصویر نمی‌شوند
                return []
            if w < 8 or node["box"][3] < 8:
                return []
            src = self.new_crop(node["box"], "tile" if node.get("tile") else role, radius=int(node.get("radius") or 0))
            width = int(max(10, min(100, round(100.0 * w / max(1.0, ref[2])))))
            st = {"align": self._align_of(node["box"], ref), "width": width}
            rad = int(node.get("radius") or 0)
            if rad:
                st["radius"] = max(0, min(80, rad))
            self.stats["images"] += 1
            return [self.block("image", src=src, alt="", style={"d": st})]
        if role == "table":
            b = self.table_block(node)
            return [b] if b else []
        if role == "input":
            return []          # فرم‌ها جدا (form_blocks) ساخته می‌شوند
        if role == "control":
            return []
        return []

    # ── جدول ⇒ کدِ سفارشی (یک ‹table› واقعی با متنِ escape‌شده)
    def table_block(self, node):
        cells = [c for c in (node.get("children") or []) if c.get("role") in ("text", "badge", "button", "box", "card")]
        texts = []
        for c in cells:
            t = _label_of(c) if c.get("role") != "text" else _clean_text(c.get("text"))
            if t:
                texts.append((c["box"], t))
        if len(texts) < 2:
            return None
        texts.sort(key=lambda p: _cy(p[0]))
        rows, cur = [], [texts[0]]
        for p in texts[1:]:
            if abs(_cy(p[0]) - _cy(cur[0][0])) <= max(8.0, 0.5 * cur[0][0][3]):
                cur.append(p)
            else:
                rows.append(cur)
                cur = [p]
        rows.append(cur)
        out = ['<table style="width:100%;border-collapse:collapse">']
        for i, row in enumerate(rows):
            row.sort(key=lambda p: -_cx(p[0]))
            tag = "th" if i == 0 and len(rows) > 1 else "td"
            out.append("<tr>" + "".join('<%s style="padding:8px 10px;border-bottom:1px solid #e5e7eb;text-align:start">%s</%s>' % (tag, _html.escape(_wrap_ltr(t)), tag) for _b, t in row) + "</tr>")
        out.append("</table>")
        self.stats["tables"] += 1
        return self.block("custom_html", code="".join(out))

    # ── ورودی‌ها + دکمهٔ کنارشان ⇒ فرمِ تماس
    def form_block(self, inputs, buttons, title=None, text=None):
        fields = []
        for n in sorted(inputs, key=lambda n: (round(n["box"][1] / 12), -n["box"][0])):
            label = _clean_text(n.get("text")) or "فیلد %d" % (len(fields) + 1)
            low = label.lower()
            kind = n.get("kind")
            typ = "textarea" if kind == "textarea" else "text"
            if re.search(r"@|email|ایمیل|پست الکترونیک", low):
                typ = "email"
            elif re.search(r"تلفن|موبایل|شماره|phone|tel|mobile", low):
                typ = "tel"
            fields.append({"label": label[:60], "type": typ, "required": False})
        btn = _label_of(buttons[0]) if buttons else "فرستادن"
        self.stats["forms"] += 1
        return self.block("contact_form", title=_clean_text(title or "")[:120], text=_clean_text(text or "")[:400], fields=fields[:12], button=btn[:60] or "فرستادن")

    # ── یک واحد (برگ یا کارت) ⇒ بلوک(ها)
    def unit_blocks(self, it: Item, ref) -> list:
        if it.kind == "leaf":
            return self.leaf_blocks(it.node, ref)
        if self.nest >= MAX_NEST:
            return self.card_flat(it)                      # عمقِ مجاز تمام شد: محتوای کارت بی‌قاب می‌آید
        self.nest += 1
        try:
            col = self.card_column(it)
        finally:
            self.nest -= 1
        if col is None:
            return []
        if it.box[2] >= PANEL_RATIO * ref[2] and len(it.leaves) >= 3:
            self.stats["panels"] += 1
        return [self.block("columns", children=[col], count=1, ratio="equal", gap=0, valign="start")]

    def card_flat(self, it: Item) -> list:
        area = it.box[2] * it.box[3]
        nested = [c for c in self.all_cards if c is not it.node and _inside(c["box"], it.box, 3) and c["box"][2] * c["box"][3] < 0.97 * area]
        return self.items_blocks(_build_items(it.leaves, nested, self.W), it.box)

    def card_column(self, it: Item):
        """کارت ⇒ یک «ستون» با رنگ/گوشه/سایه‌اش و فاصلهٔ داخلیِ سنجیده از چیدمانِ واقعیِ داخلش؛ کارت‌های تودرتو دوباره کارت می‌شوند."""
        area = it.box[2] * it.box[3]
        nested = [c for c in self.all_cards if c is not it.node and _inside(c["box"], it.box, 3) and c["box"][2] * c["box"][3] < 0.97 * area]
        inner_items = [x for x in _build_items(it.leaves, nested, self.W) if x.box[2] > 1 and x.box[3] > 1]
        inner = self.items_blocks(inner_items, it.box)
        if not inner:
            return None
        return self.block("column", children=inner, style={"d": self.card_style(it.node, it.box, inner_items)})

    def card_style(self, card, box, inner_items=None) -> dict:
        st: dict = {}
        bg = _valid_hex(card.get("background")) if card else None
        if card and card.get("gradient"):
            g = card["gradient"]
            if _valid_hex(g.get("from")) and _valid_hex(g.get("to")):
                bg = _rgb_to_hex(tuple((a + b) / 2 for a, b in zip(_hex_to_rgb(g["from"]), _hex_to_rgb(g["to"]))))
        if bg:
            st["bg"] = bg
        rad = card.get("radius") if card else None
        if rad:
            st["radius"] = int(max(0, min(80, round(float(rad)))))
        bd = (card or {}).get("border") or {}
        wd = {s: (bd.get(s) or {}).get("width", 0) for s in ("top", "right", "bottom", "left")} if bd else {}
        if wd and max(wd.values()) >= 1:
            side = max(wd, key=lambda k: wd[k])
            c = _valid_hex((bd.get(side) or {}).get("color"))
            if c:
                st["border"] = c
                st["bw"] = int(max(1, min(10, round(max(wd.values())))))
        sh = (card or {}).get("shadow")
        if sh:
            blur = float(sh.get("blur") or 0)
            st["shadow"] = "strong" if blur >= 30 else ("medium" if blur >= 14 else "soft")
        py, px = 16 * self.scale, 14 * self.scale
        if inner_items:
            top = min(x.box[1] for x in inner_items) - box[1]
            bot = _y1(box) - max(_y1(x.box) for x in inner_items)
            py = (max(0.0, top) + max(0.0, bot)) / 2.0
            wide = [x for x in inner_items if x.box[2] >= 0.9 * box[2]]
            body = [x for x in inner_items if x not in wide] or inner_items
            left = min(x.box[0] for x in body) - box[0]
            right = _x1(box) - max(_x1(x.box) for x in body)
            px = max(0.0, min(left, right))
        st["py"] = int(max(0, min(60, round(py))))
        st["px"] = int(max(0, min(48, round(px))))
        return st

    # ── فهرستِ Item ⇒ بلوک‌ها (ورودی‌ها فرمِ تماس می‌شوند؛ بقیه با برشِ XY)
    def items_blocks(self, items, ref) -> list:
        items = [it for it in items if it.box[2] > 1 and it.box[3] > 1]
        if not items:
            return []
        items = self.drop_decoration(items)
        items = self.drop_glyphs(items)
        if not items:
            return []
        inputs = [it for it in items if it.kind == "leaf" and it.node.get("role") == "input"]
        rest = [it for it in items if it not in inputs]
        if inputs:
            first_y = min(i.box[1] for i in inputs)
            buttons = [it for it in rest if it.kind == "leaf" and it.node.get("role") == "button" and it.box[1] >= first_y - 20]
            above = sorted((it for it in rest if it.kind == "leaf" and it.node.get("role") == "text" and _y1(it.box) <= first_y + 6), key=lambda it: it.box[1])
            title_n = above[0] if above else None
            text_n = above[1] if len(above) > 1 else None
            used = {id(x) for x in (title_n, text_n) if x}
            if buttons:
                used.add(id(buttons[0]))
            rest = [it for it in rest if id(it) not in used]
            self.forms.append(self.form_block([i.node for i in inputs], [buttons[0].node] if buttons else [],
                                              _clean_text(title_n.node.get("text")) if title_n else "", _clean_text(text_n.node.get("text")) if text_n else ""))
        return self.xy(rest, ref)

    def drop_glyphs(self, items):
        """گلیف‌های ریز (نقطهٔ فهرست، آیکنِ کنارِ متن) بلوک نمی‌شوند و چیدمان را هم نباید بشکنند."""
        out = []
        for it in items:
            if it.kind == "leaf" and it.node.get("role") in ("icon", "image") and not it.node.get("tile") and it.box[2] < 0.06 * self.W:
                self.stats["icons_skipped"] += 1
                continue
            out.append(it)
        return out

    def drop_decoration(self, items):
        """سایه/درخششِ زیرِ دکمه و نمادِ روی دکمه تصویر نیستند."""
        btns = [it.box for it in items if it.kind == "leaf" and it.node.get("role") == "button"]
        out = []
        for it in items:
            if it.kind == "leaf" and it.node.get("role") in ("image", "icon") and btns:
                nb = it.box
                area = max(1.0, nb[2] * nb[3])
                hit = max((_overlap_x(nb, b) * _overlap_y(nb, b) for b in btns), default=0.0)
                glow = any(_overlap_x(nb, b) >= 0.6 * min(nb[2], b[2]) and -4 <= nb[1] - _y1(b) <= 14 and nb[3] <= 60 for b in btns)
                if hit >= 0.3 * area or glow:
                    self.stats["decor_skipped"] += 1
                    continue
            out.append(it)
        return out

    # ── برشِ XY: بزرگ‌ترین فاصلهٔ خالی (افقی یا عمودی) تعیین می‌کند چیدمان «ستون‌ها» است یا «زیرِ هم»
    @staticmethod
    def _gaps(items, axis):
        spans = sorted((it.box[axis], it.box[axis] + it.box[axis + 2]) for it in items)
        out, reach = [], spans[0][1]
        for s, e in spans[1:]:
            if s > reach:
                out.append((s - reach, (s + reach) / 2.0))
            reach = max(reach, e)
        return out

    def xy(self, items, ref, depth=0) -> list:
        if not items:
            return []
        if len(items) == 1:
            return self.unit_blocks(items[0], ref)
        if depth > 60 or len(items) > 500:
            out: list = []
            for it in sorted(items, key=lambda i: (i.box[1], -i.box[0])):
                out.extend(self.unit_blocks(it, ref))
            return out
        vg = self._gaps(items, 0)
        hg = self._gaps(items, 1)
        min_v = max(12.0 * self.scale, 0.01 * ref[2])
        vbest = max((g for g, _ in vg), default=0.0)
        hbest = max((g for g, _ in hg), default=0.0)
        if self.nest < MAX_NEST and vg and vbest >= min_v and vbest >= 0.9 * hbest:
            cuts = sorted((g for g in vg if g[0] >= max(min_v, 0.15 * vbest)), key=lambda g: -g[0])[:MAX_COLS - 1]
            xs = sorted(c for _g, c in cuts)
            groups: list = [[] for _ in range(len(xs) + 1)]
            for it in items:
                k = sum(1 for x in xs if _cx(it.box) > x)
                groups[k].append(it)
            groups = [g for g in groups if g]
            if len(groups) >= 2:
                return self.columns_block(groups, ref)
        if hg and hbest >= 5.0 * self.scale:
            cut = max(hg, key=lambda g: g[0])[1]
            top = [it for it in items if _cy(it.box) <= cut]
            bot = [it for it in items if _cy(it.box) > cut]
            if top and bot:
                return self.xy(top, ref, depth + 1) + self.xy(bot, ref, depth + 1)
        out = []
        for it in sorted(items, key=lambda i: (i.box[1], -i.box[0])):
            out.extend(self.unit_blocks(it, ref))
        return out

    def compact_style(self, boxes, widths, gap, ref):
        """ردیفِ جمع‌وجورِ میانه‌چین (دو دکمهٔ کنارِ هم، چند آمار، چند ویژگیِ کوتاه): ستون‌های مساوی همهٔ پهنا را پر می‌کردند و عنصرها از هم دور می‌افتادند.

        فاصلهٔ داخلیِ افقی (px؛ سقفِ سایت‌ساز ۱۲۰) ستون‌ها را تنگ می‌کند؛ برای **دو** گروه که با ۱۲۰ هم کافی نیست، دو «ستونِ خالی» دو طرف می‌گذاریم
        (۴ ستون: خالی، الف، ب، خالی ⇒ ردیف فقط نیمهٔ میانیِ بخش را می‌گیرد؛ ستون‌های خالی در تبلت و گوشی پنهان‌اند).
        در تبلت و گوشی فاصلهٔ داخلی صفر است (ستون‌ها آن‌جا زیرِ هم‌اند). ⇒ (style، spacers، gap) یا None."""
        if ref is None or len(boxes) < 2:
            return None
        n = len(boxes)
        union = _union(boxes)
        avail = min(float(ref[2]), float(self.content_w))
        if self.nest > 0:
            avail -= 2 * 24 * self.scale                 # فاصلهٔ داخلیِ کارت/قاب
        c = max(60.0, max(widths))
        g = min(float(gap), 32.0)         # فاصلهٔ ستون‌ها در گوشی فاصلهٔ عمودیِ بینِ ردیف‌هاست؛ فاصلهٔ افقیِ بزرگ آن‌جا زشت می‌شود
        w = c + (gap - g)                 # با فاصلهٔ کمتر، ستون‌ها به‌اندازهٔ فرقش پهن‌تر می‌شوند تا مرکزِ ستون‌ها همان‌جای تصویر بماند
        total = n * w + (n - 1) * g
        if (avail - total) / 2.0 < 24 * self.scale or total > 0.72 * avail:
            return None
        if abs(_cx(union) - _cx(ref)) > 0.08 * ref[2]:       # ردیفِ میانه‌چین نیست (مثلاً کنارِ یک لبه) ⇒ دست نزن
            return None
        spacers = False
        px = (avail - total) / 2.0
        if n == 2:
            px4 = (avail - (4 * w + 3 * g)) / 2.0           # چهار ستونِ هم‌پهنا که هر کدام w است
            if px4 >= 0:
                spacers, px = True, px4
        px = int(max(0, min(120, round(px))))
        return {"d": {"px": px}, "t": {"px": 0}, "p": {"px": 0}}, spacers, int(round(g))

    def columns_block(self, groups, ref=None) -> list:
        groups = sorted(groups, key=lambda g: -_cx(_union([i.box for i in g])))          # راست‌به‌چپ مثلِ سایت‌ساز
        kids = []
        widths = []
        boxes = []
        self.nest += 1
        try:
            for g in groups:
                gb = _union([i.box for i in g])
                boxes.append(gb)
                widths.append(gb[2])
                col = self.card_column(g[0]) if (len(g) == 1 and g[0].kind == "card") else None
                if col is not None:
                    kids.append(col)
                else:
                    kids.append(self.block("column", children=self.xy(g, gb, 1), style={"d": {}}))
        finally:
            self.nest -= 1
        keep = [i for i, k in enumerate(kids) if k.get("children")]
        if len(keep) < len(kids):                      # ستونِ خالی (چیزی از آن بلوک نشد) نمی‌ماند
            kids = [kids[i] for i in keep]
            widths = [widths[i] for i in keep]
            boxes = [boxes[i] for i in keep]
        if not kids:
            return []
        if len(kids) == 1:
            return list(kids[0]["children"])
        ratio = "equal"
        if len(widths) == 2 and max(widths) > 1.6 * min(widths):
            ratio = "wide-first" if widths[0] > widths[1] else "wide-last"
        srt = sorted(boxes, key=lambda b: b[0])
        gaps = [srt[i + 1][0] - _x1(srt[i]) for i in range(len(srt) - 1)]
        gap = int(max(0, min(80, round(sum(gaps) / len(gaps))))) if gaps else 24
        tops = [b[1] for b in boxes]
        valign = "center" if max(tops) - min(tops) > 0.25 * max(b[3] for b in boxes) else "start"
        self.stats["columns"] += 1
        compact = self.compact_style(boxes, widths, gap, ref) if ratio == "equal" else None
        style = None
        if compact:
            style, spacers, gap = compact
            self.stats["compact_rows"] += 1
            if spacers:
                def spacer():
                    # ستونِ «خالی» یک فاصلهٔ ۴ پیکسلی دارد (نه خالیِ واقعی: ویرایشگر در ستونِ خالی نوشتهٔ راهنما نشان می‌دهد)
                    return self.block("column", children=[self.block("spacer", height=4)], style={"d": {"hide_tablet": True, "hide_phone": True}})
                kids = [spacer()] + kids + [spacer()]
        return [self.block("columns", children=kids, count=len(kids), ratio=ratio, gap=gap, valign=valign, style=style)]

    # ── نوار ⇒ [بخش، فرم‌ها…]
    def section_for(self, band_items, dividers, prev_end, next_start, page_bg) -> list:
        items = [it for it in band_items if it.box[2] > 1]
        if not items:
            return []
        bb = _union([it.box for it in items])
        inner_div = [d for d in dividers if bb[1] + 4 < d["box"][1] < _y1(bb) - 4 and d["box"][2] >= 0.25 * bb[2] and d["box"][3] <= 5]
        div_items = [Item("leaf", {"role": "divider", "box": d["box"], "background": d.get("background")}, d["box"]) for d in inner_div]
        ref = [0, bb[1], self.W, bb[3]]
        style: dict = {}
        excl = [it.box for it in items]
        y0 = max(0, bb[1] - int(24 * self.scale))
        y1 = min(self.H, _y1(bb) + int(24 * self.scale))
        edge = _dominant(self.img, [0, y0, max(4, 0.025 * self.W), y1 - y0], excl)
        page_rgb = _hex_to_rgb(page_bg)
        inset_color = None
        if edge is not None and _dist(edge, page_rgb) > 14:
            style["bg"] = _rgb_to_hex(edge)
        elif not (len(items) == 1 and items[0].kind == "card"):
            # قابِ درون‌صفحه (مثل بخشِ قهرمانِ گوشه‌گرد): هر دو کنارهٔ میانیِ نوار رنگی و هم‌رنگ‌اند، ولی لبهٔ صفحه نه
            left = _dominant(self.img, [0.13 * self.W, y0, 0.07 * self.W, y1 - y0], excl)
            right = _dominant(self.img, [0.80 * self.W, y0, 0.07 * self.W, y1 - y0], excl)
            if left is not None and right is not None and _dist(left, page_rgb) > 22 and _dist(right, page_rgb) > 22 and _dist(left, right) <= 60:
                mid = _median_color(self.img, [0.13 * self.W, y0, 0.74 * self.W, y1 - y0], excl)
                inset_color = _rgb_to_hex(mid if mid is not None else left)
        mark = len(self.forms)
        self.nest = 1 if inset_color else 0
        try:
            blocks = self.items_blocks(items + div_items, ref)
        finally:
            self.nest = 0
        forms = self.forms[mark:]
        del self.forms[mark:]
        if not blocks and not forms:
            return []
        pad_top = bb[1] - (prev_end if prev_end is not None else 0)
        pad_bot = (next_start if next_start is not None else self.H) - _y1(bb)
        gap_pad = min(pad_top, pad_bot) if prev_end is not None else pad_bot
        style["py"] = int(max(16, min(110, round(gap_pad / 2.0))))
        if inset_color and blocks:
            col = self.block("column", children=blocks, style={"d": {"bg": inset_color, "radius": 28, "py": max(24, int(36 * self.scale)), "px": max(12, int(24 * self.scale))}})
            blocks = [self.block("columns", children=[col], count=1, ratio="equal", gap=0, valign="start")]
            self.stats["panels"] += 1
        out = []
        if blocks:
            out.append(self.block("section", children=blocks, full=bool(style.get("bg")), style={"d": style}))
        out.extend(forms)
        return out

    # ── سربرگ: نشان + دکمه + منو
    def header_parts(self, navs):
        brand = None
        button = None
        menu = []
        logo_crop = None
        for nav in navs:
            leaves, cards, divs, a, b = [], [], [], [], []
            for c in nav.get("children") or []:
                _collect(c, cards, leaves, divs, a, b, depth=2)
            texts = [lf for lf in leaves if lf.get("role") in ("text", "badge")]
            btns = [lf for lf in leaves if lf.get("role") == "button"]
            icons = [lf for lf in leaves if lf.get("role") in ("icon", "image")]
            extra_menu = []
            if btns:
                def _bg_lum(n):
                    bg = _valid_hex(n.get("background"))
                    return _lum(_hex_to_rgb(bg)) if bg else 1.0
                primary = min(btns, key=_bg_lum)
                button = _label_of(primary)
                extra_menu = [b for b in btns if b is not primary]
                inside = {id(c) for bn in btns for c in (bn.get("children") or [])}
                texts = [t for t in texts if id(t) not in inside and not any(_inside(t["box"], bn["box"]) for bn in btns)]
            if texts:
                biggest = max(texts, key=lambda n: float((n.get("font") or {}).get("size") or 0) * (1 + 0.1 * (int((n.get("font") or {}).get("weight") or 400) >= 600)))
                bs = float((biggest.get("font") or {}).get("size") or 0)
                brand_candidates = [t for t in texts if float((t.get("font") or {}).get("size") or 0) >= bs - 0.5]
                # نشان کنارِ گوشهٔ آغازِ صفحه است؛ نزدیک‌ترین به لبه
                if self.tree.get("direction") == "rtl":
                    brand = max(brand_candidates, key=lambda n: _cx(n["box"]))
                else:
                    brand = min(brand_candidates, key=lambda n: _cx(n["box"]))
                menu_nodes = [t for t in texts if t is not brand]
                for eb in extra_menu:
                    menu_nodes.append({"box": eb["box"], "text": _label_of(eb)})
                menu_nodes.sort(key=lambda n: -_cx(n["box"]))
                menu = [_clean_text(n.get("text")) for n in menu_nodes if _clean_text(n.get("text"))]
            if icons:
                ic = max(icons, key=lambda n: n["box"][2] * n["box"][3])
                if ic["box"][2] >= 14 and ic["box"][3] >= 14 and (ic["box"][2] <= 0.2 * self.W):
                    # نشان = نمادِ کنارِ نامِ برند
                    if brand is None or abs(_cx(ic["box"]) - _cx(brand["box"])) <= 160:
                        logo_crop = ic["box"]
        return {"brand": _clean_text(brand.get("text")) if brand else "", "button": button, "menu": menu, "logo": logo_crop,
                "bg": next((_valid_hex(n.get("background")) for n in navs if n.get("background")), None)}


def _overlap_x(a, b) -> float:
    return max(0.0, min(_x1(a), _x1(b)) - max(a[0], b[0]))


# ───────────────────────────────────────────────────────────────── پوسته
def _content_width(m: Mapper) -> float:
    xs0, xs1 = [], []
    for n in m.texts:
        xs0.append(n["box"][0])
        xs1.append(_x1(n["box"]))
    if not xs0:
        return 1140.0
    xs0.sort()
    xs1.sort()
    lo = xs0[int(0.04 * (len(xs0) - 1))]
    hi = xs1[int(0.96 * (len(xs1) - 1))]
    return max(600.0, hi - lo + 40)


def _theme_for(m: Mapper, page_bg: str, tree: dict) -> dict:
    """رنگ‌های پوسته از درخت: زمینه، متنِ پرتکرار، رنگِ اصلی (پرتکرارترین دکمهٔ پُر)، روی-رنگِ-اصلی، سطح."""
    from apps.projects.builder import theme as theme_mod
    text_cols: Counter = Counter()
    for n in m.texts:
        c = _valid_hex((n.get("font") or {}).get("color"))
        if c:
            text_cols[c] += len(_clean_text(n.get("text")))
    btn_bg: Counter = Counter()
    btn_fg: dict = {}
    surf: Counter = Counter()

    def walk(n):
        if n.get("role") == "button":
            bg = _valid_hex(n.get("background"))
            if n.get("gradient"):
                bg = _valid_hex(n["gradient"].get("to")) or bg
            if bg and _lum(_hex_to_rgb(bg)) < 0.8:
                btn_bg[bg] += 1
                kid = next((c for c in n.get("children") or [] if c.get("role") == "text"), None)
                if kid:
                    btn_fg.setdefault(bg, _valid_hex((kid.get("font") or {}).get("color")))
        if n.get("role") == "card" and _valid_hex(n.get("background")):
            surf[_valid_hex(n["background"])] += 1
        for c in n.get("children") or []:
            walk(c)
    walk(tree)
    theme = theme_mod.default_theme()
    colors = theme["colors"]
    colors["bg"] = page_bg
    bg_dark = _lum(_hex_to_rgb(page_bg)) < 0.3
    # رنگِ متنِ پوسته = پرتکرارترین رنگِ متن که روی زمینهٔ صفحه خوانا باشد (تباین ≥ ۴٫۵)؛ رنگ‌های نزدیک (لبهٔ نرم‌شدهٔ حرف‌ها) یکی شمرده می‌شوند.
    # متنِ روشنِ پابرگِ تیره نباید «رنگِ متنِ سایت» شود (روی زمینهٔ روشنِ صفحه ناخوانا می‌شد).
    page_rgb = _hex_to_rgb(page_bg)
    groups: dict = {}
    for c, n in text_cols.items():
        g = groups.setdefault(tuple(int(v) // 24 for v in _hex_to_rgb(c)), Counter())
        g[c] += n
    for g in sorted(groups.values(), key=lambda g: -sum(g.values())):
        c = g.most_common(1)[0][0]
        if _contrast(_hex_to_rgb(c), page_rgb) >= 4.5:
            colors["text"] = c
            break
    else:
        colors["text"] = "#f1f5f9" if bg_dark else "#111827"
    colors["text2"] = colors["text"]
    colors["muted"] = _rgb_to_hex(tuple((a + b) / 2 for a, b in zip(_hex_to_rgb(colors["text"]), _hex_to_rgb(page_bg))))
    colors["line"] = _rgb_to_hex(tuple(a * 0.88 + b * 0.12 for a, b in zip(_hex_to_rgb(page_bg), _hex_to_rgb(colors["text"]))))
    if btn_bg:
        prim = btn_bg.most_common(1)[0][0]
        colors["primary"] = prim
        colors["on_primary"] = btn_fg.get(prim) or ("#ffffff" if _lum(_hex_to_rgb(prim)) < 0.5 else "#111827")
    elif text_cols:
        colors["primary"] = text_cols.most_common(1)[0][0]
    if surf:
        colors["surface"] = surf.most_common(1)[0][0]
    else:
        colors["surface"] = _rgb_to_hex(tuple(min(255, c + 14) if bg_dark else 255 for c in _hex_to_rgb(page_bg)))
    theme["font_body"] = theme["font_head"] = "vazirmatn"
    theme["width"] = int(max(800, min(1600, round(_content_width(m)))))
    return theme_mod.clean_theme(theme)


# ───────────────────────────────────────────────────────────────── نوارها
def _bands(items, scale):
    items = sorted(items, key=lambda it: it.box[1])
    bands, cur, cur_end = [], [], None
    gap = BAND_GAP * scale
    for it in items:
        if cur and it.box[1] - cur_end >= gap:
            bands.append(cur)
            cur, cur_end = [], None
        cur.append(it)
        cur_end = max(cur_end if cur_end is not None else 0, _y1(it.box))
    if cur:
        bands.append(cur)
    return bands


def _fallback_section(m: Mapper, leaves) -> Optional[dict]:
    blocks = []
    for lf in sorted(leaves, key=lambda n: (n["box"][1], -n["box"][0])):
        if lf.get("role") in ("text", "button", "badge"):
            blocks.extend(m.leaf_blocks(lf, [0, 0, m.W, m.H]))
    return m.block("section", children=blocks, style={"d": {"py": 32}}) if blocks else None


def _count(blocks) -> int:
    n = 0
    for b in blocks or []:
        n += 1 + _count(b.get("children"))
    return n


def _trim(doc: dict, limit: int, warnings: list) -> None:
    """سایت‌ساز بیش از ۸۰۰ بلوک نمی‌پذیرد؛ از آخرِ صفحه کم می‌کنیم و می‌گوییم."""
    while _count(doc["blocks"]) > limit and len(doc["blocks"]) > 1:
        doc["blocks"].pop()
        if not any("بخش‌های آخر" in w for w in warnings):
            warnings.append("صفحه بیش از اندازه بلوک داشت؛ بخش‌های آخرِ آن در پیش‌نویس نیامد.")


def map_tree(tree: dict, image=None, options: Optional[dict] = None, chrome: bool = True) -> dict:
    """درخت ⇒ ``{"theme","header","page","footer","menu","crops","stats","warnings","site_title","page_bg"}`` (هنوز تمیزِ سایت‌ساز نشده؛ ``clean_docs`` را صدا بزنید).

    ``chrome=False``: سربرگ و پابرگ هم داخلِ بدنهٔ صفحه می‌آیند (برای پروژه‌ای که از قبل سربرگ و پابرگ دارد)."""
    m = Mapper(tree, image, options)
    page_bg = _valid_hex(tree.get("background")) or "#ffffff"
    leaves: list = []
    cards: list = []
    divs: list = []
    nav_header: list = []
    nav_footer: list = []
    for c in tree.get("children") or []:
        _collect(c, cards, leaves, divs, nav_header, nav_footer)
    if not chrome:
        for nav in nav_header + nav_footer:
            for c in nav.get("children") or []:
                _collect(c, cards, leaves, divs, [], [], depth=2)
        nav_header, nav_footer = [], []
    m.all_cards = cards
    items = [it for it in _build_items(leaves, cards, m.W) if it.box[2] > 1 and it.box[3] > 1]
    bands = _bands(items, m.scale)
    blocks: list = []
    for i, band in enumerate(bands):
        prev_end = _y1(_union([x.box for x in bands[i - 1]])) if i > 0 else None
        nxt = _union([x.box for x in bands[i + 1]])[1] if i + 1 < len(bands) else None
        try:
            blocks.extend(m.section_for(band, divs, prev_end, nxt, page_bg))
        except Exception:   # noqa: BLE001 — یک نوارِ خراب کلِ تبدیل را نیندازد؛ همان متن‌ها بیایند
            m.warnings.append("یک بخش چیدمانِ ساده گرفت چون ساختارش خوانده نشد.")
            fb = _fallback_section(m, [lf for it in band for lf in ([it.node] if it.kind == "leaf" else it.leaves)])
            if fb is not None:
                blocks.append(fb)
    page_doc = {"v": 1, "blocks": blocks}
    _trim(page_doc, 700, m.warnings)

    header_doc = footer_doc = None
    menu: list = []
    site_title = ""
    if nav_header:
        hp = m.header_parts(nav_header)
        site_title = hp["brand"]
        logo = m.new_crop(hp["logo"], "logo", alt=hp["brand"] or "نشان") if hp["logo"] else ""
        hb = m.block("site_header", logo=logo, show_title=bool(hp["brand"]), show_menu=bool(hp["menu"]), btn=(hp["button"] or "")[:40], btn_link="#", sticky=True)
        if hp["bg"]:
            hb["style"] = {"d": {"bg": hp["bg"]}}
        header_doc = {"v": 1, "blocks": [hb]}
        menu = [{"id": "m%d" % (i + 1), "url": "#", "label": t[:40]} for i, t in enumerate(hp["menu"][:8])]
    if nav_footer:
        fl: list = []
        fc: list = []
        for nav in nav_footer:
            for c in nav.get("children") or []:
                _collect(c, fc, fl, divs, [], [], depth=2)
        m.all_cards = cards + fc
        fitems = [it for it in _build_items(fl, fc, m.W) if it.box[2] > 1 and it.box[3] > 1]
        if fitems:
            fb_box = _union([it.box for it in fitems])
            mark = len(m.forms)
            fblocks = m.items_blocks(fitems, [0, fb_box[1], m.W, fb_box[3]])
            del m.forms[mark:]
            style = {"py": int(max(20, min(80, 36 * m.scale)))}
            fbg = _valid_hex(nav_footer[0].get("background"))
            if fbg:
                style["bg"] = fbg
            if fblocks:
                footer_doc = {"v": 1, "blocks": [m.block("section", children=fblocks, full=bool(fbg), style={"d": style})]}
    theme = _theme_for(m, page_bg, tree)
    return {"theme": theme, "header": header_doc, "page": page_doc, "footer": footer_doc, "menu": menu, "crops": m.crops, "stats": dict(m.stats),
            "warnings": m.warnings, "site_title": site_title, "page_bg": page_bg, "direction": tree.get("direction") or "rtl"}


def clean_docs(result: dict) -> dict:
    """سندها را از صافیِ خودِ سایت‌ساز می‌گذراند (DocError ⇒ بالا می‌رود). ⇒ کپیِ result با سندهای تمیز."""
    from apps.projects.builder.clean import clean_doc
    out = dict(result)
    for key in ("page", "header", "footer"):
        if result.get(key):
            out[key] = clean_doc(result[key], key)
    return out
