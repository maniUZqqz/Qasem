# -*- coding: utf-8 -*-
"""سنجشِ راست‌به‌چپ و موبایلِ قطعه‌های تبدیل‌شده در مرورگرِ واقعی (Chromium بی‌سر) — ``deploy/c21/rtl_check.py``.

هر قطعه با ``dir="rtl"`` در عرضِ ۳۹۰ و ۱۲۸۰ باز می‌شود: سرریزِ افقیِ صفحه و عنصرهای بیرون‌زده شمرده می‌شود. نتیجه در رکوردِ قطعه (``rtl``) می‌ماند؛
«fail» (گوشی از کنار سرریز می‌کند، یا قطعه به‌صورتِ ایستا هیچ‌چیزِ دیدنی ندارد: «blank») قطعه را از فهرستِ «قابلِ درج» برمی‌دارد، «warn» فقط هشدار است.
«blank»: انیمیشنِ تایپ، canvas، لغزنده روی صفر و مانندش به‌صورتِ HTMLِ ایستا خالی دیده می‌شوند؛ از اسکرین‌شاتِ هر دو عرض شمرده می‌شود چند پیکسل با زمینه فرق دارد (``ink_of``).
مرورگر: ``NM_C21_PLAYWRIGHT_PY`` (پایتونی که Playwright دارد؛ پیش‌فرض /opt/up3d-uitest/venv) و ``PLAYWRIGHT_BROWSERS_PATH``؛ نبودنشان ⇒ «سنجیده نشد» (کارِ دیگر نمی‌ایستد).
"""
from __future__ import annotations

import json
import re
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from . import c21_contrast as CC, c21_convert as CV, c21_embed as EM, c21st

DEFAULT_PY = "/opt/up3d-uitest/venv/bin/python"
DEFAULT_BROWSERS = "/opt/up3d-uitest/browsers"
_REPO_SCRIPT = Path(__file__).resolve().parents[4] / "deploy" / "c21" / "rtl_check.py"        # همیشه هم‌نسخهٔ کد (بی‌نصبِ دستی)
SCRIPT = _REPO_SCRIPT if _REPO_SCRIPT.exists() else Path(CV.TOOLCHAIN) / "rtl_check.py"
CHECK_VERSION = 4                    # ۲ = اسکرین‌شاتِ «blank» + سرریزِ گوشی ⇒ fail؛ ۳ = «فقط یک قابِ خالی» (بی‌متن و بی‌تصویر) هم blank است؛ ۴ = سنجشِ خوانایی روی پوستهٔ روشن/تیره/جزیره + «بسیار کوچک» + CSSِ ترمیم‌شده؛ رکوردهای با نسخهٔ کمتر خودکار دوباره سنجیده می‌شوند (recheck_outdated)
INK_MIN = 150                        # کمتر از این تعداد پیکسلِ «پررنگ» (اختلافِ هر کانال با زمینه > ۴۰ از ۲۵۵؛ نقطه‌های محوِ شبکهٔ سوسوزن حساب نمی‌شوند) در هر دو عرض ⇒ قطعه خالی است
PAGE_BG = (0xf7, 0xf8, 0xfa)
TINY_CHARS = 5                       # کمتر از این تعداد نویسهٔ دیدنی (و بی‌تصویر، کوتاه) ⇒ «بسیار کوچک»: یک نشان/دکمهٔ بی‌متن به کارِ سایت‌ساز نمی‌آید
SECTION_MIN_H, SECTION_MIN_CHARS = 180, 24      # بخشِ صفحه (بقیه «ابزارک»)
WIDGET_WORDS = re.compile(r"\b(badge|kbd|button|btn|spinner|loader|switch|toggle|tooltip|avatar|chip|tag|counter|wheel|cursor|checkbox|radio|slider|knob|icon)s?\b", re.I)
SECTION_CATS = {"hero", "features", "cta", "pricing-section", "testimonials", "navigation", "footer", "accordion", "landing-page", "carousel", "marquee", "dashboard", "table", "chart", "form", "ai-chat"}
OVERLAP_MAX = 1                      # این تعداد متنِ رویِ‌هم‌افتاده (یا بیشتر) ⇒ درج‌شدنی نیست

_PAGE_HEAD = ('<!doctype html><html lang="fa" dir="rtl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
              '<style>:root{%s--r:16px}'
              'body{margin:0;background:var(--bg);color:var(--ink);font-family:Tahoma,sans-serif}.nb-wrap{max-width:1140px;margin:0 auto;padding:24px 16px}</style>')
_LIGHT_VARS = '--brand:#126f85;--brand-ink:#fff;--ink:#111827;--ink-2:#374151;--ink-3:#6b7280;--line:#e5e7eb;--bg:#f7f8fa;--card:#fff;'
PAGE = _PAGE_HEAD % _LIGHT_VARS + '<style>%s</style></head><body>%s</body></html>'


def page_for(css: str, html: str, colors=None) -> str:
    """صفحهٔ مستقل با متغیرهای رنگیِ پوسته (همان نام‌هایی که سایت‌ساز می‌نویسد)؛ colors نبود ⇒ همان PAGE ِ روشن."""
    if not colors:
        return PAGE % (css, html)
    pc = CC.page_colors(colors, CC.polarity(colors))
    brand_fg = CC.G.ensure(pc["primary"], [pc["bg"], pc["surface"]], 6.2)
    vars_ = ("--brand:%s;--brand-ink:%s;--brand-fg:%s;--ink:%s;--ink-2:%s;--ink-3:%s;--line:%s;--bg:%s;--card:%s;"
             % (pc["primary"], pc["on_primary"], brand_fg, pc["text"], pc["text2"], pc["muted"], pc["line"], pc["bg"], pc["surface"]))
    return _PAGE_HEAD % vars_ + '<style>%s</style></head><body>%s</body></html>' % (css, html)


def available() -> tuple[bool, str]:
    py = os.environ.get("NM_C21_PLAYWRIGHT_PY") or DEFAULT_PY
    if not os.path.exists(py):
        return False, "پایتونِ Playwright نیست (%s)" % py
    if not SCRIPT.exists():
        return False, "rtl_check.py در جعبه‌ابزار نیست"
    return True, ""


def ink_of(png_path, bg=PAGE_BG, step: int = 2, delta: int = 40):
    """اسکرین‌شات ⇒ تعدادِ (تقریبیِ) پیکسل‌هایی که با زمینهٔ صفحه فرق دارند؛ فایل/Pillow نبود ⇒ None."""
    try:
        from PIL import Image
        im = Image.open(png_path).convert("RGB")
    except Exception:                      # noqa: BLE001
        return None
    px, (w, h), n = im.load(), im.size, 0
    for y in range(0, h, step):
        for x in range(0, w, step):
            c = px[x, y]
            if abs(c[0] - bg[0]) > delta or abs(c[1] - bg[1]) > delta or abs(c[2] - bg[2]) > delta:
                n += 1
    return n * step * step


def _ctx_file(k: str, name: str) -> str:
    return "%s~%s" % (k, name)


def _read_ctx(tmp: Path, k: str, name: str) -> dict | None:
    try:
        data = json.loads((tmp / (_ctx_file(k, name) + ".json")).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return None if "error" in data else data


def check(keys: list[str], *, runner=subprocess.run, timeout: int = 900, contrast: bool = True) -> dict:
    """⇒ {key: {status, overflow_390, overflow_1280, contrast?, chars, height, …}}؛ مرورگر نبود ⇒ {key: {status: 'skipped', why}}.

    هر قطعه یک بار با پوستهٔ روشن (سرریز/خالی) و، اگر contrast، چهار بار برای خوانایی باز می‌شود: پوستهٔ روشن (tl)، پوستهٔ تیره (td)، جزیرهٔ روشن (il)، جزیرهٔ تیره (id)؛
    همان ``EM.css_for`` ِ سایت‌ساز با ``modes`` ِ مشخص ⇒ آنچه سنجیده می‌شود همان است که در سایت می‌آید."""
    ok, why = available()
    if not ok:
        return {k: {"status": "skipped", "why": why} for k in keys}
    tmp = Path(tempfile.mkdtemp(prefix="nm-c21-rtl-"))
    try:
        for k in keys:
            pv = EM.preview_page(k, mode="theme")
            if pv:
                (tmp / (k + ".html")).write_text(PAGE % (pv["css"], pv["html"]), encoding="utf-8")
                if contrast:
                    for name in CC.CTX_NAMES:
                        pol, mode = CC.CTX_SPEC[name]
                        colors = CC.PAGE_COLORS[pol]
                        pc = EM.preview_page(k, colors=colors, mode=mode)
                        (tmp / (_ctx_file(k, name) + ".html")).write_text(page_for(pc["css"], pc["html"], colors), encoding="utf-8")
        env = dict(os.environ, PLAYWRIGHT_BROWSERS_PATH=os.environ.get("PLAYWRIGHT_BROWSERS_PATH") or DEFAULT_BROWSERS)
        py = os.environ.get("NM_C21_PLAYWRIGHT_PY") or DEFAULT_PY
        r = runner([py, str(SCRIPT), str(tmp), str(tmp / "rtl.json")], capture_output=True, text=True, timeout=timeout, env=env)
        try:
            res = json.loads((tmp / "rtl.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {k: {"status": "skipped", "why": "مرورگر نتیجه نداد: " + (r.stderr or "")[-120:]} for k in keys}
        dark_bg = tuple(int(CC.PAGE_COLORS["dark"]["bg"][i:i + 2], 16) for i in (1, 3, 5))
        for k, row in res.items():                                        # «خالیِ ایستا»: در هیچ‌کدام از دو عرض چیزِ دیدنی نیست (روی پوستهٔ روشن و تیره)
            inks = [ink_of(tmp / ("%s-%d.png" % (k, w))) for w in (390, 1280)]
            inks = [i for i in inks if i is not None]
            if inks and contrast and max(inks) < INK_MIN and (tmp / (_ctx_file(k, "td") + ".png")).exists():
                dark_ink = ink_of(tmp / (_ctx_file(k, "td") + ".png"), bg=dark_bg)       # متنِ سفیدِ بی‌زمینه روی پوستهٔ روشن دیده نمی‌شود ولی روی تیره می‌شود
                if dark_ink is not None:
                    inks.append(dark_ink)
            if inks:
                row["ink"] = max(inks)
                if row.get("status") in ("ok", "warn") and max(inks) < INK_MIN:
                    row["status"], row["blank"] = "fail", True
                    row["why"] = "به‌صورتِ ایستا چیزِ دیدنی ندارد (انیمیشن/canvas/مقدارِ صفر)"
            # فقط یک قابِ خالی (حاشیه یا پس‌زمینه «جوهر» می‌دهد ولی نه متنی هست نه تصویر/فیلد/دکمه): کارِ canvas یا انیمیشنِ جاوااسکریپتی است
            if row.get("status") in ("ok", "warn") and all(int(row.get("text_%d" % w, 1)) == 0 and int(row.get("visual_%d" % w, 1)) == 0 for w in (390, 1280)):
                row["status"], row["blank"] = "fail", True
                row["why"] = "به‌صورتِ ایستا فقط یک قابِ خالی است (بی‌متن و بی‌تصویر؛ canvas/انیمیشن)"
            if contrast:
                ctx, first = {}, None
                for name in CC.CTX_NAMES:
                    data = _read_ctx(tmp, k, name)
                    if not data:
                        continue
                    first = first or data
                    m = CC.measure(data.get("items") or [], tmp / (_ctx_file(k, name) + ".png"))
                    if m is not None:
                        ctx[name] = m
                if len(ctx) == len(CC.CTX_NAMES):
                    row["contrast"] = {"v": CC.CONTRAST_VERSION, "ctx": {n: {x: c[x] for x in ("n", "hard", "soft", "worst")} for n, c in ctx.items()}, **CC.make_plan(ctx)}
                    row["contrast"]["samples"] = {n: c["samples"] for n, c in ctx.items() if c.get("samples")}
                tl = _read_ctx(tmp, k, "tl")
                if tl:
                    row["chars"], row["height"] = int(tl.get("chars") or 0), int(tl.get("height") or 0)
                    td = _read_ctx(tmp, k, "td") or {}
                    row["overlap"] = max(sum(1 for it in (d_.get("items") or []) if it.get("occ")) for d_ in (tl, td))     # متنی که چیزِ دیگری رویش افتاده (نشان روی برچسب، دو متنِ روی‌هم، آیکون روی متن)
        return res
    except subprocess.TimeoutExpired:
        return {k: {"status": "skipped", "why": "مهلتِ سنجش تمام شد"} for k in keys}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def classify(row: dict, rec: dict) -> tuple[str, str]:
    """نتیجهٔ مرورگر + رکورد ⇒ (نوع: section | widget | tiny، علتِ بسته‌شدن یا ''). «tiny»: کمتر از ۵ نویسه، بی‌تصویر، کوتاه (یک نشان/دکمهٔ بی‌متن)."""
    chars, height = row.get("chars"), row.get("height")
    if chars is None:
        return "", ""
    if chars < TINY_CHARS and not rec.get("images"):
        return "tiny", "بی‌متن است (کمتر از %d نویسهٔ دیدنی و بی‌تصویر: یک نشان، دکمهٔ تک‌آیکون یا قابِ تزئینی)؛ به کارِ ساختِ صفحه نمی‌آید." % TINY_CHARS
    big = (height or 0) >= SECTION_MIN_H and chars >= SECTION_MIN_CHARS
    if big and WIDGET_WORDS.search(rec.get("title", "")) and not (set(rec.get("cats") or []) & SECTION_CATS):         # «Badge»، «Kbd»، «Number wheel»: ویترینِ یک ابزارک، نه بخشِ صفحه
        big = False
    return ("section" if big else "widget"), ""


def apply(keys: list[str], **kw) -> dict:
    res = check(keys, **kw)
    status, kinds = {}, {}
    for k, row in res.items():
        rec = CV.load_record(k)
        if rec:
            kind, tiny_why = classify(row, rec)
            con = row.get("contrast")
            if row.get("status") in ("ok", "warn"):
                if tiny_why:
                    row["status"], row["why"] = "fail", tiny_why
                elif int(row.get("overlap") or 0) >= OVERLAP_MAX:
                    row["status"], row["overlap_fail"] = "fail", True
                    row["why"] = "متن‌ها یا نشانه‌ها روی هم می‌افتند (%d مورد: برچسب زیرِ نشان/آیکون)؛ در صفحهٔ ایستا خوانده نمی‌شود." % int(row["overlap"])
                elif con and not con.get("ok"):
                    row["status"], row["contrast_fail"] = "fail", True
                    row["why"] = "متنِ قطعه روی پوستهٔ %s هیچ‌گاه خوانا نمی‌شود (تباین زیرِ ۳:۱ حتی روی جزیرهٔ ثابت)." % ("روشن" if not (con.get("plan") or {}).get("light") else "تیره")
            rec["rtl"] = {"status": row.get("status", "skipped"), "overflow_390": bool(row.get("overflow_390")), "overflow_1280": bool(row.get("overflow_1280")),
                          "rtl": bool(row.get("rtl", True)), "why": row.get("why", ""), "checked_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                          "blank": bool(row.get("blank")), "ink": row.get("ink"), "kind": kind, "chars": row.get("chars"), "height": row.get("height"), "contrast_fail": bool(row.get("contrast_fail")), "overlap": int(row.get("overlap") or 0),
                          "v": CHECK_VERSION if row.get("status") not in ("skipped", "error") else 0}
            if con:
                rec["contrast"] = con
            CV.save_record(rec)
            status[k] = rec["rtl"]["status"]
            kinds[k] = kind
    rows = c21st.load()
    for r in rows:
        conv = r.get("conv") or {}
        if conv.get("key") in status:
            conv["rtl"] = status[conv["key"]]
            if kinds.get(conv["key"]):
                conv["kind"] = kinds[conv["key"]]
    c21st.save(rows)
    return res


def outdated_keys(limit: int = 60) -> list[str]:
    """رکوردهای تبدیل‌شده‌ای که با نسخهٔ فعلیِ سنجش نسنجیده‌اند (یا هرگز سنجیده نشدند)."""
    out = []
    for e in CV.load_index().values():
        rec = CV.load_record(e["key"])
        if rec and int((rec.get("rtl") or {}).get("v") or 0) < CHECK_VERSION:
            out.append(e["key"])
            if len(out) >= limit:
                break
    return out


def recheck_outdated(limit: int = 60, **kw) -> dict:
    """دسته‌ای از قطعه‌های قدیمی را دوباره می‌سنجد (خودکار از تسکِ تبدیل؛ مرورگر نبود ⇒ هیچ‌چیز عوض نمی‌شود). ⇒ {checked, statuses}."""
    ok, why = available()
    if not ok:
        return {"checked": 0, "left": -1, "why": why}
    keys = outdated_keys(limit)
    if not keys:
        return {"checked": 0, "left": 0}
    res = apply(keys, **kw)
    done = {k: (v or {}).get("status", "skipped") for k, v in res.items()}
    return {"checked": sum(1 for v in done.values() if v not in ("skipped", "error")), "statuses": done, "left": len(outdated_keys(1000))}
