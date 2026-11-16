# -*- coding: utf-8 -*-
"""بلوکِ «قطعهٔ 21st» (نوعِ ``c21``): یک قطعهٔ تبدیل‌شده (c21_convert) در صفحه؛ رندر، CSS، پیش‌نمایش، پیشنهاد برای AI.

سندِ صفحه فقط ``{ref, texts:[{v}], links:[{u}], images:[{src, alt}]}`` را نگه می‌دارد؛ HTML و CSS از رکوردِ تبدیل‌شده می‌آیند و همیشه از فهرستِ سفیدِ پاک‌سازی گذشته‌اند.
متنِ هر شکاف روی بوم ویرایشِ درجا دارد؛ ردیفِ حذف‌شده یعنی همان متن نشان داده نشود. تصویرِ انتخاب‌نشده روی بوم جای‌نگه‌دار است و در سایتِ نهایی نمی‌آید
(و پیش از انتشار «تصویرِ انتخاب‌نشده» پرسیده می‌شود). مجوز و مبدأ در رکورد می‌ماند و پیشِ‌نمایش آن را نشان می‌دهد.
"""
from __future__ import annotations

import re

from . import c21_convert as CV
from .clean import esc, safe_url

TYPE = "c21"
CLASS_PREFIX = CV.SCOPE_PREFIX
_RE_T = re.compile(r"\{\{T(\d+)\}\}")
_RE_NBT = re.compile(r' data-nbt="(\d+)"')
_RE_NBL = re.compile(r' data-nbl="(\d+)"')
_RE_NBI = re.compile(r'<img data-nbi="(\d+)"([^>]*)>')
_RE_CLASS = re.compile(r'class="([^"]*)"')


def attribution(rec: dict) -> str:
    """نشانِ مبدأ و مجوز به‌شکلِ یک توضیحِ HTML در خروجی (شرطِ MIT/Apache: اعلامِ حقِ نشر بماند)."""
    src = rec.get("source") or {}
    bits = [rec.get("id", ""), src.get("license") or rec.get("license", ""), src.get("repo", ""), src.get("copyright", "")]
    text = " | ".join(re.sub(r"[<>{}%]|-{2,}", " ", str(b))[:120] for b in bits if b)
    return "<!-- 21st.dev: %s -->" % text if text else ""


def default_props(rec: dict) -> dict:
    """رکورد ⇒ props ِ تازهٔ بلوک (متن‌های نمونه، پیوندهای «#»، تصویرهای خالی با توضیحِ اصلی)."""
    return {"ref": rec["key"], "texts": [{"v": t} for t in rec.get("texts", [])], "links": [{"u": u} for u in rec.get("links", [])],
            "images": [{"src": "", "alt": i.get("alt", "")} for i in rec.get("images", [])]}


def _rows(props: dict, name: str, field: str, defaults: list):
    rows = props.get(name)
    if not isinstance(rows, list) or not rows:
        return {i: v for i, v in enumerate(defaults)}
    return {i: (r.get(field) if isinstance(r, dict) else None) for i, r in enumerate(rows)}


def render(r, b) -> str:
    p = b["props"]
    key = str(p.get("ref") or "")
    rec = CV.get_record(key)
    if rec is None:
        if r.ctx.canvas:
            return '<div %s><p class="nb-blank">این قطعه دیگر در کاتالوگ نیست؛ حذفش کنید یا قطعهٔ دیگری بگذارید.</p></div>' % r.attrs(b, "nbc21-host")
        return ""
    r.use_c21(key)
    texts = _rows(p, "texts", "v", rec.get("texts", []))
    links = _rows(p, "links", "u", rec.get("links", []))
    images = p.get("images") if isinstance(p.get("images"), list) else []
    tpl = rec["template"]

    def tval(m):
        return r.line(texts.get(int(m.group(1))) or "")

    def tedit(m):
        return r.ed("texts.%s.v" % m.group(1))

    def link(m):
        i = int(m.group(1))
        u = links.get(i)
        url = r.link(u if u is not None else "#")
        ext = ' target="_blank" rel="noopener"' if url.startswith("http") else ""
        return ' href="%s"%s' % (esc(url), ext)

    def img(m):
        i = int(m.group(1))
        row = images[i] if i < len(images) and isinstance(images[i], dict) else {}
        attrs = m.group(2) or ""
        cls = (_RE_CLASS.search(attrs) or [None, ""])[1]
        alt = row.get("alt") or (rec["images"][i].get("alt", "") if i < len(rec.get("images", [])) else "")
        return r.img(row.get("src") or "", alt, cls, sizes="(max-width:800px) 100vw, 640px")

    html = _RE_NBI.sub(img, tpl)
    html = _RE_NBL.sub(link, html)
    html = _RE_NBT.sub(tedit, html)
    html = _RE_T.sub(tval, html)
    if not r.ctx.canvas and any(not (row.get("src") if isinstance(row, dict) else "") for row in images) and rec.get("images"):
        r.warn(b, "تصویرهای این قطعه را انتخاب کنید (جای خالی در سایت نمی‌آید).", kind="media")
    if rec.get("texts") and all((texts.get(i) == rec["texts"][i]) for i in range(len(rec["texts"]))) and not r.ctx.canvas:
        r.warn(b, "متن‌های این قطعه هنوز نمونه‌اند؛ با متنِ خودتان عوض کنید.", kind="sample")
    return '<div %s>%s<div class="%s" dir="auto">%s</div></div>' % (r.attrs(b, "nbc21-host"), attribution(rec), rec["scope"], html)


# ───────────────────────────── CSS و شناساییِ قطعه‌ها در HTML

HOST_CSS = ".nbc21-host{display:block;width:100%;max-width:100%;overflow-x:clip}"


def css_for(keys) -> str:
    """CSSِ قطعه‌های 21st که در سند هستند: یک بار هرکدام، ترتیبِ ثابت."""
    out = []
    for k in sorted(dict.fromkeys(keys or [])):
        rec = CV.get_record(k)
        if rec and rec.get("css"):
            out.append("/* قطعهٔ 21st: %s (%s) */\n%s" % (rec.get("title", k).replace("*/", ""), rec.get("license", ""), rec["css"]))
    return ("/* قطعه‌های 21st */\n" + HOST_CSS + "\n" + "\n".join(out)) if out else ""


def used_in_html(html: str) -> list:
    """کلیدِ قطعه‌های 21st که کلاسِ ریشه‌شان (nbc21-<کلید>) در این HTML هست."""
    found = []
    for m in re.finditer(r"\b%s(x[0-9a-f]{9})\b" % re.escape(CLASS_PREFIX), html or ""):
        if m.group(1) not in found:
            found.append(m.group(1))
    return found


def skeleton(key: str, limit: int = 1100) -> str:
    """HTMLِ نمونه برای مدلِ AI: همان قالب با متن‌های نمونه، کوتاه‌شده؛ CSS در پرامپت نمی‌آید (خودمان می‌چسبانیم)."""
    rec = CV.get_record(key)
    if not rec:
        return ""
    html = _RE_NBI.sub(lambda m: '<img src="" alt="%s">' % esc(rec["images"][int(m.group(1))].get("alt", "") if int(m.group(1)) < len(rec["images"]) else ""), rec["template"])
    html = _RE_NBL.sub(' href="#"', html)
    html = _RE_NBT.sub("", html)
    html = _RE_T.sub(lambda m: esc(rec["texts"][int(m.group(1))]) if int(m.group(1)) < len(rec["texts"]) else "", html)
    html = re.sub(r"<svg\b.*?</svg>", "<svg/>", html, flags=re.S)
    html = '<div class="%s">%s</div>' % (rec["scope"], re.sub(r"\s+", " ", html))
    if len(html) > limit:
        html = html[:limit].rsplit("<", 1)[0] + "<!-- … -->"
    return html


def preview_page(key: str, base_css: str = "", dir_: str = "rtl") -> dict:
    """پیش‌نمایشِ مستقل (برای پنل و آزمونِ مرورگر): {html, css, title, license, …} یا None."""
    rec = CV.get_record(key)
    if not rec:
        return {}
    html = _RE_NBI.sub('<img data-ph="1" alt="" width="640" height="400" style="background:#e5e7eb;min-height:120px">', rec["template"])
    html = _RE_NBL.sub(' href="#"', html)
    html = _RE_NBT.sub("", html)
    html = _RE_T.sub(lambda m: esc(rec["texts"][int(m.group(1))]) if int(m.group(1)) < len(rec["texts"]) else "", html)
    return {"key": key, "id": rec["id"], "title": rec.get("title", ""), "html": '<div class="nbc21-host"><div class="%s" dir="auto">%s</div></div>' % (rec["scope"], html),
            "css": css_for([key]), "license": rec.get("license", ""), "author": rec.get("author", ""), "library": rec.get("library", ""), "url": rec.get("url", ""),
            "source": rec.get("source", {}), "rtl": rec.get("rtl", {}), "texts": len(rec.get("texts", [])), "images": len(rec.get("images", []))}
