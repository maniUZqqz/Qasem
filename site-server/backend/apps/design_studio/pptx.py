"""نویسندهٔ PPTX (بی‌وابستگی؛ فقط zipfile): هر صفحه/اسلاید یک اسلایدِ قابل‌ویرایش — متنِ زنده (راست‌به‌چپ)، شکل، تصویر، یادداشتِ گوینده و پیوند.

ساختار همان بستهٔ استانداردِ OOXML است (presentation + master + layout + theme + slides + notesMaster + notesSlides) تا PowerPoint، LibreOffice،
Keynote و Google Slides بازش کنند. فونت‌ها جاسازی نمی‌شوند (راهنما: «فونت‌های غیرپیش‌فرض باید جاسازی شوند») — بستهٔ تحویل فونت‌ها و مجوزشان را کنارِ فایل می‌گذارد.
"""
from __future__ import annotations

import io
import math
import zipfile
from xml.sax.saxutils import escape

from PIL import Image

from . import colors, fonts, images, render_png, typeset

NS = ('xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
      'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"')
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
CSS_FAMILY = {"vazirmatn": "Vazirmatn", "estedad": "Estedad", "lalezar": "Lalezar", "shabnam": "Shabnam", "sahel": "Sahel", "samim": "Samim"}
MAX_IMG_SIDE = 2200


def _hex(c: str) -> str:
    return colors.norm(c).lstrip("#").upper()


def _x(s) -> str:
    return escape(str(s), {'"': "&quot;"})


class Deck:
    def __init__(self, width: float, height: float, unit: str, *, title: str = "", author: str = "NMarketing", rtl: bool = True, accent: str = "#126f85",
                 body_font: str = "vazirmatn", head_font: str = "vazirmatn"):
        self.unit = unit
        self.k = 36000.0 if unit == "mm" else 6350.0                  # EMU بر واحدِ صحنه
        self.pt = (72.0 / 25.4) if unit == "mm" else 0.5               # پوینت بر واحدِ صحنه
        self.cx, self.cy = round(width * self.k), round(height * self.k)
        self.title, self.author, self.rtl = title, author, rtl
        self.accent, self.body_font, self.head_font = accent, body_font, head_font
        self.slides: list[dict] = []
        self.media: dict[str, bytes] = {}

    def emu(self, v: float) -> int:
        return int(round(v * self.k))


# ───────────────────────────── عنصرها

def _fill_xml(fill, opacity: float = 1.0) -> str:
    if not fill:
        return "<a:noFill/>"
    if isinstance(fill, dict):
        stops = []
        for s in fill["stops"]:
            a = (s[2] if len(s) > 2 else 1.0) * opacity
            al = f'<a:alpha val="{int(round(a * 100000))}"/>' if a < 0.999 else ""
            stops.append(f'<a:gs pos="{int(round(s[0] * 100000))}"><a:srgbClr val="{_hex(s[1])}">{al}</a:srgbClr></a:gs>')
        if fill.get("type") == "radial":
            return f'<a:gradFill rotWithShape="1"><a:gsLst>{"".join(stops)}</a:gsLst><a:path path="circle"><a:fillToRect l="50000" t="50000" r="50000" b="50000"/></a:path></a:gradFill>'
        ang = int(round((float(fill.get("angle", 90)) % 360) * 60000))
        return f'<a:gradFill rotWithShape="1"><a:gsLst>{"".join(stops)}</a:gsLst><a:lin ang="{ang}" scaled="0"/></a:gradFill>'
    al = f'<a:alpha val="{int(round(opacity * 100000))}"/>' if opacity < 0.999 else ""
    return f'<a:solidFill><a:srgbClr val="{_hex(fill)}">{al}</a:srgbClr></a:solidFill>'


def _ln_xml(d: Deck, stroke, dash=None) -> str:
    if not stroke or not stroke.get("w"):
        return "<a:ln><a:noFill/></a:ln>"
    ds = '<a:prstDash val="dash"/>' if dash else ""
    return f'<a:ln w="{d.emu(stroke["w"])}"><a:solidFill><a:srgbClr val="{_hex(stroke["color"])}"/></a:solidFill>{ds}</a:ln>'


def _shadow_xml(d: Deck, sh) -> str:
    if not sh or sh.get("opacity", 0) <= 0:
        return ""
    dist = math.hypot(sh.get("dx", 0), sh.get("dy", 0))
    ang = math.degrees(math.atan2(sh.get("dy", 0), sh.get("dx", 0))) % 360
    return (f'<a:effectLst><a:outerShdw blurRad="{d.emu(sh.get("blur", 0))}" dist="{d.emu(dist)}" dir="{int(ang * 60000)}" algn="ctr" rotWithShape="0">'
            f'<a:srgbClr val="{_hex(sh.get("color", "#000000"))}"><a:alpha val="{int(sh.get("opacity", 0.2) * 100000)}"/></a:srgbClr></a:outerShdw></a:effectLst>')


class SlideBuilder:
    def __init__(self, deck: Deck, index: int):
        self.d, self.i = deck, index
        self.shapes: list[str] = []
        self.rels: list[tuple[str, str, str, bool]] = []          # (rId، type، target، external)
        self.next_id = 2

    def sid(self) -> int:
        self.next_id += 1
        return self.next_id

    def rel(self, typ: str, target: str, external: bool = False) -> str:
        for rid, t, tg, ext in self.rels:
            if t == typ and tg == target:
                return rid
        rid = f"rId{len(self.rels) + 2}"                              # rId1 = layout
        self.rels.append((rid, typ, target, external))
        return rid

    def hlink(self, link: dict | None, page_ids: dict[str, int]) -> str:
        if not link:
            return ""
        if link.get("url"):
            rid = self.rel(f"{REL}/hyperlink", link["url"], True)
            return f'<a:hlinkClick r:id="{rid}"/>'
        pid = link.get("page")
        if pid in page_ids:
            rid = self.rel(f"{REL}/slide", f"slide{page_ids[pid] + 1}.xml")
            return f'<a:hlinkClick r:id="{rid}" action="ppaction://hlinksldjump"/>'
        return ""


def _xfrm(d: Deck, e: dict, tag: str = "a:xfrm") -> str:
    rot = f' rot="{int(round(float(e["rot"]) * 60000))}"' if e.get("rot") else ""
    return (f'<{tag}{rot}><a:off x="{d.emu(e["x"])}" y="{d.emu(e["y"])}"/><a:ext cx="{max(1, d.emu(e["w"]))}" cy="{max(1, d.emu(e["h"]))}"/></{tag}>')


def _geom(d: Deck, e: dict, kind: str) -> str:
    if kind == "ellipse":
        return '<a:prstGeom prst="ellipse"><a:avLst/></a:prstGeom>'
    rs = render_png._radii(e.get("radius", 0), e["w"], e["h"])
    if max(rs) <= 0:
        return '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom>'
    adj = int(min(50000, round(max(rs) / max(1e-6, min(e["w"], e["h"])) * 100000)))
    return f'<a:prstGeom prst="roundRect"><a:avLst><a:gd name="adj" fmla="val {adj}"/></a:avLst></a:prstGeom>'


def _shape(sb: SlideBuilder, e: dict, page_ids: dict) -> None:
    d = sb.d
    i = sb.sid()
    kind = "ellipse" if e["type"] == "ellipse" else "rect"
    h = sb.hlink(e.get("link"), page_ids)
    name = _x(e.get("name") or e["id"])
    sb.shapes.append(
        f'<p:sp><p:nvSpPr><p:cNvPr id="{i}" name="{name}">{h}</p:cNvPr><p:cNvSpPr/><p:nvPr/></p:nvSpPr><p:spPr>{_xfrm(d, e)}{_geom(d, e, kind)}'
        f'{_fill_xml(e.get("fill"), float(e.get("opacity", 1)))}{_ln_xml(d, e.get("stroke"))}{_shadow_xml(d, e.get("shadow"))}</p:spPr>'
        f'<p:txBody><a:bodyPr rtlCol="1" anchor="ctr"/><a:lstStyle/><a:p><a:endParaRPr lang="fa-IR"/></a:p></p:txBody></p:sp>')


def _line(sb: SlideBuilder, e: dict) -> None:
    d = sb.d
    i = sb.sid()
    x, y, w, h = e["x"], e["y"], e["w"], e["h"]
    flip = (' flipH="1"' if w < 0 else "") + (' flipV="1"' if h < 0 else "")
    sb.shapes.append(
        f'<p:cxnSp><p:nvCxnSpPr><p:cNvPr id="{i}" name="{_x(e["id"])}"/><p:cNvCxnSpPr/><p:nvPr/></p:nvCxnSpPr><p:spPr>'
        f'<a:xfrm{flip}><a:off x="{d.emu(min(x, x + w))}" y="{d.emu(min(y, y + h))}"/><a:ext cx="{d.emu(abs(w))}" cy="{d.emu(abs(h))}"/></a:xfrm>'
        f'<a:prstGeom prst="line"><a:avLst/></a:prstGeom>{_ln_xml(d, e.get("stroke") or {"color": "#000000", "w": 0.3}, e.get("dash"))}</p:spPr></p:cxnSp>')


def _picture(sb: SlideBuilder, e: dict, src: images.ImageSource, page_ids: dict) -> None:
    d = sb.d
    im = src.open(e.get("src", ""), MAX_IMG_SIDE)
    if im is None:
        _shape(sb, {**e, "type": "rect", "fill": "#e2e8f0", "name": "تصویر پیدا نشد"}, page_ids)
        return
    crop, dest = images.fit_rect(im.width, im.height, e["w"], e["h"], e.get("fit", "cover"), e.get("focus"))
    n = len(d.media) + 1
    buf = io.BytesIO()
    if im.mode == "RGBA" and im.getchannel("A").getextrema()[0] < 255:
        im.save(buf, "PNG", optimize=True)
        ext = "png"
    else:
        im.convert("RGB").save(buf, "JPEG", quality=88, optimize=True)
        ext = "jpeg"
    fname = f"image{n}.{ext}"
    d.media[fname] = buf.getvalue()
    rid = sb.rel(f"{REL}/image", f"../media/{fname}")
    iw, ih = im.size
    l, t = int(round(crop[0] / iw * 100000)), int(round(crop[1] / ih * 100000))
    r, b = int(round((iw - crop[2]) / iw * 100000)), int(round((ih - crop[3]) / ih * 100000))
    box = {**e, "x": e["x"] + dest[0], "y": e["y"] + dest[1], "w": dest[2], "h": dest[3]}
    i = sb.sid()
    h = sb.hlink(e.get("link"), page_ids)
    alt = _x(e.get("alt") or e.get("name") or "")
    op = float(e.get("opacity", 1))
    blip = f'<a:blip r:embed="{rid}">' + (f'<a:alphaModFix amt="{int(op * 100000)}"/>' if op < 0.999 else "") + "</a:blip>"
    sb.shapes.append(
        f'<p:pic><p:nvPicPr><p:cNvPr id="{i}" name="{_x(e["id"])}" descr="{alt}">{h}</p:cNvPr><p:cNvPicPr><a:picLocks noChangeAspect="1"/></p:cNvPicPr><p:nvPr/></p:nvPicPr>'
        f'<p:blipFill>{blip}<a:srcRect l="{l}" t="{t}" r="{r}" b="{b}"/><a:stretch><a:fillRect/></a:stretch></p:blipFill>'
        f'<p:spPr>{_xfrm(d, box)}{_geom(d, box, "rect")}{_ln_xml(d, e.get("stroke"))}{_shadow_xml(d, e.get("shadow"))}</p:spPr></p:pic>')


def _text(sb: SlideBuilder, e: dict, page_ids: dict) -> None:
    d = sb.d
    lay = e.get("lay")
    if not lay or not str(e.get("text", "")).strip():
        return
    if e.get("bg"):
        pad = float(e.get("pad", 0))
        _shape(sb, {"id": e["id"] + "-bg", "type": "rect", "x": e["x"] - pad, "y": e["y"] - pad, "w": e["w"] + 2 * pad,
                    "h": (lay["h"] if e["h"] <= 0 else e["h"]) + 2 * pad, "fill": e["bg"], "radius": e.get("bg_radius", 0), "opacity": e.get("opacity", 1)}, page_ids)
    size = lay["size"]
    sz = max(100, int(round(size * d.pt * 100)))
    asc, desc = typeset.metrics(e["font"], e["weight"], 1.0)
    natural = max(0.9, asc + desc)
    spc = int(round(max(0.6, min(3.0, e["lh"] / natural)) * 100000))
    fam = CSS_FAMILY.get(e["font"], "Vazirmatn")
    bold = ' b="1"' if e["weight"] >= 600 else ""
    extra = (' u="sng"' if e.get("underline") else "") + (' strike="sngStrike"' if e.get("strike") else "")
    op = float(e.get("opacity", 1))
    fill = _fill_xml(e["color"], op)
    h = sb.hlink(e.get("link"), page_ids)
    paras = []
    for para in str(e["text"]).split("\n"):
        rtl = typeset.is_rtl(para, e.get("dir", "auto"))
        al = e["align"] if e["align"] != "auto" else ("right" if rtl else "left")
        if e.get("justify") and al in ("right", "left"):
            al = "justify"
        algn = {"right": "r", "left": "l", "center": "ctr", "justify": "just"}.get(al, "r")
        if not para.strip():
            paras.append(f'<a:p><a:pPr algn="{algn}" rtl="{1 if rtl else 0}"><a:lnSpc><a:spcPct val="{spc}"/></a:lnSpc></a:pPr><a:endParaRPr lang="fa-IR" sz="{sz}"/></a:p>')
            continue
        lang = "fa-IR" if rtl else "en-US"
        paras.append(
            f'<a:p><a:pPr algn="{algn}" rtl="{1 if rtl else 0}"><a:lnSpc><a:spcPct val="{spc}"/></a:lnSpc><a:spcBef><a:spcPts val="0"/></a:spcBef></a:pPr>'
            f'<a:r><a:rPr lang="{lang}" sz="{sz}"{bold}{extra} dirty="0">{fill}<a:latin typeface="{fam}"/><a:cs typeface="{fam}"/>{h.replace("a:hlinkClick", "a:hlinkClick") if h else ""}</a:rPr>'
            f'<a:t>{_x(para)}</a:t></a:r></a:p>')
    anchor = {"top": "t", "middle": "ctr", "bottom": "b"}.get(e.get("valign", "top"), "t")
    box = {**e, "w": e["w"] * 1.005, "h": e["h"] if e["h"] > 0 else lay["h"]}
    if "align" in e and (e["align"] == "right" or (e["align"] == "auto" and lay["lines"] and lay["lines"][0]["rtl"])):
        box["x"] = e["x"] - e["w"] * 0.005                              # عرضِ اضافه به سمتِ چپ (راست‌چین)
    i = sb.sid()
    sb.shapes.append(
        f'<p:sp><p:nvSpPr><p:cNvPr id="{i}" name="{_x(e.get("name") or e["id"])}"/><p:cNvSpPr txBox="1"/><p:nvPr/></p:nvSpPr><p:spPr>{_xfrm(d, box)}'
        f'<a:prstGeom prst="rect"><a:avLst/></a:prstGeom><a:noFill/></p:spPr><p:txBody><a:bodyPr wrap="square" lIns="0" tIns="0" rIns="0" bIns="0" rtlCol="1" '
        f'anchor="{anchor}"><a:noAutofit/></a:bodyPr><a:lstStyle/>{"".join(paras)}</p:txBody></p:sp>')


# ───────────────────────────── بسته

def add_slide(deck: Deck, page: dict, src: images.ImageSource, *, page_ids: dict[str, int], notes: str = "") -> None:
    sb = SlideBuilder(deck, len(deck.slides) + 1)
    for e in page["elements"]:
        if e.get("hidden"):
            continue
        t = e["type"]
        if t in ("rect", "ellipse"):
            _shape(sb, e, page_ids)
        elif t == "line":
            _line(sb, e)
        elif t == "image":
            _picture(sb, e, src, page_ids)
        elif t == "text":
            _text(sb, e, page_ids)
    deck.slides.append({"page": page, "sb": sb, "notes": notes or page.get("notes", "")})


def _bg_xml(bg) -> str:
    if not bg:
        return '<p:bg><p:bgPr><a:solidFill><a:srgbClr val="FFFFFF"/></a:solidFill><a:effectLst/></p:bgPr></p:bg>'
    return f"<p:bg><p:bgPr>{_fill_xml(bg)}<a:effectLst/></p:bgPr></p:bg>"


def _slide_xml(sl: dict) -> str:
    sb: SlideBuilder = sl["sb"]
    return (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<p:sld {NS}><p:cSld name="{_x(sl["page"].get("name", ""))}">{_bg_xml(sl["page"].get("bg"))}<p:spTree>'
            f'<p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/>'
            f'<a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>{"".join(sb.shapes)}</p:spTree></p:cSld>'
            f'<p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sld>')


def _rels_xml(items: list[tuple[str, str, str, bool]]) -> str:
    rows = "".join(f'<Relationship Id="{rid}" Type="{typ}" Target="{_x(tg)}"{" TargetMode=" + chr(34) + "External" + chr(34) if ext else ""}/>' for rid, typ, tg, ext in items)
    return f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">{rows}</Relationships>'


def _theme_xml(deck: Deck, name: str = "NM") -> str:
    a = _hex(deck.accent)
    sec = _hex(colors.darken(deck.accent, 0.35))
    return f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<a:theme xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" name="{name}"><a:themeElements><a:clrScheme name="{name}"><a:dk1><a:srgbClr val="1B2B45"/></a:dk1><a:lt1><a:srgbClr val="FFFFFF"/></a:lt1><a:dk2><a:srgbClr val="{sec}"/></a:dk2><a:lt2><a:srgbClr val="F7FAFF"/></a:lt2><a:accent1><a:srgbClr val="{a}"/></a:accent1><a:accent2><a:srgbClr val="{sec}"/></a:accent2><a:accent3><a:srgbClr val="DBE6FF"/></a:accent3><a:accent4><a:srgbClr val="F59E0B"/></a:accent4><a:accent5><a:srgbClr val="16A34A"/></a:accent5><a:accent6><a:srgbClr val="DC2626"/></a:accent6><a:hlink><a:srgbClr val="{a}"/></a:hlink><a:folHlink><a:srgbClr val="{sec}"/></a:folHlink></a:clrScheme><a:fontScheme name="{name}"><a:majorFont><a:latin typeface="{CSS_FAMILY.get(deck.head_font, 'Vazirmatn')}"/><a:ea typeface=""/><a:cs typeface="{CSS_FAMILY.get(deck.head_font, 'Vazirmatn')}"/></a:majorFont><a:minorFont><a:latin typeface="{CSS_FAMILY.get(deck.body_font, 'Vazirmatn')}"/><a:ea typeface=""/><a:cs typeface="{CSS_FAMILY.get(deck.body_font, 'Vazirmatn')}"/></a:minorFont></a:fontScheme><a:fmtScheme name="{name}"><a:fillStyleLst><a:solidFill><a:schemeClr val="phClr"/></a:solidFill><a:solidFill><a:schemeClr val="phClr"/></a:solidFill><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:fillStyleLst><a:lnStyleLst><a:ln w="6350"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:ln><a:ln w="12700"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:ln><a:ln w="19050"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:ln></a:lnStyleLst><a:effectStyleLst><a:effectStyle><a:effectLst/></a:effectStyle><a:effectStyle><a:effectLst/></a:effectStyle><a:effectStyle><a:effectLst/></a:effectStyle></a:effectStyleLst><a:bgFillStyleLst><a:solidFill><a:schemeClr val="phClr"/></a:solidFill><a:solidFill><a:schemeClr val="phClr"/></a:solidFill><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:bgFillStyleLst></a:fmtScheme></a:themeElements><a:objectDefaults/><a:extraClrSchemeLst/></a:theme>'''


def _master_xml() -> str:
    lvl = '<a:lvl1pPr algn="r" rtl="1" defTabSz="914400"><a:defRPr sz="1800"><a:solidFill><a:schemeClr val="tx1"/></a:solidFill><a:latin typeface="+mn-lt"/><a:cs typeface="+mn-cs"/></a:defRPr></a:lvl1pPr>'
    return (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<p:sldMaster {NS}><p:cSld><p:bg><p:bgRef idx="1001"><a:schemeClr val="bg1"/></p:bgRef></p:bg><p:spTree>'
            f'<p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/><a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>'
            f'</p:spTree></p:cSld><p:clrMap bg1="lt1" tx1="dk1" bg2="lt2" tx2="dk2" accent1="accent1" accent2="accent2" accent3="accent3" accent4="accent4" accent5="accent5" accent6="accent6" hlink="hlink" folHlink="folHlink"/>'
            f'<p:sldLayoutIdLst><p:sldLayoutId id="2147483649" r:id="rId1"/></p:sldLayoutIdLst><p:txStyles><p:titleStyle>{lvl}</p:titleStyle><p:bodyStyle>{lvl}</p:bodyStyle><p:otherStyle>{lvl}</p:otherStyle></p:txStyles></p:sldMaster>')


def _layout_xml() -> str:
    return (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<p:sldLayout {NS} type="blank" preserve="1"><p:cSld name="Blank"><p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>'
            f'<p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/><a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr></p:spTree></p:cSld><p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sldLayout>')


def _notes_master_xml(deck: Deck) -> str:
    return (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<p:notesMaster {NS}><p:cSld><p:bg><p:bgRef idx="1001"><a:schemeClr val="bg1"/></p:bgRef></p:bg><p:spTree>'
            f'<p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/><a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>'
            f'<p:sp><p:nvSpPr><p:cNvPr id="2" name="Slide Image Placeholder 1"/><p:cNvSpPr><a:spLocks noGrp="1" noRot="1" noChangeAspect="1"/></p:cNvSpPr><p:nvPr><p:ph type="sldImg" idx="2"/></p:nvPr></p:nvSpPr>'
            f'<p:spPr><a:xfrm><a:off x="685800" y="1143000"/><a:ext cx="5486400" cy="3086100"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom><a:noFill/><a:ln w="12700"><a:solidFill><a:prstClr val="black"/></a:solidFill></a:ln></p:spPr></p:sp>'
            f'<p:sp><p:nvSpPr><p:cNvPr id="3" name="Notes Placeholder 2"/><p:cNvSpPr><a:spLocks noGrp="1"/></p:cNvSpPr><p:nvPr><p:ph type="body" sz="quarter" idx="3"/></p:nvPr></p:nvSpPr>'
            f'<p:spPr><a:xfrm><a:off x="685800" y="4400550"/><a:ext cx="5486400" cy="3600450"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></p:spPr>'
            f'<p:txBody><a:bodyPr vert="horz" lIns="91440" tIns="45720" rIns="91440" bIns="45720" rtlCol="1"/><a:lstStyle/><a:p><a:pPr lvl="0" algn="r" rtl="1"/><a:r><a:rPr lang="fa-IR"/><a:t>یادداشت</a:t></a:r></a:p></p:txBody></p:sp>'
            f'</p:spTree></p:cSld><p:clrMap bg1="lt1" tx1="dk1" bg2="lt2" tx2="dk2" accent1="accent1" accent2="accent2" accent3="accent3" accent4="accent4" accent5="accent5" accent6="accent6" hlink="hlink" folHlink="folHlink"/>'
            f'<p:notesStyle><a:lvl1pPr marL="0" algn="r" rtl="1" defTabSz="914400"><a:defRPr sz="1200"><a:solidFill><a:schemeClr val="tx1"/></a:solidFill><a:latin typeface="+mn-lt"/><a:cs typeface="+mn-cs"/></a:defRPr></a:lvl1pPr></p:notesStyle></p:notesMaster>')


def _notes_xml(text: str) -> str:
    paras = "".join(f'<a:p><a:pPr algn="r" rtl="1"/><a:r><a:rPr lang="fa-IR" dirty="0"/><a:t>{_x(t)}</a:t></a:r></a:p>' for t in (text.split("\n") if text else [""]))
    return (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<p:notes {NS}><p:cSld><p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>'
            f'<p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/><a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>'
            f'<p:sp><p:nvSpPr><p:cNvPr id="2" name="Slide Image Placeholder 1"/><p:cNvSpPr><a:spLocks noGrp="1" noRot="1" noChangeAspect="1"/></p:cNvSpPr><p:nvPr><p:ph type="sldImg"/></p:nvPr></p:nvSpPr><p:spPr/></p:sp>'
            f'<p:sp><p:nvSpPr><p:cNvPr id="3" name="Notes Placeholder 2"/><p:cNvSpPr><a:spLocks noGrp="1"/></p:cNvSpPr><p:nvPr><p:ph type="body" idx="1"/></p:nvPr></p:nvSpPr><p:spPr/>'
            f'<p:txBody><a:bodyPr rtlCol="1"/><a:lstStyle/>{paras}</p:txBody></p:sp></p:spTree></p:cSld><p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:notes>')


def save(deck: Deck) -> bytes:
    n = len(deck.slides)
    ct = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
          '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/>'
          '<Default Extension="png" ContentType="image/png"/><Default Extension="jpeg" ContentType="image/jpeg"/><Default Extension="jpg" ContentType="image/jpeg"/>'
          '<Override PartName="/ppt/presentation.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/>'
          '<Override PartName="/ppt/slideMasters/slideMaster1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideMaster+xml"/>'
          '<Override PartName="/ppt/slideLayouts/slideLayout1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideLayout+xml"/>'
          '<Override PartName="/ppt/theme/theme1.xml" ContentType="application/vnd.openxmlformats-officedocument.theme+xml"/>'
          '<Override PartName="/ppt/theme/theme2.xml" ContentType="application/vnd.openxmlformats-officedocument.theme+xml"/>'
          '<Override PartName="/ppt/notesMasters/notesMaster1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.notesMaster+xml"/>'
          '<Override PartName="/ppt/presProps.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.presProps+xml"/>'
          '<Override PartName="/ppt/viewProps.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.viewProps+xml"/>'
          '<Override PartName="/ppt/tableStyles.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.tableStyles+xml"/>'
          '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>'
          '<Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>']
    for i in range(1, n + 1):
        ct.append(f'<Override PartName="/ppt/slides/slide{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>')
        ct.append(f'<Override PartName="/ppt/notesSlides/notesSlide{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.notesSlide+xml"/>')
    ct.append("</Types>")
    pres_rels = [("rId1", f"{REL}/slideMaster", "slideMasters/slideMaster1.xml", False)]
    for i in range(1, n + 1):
        pres_rels.append((f"rId{i + 1}", f"{REL}/slide", f"slides/slide{i}.xml", False))
    pres_rels += [(f"rId{n + 2}", f"{REL}/notesMaster", "notesMasters/notesMaster1.xml", False),
                  (f"rId{n + 3}", f"{REL}/presProps", "presProps.xml", False), (f"rId{n + 4}", f"{REL}/viewProps", "viewProps.xml", False),
                  (f"rId{n + 5}", f"{REL}/theme", "theme/theme1.xml", False), (f"rId{n + 6}", f"{REL}/tableStyles", "tableStyles.xml", False)]
    sld_ids = "".join(f'<p:sldId id="{256 + i}" r:id="rId{i + 1}"/>' for i in range(1, n + 1))
    pres = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<p:presentation {NS}{" rtl=" + chr(34) + "1" + chr(34) if deck.rtl else ""} saveSubsetFonts="1">'
            f'<p:sldMasterIdLst><p:sldMasterId id="2147483648" r:id="rId1"/></p:sldMasterIdLst><p:notesMasterIdLst><p:notesMasterId r:id="rId{n + 2}"/></p:notesMasterIdLst>'
            f'<p:sldIdLst>{sld_ids}</p:sldIdLst><p:sldSz cx="{deck.cx}" cy="{deck.cy}"/><p:notesSz cx="6858000" cy="9144000"/>'
            f'<p:defaultTextStyle><a:lvl1pPr algn="r" rtl="1"><a:defRPr sz="1800"><a:latin typeface="+mn-lt"/><a:cs typeface="+mn-cs"/></a:defRPr></a:lvl1pPr></p:defaultTextStyle></p:presentation>')
    core = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
            'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
            f'<dc:title>{_x(deck.title)}</dc:title><dc:creator>{_x(deck.author)}</dc:creator><dc:language>fa-IR</dc:language></cp:coreProperties>')
    app = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties">'
           f'<Application>NMarketing Design Studio</Application><Slides>{n}</Slides></Properties>')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", "".join(ct))
        z.writestr("_rels/.rels", _rels_xml([("rId1", f"{REL}/officeDocument", "ppt/presentation.xml", False),
                                              ("rId2", "http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties", "docProps/core.xml", False),
                                              ("rId3", f"{REL}/extended-properties", "docProps/app.xml", False)]))
        z.writestr("docProps/core.xml", core)
        z.writestr("docProps/app.xml", app)
        z.writestr("ppt/presentation.xml", pres)
        z.writestr("ppt/_rels/presentation.xml.rels", _rels_xml(pres_rels))
        z.writestr("ppt/presProps.xml", f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<p:presentationPr {NS}/>')
        z.writestr("ppt/viewProps.xml", f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<p:viewPr {NS}><p:normalViewPr><p:restoredLeft sz="15620"/><p:restoredTop sz="94660"/></p:normalViewPr></p:viewPr>')
        z.writestr("ppt/tableStyles.xml", '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<a:tblStyleLst xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" def="{5C22544A-7EE6-4342-B048-85BDC9FD1C3A}"/>')
        z.writestr("ppt/theme/theme1.xml", _theme_xml(deck))
        z.writestr("ppt/theme/theme2.xml", _theme_xml(deck, "NMNotes"))
        z.writestr("ppt/slideMasters/slideMaster1.xml", _master_xml())
        z.writestr("ppt/slideMasters/_rels/slideMaster1.xml.rels", _rels_xml([("rId1", f"{REL}/slideLayout", "../slideLayouts/slideLayout1.xml", False),
                                                                             ("rId2", f"{REL}/theme", "../theme/theme1.xml", False)]))
        z.writestr("ppt/slideLayouts/slideLayout1.xml", _layout_xml())
        z.writestr("ppt/slideLayouts/_rels/slideLayout1.xml.rels", _rels_xml([("rId1", f"{REL}/slideMaster", "../slideMasters/slideMaster1.xml", False)]))
        z.writestr("ppt/notesMasters/notesMaster1.xml", _notes_master_xml(deck))
        z.writestr("ppt/notesMasters/_rels/notesMaster1.xml.rels", _rels_xml([("rId1", f"{REL}/theme", "../theme/theme2.xml", False)]))
        for i, sl in enumerate(deck.slides, 1):
            sb: SlideBuilder = sl["sb"]
            z.writestr(f"ppt/slides/slide{i}.xml", _slide_xml(sl))
            rels = [("rId1", f"{REL}/slideLayout", "../slideLayouts/slideLayout1.xml", False)] + list(sb.rels)
            rels.append((f"rId{len(rels) + 1}", f"{REL}/notesSlide", f"../notesSlides/notesSlide{i}.xml", False))
            z.writestr(f"ppt/slides/_rels/slide{i}.xml.rels", _rels_xml(rels))
            z.writestr(f"ppt/notesSlides/notesSlide{i}.xml", _notes_xml(sl["notes"]))
            z.writestr(f"ppt/notesSlides/_rels/notesSlide{i}.xml.rels", _rels_xml([("rId1", f"{REL}/notesMaster", "../notesMasters/notesMaster1.xml", False),
                                                                                  ("rId2", f"{REL}/slide", f"../slides/slide{i}.xml", False)]))
        for name, data in deck.media.items():
            z.writestr(f"ppt/media/{name}", data)
    return buf.getvalue()


def build_pptx(pages: list[dict], src: images.ImageSource, *, unit: str = "mm", title: str = "", author: str = "NMarketing", accent: str = "#126f85",
               body_font: str = "vazirmatn", head_font: str = "vazirmatn", rtl: bool = True) -> bytes:
    """صفحه‌های صحنه ⇒ PPTX. اندازهٔ اسلاید = اندازهٔ برشِ صفحهٔ اول؛ یادداشتِ هر صفحه = page['notes']."""
    if not pages:
        raise ValueError("صفحه‌ای برای خروجی نیست.")
    deck = Deck(pages[0]["w"], pages[0]["h"], unit, title=title, author=author, rtl=rtl, accent=accent, body_font=body_font, head_font=head_font)
    page_ids = {p.get("id"): i for i, p in enumerate(pages) if p.get("id")}
    for p in pages:
        add_slide(deck, p, src, page_ids=page_ids)
    return save(deck)
