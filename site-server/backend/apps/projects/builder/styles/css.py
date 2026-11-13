# -*- coding: utf-8 -*-
"""لایهٔ CSSِ یک سبکِ طراحی: توکن‌ها ⇒ متغیرهای `--st-*` ⇒ قاعده‌هایی که کلاس‌های `nb-*` را به آن‌ها وصل می‌کنند.

⚠ اصلِ سازگاری: این لایه فقط وقتی به blocks.css اضافه می‌شود که پوسته کلیدِ `style` داشته باشد؛ پوسته‌ای که سبک ندارد
(همهٔ پروژه‌های فعلی) همان CSSِ قبلی را بایت‌به‌بایت می‌گیرد.
"""
import re

from .data import STYLES

# مقدارِ پیش‌فرضِ هر توکن = همان ظاهرِ پایهٔ بلوک‌ها؛ هر سبک فقط چیزهایی را که فرق دارد می‌دهد
DEFAULTS = {
    'page_bg': 'var(--bg)', 'page_att': 'scroll',
    'sec_py': 'clamp(44px,7vw,84px)', 'gap': '22px',
    'head_w': '800', 'head_ls': '-.01em', 'head_tt': 'none',
    'card_bg': 'var(--card)', 'card_bd': '1px solid var(--line)', 'card_sh': '0 1px 2px rgba(0,0,0,.03),0 12px 28px -22px rgba(0,0,0,.25)',
    'card_r': 'var(--r,16px)', 'bf': 'none', 'hov': 'translateY(-3px)', 'hov_sh': '0 18px 40px -22px rgba(0,0,0,.35)',
    'mo': 'transform .2s ease,box-shadow .2s ease',
    'hl_bd': '2px solid var(--brand)', 'hl_sh': '0 24px 50px -28px color-mix(in srgb,var(--brand) 70%,transparent)',
    'btn_bw': '1.5px', 'btn_sh': '0 10px 22px -12px var(--brand)', 'btn_bc': 'transparent', 'btn_hov': 'translateY(-1px)',
    'btn_filter': 'brightness(1.06)', 'btn_mo': 'filter .15s,transform .15s,background .15s,box-shadow .15s',
    'hero_bg': 'linear-gradient(135deg,var(--brand),color-mix(in srgb,var(--brand) 55%,#0f172a))', 'hero_fg': 'var(--brand-ink,#fff)',
    'hero_btn_bg': 'var(--brand-ink,#fff)', 'hero_btn_fg': 'var(--brand)',
    'cta_bg': 'linear-gradient(135deg,var(--brand),color-mix(in srgb,var(--brand) 60%,#0f172a))', 'cta_fg': 'var(--brand-ink,#fff)',
    'cta_bd': '0 solid transparent', 'cta_sh': 'none', 'cta_r': 'calc(var(--r,16px) + 8px)',
    'in_bg': 'var(--bg)', 'in_bd': '1px solid var(--line)', 'in_r': 'calc(var(--r,16px) - 6px)', 'in_sh': 'none',
    'hd_bg': 'var(--card)', 'hd_bd': '1px solid var(--line)', 'hd_bf': 'none',
    'ic_bg': 'color-mix(in srgb,var(--brand) 13%,transparent)', 'ic_fg': 'var(--brand)', 'ic_r': '14px',
    'eb_bg': 'color-mix(in srgb,currentColor 15%,transparent)', 'eb_r': '999px',
}

CORE = r"""
body{background:var(--st-page-bg);background-attachment:var(--st-page-att)}
.nb-section{padding-block:var(--st-sec-py)}
.nb-h,.nb-title,.nb-hero-title,.nb-detail-title,.nb-plan-name,.nb-feature-title,.nb-card-title,.nb-brand{font-weight:var(--st-head-w);letter-spacing:var(--st-head-ls);text-transform:var(--st-head-tt)}
.nb-feature,.nb-plan,.nb-quote,.nb-faq-item,.nb-card,.nb-form{background:var(--st-card-bg);border:var(--st-card-bd);border-radius:var(--st-card-r);box-shadow:var(--st-card-sh);-webkit-backdrop-filter:var(--st-bf);backdrop-filter:var(--st-bf);transition:var(--st-mo)}
.nb-feature:hover,.nb-card:hover,.nb-plan:hover{transform:var(--st-hov);box-shadow:var(--st-hov-sh)}
.nb-plan.is-featured{border:var(--st-hl-bd);box-shadow:var(--st-hl-sh);transform:translateY(-6px)}
.nb-grid,.nb-cards{gap:var(--st-gap)}
.nb-feature-icon{background:var(--st-ic-bg);color:var(--st-ic-fg);border-radius:var(--st-ic-r)}
.nb-eyebrow{background:var(--st-eb-bg);border-radius:var(--st-eb-r)}
.nb-btn{border-width:var(--st-btn-bw);transition:var(--st-btn-mo)}
.nb-btn:hover{transform:var(--st-btn-hov);filter:var(--st-btn-filter)}
.nb-btn.is-filled{box-shadow:var(--st-btn-sh);border-color:var(--st-btn-bc)}
.nb-btn.is-outline{border-width:var(--st-btn-bw)}
.nb-hero{background:var(--st-hero-bg);color:var(--st-hero-fg)}
.nb-hero .nb-btn.is-filled{background:var(--st-hero-btn-bg);color:var(--st-hero-btn-fg)}
.nb-cta-box{background:var(--st-cta-bg);color:var(--st-cta-fg);border:var(--st-cta-bd);box-shadow:var(--st-cta-sh);border-radius:var(--st-cta-r)}
.nb-form input:not([type=hidden]),.nb-form textarea{background:var(--st-in-bg);border:var(--st-in-bd);border-radius:var(--st-in-r);box-shadow:var(--st-in-sh)}
.nb-header{background:var(--st-hd-bg);border-bottom:var(--st-hd-bd);-webkit-backdrop-filter:var(--st-hd-bf);backdrop-filter:var(--st-hd-bf)}
@media (prefers-reduced-motion:reduce){.nb-feature,.nb-card,.nb-plan,.nb-btn{transition:none!important}.nb-feature:hover,.nb-card:hover,.nb-plan:hover,.nb-btn:hover{transform:none!important}}
""".strip()


def tokens_of(key):
    """توکن‌های کاملِ یک سبک (پیش‌فرض + بازنویسیِ سبک)."""
    out = dict(DEFAULTS)
    out.update(STYLES[key].get('tokens', {}))
    return out


def rebrand_text(text, old_hex):
    """«رنگِ اصلیِ برندم همان بماند»: هر جای سبک که رنگِ اصلیِ خودش را نوشته (hex یا rgba) به var(--brand) برمی‌گردد؛ گرادیان‌ها و سایه‌های رنگی هم با برند می‌شوند."""
    if not text or not old_hex:
        return text
    h = old_hex.lstrip('#').lower()
    rgb = tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))

    def rgba(m):
        if (int(m.group(1)), int(m.group(2)), int(m.group(3))) == rgb:
            return 'color-mix(in srgb,var(--brand) %d%%,transparent)' % round(float(m.group(4)) * 100)
        return m.group(0)
    out = re.sub(r'rgba\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*([\d.]+)\s*\)', rgba, text)
    return re.sub(r'#%s\b' % h, 'var(--brand)', out, flags=re.I)


def root_vars(key, rebrand=False):
    toks = tokens_of(key)
    if rebrand:
        primary = STYLES[key]['theme']['colors']['primary']
        toks = {k: rebrand_text(v, primary) for k, v in toks.items()}
    return ':root{%s}' % ';'.join('--st-%s:%s' % (k.replace('_', '-'), v) for k, v in toks.items())


def style_css(key, rebrand=False):
    """CSSِ کاملِ سبک؛ برای کلیدِ ناشناخته رشتهٔ خالی. rebrand: رنگِ اصلیِ سبک جایش را به var(--brand) بدهد."""
    if key not in STYLES:
        return ''
    parts = ['/* سبکِ طراحی: %s (%s) */' % (STYLES[key]['label'], key), root_vars(key, rebrand), CORE]
    extra = (STYLES[key].get('extra') or '').strip()
    if extra:
        parts.append(rebrand_text(extra, STYLES[key]['theme']['colors']['primary']) if rebrand else extra)
    return '\n'.join(parts)


__all__ = ['style_css', 'tokens_of', 'root_vars', 'rebrand_text', 'DEFAULTS', 'CORE']
