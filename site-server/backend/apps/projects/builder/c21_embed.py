# -*- coding: utf-8 -*-
"""بلوکِ «قطعهٔ 21st» (نوعِ ``c21``): یک قطعهٔ تبدیل‌شده (c21_convert) در صفحه؛ رندر، CSS، پیش‌نمایش، پیشنهاد برای AI.

سندِ صفحه فقط ``{ref, texts:[{v}], links:[{u}], images:[{src, alt}]}`` را نگه می‌دارد؛ HTML و CSS از رکوردِ تبدیل‌شده می‌آیند و همیشه از فهرستِ سفیدِ پاک‌سازی گذشته‌اند.
متنِ هر شکاف روی بوم ویرایشِ درجا دارد؛ ردیفِ حذف‌شده یعنی همان متن نشان داده نشود. تصویرِ انتخاب‌نشده روی بوم جای‌نگه‌دار است و در سایتِ نهایی نمی‌آید
(و پیش از انتشار «تصویرِ انتخاب‌نشده» پرسیده می‌شود). مجوز و مبدأ در رکورد می‌ماند و پیشِ‌نمایش آن را نشان می‌دهد.
"""
from __future__ import annotations

import hashlib
import re

from . import c21_contrast as CC, c21_convert as CV
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
    from . import c21_source
    bits = [rec.get("id", ""), src.get("license") or rec.get("license", ""), src.get("repo", ""), c21_source.clean_copyright(src.get("copyright", ""), src.get("repo", ""))]
    text = " | ".join(re.sub(r"[<>{}%]|-{2,}", " ", str(b))[:120] for b in bits if b)
    return "<!-- 21st.dev: %s -->" % text if text else ""


def text_hash(text) -> str:
    """اثرِ انگشتِ کوتاهِ یک متن (فاصله‌ها یکی)؛ برای تشخیصِ «این متن از وقتِ درج دست نخورده»."""
    return hashlib.sha1(re.sub(r"\s+", " ", str(text or "")).strip().encode("utf-8")).hexdigest()[:8]


def seed_of(texts) -> str:
    """متن‌هایی که همراهِ قطعه درج شدند ⇒ رشتهٔ اثرِ انگشت‌ها (جدا با «,»؛ سقفِ فیلد ۱۰۰۰ نویسه)."""
    out, size = [], 0
    for t in texts or []:
        h = text_hash(t)
        if size + len(h) + 1 > 950:
            break
        out.append(h)
        size += len(h) + 1
    return ",".join(out)


def default_props(rec: dict, texts=None) -> dict:
    """رکورد ⇒ props ِ تازهٔ بلوک (متن‌های نمونه، پیوندهای «#»، تصویرهای خالی با توضیحِ اصلی).

    ``texts``: متن‌هایی که واقعاً درج می‌شوند (مثلاً بعد از فارسی‌سازی)؛ ``seed`` اثرِ انگشتِ همین‌هاست: تا وقتی متنِ یک شکاف همان باشد، «هنوز نمونه است» و پیش از انتشار
    پرسیده می‌شود (دورِ ۴: متنِ فارسی‌شده با فرهنگ‌لغت یا AI دیگر شبیهِ متنِ کاربر دیده نمی‌شد و قیمت‌های ساختگیِ ۲۱st بی‌هشدار منتشر می‌شد)."""
    texts = list(rec.get("texts", [])) if texts is None else [str(t) for t in texts]
    return {"ref": rec["key"], "seed": seed_of(texts), "texts": [{"v": t} for t in texts], "links": [{"u": u} for u in rec.get("links", [])],
            "images": [{"src": "", "alt": i.get("alt", "")} for i in rec.get("images", [])]}


# ───────────────────────────── «هنوز نمونه است» (پیش از انتشار)

_PRICE = re.compile(r"[$€£¥₹]\s?\d|\d\s?[$€£¥₹]|\d[\d,.٫٬]*\s?(?:[%٪])|\d\s?(?:/|per|در)\s?(?:mo|yr|month|year|ماه|سال)|\b(?:USD|EUR)\b|دلار|یورو|\d\s*(?:K|M)\+?\b|[۰-۹]+\s?(?:میلیون|هزار)", re.I)


def meaningful(text) -> bool:
    """متنی که «محتوا» است (دست‌کم دو واژه، یا عدد): برچسب‌های تک‌واژه‌ای رابط («ماه»، «ورود»، «Pricing») نمونهٔ ساختگی حساب نمی‌شوند."""
    n = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(re.findall(r"[^\W\d_]", n)) < 3 and not re.search(r"\d", n):
        return False
    return n.count(" ") >= 1 or bool(re.search(r"\d", n))


def untouched_samples(rec: dict, props: dict) -> list[str]:
    """متن‌های «معنادار»ی که از نمونهٔ ۲۱st دست نخورده‌اند.

    بلوکی که ``seed`` دارد: متنِ شکاف با اثرِ انگشتِ هنگامِ درج یکی است. بلوکِ قدیمی (بی‌seed): با متنِ انگلیسیِ اصلی یا ترجمهٔ فرهنگ‌لغتش یکی است.
    فقط ردیف‌های موجود در سند شمرده می‌شوند (ردیفِ حذف‌شده نشان داده نمی‌شود)."""
    from . import c21_translate as TR

    originals = list(rec.get("texts") or [])
    rows = props.get("texts")
    if not isinstance(rows, list) or not rows:
        rows = [{"v": t} for t in originals]
    seed = [x for x in str(props.get("seed") or "").split(",")]
    out = []
    for i, row in enumerate(rows):
        v = row.get("v") if isinstance(row, dict) else ""
        if not isinstance(v, str) or not meaningful(v):
            continue
        if i < len(seed) and seed[i]:
            same = text_hash(v) == seed[i]
        else:
            orig = originals[i] if i < len(originals) else None
            same = orig is not None and (v == orig or v == TR.fa_text(orig))
        if same:
            out.append(v)
    return out


def sample_warnings(rec: dict, props: dict) -> list[str]:
    """⇒ جمله‌های هشدارِ فارسی (۰ تا ۲): قیمت/عددِ ساختگی، و متنِ نمونهٔ انگلیسی/ترجمه‌شده. چیزی از «دیگران» نباید به‌جای حرفِ مالک منتشر شود."""
    from .placeholders import _fa, _snip

    left = untouched_samples(rec, props)
    if not left:
        return []
    out = []
    priced = [t for t in left if _PRICE.search(t)]
    if priced:
        more = "" if len(priced) == 1 else " (و %s مورد دیگر)" % _fa(len(priced) - 1)
        out.append("قیمت یا عددِ نمونه از قطعهٔ 21st مانده («%s»)%s؛ فقط عددهای واقعیِ خودتان بماند." % (_snip(priced[0], 30), more))
    rest = [t for t in left if t not in priced]
    if rest:
        out.append("%s متنِ این قطعه هنوز نمونهٔ 21st است (مثلاً «%s»)؛ با متنِ خودتان عوض کنید." % (_fa(len(rest)), _snip(rest[0], 36)))
    return out


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
    for sentence in sample_warnings(rec, p):                 # بوم هم (فهرستِ «هنوز نمونه یا ناتمام است» ِ کنارِ ویرایشگر) مثلِ بلوک‌های خودمان
        r.warn(b, sentence, kind="sample")
    return '<div %s>%s<div class="%s" dir="auto">%s</div></div>' % (r.attrs(b, "nbc21-host"), attribution(rec), rec["scope"], html)


# ───────────────────────────── CSS و شناساییِ قطعه‌ها در HTML

HOST_CSS = ".nbc21-host{display:block;width:100%;max-width:100%;overflow-x:clip}"


#: کلاس‌های عمومیِ CSSِ پایهٔ سایت که با نامِ ابزارهای Tailwind یکی‌اند و درون قطعه نشت می‌کردند: ``.grid`` (gap + ستون‌های خودکار) ستون‌بندیِ ۷۹ قطعه را به‌هم می‌ریخت
#: (مثلاً دایرهٔ تیکِ ۲۲ پیکسلی ۲۲۰ پیکسل ستون می‌گرفت و تیک کنارِ متن می‌افتاد)؛ th/td/h1..h6 هم ترازِ راست و ارتفاعِ سطرِ سایت را می‌بردند.
#: بالاتر از CSSِ سایت و پایین‌تر از ابزارهای خودِ قطعه (هم‌وزن و دیرتر ⇒ قطعه برنده).
LEAK_CSS = ('[class*="nbc21-x"] .grid{grid-template-columns:none;gap:normal}'
            '[class*="nbc21-x"] th,[class*="nbc21-x"] td{text-align:inherit}'
            '[class*="nbc21-x"] th{background:transparent;color:inherit;font-size:inherit}'          # `th{background:#f9fafb;color:var(--ink-3)}` ِ پایهٔ سایت: سرستونِ روشن با متنِ روشن روی پوستهٔ تیره (۲٫۷:۱)
            '[class*="nbc21-x"] h1,[class*="nbc21-x"] h2,[class*="nbc21-x"] h3,[class*="nbc21-x"] h4,[class*="nbc21-x"] h5,[class*="nbc21-x"] h6{line-height:inherit}')


def css_one(rec: dict, colors=None, mode: str = "") -> str:
    """CSSِ یک قطعه برای پوستهٔ داده‌شده: حالتِ نمایش (theme | light | dark) از سنجشِ مرورگر می‌آید (c21_contrast.plan_for) مگر این‌که ``mode`` بدهند؛
    پوستهٔ تیره و جزیرهٔ تیره ⇒ ``dark:`` ِ خودِ قطعه روشن؛ جزیره ⇒ زمینه و رنگ‌های ثابتِ خوانا."""
    pol = CC.polarity(colors)
    mode = mode if mode in CC.MODES else CC.plan_for(rec, pol)
    css = CC.dark_variants(rec.get("css", ""), mode == "dark" or (mode == "theme" and pol == "dark"))
    if mode in ("light", "dark"):
        css += "\n" + CC.island_css(rec["scope"], mode, CC.page_colors(colors, pol))
    return css


def css_for(keys, colors=None, modes=None) -> str:
    """CSSِ قطعه‌های 21st که در سند هستند: یک بار هرکدام، ترتیبِ ثابت. ``colors`` = رنگ‌های پوستهٔ همین سند (برای انتخابِ روشن/تیره)؛ ``modes`` = {کلید: حالت} (سنجش)."""
    out = []
    for k in sorted(dict.fromkeys(keys or [])):
        rec = CV.get_record(k)
        if rec and rec.get("css"):
            out.append("/* قطعهٔ 21st: %s (%s) */\n%s" % (rec.get("title", k).replace("*/", ""), rec.get("license", ""), css_one(rec, colors, (modes or {}).get(k, ""))))
    return ("/* قطعه‌های 21st */\n" + HOST_CSS + "\n" + LEAK_CSS + "\n" + "\n".join(out)) if out else ""


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


def preview_page(key: str, base_css: str = "", dir_: str = "rtl", colors=None, mode: str = "") -> dict:
    """پیش‌نمایشِ مستقل (برای پنل و آزمونِ مرورگر): {html, css, title, license, …} یا None."""
    rec = CV.get_record(key)
    if not rec:
        return {}
    html = _RE_NBI.sub('<img data-ph="1" alt="" width="640" height="400" style="background:#e5e7eb;min-height:120px">', rec["template"])
    html = _RE_NBL.sub(' href="#"', html)
    html = _RE_NBT.sub("", html)
    html = _RE_T.sub(lambda m: esc(rec["texts"][int(m.group(1))]) if int(m.group(1)) < len(rec["texts"]) else "", html)
    return {"key": key, "id": rec["id"], "title": rec.get("title", ""), "html": '<div class="nbc21-host"><div class="%s" dir="auto">%s</div></div>' % (rec["scope"], html),
            "css": css_for([key], colors, {key: mode} if mode else None), "license": rec.get("license", ""), "author": rec.get("author", ""), "library": rec.get("library", ""), "url": rec.get("url", ""),
            "source": rec.get("source", {}), "rtl": rec.get("rtl", {}), "texts": len(rec.get("texts", [])), "images": len(rec.get("images", []))}
