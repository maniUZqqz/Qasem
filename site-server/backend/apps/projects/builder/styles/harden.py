# -*- coding: utf-8 -*-
"""سخت‌کردنِ خوانایی (بازبینیِ ۱۱/۱۶): «هر سبک تباین‌سنجی شده» فقط جفت‌رنگ‌های پالت را می‌سنجید؛ در مرورگر ۴۱ از ۸۹ سبک متنِ زیر ۴٫۵:۱ داشت
(نشانِ بالای هیرو، لینک‌های پابرگ، توضیحِ زیرِ دکمه، متنِ روی گرادیانِ دعوت).

دو لایه (هر دو خالص و آزمون‌پذیر؛ اندازه‌گیریِ واقعی در مرورگر: ``browser_checks/check_text_contrast.py``):

1. ``harden_palette``: متنِ دوم و کم‌رنگ با «حاشیهٔ ایمنی» می‌آیند (۶٫۳ و ۵٫۶ نسبت به زمینه و سطح، نه ۵٫۰ و ۴٫۷). چرا: کلاس‌هایی مثل لینکِ پابرگ ``opacity:.9`` دارند و
   روی کارت‌های شیشه‌ای / سطحِ کمی متفاوت، تباین از مرزِ ۴٫۵ پایین می‌افتاد.
2. ``guard_surface_fg``: متنِ روی هیرو/دعوتِ گرادیانی را روی «همهٔ ایستگاه‌های گرادیان با رنگِ اصلیِ واقعی» (برندِ نگه‌داشته‌شده هم) می‌سنجد؛ سفید یا تقریباً مشکی را برمی‌دارد
   که با بدترین ایستگاه ≥ ۴٫۵ بدهد.
"""
from __future__ import annotations

import re

from .gen_core import contrast, ensure, h2r, mix, on_color

TEXT_MIN, TEXT2_MIN, MUTED_MIN = 7.0, 6.3, 5.6
SURFACE_MIN = 5.6                      # حاشیه برای کلاس‌هایی با opacity .9/.92 (توضیحِ زیرِ دکمه، لینک‌ها)
DARK_INK = '#111827'

_HEX = re.compile(r'#([0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b')
_RGBA = re.compile(r'rgba?\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})\s*(?:,\s*([\d.]+)\s*)?\)')
_SCRIM = re.compile(r'^linear-gradient\(rgba\((\d+),(\d+),(\d+),([\d.]+)\),rgba\(\d+,\d+,\d+,[\d.]+\)\),(.*)$', re.S)
_MIX = re.compile(r'color-mix\(\s*in\s+srgb\s*,\s*(#[0-9a-fA-F]{6})\s+(\d+(?:\.\d+)?)%\s*,\s*(#[0-9a-fA-F]{6}|transparent)\s*\)')


def _full(h: str) -> str:
    h = h.lower()
    return '#' + ''.join(c * 2 for c in h[1:]) if len(h) == 4 else h


def harden_palette(colors: dict, extra_bgs=()) -> dict:
    """⇒ رنگ‌های پالت با متنِ دوم/کم‌رنگِ بااحتیاط (فقط تیره/روشن‌تر شدن؛ رنگِ اصلی و زمینه دست نمی‌خورد). extra_bgs: ایستگاه‌های زمینهٔ صفحه/کارتِ سبک
    (گرادیانِ مش، شیشهٔ نیمه‌شفاف) که رنگِ واقعیِ پشتِ متن‌اند و با ``bg`` یکی نیستند."""
    c = dict(colors)
    try:
        bgs = [c['bg'], c['surface']] + [x for x in extra_bgs if x]
        c['text'] = ensure(c['text'], bgs, TEXT_MIN)
        c['text2'] = ensure(c['text2'], bgs, TEXT2_MIN)
        c['muted'] = ensure(c['muted'], bgs, MUTED_MIN)
    except (KeyError, ValueError, IndexError):
        pass
    return c


def stops_of(css_value: str, brand: str, backdrop: str = '#ffffff', boost: float = 1.0) -> list[str]:
    """مقدارِ CSSِ یک زمینه (رنگِ ساده، گرادیان، color-mix، var(--brand)) ⇒ فهرستِ رنگ‌های hexِ آن. rgba با آلفا روی ``backdrop`` (زمینهٔ صفحهٔ سبک) ترکیب می‌شود،
    پس گرادیانِ نیمه‌شفاف روی صفحهٔ تیره تیره حساب می‌شود، نه روشن."""
    v = str(css_value or '')
    brand = _full(brand) if brand and _HEX.fullmatch(brand) else '#126f85'
    backdrop = _full(backdrop) if backdrop and _HEX.fullmatch(backdrop) else '#ffffff'
    sm = _SCRIM.match(v.strip())
    if sm:                                                     # «پرده»ی خودِ نگهبان (لایهٔ یکدستِ نیمه‌شفاف روی گرادیان): ایستگاه‌های لایهٔ زیر را تیره/روشن می‌کند، ایستگاهِ تازه‌ای نیست
        scr = '#%02x%02x%02x' % tuple(min(255, int(x)) for x in sm.group(1, 2, 3))
        return [mix(c, scr, min(1.0, float(sm.group(4)))) for c in stops_of(sm.group(5), brand, backdrop, boost)]
    v = v.replace('var(--brand)', brand)
    v = re.sub(r'var\(--brand-ink\s*,\s*(#[0-9a-fA-F]{3,6})\)', r'\1', v)
    v = _HEX.sub(lambda m: _full(m.group(0)), v)

    def _mix_sub(m):
        a, pct, b = m.group(1), float(m.group(2)) / 100.0, m.group(3)
        return a if b == 'transparent' else mix(a, b, 1 - pct)
    for _ in range(4):                                         # color-mix تودرتو
        v2 = _MIX.sub(_mix_sub, v)
        if v2 == v:
            break
        v = v2
    out = []
    for m in _RGBA.finditer(v):
        r, g, b = (min(255, int(x)) for x in m.group(1, 2, 3))
        alpha = float(m.group(4)) if m.group(4) is not None else 1.0
        if alpha <= 0.05:
            continue                                           # تقریباً شفاف (مثلِ درخششِ محو) ⇒ ایستگاه نیست
        out.append(mix(backdrop, '#%02x%02x%02x' % (r, g, b), min(1.0, alpha * boost)))
    v = _RGBA.sub(' ', v)
    out = [m.group(0) for m in _HEX.finditer(v)] + out
    return list(dict.fromkeys(out))


def pick_fg(declared: str, stops: list[str]) -> str:
    """متنی که روی همهٔ ایستگاه‌ها ≥ SURFACE_MIN بدهد: اول همان که سبک نوشته، بعد سفید، بعد تقریباً مشکی؛ هیچ‌کدام نشد ⇒ بهترین (بیشینهٔ کمینه)."""
    if not stops:
        return declared
    cands = []
    if _HEX.fullmatch(declared or ''):
        cands.append(_full(declared))
    cands += ['#ffffff', DARK_INK]
    best, best_min = (_full(declared) if _HEX.fullmatch(declared or '') else '#ffffff'), -1.0
    for cnd in cands:
        mn = min(contrast(cnd, s) for s in stops)
        if mn >= SURFACE_MIN:
            return cnd
        if mn > best_min:
            best, best_min = cnd, mn
    return best


def _scrim(declared: str, stops: list[str]):
    """هیچ متنی ≥ SURFACE_MIN نمی‌دهد ⇒ کمترین «پرده» (لایهٔ رنگیِ نیمه‌شفاف روی گرادیان) که یکی از دو متنِ روشن/تیره را خوانا کند. ⇒ (fg, scrim_hex, alpha) یا None."""
    light = _full(declared) if _HEX.fullmatch(declared or '') and contrast(declared, '#000000') > 7 else '#ffffff'
    best = None
    for fg, scr in ((light, '#000000'), (DARK_INK, '#ffffff')):
        for alpha in (0.08, 0.16, 0.24, 0.32, 0.40, 0.48, 0.56, 0.64):
            if min(contrast(fg, mix(s, scr, alpha)) for s in stops) >= SURFACE_MIN:
                if best is None or alpha < best[2]:
                    best = (fg, scr, alpha)
                break
    return best


def _eff_over(value: str, over: str, brand: str, backdrop: str):
    """زمینهٔ ``value`` (رنگِ ساده یا نیمه‌شفاف) وقتی روی رنگِ ``over`` می‌نشیند ⇒ hex، یا None اگر رنگی در آن نیست / به متنِ جاری وابسته است."""
    v = str(value or '').strip()
    if not v or 'currentcolor' in v.lower() or v in ('none', 'transparent'):
        return None
    v = v.replace('var(--brand)', brand)
    m = _RGBA.search(v)
    if m:
        r, g, b = (min(255, int(x)) for x in m.group(1, 2, 3))
        alpha = float(m.group(4)) if m.group(4) is not None else 1.0
        return mix(over, '#%02x%02x%02x' % (r, g, b), min(1.0, alpha))
    m = _MIX.search(_HEX.sub(lambda x: _full(x.group(0)), v))
    if m:
        a, pct, b2 = m.group(1), float(m.group(2)) / 100.0, m.group(3)
        return mix(over, a, pct) if b2 == 'transparent' else mix(a, b2, 1 - pct)
    m = _HEX.search(v)
    return _full(m.group(0)) if m else None


def _eyebrow_fg(t: dict, brand: str, backdrop: str):
    """نشانِ بالای هیرو (nb-eyebrow): پس‌زمینهٔ سبک (eb_bg) گاهی روشنِ مات است در حالی که متنِ هیرو سفید است (یا برعکس) ⇒ متنی که روی «پس‌زمینهٔ نشان روی همهٔ ایستگاه‌های هیرو» بخواند."""
    hero_stops = stops_of(t.get('hero_bg', ''), brand, backdrop, boost=1.7) or [backdrop]
    effs = [e for e in (_eff_over(t.get('eb_bg', ''), s, brand, backdrop) for s in hero_stops) if e]
    if not effs:
        return None                                            # به متنِ جاری وابسته (currentColor) ⇒ همان رنگِ هیرو
    fg = t.get('hero_fg', '')
    declared = _full(fg) if _HEX.fullmatch(fg or '') else '#ffffff'
    for cnd in (declared, '#ffffff', DARK_INK):
        if min(contrast(cnd, e) for e in effs) >= SURFACE_MIN:
            return cnd
    return max((declared, '#ffffff', DARK_INK), key=lambda c: min(contrast(c, e) for e in effs))


def guard_surface_fg(tokens: dict, brand: str, backdrop: str = '#ffffff', hero_variant: str = '') -> dict:
    """توکن‌های سبک ⇒ نسخهٔ نگهبانی‌شده: hero_fg روی hero_bg و cta_fg روی cta_bg. اول متنِ سفید/تیره‌ای که روی همهٔ ایستگاه‌ها بخواند؛ نشد ⇒ یک «پردهٔ» ملایم
    روی گرادیان (hero_bg/cta_bg همان گرادیان با یک لایهٔ نیمه‌شفاف در بالا) تا متنِ سبک بخواند."""
    t = dict(tokens)
    for bg_key, fg_key in (('hero_bg', 'hero_fg'), ('cta_bg', 'cta_fg')):
        value = t.get(bg_key, '')
        stops = stops_of(value, brand, backdrop, boost=1.7)      # تودرتوییِ درخشش‌های نیمه‌شفاف رنگ را روشن‌تر از تک‌تک ایستگاه‌ها می‌کند
        if bg_key == 'hero_bg' and hero_variant == 'framed':       # چیدمانِ «قابِ شیشه‌ای»: لایهٔ سفیدِ ۱۴٪ پشتِ متن؛ زمینهٔ واقعیِ متن روشن‌تر از ایستگاه‌هاست
            stops = [mix(s, '#ffffff', 0.18) for s in stops]
        fg = t.get(fg_key, '')
        if not stops or not (_HEX.fullmatch(fg or '') or fg.startswith('var(--brand-ink')):
            continue
        declared = _full(fg) if _HEX.fullmatch(fg or '') else '#ffffff'
        new = pick_fg(declared, stops)
        if min(contrast(new, s) for s in stops) >= SURFACE_MIN:
            if new != declared:
                t[fg_key] = new
            continue
        sc = _scrim(declared, stops)
        if sc is not None:
            fg2, scr, alpha = sc
            r, g, b = h2r(scr)
            layer = 'linear-gradient(rgba(%d,%d,%d,%s),rgba(%d,%d,%d,%s))' % (r, g, b, ('%.2f' % alpha).rstrip('0'), r, g, b, ('%.2f' % alpha).rstrip('0'))
            t[bg_key] = layer + ',' + value
            t[fg_key] = fg2
        else:
            t[fg_key] = new                                    # بهترین موجود (بیشینهٔ کمینه)
    eb = _eyebrow_fg(t, brand, backdrop)
    if eb:
        t['eb_fg'] = eb
    return t


def apply_to_styles(styles: dict, tokens_of=None) -> None:
    """همهٔ سبک‌ها (جای‌به‌جا): پالتِ بااحتیاط، با در نظر گرفتنِ زمینهٔ صفحه و کارتِ خودِ سبک. فقط یک بار هنگامِ بارگذاری."""
    for key, st in styles.items():
        extra = []
        if tokens_of is not None:
            try:
                toks = tokens_of(key)
                c = st['theme']['colors']
                for tk in ('page_bg', 'card_bg'):
                    extra += stops_of(toks.get(tk, ''), c['primary'], c['bg'])
            except (KeyError, ValueError, IndexError):
                extra = []
        st['theme']['colors'] = harden_palette(st['theme']['colors'], extra)
