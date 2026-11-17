# -*- coding: utf-8 -*-
"""خوانایی قطعه‌های 21st.dev روی پوسته‌های روشن و تیره («جزیرهٔ رنگ»).

مشکل (بازبینیِ ۱۱/۱۷): قطعه‌ها را نویسنده‌های دیگر نوشته‌اند؛ بعضی رنگِ ثابتِ روشن دارند (``bg-white``) ولی متنشان از رنگِ پوستهٔ سایت می‌آید (``text-foreground``)
و روی پوستهٔ تیره متنِ سفید روی کارتِ سفید می‌شد (۲۷٪ قطعه‌ها روی سبک‌های تیره زیرِ ۳:۱ بودند، بعضی ۱٫۰:۱).

راه‌حل (سه لایه، همه با مرورگرِ واقعی سنجیده می‌شود):

1. **همان CSS، درست**: متغیرهای shadcn به متغیرهای سایت وصل‌اند؛ تغییردهنده‌های ``dark:`` وقتی پوسته تیره است روشن می‌شوند (``:where(.dark,.dark *)`` ⇒ ``:where(*)``)،
   پس قطعه‌ای که نسخهٔ تیرهٔ خودش را دارد همان را نشان می‌دهد.
2. **جزیره**: اگر قطعه با رنگ‌های سایت خوانا نیست، روی یک «جزیرهٔ» روشن یا تیرهٔ ثابت می‌نشیند (زمینه + متغیرهای ``--bg --ink …``)؛ رنگِ برند همان می‌ماند ولی
   در حدِ خوانایی روی جزیره جابه‌جا می‌شود (``ensure``).
3. **سنجش**: ``c21_rtl.check`` هر قطعه را در چهار حالت (پوستهٔ روشن، پوستهٔ تیره، جزیرهٔ روشن، جزیرهٔ تیره) باز می‌کند و برای هر متنِ دیدنی بدترین تباین را با پیکسل‌های واقعیِ پشتش
   می‌سنجد؛ «سخت» = زیرِ ۳:۱ (نامرئی)، «نرم» = زیرِ ۴٫۵:۱ (متنِ معمولی). ``plan`` می‌گوید روی پوستهٔ روشن/تیره کدام حالت (theme | light | dark) درست است؛ اگر هیچ‌کدام نیست
   قطعه «درج‌شدنی» نیست (``rtl.status = fail``).

قطعه‌ای که اندازه‌گیری نشده (رکوردِ قدیمی، مرورگر نبود) بدونِ جزیره و با رنگ‌های سایت می‌آید (رفتارِ پیشین) تا سنجش برسد.
"""
from __future__ import annotations

import re

from .styles import gen_core as G

CONTRAST_VERSION = 1
HARD = 3.0                     # زیرِ این، متن عملاً دیده نمی‌شود
SOFT = 4.5                     # حدِ WCAG AA برای متنِ معمولی
MODES = ("theme", "light", "dark")

#: جزیرهٔ ثابت: دو پالتِ خوانا (متن/زمینه ≥ ۱۵:۱، متنِ دوم و کم‌رنگ ≥ ۴٫۵:۱ روی هر دو سطح)
ISLANDS = {
    "light": {"bg": "#ffffff", "card": "#ffffff", "ink": "#111827", "ink2": "#374151", "ink3": "#5f6b7a", "line": "#e5e7eb"},
    "dark": {"bg": "#0b1020", "card": "#151b30", "ink": "#f3f4f6", "ink2": "#d1d5db", "ink3": "#a3acbb", "line": "#2d3654"},
}
#: پوسته‌های نمایندهٔ سنجش (همان «آبیِ آرام» و «تیره» ِ پوسته‌های آماده‌ی سایت‌ساز)
PAGE_COLORS = {
    "light": {"primary": "#126F85", "on_primary": "#ffffff", "text": "#111827", "text2": "#374151", "muted": "#6b7280", "line": "#e5e7eb", "bg": "#f7f8fa", "surface": "#ffffff"},
    "dark": {"primary": "#38bdf8", "on_primary": "#06202e", "text": "#f1f5f9", "text2": "#cbd5e1", "muted": "#94a3b8", "line": "#334155", "bg": "#0f172a", "surface": "#1e293b"},
}
CTX_NAMES = ("tl", "td", "il", "id")          # پوستهٔ روشن، پوستهٔ تیره، جزیرهٔ روشن (روی صفحهٔ تیره)، جزیرهٔ تیره (روی صفحهٔ روشن)
CTX_SPEC = {"tl": ("light", "theme"), "td": ("dark", "theme"), "il": ("dark", "light"), "id": ("light", "dark")}   # نام ⇒ (پالتِ صفحه، حالتِ قطعه)

_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
DARK_VARIANT = (":where(.dark,.dark *)", ":where(.dark, .dark *)")


def _hex(v, default: str) -> str:
    v = (v or "").strip() if isinstance(v, str) else ""
    if re.fullmatch(r"#[0-9a-fA-F]{3}", v):
        v = "#" + "".join(c * 2 for c in v[1:])
    return v.lower() if _HEX.match(v) else default


def page_colors(colors, polarity_hint: str = "light") -> dict:
    """رنگ‌های پوسته (کلیدهای primary/bg/text/…) ⇒ پالتِ کامل؛ کلیدِ نبود از پوستهٔ نمایندهٔ همان قطبیت پر می‌شود."""
    base = PAGE_COLORS["dark" if polarity_hint == "dark" else "light"]
    c = colors if isinstance(colors, dict) else {}
    return {k: _hex(c.get(k), v) for k, v in base.items()}


def polarity(colors) -> str:
    """'dark' اگر زمینهٔ پوسته از متنش تیره‌تر است؛ نبودنِ رنگ ⇒ 'light'."""
    c = colors if isinstance(colors, dict) else {}
    bg, ink = _hex(c.get("bg"), ""), _hex(c.get("text"), "")
    if not bg or not ink:
        return "light"
    return "dark" if G.lum(bg) < G.lum(ink) else "light"


def island_vars(mode: str, colors=None) -> dict:
    """متغیرهای CSSِ جزیره؛ رنگِ برندِ پوسته روی جزیره خوانا می‌شود (متنِ برند ≥ ۴٫۶)، و متنِ روی برند همان بهترین (سیاه/سفید) است."""
    base = ISLANDS["dark" if mode == "dark" else "light"]
    brand = _hex((colors or {}).get("primary") if isinstance(colors, dict) else None, PAGE_COLORS["light"]["primary"])
    brand_i = G.ensure(brand, [base["bg"], base["card"]], 4.6)
    brand_ink = "#ffffff" if G.contrast(brand_i, "#ffffff") >= G.contrast(brand_i, "#000000") else "#000000"
    return {"--bg": base["bg"], "--card": base["card"], "--ink": base["ink"], "--ink-2": base["ink2"], "--ink-3": base["ink3"], "--line": base["line"],
            "--brand": brand_i, "--brand-ink": brand_ink, "--brand-fg": brand_i}


def island_css(scope: str, mode: str, colors=None) -> str:
    """قاعدهٔ جزیره روی خودِ عنصرِ ریشهٔ قطعه (`.scope`)؛ دوبارِ کلاس تا بر ریستِ خودِ قطعه غلبه کند."""
    decl = ";".join("%s:%s" % kv for kv in island_vars(mode, colors).items())
    return ".%s.%s{%s;background:var(--bg);color:var(--ink)}" % (scope, scope, decl)


def dark_variants(css: str, on: bool) -> str:
    """پوستهٔ تیره یا جزیرهٔ تیره ⇒ تغییردهنده‌های ``dark:`` ِ قطعه روشن می‌شوند (ساده‌ترین راه: شرطِ «پدری با کلاسِ dark» همیشه درست)."""
    if not on or ":where(.dark" not in css:
        return css
    for s in DARK_VARIANT:
        css = css.replace(s, ":where(*)")
    return css


def plan_for(rec: dict | None, pol: str) -> str:
    """رکورد + قطبیتِ پوسته ⇒ حالتِ نمایش: 'theme' | 'light' | 'dark'. اندازه‌گیری‌نشده ⇒ 'theme'؛ هیچ حالتِ خوانایی نیست ⇒ بهترین (نزدیک‌ترین جزیره)."""
    c = (rec or {}).get("contrast") or {}
    plan = c.get("plan") or {}
    m = plan.get(pol)
    if m in MODES:
        return m
    if m == "" and plan:                       # سنجیده شد و هیچ حالتی کامل نبود: کم‌بدترین جزیره (هشدار در رندر)
        return c.get("best", {}).get(pol) if c.get("best", {}).get(pol) in MODES else "theme"
    return "theme"


def make_plan(ctx: dict) -> dict:
    """نتیجهٔ چهار سنجش ⇒ {plan: {light, dark}, best, ok}.

    ctx = {tl|td|il|id: {hard, soft, worst, n}}. برای هر قطبیتِ پوسته ترتیبِ ترجیح: همان پوسته (theme) ⇒ جزیرهٔ هم‌قطب ⇒ جزیرهٔ مخالف؛ اولین که هیچ متنِ «سخت» و «نرم» ندارد برنده است،
    وگرنه اولی که فقط «نرم» دارد؛ وگرنه '' (درج‌شدنی نیست در آن قطب)."""
    def cell(name):
        return ctx.get(name) or {"hard": 99, "soft": 99, "n": 0}

    def pick(order):
        cands = [(m, cell(n)) for m, n in order]
        for m, c in cands:
            if c["hard"] == 0 and c["soft"] == 0:
                return m, False
        for m, c in cands:
            if c["hard"] == 0:
                return m, False
        best = min(cands, key=lambda mc: (mc[1]["hard"], mc[1]["soft"]))[0]
        return "", best

    plan, best = {}, {}
    plan["light"], b1 = pick((("theme", "tl"), ("light", "il"), ("dark", "id")))
    plan["dark"], b2 = pick((("theme", "td"), ("dark", "id"), ("light", "il")))
    best["light"], best["dark"] = (b1 or plan["light"]), (b2 or plan["dark"])
    return {"plan": plan, "best": best, "ok": bool(plan["light"] and plan["dark"])}


# ───────────────────────────── اندازه‌گیری (Pillow + متن‌های گرفته‌شده در مرورگر)

def _lum(c) -> float:
    def f(v):
        v /= 255.0
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    return 0.2126 * f(c[0]) + 0.7152 * f(c[1]) + 0.0722 * f(c[2])


def _ratio(a, b) -> float:
    la, lb = _lum(a), _lum(b)
    if la < lb:
        la, lb = lb, la
    return (la + 0.05) / (lb + 0.05)


def measure(items: list, png_path) -> dict | None:
    """items (متن‌های دیدنیِ صفحه با رنگ و مستطیل) + اسکرین‌شاتِ همان صفحه با متنِ شفاف ⇒ {n, hard, soft, worst, samples[]}؛ Pillow/فایل نبود ⇒ None.

    هر متن روی شبکهٔ ۴×۳ از پیکسل‌های واقعیِ پشتش سنجیده می‌شود (گرادیان، شیشه، تصویر)؛ بدترین نسبت ملاک است."""
    try:
        from PIL import Image
        im = Image.open(png_path).convert("RGB")
    except Exception:                          # noqa: BLE001
        return None
    W, H = im.size
    px = im.load()
    n = hard = soft = 0
    worst_all = 99.0
    samples = []
    for it in items or []:
        if float(it.get("alpha", 1)) < 0.05:
            continue
        worst, wfg, wbg = 99.0, None, None
        a = min(1.0, max(0.0, float(it.get("alpha", 1))))
        col = it.get("color") or [0, 0, 0]
        for x, y, w, h in it.get("rects") or []:
            for gx in (0.1, 0.35, 0.65, 0.9):
                for gy in (0.2, 0.5, 0.8):
                    X, Y = int(x + w * gx), int(y + h * gy)
                    if 0 <= X < W and 0 <= Y < H:
                        bg = px[X, Y]
                        eff = tuple(bg[i] * (1 - a) + col[i] * a for i in range(3))
                        r = _ratio(eff, bg)
                        if r < worst:
                            worst, wfg, wbg = r, eff, bg
        if worst == 99.0:
            continue
        n += 1
        worst_all = min(worst_all, worst)
        if worst < HARD:
            hard += 1
            if len(samples) < 3:
                samples.append({"text": str(it.get("text", ""))[:30], "ratio": round(worst, 2), "fg": "#%02x%02x%02x" % tuple(int(v) for v in wfg), "bg": "#%02x%02x%02x" % tuple(wbg)})
        elif worst < SOFT and not it.get("large"):
            soft += 1
    return {"n": n, "hard": hard, "soft": soft, "worst": round(worst_all, 2) if n else None, "samples": samples}
