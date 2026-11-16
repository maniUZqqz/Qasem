"""نویسندهٔ PDF (بی‌وابستگی؛ فقط zlib + Pillow): صفحهٔ برداری با متنِ منحنی‌شده، عکسِ JPEG، شیب، خونریزی، علامتِ برش، پیوند و نشانک.

* «PDF چاپی»: TrimBox = اندازهٔ برش، BleedBox = برش + خونریزی (۳ میلی‌متر)، MediaBox = با علامت‌های برش؛ عکس‌ها تا ۳۰۰ dpi؛ متن‌ها منحنی (بی‌فونت).
* «PDF نمایشی»: سبک‌تر (عکس ~۱۱۰ dpi)، بی‌خونریزی و علامت، با پیوندِ قابل‌کلیک (فهرستِ مطالب) و نشانک.
* رنگ‌ها RGB‌اند. CMYK و PDF/X واقعی را چاپخانه از همین فایل می‌سازد (در بستهٔ چاپخانه همین نکته نوشته می‌شود).
"""
from __future__ import annotations

import datetime as _dt
import io
import math
import zlib

from PIL import Image

from . import colors, images, outline, render_png

PT_PER_MM = 72.0 / 25.4
KAPPA = 0.5522847498


def _f(v: float) -> str:
    s = f"{v:.3f}".rstrip("0").rstrip(".")
    return s if s not in ("", "-0") else "0"


def _pdf_str(s: str) -> str:
    """رشتهٔ یونیکد ⇒ <FEFF…> (UTF-16BE)."""
    return "<FEFF" + s.encode("utf-16-be").hex().upper() + ">"


class PdfDoc:
    def __init__(self, *, title: str = "", author: str = "", subject: str = "", keywords: str = "", rtl: bool = True, lang: str = "fa-IR",
                 creator: str = "NMarketing Design Studio"):
        self.objs: list[bytes | None] = []
        self.meta = {"title": title, "author": author, "subject": subject, "keywords": keywords, "creator": creator}
        self.rtl, self.lang = rtl, lang
        self.pages: list[PageBuilder] = []
        self.outlines: list[tuple[str, int, int]] = []
        self.catalog_ref = self._reserve()
        self.pages_ref = self._reserve()

    def _reserve(self) -> int:
        self.objs.append(None)
        return len(self.objs)

    def _set(self, num: int, body: bytes) -> None:
        self.objs[num - 1] = body

    def add(self, body: str | bytes) -> int:
        n = self._reserve()
        self._set(n, body.encode("latin-1") if isinstance(body, str) else body)
        return n

    def add_stream(self, dict_body: str, data: bytes, *, flate: bool = True) -> int:
        if flate:
            data = zlib.compress(data, 6)
            dict_body += " /Filter /FlateDecode"
        n = self._reserve()
        self._set(n, f"<< {dict_body} /Length {len(data)} >>\nstream\n".encode("latin-1") + data + b"\nendstream")
        return n

    def new_page(self, w: float, h: float, *, bleed: float = 0.0, slug: float = 0.0, ptu: float = PT_PER_MM) -> "PageBuilder":
        pb = PageBuilder(self, w, h, bleed, slug, ptu)
        self.pages.append(pb)
        return pb

    def bookmark(self, title: str, page_index: int, level: int = 0) -> None:
        self.outlines.append((title, page_index, level))

    # ---- خروجی ----
    def save(self) -> bytes:
        page_nums = [p.obj for p in self.pages]
        for p in self.pages:
            p.finish(page_nums)
        kids = " ".join(f"{n} 0 R" for n in page_nums)
        self._set(self.pages_ref, f"<< /Type /Pages /Kids [{kids}] /Count {len(page_nums)} >>".encode("latin-1"))
        cat = f"/Type /Catalog /Pages {self.pages_ref} 0 R /Lang ({self.lang})"
        if self.rtl:
            cat += " /ViewerPreferences << /Direction /R2L /DisplayDocTitle true >>"
        else:
            cat += " /ViewerPreferences << /DisplayDocTitle true >>"
        if self.outlines:
            cat += f" /Outlines {self._write_outlines(page_nums)} 0 R /PageMode /UseOutlines"
        else:
            cat += " /PageMode /UseNone"
        self._set(self.catalog_ref, f"<< {cat} >>".encode("latin-1"))
        now = _dt.datetime.now(_dt.timezone.utc).strftime("D:%Y%m%d%H%M%SZ")
        m = self.meta
        info = self.add(f"<< /Title {_pdf_str(m['title'])} /Author {_pdf_str(m['author'])} /Subject {_pdf_str(m['subject'])} "
                        f"/Keywords {_pdf_str(m['keywords'])} /Creator {_pdf_str(m['creator'])} /Producer (NMarketing Design Studio) "
                        f"/CreationDate ({now}) /ModDate ({now}) >>")
        out = io.BytesIO()
        out.write(b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n")
        offsets = []
        for i, body in enumerate(self.objs, 1):
            offsets.append(out.tell())
            out.write(f"{i} 0 obj\n".encode("latin-1"))
            out.write(body if body is not None else b"null")
            out.write(b"\nendobj\n")
        xref = out.tell()
        out.write(f"xref\n0 {len(self.objs) + 1}\n".encode("latin-1"))
        out.write(b"0000000000 65535 f \n")
        for off in offsets:
            out.write(f"{off:010d} 00000 n \n".encode("latin-1"))
        out.write(f"trailer\n<< /Size {len(self.objs) + 1} /Root {self.catalog_ref} 0 R /Info {info} 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode("latin-1"))
        return out.getvalue()

    def _write_outlines(self, page_nums: list[int]) -> int:
        root = self._reserve()
        items = []
        for title, pi, level in self.outlines:
            if 0 <= pi < len(page_nums):
                items.append((title, page_nums[pi], level))
        nums = [self._reserve() for _ in items]
        # فقط سطحِ ۰ و ۱؛ سطحِ ۱ فرزندِ آخرین سطحِ ۰ است
        parents: dict[int, int | None] = {}
        children: dict[int, list[int]] = {}
        top: list[int] = []
        last_top = None
        for i, (_, _, lvl) in enumerate(items):
            if lvl == 0 or last_top is None:
                top.append(i)
                parents[i] = None
                last_top = i
            else:
                parents[i] = last_top
                children.setdefault(last_top, []).append(i)

        def siblings(lst):
            for k, i in enumerate(lst):
                title, pg, _ = items[i]
                parent = root if parents[i] is None else nums[parents[i]]
                body = f"/Title {_pdf_str(title)} /Parent {parent} 0 R /Dest [{pg} 0 R /Fit]"
                if k > 0:
                    body += f" /Prev {nums[lst[k - 1]]} 0 R"
                if k < len(lst) - 1:
                    body += f" /Next {nums[lst[k + 1]]} 0 R"
                kids = children.get(i)
                if kids:
                    body += f" /First {nums[kids[0]]} 0 R /Last {nums[kids[-1]]} 0 R /Count {len(kids)}"
                self._set(nums[i], f"<< {body} >>".encode("latin-1"))
                if kids:
                    siblings(kids)

        siblings(top)
        if top:
            self._set(root, f"<< /Type /Outlines /First {nums[top[0]]} 0 R /Last {nums[top[-1]]} 0 R /Count {len(items)} >>".encode("latin-1"))
        else:
            self._set(root, b"<< /Type /Outlines /Count 0 >>")
        return root


class PageBuilder:
    def __init__(self, doc: PdfDoc, w: float, h: float, bleed: float, slug: float, ptu: float):
        self.doc, self.w, self.h, self.bleed, self.slug, self.ptu = doc, w, h, bleed, slug, ptu
        self.off = bleed + slug
        self.mw = (w + 2 * self.off) * ptu
        self.mh = (h + 2 * self.off) * ptu
        self.obj = doc._reserve()
        self.ops: list[str] = []
        self.xobjs: dict[str, int] = {}
        self.gstates: dict[str, int] = {}
        self.shadings: dict[str, int] = {}
        self.links: list[tuple[tuple, dict]] = []
        self._n = 0
        self.image_report: list[dict] = []

    # ---- مختصات ----
    def X(self, x: float) -> float:
        return (x + self.off) * self.ptu

    def Y(self, y: float) -> float:
        return self.mh - (y + self.off) * self.ptu

    def L(self, v: float) -> float:
        return v * self.ptu

    def op(self, s: str) -> None:
        self.ops.append(s)

    def _name(self, prefix: str) -> str:
        self._n += 1
        return f"{prefix}{self._n}"

    # ---- رنگ و شفافیت ----
    def alpha(self, a: float) -> str:
        if a >= 0.999:
            return ""
        key = f"{a:.3f}"
        for nm, _ in self.gstates.items():
            if nm.endswith("_" + key):
                return f"/{nm} gs "
        nm = f"GS{len(self.gstates) + 1}_{key}"
        self.gstates[nm] = self.doc.add(f"<< /Type /ExtGState /ca {key} /CA {key} >>")
        return f"/{nm} gs "

    @staticmethod
    def rgb(c: str, stroke: bool = False) -> str:
        r, g, b = colors.rgb(c)
        return f"{_f(r / 255)} {_f(g / 255)} {_f(b / 255)} {'RG' if stroke else 'rg'}"

    # ---- مسیر ----
    def path_rrect(self, x: float, y: float, w: float, h: float, radius) -> str:
        X0, Y0 = self.X(x), self.Y(y + h)
        W, H = self.L(w), self.L(h)
        rs = render_png._radii(radius, w, h)
        if max(rs) <= 0:
            return f"{_f(X0)} {_f(Y0)} {_f(W)} {_f(H)} re"
        tl, tr, br, bl = (self.L(r) for r in rs)
        k = KAPPA
        p = [f"{_f(X0 + bl)} {_f(Y0)} m", f"{_f(X0 + W - br)} {_f(Y0)} l"]
        if br:
            p.append(f"{_f(X0 + W - br + br * k)} {_f(Y0)} {_f(X0 + W)} {_f(Y0 + br - br * k)} {_f(X0 + W)} {_f(Y0 + br)} c")
        p.append(f"{_f(X0 + W)} {_f(Y0 + H - tr)} l")
        if tr:
            p.append(f"{_f(X0 + W)} {_f(Y0 + H - tr + tr * k)} {_f(X0 + W - tr + tr * k)} {_f(Y0 + H)} {_f(X0 + W - tr)} {_f(Y0 + H)} c")
        p.append(f"{_f(X0 + tl)} {_f(Y0 + H)} l")
        if tl:
            p.append(f"{_f(X0 + tl - tl * k)} {_f(Y0 + H)} {_f(X0)} {_f(Y0 + H - tl + tl * k)} {_f(X0)} {_f(Y0 + H - tl)} c")
        p.append(f"{_f(X0)} {_f(Y0 + bl)} l")
        if bl:
            p.append(f"{_f(X0)} {_f(Y0 + bl - bl * k)} {_f(X0 + bl - bl * k)} {_f(Y0)} {_f(X0 + bl)} {_f(Y0)} c")
        p.append("h")
        return " ".join(p)

    def path_ellipse(self, x: float, y: float, w: float, h: float) -> str:
        cx, cy = self.X(x + w / 2), self.Y(y + h / 2)
        rx, ry = self.L(w / 2), self.L(h / 2)
        k = KAPPA
        return (f"{_f(cx + rx)} {_f(cy)} m {_f(cx + rx)} {_f(cy + ry * k)} {_f(cx + rx * k)} {_f(cy + ry)} {_f(cx)} {_f(cy + ry)} c "
                f"{_f(cx - rx * k)} {_f(cy + ry)} {_f(cx - rx)} {_f(cy + ry * k)} {_f(cx - rx)} {_f(cy)} c "
                f"{_f(cx - rx)} {_f(cy - ry * k)} {_f(cx - rx * k)} {_f(cy - ry)} {_f(cx)} {_f(cy - ry)} c "
                f"{_f(cx + rx * k)} {_f(cy - ry)} {_f(cx + rx)} {_f(cy - ry * k)} {_f(cx + rx)} {_f(cy)} c h")

    # ---- شیب ----
    def shading(self, g: dict, x: float, y: float, w: float, h: float) -> str:
        a = math.radians(float(g.get("angle", 90)))
        dx, dy = math.cos(a), math.sin(a)
        half = (abs(w * dx) + abs(h * dy)) / 2
        cx, cy = x + w / 2, y + h / 2
        x0, y0, x1, y1 = cx - dx * half, cy - dy * half, cx + dx * half, cy + dy * half
        stops = sorted(g["stops"], key=lambda s: s[0])
        fns, bounds, enc = [], [], []
        for s0, s1 in zip(stops, stops[1:]):
            c0 = [v / 255 for v in colors.rgb(s0[1])]
            c1 = [v / 255 for v in colors.rgb(s1[1])]
            fns.append(f"<< /FunctionType 2 /Domain [0 1] /C0 [{' '.join(_f(v) for v in c0)}] /C1 [{' '.join(_f(v) for v in c1)}] /N 1 >>")
            enc += ["0", "1"]
        bounds = [_f(s[0]) for s in stops[1:-1]]
        fn = fns[0] if len(fns) == 1 else (f"<< /FunctionType 3 /Domain [0 1] /Functions [{' '.join(fns)}] /Bounds [{' '.join(bounds)}] /Encode [{' '.join(enc)}] >>")
        kind = 3 if g.get("type") == "radial" else 2
        if kind == 3:
            r = max(w, h) / 2
            coords = f"[{_f(self.X(cx))} {_f(self.Y(cy))} 0 {_f(self.X(cx))} {_f(self.Y(cy))} {_f(self.L(r))}]"
        else:
            coords = f"[{_f(self.X(x0))} {_f(self.Y(y0))} {_f(self.X(x1))} {_f(self.Y(y1))}]"
        nm = self._name("Sh")
        self.shadings[nm] = self.doc.add(f"<< /ShadingType {kind} /ColorSpace /DeviceRGB /Coords {coords} /Function {fn} /Extend [true true] >>")
        return nm

    # ---- تصویر ----
    def add_image(self, im: Image.Image, *, jpeg_q: int, dpi: int) -> str:
        nm = self._name("Im")
        w, h = im.size
        if im.mode == "RGBA" and im.getchannel("A").getextrema()[0] < 255:
            rgb = im.convert("RGB")
            alpha = im.getchannel("A")
            sm = self.doc.add_stream(f"/Type /XObject /Subtype /Image /Width {w} /Height {h} /ColorSpace /DeviceGray /BitsPerComponent 8", alpha.tobytes())
            num = self.doc.add_stream(f"/Type /XObject /Subtype /Image /Width {w} /Height {h} /ColorSpace /DeviceRGB /BitsPerComponent 8 /SMask {sm} 0 R /Interpolate true",
                                      rgb.tobytes())
        else:
            data = images.jpeg_bytes(im, jpeg_q, dpi)
            num = self.doc.add_stream(f"/Type /XObject /Subtype /Image /Width {w} /Height {h} /ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode",
                                      data, flate=False)
        self.xobjs[nm] = num
        return nm

    def draw_image_xobj(self, nm: str, x: float, y: float, w: float, h: float) -> None:
        self.op(f"q {_f(self.L(w))} 0 0 {_f(self.L(h))} {_f(self.X(x))} {_f(self.Y(y + h))} cm /{nm} Do Q")

    # ---- پیوند ----
    def link(self, x: float, y: float, w: float, h: float, target: dict) -> None:
        self.links.append(((self.X(x), self.Y(y + h), self.X(x + w), self.Y(y)), target))

    # ---- پایان ----
    def finish(self, page_nums: list[int], ids: dict[str, int] | None = None) -> None:
        content = "\n".join(self.ops).encode("latin-1")
        cnum = self.doc.add_stream("", content)
        res = []
        if self.xobjs:
            res.append("/XObject << " + " ".join(f"/{k} {v} 0 R" for k, v in self.xobjs.items()) + " >>")
        if self.gstates:
            res.append("/ExtGState << " + " ".join(f"/{k} {v} 0 R" for k, v in self.gstates.items()) + " >>")
        if self.shadings:
            res.append("/Shading << " + " ".join(f"/{k} {v} 0 R" for k, v in self.shadings.items()) + " >>")
        annots = []
        for rect, tgt in self.links:
            r = " ".join(_f(v) for v in rect)
            if "page" in tgt and 0 <= tgt["page"] < len(page_nums):
                annots.append(self.doc.add(f"<< /Type /Annot /Subtype /Link /Rect [{r}] /Border [0 0 0] /Dest [{page_nums[tgt['page']]} 0 R /Fit] >>"))
            elif tgt.get("url"):
                u = tgt["url"].replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
                annots.append(self.doc.add(f"<< /Type /Annot /Subtype /Link /Rect [{r}] /Border [0 0 0] /A << /S /URI /URI ({u}) >> >>"))
        s, b = self.slug * self.ptu, (self.slug + self.bleed) * self.ptu
        boxes = (f"/MediaBox [0 0 {_f(self.mw)} {_f(self.mh)}] /CropBox [0 0 {_f(self.mw)} {_f(self.mh)}] "
                 f"/BleedBox [{_f(s)} {_f(s)} {_f(self.mw - s)} {_f(self.mh - s)}] /TrimBox [{_f(b)} {_f(b)} {_f(self.mw - b)} {_f(self.mh - b)}] "
                 f"/ArtBox [{_f(b)} {_f(b)} {_f(self.mw - b)} {_f(self.mh - b)}]")
        body = f"<< /Type /Page /Parent {self.doc.pages_ref} 0 R {boxes} /Contents {cnum} 0 R /Resources << {' '.join(res)} >>"
        if annots:
            body += " /Annots [" + " ".join(f"{a} 0 R" for a in annots) + "]"
        self.doc._set(self.obj, (body + " >>").encode("latin-1"))


# ───────────────────────────── صحنه ⇒ PDF

class Options:
    def __init__(self, *, mode: str = "print", dpi: int = 300, bleed: bool = True, marks: bool = True, jpeg_q: int = 90, outline_quality: str = "print",
                 eps: float = 0.5):
        self.mode, self.dpi, self.bleed, self.marks = mode, dpi, bleed, marks
        self.jpeg_q, self.outline_quality, self.eps = jpeg_q, outline_quality, eps
        self.page_ids: dict[str, int] = {}


PRINT = dict(mode="print", dpi=300, bleed=True, marks=True, jpeg_q=90, outline_quality="print", eps=0.5)
SCREEN = dict(mode="screen", dpi=110, bleed=False, marks=False, jpeg_q=78, outline_quality="screen", eps=0.8)


def draw_page(pb: PageBuilder, page: dict, src: images.ImageSource, o: Options, ptu: float, page_index: int, report: dict) -> None:
    """صفحهٔ صحنه را روی PageBuilder می‌کشد."""
    b = pb.bleed
    s = pb.slug
    # برشِ محتوا به جعبهٔ خونریزی
    bx, by = -b, -b
    bw, bh = page["w"] + 2 * b, page["h"] + 2 * b
    pb.op(f"q {_f(pb.X(bx))} {_f(pb.Y(by + bh))} {_f(pb.L(bw))} {_f(pb.L(bh))} re W n")
    bg = page.get("bg")
    if bg:
        _fill_box(pb, bg, bx, by, bw, bh, 1.0, None, report, o)
    for e in page["elements"]:
        if e.get("hidden"):
            continue
        pb.op("q")
        try:
            _draw_element(pb, e, src, o, report)
        finally:
            pb.op("Q")
        lk = e.get("link")
        if lk:
            if "page" in lk:
                pb.link(*render_png_bbox(e), {"page": o.page_ids.get(lk["page"], -1)})
            else:
                pb.link(*render_png_bbox(e), lk)
    pb.op("Q")
    if o.marks and s > 0:
        _marks(pb, page)


def render_png_bbox(e):
    from . import scene
    return scene.bbox(e)


def _marks(pb: PageBuilder, page: dict) -> None:
    x0, y0, x1, y1 = 0.0, 0.0, page["w"], page["h"]
    L = 5.0
    gap = pb.bleed + 0.5
    pb.op(f"q 0 0 0 RG {_f(0.25)} w")
    for (cx, cy, sx, sy) in ((x0, y0, -1, -1), (x1, y0, 1, -1), (x0, y1, -1, 1), (x1, y1, 1, 1)):
        pb.op(f"{_f(pb.X(cx + sx * gap))} {_f(pb.Y(cy))} m {_f(pb.X(cx + sx * (gap + L)))} {_f(pb.Y(cy))} l S")
        pb.op(f"{_f(pb.X(cx))} {_f(pb.Y(cy + sy * gap))} m {_f(pb.X(cx))} {_f(pb.Y(cy + sy * (gap + L)))} l S")
    pb.op("Q")


def _alpha_gradient(g: dict) -> bool:
    return isinstance(g, dict) and any(len(s) > 2 and s[2] < 0.999 for s in g.get("stops", []))


def _fill_box(pb: PageBuilder, fill, x, y, w, h, opacity, radius, report, o, path: str | None = None) -> None:
    """پرکردنِ یک جعبه با رنگ یا شیب (مسیر اختیاری، برای ellipse و گوشهٔ گرد)."""
    path = path or pb.path_rrect(x, y, w, h, radius or 0)
    if isinstance(fill, dict):
        if _alpha_gradient(fill):
            ppi = 96 if o.mode == "print" else 60
            wpx = max(2, min(1200, int(w * ppi / 25.4 if pb.ptu > 2 else w * 0.5)))
            hpx = max(2, min(1200, int(h * wpx / max(w, 1e-6))))
            gi = render_png.gradient_image(wpx, hpx, fill)
            nm = pb.add_image(gi, jpeg_q=o.jpeg_q, dpi=ppi)
            pb.op(f"q {path} W n {pb.alpha(opacity)}")
            pb.draw_image_xobj(nm, x, y, w, h)
            pb.op("Q")
            return
        sh = pb.shading(fill, x, y, w, h)
        pb.op(f"q {path} W n {pb.alpha(opacity)}/{sh} sh Q")
    else:
        pb.op(f"{pb.alpha(opacity)}{pb.rgb(fill)} {path} f")


def _stroke_ops(pb: PageBuilder, stroke: dict, path: str, dash=None) -> None:
    d = f"[{_f(pb.L(dash[0]))} {_f(pb.L(dash[1]))}] 0 d " if dash else ""
    pb.op(f"{d}{pb.rgb(stroke['color'], True)} {_f(pb.L(stroke['w']))} w {path} S")


def _shadow_raster(pb: PageBuilder, e: dict, o: Options) -> None:
    sh = e.get("shadow")
    if not sh or sh.get("opacity", 0) <= 0:
        return
    ppi = 96 if o.mode == "print" else 72
    k = (ppi / 25.4) if pb.ptu > 2 else 1.0
    r = render_png.Renderer(None, k)
    x, y, w, h = e["x"], e["y"], e["w"], e["h"]
    pad = float(sh.get("blur", 0)) * 1.8 + 2
    ox, oy = x - pad + float(sh.get("dx", 0)), y - pad + float(sh.get("dy", 0))
    W, H = w + 2 * pad, h + 2 * pad
    layer = Image.new("RGBA", (max(1, round(W * k)), max(1, round(H * k))), (0, 0, 0, 0))
    mask = render_png.shape_mask(max(1, round(w * k)), max(1, round(h * k)), [rr * k for rr in render_png._radii(e.get("radius", 0), w, h)] if e["type"] != "ellipse" else 0,
                                 "ellipse" if e["type"] == "ellipse" else "rect")
    e2 = {**e, "shadow": {**sh, "dx": 0, "dy": 0}}
    r._shadow(layer, e2, mask, round(pad * k), round(pad * k))
    nm = pb.add_image(layer, jpeg_q=o.jpeg_q, dpi=ppi)
    pb.op(pb.alpha(float(e.get("opacity", 1))).strip())
    pb.draw_image_xobj(nm, ox, oy, W, H)


def _draw_element(pb: PageBuilder, e: dict, src: images.ImageSource, o: Options, report: dict) -> None:
    t = e["type"]
    op = float(e.get("opacity", 1))
    if e.get("rot"):
        cx, cy = e["x"] + e["w"] / 2, e["y"] + e["h"] / 2
        a = math.radians(-float(e["rot"]))
        ca, sa = math.cos(a), math.sin(a)
        X, Y = pb.X(cx), pb.Y(cy)
        pb.op(f"1 0 0 1 {_f(X)} {_f(Y)} cm {_f(ca)} {_f(sa)} {_f(-sa)} {_f(ca)} 0 0 cm 1 0 0 1 {_f(-X)} {_f(-Y)} cm")
    if t == "rect":
        _shadow_raster(pb, e, o)
        if e.get("fill"):
            _fill_box(pb, e["fill"], e["x"], e["y"], e["w"], e["h"], op, e.get("radius"), report, o)
        if e.get("stroke"):
            _stroke_ops(pb, e["stroke"], pb.path_rrect(e["x"], e["y"], e["w"], e["h"], e.get("radius", 0)))
    elif t == "ellipse":
        _shadow_raster(pb, e, o)
        path = pb.path_ellipse(e["x"], e["y"], e["w"], e["h"])
        if e.get("fill"):
            _fill_box(pb, e["fill"], e["x"], e["y"], e["w"], e["h"], op, None, report, o, path=path)
        if e.get("stroke"):
            _stroke_ops(pb, e["stroke"], path)
    elif t == "line":
        st = e.get("stroke") or {"color": "#000000", "w": 0.3}
        path = f"{_f(pb.X(e['x']))} {_f(pb.Y(e['y']))} m {_f(pb.X(e['x'] + e['w']))} {_f(pb.Y(e['y'] + e['h']))} l"
        pb.op(pb.alpha(op).strip())
        _stroke_ops(pb, st, path, e.get("dash"))
    elif t == "image":
        _draw_image(pb, e, src, o, report)
    elif t == "text":
        _draw_text(pb, e, o, report)


def _draw_image(pb: PageBuilder, e: dict, src: images.ImageSource, o: Options, report: dict) -> None:
    x, y, w, h = e["x"], e["y"], e["w"], e["h"]
    op = float(e.get("opacity", 1))
    _shadow_raster(pb, e, o)
    w_in = (w * (1 / 25.4)) if pb.ptu > 2 else (w * pb.ptu / 72.0)
    h_in = (h * (1 / 25.4)) if pb.ptu > 2 else (h * pb.ptu / 72.0)
    target_w, target_h = max(2, int(w_in * o.dpi)), max(2, int(h_in * o.dpi))
    full = src.open(e.get("src", ""), int(max(target_w, target_h) * 2.2) + 16)
    clip = pb.path_rrect(x, y, w, h, e.get("radius", 0))
    if full is None:
        report.setdefault("missing_images", []).append(e.get("src", ""))
        pb.op(f"{pb.rgb('#e2e8f0')} {clip} f")
        return
    crop, dest = images.fit_rect(full.width, full.height, w, h, e.get("fit", "cover"), e.get("focus"))
    cw_px = max(1.0, crop[2] - crop[0])
    # dpi مؤثرِ تصویرِ اصلی در اندازهٔ چاپ (برای وارسیِ ۳۰۰ dpi)
    orig = src.size(e.get("src", "")) or full.size
    scale_back = orig[0] / max(1, full.width)
    eff = cw_px * scale_back / max(1e-6, (dest[2] / w) * w_in) if w_in else 0
    report.setdefault("images", []).append({"src": e.get("src", ""), "dpi": round(eff), "w_mm": round(w, 1) if pb.ptu > 2 else None, "id": e.get("id", "")})
    part = full.crop(tuple(int(round(v)) for v in crop))
    dw_px = max(2, min(part.width, int(round(target_w * dest[2] / w))))
    dh_px = max(2, min(part.height, int(round(target_h * dest[3] / h))))
    if (dw_px, dh_px) != part.size:
        part = part.resize((dw_px, dh_px), Image.LANCZOS)
    nm = pb.add_image(part, jpeg_q=o.jpeg_q, dpi=o.dpi)
    pb.op(f"{clip} W n {pb.alpha(op)}".strip())
    pb.draw_image_xobj(nm, x + dest[0], y + dest[1], dest[2], dest[3])
    if e.get("stroke"):
        _stroke_ops(pb, e["stroke"], clip)


def _draw_text(pb: PageBuilder, e: dict, o: Options, report: dict) -> None:
    lay = e.get("lay")
    if not lay or not lay["lines"]:
        return
    op = float(e.get("opacity", 1))
    if e.get("bg"):
        pad = float(e.get("pad", 0))
        _fill_box(pb, e["bg"], e["x"] - pad, e["y"] - pad, e["w"] + 2 * pad, (lay["h"] if e["h"] <= 0 else e["h"]) + 2 * pad, op, e.get("bg_radius", 0), report, o)
    size = lay["size"]
    out_pt = size * pb.ptu
    em_px = outline.em_pixels(out_pt, o.outline_quality)
    ops = []
    for ln in lay["lines"]:
        if not ln["t"].strip():
            continue
        pieces = ln["words"] if ln.get("words") else [{"t": ln["t"], "x": ln["x"]}]
        for pc in pieces:
            polys, _ = outline.line_contours(pc["t"], e["font"], e["weight"], ln["rtl"], em_px, o.eps)
            tx = e["x"] + pc["x"]
            ty = e["y"] + ln["y"] + lay["baseline"]
            for poly in polys:
                pts = [(pb.X(tx + px * size), pb.Y(ty + py * size)) for px, py in poly]
                ops.append(f"{_f(pts[0][0])} {_f(pts[0][1])} m " + " ".join(f"{_f(a)} {_f(b)} l" for a, b in pts[1:]) + " h")
    if ops:
        pb.op(f"{pb.alpha(op)}{pb.rgb(e['color'])}")
        for i in range(0, len(ops), 400):
            pb.op(" ".join(ops[i:i + 400]) + " f*")
    if e.get("underline") or e.get("strike"):
        th = size * 0.06
        for ln in lay["lines"]:
            if not ln["t"].strip():
                continue
            lx = e["x"] + ln["x"]
            base = e["y"] + ln["y"] + lay["baseline"]
            if e.get("underline"):
                pb.op(f"{pb.rgb(e['color'])} {_f(pb.X(lx))} {_f(pb.Y(base + size * 0.12 + th))} {_f(pb.L(ln['w']))} {_f(pb.L(th))} re f")
            if e.get("strike"):
                pb.op(f"{pb.rgb(e['color'])} {_f(pb.X(lx))} {_f(pb.Y(base - size * 0.28 + th))} {_f(pb.L(ln['w']))} {_f(pb.L(th))} re f")


def build_pdf(pages: list[dict], src: images.ImageSource, *, unit: str = "mm", options: dict | None = None, title: str = "", author: str = "",
              subject: str = "", rtl: bool = True, bookmarks: list[tuple[str, int, int]] | None = None, page_ptu: float | None = None) -> tuple[bytes, dict]:
    """صفحه‌های صحنه ⇒ (بایتِ PDF، گزارش). unit: «mm» (چاپ) یا «px» (اسلاید/UI؛ هر واحد = ۰٫۵ پوینت ⇒ ۱۹۲۰ px = ۹۶۰ pt)."""
    o = Options(**{**(PRINT if (options or {}).get("mode", "print") == "print" else SCREEN), **(options or {})})
    ptu = page_ptu or (PT_PER_MM if unit == "mm" else 0.5)
    doc = PdfDoc(title=title, author=author, subject=subject, rtl=rtl)
    report: dict = {"pages": len(pages), "mode": o.mode, "dpi": o.dpi, "unit": unit}
    o.page_ids = {p.get("id"): i for i, p in enumerate(pages) if p.get("id")}
    for i, page in enumerate(pages):
        bleed = float(page.get("bleed", 0)) if o.bleed else 0.0
        slug = 7.0 if (o.marks and bleed) else 0.0
        pb = doc.new_page(page["w"], page["h"], bleed=bleed, slug=slug, ptu=ptu)
        draw_page(pb, page, src, o, ptu, i, report)
    for t, pi, lvl in bookmarks or []:
        doc.bookmark(t, pi, lvl)
    data = doc.save()
    report["bytes"] = len(data)
    if pages:
        p0 = doc.pages[0]
        report["media_pt"] = [round(p0.mw, 2), round(p0.mh, 2)]
        report["trim_mm"] = [pages[0]["w"], pages[0]["h"]] if unit == "mm" else None
        report["bleed_mm"] = float(pages[0].get("bleed", 0)) if o.bleed and unit == "mm" else 0.0
        report["marks"] = bool(o.marks and p0.slug)
    return data, report
