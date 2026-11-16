# -*- coding: utf-8 -*-
"""هستهٔ ساختِ سبک‌های خودکار از دادهٔ ui-ux-pro-max: ابزارِ رنگ (تباینِ WCAG) و «الگوهای» ظاهری (archetype).

هر سبک = یک ردیفِ دادهٔ ui-ux-pro-max (نام، کلیدواژه، رنگ‌های پیشنهادی، ``rtl_level``) + یک «الگو» از این‌جا (شکلِ کارت، دکمه، سایه، پس‌زمینه…) + یک رنگِ اصلی.
خروجی دقیقاً همان ساختاری است که ``styles/data.py`` برای ۱۴ سبکِ دست‌ساز دارد (theme، tokens، sections، extra)؛ پس همهٔ ابزارها (اعمال، برگشت، «رنگِ برندم بماند»، AI، پیش‌نمایش) بی‌تغییر کار می‌کنند.

اصل‌ها (هر کدام در آزمون سنجیده می‌شود):
* رنگ‌ها را تباینِ WCAG می‌سازد، نه سلیقه: متن/زمینه ≥ ۷، متنِ دوم و کم‌رنگ ≥ ۴٫۵، متنِ دکمه/رنگِ اصلی ≥ ۴٫۵، رنگِ اصلی روی زمینه ≥ ۴٫۵، و متنِ هیرو/دعوت روی همهٔ ایستگاه‌های گرادیانش ≥ ۴٫۵.
* راست‌به‌چپ: هیچ ویژگیِ فیزیکی (left/right) در CSS نیست؛ فقط start/end و ویژگی‌های منطقی. فاصلهٔ حروف (letter-spacing) همیشه صفر است (حروفِ فارسی نباید از هم باز شوند) و text-transform نداریم.
* بی‌@import و بی‌url()؛ فقط CSSِ ساده با آکولادِ متوازن.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


# ───────────────────────────── رنگ

def h2r(h: str) -> tuple[int, int, int]:
    h = h.lstrip('#')
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def r2h(c) -> str:
    return '#%02x%02x%02x' % tuple(max(0, min(255, int(round(x)))) for x in c)


def mix(a: str, b: str, t: float) -> str:
    """t=0 ⇒ a ؛ t=1 ⇒ b."""
    ra, rb = h2r(a), h2r(b)
    return r2h([ra[i] * (1 - t) + rb[i] * t for i in range(3)])


def lum(h: str) -> float:
    def ch(v):
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = h2r(h)
    return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)


def contrast(a: str, b: str) -> float:
    la, lb = lum(a), lum(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def ensure(fg: str, bgs, ratio: float) -> str:
    """fg را (به سمتِ سیاه یا سفید، هرکدام تباینِ بیشتری می‌دهد) تا وقتی با همهٔ زمینه‌ها ≥ ratio شود جابه‌جا می‌کند؛ کمترین تغییرِ ممکن."""
    bgs = [bgs] if isinstance(bgs, str) else list(bgs)
    if min(contrast(fg, b) for b in bgs) >= ratio:
        return fg
    avg = sum(lum(b) for b in bgs) / len(bgs)
    target = '#000000' if avg > 0.3 else '#ffffff'
    for i in range(1, 41):
        c = mix(fg, target, i / 40)
        if min(contrast(c, b) for b in bgs) >= ratio:
            return c
    return target


def on_color(h: str) -> str:
    """متنِ روی h: سفید یا تقریباً مشکی، هرکدام تباینِ بیشتری دارد."""
    dark, light = '#0b0d12', '#ffffff'
    return light if contrast(light, h) >= contrast(dark, h) else dark


def shade(h: str, t: float) -> str:
    return mix(h, '#000000', t)


def tint(h: str, t: float) -> str:
    return mix(h, '#ffffff', t)


def rgba(h: str, a: float) -> str:
    r, g, b = h2r(h)
    return 'rgba(%d,%d,%d,%s)' % (r, g, b, ('%.2f' % a).rstrip('0').rstrip('.') or '0')


def stop_for(color: str, fg: str, ratio: float = 4.6) -> str:
    """رنگِ ایستگاهِ گرادیان که با متنِ fg خوانا بماند (از fg دور می‌شود)."""
    if contrast(color, fg) >= ratio:
        return color
    target = '#000000' if lum(fg) > 0.4 else '#ffffff'
    for i in range(1, 41):
        c = mix(color, target, i / 40)
        if contrast(c, fg) >= ratio:
            return c
    return target


@dataclass
class Pal:
    """پالتِ یک سبک: همهٔ رنگ‌ها hex و تباینشان تضمین‌شده."""
    primary: str
    on_primary: str
    text: str
    text2: str
    muted: str
    line: str
    bg: str
    surface: str
    acc2: str
    dark: bool

    def colors(self) -> dict:
        return {'primary': self.primary, 'on_primary': self.on_primary, 'text': self.text, 'text2': self.text2, 'muted': self.muted,
                'line': self.line, 'bg': self.bg, 'surface': self.surface}


def make_palette(acc: str, *, dark: bool = False, bg: str | None = None, surface: str | None = None, text: str | None = None, tone: str | None = None,
                 acc2: str | None = None, line: str | None = None) -> Pal:
    tone = tone or acc
    if dark:
        bg = bg or mix('#090b11', tone, 0.07)
        surface = surface or mix(bg, '#ffffff', 0.06)
        text = text or '#eef1f8'
    else:
        bg = bg or mix('#ffffff', tone, 0.05)
        surface = surface or '#ffffff'
        text = text or mix('#0d1117', tone, 0.10)
    both = [bg, surface]
    text = ensure(text, both, 7.3)
    text2 = ensure(mix(text, bg, 0.22), both, 5.0)
    muted = ensure(mix(text, bg, 0.42), both, 4.7)
    line = line or mix(bg, text, 0.16 if dark else 0.14)
    primary = ensure(acc, both, 4.7)
    on = on_color(primary)
    if contrast(on, primary) < 4.6:                  # رنگِ میانه که نه سفید و نه مشکی خوب می‌خواندش: رنگِ اصلی را کمی عوض کن
        primary = ensure(primary, [on], 4.7)
    low = lambda c: c.lower()                        # noqa: E731 - تمِ سایت همیشه hex ِ کوچک نگه می‌دارد
    return Pal(primary=low(primary), on_primary=low(on), text=low(text), text2=low(text2), muted=low(muted), line=low(line), bg=low(bg), surface=low(surface),
               acc2=low(acc2 or tint(primary, .35)), dark=dark)


# ───────────────────────────── ابزارِ توکن

def hero_pair(P: Pal, a: str | None = None, b: str | None = None, angle: int = 135, solid: bool = False):
    """⇒ (hero_bg, hero_fg, hero_btn_bg, hero_btn_fg): متنِ هیرو روی همهٔ ایستگاه‌ها خوانا؛ دکمهٔ هیرو با متنش جور."""
    a = a or P.primary
    fg = on_color(a)
    sa = stop_for(a, fg)
    if solid:
        bg = sa
    else:
        sb = stop_for(b or (shade(a, .35) if fg == '#ffffff' else tint(a, .35)), fg)
        bg = 'linear-gradient(%ddeg,%s,%s)' % (angle, sa, sb)
    btn_bg = fg
    btn_fg = ensure(sa, [btn_bg], 4.7)
    return bg, fg, btn_bg, btn_fg


def fill(css: str, P: Pal) -> str:
    """جایگزینیِ @acc@ … در قالبِ CSS."""
    rep = {'@acc@': P.primary, '@acc2@': P.acc2, '@bg@': P.bg, '@surf@': P.surface, '@text@': P.text, '@line@': P.line, '@on@': P.on_primary,
           '@muted@': P.muted}
    for k, v in rep.items():
        css = css.replace(k, v)
    return css


PHYS = re.compile(r'(?<![\w-])(?:margin|padding|border)-(?:left|right)\b|(?<![\w-])(?:left|right)\s*:|text-align\s*:\s*(?:left|right)|float\s*:\s*(?:left|right)|'
                  r'border-(?:top|bottom)-(?:left|right)-radius|translate[X]?\(\s*-?\d')
