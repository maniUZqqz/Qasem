"""چیدمانِ خودکار (Auto Layout) شبیهِ Figma: قاب‌های «پشته» (عمودی/افقی) و «شبکه» با فاصلهٔ داخلی، فاصله و ترازِ فرزندها.

گره‌ها دیکشنری‌اند (قابلِ ذخیره در JSON):

    {"t": "frame", "dir": "v"|"h"|"grid"|"z", "pad": 16 | [بالا، راست، پایین، چپ], "gap": 8, "cols": 3, "col_gap": …, "row_gap": …,
     "align": "start"|"center"|"end"|"stretch", "justify": "start"|"center"|"end"|"between", "w"/"h": عدد | "fill" | "hug",
     "min_h", "max_w", "grow", "fill", "radius", "stroke", "shadow", "rtl": True, "children": [...]}
    {"t": "text", "text", "size", "weight", "font", "color", "align", "lh", "w": "fill"|"hug"|عدد, "max_lines", "h"}
    {"t": "image", "src", "w", "h" | "ratio", "fit", "radius"}    {"t": "rect", "w", "h", "fill", "radius"}    {"t": "spacer", "w", "h"}

«شروع» در حالتِ راست‌به‌چپ (rtl=True، پیش‌فرض) یعنی لبهٔ راست: ردیفِ افقی و ستونِ اولِ شبکه از راست شروع می‌شود.
خروجی: فهرستِ عنصرهای صحنه (scene.rect/text/image) با مختصاتِ مطلق.
"""
from __future__ import annotations

from . import scene, typeset

MAX_DEPTH = 24
MAX_NODES = 1500


class LayoutError(ValueError):
    pass


class Ctx:
    def __init__(self, *, prefix: str = "n", defaults: dict | None = None, rtl: bool = True, digits: str = "keep", var=None):
        self.prefix = prefix
        self.n = 0
        self.rtl = rtl
        self.digits = digits
        self.defaults = {"font": "vazirmatn", "weight": 400, "color": "#111827", "size": 16.0, "lh": 1.5, **(defaults or {})}
        self.var = var or (lambda v: v)              # «var:primary» ⇒ رنگ (برای حالتِ روشن/تیره)
        self.cache: dict = {}
        self.boxes: dict = {}
        self.keep: list = []             # گره‌های موقت را زنده نگه می‌دارد تا id() ِ آن‌ها در کَش دوباره استفاده نشود
        self.count = 0

    def nid(self, node: dict, kind: str) -> str:
        if node.get("id"):
            return str(node["id"])
        self.n += 1
        return f"{self.prefix}{self.n}"


def _pad(n: dict) -> tuple[float, float, float, float]:
    p = n.get("pad", 0)
    if isinstance(p, (list, tuple)):
        if len(p) == 4:
            return tuple(float(x) for x in p)          # بالا، راست، پایین، چپ
        if len(p) == 2:
            return float(p[0]), float(p[1]), float(p[0]), float(p[1])
    try:
        v = float(p or 0)
    except (TypeError, ValueError):
        v = 0.0
    return v, v, v, v


def _dim(v):
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v)
    return v if v in ("fill", "hug") else None


def _txt(n: dict, ctx: Ctx, w: float | None, h_limit: float | None = None) -> dict:
    d = ctx.defaults
    return typeset.layout_text(typeset.digits(n.get("text", ""), ctx.digits), font=n.get("font", d["font"]), weight=int(n.get("weight", d["weight"])),
                               size=float(n.get("size", d["size"])), w=max(1.0, w if w is not None else 100000.0), h=h_limit,
                               align=n.get("align", "auto"), dir=n.get("dir", "auto"), lh=float(n.get("lh", d["lh"])),
                               max_lines=n.get("max_lines"), shrink=float(n.get("shrink", 0) or 0), justify=bool(n.get("justify")),
                               valign=n.get("valign", "top"))


def _count(ctx: Ctx) -> None:
    ctx.count += 1
    if ctx.count > MAX_NODES * 6:
        raise LayoutError("طرح بیش از اندازه بزرگ است.")


# ───────────────────────────── اندازه‌گیری

def size(node: dict, avail_w: float, ctx: Ctx, avail_h: float | None = None, depth: int = 0) -> tuple[float, float]:
    """اندازهٔ بیرونیِ گره وقتی حداکثر پهنایش avail_w است."""
    if depth > MAX_DEPTH:
        raise LayoutError("تودرتوییِ قاب‌ها بیش از اندازه است.")
    key = (id(node), round(avail_w, 2), None if avail_h is None else round(avail_h, 2))
    hit = ctx.cache.get(key)
    if hit is not None:
        return hit
    _count(ctx)
    t = node.get("t")
    w_spec, h_spec = _dim(node.get("w")), _dim(node.get("h"))
    if t == "text" and node.get("max_w"):
        avail_w = min(avail_w, float(node["max_w"]))
    if t == "text":
        if isinstance(w_spec, float):
            W = min(w_spec, avail_w) if node.get("clamp") else w_spec
            lay = _txt(node, ctx, W)
        elif w_spec == "hug":
            lay = _txt(node, ctx, avail_w)
            W = max(1.0, min(avail_w, lay["w"] + 1.0))
        else:
            W = avail_w
            lay = _txt(node, ctx, W)
        H = h_spec if isinstance(h_spec, float) else lay["h"]
        res = (W, H)
    elif t in ("rect", "spacer"):
        W = w_spec if isinstance(w_spec, float) else (avail_w if w_spec == "fill" else 0.0)
        res = (min(W, avail_w) if node.get("clamp") else W, h_spec if isinstance(h_spec, float) else 0.0)
    elif t == "image":
        W = w_spec if isinstance(w_spec, float) else avail_w
        if isinstance(h_spec, float):
            H = h_spec
        else:
            H = W * float(node.get("ratio", 0.75))
        res = (W, H)
    elif t == "frame":
        res = _size_frame(node, avail_w, ctx, avail_h, depth)
    else:
        raise LayoutError(f"نوعِ گرهٔ «{t}» ناشناخته است.")
    ctx.cache[key] = res
    return res


def _size_frame(n: dict, avail_w: float, ctx: Ctx, avail_h: float | None, depth: int) -> tuple[float, float]:
    pt, pr, pb, pl = _pad(n)
    gap = float(n.get("gap", 0) or 0)
    kids = [c for c in (n.get("children") or []) if not c.get("abs") and not c.get("hidden")]
    w_spec, h_spec = _dim(n.get("w")), _dim(n.get("h"))
    max_w = n.get("max_w")
    outer_cap = avail_w if not max_w else min(avail_w, float(max_w))
    if isinstance(w_spec, float):
        W = w_spec
    elif w_spec == "hug":
        W = None
    else:
        W = outer_cap
    inner_w = (W if W is not None else outer_cap) - pl - pr
    inner_w = max(0.0, inner_w)
    d = n.get("dir", "v")
    content_w = 0.0
    content_h = 0.0
    if d == "v":
        for i, c in enumerate(kids):
            cw, ch = size(c, inner_w, ctx, None, depth + 1)
            content_w = max(content_w, cw)
            content_h += ch + (gap if i else 0)
    elif d == "h":
        widths = _row_widths(kids, inner_w, gap, ctx, depth)
        for i, (c, cw) in enumerate(zip(kids, widths)):
            _, ch = size(c, cw, ctx, None, depth + 1)
            content_h = max(content_h, ch)
            content_w += cw + (gap if i else 0)
    elif d == "grid":
        cols = _cols(n, inner_w)
        cg = float(n.get("col_gap", gap) or 0)
        rg = float(n.get("row_gap", gap) or 0)
        col_w = max(1.0, (inner_w - cg * (cols - 1)) / cols)
        rows = _grid_rows(kids, cols, col_w, cg, ctx, depth)
        content_h = sum(r["h"] for r in rows) + rg * max(0, len(rows) - 1)
        content_w = inner_w
    else:                                                            # z
        for c in kids:
            cw, ch = size(c, inner_w, ctx, None, depth + 1)
            content_w, content_h = max(content_w, cw), max(content_h, ch)
    if W is None:
        W = min(outer_cap, content_w + pl + pr)
    if isinstance(h_spec, float):
        H = h_spec
    else:
        H = content_h + pt + pb
        if n.get("min_h"):
            H = max(H, float(n["min_h"]))
    return max(W, float(n.get("min_w", 0) or 0)), H


def _cols(n: dict, inner_w: float) -> int:
    cols = int(n.get("cols") or 0)
    if cols <= 0 and n.get("min_col_w"):
        cols = max(1, int(inner_w // max(1.0, float(n["min_col_w"]))))
    return max(1, cols or 1)


def _hug(c: dict, avail: float, ctx: Ctx, depth: int) -> float:
    """پهنای طبیعیِ فرزندِ بی‌پهنا در ردیفِ افقی (مثلِ «hug contents» در Figma)."""
    if c.get("t") == "image":
        return float(c.get("w") or 100)
    ghost = {**c, "w": "hug"}
    ctx.keep.append(ghost)
    return size(ghost, max(0.0, avail), ctx, None, depth + 1)[0]


def _row_widths(kids: list, inner_w: float, gap: float, ctx: Ctx, depth: int) -> list[float]:
    """پهنای هر فرزندِ ردیفِ افقی: ثابت/hug همان، fill ⇐ سهمِ باقی‌مانده (به نسبتِ grow)."""
    widths: list[float | None] = []
    fixed = 0.0
    grow_sum = 0.0
    for c in kids:
        ws = _dim(c.get("w"))
        if isinstance(ws, float):
            widths.append(ws)
            fixed += ws
        elif ws == "fill" or c.get("grow"):
            widths.append(None)
            grow_sum += float(c.get("grow") or 1)
        else:
            cw = _hug(c, inner_w - fixed, ctx, depth)
            widths.append(cw)
            fixed += cw
    free = inner_w - fixed - gap * max(0, len(kids) - 1)
    out = []
    for c, w in zip(kids, widths):
        if w is None:
            out.append(max(0.0, free * (float(c.get("grow") or 1) / grow_sum)) if grow_sum else 0.0)
        else:
            out.append(w)
    return out


def _grid_rows(kids: list, cols: int, col_w: float, cg: float, ctx: Ctx, depth: int) -> list[dict]:
    rows: list[dict] = []
    cur: list = []
    used = 0
    for c in kids:
        span = max(1, min(cols, int(c.get("span") or 1)))
        if used + span > cols:
            rows.append({"items": cur})
            cur, used = [], 0
        cur.append((c, used, span))
        used += span
    if cur:
        rows.append({"items": cur})
    for r in rows:
        hmax = 0.0
        for c, col, span in r["items"]:
            w = col_w * span + cg * (span - 1)
            _, ch = size(c, w, ctx, None, depth + 1)
            hmax = max(hmax, ch)
        r["h"] = hmax
    return rows


# ───────────────────────────── چیدن

def place(node: dict, x: float, y: float, w: float, h: float, ctx: Ctx, out: list, depth: int = 0) -> None:
    """گره را در جعبهٔ (x، y، w، h) می‌چیند و عنصرهای صحنه را به ``out`` می‌افزاید."""
    if depth > MAX_DEPTH:
        raise LayoutError("تودرتوییِ قاب‌ها بیش از اندازه است.")
    if node.get("hidden"):
        return
    t = node.get("t")
    var = ctx.var
    if node.get("id"):
        ctx.boxes[str(node["id"])] = (x, y, w, h)
    common = {k: node[k] for k in ("link", "name", "role", "locked", "node") if node.get(k)}
    if node.get("hotspot"):
        common["hotspot"] = node["hotspot"]
    if t == "text":
        eid = ctx.nid(node, "text")
        d = ctx.defaults
        out.append(scene.text(eid, x, y, w, h, node.get("text", ""), font=node.get("font", d["font"]), weight=int(node.get("weight", d["weight"])),
                              size=float(node.get("size", d["size"])), color=var(node.get("color", d["color"])), align=node.get("align", "auto"),
                              dir=node.get("dir", "auto"), lh=float(node.get("lh", d["lh"])), max_lines=node.get("max_lines"),
                              shrink=float(node.get("shrink", 0) or 0), justify=bool(node.get("justify")), valign=node.get("valign", "top"),
                              opacity=float(node.get("opacity", 1)), **common,
                              **{k: node[k] for k in ("underline", "strike", "ph") if node.get(k)}))
    elif t == "rect":
        out.append(scene.rect(ctx.nid(node, "rect"), x, y, w, h, _col(node.get("fill"), var), radius=node.get("radius", 0), stroke=_stroke(node.get("stroke"), var),
                              opacity=float(node.get("opacity", 1)), shadow=node.get("shadow"), **common))
    elif t == "image":
        out.append(scene.image(ctx.nid(node, "img"), x, y, w, h, node.get("src", ""), fit=node.get("fit", "cover"), focus=node.get("focus", (0.5, 0.5)),
                               radius=node.get("radius", 0), opacity=float(node.get("opacity", 1)), stroke=_stroke(node.get("stroke"), var),
                               shadow=node.get("shadow"), **common, **({"alt": node["alt"]} if node.get("alt") else {})))
    elif t == "spacer":
        return
    elif t == "frame":
        _place_frame(node, x, y, w, h, ctx, out, depth, common)


def _col(c, var):
    if isinstance(c, dict):
        return {**c, "stops": [[s[0], var(s[1])] + list(s[2:]) for s in c.get("stops", [])]}
    return var(c) if c else None


def _stroke(s, var):
    if isinstance(s, dict) and s.get("w"):
        return {"color": var(s.get("color", "#000000")), "w": s["w"]}
    return None


def _place_frame(n: dict, x: float, y: float, W: float, H: float, ctx: Ctx, out: list, depth: int, common: dict) -> None:
    var = ctx.var
    fid = ctx.nid(n, "frame")
    if n.get("fill") or n.get("stroke") or n.get("shadow"):
        out.append(scene.rect(fid, x, y, W, H, _col(n.get("fill"), var), radius=n.get("radius", 0), stroke=_stroke(n.get("stroke"), var),
                              opacity=float(n.get("opacity", 1)), shadow=n.get("shadow"), **common))
    elif common.get("link") or n.get("hotspot"):
        out.append(scene.rect(fid, x, y, W, H, None, **common))
    pt, pr, pb, pl = _pad(n)
    gap = float(n.get("gap", 0) or 0)
    rtl = bool(n.get("rtl", ctx.rtl))
    kids = [c for c in (n.get("children") or []) if not c.get("hidden")]
    flow = [c for c in kids if not c.get("abs")]
    ix, iy = x + pl, y + pt
    iw, ih = max(0.0, W - pl - pr), max(0.0, H - pt - pb)
    d = n.get("dir", "v")
    align = n.get("align", "stretch" if d == "v" else "start")
    justify = n.get("justify", "start")
    for c in kids:
        if c.get("abs") and c.get("behind"):
            _place_abs(c, x, y, W, H, iw, ctx, out, depth)

    if d == "v":
        dims = [size(c, iw, ctx, None, depth + 1) for c in flow]
        grows = [float(c.get("grow") or 0) if _dim(c.get("h")) == "fill" or c.get("grow") else 0.0 for c in flow]
        used = sum(h for _, h in dims) + gap * max(0, len(flow) - 1)
        free = ih - used
        gs = sum(grows)
        extra = [0.0] * len(flow)
        if gs > 0 and free > 0:
            extra = [free * g / gs for g in grows]
            free = 0.0
        cy = iy
        step_extra = 0.0
        if free > 0:
            if justify == "center":
                cy += free / 2
            elif justify == "end":
                cy += free
            elif justify == "between" and len(flow) > 1:
                step_extra = free / (len(flow) - 1)
        for c, (cw, ch), ex in zip(flow, dims, extra):
            ch = ch + ex
            fw = iw if (align == "stretch" and not isinstance(_dim(c.get("w")), float)) or _dim(c.get("w")) == "fill" else cw
            eff = align
            if c.get("max_w") and fw > float(c["max_w"]):
                fw, eff = float(c["max_w"]), "center"
            cx = _cross_x(ix, iw, fw, eff, rtl)
            place(c, cx, cy, fw, ch, ctx, out, depth + 1)
            cy += ch + gap + step_extra
    elif d == "h":
        widths = _row_widths(flow, iw, gap, ctx, depth)
        total = sum(widths) + gap * max(0, len(flow) - 1)
        free = iw - total
        start_off = 0.0
        step_extra = 0.0
        if free > 0:
            if justify == "center":
                start_off = free / 2
            elif justify == "end":
                start_off = free
            elif justify == "between" and len(flow) > 1:
                step_extra = free / (len(flow) - 1)
        cursor = start_off
        for c, cw in zip(flow, widths):
            _, ch = size(c, cw, ctx, None, depth + 1)
            fh = ih if (align == "stretch" and not isinstance(_dim(c.get("h")), float)) or _dim(c.get("h")) == "fill" else ch
            cy = iy + {"start": 0.0, "stretch": 0.0, "center": (ih - fh) / 2, "end": ih - fh}.get(align, 0.0)
            cx = (ix + iw - cursor - cw) if rtl else (ix + cursor)
            place(c, cx, cy, cw, fh, ctx, out, depth + 1)
            cursor += cw + gap + step_extra
    elif d == "grid":
        cols = _cols(n, iw)
        cg = float(n.get("col_gap", gap) or 0)
        rg = float(n.get("row_gap", gap) or 0)
        col_w = max(1.0, (iw - cg * (cols - 1)) / cols)
        rows = _grid_rows(flow, cols, col_w, cg, ctx, depth)
        cy = iy
        for r in rows:
            for c, col, span in r["items"]:
                cw = col_w * span + cg * (span - 1)
                off = col * (col_w + cg)
                cx = (ix + iw - off - cw) if rtl else (ix + off)
                _, ch = size(c, cw, ctx, None, depth + 1)
                fh = r["h"] if align == "stretch" else ch
                place(c, cx, cy, cw, fh, ctx, out, depth + 1)
            cy += r["h"] + rg
    else:                                                           # z: همه روی هم
        for c in flow:
            cw, ch = size(c, iw, ctx, None, depth + 1)
            fw = iw if _dim(c.get("w")) == "fill" else cw
            fh = ih if _dim(c.get("h")) == "fill" else ch
            cx = _cross_x(ix, iw, fw, n.get("align", "start") if n.get("align") != "stretch" else "start", rtl)
            cy = iy + {"start": 0.0, "center": (ih - fh) / 2, "end": ih - fh}.get(n.get("valign", "start"), 0.0)
            place(c, cx, cy, fw, fh, ctx, out, depth + 1)
    for c in kids:
        if c.get("abs") and not c.get("behind"):
            _place_abs(c, x, y, W, H, iw, ctx, out, depth)


def _place_abs(c: dict, x: float, y: float, W: float, H: float, iw: float, ctx: Ctx, out: list, depth: int) -> None:
    a = c["abs"]
    cw, ch = size(c, iw, ctx, None, depth + 1)
    ax = float(a.get("x", 0)) if "x" in a else None
    ay = float(a.get("y", 0))
    cx = (x + (W - float(a["right"]) - cw)) if "right" in a else (x + ax if ax is not None else x)
    cy = (y + (H - float(a["bottom"]) - ch)) if "bottom" in a else y + ay
    place(c, cx, cy, cw, ch, ctx, out, depth + 1)


def _cross_x(ix: float, iw: float, cw: float, align: str, rtl: bool) -> float:
    if align == "center":
        return ix + (iw - cw) / 2
    if align == "end":
        return ix if rtl else ix + iw - cw
    if align == "stretch":
        return ix
    return ix + iw - cw if rtl else ix                              # start


def solve(root: dict, width: float, *, height: float | None = None, x: float = 0.0, y: float = 0.0, ctx: Ctx | None = None) -> tuple[list[dict], tuple[float, float]]:
    """ریشه را با پهنای width می‌چیند. ⇒ (عنصرها، (پهنا، بلندی))؛ اگر height داده شود ریشه آن‌قدر بلند می‌شود."""
    ctx = ctx or Ctx()
    w, h = size(root, width, ctx)
    w = width if _dim(root.get("w")) == "fill" or root.get("w") is None else w
    if height is not None:
        h = max(h, height)
    out: list[dict] = []
    place(root, x, y, w, h, ctx, out)
    return out, (w, h)
